from datetime import datetime, timedelta
import statistics
from collections import defaultdict
from typing import List, Dict, Any
from sqlmodel import select

from ..database import session_scope
from ..models import Sensor, SensorReading, ScheduleRun


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


def get_weekly_summary() -> List[Dict[str, Any]]:
    """Aggregate metrics per day for the last 7 days: baseline vs optimized energy and scores."""
    with session_scope() as session:
        since = datetime.utcnow() - timedelta(days=7)
        # Select all runs in the last 7 days
        stmt = select(ScheduleRun).where(ScheduleRun.generated_at >= since).order_by(ScheduleRun.generated_at.desc())
        runs = session.exec(stmt).all()
        
        runs_by_day = {}
        for run in runs:
            day_str = run.generated_at.strftime("%Y-%m-%d")
            if day_str not in runs_by_day:
                runs_by_day[day_str] = run
                
        summary = []
        for day_str in sorted(runs_by_day.keys(), reverse=True):
            run = runs_by_day[day_str]
            savings = max(0.0, round(run.baseline_kwh - run.optimized_kwh, 2))
            summary.append({
                "date": day_str,
                "baseline_kwh": run.baseline_kwh,
                "optimized_kwh": run.optimized_kwh,
                "savings_kwh": savings,
                "carbon_kg": run.carbon_kg or 0.0,
                "comfort_score": run.comfort_score,
                "cost_score": run.cost_score,
            })
        return summary


def get_savings_total(tariff: float) -> Dict[str, Any]:
    """Compute all-time total kwh, co2, and cost savings across optimization runs."""
    with session_scope() as session:
        stmt = select(ScheduleRun).order_by(ScheduleRun.generated_at.desc())
        runs = session.exec(stmt).all()
        
        total_runs = len(runs)
        if total_runs == 0:
            return {
                "total_kwh_saved": 0.0,
                "total_carbon_saved_kg": 0.0,
                "total_cost_saved": 0.0,
                "total_runs": 0,
                "best_day": None,
                "worst_day": None
            }
            
        runs_by_day = defaultdict(list)
        for run in runs:
            day_str = run.generated_at.strftime("%Y-%m-%d")
            runs_by_day[day_str].append(run)
            
        daily_savings = {}
        total_kwh_saved = 0.0
        total_carbon_saved_kg = 0.0
        for day_str, day_runs in runs_by_day.items():
            latest_run = sorted(day_runs, key=lambda r: r.generated_at)[-1]
            savings = max(0.0, latest_run.baseline_kwh - latest_run.optimized_kwh)
            daily_savings[day_str] = savings
            total_kwh_saved += savings
            total_carbon_saved_kg += latest_run.carbon_saved_kg or 0.0
            
        best_day = max(daily_savings, key=daily_savings.get) if daily_savings else None
        worst_day = min(daily_savings, key=daily_savings.get) if daily_savings else None
        
        return {
            "total_kwh_saved": round(total_kwh_saved, 2),
            "total_carbon_saved_kg": round(total_carbon_saved_kg, 2),
            "total_cost_saved": round(total_kwh_saved * tariff, 2),
            "total_runs": total_runs,
            "best_day": best_day,
            "worst_day": worst_day
        }


def get_zone_comparison() -> List[Dict[str, Any]]:
    """Compare comfort, occupancy, power, and compute efficiency score per zone in the last 24h."""
    with session_scope() as session:
        stmt = select(Sensor).where(Sensor.is_deleted == False)
        sensors = session.exec(stmt).all()
        
        sensors_by_zone = defaultdict(list)
        for s in sensors:
            sensors_by_zone[s.zone].append(s)
            
        since = datetime.utcnow() - timedelta(hours=24)
        comparison = []
        
        for zone, zone_sensors in sensors_by_zone.items():
            if zone == "panel":
                continue
                
            sensor_ids = [s.id for s in zone_sensors]
            readings_stmt = select(SensorReading).where(SensorReading.sensor_id.in_(sensor_ids), SensorReading.recorded_at >= since)
            readings = session.exec(readings_stmt).all()
            
            kind_values = defaultdict(list)
            for r in readings:
                sensor = next(s for s in zone_sensors if s.id == r.sensor_id)
                kind_values[sensor.kind].append(r.value)
                
            avg_temp = round(statistics.mean(kind_values["temperature"]), 2) if kind_values["temperature"] else 21.0
            avg_occ = round(statistics.mean(kind_values["occupancy"]), 2) if kind_values["occupancy"] else 0.0
            
            power_readings = kind_values["power"]
            avg_kw = statistics.mean(power_readings) if power_readings else 0.0
            total_kwh = round(avg_kw * 24.0, 2)
            
            # Wasted energy when zone is unoccupied but draw is high
            waste = 0.0
            if avg_occ < 0.1 and total_kwh > 0.5:
                waste = min(50.0, total_kwh * 15.0)
            efficiency_score = round(max(30.0, min(99.0, 95.0 - waste)), 1)
            
            comparison.append({
                "zone": zone,
                "avg_temp": avg_temp,
                "avg_occupancy": avg_occ,
                "total_kwh": total_kwh,
                "sensor_count": len(zone_sensors),
                "efficiency_score": efficiency_score
            })
            
        return comparison


def get_sensor_history(sensor_id: int, hours: int = 24) -> List[Dict[str, Any]]:
    """Fetch raw values and timestamps for sparklines."""
    with session_scope() as session:
        since = datetime.utcnow() - timedelta(hours=hours)
        stmt = select(SensorReading).where(SensorReading.sensor_id == sensor_id, SensorReading.recorded_at >= since).order_by(SensorReading.recorded_at.asc())
        readings = session.exec(stmt).all()
        return [{"recorded_at": r.recorded_at, "value": r.value} for r in readings]


