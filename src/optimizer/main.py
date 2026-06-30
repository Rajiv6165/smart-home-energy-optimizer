from __future__ import annotations

import asyncio
import logging
import os
from contextlib import AsyncExitStack
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .api.auth_routes import router as auth_router
from .config import get_settings
from .database import init_db
from .services import optimizer, weather, sensors
from .demo import bootstrap_demo

logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(
    title="Smart Home Energy Optimizer",
    version="2.0.0",
    description="Production-grade smart home HVAC optimizer with JWT auth, real-time WebSocket feeds, and AI-powered recommendations.",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # Tighten in production to your domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth_router, prefix="/auth")
app.include_router(router)


@app.get("/", include_in_schema=False)
def root_redirect():
    """Redirect root URL to the React dashboard."""
    return RedirectResponse(url="/frontend/")

# ── Static frontend ────────────────────────────────────────────────────────────
_frontend_dir = Path(__file__).parent.parent.parent / "frontend"
if _frontend_dir.exists():
    app.mount("/frontend", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
    logger.info("Frontend mounted at /frontend from %s", _frontend_dir)


# ── Background tasks ──────────────────────────────────────────────────────────

async def _periodic_weather() -> None:
    await asyncio.sleep(2)
    while True:
        try:
            forecasts = await weather.fetch_forecast()
            weather.persist_forecast(forecasts)
            logger.info("Weather refresh stored %s samples", len(forecasts))
        except Exception as exc:
            logger.warning("Weather refresh failed: %s", exc)
        await asyncio.sleep(settings.weather_refresh_minutes * 60)


async def _periodic_schedule() -> None:
    await asyncio.sleep(5)
    while True:
        try:
            optimizer.generate_schedule()
            logger.info("Schedule recomputed successfully in background")
        except ValueError as exc:
            logger.debug("Schedule skipped: %s", exc)
        except Exception as exc:
            logger.warning("Schedule job failed: %s", exc)
        await asyncio.sleep(settings.schedule_refresh_minutes * 60)


async def _periodic_alerts() -> None:
    await asyncio.sleep(10)
    while True:
        try:
            from .services.alerts import check_and_trigger_alerts
            check_and_trigger_alerts()
            logger.info("Alert checks executed in background")
        except Exception as exc:
            logger.warning("Alert checks job failed: %s", exc)
        await asyncio.sleep(60)


@app.on_event("startup")
async def startup_event() -> None:
    logging.basicConfig(level=logging.INFO)
    init_db()

    try:
        active_sensors = sensors.list_sensors()
        if not active_sensors:
            logger.info("No active sensors found in database. Seeding demo data...")
            bootstrap_demo()
        else:
            logger.info("Database already seeded with %s active sensors.", len(active_sensors))
    except Exception as exc:
        logger.error("Auto-seeding check failed: %s", exc)

    app.state._exit_stack = AsyncExitStack()
    app.state._tasks = [
        asyncio.create_task(_periodic_weather()),
        asyncio.create_task(_periodic_schedule()),
        asyncio.create_task(_periodic_alerts()),
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
