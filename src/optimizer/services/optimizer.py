from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from statistics import mean, stdev
from typing import Iterable
import asyncio
from sqlmodel import select

from ..config import get_settings
from ..database import session_scope
from ..models import Recommendation, ScheduleBlock, ScheduleRun, Sensor, SensorReading, WeatherForecast

settings = get_settings()

# US average grid carbon intensity (kg CO2 per kWh)
_CARBON_KG_PER_KWH = 0.386


# ─────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────

def _recent_sensor_ids(session, kind: str) -> list[int]:
    statement = select(Sensor.id).where(Sensor.kind == kind).where(Sensor.is_deleted == False)
    return [row[0] if isinstance(row, tuple) else row for row in session.exec(statement).all()]


def _recent_readings(session, sensor_ids: Iterable[int], hours: int = 6) -> list[SensorReading]:
    if not sensor_ids:
        return []
    since = datetime.utcnow() - timedelta(hours=hours)
    statement = (
        select(SensorReading)
        .where(SensorReading.sensor_id.in_(sensor_ids))
        .where(SensorReading.recorded_at >= since)
        .order_by(SensorReading.recorded_at)
    )
    return session.exec(statement).all()


def _compute_indoor_baseline(session) -> tuple[float, float]:
    temp_ids = _recent_sensor_ids(session, "temperature")
    temps = [reading.value for reading in _recent_readings(session, temp_ids)]
    indoor_temp = mean(temps) if temps else 22.0

    occ_ids = _recent_sensor_ids(session, "occupancy")
    occ_vals = [reading.value for reading in _recent_readings(session, occ_ids)]
    occupancy = min(1.0, sum(occ_vals) / len(occ_vals)) if occ_vals else 0.7
    return indoor_temp, occupancy


def _baseline_kwh(forecasts: list[WeatherForecast], base_setpoint: float) -> float:
    demand = 0.0
    for forecast in forecasts:
        thermal_gap = abs(base_setpoint - forecast.temperature_c)
        demand += max(0.4, thermal_gap * 0.12)
    return round(demand, 2)


def _estimate_block_kwh(target_temp: float, forecast: WeatherForecast, occupancy: float) -> float:
    thermal_gap = abs(target_temp - forecast.temperature_c)
    solar_relief = max(0.1, 1 - (forecast.solar_irradiance_wm2 / 900))
    hvac_load = (thermal_gap * 0.1 + solar_relief * 0.2) * (0.8 + occupancy * 0.4)
    return round(max(0.2, hvac_load), 3)


def _comfort_delta(target_temp: float) -> float:
    mid = (settings.comfort_min_c + settings.comfort_max_c) / 2
    band = settings.comfort_max_c - settings.comfort_min_c
    return round((target_temp - mid) / (band / 2 or 1), 3)


def _data_confidence(session) -> float:
    """
    Calculate a data completeness confidence score (0–1).
    Based on number of sensor readings in the past 24h vs expected.
    """
    since = datetime.utcnow() - timedelta(hours=24)
    statement = (
        select(SensorReading)
        .where(SensorReading.recorded_at >= since)
    )
    count = len(session.exec(statement).all())
    # Expect at least 144 readings/day (one per sensor per 10 min), clamp to 1.0
    return round(min(1.0, count / 144), 2)


def _check_extreme_heat_ahead(forecasts: list[WeatherForecast], hours_ahead: int = 3) -> bool:
    """Return True if any forecast within the next N hours exceeds 32°C."""
    cutoff = datetime.utcnow() + timedelta(hours=hours_ahead)
    return any(f.temperature_c > 32.0 for f in forecasts if f.timestamp <= cutoff)


def _detect_high_usage_windows(session) -> list[int]:
    """
    Detect recurring high-usage hours from historical ScheduleBlock data.
    Groups by hour-of-day and returns the top 2 highest avg kWh hours.
    """
    statement = (
        select(ScheduleBlock)
        .order_by(ScheduleBlock.timestamp.desc())
        .limit(500)
    )
    blocks = session.exec(statement).all()
    if not blocks:
        return []

    hour_kwh: dict[int, list[float]] = defaultdict(list)
    for block in blocks:
        hour_kwh[block.timestamp.hour].append(block.estimated_kwh)

    avg_by_hour = {h: mean(vals) for h, vals in hour_kwh.items()}
    sorted_hours = sorted(avg_by_hour, key=avg_by_hour.get, reverse=True)
    return sorted_hours[:2]


