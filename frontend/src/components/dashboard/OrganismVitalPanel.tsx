'use client';

import { useVitalStatus } from '@/hooks/useTrading';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skull, Zap, Shield, Activity, BrainCircuit, AlertTriangle, Crown, Flame } from 'lucide-react';

// ── State colour mappings ────────────────────────────────────────────────────
const SURVIVAL_CONFIG: Record<string, { label: string; color: string; bg: string; border: string; icon: any; pulse: boolean }> = {
  HEALTHY:       { label: 'HEALTHY',       color: 'text-emerald-400',  bg: 'bg-emerald-500/10',  border: 'border-emerald-500/30', icon: Shield,       pulse: false },
  WOUNDED:       { label: '⚠ WOUNDED',     color: 'text-amber-400',    bg: 'bg-amber-500/10',    border: 'border-amber-500/40',  icon: AlertTriangle, pulse: true  },
  ORGAN_FAILURE: { label: '🚨 ORGAN FAIL', color: 'text-orange-400',   bg: 'bg-orange-500/10',   border: 'border-orange-500/50', icon: AlertTriangle, pulse: true  },
  DECEASED:      { label: '💀 DECEASED',   color: 'text-red-500',      bg: 'bg-red-500/10',      border: 'border-red-500/60',    icon: Skull,        pulse: true  },
};

const APEX_CONFIG: Record<string, { label: string; color: string; bg: string; icon: any }> = {
  HUNTING:     { label: '🎯 HUNTING',     color: 'text-slate-300',   bg: 'bg-slate-500/10',   icon: Activity    },
  DOMINANT:    { label: '🦾 DOMINANT',    color: 'text-blue-400',    bg: 'bg-blue-500/10',    icon: Zap         },
  APEX:        { label: '⚡ APEX',        color: 'text-violet-400',  bg: 'bg-violet-500/10',  icon: Flame       },
  SINGULARITY: { label: '👑 SINGULARITY', color: 'text-yellow-400',  bg: 'bg-yellow-400/10',  icon: Crown       },
};

function VitalBar({ value, max, color, label }: { value: number; max: number; color: string; label: string }) {
  const pct = Math.min(100, (value / max) * 100);
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>{label}</span>
        <span className="font-mono">{value.toFixed(2)}%</span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-secondary/50">
        <div
          className={`h-full rounded-full transition-all duration-700 ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export function OrganismVitalPanel() {
  const { data: vitals, isLoading } = useVitalStatus();

  if (isLoading || !vitals) {
    return (
      <Card className="bg-card/40 border-primary/10 animate-pulse">
        <CardContent className="h-48 flex items-center justify-center text-muted-foreground text-sm">
          Connecting to organism…
        </CardContent>
      </Card>
    );
  }

  const survival = SURVIVAL_CONFIG[vitals.survival_state] || SURVIVAL_CONFIG.HEALTHY;
  const apex = APEX_CONFIG[vitals.apex_state] || APEX_CONFIG.HUNTING;
  const SurvivalIcon = survival.icon;
  const ApexIcon = apex.icon;
  const budget = vitals.intelligence_budget || {};
  const events: any[] = (vitals.event_log || []).slice(-5).reverse();
  const thresholds = vitals.thresholds || {};

  return (
    <div className="space-y-4">
      {/* ── Main Vitals Row ────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3">

        {/* Survival State */}
        <Card className={`${survival.bg} ${survival.border} border`}>
          <CardHeader className="pb-2 pt-4 px-4">
            <CardTitle className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
              Survival State
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <div className={`flex items-center gap-2 ${survival.color}`}>
              <SurvivalIcon className={`h-4 w-4 ${survival.pulse ? 'animate-pulse' : ''}`} />
              <span className="text-base font-bold font-mono tracking-wide">{survival.label}</span>
            </div>
            <div className="mt-3 space-y-2">
              <VitalBar
                value={vitals.drawdown_pct}
                max={thresholds.protocol_final_pct || 15}
                color="bg-red-500"
                label="Drawdown"
              />
            </div>
          </CardContent>
        </Card>

        {/* Apex Tier */}
        <Card className={`${apex.bg} border border-white/5`}>
          <CardHeader className="pb-2 pt-4 px-4">
            <CardTitle className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
              Apex Tier
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <div className={`flex items-center gap-2 ${apex.color}`}>
              <ApexIcon className="h-4 w-4" />
              <span className="text-base font-bold font-mono tracking-wide">{apex.label}</span>
            </div>
            <div className="mt-3 space-y-2">
              <VitalBar
                value={vitals.profit_pct}
                max={thresholds.tier_3_profit_pct || 50}
                color="bg-violet-500"
                label="Profit"
              />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* ── Intelligence Budget ────────────────────────────────────── */}
      <Card className="bg-card/30 border border-violet-500/10">
        <CardHeader className="pb-2 pt-4 px-4">
          <div className="flex items-center gap-2">
            <BrainCircuit className="h-3.5 w-3.5 text-violet-400" />
            <CardTitle className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
              Intelligence Budget
            </CardTitle>
          </div>
        </CardHeader>
        <CardContent className="px-4 pb-4 space-y-2">
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs font-mono">
            <span className="text-muted-foreground">Model</span>
            <span className="text-violet-300 truncate">{budget.model || '—'}</span>
            <span className="text-muted-foreground">Temperature</span>
            <span className="text-blue-300">{budget.temperature ?? '—'}</span>
            <span className="text-muted-foreground">Thinking Budget</span>
            <span className="text-emerald-300">{budget.thinking_budget?.toLocaleString() ?? '—'} tokens</span>
            <span className="text-muted-foreground">Qty Multiplier</span>
            <span className={vitals.qty_multiplier >= 1.5 ? 'text-yellow-400' : vitals.qty_multiplier <= 0 ? 'text-red-500' : 'text-slate-300'}>
              ×{vitals.qty_multiplier?.toFixed(2) ?? '1.00'}
            </span>
          </div>
          {budget.description && (
            <p className="text-[10px] text-muted-foreground italic border-t border-white/5 pt-2 mt-1">
              {budget.description}
            </p>
          )}
        </CardContent>
      </Card>

      {/* ── Threshold Quick Reference ──────────────────────────────── */}
      <Card className="bg-card/20 border border-white/5">
        <CardContent className="px-4 py-3">
          <div className="grid grid-cols-3 gap-2 text-[10px] text-center">
            <div>
              <div className="text-amber-400 font-bold font-mono">{thresholds.wounded_pct ?? 5}%</div>
              <div className="text-muted-foreground">Wounded</div>
            </div>
            <div>
              <div className="text-orange-400 font-bold font-mono">{thresholds.organ_failure_pct ?? 10}%</div>
              <div className="text-muted-foreground">Organ Failure</div>
            </div>
            <div>
              <div className="text-red-500 font-bold font-mono">{thresholds.protocol_final_pct ?? 15}%</div>
              <div className="text-muted-foreground">💀 Protocol Final</div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ── Event Log ─────────────────────────────────────────────── */}
      {events.length > 0 && (
        <Card className="bg-card/20 border border-white/5">
          <CardHeader className="pb-1 pt-3 px-4">
            <CardTitle className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
              Organism Log
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3 space-y-2">
            {events.map((ev, i) => (
              <div key={i} className="flex gap-2 text-[10px]">
                <span className="text-muted-foreground font-mono shrink-0">
                  {new Date(ev.timestamp).toLocaleTimeString()}
                </span>
                <span className="text-slate-300 leading-snug">{ev.message}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
