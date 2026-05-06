'use client';

import { useState } from 'react';
import { useUpdateFleetConfig } from '@/hooks/useFleet';
import { FleetConfig } from '@/lib/api';
import { Settings2, X, Save, Shield, Bot, BrainCircuit, Clock, Globe } from 'lucide-react';

interface Props {
  config: FleetConfig;
  onClose: () => void;
}

export function FleetSettings({ config, onClose }: Props) {
  const [form, setForm] = useState<FleetConfig>({ ...config });
  const update = useUpdateFleetConfig();

  const set = <K extends keyof FleetConfig>(key: K, value: FleetConfig[K]) =>
    setForm(prev => ({ ...prev, [key]: value }));

  const handleSave = () => {
    update.mutate(form, { onSuccess: onClose });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />

      <div className="relative z-10 w-full max-w-md rounded-2xl border border-white/8 bg-[#0d0d14] shadow-2xl shadow-primary/10 overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-5 border-b border-white/8">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-primary/20 flex items-center justify-center">
              <Settings2 className="w-4 h-4 text-primary" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-white tracking-wide">Fleet Settings</h2>
              <p className="text-[10px] text-muted-foreground font-mono uppercase tracking-widest">
                Global Fleet Configuration
              </p>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-white/5 text-muted-foreground hover:text-white transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-6 space-y-6">

          {/* Max Bots */}
          <SettingRow
            icon={<Bot className="w-3.5 h-3.5 text-primary" />}
            label="Max Bots"
            sub="Maximum simultaneous bots (1–50)"
          >
            <div className="flex items-center gap-3">
              <input
                type="range"
                min={1} max={50} step={1}
                value={form.max_bots}
                onChange={e => set('max_bots', parseInt(e.target.value))}
                className="flex-1 accent-primary"
              />
              <span className="w-8 text-sm font-mono font-bold text-primary text-right tabular-nums">{form.max_bots}</span>
            </div>
          </SettingRow>

          {/* Fleet Drawdown */}
          <SettingRow
            icon={<Shield className="w-3.5 h-3.5 text-red-400" />}
            label="Max Fleet Drawdown"
            sub="Emergency halt threshold across all bots"
          >
            <div className="flex items-center gap-3">
              <input
                type="range"
                min={1} max={50} step={0.5}
                value={form.max_fleet_drawdown_pct}
                onChange={e => set('max_fleet_drawdown_pct', parseFloat(e.target.value))}
                className="flex-1 accent-red-500"
              />
              <span className="w-10 text-sm font-mono font-bold text-red-400 text-right tabular-nums">{form.max_fleet_drawdown_pct.toFixed(1)}%</span>
            </div>
          </SettingRow>

          {/* Log Retention */}
          <SettingRow
            icon={<Clock className="w-3.5 h-3.5 text-muted-foreground" />}
            label="Log Retention"
            sub="Days to keep historical logs"
          >
            <div className="flex items-center gap-3">
              <input
                type="range"
                min={1} max={365} step={1}
                value={form.log_retention_days}
                onChange={e => set('log_retention_days', parseInt(e.target.value))}
                className="flex-1 accent-primary"
              />
              <span className="w-10 text-sm font-mono font-semibold text-white text-right tabular-nums">{form.log_retention_days}d</span>
            </div>
          </SettingRow>

          {/* Toggles */}
          <div className="space-y-4 pt-2">
            {[
              { key: 'global_risk_enabled' as const, label: 'Fleet Risk Kill Switch', sub: 'Enable global drawdown emergency halt', icon: <Shield className="w-3.5 h-3.5 text-red-400" />, color: 'bg-red-500' },
              { key: 'sub_agents_enabled' as const, label: 'Sub-Agents Enabled', sub: 'Enable AI sub-agent pools across all bots', icon: <BrainCircuit className="w-3.5 h-3.5 text-violet-400" />, color: 'bg-violet-500' },
              { key: 'auto_redeploy' as const, label: 'Auto-Redeploy on Crash', sub: 'Automatically restart failed bots', icon: <Bot className="w-3.5 h-3.5 text-sky-400" />, color: 'bg-sky-500' },
            ].map(({ key, label, sub, icon, color }) => (
              <div key={key} className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  {icon}
                  <div>
                    <div className="text-sm text-white">{label}</div>
                    <div className="text-[10px] font-mono text-muted-foreground">{sub}</div>
                  </div>
                </div>
                <button
                  onClick={() => set(key, !form[key])}
                  className={`w-10 h-5 rounded-full transition-all relative shrink-0 ${form[key] ? color : 'bg-white/10'}`}
                >
                  <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all ${form[key] ? 'left-5' : 'left-0.5'}`} />
                </button>
              </div>
            ))}
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-white/8 flex items-center gap-3 justify-end">
          {update.isError && (
            <p className="text-xs text-red-400 font-mono flex-1">Save failed. Try again.</p>
          )}
          <button onClick={onClose} className="px-4 py-2 rounded-xl border border-white/8 text-xs text-muted-foreground hover:text-white hover:border-white/20 transition-all font-mono">
            CANCEL
          </button>
          <button
            onClick={handleSave}
            disabled={update.isPending}
            className="px-5 py-2 rounded-xl bg-primary text-primary-foreground text-xs font-mono font-semibold hover:bg-primary/90 disabled:opacity-50 transition-all flex items-center gap-2"
          >
            <Save className="w-3.5 h-3.5" />
            {update.isPending ? 'SAVING...' : 'SAVE CONFIG'}
          </button>
        </div>
      </div>
    </div>
  );
}

function SettingRow({ icon, label, sub, children }: {
  icon: React.ReactNode; label: string; sub: string; children: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        {icon}
        <div>
          <div className="text-sm font-medium text-white">{label}</div>
          <div className="text-[10px] font-mono text-muted-foreground">{sub}</div>
        </div>
      </div>
      {children}
    </div>
  );
}
