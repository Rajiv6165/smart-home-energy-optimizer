from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack

from fastapi import FastAPI

from .api.routes import router
from .config import get_settings
from .database import init_db
from .services import optimizer, weather

logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(title="Smart Home Energy Optimizer", version="0.1.0")
app.include_router(router)


async def _periodic_weather() -> None:
    while True:
        try:
            forecasts = await weather.fetch_forecast()
            weather.persist_forecast(forecasts)
            logger.info("Weather refresh stored %s samples", len(forecasts))
        except Exception as exc:  # pragma: no cover - guardrail
            logger.warning("Weather refresh failed: %s", exc)
        await asyncio.sleep(settings.weather_refresh_minutes * 60)


async def _periodic_schedule() -> None:
    while True:
        try:
            optimizer.generate_schedule()
            logger.info("Schedule recomputed")
        except ValueError as exc:
            logger.debug("Schedule skipped: %s", exc)
        except Exception as exc:  # pragma: no cover
            logger.warning("Schedule job failed: %s", exc)
        await asyncio.sleep(settings.schedule_refresh_minutes * 60)


@app.on_event("startup")
async def startup_event() -> None:
    logging.basicConfig(level=logging.INFO)
    init_db()
    app.state._exit_stack = AsyncExitStack()
    app.state._tasks = [
        asyncio.create_task(_periodic_weather()),
        asyncio.create_task(_periodic_schedule()),
    ]


@app.on_event("shutdown")
async def shutdown_event() -> None:
    tasks = getattr(app.state, "_tasks", [])
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    stack: AsyncExitStack | None = getattr(app.state, "_exit_stack", None)
    if stack:
        await stack.aclose()


__all__ = ["app"]
