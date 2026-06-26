from datetime import datetime
from typing import List, Optional
import asyncio
import statistics
from sqlmodel import select

from ..database import session_scope
from ..models import Sensor, SensorReading, AlertConfig


def create_sensor(name: str, zone: str, kind: str, units: str) -> Sensor:
    sensor = Sensor(name=name, zone=zone, kind=kind, units=units, is_deleted=False)
    with session_scope() as session:
        session.add(sensor)
        session.flush()
        session.refresh(sensor)
        return sensor


def list_sensors() -> List[Sensor]:
    with session_scope() as session:
        statement = select(Sensor).where(Sensor.is_deleted == False).order_by(Sensor.zone, Sensor.name)
        return session.exec(statement).all()


def get_sensor(sensor_id: int) -> Optional[Sensor]:
    with session_scope() as session:
        sensor = session.get(Sensor, sensor_id)
        if sensor and not sensor.is_deleted:
            return sensor
        return None


def update_sensor(sensor_id: int, name: Optional[str] = None, zone: Optional[str] = None) -> Optional[Sensor]:
    with session_scope() as session:
        sensor = session.get(Sensor, sensor_id)
        if not sensor or sensor.is_deleted:
            return None
        if name is not None:
            sensor.name = name
        if zone is not None:
            sensor.zone = zone
        session.add(sensor)
        session.commit()
        session.refresh(sensor)
        return sensor


def soft_delete_sensor(sensor_id: int) -> bool:
    with session_scope() as session:
        sensor = session.get(Sensor, sensor_id)
        if not sensor or sensor.is_deleted:
            return False
        sensor.is_deleted = True
        session.add(sensor)
        session.commit()
        return True


def add_reading(sensor_id: int, value: float, recorded_at: datetime | None = None) -> SensorReading:
    recorded = recorded_at or datetime.utcnow()
    reading = SensorReading(sensor_id=sensor_id, value=value, recorded_at=recorded)
    
    with session_scope() as session:
        sensor = session.get(Sensor, sensor_id)
        if not sensor or sensor.is_deleted:
            raise ValueError(f"Sensor with id {sensor_id} does not exist or has been soft-deleted.")
        
        session.add(reading)
        session.commit()
        session.refresh(reading)

        # Calculate anomaly detection over the last 10 readings
        past_readings = list_readings(sensor_id, limit=10)
        is_anomaly = False
        if len(past_readings) >= 5:
            vals = [r.value for r in past_readings]
            mean_val = statistics.mean(vals)
            stdev_val = statistics.stdev(vals) if len(vals) > 1 else 0.0
            if stdev_val > 0.05:  # Ignore tiny variance noise
                z_score = abs(value - mean_val) / stdev_val
                if z_score > 2.0:
                    is_anomaly = True

        # 1. Broadcaster for live readings
        reading_payload = {
            "type": "reading",
            "data": {
                "id": reading.id,
                "sensor_id": sensor.id,
                "sensor_name": sensor.name,
                "sensor_kind": sensor.kind,
                "sensor_zone": sensor.zone,
                "value": reading.value,
                "recorded_at": reading.recorded_at.isoformat(),
                "is_anomaly": is_anomaly,
            }
        }
        
        # 2. Check alert configs
        statement = select(AlertConfig).where(
            AlertConfig.sensor_id == sensor_id,
            AlertConfig.is_active == True
        )
        alerts = session.exec(statement).all()
        triggered_alerts = []

        for alert in alerts:
            triggered = False
            op = alert.operator
            if op == ">" and value > alert.threshold_value:
                triggered = True
            elif op == "<" and value < alert.threshold_value:
                triggered = True
            elif op == ">=" and value >= alert.threshold_value:
                triggered = True
            elif op == "<=" and value <= alert.threshold_value:
                triggered = True

            if triggered:
                alert_payload = {
                    "type": "alert",
                    "data": {
                        "id": alert.id,
                        "sensor_id": sensor.id,
                        "sensor_name": sensor.name,
                        "value": value,
                        "threshold_value": alert.threshold_value,
                        "operator": alert.operator,
                        "timestamp": reading.recorded_at.isoformat(),
                    }
                }
                triggered_alerts.append(alert_payload)

        # Broadcast events asynchronously using event loop tasks
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                from ..api.websocket_manager import manager
                # Send reading to 'readings' room
                loop.create_task(manager.broadcast(reading_payload, "readings"))
                # Send all triggered alerts to 'alerts' room
                for alert_msg in triggered_alerts:
                    loop.create_task(manager.broadcast(alert_msg, "alerts"))
        except Exception:
            pass

        return reading


def list_readings(sensor_id: int, limit: int = 100) -> List[SensorReading]:
    with session_scope() as session:
        sensor = session.get(Sensor, sensor_id)
        if not sensor or sensor.is_deleted:
            return []
        statement = (
            select(SensorReading)
            .where(SensorReading.sensor_id == sensor_id)
            .order_by(SensorReading.recorded_at.desc())
            .limit(limit)
        )
        results = session.exec(statement).all()
        return list(reversed(results))


def configure_alert(sensor_id: int, threshold_value: float, operator: str = ">", is_active: bool = True) -> AlertConfig:
    with session_scope() as session:
        sensor = session.get(Sensor, sensor_id)
        if not sensor or sensor.is_deleted:
            raise ValueError("Sensor does not exist or has been soft-deleted.")
        
        # Deactivate any duplicate config
        existing_stmt = select(AlertConfig).where(
            AlertConfig.sensor_id == sensor_id,
            AlertConfig.operator == operator,
            AlertConfig.is_active == True
        )
        existing = session.exec(existing_stmt).all()
        for old_alert in existing:
            old_alert.is_active = False
            session.add(old_alert)

        alert = AlertConfig(
            sensor_id=sensor_id,
            threshold_value=threshold_value,
            operator=operator,
            is_active=is_active
        )
        session.add(alert)
        session.commit()
        session.refresh(alert)
        return alert
