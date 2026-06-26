from datetime import datetime
from typing import Optional, List

from sqlmodel import Field, Relationship, SQLModel


class Sensor(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    zone: str
    kind: str = Field(description="temperature|humidity|occupancy|power")
    units: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

    readings: List["SensorReading"] = Relationship(back_populates="sensor")


class SensorReading(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    sensor_id: int = Field(foreign_key="sensor.id")
    value: float
    recorded_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    sensor: Optional["Sensor"] = Relationship(back_populates="readings")


class WeatherForecast(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(index=True)
    temperature_c: float
    humidity: float
    solar_irradiance_wm2: float
    source: str = "open-meteo"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ScheduleRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    baseline_kwh: float
    optimized_kwh: float
    comfort_score: float
    cost_score: float
    notes: Optional[str] = None

    blocks: List["ScheduleBlock"] = Relationship(back_populates="run")


class ScheduleBlock(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="schedulerun.id", index=True)
    timestamp: datetime = Field(index=True)
    target_temp_c: float
    target_hvac_mode: str = Field(default="auto")
    estimated_kwh: float
    comfort_delta: float

    run: Optional["ScheduleRun"] = Relationship(back_populates="blocks")


class Recommendation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    detail: str
    estimated_savings_kwh: float = 0.0
    confidence: float = 0.5
    created_at: datetime = Field(default_factory=datetime.utcnow)
    category: str = Field(default="general")
