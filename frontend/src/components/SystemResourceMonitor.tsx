'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { Cpu, MemoryStick, Server, ChevronDown } from 'lucide-react';
import { AnimatePresence, motion } from 'framer-motion';
import { API_BASE_URL } from '@/lib/api';

// ─── Constants ────────────────────────────────────────────
const POLL_INTERVAL_MS = 10_000;   // 10 seconds
const WINDOW_POINTS    = 30;       // 30 × 10s = 5 min rolling window

// ─── Types ───────────────────────────────────────────────

interface ResourceData {
  cpu:     { percent: number; count: number; per_core: number[] };
  ram:     { total_mb: number; used_mb: number; available_mb: number; percent: number };
  swap:    { total_mb: number; used_mb: number; percent: number };
  process: { rss_mb: number; vms_mb: number; cpu_pct: number; pid: number };
  timestamp: string;
}

interface DataPoint {
  ts:     number;   // epoch ms
  cpu:    number;   // 0-100
  ram:    number;   // 0-100
  rss:    number;   // MB
}

// ─── Helpers ─────────────────────────────────────────────

function pctColor(pct: number): string {
  if (pct >= 85) return '#f43f5e';
  if (pct >= 60) return '#f59e0b';
  return '#10b981';
}

function mbToGb(mb: number): string {
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb.toFixed(0)} MB`;
}

// ─── SVG Line Chart ───────────────────────────────────────

interface LineChartProps {
  history: DataPoint[];
  width?: number;
  height?: number;
}

function LineChart({ history, width = 248, height = 72 }: LineChartProps) {
  if (history.length < 2) {
    return (
      <div
        className="flex items-center justify-center text-[8px] font-mono text-muted-foreground rounded-xl bg-white/4 border border-white/8"
        style={{ width, height }}
      >
        Collecting data…
      </div>
    );
  }

  const pad = { top: 8, right: 4, bottom: 16, left: 28 };
  const innerW = width  - pad.left - pad.right;
  const innerH = height - pad.top  - pad.bottom;

  // X maps index → pixel
  const xScale = (i: number) =>
    pad.left + (i / (WINDOW_POINTS - 1)) * innerW;

  // Y maps 0-100 → pixel (inverted)
  const yScale = (v: number) =>
    pad.top + innerH - (v / 100) * innerH;

  // Pad history on the left with nulls so the line anchors to the right
  const padded: (DataPoint | null)[] = [
    ...Array(WINDOW_POINTS - history.length).fill(null),
    ...history,
  ];

  function makePath(key: 'cpu' | 'ram'): string {
    const pts: string[] = [];
    padded.forEach((p, i) => {
      if (!p) return;
      const x = xScale(i);
      const y = yScale(p[key]);
      pts.push(pts.length === 0 ? `M ${x},${y}` : `L ${x},${y}`);
    });
    return pts.join(' ');
  }

  function makeArea(key: 'cpu' | 'ram'): string {
    const pts: { x: number; y: number }[] = [];
    padded.forEach((p, i) => {
      if (!p) return;
      pts.push({ x: xScale(i), y: yScale(p[key]) });
    });
    if (!pts.length) return '';
    const bottom = pad.top + innerH;
    return [
      `M ${pts[0].x},${bottom}`,
      ...pts.map(p => `L ${p.x},${p.y}`),
      `L ${pts[pts.length - 1].x},${bottom}`,
      'Z',
    ].join(' ');
  }

  const yTicks   = [0, 25, 50, 75, 100];
  const nowLabel = 'now';
  const agoLabel = `${Math.round((WINDOW_POINTS * POLL_INTERVAL_MS) / 60000)}m ago`;
  const cpuLast  = history[history.length - 1].cpu;
  const ramLast  = history[history.length - 1].ram;

  // Find the index of the rightmost non-null entry (ES2017-safe)
  function lastFilledIndex(): number {
    for (let i = padded.length - 1; i >= 0; i--) {
      if (padded[i] !== null) return i;
    }
    return -1;
  }

  const lastIdx    = lastFilledIndex();
  const lastCpuPct = history[history.length - 1].cpu;
  const lastRamPct = history[history.length - 1].ram;


  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <defs>
        <linearGradient id="cpu-grad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"   stopColor={pctColor(cpuLast)} stopOpacity={0.35} />
          <stop offset="100%" stopColor={pctColor(cpuLast)} stopOpacity={0.02} />
        </linearGradient>
        <linearGradient id="ram-grad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"   stopColor={pctColor(ramLast)} stopOpacity={0.25} />
          <stop offset="100%" stopColor={pctColor(ramLast)} stopOpacity={0.02} />
        </linearGradient>
      </defs>

      {/* Y-axis grid + labels */}
      {yTicks.map(t => (
        <g key={t}>
          <line
            x1={pad.left} y1={yScale(t)}
            x2={pad.left + innerW} y2={yScale(t)}
            stroke="rgba(255,255,255,0.06)"
            strokeWidth={1}
          />
          <text
            x={pad.left - 4} y={yScale(t) + 3}
            textAnchor="end"
            fontSize={6}
            fontFamily="monospace"
            fill="rgba(255,255,255,0.3)"
          >
            {t}
          </text>
        </g>
      ))}

      {/* X-axis labels */}
      <text x={pad.left} y={height - 2} fontSize={6} fontFamily="monospace" fill="rgba(255,255,255,0.3)">{agoLabel}</text>
      <text x={pad.left + innerW} y={height - 2} textAnchor="end" fontSize={6} fontFamily="monospace" fill="rgba(255,255,255,0.3)">{nowLabel}</text>

      {/* RAM area + line */}
      <path d={makeArea('ram')} fill="url(#ram-grad)" />
      <path
        d={makePath('ram')}
        fill="none"
        stroke={pctColor(ramLast)}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
        opacity={0.7}
      />

      {/* CPU area + line */}
      <path d={makeArea('cpu')} fill="url(#cpu-grad)" />
      <path
        d={makePath('cpu')}
        fill="none"
        stroke={pctColor(cpuLast)}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />

      {/* Live dot — CPU */}
      {lastIdx >= 0 && (
        <circle
          cx={xScale(lastIdx)}
          cy={yScale(lastCpuPct)}
          r={2.5}
          fill={pctColor(lastCpuPct)}
          style={{ filter: `drop-shadow(0 0 3px ${pctColor(lastCpuPct)})` }}
        />
      )}

      {/* Live dot — RAM */}
      {lastIdx >= 0 && (
        <circle
          cx={xScale(lastIdx)}
          cy={yScale(lastRamPct)}
          r={2.5}
          fill={pctColor(lastRamPct)}
          style={{ filter: `drop-shadow(0 0 3px ${pctColor(lastRamPct)})` }}
        />
      )}
    </svg>
  );
}

// ─── Arc Gauge ───────────────────────────────────────────

function ArcGauge({ pct, size = 40 }: { pct: number; size?: number }) {
  const r = (size - 6) / 2;
  const circ = 2 * Math.PI * r;
  const arcLen = circ * (240 / 360);
  const dashOffset = arcLen - (pct / 100) * arcLen;
  const color = pctColor(pct);

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="shrink-0">
      <circle cx={size/2} cy={size/2} r={r} fill="none"
        stroke="rgba(255,255,255,0.06)" strokeWidth={4}
        strokeDasharray={`${arcLen} ${circ}`} strokeDashoffset={0}
        strokeLinecap="round"
        transform={`rotate(150 ${size/2} ${size/2})`}
      />
      <circle cx={size/2} cy={size/2} r={r} fill="none"
        stroke={color} strokeWidth={4}
        strokeDasharray={`${arcLen} ${circ}`} strokeDashoffset={dashOffset}
        strokeLinecap="round"
        transform={`rotate(150 ${size/2} ${size/2})`}
        style={{ transition: 'stroke-dashoffset 0.6s ease, stroke 0.4s ease', filter: `drop-shadow(0 0 3px ${color}80)` }}
      />
      <text x={size/2} y={size/2+4} textAnchor="middle"
        fontSize={9} fontWeight={700} fontFamily="monospace" fill={color}>
        {pct}%
      </text>
    </svg>
  );
}

// ─── Per-core mini bars ───────────────────────────────────

function CoreBars({ cores }: { cores: number[] }) {
  return (
    <div className="flex items-end gap-[2px] h-4">
      {cores.map((c, i) => (
        <div key={i} title={`Core ${i}: ${c}%`}
          className="w-1 rounded-sm transition-all duration-500"
          style={{ height: `${Math.max(10, c)}%`, backgroundColor: pctColor(c), opacity: 0.85 }}
        />
      ))}
    </div>
  );
}

// ─── Stat row ────────────────────────────────────────────

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-1 border-b border-white/5 last:border-0">
      <span className="text-[8px] text-muted-foreground uppercase tracking-wider font-mono">{label}</span>
      <span className="text-[9px] text-white font-mono font-semibold tabular-nums">{value}</span>
    </div>
  );
}

// ─── Legend dot ──────────────────────────────────────────

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-1">
      <div className="w-2 h-[2px] rounded-full" style={{ backgroundColor: color }} />
      <span className="text-[8px] font-mono text-muted-foreground">{label}</span>
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────

export function SystemResourceMonitor() {
  const [latest, setLatest]   = useState<ResourceData | null>(null);
  const [history, setHistory] = useState<DataPoint[]>([]);
  const [isOpen, setIsOpen]   = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const mountedRef  = useRef(true);

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/system/resources`);
      if (!res.ok) return;
      const json: ResourceData = await res.json();
      if (!mountedRef.current) return;

      setLatest(json);
      setHistory(prev => {
        const point: DataPoint = {
          ts:  Date.now(),
          cpu: json.cpu.percent,
          ram: json.ram.percent,
          rss: json.process.rss_mb,
        };
        const next = [...prev, point];
        return next.length > WINDOW_POINTS ? next.slice(-WINDOW_POINTS) : next;
      });
    } catch {
      // Silently fail when backend is offline
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    fetchData();
    const id = setInterval(fetchData, POLL_INTERVAL_MS);
    return () => {
      mountedRef.current = false;
      clearInterval(id);
    };
  }, [fetchData]);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node))
        setIsOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  if (!latest) {
    return (
      <div className="flex items-center gap-1.5 px-2 py-1 rounded-xl bg-white/4 border border-white/8 h-[38px] opacity-40 animate-pulse">
        <Cpu className="w-3 h-3 text-muted-foreground" />
        <span className="text-[9px] font-mono text-muted-foreground">---</span>
      </div>
    );
  }

  const cpuColor = pctColor(latest.cpu.percent);
  const ramColor = pctColor(latest.ram.percent);
  const elapsed  = Math.round((history.length * POLL_INTERVAL_MS) / 1000);

  return (
    <div className="relative" ref={dropdownRef}>

      {/* ── Trigger pill ── */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 px-2.5 py-1 rounded-xl bg-white/4 border border-white/8 hover:bg-white/8 transition-all h-[38px]"
      >
        <ArcGauge pct={latest.cpu.percent} size={32} />
        <ArcGauge pct={latest.ram.percent}  size={32} />
        <ChevronDown
          className={`w-3 h-3 text-muted-foreground transition-transform duration-300 ${isOpen ? 'rotate-180' : ''}`}
        />
      </button>

      {/* ── Dropdown ── */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: 8, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.96 }}
            transition={{ duration: 0.18 }}
            className="absolute right-0 mt-2 w-[296px] rounded-2xl bg-slate-950/95 backdrop-blur-2xl border border-white/10 shadow-2xl z-50 overflow-hidden"
          >
            {/* Glow */}
            <div className="absolute top-0 left-1/2 -translate-x-1/2 w-40 h-24 bg-primary/10 rounded-full blur-[50px] pointer-events-none" />

            <div className="p-4 space-y-3 relative">

              {/* Header */}
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-bold text-white uppercase tracking-widest">System Monitor</span>
                <div className="flex items-center gap-2">
                  <span className="text-[8px] font-mono text-muted-foreground">
                    {elapsed}s / {(WINDOW_POINTS * POLL_INTERVAL_MS / 1000)}s window
                  </span>
                  <div className="flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-white/5 border border-white/10">
                    <div className="w-1 h-1 rounded-full bg-emerald-400 animate-pulse" />
                    <span className="text-[8px] font-mono text-emerald-400">LIVE</span>
                  </div>
                </div>
              </div>

              {/* ── 5-min Graph ── */}
              <div className="rounded-xl bg-white/4 border border-white/8 p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[8px] font-bold text-white uppercase tracking-wider">5-Minute Window</span>
                  <div className="flex items-center gap-2">
                    <LegendDot color={cpuColor} label="CPU" />
                    <LegendDot color={ramColor}  label="RAM" />
                  </div>
                </div>
                <LineChart history={history} width={256} height={80} />
              </div>

              {/* ── Current Readings (gauges + bars) ── */}
              <div className="grid grid-cols-2 gap-2">
                {/* CPU */}
                <div className="rounded-xl bg-white/4 border border-white/8 p-2.5 space-y-2">
                  <div className="flex items-center gap-1.5">
                    <Cpu className="w-3 h-3" style={{ color: cpuColor }} />
                    <span className="text-[8px] font-bold text-white uppercase tracking-wider">CPU</span>
                    <span className="ml-auto text-[7px] font-mono text-muted-foreground">{latest.cpu.count}c</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <ArcGauge pct={latest.cpu.percent} size={44} />
                    <div className="flex-1">
                      <div className="w-full h-1 rounded-full bg-white/8 overflow-hidden mb-1.5">
                        <div className="h-full rounded-full transition-all duration-500"
                          style={{ width: `${latest.cpu.percent}%`, backgroundColor: cpuColor }} />
                      </div>
                      <CoreBars cores={latest.cpu.per_core} />
                    </div>
                  </div>
                </div>

                {/* RAM */}
                <div className="rounded-xl bg-white/4 border border-white/8 p-2.5 space-y-2">
                  <div className="flex items-center gap-1.5">
                    <MemoryStick className="w-3 h-3" style={{ color: ramColor }} />
                    <span className="text-[8px] font-bold text-white uppercase tracking-wider">RAM</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <ArcGauge pct={latest.ram.percent} size={44} />
                    <div className="flex-1 space-y-1">
                      <div className="w-full h-1 rounded-full bg-white/8 overflow-hidden">
                        <div className="h-full rounded-full transition-all duration-500"
                          style={{ width: `${latest.ram.percent}%`, backgroundColor: ramColor }} />
                      </div>
                      <div className="text-[7px] font-mono text-muted-foreground leading-tight">
                        {mbToGb(latest.ram.used_mb)}<br />
                        / {mbToGb(latest.ram.total_mb)}
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              {/* ── Process ── */}
              <div className="rounded-xl bg-white/4 border border-white/8 p-3">
                <div className="flex items-center gap-1.5 mb-2">
                  <Server className="w-3 h-3 text-primary" />
                  <span className="text-[8px] font-bold text-white uppercase tracking-wider">Backend Process</span>
                  <span className="ml-auto text-[7px] font-mono text-muted-foreground">PID {latest.process.pid}</span>
                </div>
                <StatRow label="RSS Memory"      value={mbToGb(latest.process.rss_mb)} />
                <StatRow label="Virtual Memory"  value={mbToGb(latest.process.vms_mb)} />
                <StatRow label="Process CPU"     value={`${latest.process.cpu_pct}%`} />
                {latest.swap.total_mb > 0 && (
                  <StatRow label="Swap Used" value={`${mbToGb(latest.swap.used_mb)} (${latest.swap.percent}%)`} />
                )}
              </div>

              <div className="text-[8px] text-center text-muted-foreground font-mono">
                Sampling every {POLL_INTERVAL_MS / 1000}s · {WINDOW_POINTS}-point rolling window
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