def _detect_zone_deviations(session) -> list[tuple[str, float]]:
    """
    Detect zones where avg temperature consistently deviates > 1.5°C from the setpoint midpoint.
    Returns list of (zone_name, avg_deviation).
    """
    base_setpoint = (settings.comfort_min_c + settings.comfort_max_c) / 2
    since = datetime.utcnow() - timedelta(hours=24)

    statement = (
        select(SensorReading, Sensor)
        .join(Sensor)
        .where(Sensor.kind == "temperature")
        .where(Sensor.is_deleted == False)
        .where(SensorReading.recorded_at >= since)
    )
    results = session.exec(statement).all()

    zone_temps: dict[str, list[float]] = defaultdict(list)
    for reading, sensor in results:
        zone_temps[sensor.zone].append(reading.value)

    deviations = []
    for zone, temps in zone_temps.items():
        if temps:
            avg_temp = mean(temps)
            deviation = abs(avg_temp - base_setpoint)
            if deviation > 1.5:
                deviations.append((zone, round(deviation, 2)))
    return deviations


def _detect_unoccupied_hvac_waste(session) -> list[tuple[str, float]]:
    """
    Detect zones that had HVAC running while unoccupied.
    Returns list of (zone_name, estimated_wasted_kwh).
    """
    since = datetime.utcnow() - timedelta(hours=8)

    occ_stmt = (
        select(SensorReading, Sensor)
        .join(Sensor)
        .where(Sensor.kind == "occupancy")
        .where(Sensor.is_deleted == False)
        .where(SensorReading.recorded_at >= since)
    )
    occ_results = session.exec(occ_stmt).all()

    power_stmt = (
        select(SensorReading, Sensor)
        .join(Sensor)
        .where(Sensor.kind == "power")
        .where(Sensor.is_deleted == False)
        .where(Sensor.zone != "panel")
        .where(SensorReading.recorded_at >= since)
    )
    power_results = session.exec(power_stmt).all()

    zone_occ: dict[str, list[float]] = defaultdict(list)
    for reading, sensor in occ_results:
        zone_occ[sensor.zone].append(reading.value)

    zone_power: dict[str, list[float]] = defaultdict(list)
    for reading, sensor in power_results:
        zone_power[sensor.zone].append(reading.value)

    waste_zones = []
    for zone, occ_vals in zone_occ.items():
        avg_occ = mean(occ_vals) if occ_vals else 0
        if avg_occ < 0.1 and zone in zone_power:
            avg_power = mean(zone_power[zone])
            wasted_kwh = round(avg_power * 8, 2)  # 8 hours
            if wasted_kwh > 0.5:
                waste_zones.append((zone, wasted_kwh))
    return waste_zones


# ─────────────────────────────────────────────────────────────
# Main schedule generator
# ─────────────────────────────────────────────────────────────

