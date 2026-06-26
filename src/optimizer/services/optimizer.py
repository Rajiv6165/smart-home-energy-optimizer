from __future__ import annotations

from datetime import datetime, timedelta
from statistics import mean
from typing import Iterable

from sqlmodel import select

from ..config import get_settings
from ..database import session_scope
from ..models import Recommendation, ScheduleBlock, ScheduleRun, Sensor, SensorReading, WeatherForecast

settings = get_settings()


def _recent_sensor_ids(session, kind: str) -> list[int]:
    statement = select(Sensor.id).where(Sensor.kind == kind)
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


def generate_schedule() -> ScheduleRun:
    with session_scope() as session:
        statement = select(WeatherForecast).where(WeatherForecast.timestamp >= datetime.utcnow()).order_by(WeatherForecast.timestamp).limit(30)
        forecasts = session.exec(statement).all()

        if not forecasts:
            raise ValueError("No weather data available. Fetch forecast first.")

        indoor_temp, occupancy = _compute_indoor_baseline(session)
        base_setpoint = (settings.comfort_min_c + settings.comfort_max_c) / 2

        blocks: list[ScheduleBlock] = []
        optimized_demand = 0.0
        comfort_penalties = []

        for forecast in forecasts:
            adjustment = 0.0
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

            target_temp = min(settings.comfort_max_c + 0.5, max(settings.comfort_min_c - 1, base_setpoint + adjustment))
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

        run = ScheduleRun(
            baseline_kwh=baseline,
            optimized_kwh=round(optimized_demand, 2),
            comfort_score=comfort_score,
            cost_score=cost_score,
            notes=f"Occupancy {occupancy:.0%}; indoor baseline {indoor_temp:.1f}C",
        )
        session.add(run)
        session.flush()

        for block in blocks:
            block.run_id = run.id
            session.add(block)

        session.commit()
        session.refresh(run)

        # Auto-generate recommendations for this run
        _create_recommendations(session, run)
        session.refresh(run)
        return run


def _create_recommendations(session, run: ScheduleRun) -> None:
    savings = round(run.baseline_kwh - run.optimized_kwh, 2)
    if savings > 0:
        session.add(
            Recommendation(
                title="Shift HVAC load to better hours",
                detail="The optimizer reduced setpoints during mild outdoor periods to save energy without leaving the comfort band.",
                estimated_savings_kwh=savings,
                confidence=0.75,
                category="schedule",
            )
        )
    if run.comfort_score < 0.8:
        session.add(
            Recommendation(
                title="Tighten comfort preferences",
                detail="Consider narrowing the comfort band or enabling occupancy-driven boosts for critical rooms.",
                estimated_savings_kwh=0.4,
                confidence=0.55,
                category="comfort",
            )
        )


def latest_schedule() -> ScheduleRun | None:
    with session_scope() as session:
        statement = select(ScheduleRun).order_by(ScheduleRun.generated_at.desc()).limit(1)
        run = session.exec(statement).first()
        if not run:
            return None
        run.blocks  # trigger lazy load if needed
        return run


def latest_recommendations(limit: int = 5) -> list[Recommendation]:
    with session_scope() as session:
        statement = select(Recommendation).order_by(Recommendation.created_at.desc()).limit(limit)
        return session.exec(statement).all()
