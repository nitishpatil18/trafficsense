"""
interactive calibration: click two points on a frame and enter the real-world
distance between them in meters. saves meters_per_pixel and a counting line.
"""
import json
from pathlib import Path
import cv2

INPUT_VIDEO = Path("data/videos/incident_sample.mp4")
CALIB_FILE = Path("outputs/calibration_incident.json")

clicks = []
line_pts = []
mode = "calib"   # "calib" -> "line" -> "done"

def on_mouse(event, x, y, flags, param):
    global mode
    if event != cv2.EVENT_LBUTTONDOWN:
        return
    if mode == "calib" and len(clicks) < 2:
        clicks.append((x, y))
        if len(clicks) == 2:
            mode = "line"
            print("now click 2 points to define the counting line (a virtual line "
                  "vehicles must cross to be counted).")
    elif mode == "line" and len(line_pts) < 2:
        line_pts.append((x, y))
        if len(line_pts) == 2:
            mode = "done"

def main():
    CALIB_FILE.parent.mkdir(exist_ok=True)
    cap = cv2.VideoCapture(str(INPUT_VIDEO))
    # use frame 100 (more stable than frame 0)
    cap.set(cv2.CAP_PROP_POS_FRAMES, 100)
    ok, frame = cap.read()
    cap.release()
    assert ok, "could not read frame"

    cv2.namedWindow("calibrate")
    cv2.setMouseCallback("calibrate", on_mouse)

    print("step 1: click 2 points on the road whose real-world distance you know.")
    print("        good choice: across a lane (~3.5m), or along a lane marker (~3m dash).")
    print("        press 'r' to reset, 'q' to quit.")

    while True:
        disp = frame.copy()
        # draw clicks
        for i, p in enumerate(clicks):
            cv2.circle(disp, p, 6, (0, 0, 255), -1)
            cv2.putText(disp, f"c{i+1}", (p[0] + 8, p[1] - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        if len(clicks) == 2:
            cv2.line(disp, clicks[0], clicks[1], (0, 0, 255), 2)
        for i, p in enumerate(line_pts):
            cv2.circle(disp, p, 6, (0, 255, 255), -1)
            cv2.putText(disp, f"L{i+1}", (p[0] + 8, p[1] - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        if len(line_pts) == 2:
            cv2.line(disp, line_pts[0], line_pts[1], (0, 255, 255), 2)

        cv2.putText(disp, f"mode: {mode}", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.imshow("calibrate", disp)
        key = cv2.waitKey(20) & 0xff
        if key == ord("q"):
            return
        if key == ord("r"):
            clicks.clear(); line_pts.clear()
            globals()["mode"] = "calib"
        if mode == "done":
            cv2.imshow("calibrate", disp)
            cv2.waitKey(500)
            break

    cv2.destroyAllWindows()

    # compute meters per pixel
    (x1, y1), (x2, y2) = clicks
    pix_dist = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
    real_m = float(input(f"\nyou clicked 2 points {pix_dist:.1f} px apart.\n"
                         f"enter real-world distance between them in meters "
                         f"(e.g. 3.5 for a lane width): "))
    mpp = real_m / pix_dist

    out = {
        "video": str(INPUT_VIDEO),
        "calib_points": clicks,
        "calib_real_meters": real_m,
        "pixel_distance": pix_dist,
        "meters_per_pixel": mpp,
        "counting_line": line_pts,
    }
    with open(CALIB_FILE, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nmeters_per_pixel = {mpp:.5f}")
    print(f"saved: {CALIB_FILE}")

if __name__ == "__main__":
    main()