"""
run yolov8 on a video file, save annotated output with bounding boxes,
per-frame counts, and fps stats.
"""
import time
from pathlib import Path
import cv2
from ultralytics import YOLO

# config
INPUT_VIDEO = Path("data/videos/traffic_sample.mp4")
OUTPUT_VIDEO = Path("outputs/traffic_annotated.mp4")
MODEL_PATH = Path("models/yolov8n.pt")
CONF_THRESHOLD = 0.35

# coco classes we care about (vehicles only)
VEHICLE_CLASSES = {1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

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

    frame_idx = 0
    total_vehicles = 0
    t0 = time.time()

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        results = model.predict(frame, conf=CONF_THRESHOLD, verbose=False)[0]

        # count vehicles in this frame
        counts = {name: 0 for name in VEHICLE_CLASSES.values()}
        for box in results.boxes:
            cls_id = int(box.cls[0])
            if cls_id not in VEHICLE_CLASSES:
                continue
            name = VEHICLE_CLASSES[cls_id]
            counts[name] += 1
            conf = float(box.conf[0])
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, f"{name} {conf:.0%}", (x1, y1 - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        frame_total = sum(counts.values())
        total_vehicles += frame_total

        # overlay summary
        y = 25
        cv2.putText(frame, f"frame {frame_idx+1}/{total_frames}", (10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        for name, c in counts.items():
            if c == 0:
                continue
            y += 22
            cv2.putText(frame, f"{name}: {c}", (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

        writer.write(frame)
        frame_idx += 1

        if frame_idx % 30 == 0:
            elapsed = time.time() - t0
            print(f"  processed {frame_idx}/{total_frames} frames "
                  f"({frame_idx/elapsed:.1f} fps)")

    cap.release()
    writer.release()

    elapsed = time.time() - t0
    print(f"\ndone. {frame_idx} frames in {elapsed:.1f}s ({frame_idx/elapsed:.1f} fps)")
    print(f"avg vehicles/frame: {total_vehicles/max(frame_idx,1):.1f}")
    print(f"output: {OUTPUT_VIDEO}")

if __name__ == "__main__":
    main()