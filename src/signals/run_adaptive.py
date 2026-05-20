"""
adaptive signal control: reallocates green time every 10 seconds based on
real-time queue lengths. minimum 10s, maximum 50s per phase.
phase 0 = NS green, phase 2 = EW green (phases 1 and 3 are yellows).
"""
import json
import xml.etree.ElementTree as ET
from pathlib import Path
import traci

import os
NETWORK_NAME = os.environ.get("NETWORK", "network")
NETWORK_DIR = Path(__file__).parent / NETWORK_NAME
SUMOCFG = NETWORK_DIR / "simulation.sumocfg"
SUFFIX = "" if NETWORK_NAME == "network" else f"_{NETWORK_NAME.replace('network_', '')}"
OUTPUT_LOG = Path(__file__).parent / f"adaptive_log{SUFFIX}.json"

# TLS_ID is discovered at runtime since osm-derived networks have unpredictable ids
TLS_ID = None
MIN_GREEN = 10
MAX_GREEN = 50
YELLOW = 3

def queue_on(edges):
    return sum(traci.edge.getLastStepHaltingNumber(e) for e in edges)

def discover_incoming_edges(tls_id):
    """
    group incoming edges of a tls into 2 perpendicular axes.
    no cardinal assumption: we find the dominant heading, call that axis A,
    and put edges within 45deg of it (or 180deg opposite) into A; rest into B.
    """
    import math
    lanes = traci.trafficlight.getControlledLanes(tls_id)
    edge_headings = {}
    for lane in lanes:
        edge = traci.lane.getEdgeID(lane)
        if edge in edge_headings:
            continue
        shape = traci.lane.getShape(lane)
        if len(shape) < 2:
            continue
        (x1, y1), (x2, y2) = shape[-2], shape[-1]
        heading = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 360
        edge_headings[edge] = heading

    if not edge_headings:
        return [], []

    # use the first edge's heading as anchor for axis A
    anchor = next(iter(edge_headings.values()))
    axis_a, axis_b = [], []
    for edge, h in edge_headings.items():
        # distance to anchor, folded to [0, 180]
        diff = abs(h - anchor) % 360
        if diff > 180:
            diff = 360 - diff
        # axis A: heading is similar to anchor OR exactly opposite (~180deg apart)
        if diff < 45 or diff > 135:
            axis_a.append(edge)
        else:
            axis_b.append(edge)
    return axis_a, axis_b

def main():
    tripinfo = Path(__file__).parent / f"adaptive_tripinfo{SUFFIX}.xml"
    sumo_cmd = [
        "sumo", "-c", str(SUMOCFG),
        "--no-warnings", "true",
        "--tripinfo-output", str(tripinfo),
    ]
    traci.start(sumo_cmd)
    global TLS_ID
    # find the busiest tls in the network (the one with most controlled lanes)
    all_tls = traci.trafficlight.getIDList()
    if not all_tls:
        print("ERROR: no traffic light in network")
        traci.close()
        return
    TLS_ID = max(all_tls, key=lambda t: len(traci.trafficlight.getControlledLanes(t)))
    print(f"controlling tls: {TLS_ID} (out of {len(all_tls)} tls in network)")

    # discover phase indices. the generated tls usually has 4 phases:
    # 0: NS green, 1: NS yellow, 2: EW green, 3: EW yellow
    logic = traci.trafficlight.getAllProgramLogics(TLS_ID)[0]

    print(f"tls {TLS_ID} has {len(logic.phases)} phases:")
    for i, p in enumerate(logic.phases):
        print(f"  phase {i}: state={p.state} dur={p.duration}")

    AXIS_A_EDGES, AXIS_B_EDGES = discover_incoming_edges(TLS_ID)
    print(f"axis A edges ({len(AXIS_A_EDGES)}): {AXIS_A_EDGES[:3]}...")
    print(f"axis B edges ({len(AXIS_B_EDGES)}): {AXIS_B_EDGES[:3]}...")
    if not AXIS_A_EDGES or not AXIS_B_EDGES:
        print("ERROR: could not split incoming edges into two axes")
        traci.close()
        return
    
    # detect which phase serves which axis by inspecting controlled lanes per phase
    controlled_lanes = traci.trafficlight.getControlledLanes(TLS_ID)
    lane_to_axis = {}
    for lane in controlled_lanes:
        edge = traci.lane.getEdgeID(lane)
        if edge in AXIS_A_EDGES:
            lane_to_axis[lane] = "A"
        elif edge in AXIS_B_EDGES:
            lane_to_axis[lane] = "B"

    # for each green phase, count how many of its 'G' chars correspond to axis A vs B
    green_phases = []
    for i, p in enumerate(logic.phases):
        if "G" not in p.state and "g" not in p.state:
            continue
        a_green, b_green = 0, 0
        for idx, ch in enumerate(p.state):
            if ch.lower() == "g" and idx < len(controlled_lanes):
                ax = lane_to_axis.get(controlled_lanes[idx])
                if ax == "A":
                    a_green += 1
                elif ax == "B":
                    b_green += 1
        green_phases.append((i, a_green, b_green))
        print(f"  phase {i}: axis A green count={a_green}, axis B green count={b_green}")

    # pick the phase where A dominates as AXIS_A_PHASE; B-dominant as AXIS_B_PHASE
    axis_a_phase = max(green_phases, key=lambda x: x[1] - x[2])[0]
    axis_b_phase = max(green_phases, key=lambda x: x[2] - x[1])[0]
    print(f"axis A phase = {axis_a_phase}, axis B phase = {axis_b_phase}")

    timeline = []
    arrived = 0
    current_phase = axis_a_phase
    traci.trafficlight.setPhase(TLS_ID, current_phase)
    green_started = 0
    decision_log = []

    step = 0
    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()
        step += 1

        ns_q = queue_on(AXIS_A_EDGES)
        ew_q = queue_on(AXIS_B_EDGES)
        arrived += traci.simulation.getArrivedNumber()

        timeline.append({
            "t": step,
            "phase": traci.trafficlight.getPhase(TLS_ID),
            "ns_q": ns_q, "ew_q": ew_q,
        })

        # decide if we should switch
        phase_now = traci.trafficlight.getPhase(TLS_ID)
        # only act during green phases
        if phase_now in (axis_a_phase, axis_b_phase):
            green_elapsed = step - green_started
            is_ns = phase_now == axis_a_phase
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
            if cur in (axis_a_phase, axis_b_phase) and prev != cur:
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