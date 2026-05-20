import { useEffect, useRef, useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, CartesianGrid,
} from "recharts";

const API = "http://localhost:8000";
const WS = "ws://localhost:8000/ws/stream";

const sevBadge = (s) =>
  s === "HIGH" ? "bg-red-500/15 text-red-300 border-red-500/30"
  : s === "MEDIUM" ? "bg-amber-500/15 text-amber-300 border-amber-500/30"
  : "bg-neutral-600/20 text-neutral-300 border-neutral-600/30";

const Card = ({ children, className = "" }) => (
  <div className={`bg-[var(--bg-elev)] border border-[var(--border)] rounded-xl ${className}`}>
    {children}
  </div>
);

const CardHeader = ({ title, sub, right }) => (
  <div className="flex items-start justify-between px-5 pt-5 pb-4">
    <div>
      <div className="text-sm font-semibold text-white">{title}</div>
      {sub && <div className="text-xs text-[var(--text-muted)] mt-0.5">{sub}</div>}
    </div>
    {right}
  </div>
);

const Kpi = ({ label, value, sub }) => (
  <Card className="px-5 py-4">
    <div className="text-[10px] uppercase tracking-[0.12em] text-[var(--text-dim)] font-semibold">{label}</div>
    <div className="kpi-num text-2xl font-semibold mt-2 text-white">{value}</div>
    {sub && <div className="text-[11px] text-[var(--text-muted)] mt-1 mono">{sub}</div>}
  </Card>
);

const ChartTooltip = (props) => (
  <Tooltip
    {...props}
    contentStyle={{
      background: "var(--bg-elev-2)",
      border: "1px solid var(--border-strong)",
      borderRadius: 8,
      color: "var(--text)",
      fontSize: 12,
    }}
    cursor={{ fill: "rgba(255,255,255,0.04)" }}
  />
);

