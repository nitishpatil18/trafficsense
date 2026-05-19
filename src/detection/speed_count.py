"""
yolov8 + bytetrack + speed estimation + line-crossing counter.
reads outputs/calibration.json for meters_per_pixel and counting_line.
outputs annotated video and a summary json.
"""
import json
import time
from collections import defaultdict, deque
from pathlib import Path
import cv2
import numpy as np
from ultralytics import YOLO

INPUT_VIDEO = Path("data/videos/traffic_sample.mp4")
OUTPUT_VIDEO = Path("outputs/traffic_speed.mp4")
OUTPUT_SUMMARY = Path("outputs/summary.json")
CALIB_FILE = Path("outputs/calibration.json")
MODEL_PATH = Path("models/yolov8n.pt")
CONF_THRESHOLD = 0.35
SMOOTH_WINDOW = 10   # frames of trajectory used for speed smoothing

VEHICLE_CLASSES = {1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

def color_for_id(tid: int):
    return int((tid * 53 + 150) % 256), int((tid * 17 + 80) % 256), int((tid * 37) % 256)

def side_of_line(p, a, b):
    """returns sign of cross product: which side of line ab point p is on."""
    return np.sign((b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]))

def main():
    assert CALIB_FILE.exists(), "run calibrate.py first"
    calib = json.loads(CALIB_FILE.read_text())
    mpp = calib["meters_per_pixel"]
    line = calib["counting_line"]
    assert len(line) == 2, "calibration missing counting line"
    a, b = tuple(line[0]), tuple(line[1])

    print(f"meters_per_pixel = {mpp:.5f}")
    print(f"counting line: {a} -> {b}")

    model = YOLO(str(MODEL_PATH))

    cap = cv2.VideoCapture(str(INPUT_VIDEO))
    fps_in = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    writer = cv2.VideoWriter(str(OUTPUT_VIDEO),
                             cv2.VideoWriter_fourcc(*"mp4v"),
                             fps_in, (width, height))

    history = defaultdict(lambda: deque(maxlen=SMOOTH_WINDOW))  # tid -> deque[(frame, cx, cy)]
    last_side = {}            # tid -> last side sign relative to counting line
    counted_in = set()        # ids that crossed inbound (negative -> positive side)
    counted_out = set()       # ids that crossed outbound (positive -> negative)
    track_class = {}
    speeds_per_id = defaultdict(list)

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

        if result.boxes is not None and result.boxes.id is not None:
            ids = result.boxes.id.int().cpu().tolist()
            classes = result.boxes.cls.int().cpu().tolist()
            xyxys = result.boxes.xyxy.cpu().tolist()

            for tid, cls_id, (x1, y1, x2, y2) in zip(ids, classes, xyxys):
                if cls_id not in VEHICLE_CLASSES:
                    continue
                name = VEHICLE_CLASSES[cls_id]
                track_class[tid] = name

                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                history[tid].append((frame_idx, cx, cy))

                # speed estimation
                speed_kmh = 0.0
                if len(history[tid]) >= 2:
                    f0, x0, y0 = history[tid][0]
                    f1, x1c, y1c = history[tid][-1]
                    if f1 > f0:
                        pix_dist = ((x1c - x0) ** 2 + (y1c - y0) ** 2) ** 0.5
                        meters = pix_dist * mpp
                        seconds = (f1 - f0) / fps_in
                        speed_kmh = (meters / seconds) * 3.6
                        speeds_per_id[tid].append(speed_kmh)

                # counting line crossing
                side = side_of_line((cx, cy), a, b)
                if tid in last_side and side != 0 and last_side[tid] != 0:
                    if last_side[tid] < 0 and side > 0:
                        counted_in.add(tid)
                    elif last_side[tid] > 0 and side < 0:
                        counted_out.add(tid)
                if side != 0:
                    last_side[tid] = side

                color = color_for_id(tid)
                x1i, y1i, x2i, y2i = int(x1), int(y1), int(x2), int(y2)
                cv2.rectangle(frame, (x1i, y1i), (x2i, y2i), color, 2)
                cv2.putText(frame, f"#{tid} {name} {speed_kmh:.0f}km/h",
                            (x1i, y1i - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        # draw counting line
        cv2.line(frame, a, b, (0, 255, 255), 2)

        # overlay stats
        total_crossed = len(counted_in) + len(counted_out)
        all_speeds = [s for lst in speeds_per_id.values() for s in lst]
        avg_speed = float(np.mean(all_speeds)) if all_speeds else 0.0
        overlays = [
            f"frame {frame_idx+1}",
            f"crossed in:  {len(counted_in)}",
            f"crossed out: {len(counted_out)}",
            f"total:       {total_crossed}",
            f"avg speed:   {avg_speed:.1f} km/h",
        ]
        for i, txt in enumerate(overlays):
            cv2.putText(frame, txt, (10, 25 + i * 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        writer.write(frame)
        frame_idx += 1

        if frame_idx % 60 == 0:
            print(f"  {frame_idx} frames | in={len(counted_in)} out={len(counted_out)} "
                  f"| avg {avg_speed:.1f} km/h")

    writer.release()

    elapsed = time.time() - t0
    print(f"\ndone. {frame_idx} frames in {elapsed:.1f}s ({frame_idx/elapsed:.1f} fps)")

    # per-class averages
    per_class_speed = defaultdict(list)
    for tid, speeds in speeds_per_id.items():
        if speeds:
            per_class_speed[track_class[tid]].append(float(np.mean(speeds)))

    summary = {
        "video": str(INPUT_VIDEO),
        "fps": fps_in,
        "meters_per_pixel": mpp,
        "counting_line": line,
        "unique_vehicles": len(track_class),
        "crossed_in": len(counted_in),
        "crossed_out": len(counted_out),
        "total_crossed": len(counted_in) + len(counted_out),
        "avg_speed_kmh_overall": float(np.mean([s for lst in speeds_per_id.values() for s in lst])) if speeds_per_id else 0.0,
        "avg_speed_kmh_by_class": {k: float(np.mean(v)) for k, v in per_class_speed.items()},
        "count_by_class": {k: sum(1 for tid, n in track_class.items() if n == k) for k in VEHICLE_CLASSES.values()},
    }
    OUTPUT_SUMMARY.write_text(json.dumps(summary, indent=2))
    print(f"\nsaved: {OUTPUT_SUMMARY}")
    print(f"saved: {OUTPUT_VIDEO}")
    print("\nsummary:")
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()