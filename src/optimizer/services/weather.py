from __future__ import annotations

from datetime import datetime
from typing import Iterable

import httpx
from sqlmodel import select

from ..config import get_settings
from ..database import session_scope
from ..models import WeatherForecast

settings = get_settings()


async def fetch_forecast() -> list[WeatherForecast]:
    params = {
        "latitude": settings.home_latitude,
        "longitude": settings.home_longitude,
        "hourly": "temperature_2m,relative_humidity_2m,direct_radiation",
        "forecast_days": 2,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
        response.raise_for_status()
        data = response.json()

    hours = data["hourly"]["time"]
    temps = data["hourly"]["temperature_2m"]
    humidity = data["hourly"]["relative_humidity_2m"]
    radiation = data["hourly"].get("direct_radiation", [0] * len(hours))

    forecasts: list[WeatherForecast] = []
    for ts, temp, hum, rad in zip(hours, temps, humidity, radiation):
        forecasts.append(
            WeatherForecast(
                timestamp=datetime.fromisoformat(ts),
                temperature_c=temp,
                humidity=hum,
                solar_irradiance_wm2=rad or 0.0,
            )
        )
    return forecasts


def persist_forecast(forecasts: Iterable[WeatherForecast]) -> list[WeatherForecast]:
    saved: list[WeatherForecast] = []
    with session_scope() as session:
        # Purge overlapping timestamps to keep storage lean
        timestamps = [f.timestamp for f in forecasts]
        if timestamps:
            statement = select(WeatherForecast).where(WeatherForecast.timestamp.in_(timestamps))
            existing = session.exec(statement).all()
            for record in existing:
                session.delete(record)

        for forecast in forecasts:
            session.add(forecast)
            saved.append(forecast)
    return saved


def latest_forecasts(limit: int = 24) -> list[WeatherForecast]:
    with session_scope() as session:
        statement = select(WeatherForecast).order_by(WeatherForecast.timestamp).limit(limit)
        return session.exec(statement).all()
