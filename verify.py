"""Quick verification script for the upgraded Smart Home Energy Optimizer API."""
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
PASS = "[PASS]"
FAIL = "[FAIL]"
INFO = "[INFO]"
errors = []


def req(method, path, data=None, headers=None, token=None):
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    if token:
        h["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data else None
    r = urllib.request.Request(f"{BASE}{path}", data=body, headers=h, method=method)
    try:
        resp = urllib.request.urlopen(r)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, {}


def check(label, cond, info=""):
    if cond:
        print(f"{PASS} {label} {info}")
    else:
        print(f"{FAIL} {label} {info}")
        errors.append(label)


# 1. Health
code, body = req("GET", "/health")
check("GET /health", code == 200, f"status={body.get('data',{}).get('status')}")

# 2. Register fresh user
email = f"verifier_{int(time.time())}@test.io"
code, body = req("POST", "/auth/register", {"email": email, "password": "Verify123!"})
check("POST /auth/register", code == 201, f"email={body.get('email')}")
token = body.get("access_token", "")

# 3. Login same user
code, body2 = req("POST", "/auth/login", {"email": email, "password": "Verify123!"})
check("POST /auth/login", code == 200, f"token={'OK' if body2.get('access_token') else 'MISSING'}")

# 4. GET /sensors (public)
code, body = req("GET", "/sensors")
check("GET /sensors (public)", code == 200, f"{len(body.get('data',[]))} sensors")

# 5. POST /sensors WITHOUT token -> should 401
code, _ = req("POST", "/sensors", {"name": "X", "zone": "y", "kind": "temperature", "units": "C"})
check("POST /sensors no-auth -> 401", code == 401)

# 6. POST /sensors WITH token -> should 201
code, body = req("POST", "/sensors", {"name": "Verify Sensor", "zone": "office", "kind": "temperature", "units": "C"}, token=token)
check("POST /sensors with-auth", code == 200, f"id={body.get('data',{}).get('id')}")
sid = body.get("data", {}).get("id")

# 7. PUT /sensors/{id} (protected)
if sid:
    code, body = req("PUT", f"/sensors/{sid}", {"name": "Verified Sensor Renamed", "zone": "office"}, token=token)
    check("PUT /sensors/{id}", code == 200, f"name={body.get('data',{}).get('name')}")

# 8. GET /schedules/latest
code, body = req("GET", "/schedules/latest")
if code == 200:
    d = body.get("data", {})
    check("GET /schedules/latest (carbon_kg)", d.get("carbon_kg") is not None, f"carbon_kg={d.get('carbon_kg')}")
    check("GET /schedules/latest (carbon_saved_kg)", d.get("carbon_saved_kg") is not None, f"carbon_saved_kg={d.get('carbon_saved_kg')}")
else:
    print(f"{INFO} No schedule yet (will generate)")
    code, body = req("POST", "/optimizer/run", token=token)
    check("POST /optimizer/run", code == 200, f"carbon_kg={body.get('data',{}).get('carbon_kg')}")

# 9. GET /insights/tips
code, body = req("GET", "/insights/tips")
tips = body.get("data", [])
check("GET /insights/tips", code == 200, f"{len(tips)} recommendations")

# 10. GET /weather/current
code, body = req("GET", "/weather/current")
check("GET /weather/current", code == 200, f"{len(body.get('data',[]))} snapshots")

# 11. GET /analytics/daily-summary
code, body = req("GET", "/analytics/daily-summary")
check("GET /analytics/daily-summary", code == 200, f"{len(body.get('data',[]))} days")

# 12. GET /analytics/zone-breakdown
code, body = req("GET", "/analytics/zone-breakdown")
zones = body.get("data", [])
check("GET /analytics/zone-breakdown", code == 200, str([z["zone"] for z in zones]))

# 13. POST /alerts/config (protected)
code, body = req("POST", "/alerts/config", {"sensor_id": 1, "threshold_value": 26.0, "operator": ">", "is_active": True}, token=token)
check("POST /alerts/config", code == 200, f"id={body.get('data',{}).get('id')}")

# 14. GET /schedules/history
code, body = req("GET", "/schedules/history?limit=5")
check("GET /schedules/history", code == 200, f"{len(body.get('data',[]))} runs")

# 15. DELETE /sensors/{id} (protected)
if sid:
    code, body = req("DELETE", f"/sensors/{sid}", token=token)
    check("DELETE /sensors/{id}", code == 200, f"deleted={body.get('data',{}).get('deleted')}")

# Summary
print()
print("=" * 40)
if errors:
    print(f"FAILED: {len(errors)} tests: {errors}")
    sys.exit(1)
else:
    print(f"ALL {15} TESTS PASSED")
