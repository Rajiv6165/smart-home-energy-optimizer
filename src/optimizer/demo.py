from __future__ import annotations

from datetime import datetime, timedelta
from random import gauss, random

from .database import init_db
from .services import sensors as sensor_service


def bootstrap_demo(hours: int = 36) -> None:
    """Seed demo sensors and synthetic readings for quick experimentation."""
    init_db()
    existing = {sensor.name: sensor for sensor in sensor_service.list_sensors()}
    
    definitions = [
        ("Living Room Temp", "living_room", "temperature", "C"),
        ("Bedroom Temp", "bedroom", "temperature", "C"),
        ("Living Room Occupancy", "living_room", "occupancy", "bool"),
        ("Bedroom Occupancy", "bedroom", "occupancy", "bool"),
        ("Living Room HVAC Power", "living_room", "power", "kW"),
        ("Bedroom HVAC Power", "bedroom", "power", "kW"),
        ("Whole Home Power", "panel", "power", "kW"),
    ]

    sensors = []
    for name, zone, kind, units in definitions:
        sensor = existing.get(name)
        if not sensor:
            sensor = sensor_service.create_sensor(name, zone, kind, units)
        sensors.append(sensor)

    now = datetime.utcnow()
    # Check if we already have readings; if we have readings for all sensors, don't re-seed duplicates
    with sensor_service.session_scope() as session:
        from sqlmodel import select
        from .models import SensorReading
        has_readings = session.exec(select(SensorReading).limit(1)).first() is not None

    if has_readings:
        print("Database already contains readings. Skipping seeding to prevent duplicates.")
        return

    for sensor in sensors:
        baseline = 22.0 if sensor.kind == "temperature" else 0.5
        for step in range(hours):
            timestamp = now - timedelta(hours=hours - step)
            if sensor.kind == "temperature":
                value = baseline + gauss(0, 0.8)
            elif sensor.kind == "occupancy":
                value = 1.0 if random() > 0.5 else 0.0
            else:  # power
                if "HVAC" in sensor.name:
                    # HVAC power fluctuates depending on occupancy/mode simulation
                    value = 1.2 + gauss(0, 0.2)
                else:
                    # Whole Home Power Panel
                    value = 2.5 + gauss(0, 0.4)
            sensor_service.add_reading(sensor.id, max(0.0, value), timestamp)

    print(f"Seeded {len(sensors)} sensors with {hours}h of history")


if __name__ == "__main__":
    bootstrap_demo()
