from fastapi import APIRouter, HTTPException

from ..models import ScheduleRun
from ..schemas import (
    RecommendationRead,
    ScheduleBlockRead,
    ScheduleResponse,
    SensorCreate,
    SensorRead,
    SensorReadingCreate,
    SensorReadingRead,
    WeatherSnapshot,
)
from ..services import optimizer as optimizer_service
from ..services import sensors as sensor_service
from ..services import weather as weather_service

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
        blocks=blocks,
    )


@router.get("/health")
def health_check():
    return {"status": "ok"}


@router.post("/sensors", response_model=SensorRead)
def create_sensor(payload: SensorCreate):
    sensor = sensor_service.create_sensor(**payload.dict())
    return sensor


@router.get("/sensors", response_model=list[SensorRead])
def get_sensors():
    return sensor_service.list_sensors()


@router.post("/sensors/{sensor_id}/readings", response_model=SensorReadingRead)
def post_reading(sensor_id: int, payload: SensorReadingCreate):
    reading = sensor_service.add_reading(sensor_id, payload.value, payload.recorded_at)
    return reading


@router.get("/sensors/{sensor_id}/readings", response_model=list[SensorReadingRead])
def get_readings(sensor_id: int, limit: int = 100):
    return sensor_service.list_readings(sensor_id, limit)


@router.post("/optimizer/run", response_model=ScheduleResponse)
def trigger_optimizer():
    try:
        run = optimizer_service.generate_schedule()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_schedule(run)


@router.get("/schedules/latest", response_model=ScheduleResponse)
def get_latest_schedule():
    run = optimizer_service.latest_schedule()
    if not run:
        raise HTTPException(status_code=404, detail="No schedule computed yet")
    return _serialize_schedule(run)


@router.get("/insights/tips", response_model=list[RecommendationRead])
def get_recommendations():
    return optimizer_service.latest_recommendations()


@router.post("/weather/refresh", response_model=list[WeatherSnapshot])
async def refresh_weather():
    forecasts = await weather_service.fetch_forecast()
    weather_service.persist_forecast(forecasts)
    return [
        WeatherSnapshot(
            timestamp=forecast.timestamp,
            temperature_c=forecast.temperature_c,
            humidity=forecast.humidity,
            solar_irradiance_wm2=forecast.solar_irradiance_wm2,
        )
        for forecast in forecasts[:12]
    ]
