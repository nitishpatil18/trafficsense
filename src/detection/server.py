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

ROOT = Path(__file__).resolve().parents[2]
VIDEO = ROOT / "data/videos/traffic_sample.mp4"
CALIB = ROOT / "outputs/calibration.json"
MODEL = ROOT / "models/yolov8n.pt"

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
    for fs in stream.run(loop=True):
        with state_lock:
            current = fs
            if fs.new_events:
                events_log.extend(fs.new_events)
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

@app.on_event("startup")
def start_pipeline():
    t = Thread(target=_pipeline_thread, daemon=True)
    t.start()

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