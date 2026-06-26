from datetime import datetime
from typing import List, Optional, Generic, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")


class MetaSchema(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    version: str = "1.0"


class ResponseEnvelope(BaseModel, Generic[T]):
    data: T
    meta: MetaSchema = Field(default_factory=MetaSchema)


class SensorCreate(BaseModel):
    name: str
    zone: str
    kind: str
    units: str


class SensorUpdate(BaseModel):
    name: Optional[str] = None
    zone: Optional[str] = None


class SensorRead(SensorCreate):
    id: int
    is_deleted: bool
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
    carbon_kg: Optional[float] = None
    carbon_saved_kg: Optional[float] = None
    blocks: List[ScheduleBlockRead]


class RecommendationRead(BaseModel):
    id: int
    title: str
    detail: str
    estimated_savings_kwh: float
    confidence: float = Field(ge=0, le=1)
    category: str
    created_at: datetime


class AlertConfigCreate(BaseModel):
    sensor_id: int
    threshold_value: float
    operator: str = ">"  # '>', '<', '>=', '<='
    is_active: bool = True


class AlertConfigRead(AlertConfigCreate):
    id: int
    created_at: datetime


class DailySummaryRead(BaseModel):
    date: str
    avg_temperature: Optional[float] = None
    avg_occupancy: Optional[float] = None
    total_kwh: Optional[float] = None


class ZoneBreakdownRead(BaseModel):
    zone: str
    energy_usage_kwh: float
    percentage: float


class SensorStatsRead(BaseModel):
    sensor_id: int
    min_value: float
    max_value: float
    avg_value: float
    trend: str  # "upward" | "downward" | "stable" | "insufficient_data"
