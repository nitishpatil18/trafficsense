"""
real-time incident detection on top of tracked vehicles.
events: STOPPED (relative to median speed), SUDDEN_BRAKE (rapid deceleration).
"""
from collections import defaultdict, deque
from dataclasses import dataclass, asdict
from typing import Optional

@dataclass
class Event:
    frame: int
    time_sec: float
    track_id: int
    vehicle_class: str
    event_type: str           # "STOPPED" | "SUDDEN_BRAKE"
    severity: str             # "LOW" | "MEDIUM" | "HIGH"
    speed_kmh: float
    median_speed_kmh: float
    position: tuple           # (cx, cy) in pixels

    def to_dict(self):
        return asdict(self)


class IncidentDetector:
    """
    state machine per track_id. consumes (frame, speed, pos) updates,
    returns events when fired.
    """
    def __init__(
        self,
        fps: float,
        stopped_ratio: float = 0.20,
        stopped_duration_sec: float = 3.0,
        min_median_kmh: float = 8.0,
        brake_drop_kmh: float = 25.0,
        brake_min_peak_kmh: float = 25.0,   # NEW: must have been going fast before braking counts
        brake_window_sec: float = 0.5,
        cooldown_sec: float = 8.0,
    ):
        self.fps = fps
        self.stopped_ratio = stopped_ratio
        self.stopped_frames = int(stopped_duration_sec * fps)
        self.min_median_kmh = min_median_kmh
        self.brake_drop_kmh = brake_drop_kmh
        self.brake_min_peak_kmh = brake_min_peak_kmh
        self.brake_window = int(brake_window_sec * fps)
        self.cooldown_frames = int(cooldown_sec * fps)

        # per-track state
        self.speed_history: dict[int, deque] = defaultdict(
            lambda: deque(maxlen=max(self.stopped_frames, self.brake_window) + 5)
        )
        self.last_event_frame: dict[tuple[int, str], int] = {}

    def update(
        self,
        frame_idx: int,
        track_id: int,
        vehicle_class: str,
        speed_kmh: float,
        position: tuple,
        median_speed_kmh: float,
    ) -> list[Event]:
        self.speed_history[track_id].append(speed_kmh)
        events: list[Event] = []

        # STOPPED check
        if (median_speed_kmh >= self.min_median_kmh
                and len(self.speed_history[track_id]) >= self.stopped_frames):
            recent = list(self.speed_history[track_id])[-self.stopped_frames:]
            if max(recent) < median_speed_kmh * self.stopped_ratio:
                if self._allow(track_id, "STOPPED", frame_idx):
                    events.append(Event(
                        frame=frame_idx,
                        time_sec=frame_idx / self.fps,
                        track_id=track_id,
                        vehicle_class=vehicle_class,
                        event_type="STOPPED",
                        severity="MEDIUM",
                        speed_kmh=round(speed_kmh, 2),
                        median_speed_kmh=round(median_speed_kmh, 2),
                        position=(round(position[0], 1), round(position[1], 1)),
                    ))

        # SUDDEN_BRAKE check
        if len(self.speed_history[track_id]) >= self.brake_window:
            window = list(self.speed_history[track_id])[-self.brake_window:]
            drop = max(window) - min(window)
            # ensure direction is "high then low"
            peak_idx = window.index(max(window))
            trough_idx = window.index(min(window))
            peak_speed = max(window)
            if (drop >= self.brake_drop_kmh
                    and peak_speed >= self.brake_min_peak_kmh
                    and trough_idx > peak_idx):
                if self._allow(track_id, "SUDDEN_BRAKE", frame_idx):
                    severity = "HIGH" if drop >= self.brake_drop_kmh * 1.5 else "MEDIUM"
                    events.append(Event(
                        frame=frame_idx,
                        time_sec=frame_idx / self.fps,
                        track_id=track_id,
                        vehicle_class=vehicle_class,
                        event_type="SUDDEN_BRAKE",
                        severity=severity,
                        speed_kmh=round(speed_kmh, 2),
                        median_speed_kmh=round(median_speed_kmh, 2),
                        position=(round(position[0], 1), round(position[1], 1)),
                    ))

        return events

    def _allow(self, tid: int, etype: str, frame_idx: int) -> bool:
        key = (tid, etype)
        last = self.last_event_frame.get(key, -10_000_000)
        if frame_idx - last >= self.cooldown_frames:
            self.last_event_frame[key] = frame_idx
            return True
        return False