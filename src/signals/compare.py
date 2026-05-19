"""
prints the headline number: % improvement of adaptive over fixed.
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
fixed = json.loads((HERE / "fixed_log.json").read_text())["summary"]
adaptive = json.loads((HERE / "adaptive_log.json").read_text())["summary"]

print("\n=== FIXED ===")
for k, v in fixed.items():
    print(f"  {k}: {v}")
print("\n=== ADAPTIVE ===")
for k, v in adaptive.items():
    print(f"  {k}: {v}")

f_wait = fixed["avg_wait_time_sec"]
a_wait = adaptive["avg_wait_time_sec"]
improvement = (f_wait - a_wait) / f_wait * 100 if f_wait > 0 else 0.0

f_travel = fixed["avg_travel_time_sec"]
a_travel = adaptive["avg_travel_time_sec"]
travel_improvement = (f_travel - a_travel) / f_travel * 100 if f_travel > 0 else 0.0

print("\n=== HEADLINE ===")
print(f"avg wait time: fixed {f_wait}s  ->  adaptive {a_wait}s")
print(f"  improvement: {improvement:+.1f}%")
print(f"avg travel time: fixed {f_travel}s -> adaptive {a_travel}s")
print(f"  improvement: {travel_improvement:+.1f}%")