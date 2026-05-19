"""
yolov8 + bytetrack: assign persistent ids to vehicles across frames.
outputs annotated video, per-id trajectory log, and total unique vehicle count.
"""
import time
import json
from collections import defaultdict
from pathlib import Path
import cv2
from ultralytics import YOLO

INPUT_VIDEO = Path("data/videos/traffic_sample.mp4")
OUTPUT_VIDEO = Path("outputs/traffic_tracked.mp4")
OUTPUT_LOG = Path("outputs/tracks.json")
MODEL_PATH = Path("models/yolov8n.pt")
CONF_THRESHOLD = 0.35

VEHICLE_CLASSES = {1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

# colour per id (deterministic, so same id = same colour across frames)
def color_for_id(track_id: int):
    rng_r = (track_id * 37) % 256
    rng_g = (track_id * 17 + 80) % 256
    rng_b = (track_id * 53 + 150) % 256
    return int(rng_b), int(rng_g), int(rng_r)

def main():
    assert INPUT_VIDEO.exists(), f"video not found: {INPUT_VIDEO}"
    OUTPUT_VIDEO.parent.mkdir(exist_ok=True)

    print(f"loading model from {MODEL_PATH}...")
    model = YOLO(str(MODEL_PATH))

    cap = cv2.VideoCapture(str(INPUT_VIDEO))
    fps_in = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"video: {width}x{height} @ {fps_in:.1f}fps, {total_frames} frames")

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(OUTPUT_VIDEO), fourcc, fps_in, (width, height))

    # storage
    track_history = defaultdict(list)   # id -> list of (frame, cx, cy)
    track_class = {}                    # id -> class name
    unique_ids_seen = set()

    frame_idx = 0
    t0 = time.time()

    # stream=True saves memory; persist=True keeps tracker state across calls
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
            confs = result.boxes.conf.cpu().tolist()

            for tid, cls_id, (x1, y1, x2, y2), conf in zip(ids, classes, xyxys, confs):
                if cls_id not in VEHICLE_CLASSES:
                    continue
                name = VEHICLE_CLASSES[cls_id]
                track_class[tid] = name
                unique_ids_seen.add(tid)

                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                track_history[tid].append((frame_idx, float(cx), float(cy)))

                color = color_for_id(tid)
                x1i, y1i, x2i, y2i = int(x1), int(y1), int(x2), int(y2)
                cv2.rectangle(frame, (x1i, y1i), (x2i, y2i), color, 2)
                cv2.putText(frame, f"#{tid} {name}", (x1i, y1i - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

                # draw recent trail (last 30 points)
                trail = track_history[tid][-30:]
                for i in range(1, len(trail)):
                    _, px1, py1 = trail[i - 1]
                    _, px2, py2 = trail[i]
                    cv2.line(frame, (int(px1), int(py1)), (int(px2), int(py2)),
                             color, 2)

        # overlay
        cv2.putText(frame, f"frame {frame_idx+1}/{total_frames}", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.putText(frame, f"unique vehicles so far: {len(unique_ids_seen)}",
                    (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

        writer.write(frame)
        frame_idx += 1

        if frame_idx % 60 == 0:
            elapsed = time.time() - t0
            print(f"  {frame_idx}/{total_frames} | unique ids: {len(unique_ids_seen)} "
                  f"| {frame_idx/elapsed:.1f} fps")

    cap.release()
    writer.release()

    elapsed = time.time() - t0
    print(f"\ndone. {frame_idx} frames in {elapsed:.1f}s ({frame_idx/elapsed:.1f} fps)")
    print(f"total unique vehicles tracked: {len(unique_ids_seen)}")

    # per-class breakdown
    class_counts = defaultdict(int)
    for tid, name in track_class.items():
        class_counts[name] += 1
    print("breakdown:")
    for name, c in sorted(class_counts.items(), key=lambda x: -x[1]):
        print(f"  {name}: {c}")

    # save tracks for later modules (speed est, incident detection)
    log = {
        "video": str(INPUT_VIDEO),
        "fps": fps_in,
        "frame_count": frame_idx,
        "unique_vehicles": len(unique_ids_seen),
        "class_counts": dict(class_counts),
        "tracks": {str(tid): {
            "class": track_class[tid],
            "points": track_history[tid],
        } for tid in track_history},
    }
    with open(OUTPUT_LOG, "w") as f:
        json.dump(log, f, indent=2)
    print(f"\nsaved tracks: {OUTPUT_LOG}")
    print(f"saved video:  {OUTPUT_VIDEO}")

if __name__ == "__main__":
    main()