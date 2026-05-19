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

f_clear = fixed["duration_sec"]
a_clear = adaptive["duration_sec"]
clear_imp = (f_clear - a_clear) / f_clear * 100 if f_clear > 0 else 0.0

print("\n=== HEADLINE ===")
print(f"avg wait time:     fixed {f_wait:>6}s  ->  adaptive {a_wait:>6}s   ({improvement:+.1f}%)")
print(f"avg travel time:   fixed {f_travel:>6}s  ->  adaptive {a_travel:>6}s   ({travel_improvement:+.1f}%)")
print(f"queue clear time:  fixed {f_clear:>6}s  ->  adaptive {a_clear:>6}s   ({clear_imp:+.1f}%)")
print(f"trips completed:   fixed {fixed['completed_trips']:>6}     adaptive {adaptive['completed_trips']:>6}")