from datetime import datetime
from typing import List

from sqlmodel import select

from ..database import session_scope
from ..models import Sensor, SensorReading


def create_sensor(name: str, zone: str, kind: str, units: str) -> Sensor:
    sensor = Sensor(name=name, zone=zone, kind=kind, units=units)
    with session_scope() as session:
        session.add(sensor)
        session.flush()
        session.refresh(sensor)
        return sensor


def list_sensors() -> List[Sensor]:
    with session_scope() as session:
        statement = select(Sensor).order_by(Sensor.zone, Sensor.name)
        return session.exec(statement).all()


def add_reading(sensor_id: int, value: float, recorded_at: datetime | None = None) -> SensorReading:
    reading = SensorReading(sensor_id=sensor_id, value=value, recorded_at=recorded_at or datetime.utcnow())
    with session_scope() as session:
        session.add(reading)
        session.flush()
        session.refresh(reading)
        return reading


def list_readings(sensor_id: int, limit: int = 100) -> List[SensorReading]:
    with session_scope() as session:
        statement = (
            select(SensorReading)
            .where(SensorReading.sensor_id == sensor_id)
            .order_by(SensorReading.recorded_at.desc())
            .limit(limit)
        )
        results = session.exec(statement).all()
        return list(reversed(results))
