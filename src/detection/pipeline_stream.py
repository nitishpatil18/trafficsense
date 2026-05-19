"""
streaming version of the pipeline. exposes a generator that yields per-frame
state + events as they happen. the fastapi server consumes this.
"""
import json
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from threading import Thread, Lock
from typing import Iterator
import cv2
import numpy as np
from ultralytics import YOLO

from incidents import IncidentDetector

VEHICLE_CLASSES = {1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
SMOOTH_WINDOW = 30
EMA_ALPHA = 0.25
CONF_THRESHOLD = 0.35

def color_for_id(tid: int):
    return int((tid*53+150)%256), int((tid*17+80)%256), int((tid*37)%256)

def side_of_line(p, a, b):
    return np.sign((b[0]-a[0])*(p[1]-a[1]) - (b[1]-a[1])*(p[0]-a[0]))


@dataclass
class FrameState:
    frame_idx: int
    time_sec: float
    fps: float
    unique_vehicles: int
    counted_in: int
    counted_out: int
    median_speed_kmh: float
    count_by_class: dict
    new_events: list = field(default_factory=list)
    jpeg_bytes: bytes = b""  # annotated frame, jpeg encoded


class PipelineStream:
    def __init__(self, video_path: Path, calib_path: Path, model_path: Path):
        self.video_path = video_path
        self.model_path = model_path
        calib = json.loads(Path(calib_path).read_text())
        self.mpp = calib["meters_per_pixel"]
        line = calib["counting_line"]
        self.line_a, self.line_b = tuple(line[0]), tuple(line[1])

        cap = cv2.VideoCapture(str(video_path))
        self.fps_in = cap.get(cv2.CAP_PROP_FPS)
        self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()

    def run(self, loop: bool = True) -> Iterator[FrameState]:
        """yields FrameState objects per frame. if loop=true, restarts at end."""
        model = YOLO(str(self.model_path))

        while True:
            detector = IncidentDetector(fps=self.fps_in)
            history = defaultdict(lambda: deque(maxlen=SMOOTH_WINDOW))
            smoothed_speed = {}
            last_side = {}
            counted_in, counted_out = set(), set()
            track_class = {}
            frame_idx = 0

            for result in model.track(
                source=str(self.video_path),
                conf=CONF_THRESHOLD,
                tracker="bytetrack.yaml",
                persist=True,
                stream=True,
                verbose=False,
            ):
                frame = result.orig_img.copy()
                frame_speeds = []
                frame_track_data = []

                if result.boxes is not None and result.boxes.id is not None:
                    ids = result.boxes.id.int().cpu().tolist()
                    classes = result.boxes.cls.int().cpu().tolist()
                    xyxys = result.boxes.xyxy.cpu().tolist()

                    for tid, cls_id, (x1,y1,x2,y2) in zip(ids, classes, xyxys):
                        if cls_id not in VEHICLE_CLASSES:
                            continue
                        name = VEHICLE_CLASSES[cls_id]
                        track_class[tid] = name
                        cx, cy = (x1+x2)/2, (y1+y2)/2
                        history[tid].append((frame_idx, cx, cy))

                        speed = 0.0
                        if len(history[tid]) >= 2:
                            f0,x0,y0 = history[tid][0]
                            f1,xc,yc = history[tid][-1]
                            if f1 > f0:
                                pix = ((xc-x0)**2 + (yc-y0)**2) ** 0.5
                                sec = (f1-f0)/self.fps_in
                                speed = (pix*self.mpp/sec)*3.6
                        prev = smoothed_speed.get(tid, speed)
                        speed = EMA_ALPHA*speed + (1-EMA_ALPHA)*prev
                        smoothed_speed[tid] = speed
                        frame_speeds.append(speed)
                        frame_track_data.append((tid, name, cx, cy, speed, (x1,y1,x2,y2)))

                        side = side_of_line((cx,cy), self.line_a, self.line_b)
                        if tid in last_side and side != 0 and last_side[tid] != 0:
                            if last_side[tid] < 0 and side > 0:
                                counted_in.add(tid)
                            elif last_side[tid] > 0 and side < 0:
                                counted_out.add(tid)
                        if side != 0:
                            last_side[tid] = side

                median_speed = float(np.median(frame_speeds)) if frame_speeds else 0.0

                # incidents + draw
                events_this_frame = []
                for tid, name, cx, cy, speed, (x1,y1,x2,y2) in frame_track_data:
                    evs = detector.update(frame_idx, tid, name, speed, (cx,cy), median_speed)
                    events_this_frame.extend(evs)

                    color = color_for_id(tid)
                    is_evt = any(e.track_id == tid for e in evs)
                    bc = (0,0,255) if is_evt else color
                    th = 4 if is_evt else 2
                    x1i,y1i,x2i,y2i = int(x1),int(y1),int(x2),int(y2)
                    cv2.rectangle(frame, (x1i,y1i), (x2i,y2i), bc, th)
                    label = f"#{tid} {name} {speed:.0f}km/h"
                    cv2.putText(frame, label, (x1i, y1i-6),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, bc, 2)

                cv2.line(frame, self.line_a, self.line_b, (0,255,255), 2)

                # overlays
                overlays = [
                    f"frame {frame_idx+1}",
                    f"unique: {len(track_class)}",
                    f"in/out: {len(counted_in)}/{len(counted_out)}",
                    f"median speed: {median_speed:.1f} km/h",
                ]
                for i, txt in enumerate(overlays):
                    cv2.putText(frame, txt, (10, 25+i*24),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 2)

                # count by class
                cbc = {k: 0 for k in VEHICLE_CLASSES.values()}
                for n in track_class.values():
                    cbc[n] = cbc.get(n, 0) + 1

                # encode jpeg
                # downscale to 854x480 max and lower jpeg quality for streaming
                h, w = frame.shape[:2]
                if w > 854:
                    new_w, new_h = 854, int(h * 854 / w)
                    stream_frame = cv2.resize(frame, (new_w, new_h))
                else:
                    stream_frame = frame
                ok, buf = cv2.imencode(".jpg", stream_frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
                jpeg = buf.tobytes() if ok else b""

                yield FrameState(
                    frame_idx=frame_idx,
                    time_sec=frame_idx/self.fps_in,
                    fps=self.fps_in,
                    unique_vehicles=len(track_class),
                    counted_in=len(counted_in),
                    counted_out=len(counted_out),
                    median_speed_kmh=median_speed,
                    count_by_class=cbc,
                    new_events=[e.to_dict() for e in events_this_frame],
                    jpeg_bytes=jpeg,
                )
                frame_idx += 1

            if not loop:
                break