# Smart Home Energy Optimizer

An AI-powered smart home energy optimization system featuring a FastAPI backend with real-time IoT sensor ingestion, HVAC schedule optimization, weather forecasting integration, and a visually stunning React dashboard.

## Features
- Register sensors (temperature, occupancy, power, etc.) and stream readings.
- Pull hourly forecasts from Open-Meteo to anticipate outdoor swings.
- Optimization engine balances comfort vs. kWh spend for the next 24–30 hours.
- Insights service surfaces estimated savings and actionable tips.
- Background jobs keep forecasts and schedules fresh.

## Getting Started
1. **Install deps**
   ```bash
   pip install -r requirements.txt  # or use pyproject with pip>=23: pip install .
   ```
   (If you prefer, create a virtualenv first.)

2. **Seed demo data**
   ```bash
   python -m optimizer.demo
   ```

3. **Run the API**
   ```bash
   uvicorn optimizer.main:app --reload
   ```

4. **Try it out**
   - `POST /weather/refresh` to fetch forecasts immediately.
   - `POST /optimizer/run` to generate a schedule.
   - `GET /schedules/latest` and `GET /insights/tips` to inspect results.

## Configuration
Customize defaults via environment variables or an `.env` file:

| Variable | Default | Description |
| --- | --- | --- |
| `DATABASE_URL` | sqlite:///.../optimizer.db | Where SQLModel stores data |
| `HOME_LATITUDE` | 37.7749 | Location for weather |
| `HOME_LONGITUDE` | -122.4194 | Location for weather |
| `COMFORT_MIN_C` | 20.5 | Lower comfort bound |
| `COMFORT_MAX_C` | 23.5 | Upper comfort bound |
| `TARIFF_PER_KWH` | 0.22 | Flat rate for savings calc |
| `WEATHER_REFRESH_MINUTES` | 60 | Background fetch cadence |
| `SCHEDULE_REFRESH_MINUTES` | 90 | Re-optimization cadence |

## API Snapshot
- `GET /health` – service status
- `POST /sensors` / `GET /sensors`
- `POST /sensors/{id}/readings` / `GET /sensors/{id}/readings`
- `POST /weather/refresh`
- `POST /optimizer/run`
- `GET /schedules/latest`
- `GET /insights/tips`

Refer to `docs/ARCHITECTURE.md` for the full component overview and future roadmap ideas.