def generate_schedule() -> ScheduleRun:
    with session_scope() as session:
        statement = (
            select(WeatherForecast)
            .where(WeatherForecast.timestamp >= datetime.utcnow())
            .order_by(WeatherForecast.timestamp)
            .limit(30)
        )
        forecasts = session.exec(statement).all()

        if not forecasts:
            raise ValueError("No weather data available. Fetch forecast first.")

        indoor_temp, occupancy = _compute_indoor_baseline(session)
        base_setpoint = (settings.comfort_min_c + settings.comfort_max_c) / 2

        # ── Predictive pre-cooling: if extreme heat ahead, pre-cool 1.5°C earlier
        extreme_heat_ahead = _check_extreme_heat_ahead(forecasts, hours_ahead=3)
        precool_offset = -1.5 if extreme_heat_ahead else 0.0

        blocks: list[ScheduleBlock] = []
        optimized_demand = 0.0
        comfort_penalties = []

        for forecast in forecasts:
            adjustment = precool_offset
            if forecast.temperature_c < settings.comfort_min_c:
                adjustment += 0.6
            elif forecast.temperature_c > settings.comfort_max_c + 2:
                adjustment -= 0.8

            if occupancy < 0.35:
                adjustment -= 0.5
            elif occupancy > 0.8:
                adjustment += 0.3

            if forecast.solar_irradiance_wm2 > 500:
                adjustment -= 0.3

            target_temp = min(
                settings.comfort_max_c + 0.5,
                max(settings.comfort_min_c - 1, base_setpoint + adjustment)
            )
            estimated_kwh = _estimate_block_kwh(target_temp, forecast, occupancy)
            comfort_delta = _comfort_delta(target_temp)
            comfort_penalties.append(abs(comfort_delta))
            optimized_demand += estimated_kwh

            blocks.append(
                ScheduleBlock(
                    timestamp=forecast.timestamp,
                    target_temp_c=round(target_temp, 2),
                    target_hvac_mode="heat" if target_temp > indoor_temp else "cool",
                    estimated_kwh=estimated_kwh,
                    comfort_delta=comfort_delta,
                )
            )

        baseline = _baseline_kwh(forecasts, base_setpoint)
        comfort_score = round(max(0.0, 1 - (sum(comfort_penalties) / len(blocks))), 3)
        cost_score = round(min(1.0, max(0.0, baseline - optimized_demand) / max(1.0, baseline)), 3)

        # ── Carbon footprint
        optimized_kwh_total = round(optimized_demand, 2)
        carbon_kg = round(optimized_kwh_total * _CARBON_KG_PER_KWH, 3)
        carbon_saved_kg = round((baseline - optimized_kwh_total) * _CARBON_KG_PER_KWH, 3)

        run = ScheduleRun(
            baseline_kwh=baseline,
            optimized_kwh=optimized_kwh_total,
            comfort_score=comfort_score,
            cost_score=cost_score,
            carbon_kg=carbon_kg,
            carbon_saved_kg=max(0.0, carbon_saved_kg),
            notes=f"Occupancy {occupancy:.0%}; indoor baseline {indoor_temp:.1f}C"
                  + ("; pre-cool active (extreme heat forecast)" if extreme_heat_ahead else ""),
        )
        session.add(run)
        session.flush()

        for block in blocks:
            block.run_id = run.id
            session.add(block)

        session.commit()
        session.refresh(run)

        # ── Generate enhanced recommendations
        _create_recommendations(session, run, forecasts)
        session.refresh(run)

        run.blocks  # pre-load before session closes

        # ── Broadcast via WebSocket
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                from ..api.websocket_manager import manager
                schedule_payload = {
                    "type": "schedule",
                    "data": {
                        "run_id": run.id,
                        "generated_at": run.generated_at.isoformat(),
                        "baseline_kwh": run.baseline_kwh,
                        "optimized_kwh": run.optimized_kwh,
                        "comfort_score": run.comfort_score,
                        "cost_score": run.cost_score,
                        "carbon_kg": run.carbon_kg,
                        "carbon_saved_kg": run.carbon_saved_kg,
                        "notes": run.notes,
                        "blocks": [
                            {
                                "timestamp": block.timestamp.isoformat(),
                                "target_temp_c": block.target_temp_c,
                                "target_hvac_mode": block.target_hvac_mode,
                                "estimated_kwh": block.estimated_kwh,
                                "comfort_delta": block.comfort_delta,
                            }
                            for block in sorted(run.blocks, key=lambda b: b.timestamp)
                        ],
                    },
                }
                loop.create_task(manager.broadcast(schedule_payload, "schedules"))
        except Exception:
            pass

        return run


# ─────────────────────────────────────────────────────────────
# Enhanced recommendations engine
# ─────────────────────────────────────────────────────────────

