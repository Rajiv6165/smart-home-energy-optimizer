from datetime import datetime
from typing import Optional, List

from sqlmodel import Field, Relationship, SQLModel


class User(SQLModel, table=True):
    """Registered user for JWT authentication."""
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Sensor(SQLModel, table=True):
    """Physical or virtual sensor installed in a zone."""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    zone: str
    kind: str = Field(description="temperature|humidity|occupancy|power")
    units: str
    is_deleted: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    readings: List["SensorReading"] = Relationship(back_populates="sensor")


class SensorReading(SQLModel, table=True):
    """A single reading from a sensor at a point in time."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sensor_id: int = Field(foreign_key="sensor.id")
    value: float
    recorded_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    sensor: Optional["Sensor"] = Relationship(back_populates="readings")


class WeatherForecast(SQLModel, table=True):
    """Hourly weather forecast snapshot from Open-Meteo."""
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(index=True)
    temperature_c: float
    humidity: float
    solar_irradiance_wm2: float
    source: str = "open-meteo"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ScheduleRun(SQLModel, table=True):
    """A completed optimization run with energy and carbon metrics."""
    id: Optional[int] = Field(default=None, primary_key=True)
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    baseline_kwh: float
    optimized_kwh: float
    comfort_score: float
    cost_score: float
    notes: Optional[str] = None
    # Carbon footprint tracking (US average: 0.386 kg CO2 per kWh)
    carbon_kg: Optional[float] = None
    carbon_saved_kg: Optional[float] = None

    blocks: List["ScheduleBlock"] = Relationship(back_populates="run")


class ScheduleBlock(SQLModel, table=True):
    """A single 1-hour HVAC instruction block within a ScheduleRun."""
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="schedulerun.id", index=True)
    timestamp: datetime = Field(index=True)
    target_temp_c: float
    target_hvac_mode: str = Field(default="auto")
    estimated_kwh: float
    comfort_delta: float

    run: Optional["ScheduleRun"] = Relationship(back_populates="blocks")


class Recommendation(SQLModel, table=True):
    """AI-generated energy saving recommendation."""
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    detail: str
    estimated_savings_kwh: float = 0.0
    confidence: float = 0.5
    created_at: datetime = Field(default_factory=datetime.utcnow)
    category: str = Field(default="general")


class AlertConfig(SQLModel, table=True):
    """Threshold-based alert configuration for a sensor."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sensor_id: int = Field(foreign_key="sensor.id", index=True)
    threshold_value: float
    operator: str = Field(default=">")  # '>', '<', '>=', '<='
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
