from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Request, Response, Query
from typing import List, Dict, Any, Optional

from ..auth import get_current_user
from ..models import ScheduleRun, User
from ..schemas import (
    ResponseEnvelope,
    SensorCreate,
    SensorUpdate,
    SensorRead,
    SensorReadingCreate,
    SensorReadingRead,
    WeatherSnapshot,
    ScheduleBlockRead,
    ScheduleResponse,
    RecommendationRead,
    AlertConfigCreate,
    AlertConfigRead,
    DailySummaryRead,
    ZoneBreakdownRead,
    SensorStatsRead,
)
from ..services import optimizer as optimizer_service
from ..services import sensors as sensor_service
from ..services import weather as weather_service
from ..services import analytics as analytics_service
from .websocket_manager import manager

router = APIRouter()


def _serialize_schedule(run: ScheduleRun) -> ScheduleResponse:
    blocks = [
        ScheduleBlockRead(
            timestamp=block.timestamp,
            target_temp_c=block.target_temp_c,
            target_hvac_mode=block.target_hvac_mode,
            estimated_kwh=block.estimated_kwh,
            comfort_delta=block.comfort_delta,
        )
        for block in sorted(run.blocks, key=lambda b: b.timestamp)
    ]
    return ScheduleResponse(
        run_id=run.id,
        generated_at=run.generated_at,
        baseline_kwh=run.baseline_kwh,
        optimized_kwh=run.optimized_kwh,
        comfort_score=run.comfort_score,
        cost_score=run.cost_score,
        carbon_kg=getattr(run, "carbon_kg", None),
        carbon_saved_kg=getattr(run, "carbon_saved_kg", None),
        blocks=blocks,
    )


# ──────────────────────────────────────────────
# 1. System Health (public)
# ──────────────────────────────────────────────

@router.get("/health", response_model=ResponseEnvelope[Dict[str, str]])
def health_check():
    return {"data": {"status": "ok"}}


# ──────────────────────────────────────────────
# 2. Sensors Management
# ──────────────────────────────────────────────

@router.post("/sensors", response_model=ResponseEnvelope[SensorRead])
def create_sensor(payload: SensorCreate, _: User = Depends(get_current_user)):
    sensor = sensor_service.create_sensor(**payload.dict())
    return {"data": sensor}


@router.get("/sensors", response_model=ResponseEnvelope[List[SensorRead]])
def get_sensors(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100)
):
    sensors = sensor_service.list_sensors()
    paginated = sensors[skip: skip + limit]
    return {"data": paginated}


@router.put("/sensors/{sensor_id}", response_model=ResponseEnvelope[SensorRead])
def update_sensor(sensor_id: int, payload: SensorUpdate, _: User = Depends(get_current_user)):
    sensor = sensor_service.update_sensor(sensor_id, payload.name, payload.zone)
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found or has been soft-deleted")
    return {"data": sensor}


@router.delete("/sensors/{sensor_id}", response_model=ResponseEnvelope[Dict[str, Any]])
def delete_sensor(sensor_id: int, _: User = Depends(get_current_user)):
    success = sensor_service.soft_delete_sensor(sensor_id)
    if not success:
        raise HTTPException(status_code=404, detail="Sensor not found or already deleted")
    return {"data": {"sensor_id": sensor_id, "deleted": True}}


# ──────────────────────────────────────────────
# 3. Readings Ingestion
# ──────────────────────────────────────────────

@router.post("/sensors/{sensor_id}/readings", response_model=ResponseEnvelope[SensorReadingRead])
def post_reading(sensor_id: int, payload: SensorReadingCreate, _: User = Depends(get_current_user)):
    try:
        reading = sensor_service.add_reading(sensor_id, payload.value, payload.recorded_at)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"data": reading}


@router.get("/sensors/{sensor_id}/readings", response_model=ResponseEnvelope[List[SensorReadingRead]])
def get_readings(
    sensor_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000)
):
    readings = sensor_service.list_readings(sensor_id, limit=skip + limit)
    paginated = readings[skip: skip + limit]
    return {"data": paginated}


# ──────────────────────────────────────────────
# 4. Analytics & Stats (public reads)
# ──────────────────────────────────────────────

@router.get("/analytics/daily-summary", response_model=ResponseEnvelope[List[DailySummaryRead]])
def get_daily_summary():
    return {"data": analytics_service.get_daily_summary()}


@router.get("/analytics/zone-breakdown", response_model=ResponseEnvelope[List[ZoneBreakdownRead]])
def get_zone_breakdown():
    return {"data": analytics_service.get_zone_breakdown()}