def _create_recommendations(
    session, run: ScheduleRun, forecasts: list[WeatherForecast]
) -> None:
    savings = round(run.baseline_kwh - run.optimized_kwh, 2)
    confidence = _data_confidence(session)

    # 1. Schedule savings recommendation
    if savings > 0:
        session.add(
            Recommendation(
                title="Shift HVAC load to optimal hours",
                detail=(
                    f"The optimizer reduced setpoints during mild outdoor periods, "
                    f"saving an estimated {savings} kWh and {round(savings * _CARBON_KG_PER_KWH, 2)} kg CO₂ "
                    f"vs the unoptimized baseline."
                ),
                estimated_savings_kwh=savings,
                confidence=round(min(0.95, 0.6 + confidence * 0.35), 2),
                category="schedule",
            )
        )

    # 2. Comfort tightening
    if run.comfort_score < 0.8:
        session.add(
            Recommendation(
                title="Tighten comfort preferences",
                detail="Consider narrowing the comfort band or enabling occupancy-driven boosts for critical rooms.",
                estimated_savings_kwh=0.4,
                confidence=round(0.5 + confidence * 0.2, 2),
                category="comfort",
            )
        )

    # 3. Zone deviations
    deviating_zones = _detect_zone_deviations(session)
    for zone, deviation in deviating_zones:
        session.add(
            Recommendation(
                title=f"Zone '{zone}' consistently off-setpoint",
                detail=(
                    f"'{zone}' averaged {deviation}°C away from the target setpoint over the past 24h. "
                    f"Check sensor calibration or adjust zone-specific setpoints."
                ),
                estimated_savings_kwh=round(deviation * 0.15, 2),
                confidence=round(0.65 + confidence * 0.2, 2),
                category="comfort",
            )
        )

    # 4. Unoccupied HVAC waste
    waste_zones = _detect_unoccupied_hvac_waste(session)
    for zone, wasted_kwh in waste_zones:
        session.add(
            Recommendation(
                title=f"'{zone}' HVAC running while unoccupied",
                detail=(
                    f"Zone '{zone}' was unoccupied for the past 8 hours but HVAC kept running — "
                    f"potential {wasted_kwh} kWh wasted "
                    f"({round(wasted_kwh * _CARBON_KG_PER_KWH, 2)} kg CO₂). "
                    f"Enable auto-setback for unoccupied zones."
                ),
                estimated_savings_kwh=wasted_kwh,
                confidence=round(0.7 + confidence * 0.2, 2),
                category="schedule",
            )
        )

    # 5. Solar irradiance peak advisor
    peak_solar = max((f.solar_irradiance_wm2 for f in forecasts), default=0)
    peak_forecast = max(forecasts, key=lambda f: f.solar_irradiance_wm2, default=None)
    if peak_solar > 600 and peak_forecast:
        peak_time = peak_forecast.timestamp.strftime("%I %p")
        session.add(
            Recommendation(
                title=f"Solar irradiance peak at {peak_time} — reduce heating",
                detail=(
                    f"Forecast shows solar irradiance of {int(peak_solar)} W/m² at {peak_time}. "
                    f"Reducing heating setpoint by 1°C during this window could save ~0.3 kWh."
                ),
                estimated_savings_kwh=0.3,
                confidence=round(0.72 + confidence * 0.15, 2),
                category="general",
            )
        )

    # 6. Pattern-detected high-usage windows
    high_usage_hours = _detect_high_usage_windows(session)
    if high_usage_hours:
        hours_str = " and ".join(f"{h:02d}:00" for h in high_usage_hours)
        session.add(
            Recommendation(
                title=f"Recurring high-usage windows detected: {hours_str}",
                detail=(
                    f"Historical data shows consistently elevated HVAC load around {hours_str}. "
                    f"Pre-conditioning 30 minutes earlier could flatten the demand curve and reduce peak costs."
                ),
                estimated_savings_kwh=0.5,
                confidence=round(0.6 + confidence * 0.25, 2),
                category="schedule",
            )
        )

    session.commit()


# ─────────────────────────────────────────────────────────────
# Query helpers
# ─────────────────────────────────────────────────────────────

def latest_schedule() -> ScheduleRun | None:
    with session_scope() as session:
        statement = select(ScheduleRun).order_by(ScheduleRun.generated_at.desc()).limit(1)
        run = session.exec(statement).first()
        if not run:
            return None
        run.blocks
        return run


def latest_recommendations(limit: int = 10) -> list[Recommendation]:
    with session_scope() as session:
        statement = select(Recommendation).order_by(Recommendation.created_at.desc()).limit(limit)
        return session.exec(statement).all()


def schedule_history(limit: int = 10) -> list[ScheduleRun]:
    """Retrieve list of past schedule runs."""
    with session_scope() as session:
        statement = select(ScheduleRun).order_by(ScheduleRun.generated_at.desc()).limit(limit)
        runs = session.exec(statement).all()
        for run in runs:
            run.blocks
        return runs
