import asyncio
import json
import urllib.request
import time
import websockets

BASE_HTTP = "http://127.0.0.1:8000"
BASE_WS = "ws://127.0.0.1:8000"

def http_post(path, data, token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode()
    r = urllib.request.Request(f"{BASE_HTTP}{path}", data=body, headers=h, method="POST")
    try:
        resp = urllib.request.urlopen(r)
        return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))

async def test_websocket():
    # 1. Login to get token
    email = f"ws_tester_{int(time.time())}@test.io"
    password = "WSTesterPassword123!"
    
    print("[TEST] Registering user...")
    status, body = http_post("/auth/register", {"email": email, "password": password})
    if status != 201:
        print(f"[FAIL] Register failed: {status}, {body}")
        return
    token = body.get("access_token")
    
    # Get sensor id for testing
    h = {"Authorization": f"Bearer {token}"}
    r = urllib.request.Request(f"{BASE_HTTP}/sensors", headers=h, method="GET")
    with urllib.request.urlopen(r) as resp:
        sensors = json.loads(resp.read().decode("utf-8")).get("data", [])
    
    temp_sensor = next((s for s in sensors if s["kind"] == "temperature"), None)
    if not temp_sensor:
        print("[TEST] Creating sensor...")
        status, body = http_post("/sensors", {"name": "WS Temp Sensor", "zone": "living_room", "kind": "temperature", "units": "C"}, token=token)
        temp_sensor = body.get("data")
        
    sensor_id = temp_sensor["id"]
    
    # 2. Connect to WS
    uri = f"{BASE_WS}/ws/live-feed?room=all"
    print(f"[TEST] Connecting to WebSocket: {uri}")
    
    async with websockets.connect(uri) as websocket:
        print("[PASS] Connected to WebSocket!")
        
        # We will trigger the HTTP requests
        print("[TEST] Ingesting reading via HTTP to trigger WebSocket broadcast...")
        # Post low temp to trigger threshold alert if config exists, or high temp (27.5) to trigger alert
        status, body = http_post(f"/sensors/{sensor_id}/readings", {"value": 29.5}, token=token)
        if status != 200:
            print(f"[FAIL] Ingestion failed: {status}")
            return
            
        print("[TEST] Running optimizer via HTTP to trigger schedule broadcast...")
        status, body = http_post("/optimizer/run", {}, token=token)
        if status != 200:
            print(f"[FAIL] Optimizer trigger failed: {status}, {body}")
            return
            
        # Start listening for frames
        received_ping = False
        received_reading = False
        received_schedule = False
        received_new_alert = False
        
        print("[TEST] Listening for WebSocket frames (timeout 15 seconds)...")
        start_time = time.time()
        while time.time() - start_time < 15:
            try:
                # wait for a message
                msg_str = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                msg = json.loads(msg_str)
                mtype = msg.get("type")
                print(f"[WS RECV] Got frame: {mtype}")
                
                if mtype == "ping":
                    received_ping = True
                elif mtype == "sensor_reading":
                    received_reading = True
                    # Check field properties
                    data = msg.get("data", {})
                    assert data.get("sensor_id") == sensor_id
                    assert data.get("value") == 29.5
                    print("  -> verified sensor_reading fields.")
                elif mtype == "schedule_updated":
                    received_schedule = True
                    # Check fields
                    data = msg.get("data", {})
                    assert "run_id" in data
                    assert "optimized_kwh" in data
                    print("  -> verified schedule_updated fields.")
                elif mtype == "new_alert":
                    received_new_alert = True
                    data = msg.get("data", {})
                    assert "severity" in data
                    print(f"  -> verified new_alert fields: {data.get('title')}")
                    
            except asyncio.TimeoutError:
                pass
            
            # If we received reading and schedule, we are good to go!
            # (Ping and new_alert are bonus depending on timing, but ping is sent every 30s so might take longer,
            # and new_alert triggers on high temp warning).
            # Wait, high temp is 29.5 which is > 26, but the alert checker service runs in the background task alerts checker every 60s,
            # however, if there is a threshold config for that sensor, it might trigger immediately.
            # In our case, the background alert checker will run, but let's check if we got reading and schedule_updated!
            if received_reading and received_schedule:
                break
                
        # Validate asserts
        if not received_reading:
            print("[FAIL] Did not receive 'sensor_reading' frame via WebSocket")
            return
        if not received_schedule:
            print("[FAIL] Did not receive 'schedule_updated' frame via WebSocket")
            return
            
        print(f"[PASS] WS received_reading: {received_reading}")
        print(f"[PASS] WS received_schedule: {received_schedule}")
        print(f"[PASS] WS received_ping: {received_ping} (might be False depending on 30s cycle)")
        print(f"[PASS] WS received_new_alert: {received_new_alert} (might be False if background worker hasn't run yet)")
        print("[SUCCESS] All WebSocket feed tests passed!")

if __name__ == "__main__":
    asyncio.run(test_websocket())