@router.get("/sensors/{sensor_id}/stats", response_model=ResponseEnvelope[SensorStatsRead])
def get_sensor_stats(sensor_id: int):
    try:
        stats = analytics_service.get_sensor_stats(sensor_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"data": stats}


@router.get("/analytics/zone-occupancy", response_model=ResponseEnvelope[Dict[str, Any]])
def get_zone_occupancy():
    """Return latest average occupancy value per zone (for live dashboard dots)."""
    return {"data": analytics_service.get_zone_occupancy()}


@router.get("/analytics/temperature-history", response_model=ResponseEnvelope[List[Dict[str, Any]]])
def get_temperature_history(hours: int = Query(6, ge=1, le=48)):
    """Return per-zone temperature readings bucketed into 30-min slots for the last N hours."""
    return {"data": analytics_service.get_temperature_history(hours=hours)}



# ──────────────────────────────────────────────
# 5. Alert Configuration (protected write)
# ──────────────────────────────────────────────

@router.post("/alerts/config", response_model=ResponseEnvelope[AlertConfigRead])
def configure_alert(payload: AlertConfigCreate, _: User = Depends(get_current_user)):
    try:
        alert = sensor_service.configure_alert(
            sensor_id=payload.sensor_id,
            threshold_value=payload.threshold_value,
            operator=payload.operator,
            is_active=payload.is_active
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"data": alert}


# ──────────────────────────────────────────────
# 6. Schedules & Optimization
# ──────────────────────────────────────────────

@router.post("/optimizer/run", response_model=ResponseEnvelope[ScheduleResponse])
def trigger_optimizer(_: User = Depends(get_current_user)):
    try:
        run = optimizer_service.generate_schedule()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"data": _serialize_schedule(run)}


@router.get("/schedules/latest")
def get_latest_schedule(request: Request, response: Response):
    run = optimizer_service.latest_schedule()
    if not run:
        raise HTTPException(status_code=404, detail="No schedule computed yet")

    last_modified = run.generated_at.strftime("%a, %d %b %Y %H:%M:%S GMT")
    etag = f'W/"{hash(run.generated_at)}"'

    if_none_match = request.headers.get("if-none-match")
    if_modified_since = request.headers.get("if-modified-since")

    if if_none_match == etag or if_modified_since == last_modified:
        response.status_code = 304
        return None

    response.headers["Last-Modified"] = last_modified
    response.headers["ETag"] = etag

    serialized = _serialize_schedule(run)
    envelope = ResponseEnvelope(data=serialized)
    return envelope


@router.get("/schedules/history", response_model=ResponseEnvelope[List[ScheduleResponse]])
def get_schedule_history(limit: int = Query(10, ge=1, le=100)):
    runs = optimizer_service.schedule_history(limit=limit)
    serialized = [_serialize_schedule(run) for run in runs]
    return {"data": serialized}


# ──────────────────────────────────────────────
# 7. Insights (public read)
# ──────────────────────────────────────────────

@router.get("/insights/tips", response_model=ResponseEnvelope[List[RecommendationRead]])
def get_recommendations():
    return {"data": optimizer_service.latest_recommendations(limit=20)}


# ──────────────────────────────────────────────
# 8. External Integrations
# ──────────────────────────────────────────────

@router.post("/weather/refresh", response_model=ResponseEnvelope[List[WeatherSnapshot]])
async def refresh_weather(_: User = Depends(get_current_user)):
    forecasts = await weather_service.fetch_forecast()
    weather_service.persist_forecast(forecasts)
    snapshots = [
        WeatherSnapshot(
            timestamp=forecast.timestamp,
            temperature_c=forecast.temperature_c,
            humidity=forecast.humidity,
            solar_irradiance_wm2=forecast.solar_irradiance_wm2,
        )
        for forecast in forecasts[:12]
    ]
    return {"data": snapshots}


@router.get("/weather/current", response_model=ResponseEnvelope[List[WeatherSnapshot]])
def get_current_weather():
    """Return the latest 12 stored forecast snapshots for the frontend weather panel."""
    forecasts = weather_service.latest_forecasts(limit=12)
    snapshots = [
        WeatherSnapshot(
            timestamp=f.timestamp,
            temperature_c=f.temperature_c,
            humidity=f.humidity,
            solar_irradiance_wm2=f.solar_irradiance_wm2,
        )
        for f in forecasts
    ]
    return {"data": snapshots}


# ──────────────────────────────────────────────
# 9. Real-time Live Feed WebSockets
# ──────────────────────────────────────────────

@router.websocket("/ws/live-feed")
async def websocket_live_feed(websocket: WebSocket, room: str = Query("all")):
    await manager.connect(websocket, room)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, room)
