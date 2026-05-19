"""
adaptive signal control: reallocates green time every 10 seconds based on
real-time queue lengths. minimum 10s, maximum 50s per phase.
phase 0 = NS green, phase 2 = EW green (phases 1 and 3 are yellows).
"""
import json
import xml.etree.ElementTree as ET
from pathlib import Path
import traci

NETWORK_DIR = Path(__file__).parent / "network"
SUMOCFG = NETWORK_DIR / "simulation.sumocfg"
OUTPUT_LOG = Path(__file__).parent / "adaptive_log.json"

TLS_ID = "center"      # node id became the tls id
MIN_GREEN = 10
MAX_GREEN = 50
YELLOW = 3

def queue_on(edges):
    return sum(traci.edge.getLastStepHaltingNumber(e) for e in edges)

def main():
    tripinfo = Path(__file__).parent / "adaptive_tripinfo.xml"
    sumo_cmd = [
        "sumo", "-c", str(SUMOCFG),
        "--no-warnings", "true",
        "--tripinfo-output", str(tripinfo),
    ]
    traci.start(sumo_cmd)

    # discover phase indices. the generated tls usually has 4 phases:
    # 0: NS green, 1: NS yellow, 2: EW green, 3: EW yellow
    logic = traci.trafficlight.getAllProgramLogics(TLS_ID)[0]
    print(f"tls {TLS_ID} has {len(logic.phases)} phases:")
    for i, p in enumerate(logic.phases):
        print(f"  phase {i}: state={p.state} dur={p.duration}")

    NS_GREEN_PHASE = 0
    EW_GREEN_PHASE = 2

    timeline = []
    arrived = 0
    current_phase = NS_GREEN_PHASE
    traci.trafficlight.setPhase(TLS_ID, current_phase)
    green_started = 0
    decision_log = []

    step = 0
    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()
        step += 1

        ns_q = queue_on(["n2c", "s2c"])
        ew_q = queue_on(["e2c", "w2c"])
        arrived += traci.simulation.getArrivedNumber()

        timeline.append({
            "t": step,
            "phase": traci.trafficlight.getPhase(TLS_ID),
            "ns_q": ns_q, "ew_q": ew_q,
        })

        # decide if we should switch
        phase_now = traci.trafficlight.getPhase(TLS_ID)
        # only act during green phases
        if phase_now in (NS_GREEN_PHASE, EW_GREEN_PHASE):
            green_elapsed = step - green_started
            is_ns = phase_now == NS_GREEN_PHASE
            my_q = ns_q if is_ns else ew_q
            other_q = ew_q if is_ns else ns_q

            should_switch = False
            if green_elapsed >= MAX_GREEN:
                should_switch = True
                reason = "max_green"
            elif green_elapsed >= MIN_GREEN and other_q > my_q * 1.5 and other_q >= 3:
                should_switch = True
                reason = "other_dir_heavier"
            else:
                reason = "hold"

            if should_switch:
                next_phase = phase_now + 1   # go to yellow
                traci.trafficlight.setPhase(TLS_ID, next_phase)
                decision_log.append({
                    "t": step, "from": phase_now, "to": next_phase,
                    "green_elapsed": green_elapsed,
                    "ns_q": ns_q, "ew_q": ew_q, "reason": reason,
                })
        else:
            # we're in yellow. when it ends, sumo advances naturally; we just
            # detect the transition to track green start time.
            if phase_now in (1, 3):
                # check if next step we'll be in green
                pass

        # detect green-phase entry to reset green_started
        if step > 1:
            prev = timeline[-2]["phase"]
            cur = timeline[-1]["phase"]
            if cur in (NS_GREEN_PHASE, EW_GREEN_PHASE) and prev != cur:
                green_started = step

    traci.close()

    # parse tripinfo
    waits, travels = [], []
    tree = ET.parse(tripinfo)
    for trip in tree.getroot().findall("tripinfo"):
        waits.append(float(trip.get("waitingTime")))
        travels.append(float(trip.get("duration")))
    avg_wait = sum(waits) / max(len(waits), 1)
    avg_travel = sum(travels) / max(len(travels), 1)

    summary = {
        "controller": "adaptive",
        "duration_sec": step,
        "vehicles_arrived": arrived,
        "completed_trips": len(waits),
        "avg_wait_time_sec": round(avg_wait, 2),
        "avg_travel_time_sec": round(avg_travel, 2),
        "switch_decisions": len(decision_log),
    }
    OUTPUT_LOG.write_text(json.dumps({
        "summary": summary,
        "decisions": decision_log,
        "timeline": timeline,
    }, indent=2))
    print(json.dumps(summary, indent=2))
    print(f"saved: {OUTPUT_LOG}")

if __name__ == "__main__":
    main()