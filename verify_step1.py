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
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read())
        except Exception:
            err_body = {}
        return e.code, err_body

def run_tests():
    # 1. Register & Login
    email = f"alert_tester_{int(time.time())}@test.io"
    password = "AlertTesterPassword123!"
    
    print("[TEST] Registering user...")
    code, body = req("POST", "/auth/register", {"email": email, "password": password})
    if code != 201:
        print(f"[FAIL] Register failed: {code}, {body}")
        return
    token = body.get("access_token")
    
    # 2. Get alerts
    print("[TEST] Fetching initial alerts (should be empty or existing)...")
    code, body = req("GET", "/alerts", token=token)
    if code != 200:
        print(f"[FAIL] GET /alerts failed: {code}")
        return
    initial_alerts = body.get("data", [])
    print(f"[PASS] Initial alert count: {len(initial_alerts)}")
    
    # 3. Simulate high temperature reading to trigger alert
    print("[TEST] Fetching sensors to find a temperature sensor...")
    code, body = req("GET", "/sensors", token=token)
    sensors = body.get("data", [])
    temp_sensor = next((s for s in sensors if s["kind"] == "temperature"), None)
    
    if not temp_sensor:
        print("[INFO] No temperature sensor found. Creating one...")
        code, body = req("POST", "/sensors", {"name": "Test Room Temp", "zone": "bedroom", "kind": "temperature", "units": "C"}, token=token)
        temp_sensor = body.get("data")
        
    print(f"[TEST] Posting high reading (28.5°C) to sensor {temp_sensor['id']}...")
    code, body = req("POST", f"/sensors/{temp_sensor['id']}/readings", {"value": 28.5}, token=token)
    if code != 200:
        print(f"[FAIL] Failed to post reading: {code}")
        return
        
    # We will trigger the rules directly by running a short python command or waiting a bit.
    # Since we added periodic check, let's wait 3 seconds and hit a custom endpoint, or wait, we can run check_and_trigger_alerts directly via python!
    # Let's run check_and_trigger_alerts directly via python command first to avoid waiting for the 60s background task.
    # But wait, let's verify if we can trigger it and fetch alerts.
    print("[TEST] Waiting 12 seconds for background alerts worker to trigger... (first run runs after sleep(10))")
    time.sleep(12)
    
    code, body = req("GET", "/alerts", token=token)
    alerts = body.get("data", [])
    print(f"[INFO] Current alerts: {len(alerts)}")
    
    warning_alert = next((a for a in alerts if a["category"] == "temperature" and a["severity"] == "warning" and a["sensor_id"] == temp_sensor["id"]), None)
    if not warning_alert:
        print("[FAIL] Warning alert was not generated in background.")
        # Let's try triggering manually via python command to see if it works or if database issue.
        return
    
    print(f"[PASS] Warning alert generated: {warning_alert['title']} - {warning_alert['message']}")
    
    # 4. Mark alert as read
    aid = warning_alert["id"]
    print(f"[TEST] Marking alert {aid} as read...")
    code, body = req("POST", f"/alerts/mark-read/{aid}", token=token)
    if code != 200 or not body.get("data", {}).get("is_read"):
        print(f"[FAIL] Mark read failed: {code}, {body}")
        return
    print("[PASS] Alert successfully marked as read.")
    
    # 5. Mark all as read
    print("[TEST] Marking all alerts as read...")
    code, body = req("POST", "/alerts/mark-all-read", token=token)
    if code != 200:
        print(f"[FAIL] Mark all read failed: {code}")
        return
    print(f"[PASS] Mark all read successful: {body.get('data')}")
    
    # 6. Delete alert
    print(f"[TEST] Deleting alert {aid}...")
    code, body = req("DELETE", f"/alerts/{aid}", token=token)
    if code != 200 or not body.get("data", {}).get("deleted"):
        print(f"[FAIL] Delete failed: {code}, {body}")
        return
    print("[PASS] Alert successfully deleted.")
    print("[SUCCESS] All Step 1 tests passed!")

if __name__ == "__main__":
    run_tests()