export default function App() {
  const [summary, setSummary] = useState(null);
  const [events, setEvents] = useState([]);
  const [speedSeries, setSpeedSeries] = useState([]);
  const [connected, setConnected] = useState(false);
  const [signal, setSignal] = useState(null);
  const [comparison, setComparison] = useState(null);
  const [activeBench, setActiveBench] = useState("synthetic");
  const wsRef = useRef(null);

  useEffect(() => {
    let alive = true;
    const connect = () => {
      const ws = new WebSocket(WS);
      wsRef.current = ws;
      ws.onopen = () => setConnected(true);
      ws.onclose = () => { setConnected(false); if (alive) setTimeout(connect, 1500); };
      let lastSeriesPush = 0;
      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        if (msg.type === "summary") {
          setSummary(msg);
          const now = Date.now();
          if (now - lastSeriesPush > 1000) {
            lastSeriesPush = now;
            setSpeedSeries((s) => [...s, { t: msg.frame_idx, v: msg.median_speed_kmh }].slice(-30));
          }
        } else if (msg.type === "events") {
          if (msg.events.length === 1 && msg.events[0]._clear) setEvents([]);
          else setEvents((prev) => [...msg.events.reverse(), ...prev].slice(0, 50));
        }
      };
    };
    connect();
    return () => { alive = false; wsRef.current?.close(); };
  }, []);

  useEffect(() => {
    fetch(`${API}/events?limit=50`).then(r => r.json()).then(l => setEvents(l.slice().reverse())).catch(() => {});
  }, []);

  useEffect(() => {
    const tick = () => fetch(`${API}/signal/state`).then(r => r.json()).then(setSignal).catch(() => {});
    tick();
    const id = setInterval(tick, 500);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    fetch(`${API}/signal/comparison`).then(r => r.json()).then(setComparison).catch(() => {});
  }, []);

  const cbc = summary?.count_by_class || {};
  const classChartData = Object.entries(cbc).map(([k, v]) => ({ name: k, count: v }));
  const bench = comparison?.[activeBench];

  return (
    <div className="min-h-screen">
      {/* sticky header */}
      <header className="border-b border-[var(--border)] bg-[var(--bg)]/80 backdrop-blur-md sticky top-0 z-20">
        <div className="max-w-[1500px] mx-auto px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[var(--accent)] to-[var(--accent-2)] flex items-center justify-center text-[var(--bg)] font-bold">
              T
            </div>
            <div className="flex items-baseline gap-3">
              <div className="text-base font-semibold text-white tracking-tight">TrafficSense</div>
              <div className="text-xs text-[var(--text-dim)] hidden sm:block">intelligent transport system</div>
            </div>
          </div>
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[var(--bg-elev)] border border-[var(--border)]">
            <span className={`w-1.5 h-1.5 rounded-full ${connected ? "bg-[var(--good)] pulse-dot" : "bg-[var(--bad)]"}`} />
            <span className="text-[11px] text-[var(--text-muted)] mono uppercase tracking-wider">
              {connected ? "Live" : "Offline"}
            </span>
          </div>
        </div>
      </header>

      <main className="max-w-[1500px] mx-auto px-8 py-10">

        {/* HERO: the headline result */}
        <section className="mb-12">
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">
            <Card className="lg:col-span-3 px-7 py-8 relative overflow-hidden">
              <div className="absolute inset-0 bg-gradient-to-br from-[var(--accent)]/5 via-transparent to-transparent pointer-events-none" />
              <div className="relative">
                <div className="text-[10px] uppercase tracking-[0.15em] text-[var(--text-dim)] font-semibold mb-3">
                  headline result · {activeBench === "synthetic" ? "controlled experiment" : "real bengaluru intersection"}
                </div>
                <div className="flex items-baseline gap-3">
                  <div className="kpi-num text-7xl font-bold text-[var(--accent)] tracking-tighter">
                    {bench?.wait_improvement_pct ?? "—"}%
                  </div>
                  <div className="text-lg text-white">reduction in average wait time</div>
                </div>
                <div className="text-sm text-[var(--text-muted)] mt-2 max-w-md">
                  adaptive signal control vs fixed-timer baseline,
                  measured over <span className="text-white mono">{bench?.fixed.completed_trips ?? "—"}</span> completed vehicle trips.
                </div>

                <div className="flex gap-2 mt-6">
                  {["synthetic", "bengaluru"].map((k) => (
                    <button
                      key={k}
                      onClick={() => setActiveBench(k)}
                      disabled={!comparison?.[k]}
                      className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
                        activeBench === k
                          ? "bg-[var(--accent)]/15 border-[var(--accent)]/40 text-[var(--accent)]"
                          : "bg-transparent border-[var(--border)] text-[var(--text-muted)] hover:text-white disabled:opacity-30"
                      }`}
                    >
                      {k === "synthetic" ? "synthetic 4-way" : "bengaluru osm"}
                    </button>
                  ))}
                </div>
              </div>
            </Card>

            <Card className="lg:col-span-2 px-6 py-6">
              <div className="text-[10px] uppercase tracking-[0.15em] text-[var(--text-dim)] font-semibold mb-4">
                benchmark breakdown
              </div>
              {bench ? (
                <div className="space-y-3.5 text-sm">
                  <Row k="fixed avg wait" v={`${bench.fixed.avg_wait_time_sec}s`} />
                  <Row k="adaptive avg wait" v={`${bench.adaptive.avg_wait_time_sec}s`} accent />
                  <div className="h-px bg-[var(--border)] my-1" />
                  <Row k="travel time" v={`${bench.travel_improvement_pct}% faster`} />
                  <Row k="queue clear" v={`${bench.clear_improvement_pct}% faster`} />
                  <Row k="trips" v={`${bench.fixed.completed_trips} = ${bench.adaptive.completed_trips}`} muted />
                </div>
              ) : <div className="text-[var(--text-dim)] text-sm">no data</div>}
            </Card>
          </div>
        </section>

        {/* PERCEPTION */}
        <SectionTitle>perception</SectionTitle>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <Kpi label="frame" value={summary?.frame_idx ?? "—"} sub={`t = ${summary?.time_sec ?? 0}s`} />
          <Kpi label="vehicles tracked" value={summary?.unique_vehicles ?? "—"} />
          <Kpi label="median speed" value={`${summary?.median_speed_kmh ?? 0}`} sub="km/h" />
          <Kpi label="incidents" value={summary?.events_total ?? 0} sub={`${summary?.counted_in ?? 0} in / ${summary?.counted_out ?? 0} out`} />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 mb-12">
          <Card className="lg:col-span-2">
            <CardHeader
              title="live annotated feed"
              sub="yolov8s detection · bytetrack id assignment"
              right={<div className="mono text-[10px] text-[var(--text-dim)] uppercase">streaming</div>}
            />
            <div className="px-5 pb-5">
              <div className="rounded-lg overflow-hidden border border-[var(--border-strong)] bg-black">
                <img src={`${API}/stream.mjpg`} alt="live feed" className="w-full block" />
              </div>
              <div className="flex flex-wrap gap-4 mt-4 text-[11px] text-[var(--text-muted)]">
                <span className="flex items-center gap-1.5"><span className="inline-block w-3 h-0.5 bg-yellow-400" />counting line</span>
                <span className="flex items-center gap-1.5"><span className="inline-block w-2 h-2 bg-red-500 rounded-sm" />incident flagged</span>
                <span className="flex items-center gap-1.5"><span className="inline-block w-2 h-2 bg-emerald-400 rounded-sm" />tracked vehicle</span>
              </div>
            </div>
          </Card>

          <Card className="flex flex-col">
            <CardHeader
              title="incident log"
              right={<div className="mono text-xs text-[var(--text-dim)]">{events.length}</div>}
            />
            <div className="px-5 pb-5 overflow-y-auto max-h-[500px] divide-y divide-[var(--border)] scrollbar-thin">
              {events.length === 0 && (
                <div className="text-[var(--text-dim)] text-sm py-10 text-center">
                  no incidents detected
                </div>
              )}
              {events.map((e, i) => (
                <div key={i} className="py-3 flex items-start gap-2.5 fade-in">
                  <span className={`text-[10px] px-1.5 py-0.5 rounded mt-0.5 font-semibold border ${sevBadge(e.severity)}`}>
                    {e.severity}
                  </span>
                  <div className="text-sm flex-1 min-w-0">
                    <div className="text-white truncate">
                      {e.event_type} <span className="mono text-[var(--accent)]">#{e.track_id}</span> <span className="text-[var(--text-muted)]">{e.vehicle_class}</span>
                    </div>
                    <div className="text-[11px] text-[var(--text-dim)] mono mt-0.5">
                      t={e.time_sec}s · {e.speed_kmh} km/h (median {e.median_speed_kmh})
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>

        {/* CONTROL */}
        <SectionTitle>control</SectionTitle>

        <Card className="mb-12">
          <CardHeader
            title="adaptive signal control"
            sub="live sumo simulation · webster-style controller"
            right={
              <div className="text-[11px] text-[var(--text-dim)] mono">
                episode {signal?.episode ?? "-"} · t={signal?.t ?? 0}s · {signal?.switch_decisions ?? 0} switches
              </div>
            }
          />
          <div className="px-5 pb-5">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* left: phase + queues */}
              <div>
                <div className="flex items-center gap-5 mb-5 px-4 py-3 rounded-lg bg-[var(--bg-elev-2)] border border-[var(--border)]">
                  <div className="flex items-center gap-2">
                    <div className={`w-2.5 h-2.5 rounded-full ${signal?.phase === 0 ? "bg-[var(--good)] pulse-dot" : "bg-[var(--text-dim)]"}`} />
                    <span className="text-sm text-white">axis A</span>
                  </div>
                  <div className="text-[var(--border-strong)]">|</div>
                  <div className="flex items-center gap-2">
                    <div className={`w-2.5 h-2.5 rounded-full ${signal?.phase === 2 ? "bg-[var(--good)] pulse-dot" : "bg-[var(--text-dim)]"}`} />
                    <span className="text-sm text-white">axis B</span>
                  </div>
                  {signal?.preempt_active && (
                    <div className="ml-auto px-2 py-1 rounded text-[10px] font-semibold bg-red-500/20 text-red-300 border border-red-500/40 mono">
                      PREEMPT · {signal.preempt_direction}
                    </div>
                  )}
                </div>

                <div className="text-[10px] uppercase tracking-[0.12em] text-[var(--text-dim)] font-semibold mb-3">queue depth per approach</div>
                <div className="space-y-2.5">
                  {["n", "s", "e", "w"].map((d) => {
                    const q = signal?.queue?.[d] ?? 0;
                    const pct = Math.min(q * 8, 100);
                    return (
                      <div key={d} className="flex items-center gap-3 text-sm">
                        <div className="w-5 text-[var(--text-muted)] uppercase mono text-[11px]">{d}</div>
                        <div className="flex-1 h-2 bg-[var(--bg-elev-2)] rounded-full overflow-hidden">
                          <div
                            className="h-full bg-gradient-to-r from-[var(--accent-2)] to-[var(--accent)] transition-all duration-300"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <div className="w-7 text-right text-white kpi-num text-sm">{q}</div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* right: controls */}
              <div>
                <div className="text-[10px] uppercase tracking-[0.12em] text-[var(--text-dim)] font-semibold mb-3">manual controls</div>
                <div className="space-y-2">
                  <button
                    onClick={() => fetch(`${API}/signal/preempt?direction=NS`, { method: "POST" })}
                    className="w-full text-sm px-4 py-2.5 rounded-lg bg-[var(--bg-elev-2)] hover:bg-[var(--border)] text-white border border-[var(--border-strong)] transition-colors text-left"
                  >
                    trigger axis A preempt
                  </button>
                  <button
                    onClick={() => fetch(`${API}/signal/preempt?direction=EW`, { method: "POST" })}
                    className="w-full text-sm px-4 py-2.5 rounded-lg bg-[var(--bg-elev-2)] hover:bg-[var(--border)] text-white border border-[var(--border-strong)] transition-colors text-left"
                  >
                    trigger axis B preempt
                  </button>
                  <button
                    onClick={() => fetch(`${API}/debug/fake_incident?direction=NS`, { method: "POST" })}
                    className="w-full text-sm px-4 py-2.5 rounded-lg bg-[var(--accent)]/10 hover:bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/30 transition-colors text-left"
                  >
                    simulate cv-triggered incident →
                  </button>
                </div>
              </div>
            </div>
          </div>
        </Card>

        {/* METRICS */}
        <SectionTitle>metrics</SectionTitle>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          <Card>
            <CardHeader title="vehicles by class" sub="cumulative over current loop" />
            <div className="px-5 pb-5">
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={classChartData}>
                  <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="name" stroke="var(--text-dim)" fontSize={11} />
                  <YAxis stroke="var(--text-dim)" fontSize={11} />
                  <ChartTooltip />
                  <Bar dataKey="count" fill="var(--accent)" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <Card>
            <CardHeader title="median speed" sub="rolling, last 30 samples" />
            <div className="px-5 pb-5">
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={speedSeries}>
                  <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="t" stroke="var(--text-dim)" fontSize={11} />
                  <YAxis stroke="var(--text-dim)" fontSize={11} />
                  <ChartTooltip />
                  <Line type="monotone" dataKey="v" stroke="var(--accent)" dot={false} strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Card>
        </div>

        <footer className="text-center text-[11px] text-[var(--text-dim)] mt-16 pb-2">
          TrafficSense · final year project · CI39 · ramaiah institute of technology
          <span className="mx-2">·</span>
          <a href="https://github.com/nitishpatil18/trafficsense" className="hover:text-[var(--accent)]" target="_blank" rel="noreferrer">
            github
          </a>
        </footer>
      </main>
    </div>
  );
}

const SectionTitle = ({ children }) => (
  <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--text-dim)] font-semibold mb-5 mt-2">
    {children}
  </div>
);

const Row = ({ k, v, accent, muted }) => (
  <div className="flex justify-between items-baseline">
    <span className={`text-sm ${muted ? "text-[var(--text-dim)]" : "text-[var(--text-muted)]"}`}>{k}</span>
    <span className={`mono kpi-num text-sm ${accent ? "text-[var(--accent)] font-semibold" : muted ? "text-[var(--text-dim)]" : "text-white"}`}>{v}</span>
  </div>
);