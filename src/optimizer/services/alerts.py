from datetime import datetime, timedelta
import asyncio
from sqlmodel import select
from ..database import session_scope
from ..models import Alert, Sensor, SensorReading, ScheduleRun

def create_alert(session, title: str, message: str, severity: str, category: str, sensor_id: int = None, zone: str = None) -> Alert | None:
    """Helper to create and save a new alert if it does not violate de-duplication rules, and broadcast it."""
    # Check for unread alerts with the same category and sensor/zone
    stmt = select(Alert).where(Alert.category == category, Alert.severity == severity, Alert.is_read == False)
    if sensor_id is not None:
        stmt = stmt.where(Alert.sensor_id == sensor_id)
    if zone is not None:
        stmt = stmt.where(Alert.zone == zone)
    existing_unread = session.exec(stmt).first()
    if existing_unread:
        return None

    # Check for recently triggered alerts of the same category and sensor/zone (last 1 hour) to avoid spamming
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    stmt_recent = select(Alert).where(Alert.category == category, Alert.severity == severity, Alert.triggered_at >= one_hour_ago)
    if sensor_id is not None:
        stmt_recent = stmt_recent.where(Alert.sensor_id == sensor_id)
    if zone is not None:
        stmt_recent = stmt_recent.where(Alert.zone == zone)
    existing_recent = session.exec(stmt_recent).first()
    if existing_recent:
        return None

    alert = Alert(
        title=title,
        message=message,
        severity=severity,
        category=category,
        sensor_id=sensor_id,
        zone=zone,
        triggered_at=datetime.utcnow(),
        is_read=False
    )
    session.add(alert)
    session.commit()
    session.refresh(alert)

    # Broadcast via WebSocket
    try:
        from ..api.websocket_manager import manager
        payload = {
            "type": "new_alert",
            "data": {
                "id": alert.id,
                "title": alert.title,
                "message": alert.message,
                "severity": alert.severity,
                "sensor_id": alert.sensor_id,
                "zone": alert.zone,
                "triggered_at": alert.triggered_at.isoformat(),
                "is_read": alert.is_read,
                "category": alert.category
            },
            "timestamp": alert.triggered_at.isoformat()
        }
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(manager.broadcast(payload, "alerts"))
    except Exception:
        pass

    return alert

def check_and_trigger_alerts() -> None:
    """Evaluate smart home rules and trigger alerts as needed."""
    with session_scope() as session:
        # Get all active sensors
        stmt = select(Sensor).where(Sensor.is_deleted == False)
        sensors = session.exec(stmt).all()

        now = datetime.utcnow()

        # Rule 1 & 2: Temperature sensor warnings
        # Rule 3: Power sensor > 3.0 kW
        for sensor in sensors:
            reading_stmt = select(SensorReading).where(SensorReading.sensor_id == sensor.id).order_by(SensorReading.recorded_at.desc())
            latest_reading = session.exec(reading_stmt).first()

            if latest_reading:
                if sensor.kind == "temperature":
                    if latest_reading.value > 26.0:
                        create_alert(
                            session=session,
                            title="High Temperature Warning",
                            message=f"Sensor '{sensor.name}' in {sensor.zone} is reading {latest_reading.value}°C, which is above 26°C.",
                            severity="warning",
                            category="temperature",
                            sensor_id=sensor.id,
                            zone=sensor.zone
                        )
                    elif latest_reading.value < 18.0:
                        create_alert(
                            session=session,
                            title="Low Temperature Warning",
                            message=f"Sensor '{sensor.name}' in {sensor.zone} is reading {latest_reading.value}°C, which is below 18°C.",
                            severity="warning",
                            category="temperature",
                            sensor_id=sensor.id,
                            zone=sensor.zone
                        )
                elif sensor.kind == "power":
                    if latest_reading.value > 3.0:
                        create_alert(
                            session=session,
                            title="High Power Usage",
                            message=f"Sensor '{sensor.name}' in {sensor.zone} is drawing {latest_reading.value} kW, exceeding the 3.0 kW threshold.",
                            severity="critical",
                            category="power",
                            sensor_id=sensor.id,
                            zone=sensor.zone
                        )

        # Rule 4: Occupancy = 0 for 3+ hours but power > 1kW
        # Find all active occupancy sensors. Ensure they've been 0 for the last 3 hours.
        three_hours_ago = now - timedelta(hours=3)
        occupancy_sensors = [s for s in sensors if s.kind == "occupancy"]
        if occupancy_sensors:
            all_vacant = True
            has_occupancy_readings = False
            for os in occupancy_sensors:
                # Query readings in the last 3 hours
                occ_readings_stmt = select(SensorReading).where(
                    SensorReading.sensor_id == os.id,
                    SensorReading.recorded_at >= three_hours_ago
                )
                occ_readings = session.exec(occ_readings_stmt).all()
                if occ_readings:
                    has_occupancy_readings = True
                    # If any reading was non-zero, then occupancy was not 0 for 3+ hours
                    if any(r.value > 0 for r in occ_readings):
                        all_vacant = False
                        break
                else:
                    # If no readings in 3h, check the latest absolute reading. If it's occupied, not vacant
                    latest_occ_stmt = select(SensorReading).where(SensorReading.sensor_id == os.id).order_by(SensorReading.recorded_at.desc())
                    latest_occ = session.exec(latest_occ_stmt).first()
                    if latest_occ and latest_occ.value > 0:
                        all_vacant = False
                        break

            if all_vacant and has_occupancy_readings:
                # Check all power sensors to see if any draw is > 1 kW
                power_sensors = [s for s in sensors if s.kind == "power"]
                for ps in power_sensors:
                    pow_stmt = select(SensorReading).where(SensorReading.sensor_id == ps.id).order_by(SensorReading.recorded_at.desc())
                    latest_pow = session.exec(pow_stmt).first()
                    if latest_pow and latest_pow.value > 1.0:
                        create_alert(
                            session=session,
                            title="Unoccupied Energy Waste",
                            message=f"No occupancy detected for 3+ hours, but power draw for {ps.name} is high: {latest_pow.value} kW.",
                            severity="warning",
                            category="occupancy",
                            sensor_id=ps.id,
                            zone=ps.zone
                        )

        # Rule 5: No sensor readings for 2+ hours
        two_hours_ago = now - timedelta(hours=2)
        for sensor in sensors:
            latest_reading_stmt = select(SensorReading).where(SensorReading.sensor_id == sensor.id).order_by(SensorReading.recorded_at.desc())
            latest_r = session.exec(latest_reading_stmt).first()
            if not latest_r or latest_r.recorded_at < two_hours_ago:
                create_alert(
                    session=session,
                    title="Sensor Offline",
                    message=f"Sensor '{sensor.name}' in {sensor.zone} has not sent readings for 2+ hours.",
                    severity="info",
                    category="system",
                    sensor_id=sensor.id,
                    zone=sensor.zone
                )

        # Rule 6: Comfort score < 0.5
        latest_run_stmt = select(ScheduleRun).order_by(ScheduleRun.generated_at.desc())
        latest_run = session.exec(latest_run_stmt).first()
        if latest_run and latest_run.comfort_score < 0.5:
            create_alert(
                session=session,
                title="Low Comfort Level",
                message=f"The comfort score has dropped to {latest_run.comfort_score}, below the 0.5 comfort threshold.",
                severity="warning",
                category="system",
                sensor_id=None,
                zone=None
            )
