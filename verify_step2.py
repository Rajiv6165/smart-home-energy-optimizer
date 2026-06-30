import json
import urllib.request
import urllib.error
import time

BASE = "http://127.0.0.1:8000"

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
        return resp.status, json.loads(resp.read().decode("utf-8")), resp.info()
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read().decode("utf-8"))
        except Exception:
            err_body = {}
        return e.code, err_body, e.headers
    except Exception as e:
        return 0, {"detail": str(e)}, {}

def run_tests():
    # 1. Register & Login
    email = f"profile_tester_{int(time.time())}@test.io"
    password = "ProfileTesterPassword123!"
    
    print("[TEST] Registering user...")
    status, body, _ = req("POST", "/auth/register", {"email": email, "password": password})
    if status != 201:
        print(f"[FAIL] Register failed: {status}, {body}")
        return
    token = body.get("access_token")
    
    # 2. GET Profile
    print("[TEST] Fetching default user profile...")
    status, body, _ = req("GET", "/auth/profile", token=token)
    if status != 200:
        print(f"[FAIL] GET /auth/profile failed: {status}, {body}")
        return
    
    profile = body.get("data", {})
    if profile.get("home_name") != "My Smart Home":
        print(f"[FAIL] Default home_name incorrect: {profile.get('home_name')}")
        return
    print(f"[PASS] Default home name is correct: {profile.get('home_name')}")
    print(f"[PASS] Default tariff rate: {profile.get('tariff_per_kwh')} $/kWh")
    
    # 3. PUT Profile
    print("[TEST] Updating profile preferences...")
    payload = {
        "full_name": "Rajiv Test",
        "home_name": "Rajiv Solar Fortress",
        "comfort_min_c": 19.5,
        "comfort_max_c": 23.5,
        "tariff_per_kwh": 0.28,
        "timezone": "America/New_York",
        "notifications_enabled": False
    }
    status, body, _ = req("PUT", "/auth/profile", payload, token=token)
    if status != 200:
        print(f"[FAIL] PUT /auth/profile failed: {status}, {body}")
        return
    
    updated = body.get("data", {})
    if updated.get("home_name") != "Rajiv Solar Fortress" or updated.get("comfort_min_c") != 19.5 or updated.get("tariff_per_kwh") != 0.28:
        print(f"[FAIL] Profile values did not update correctly: {updated}")
        return
    print("[PASS] Profile updated successfully in response.")
    
    # Verify persistence
    status, body, _ = req("GET", "/auth/profile", token=token)
    persisted = body.get("data", {})
    if persisted.get("full_name") != "Rajiv Test":
        print(f"[FAIL] Profile values did not persist: {persisted}")
        return
    print("[PASS] Profile values verified in database.")
    
    # 4. Change Password
    print("[TEST] Changing password...")
    status, body, _ = req("POST", "/auth/change-password", {
        "old_password": password,
        "new_password": "NewSecurePassword456!"
    }, token=token)
    if status != 200 or not body.get("data", {}).get("success"):
        print(f"[FAIL] Change password failed: {status}, {body}")
        return
    print("[PASS] Password changed successfully.")
    
    # Try login with old password (should fail)
    status, body, _ = req("POST", "/auth/login", {"email": email, "password": password})
    if status != 401:
        print(f"[FAIL] Login with old password did not fail as expected: {status}")
        return
    print("[PASS] Authentication fails with old password.")
    
    # Try login with new password (should pass)
    status, body, _ = req("POST", "/auth/login", {"email": email, "password": "NewSecurePassword456!"})
    if status != 200:
        print(f"[FAIL] Login with new password failed: {status}, {body}")
        return
    token = body.get("access_token")
    print("[PASS] Successfully authenticated with new password.")
    
    # 5. Advanced Analytics
    print("[TEST] Fetching weekly summary...")
    status, body, _ = req("GET", "/analytics/weekly-summary", token=token)
    if status != 200:
        print(f"[FAIL] GET /analytics/weekly-summary failed: {status}")
        return
    print(f"[PASS] Weekly summary items: {len(body.get('data', []))}")
    
    print("[TEST] Fetching savings total...")
    status, body, _ = req("GET", "/analytics/savings-total", token=token)
    if status != 200:
        print(f"[FAIL] GET /analytics/savings-total failed: {status}")
        return
    totals = body.get("data", {})
    print(f"[PASS] Savings total runs: {totals.get('total_runs')}, saved: {totals.get('total_kwh_saved')} kWh, cost saved: ${totals.get('total_cost_saved')}")
    
    print("[TEST] Fetching zone comparisons...")
    status, body, _ = req("GET", "/analytics/zone-comparison", token=token)
    if status != 200:
        print(f"[FAIL] GET /analytics/zone-comparison failed: {status}")
        return
    zones = body.get("data", [])
    print(f"[PASS] Zones compared: {len(zones)}")
    for z in zones:
        print(f"  - Zone: {z['zone']}, Temp: {z['avg_temp']}°C, Occ: {z['avg_occupancy']}, kWh: {z['total_kwh']}, Eff: {z['efficiency_score']}%")
        
    print("[TEST] Fetching sensor history for sensor 1...")
    status, body, _ = req("GET", "/analytics/sensor-history/1?hours=24", token=token)
    if status != 200:
        print(f"[FAIL] GET /analytics/sensor-history/1 failed: {status}")
        return
    print(f"[PASS] Sensor history items returned: {len(body.get('data', []))}")
    
    # 6. Exporters
    print("[TEST] Downloading schedule CSV...")
    # Using urllib request directly to check download headers
    r = urllib.request.Request(f"{BASE}/export/schedule-csv", headers={"Authorization": f"Bearer {token}"})
    try:
        resp = urllib.request.urlopen(r)
        check_csv = resp.read()
        disp = resp.headers.get("Content-Disposition")
        if resp.status == 200 and "attachment" in disp and check_csv.startswith(b"timestamp"):
            print(f"[PASS] Schedule CSV download verified. Header: {disp}, Size: {len(check_csv)} bytes")
        else:
            print(f"[FAIL] Schedule CSV headers/content invalid: status={resp.status}, header={disp}")
            return
    except Exception as e:
        print(f"[FAIL] Schedule CSV failed: {e}")
        return
        
    print("[TEST] Downloading analytics CSV...")
    r = urllib.request.Request(f"{BASE}/export/analytics-csv", headers={"Authorization": f"Bearer {token}"})
    try:
        resp = urllib.request.urlopen(r)
        check_csv = resp.read()
        disp = resp.headers.get("Content-Disposition")
        if resp.status == 200 and "attachment" in disp and check_csv.startswith(b"date"):
            print(f"[PASS] Analytics CSV download verified. Header: {disp}, Size: {len(check_csv)} bytes")
        else:
            print(f"[FAIL] Analytics CSV headers/content invalid: status={resp.status}, header={disp}")
            return
    except Exception as e:
        print(f"[FAIL] Analytics CSV failed: {e}")
        return
        
    print("[TEST] Downloading full system JSON report...")
    r = urllib.request.Request(f"{BASE}/export/report-json", headers={"Authorization": f"Bearer {token}"})
    try:
        resp = urllib.request.urlopen(r)
        check_json = json.loads(resp.read().decode("utf-8"))
        disp = resp.headers.get("Content-Disposition")
        if resp.status == 200 and "attachment" in disp and "savings_totals" in check_json:
            print(f"[PASS] Report JSON download verified. User home in report: {check_json['user']['home_name']}")
        else:
            print(f"[FAIL] Report JSON headers/content invalid: status={resp.status}, header={disp}")
            return
    except Exception as e:
        print(f"[FAIL] Report JSON failed: {e}")
        return
        
    print("[SUCCESS] All Step 2 tests passed successfully!")

if __name__ == "__main__":
    run_tests()
