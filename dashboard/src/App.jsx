import { useEffect, useRef, useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, CartesianGrid,
} from "recharts";

const API = "http://localhost:8000";
const WS = "ws://localhost:8000/ws/stream";

const KPI = ({ label, value, sub }) => (
  <div className="bg-neutral-900 rounded-xl p-4 border border-neutral-800">
    <div className="text-xs uppercase tracking-wide text-neutral-400">{label}</div>
    <div className="text-3xl font-semibold mt-1 text-white">{value}</div>
    {sub && <div className="text-xs text-neutral-500 mt-1">{sub}</div>}
  </div>
);

const sevColor = (s) =>
  s === "HIGH" ? "bg-red-600" : s === "MEDIUM" ? "bg-amber-500" : "bg-neutral-500";

export default function App() {
  const [summary, setSummary] = useState(null);
  const [events, setEvents] = useState([]);
  const [speedSeries, setSpeedSeries] = useState([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef(null);

  // websocket
  useEffect(() => {
    let alive = true;
    const connect = () => {
      const ws = new WebSocket(WS);
      wsRef.current = ws;
      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        if (alive) setTimeout(connect, 1500);
      };
      let lastSeriesPush = 0;
      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        if (msg.type === "summary") {
          setSummary(msg);
          const now = Date.now();
          if (now - lastSeriesPush > 1000) {
            lastSeriesPush = now;
            setSpeedSeries((s) =>
              [...s, { t: msg.frame_idx, v: msg.median_speed_kmh }].slice(-30)
            );
          }
        } else if (msg.type === "events") {
          setEvents((prev) => [...msg.events.reverse(), ...prev].slice(0, 50));
        }
      };
    };
    connect();
    return () => { alive = false; wsRef.current?.close(); };
  }, []);

  // fetch initial events backlog once
  useEffect(() => {
    fetch(`${API}/events?limit=50`)
      .then((r) => r.json())
      .then((list) => setEvents(list.slice().reverse()))
      .catch(() => {});
  }, []);

  const cbc = summary?.count_by_class || {};
  const classChartData = Object.entries(cbc).map(([k, v]) => ({ name: k, count: v }));

  return (
    <div className="min-h-screen p-6">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-white">TrafficSense</h1>
          <p className="text-sm text-neutral-500">
            real-time vehicle detection, tracking, and incident monitoring
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${connected ? "bg-green-500" : "bg-red-500"}`} />
          <span className="text-sm text-neutral-400">
            {connected ? "live" : "disconnected"}
          </span>
        </div>
      </header>

      {/* kpi row */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
        <KPI label="frame" value={summary?.frame_idx ?? "-"} sub={`t = ${summary?.time_sec ?? 0}s`} />
        <KPI label="unique vehicles" value={summary?.unique_vehicles ?? "-"} />
        <KPI label="crossed in / out" value={`${summary?.counted_in ?? 0} / ${summary?.counted_out ?? 0}`} />
        <KPI label="median speed" value={`${summary?.median_speed_kmh ?? 0} km/h`} />
        <KPI label="total events" value={summary?.events_total ?? 0} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* live video */}
        <div className="lg:col-span-2 bg-neutral-900 rounded-xl border border-neutral-800 p-4">
          <div className="text-sm text-neutral-400 mb-2">live annotated feed</div>
          <img
            src={`${API}/stream.mjpg`}
            alt="live feed"
            className="w-full rounded-lg border border-neutral-800"
          />
          <div className="text-xs text-neutral-500 mt-2">
            refreshes 5x/sec. yellow line = counting line. red boxes = incident.
          </div>
        </div>

        {/* event log */}
        <div className="bg-neutral-900 rounded-xl border border-neutral-800 p-4 flex flex-col">
          <div className="text-sm text-neutral-400 mb-2">incident log ({events.length})</div>
          <div className="overflow-y-auto max-h-[520px] divide-y divide-neutral-800">
            {events.length === 0 && (
              <div className="text-neutral-500 text-sm py-4">no incidents yet.</div>
            )}
            {events.map((e, i) => (
              <div key={i} className="py-2 flex items-start gap-2">
                <span className={`text-xs px-2 py-0.5 rounded text-white mt-0.5 ${sevColor(e.severity)}`}>
                  {e.severity}
                </span>
                <div className="text-sm flex-1">
                  <div className="text-white">
                    {e.event_type} • #{e.track_id} {e.vehicle_class}
                  </div>
                  <div className="text-xs text-neutral-500">
                    t = {e.time_sec}s • speed {e.speed_kmh} km/h (median {e.median_speed_kmh})
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6">
        <div className="bg-neutral-900 rounded-xl border border-neutral-800 p-4">
          <div className="text-sm text-neutral-400 mb-2">vehicles by class (cumulative)</div>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={classChartData}>
              <XAxis dataKey="name" stroke="#737373" fontSize={12} />
              <YAxis stroke="#737373" fontSize={12} />
              <Tooltip contentStyle={{ background: "#171717", border: "1px solid #262626" }} />
              <Bar dataKey="count" fill="#60a5fa" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-neutral-900 rounded-xl border border-neutral-800 p-4">
          <div className="text-sm text-neutral-400 mb-2">median speed (km/h, last 60 samples)</div>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={speedSeries}>
              <CartesianGrid stroke="#262626" strokeDasharray="3 3" />
              <XAxis dataKey="t" stroke="#737373" fontSize={12} />
              <YAxis stroke="#737373" fontSize={12} />
              <Tooltip contentStyle={{ background: "#171717", border: "1px solid #262626" }} />
              <Line type="monotone" dataKey="v" stroke="#34d399" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <footer className="text-center text-xs text-neutral-600 mt-8">
        TrafficSense • final year project • RIT bengaluru
      </footer>
    </div>
  );
}