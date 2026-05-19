"""
sanity check: download yolov8n, run on a sample image, save output.
if this runs and saves outputs/test_detection.jpg, your env is good.
"""
from pathlib import Path
from ultralytics import YOLO

OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

print("loading yolov8n...")
model = YOLO("yolov8n.pt")  # auto-downloads ~6mb on first run

print("running detection on sample image...")
results = model("https://ultralytics.com/images/bus.jpg", verbose=False)

for r in results:
    out_path = OUTPUT_DIR / "test_detection.jpg"
    r.save(filename=str(out_path))
    print(f"\nsaved: {out_path}")
    print(f"detected {len(r.boxes)} objects:")
    for box in r.boxes:
        cls_id = int(box.cls[0])
        conf = float(box.conf[0])
        name = model.names[cls_id]
        print(f"  - {name} ({conf:.2%})")

print("\nsetup verified.")