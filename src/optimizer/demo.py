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
        ("Whole Home Power", "panel", "power", "kW"),
    ]

    sensors = []
    for name, zone, kind, units in definitions:
        sensor = existing.get(name)
        if not sensor:
            sensor = sensor_service.create_sensor(name, zone, kind, units)
        sensors.append(sensor)

    now = datetime.utcnow()
    for sensor in sensors:
        baseline = 22.0 if sensor.kind == "temperature" else 0.5
        for step in range(hours):
            timestamp = now - timedelta(hours=hours - step)
            if sensor.kind == "temperature":
                value = baseline + gauss(0, 0.8)
            elif sensor.kind == "occupancy":
                value = 1.0 if random() > 0.5 else 0.0
            else:  # power
                value = 2.5 + gauss(0, 0.4)
            sensor_service.add_reading(sensor.id, value, timestamp)

    print(f"Seeded {len(sensors)} sensors with {hours}h of history")


if __name__ == "__main__":
    bootstrap_demo()
