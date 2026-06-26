# Smart Home Energy Optimizer

## Goals
- Collect live indoor sensor data (temperature, humidity, occupancy, energy consumption).
- Pull short-term weather forecasts to anticipate outdoor conditions.
- Generate heating/cooling schedules that balance comfort with reduced energy consumption.
- Surface actionable savings tips and explain why each change is recommended.

## High-Level Components
1. **API Gateway (FastAPI)**
   - REST endpoints to ingest sensor readings, request optimized schedules, and retrieve insights.
2. **Data Store (SQLite via SQLModel)**
   - Persists sensors, readings, weather snapshots, and published schedules.
3. **Weather Service (httpx)**
   - Fetches hourly forecasts from the Open-Meteo public API (no key required).
   - Falls back to cached data if the network call fails.
4. **Optimization Engine**
   - Consolidates sensor history and forecast projections.
   - Predicts thermal demand using a simple resistance/capacitance-style model.
   - Produces target HVAC setpoints for the next 24h with comfort + cost scoring.
5. **Insights Service**
   - Compares actual usage vs. optimized plan to compute estimated savings.
   - Generates personalized recommendations tagged with confidence + impact.
6. **Background Jobs**
   - Periodically refresh forecasts and recompute schedules.
   - Could be run via `apscheduler` or an async task loop (initial version uses async loop triggered at startup).

## Data Flow
1. **Sensor ingestion**: Edge devices call `/sensors/{id}/readings` to push values. Data is stored immediately and also buffered in memory for quick access.
2. **Weather sync**: A background coroutine calls Open-Meteo every hour, storing results in `weather_forecasts`.
3. **Optimization pass**:
   - Gather latest 24h of sensor readings per zone.
   - Merge with forecast temperatures and solar gain estimates.
   - Score candidate HVAC setpoints using: comfort penalty, energy cost proxy (kWh * tariff), and actuator constraints.
4. **Schedules & tips**: The resulting plan is persisted and exposed via `/schedules/latest` and `/insights/tips`.
5. **Client apps**: Mobile/web dashboards can consume the API, visualize timelines, and allow overrides.

## Non-Goals (v1)
- Full user authentication/multi-home support (single-home demo only).
- Direct control of physical devices (export JSON schedule instead).
- Real utility pricing integration (uses flat tariff but pluggable strategy).

## Future Extensions
- Plug in real utility TOU rates.
- Add machine-learning based thermal prediction.
- Sync with Matter-compatible thermostats for closed-loop control.
- Build a React dashboard for interactive insights.
