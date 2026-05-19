"""
streaming sumo adaptive controller. runs continuously, exposes state via shared dict.
each "episode" is one 600-sec demand window; restarts in a loop for the dashboard.
"""
import threading
import time
from pathlib import Path
from typing import Optional
import traci

NETWORK_DIR = Path(__file__).parent / "network"
SUMOCFG = NETWORK_DIR / "simulation.sumocfg"

TLS_ID = "center"
NS_GREEN_PHASE = 0
EW_GREEN_PHASE = 2
MIN_GREEN = 10
MAX_GREEN = 50

PHASE_NAME = {0: "NS_GREEN", 1: "NS_YELLOW", 2: "EW_GREEN", 3: "EW_YELLOW"}


class SumoStream:
    def __init__(self):
        self._state = {
            "running": False,
            "t": 0,
            "phase": 0,
            "phase_name": "NS_GREEN",
            "queue": {"n": 0, "s": 0, "e": 0, "w": 0},
            "queue_total": 0,
            "vehicles_active": 0,
            "vehicles_arrived": 0,
            "total_wait_accum": 0.0,
            "switch_decisions": 0,
            "preempt_active": False,
            "preempt_direction": None,
            "preempt_until_step": 0,
            "episode": 0,
        }
        self._preempt_request: Optional[str] = None   # "NS" | "EW"
        self._lock = threading.Lock()
        self._stop = False

    @property
    def state(self) -> dict:
        with self._lock:
            return dict(self._state)

    def request_preempt(self, direction: str):
        """external trigger (e.g. cv incident) requests emergency green."""
        with self._lock:
            self._preempt_request = direction.upper()

    def stop(self):
        self._stop = True

    def run_forever(self):
        episode = 0
        while not self._stop:
            episode += 1
            self._run_one_episode(episode)

    def _run_one_episode(self, episode: int):
        sumo_cmd = ["sumo", "-c", str(SUMOCFG), "--no-warnings", "true", "--no-step-log", "true"]
        traci.start(sumo_cmd)
        with self._lock:
            self._state["running"] = True
            self._state["episode"] = episode

        green_started = 0
        switches = 0
        total_wait_accum = 0.0
        preempt_until = 0
        preempt_dir = None

        try:
            step = 0
            while traci.simulation.getMinExpectedNumber() > 0 and not self._stop:
                traci.simulationStep()
                step += 1

                ns_q_n = traci.edge.getLastStepHaltingNumber("n2c")
                ns_q_s = traci.edge.getLastStepHaltingNumber("s2c")
                ew_q_e = traci.edge.getLastStepHaltingNumber("e2c")
                ew_q_w = traci.edge.getLastStepHaltingNumber("w2c")
                ns_q = ns_q_n + ns_q_s
                ew_q = ew_q_e + ew_q_w

                vehs = traci.vehicle.getIDList()
                # accumulate wait time delta (sum of current waits is fine for a live read)
                sec_wait = sum(traci.vehicle.getWaitingTime(v) for v in vehs)
                total_wait_accum += sec_wait

                phase_now = traci.trafficlight.getPhase(TLS_ID)

                # preempt handling
                with self._lock:
                    req = self._preempt_request
                    self._preempt_request = None
                if req in ("NS", "EW"):
                    target_phase = NS_GREEN_PHASE if req == "NS" else EW_GREEN_PHASE
                    if phase_now != target_phase:
                        traci.trafficlight.setPhase(TLS_ID, phase_now + 1 if phase_now in (NS_GREEN_PHASE, EW_GREEN_PHASE) else phase_now)
                    preempt_until = step + 20   # hold preempt for 20s
                    preempt_dir = req

                in_preempt = step < preempt_until

                # adaptive switching (skip during preempt)
                if not in_preempt and phase_now in (NS_GREEN_PHASE, EW_GREEN_PHASE):
                    green_elapsed = step - green_started
                    is_ns = phase_now == NS_GREEN_PHASE
                    my_q = ns_q if is_ns else ew_q
                    other_q = ew_q if is_ns else ns_q
                    if green_elapsed >= MAX_GREEN:
                        traci.trafficlight.setPhase(TLS_ID, phase_now + 1)
                        switches += 1
                    elif green_elapsed >= MIN_GREEN and other_q > my_q * 1.5 and other_q >= 3:
                        traci.trafficlight.setPhase(TLS_ID, phase_now + 1)
                        switches += 1

                # track green-start
                if step > 1 and traci.trafficlight.getPhase(TLS_ID) in (NS_GREEN_PHASE, EW_GREEN_PHASE):
                    if step == 1 or self._state.get("phase", -1) != traci.trafficlight.getPhase(TLS_ID):
                        if traci.trafficlight.getPhase(TLS_ID) in (NS_GREEN_PHASE, EW_GREEN_PHASE):
                            green_started = step

                phase_now_after = traci.trafficlight.getPhase(TLS_ID)

                with self._lock:
                    self._state.update({
                        "t": step,
                        "phase": phase_now_after,
                        "phase_name": PHASE_NAME.get(phase_now_after, "?"),
                        "queue": {"n": ns_q_n, "s": ns_q_s, "e": ew_q_e, "w": ew_q_w},
                        "queue_total": ns_q + ew_q,
                        "vehicles_active": len(vehs),
                        "vehicles_arrived": self._state["vehicles_arrived"] + traci.simulation.getArrivedNumber(),
                        "total_wait_accum": round(total_wait_accum, 1),
                        "switch_decisions": switches,
                        "preempt_active": in_preempt,
                        "preempt_direction": preempt_dir if in_preempt else None,
                        "preempt_until_step": preempt_until if in_preempt else 0,
                    })

                # pace ~real-time (1 sumo step = 1 real second feels right for dashboard demos)
                time.sleep(0.1)   # speed up 10x so the demo doesn't take 10 min per episode

        finally:
            try:
                traci.close()
            except Exception:
                pass
            with self._lock:
                self._state["running"] = False
                self._state["vehicles_arrived"] = 0  # reset counter for next episode