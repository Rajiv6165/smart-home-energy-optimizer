from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    database_url: str = Field(
        default="sqlite:///optimizer.db",
        description="SQLModel-compatible database URL",
    )
    home_latitude: float = 37.7749
    home_longitude: float = -122.4194
    comfort_min_c: float = 20.5
    comfort_max_c: float = 23.5
    tariff_per_kwh: float = 0.22
    weather_refresh_minutes: int = 60
    schedule_refresh_minutes: int = 90

    # JWT Authentication
    jwt_secret_key: str = Field(
        default="change-me-in-production-use-a-32-char-random-string",
        description="Secret key for signing JWT tokens",
    )
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


def get_settings() -> Settings:
    return Settings()
