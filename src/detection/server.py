"""
fastapi server: runs pipeline in background, exposes rest + websocket api.
"""
import asyncio
import json
from pathlib import Path
from threading import Thread, Lock
import time
import cv2
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse

from pipeline_stream import PipelineStream, FrameState

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "signals"))
from sumo_stream import SumoStream

ROOT = Path(__file__).resolve().parents[2]
VIDEO = ROOT / "data/videos/traffic_sample.mp4"
CALIB = ROOT / "outputs/calibration.json"
MODEL = ROOT / "models/yolov8s.pt"

app = FastAPI(title="TrafficSense API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# shared mutable state
state_lock = Lock()
current: FrameState | None = None
events_log: list = []
event_subscribers: list[asyncio.Queue] = []

def _pipeline_thread():
    global current
    print(f"[pipeline] starting on {VIDEO.name}")
    stream = PipelineStream(VIDEO, CALIB, MODEL)
    last_emit = time.time()
    target_dt = 1.0 / stream.fps_in
    last_frame_idx = -1
    for fs in stream.run(loop=True):
        # detect video loop restart -> clear stale events
        if fs.frame_idx < last_frame_idx:
            with state_lock:
                events_log.clear()
                for q in list(event_subscribers):
                    try:
                        q.put_nowait([{"_clear": True}])
                    except asyncio.QueueFull:
                        pass
        last_frame_idx = fs.frame_idx

        with state_lock:
            current = fs
            if fs.new_events:
                events_log.extend(fs.new_events)
                if len(events_log) > 200:
                    del events_log[:-200]
                # AUTO-PREEMPT: any HIGH incident triggers sumo signal preempt
                high_events = [e for e in fs.new_events if e.get("severity") == "HIGH"]
                if high_events:
                    e = high_events[0]
                    cx = e.get("position", [0, 0])[0]
                    direction = "NS" if cx < 640 else "EW"
                    sumo.request_preempt(direction)
                    print(f"[AUTO-PREEMPT] {e['event_type']} severity={e['severity']} -> {direction}")
                # notify subscribers without blocking
                for q in list(event_subscribers):
                    try:
                        q.put_nowait(fs.new_events)
                    except asyncio.QueueFull:
                        pass
        # pace to roughly real-time playback (skip if cpu can't keep up)
        now = time.time()
        sleep = target_dt - (now - last_emit)
        if sleep > 0:
            time.sleep(sleep)
        last_emit = time.time()

sumo = SumoStream()

@app.on_event("startup")
def start_threads():
    Thread(target=_pipeline_thread, daemon=True).start()
    Thread(target=sumo.run_forever, daemon=True).start()

@app.get("/signal/state")
def signal_state():
    return sumo.state

@app.get("/signal/comparison")
def signal_comparison():
    """returns the fixed vs adaptive headline from the offline benchmark."""
    fixed_path = ROOT / "src/signals/fixed_log.json"
    adaptive_path = ROOT / "src/signals/adaptive_log.json"
    if not (fixed_path.exists() and adaptive_path.exists()):
        return JSONResponse({"status": "no_benchmark"}, status_code=503)
    f = json.loads(fixed_path.read_text())["summary"]
    a = json.loads(adaptive_path.read_text())["summary"]
    return {
        "fixed": f,
        "adaptive": a,
        "wait_improvement_pct": round((f["avg_wait_time_sec"] - a["avg_wait_time_sec"]) / f["avg_wait_time_sec"] * 100, 1),
        "travel_improvement_pct": round((f["avg_travel_time_sec"] - a["avg_travel_time_sec"]) / f["avg_travel_time_sec"] * 100, 1),
        "clear_improvement_pct": round((f["duration_sec"] - a["duration_sec"]) / f["duration_sec"] * 100, 1),
    }

@app.post("/signal/preempt")
def signal_preempt(direction: str):
    """trigger emergency green for NS or EW direction."""
    direction = direction.upper()
    if direction not in ("NS", "EW"):
        return JSONResponse({"error": "direction must be NS or EW"}, status_code=400)
    sumo.request_preempt(direction)
    return {"requested": direction}

@app.post("/debug/fake_incident")
def fake_incident(direction: str = "NS"):
    """inject a fake HIGH incident for demo purposes."""
    fake = {
        "frame": current.frame_idx if current else 0,
        "time_sec": current.time_sec if current else 0.0,
        "track_id": -1,
        "vehicle_class": "demo",
        "event_type": "SUDDEN_BRAKE",
        "severity": "HIGH",
        "speed_kmh": 2.0,
        "median_speed_kmh": 30.0,
        "position": [200 if direction.upper() == "NS" else 1000, 400],
    }
    with state_lock:
        events_log.append(fake)
        for q in list(event_subscribers):
            try:
                q.put_nowait([fake])
            except asyncio.QueueFull:
                pass
    sumo.request_preempt(direction.upper())
    return {"injected": fake, "preempt": direction.upper()}

@app.get("/")
def root():
    return {"name": "TrafficSense", "endpoints": ["/summary", "/events", "/frame.jpg", "/ws/stream"]}

@app.get("/summary")
def summary():
    with state_lock:
        if current is None:
            return JSONResponse({"status": "warming_up"}, status_code=503)
        return {
            "frame_idx": current.frame_idx,
            "time_sec": round(current.time_sec, 2),
            "unique_vehicles": current.unique_vehicles,
            "counted_in": current.counted_in,
            "counted_out": current.counted_out,
            "median_speed_kmh": round(current.median_speed_kmh, 2),
            "count_by_class": current.count_by_class,
            "events_total": len(events_log),
        }

@app.get("/events")
def events(limit: int = 50):
    with state_lock:
        return events_log[-limit:]

@app.get("/frame.jpg")
def frame_jpg():
    with state_lock:
        if current is None or not current.jpeg_bytes:
            return Response(status_code=503)
        return Response(content=current.jpeg_bytes, media_type="image/jpeg")
    
@app.get("/stream.mjpg")
def stream_mjpg():
    """multipart mjpeg stream. one http connection, browser plays as video."""
    from fastapi.responses import StreamingResponse

    def gen():
        boundary = b"--frame"
        last_idx = -1
        while True:
            with state_lock:
                fs = current
            if fs is None or not fs.jpeg_bytes or fs.frame_idx == last_idx:
                time.sleep(0.02)
                continue
            last_idx = fs.frame_idx
            yield (
                boundary + b"\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(fs.jpeg_bytes)).encode() + b"\r\n\r\n"
                + fs.jpeg_bytes + b"\r\n"
            )

    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")

@app.websocket("/ws/stream")
async def ws_stream(ws: WebSocket):
    await ws.accept()
    q: asyncio.Queue = asyncio.Queue(maxsize=10)
    event_subscribers.append(q)
    try:
        # push periodic state updates + events as they happen
        while True:
            # send current summary every 200ms
            await asyncio.sleep(0.2)
            with state_lock:
                if current is None:
                    continue
                payload = {
                    "type": "summary",
                    "frame_idx": current.frame_idx,
                    "time_sec": round(current.time_sec, 2),
                    "unique_vehicles": current.unique_vehicles,
                    "counted_in": current.counted_in,
                    "counted_out": current.counted_out,
                    "median_speed_kmh": round(current.median_speed_kmh, 2),
                    "count_by_class": current.count_by_class,
                    "events_total": len(events_log),
                }
            await ws.send_text(json.dumps(payload))
            # drain any pending events
            while not q.empty():
                events = q.get_nowait()
                await ws.send_text(json.dumps({"type": "events", "events": events}))
    except WebSocketDisconnect:
        pass
    finally:
        if q in event_subscribers:
            event_subscribers.remove(q)