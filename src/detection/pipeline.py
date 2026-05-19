"""
unified pipeline: detection + tracking + speed + line counting + incident detection.
outputs annotated video, events log, and full summary json.
"""
import json
import time
from collections import defaultdict, deque
from pathlib import Path
import cv2
import numpy as np
from ultralytics import YOLO

from incidents import IncidentDetector

INPUT_VIDEO = Path("data/videos/traffic_sample.mp4")
OUTPUT_VIDEO = Path("outputs/traffic_pipeline.mp4")
OUTPUT_EVENTS = Path("outputs/events.json")
OUTPUT_SUMMARY = Path("outputs/pipeline_summary.json")
CALIB_FILE = Path("outputs/calibration.json")
MODEL_PATH = Path("models/yolov8n.pt")
CONF_THRESHOLD = 0.35
SMOOTH_WINDOW = 30
EMA_ALPHA = 0.25

VEHICLE_CLASSES = {1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

def color_for_id(tid: int):
    return int((tid * 53 + 150) % 256), int((tid * 17 + 80) % 256), int((tid * 37) % 256)

def side_of_line(p, a, b):
    return np.sign((b[0]-a[0])*(p[1]-a[1]) - (b[1]-a[1])*(p[0]-a[0]))

def main():
    assert CALIB_FILE.exists(), "run calibrate.py first"
    calib = json.loads(CALIB_FILE.read_text())
    mpp = calib["meters_per_pixel"]
    line = calib["counting_line"]
    a, b = tuple(line[0]), tuple(line[1])

    cap = cv2.VideoCapture(str(INPUT_VIDEO))
    fps_in = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    print(f"video: {width}x{height} @ {fps_in:.1f}fps  mpp={mpp:.5f}")

    model = YOLO(str(MODEL_PATH))
    detector = IncidentDetector(fps=fps_in)

    writer = cv2.VideoWriter(str(OUTPUT_VIDEO),
                             cv2.VideoWriter_fourcc(*"mp4v"),
                             fps_in, (width, height))

    history = defaultdict(lambda: deque(maxlen=SMOOTH_WINDOW))
    last_side = {}
    counted_in, counted_out = set(), set()
    track_class = {}
    smoothed_speed = {}     # NEW: tid -> ema-smoothed speed
    all_events = []
    active_event_flashes = {}   # tid -> frame_idx when last fired (for visual flash)

    frame_idx = 0
    t0 = time.time()

    for result in model.track(
        source=str(INPUT_VIDEO),
        conf=CONF_THRESHOLD,
        tracker="bytetrack.yaml",
        persist=True,
        stream=True,
        verbose=False,
    ):
        frame = result.orig_img.copy()

        # collect per-frame speeds for median
        frame_speeds = []
        frame_track_data = []  # (tid, name, cx, cy, speed, x1y1x2y2)

        if result.boxes is not None and result.boxes.id is not None:
            ids = result.boxes.id.int().cpu().tolist()
            classes = result.boxes.cls.int().cpu().tolist()
            xyxys = result.boxes.xyxy.cpu().tolist()

            for tid, cls_id, (x1, y1, x2, y2) in zip(ids, classes, xyxys):
                if cls_id not in VEHICLE_CLASSES:
                    continue
                name = VEHICLE_CLASSES[cls_id]
                track_class[tid] = name
                cx, cy = (x1+x2)/2, (y1+y2)/2
                history[tid].append((frame_idx, cx, cy))

                speed_kmh = 0.0
                if len(history[tid]) >= 2:
                    f0, x0, y0 = history[tid][0]
                    f1, xc, yc = history[tid][-1]
                    if f1 > f0:
                        pix = ((xc-x0)**2 + (yc-y0)**2) ** 0.5
                        sec = (f1-f0) / fps_in
                        speed_kmh = (pix * mpp / sec) * 3.6
                # ema smooth to kill centroid-jitter noise
                prev = smoothed_speed.get(tid, speed_kmh)
                speed_kmh = EMA_ALPHA * speed_kmh + (1 - EMA_ALPHA) * prev
                smoothed_speed[tid] = speed_kmh
                frame_speeds.append(speed_kmh)
                frame_track_data.append((tid, name, cx, cy, speed_kmh, (x1, y1, x2, y2)))

                # line crossing
                side = side_of_line((cx, cy), a, b)
                if tid in last_side and side != 0 and last_side[tid] != 0:
                    if last_side[tid] < 0 and side > 0:
                        counted_in.add(tid)
                    elif last_side[tid] > 0 and side < 0:
                        counted_out.add(tid)
                if side != 0:
                    last_side[tid] = side

        median_speed = float(np.median(frame_speeds)) if frame_speeds else 0.0

        # incident pass + drawing
        events_this_frame = []
        for tid, name, cx, cy, speed_kmh, (x1, y1, x2, y2) in frame_track_data:
            events = detector.update(frame_idx, tid, name, speed_kmh, (cx, cy), median_speed)
            for e in events:
                all_events.append(e.to_dict())
                events_this_frame.append(e)
                active_event_flashes[tid] = (frame_idx, e.event_type)

            # draw
            color = color_for_id(tid)
            is_flashing = (tid in active_event_flashes and
                           frame_idx - active_event_flashes[tid][0] < int(fps_in * 1.5))
            box_color = (0, 0, 255) if is_flashing else color
            thickness = 4 if is_flashing else 2
            x1i, y1i, x2i, y2i = int(x1), int(y1), int(x2), int(y2)
            cv2.rectangle(frame, (x1i, y1i), (x2i, y2i), box_color, thickness)
            label = f"#{tid} {name} {speed_kmh:.0f}km/h"
            if is_flashing:
                label += f"  ! {active_event_flashes[tid][1]}"
            cv2.putText(frame, label, (x1i, y1i - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, box_color, 2)

        # counting line
        cv2.line(frame, a, b, (0, 255, 255), 2)

        # overlay
        overlays = [
            f"frame {frame_idx+1}",
            f"unique: {len(track_class)}",
            f"in/out: {len(counted_in)}/{len(counted_out)}",
            f"median speed: {median_speed:.1f} km/h",
            f"events total: {len(all_events)}",
        ]
        for i, txt in enumerate(overlays):
            cv2.putText(frame, txt, (10, 25 + i*24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        # red banner if event fired this frame
        if events_this_frame:
            cv2.rectangle(frame, (0, 0), (width, 8), (0, 0, 255), -1)
            cv2.rectangle(frame, (0, height-8), (width, height), (0, 0, 255), -1)
            top = events_this_frame[0]
            banner = f"!! {top.event_type}  id#{top.track_id} ({top.vehicle_class})  sev={top.severity}"
            cv2.putText(frame, banner, (10, height - 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        writer.write(frame)
        frame_idx += 1

        if frame_idx % 60 == 0:
            print(f"  {frame_idx} frames | events={len(all_events)} "
                  f"| median={median_speed:.1f} km/h | "
                  f"{frame_idx/(time.time()-t0):.1f} fps")

    writer.release()
    elapsed = time.time() - t0
    print(f"\ndone. {frame_idx} frames in {elapsed:.1f}s ({frame_idx/elapsed:.1f} fps)")

    # event breakdown
    breakdown = defaultdict(int)
    for e in all_events:
        breakdown[e["event_type"]] += 1
    print(f"events: {dict(breakdown)}")

    summary = {
        "video": str(INPUT_VIDEO),
        "frames": frame_idx,
        "unique_vehicles": len(track_class),
        "crossed_in": len(counted_in),
        "crossed_out": len(counted_out),
        "events_total": len(all_events),
        "events_by_type": dict(breakdown),
    }

    OUTPUT_EVENTS.write_text(json.dumps(all_events, indent=2))
    OUTPUT_SUMMARY.write_text(json.dumps(summary, indent=2))
    print(f"saved: {OUTPUT_EVENTS}")
    print(f"saved: {OUTPUT_SUMMARY}")
    print(f"saved: {OUTPUT_VIDEO}")

if __name__ == "__main__":
    main()