from datetime import datetime, timedelta
import statistics
from collections import defaultdict
from typing import List, Dict, Any
from sqlmodel import select

from ..database import session_scope
from ..models import Sensor, SensorReading


def get_daily_summary() -> List[Dict[str, Any]]:
    """Aggregate metrics per day: avg temp, occupancy rate, total panel kWh."""
    with session_scope() as session:
        statement = (
            select(SensorReading, Sensor)
            .join(Sensor)
            .where(Sensor.is_deleted == False)
            .order_by(SensorReading.recorded_at.desc())
        )
        results = session.exec(statement).all()

        data_by_day = defaultdict(lambda: defaultdict(list))
        for reading, sensor in results:
            day_str = reading.recorded_at.strftime("%Y-%m-%d")
            data_by_day[day_str][sensor.kind].append(reading.value)

            # Special tracking for whole home power panel to compute daily kWh
            if sensor.kind == "power" and sensor.zone == "panel":
                data_by_day[day_str]["panel_power"].append(reading.value)

        summaries = []
        for day_str in sorted(data_by_day.keys(), reverse=True):
            day_data = data_by_day[day_str]

            avg_temp = None
            if day_data["temperature"]:
                avg_temp = round(statistics.mean(day_data["temperature"]), 2)

            avg_occ = None
            if day_data["occupancy"]:
                avg_occ = round(statistics.mean(day_data["occupancy"]), 3)

            total_kwh = None
            if day_data["panel_power"]:
                # Daily kWh estimate = Avg kW * 24 hours
                avg_kw = statistics.mean(day_data["panel_power"])
                total_kwh = round(avg_kw * 24.0, 2)

            summaries.append({
                "date": day_str,
                "avg_temperature": avg_temp,
                "avg_occupancy": avg_occ,
                "total_kwh": total_kwh,
            })
        return summaries


def get_zone_breakdown() -> List[Dict[str, Any]]:
    """Compute per-zone energy usage breakdown in kWh and percentage."""
    with session_scope() as session:
        # Fetch power readings across active sensors
        statement = (
            select(SensorReading, Sensor)
            .join(Sensor)
            .where(Sensor.kind == "power")
            .where(Sensor.is_deleted == False)
        )
        results = session.exec(statement).all()

        # Group non-panel power readings by zone
        zone_powers = defaultdict(list)
        for reading, sensor in results:
            if sensor.zone != "panel":
                zone_powers[sensor.zone].append(reading.value)

        breakdown = []
        total_zone_kwh = 0.0
        for zone, values in zone_powers.items():
            avg_kw = statistics.mean(values) if values else 0.0
            # Daily usage proxy = Average kW * 24h
            kwh = round(avg_kw * 24.0, 2)
            total_zone_kwh += kwh
            breakdown.append({
                "zone": zone,
                "energy_usage_kwh": kwh,
                "percentage": 0.0,
            })

        for item in breakdown:
            if total_zone_kwh > 0:
                item["percentage"] = round((item["energy_usage_kwh"] / total_zone_kwh) * 100.0, 1)

        return sorted(breakdown, key=lambda x: x["energy_usage_kwh"], reverse=True)


def get_sensor_stats(sensor_id: int) -> Dict[str, Any]:
    """Calculate min/max/avg/trend for a sensor over the last 24 hours."""
    with session_scope() as session:
        sensor = session.get(Sensor, sensor_id)
        if not sensor or sensor.is_deleted:
            raise ValueError(f"Sensor with id {sensor_id} not found or has been soft-deleted.")

        since = datetime.utcnow() - timedelta(hours=24)
        statement = (
            select(SensorReading)
            .where(SensorReading.sensor_id == sensor_id)
            .where(SensorReading.recorded_at >= since)
            .order_by(SensorReading.recorded_at)
        )
        readings = session.exec(statement).all()

        if not readings:
            raise ValueError(f"No readings found for sensor {sensor_id} in the last 24 hours.")

        values = [r.value for r in readings]
        min_val = min(values)
        max_val = max(values)
        avg_val = round(statistics.mean(values), 2)

        # Trend analysis
        if len(readings) < 4:
            trend = "insufficient_data"
        else:
            midpoint = len(readings) // 2
            first_half = [r.value for r in readings[:midpoint]]
            second_half = [r.value for r in readings[midpoint:]]
            avg_first = statistics.mean(first_half)
            avg_second = statistics.mean(second_half)

            diff = avg_second - avg_first
            # Sensitivity offset threshold based on metric types
            threshold = 0.2 if sensor.kind == "temperature" else (0.1 if sensor.kind == "power" else 0.05)

            if diff > threshold:
                trend = "upward"
            elif diff < -threshold:
                trend = "downward"
            else:
                trend = "stable"

        return {
            "sensor_id": sensor_id,
            "min_value": min_val,
            "max_value": max_val,
            "avg_value": avg_val,
            "trend": trend,
        }


def get_zone_occupancy() -> Dict[str, Any]:
    """Return the most recent average occupancy reading per zone (last 2 hours)."""
    with session_scope() as session:
        since = datetime.utcnow() - timedelta(hours=2)
        statement = (
            select(SensorReading, Sensor)
            .join(Sensor)
            .where(Sensor.kind == "occupancy")
            .where(Sensor.is_deleted == False)
            .where(SensorReading.recorded_at >= since)
        )
        results = session.exec(statement).all()

        zone_vals: dict[str, list[float]] = defaultdict(list)
        for reading, sensor in results:
            zone_vals[sensor.zone].append(reading.value)

        return {
            zone: round(statistics.mean(vals), 2)
            for zone, vals in zone_vals.items()
            if vals
        }


def get_temperature_history(hours: int = 6) -> List[Dict[str, Any]]:
    """
    Return per-zone temperature readings bucketed into 30-min slots.
    Output: list of { time, zone1: val, zone2: val, ... } dicts for Recharts.
    """
    with session_scope() as session:
        since = datetime.utcnow() - timedelta(hours=hours)
        statement = (
            select(SensorReading, Sensor)
            .join(Sensor)
            .where(Sensor.kind == "temperature")
            .where(Sensor.is_deleted == False)
            .where(SensorReading.recorded_at >= since)
            .order_by(SensorReading.recorded_at)
        )
        results = session.exec(statement).all()

        # Collect all zones
        zones = list({sensor.zone for _, sensor in results})

        # Build 30-min buckets
        num_slots = hours * 2  # 30-min slots
        slot_data: dict[str, dict[str, list[float]]] = {}
        slot_labels: list[str] = []

        for i in range(num_slots):
            slot_time = since + timedelta(minutes=i * 30)
            label = slot_time.strftime("%H:%M")
            slot_labels.append(label)
            slot_data[label] = {z: [] for z in zones}

        # Fill buckets
        for reading, sensor in results:
            elapsed = (reading.recorded_at - since).total_seconds()
            slot_idx = int(elapsed // 1800)
            if 0 <= slot_idx < num_slots:
                label = slot_labels[slot_idx]
                slot_data[label][sensor.zone].append(reading.value)

        # Aggregate
        output = []
        for label in slot_labels:
            row: Dict[str, Any] = {"time": label}
            for zone in zones:
                vals = slot_data[label][zone]
                row[zone] = round(statistics.mean(vals), 2) if vals else None
            output.append(row)

        return output

