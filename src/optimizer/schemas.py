from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class SensorCreate(BaseModel):
    name: str
    zone: str
    kind: str
    units: str


class SensorRead(SensorCreate):
    id: int
    created_at: datetime


class SensorReadingCreate(BaseModel):
    value: float
    recorded_at: Optional[datetime] = None


class SensorReadingRead(SensorReadingCreate):
    id: int
    sensor_id: int
    recorded_at: datetime


class WeatherSnapshot(BaseModel):
    timestamp: datetime
    temperature_c: float
    humidity: float
    solar_irradiance_wm2: float


class ScheduleBlockRead(BaseModel):
    timestamp: datetime
    target_temp_c: float
    target_hvac_mode: str
    estimated_kwh: float
    comfort_delta: float


class ScheduleResponse(BaseModel):
    run_id: int
    generated_at: datetime
    baseline_kwh: float
    optimized_kwh: float
    comfort_score: float
    cost_score: float
    blocks: List[ScheduleBlockRead]


class RecommendationRead(BaseModel):
    id: int
    title: str
    detail: str
    estimated_savings_kwh: float
    confidence: float = Field(ge=0, le=1)
    category: str
    created_at: datetime
