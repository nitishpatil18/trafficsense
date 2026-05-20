# TrafficSense

an intelligent transport system that integrates real-time computer-vision-based vehicle perception with adaptive traffic signal control, on a single backend, with one operator dashboard.

**headline results:**
- **+46.2%** average wait-time reduction vs fixed-timer baseline on a synthetic 4-way junction with asymmetric demand
- **+16.0%** wait-time reduction on a real bengaluru intersection (ms ramaiah road, mathikere) extracted from openstreetmap

both numbers are from SUMO's official tripinfo output, reproducible with seed 42.

---

## what this does

| layer | what it does |
|---|---|
| perception | detects vehicles (yolov8s) + assigns persistent ids (bytetrack) + estimates per-vehicle speed + counts directional flow + flags incidents (stopped, sudden-brake) |
| control | runs a sumo simulation of a signalised junction; compares fixed-timer baseline against a webster-style adaptive controller |
| integration | when a HIGH-severity incident is detected by the vision pipeline, the system automatically preempts the relevant signal phase |
| dashboard | live operator ui showing the annotated video, kpis, incident log, signal state, queue depth, and the headline comparison number |

---

## stack

- **backend:** python 3.11, fastapi, ultralytics (yolov8), opencv, eclipse-sumo + traci
- **frontend:** vite, react 18, tailwind css 3, recharts
- **simulation:** sumo 1.26
- **package management:** uv (python), npm (node)

runs end-to-end on a single laptop, cpu only, no gpu required.

---

## quick start

### prerequisites

```bash
# uv (python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# node (for the dashboard)
# install from https://nodejs.org or via brew: brew install node
```

### setup

```bash
git clone https://github.com/nitishpatil18/trafficsense.git
cd trafficsense

# install python deps
uv sync

# install dashboard deps
cd dashboard && npm install && cd ..
```

### download the test video

place any traffic video at `data/videos/traffic_sample.mp4`. for the included calibration to work, an overhead cctv-style clip works best.

### one-time calibration

```bash
uv run python src/detection/calibrate.py
```

a window appears. click 4 points:
1-2. across a road feature whose real distance you know (e.g. one lane width, then enter 3.5)
3-4. across the road to draw a counting line

saves `outputs/calibration.json`.

### run the backend

```bash
PYTHONPATH=src/detection uv run uvicorn server:app --host 0.0.0.0 --port 8000
```

### run the dashboard

in a second terminal:

```bash
cd dashboard
npm run dev
```

open <http://localhost:5173> in a browser.

---

## reproducing the signal-control benchmark

### synthetic 4-way junction

```bash
uv run python src/signals/run_fixed.py
uv run python src/signals/run_adaptive.py
uv run python src/signals/compare.py
```

expected output: `+46.2%` wait-time reduction.

### real bengaluru intersection

```bash
# regenerate traffic demand
RANDOMTRIPS=$(uv run python -c "import os, sumo; print(os.path.join(os.path.dirname(sumo.__file__), 'tools', 'randomTrips.py'))")
uv run python "$RANDOMTRIPS" \
  -n src/signals/network_real/intersection.net.xml \
  -e 600 -p 0.5 --fringe-factor 5 \
  --route-file src/signals/network_real/routes.rou.xml \
  --validate --seed 42

# run benchmarks
NETWORK=network_real uv run python src/signals/run_fixed.py
NETWORK=network_real uv run python src/signals/run_adaptive.py
```

results saved to `src/signals/fixed_log_real.json` and `adaptive_log_real.json`.

---

## project structure

```
trafficsense/
├── src/
│   ├── detection/                    # cv pipeline + fastapi server
│   │   ├── pipeline_stream.py        # streaming yolov8 + bytetrack pipeline
│   │   ├── incidents.py              # rule-based incident detector
│   │   ├── server.py                 # fastapi server (rest + ws + mjpeg)
│   │   ├── calibrate.py              # interactive calibration tool
│   │   └── pipeline.py               # standalone offline pipeline
│   │
│   └── signals/                      # sumo signal control
│       ├── sumo_stream.py            # live sumo runner for dashboard
│       ├── run_fixed.py              # fixed-timer baseline benchmark
│       ├── run_adaptive.py           # adaptive controller benchmark
│       ├── compare.py                # benchmark comparison
│       ├── network/                  # synthetic 4-way junction
│       └── network_real/             # real bengaluru osm network
│
├── dashboard/                        # react frontend
│   ├── src/App.jsx                   # main dashboard component
│   └── ...
│
├── data/videos/                      # input videos (gitignored)
├── models/                           # yolo weights (gitignored)
├── outputs/                          # runtime artefacts, calibration json
└── README.md
```

---

## api reference

| endpoint | method | purpose |
|---|---|---|
| `/summary` | GET | current perception kpis |
| `/events` | GET | recent incident events |
| `/frame.jpg` | GET | latest annotated frame (jpeg) |
| `/stream.mjpg` | GET | persistent mjpeg video stream |
| `/ws/stream` | WS | live json updates over websocket |
| `/signal/state` | GET | live sumo phase, queues, switch count |
| `/signal/comparison` | GET | benchmark numbers (synthetic + bengaluru) |
| `/signal/preempt` | POST | manually trigger emergency green |
| `/debug/fake_incident` | POST | inject a synthetic HIGH incident |

---

## limitations (honest)

- detection accuracy is qualitative on the test clip; mAP on labelled indian traffic data was not computed.
- camera calibration is a single meters-per-pixel scalar, not a 4-point homography; speeds far from the calibration point are approximate.
- incident thresholds are tuned for one scene; production deployment would auto-tune.
- adaptive controller is rule-based webster-style, not learned (deep RL was scoped out).
- real-network result adapts only one junction; multi-junction coordination is future work.
- the cv→signal trigger uses synthetic injection in the demo because a public-domain indian clip with the exact speed regime our thresholds expect could not be obtained.

these limitations are detailed in the final report (chapter 8).

---

## future work

- multi-junction coordinated control
- homographic camera calibration (4-point)
- fine-tune yolov8s on the indian driving dataset
- live rtsp/cctv ingestion
- deep reinforcement learning controller
- multi-camera fusion in world coordinates
- edge deployment on nvidia jetson or apple neural engine

---

## team

| name | usn |
|---|---|
| nitish patil | 1MS23CI079 |
| pramod mg | — |
| satyan torushe | — |

**institution:** ramaiah institute of technology, bengaluru
**department:** computer science engineering (ai & ml)
**team code:** CI39
**academic year:** 2025–2026

---

## license

mit. see `LICENSE` for details. (open-source dependencies retain their own licences; SUMO is EPL-2.0.)

---

## acknowledgements

built on top of: [eclipse sumo](https://eclipse.dev/sumo/), [ultralytics yolov8](https://github.com/ultralytics/ultralytics), [bytetrack](https://github.com/ifzhang/ByteTrack), [fastapi](https://fastapi.tiangolo.com), [react](https://react.dev), [tailwind css](https://tailwindcss.com), [recharts](https://recharts.org).