'use client';

import { useState } from 'react';
import {
  useDeployBot,
  useFleetConfig,
  useAvailableSymbols,
  useMT5Account,
  useFleetStatus,
} from '@/hooks/useFleet';
import { BotDeployRequest } from '@/lib/api';
import {
  X, Rocket, ChevronDown, ChevronUp, Bot,
  BrainCircuit, Shield, BarChart2, Wifi, AlertTriangle, Zap
} from 'lucide-react';

const STRATEGIES = ['mean_reversion', 'momentum', 'breakout', 'scalp'];
const ALL_AGENTS = ['sentiment', 'macro', 'earnings', 'technical'];

const DEFAULT_FORM: BotDeployRequest = {
  name: '',
  symbol: '',
  account_id: '',
  strategy: 'mean_reversion',
  max_daily_drawdown_pct: 5.0,
  capital_allocation: 10000.0,
  qty: 1,
  short_selling_enabled: true,
  stop_loss_pct: 1.5,
  bb_period: 20,
  bb_std_dev: 2.0,
  ai_brain_enabled: true,
  ai_interval_minutes: 60,
  sub_agents: ['sentiment', 'macro', 'earnings', 'technical'],
  tags: [],
  fib_enabled: true,
  auto_start: true,
  leverage_mode_enabled: false,
  leverage_factor: 20,
  isolated_risk_usd: 40.0,
  net_profit_target_usd: 1.0,
  take_profit_usd: 1.0,
};

interface Props {
  onClose: () => void;
  onDeployed?: (botId: string) => void;
}

export function DeployWizard({ onClose, onDeployed }: Props) {
  const [form, setForm] = useState<BotDeployRequest>(DEFAULT_FORM);
  const [advanced, setAdvanced] = useState(false);
  const [tagInput, setTagInput] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  const deployBot = useDeployBot();
  const { data: fleetConfig } = useFleetConfig();
  const { data: fleetStatus } = useFleetStatus();
  const { data: symbolsData, isLoading: isLoadingSymbols, isError: isErrorSymbols } = useAvailableSymbols();
  const { data: accountInfo } = useMT5Account();
  
  // Calculate max available allocation
  const totalAllocated = fleetStatus?.bots?.reduce((sum, b) => sum + b.capital_allocation, 0) || 0;
  // Include paper PnL so max available reflects paper profits/losses
  const displayEquity = accountInfo ? accountInfo.equity : 0;
  const maxAllocation = accountInfo ? Math.max(0, displayEquity - totalAllocated) : 0;
  // Initialize default symbol once loaded
  const [initialized, setInitialized] = useState(false);
  if (!initialized && symbolsData?.symbols?.length && !form.symbol) {
    const first = symbolsData.symbols[0];
    setForm(prev => ({ ...prev, symbol: first.name, qty: first.volume_min ?? 0.01 }));
    setInitialized(true);
  }

  const filteredSymbols = symbolsData?.symbols.filter(s =>
    s.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    s.description?.toLowerCase().includes(searchTerm.toLowerCase()) ||
    s.category.toLowerCase().includes(searchTerm.toLowerCase())
  ).slice(0, 50) || []; // Performance limit

  const selectedSymbolInfo = symbolsData?.symbols.find(s => s.name === form.symbol);
  const volMin = selectedSymbolInfo?.volume_min ?? 0.01;
  const volMax = selectedSymbolInfo?.volume_max ?? 100.0;
  const volStep = selectedSymbolInfo?.volume_step ?? 0.01;
  const volDecimals = volStep < 1 ? String(volStep).split('.')[1]?.length ?? 2 : 0;


  const set = <K extends keyof BotDeployRequest>(key: K, value: BotDeployRequest[K]) =>
    setForm(prev => ({ ...prev, [key]: value }));

  const toggleAgent = (agent: string) => {
    set('sub_agents', form.sub_agents.includes(agent)
      ? form.sub_agents.filter(a => a !== agent)
      : [...form.sub_agents, agent]
    );
  };

  const addTag = () => {
    const t = tagInput.trim().toLowerCase();
    if (t && !form.tags.includes(t)) {
      set('tags', [...form.tags, t]);
    }
    setTagInput('');
  };

  const handleDeploy = () => {
    const name = form.name.trim() || `${form.symbol} Bot`;
    deployBot.mutate(
      { ...form, name },
      {
        onSuccess: (res) => {
          onDeployed?.(res.bot_id);
          onClose();
        },
      }
    );
  };

  const overAllocated = maxAllocation > 0 && form.capital_allocation > maxAllocation;
  const canDeploy = !deployBot.isPending && !overAllocated;
  const atCap = fleetConfig && fleetConfig.max_bots !== undefined;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <div className="relative z-10 w-full max-w-lg rounded-2xl border border-white/8 bg-[#0d0d14] shadow-2xl shadow-primary/10 overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-5 border-b border-white/8">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-primary/20 flex items-center justify-center">
              <Rocket className="w-4 h-4 text-primary" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-white tracking-wide">Deploy New Bot</h2>
              <p className="text-[10px] text-muted-foreground font-mono uppercase tracking-widest">
                Fleet Deployment Wizard
              </p>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-white/5 text-muted-foreground hover:text-white transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-6 space-y-5 max-h-[70vh] overflow-y-auto">

          {/* Identity */}
          <section className="space-y-3">
            <label className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground flex items-center gap-2">
              <Bot className="w-3 h-3" /> Bot Identity
            </label>
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2">
                <input
                  type="text"
                  placeholder="Name (e.g. Alpha Hunter)"
                  value={form.name}
                  onChange={e => set('name', e.target.value)}
                  className="w-full px-3 py-2.5 rounded-xl bg-white/5 border border-white/8 text-sm text-white placeholder-muted-foreground focus:outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20 transition-all font-mono"
                />
              </div>
              <div className="relative">
                <div className="relative group">
                  <input
                    type="text"
                    placeholder="Search Symbol..."
                    value={searchTerm || form.symbol}
                    onFocus={() => setIsOpen(true)}
                    onChange={e => {
                      setSearchTerm(e.target.value);
                      setIsOpen(true);
                    }}
                    className="w-full px-3 py-2.5 rounded-xl bg-white/5 border border-white/8 text-sm text-white placeholder-muted-foreground focus:outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20 transition-all font-mono"
                  />
                  <div className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none">
                    <ChevronDown className={`w-3 h-3 text-muted-foreground transition-transform ${isOpen ? 'rotate-180' : ''}`} />
                  </div>
                </div>

                {isOpen && (
                  <>
                    <div className="fixed inset-0 z-[60]" onClick={() => setIsOpen(false)} />
                    <div className="absolute left-0 right-0 top-full mt-2 z-[70] max-h-60 overflow-y-auto rounded-xl border border-white/8 bg-[#16161f] shadow-2xl backdrop-blur-xl animate-in fade-in slide-in-from-top-2 duration-200">
                      {isLoadingSymbols ? (
                        <div className="p-4 text-center text-xs text-muted-foreground font-mono animate-pulse">
                          Scanning MT5 Terminal...
                        </div>
                      ) : filteredSymbols.length === 0 ? (
                        <div className="p-4 text-center text-xs text-muted-foreground font-mono">
                          No symbols found
                        </div>
                      ) : (
                        <div className="py-2">
                          {filteredSymbols.map(s => (
                            <button
                              key={s.name}
                              onClick={() => {
                                setForm(prev => ({ ...prev, symbol: s.name, qty: s.volume_min ?? 0.01 }));
                                setSearchTerm('');
                                setIsOpen(false);
                              }}
                              className={`w-full px-4 py-2 text-left hover:bg-white/5 transition-colors flex flex-col gap-0.5 ${
                                form.symbol === s.name ? 'bg-primary/10 border-l-2 border-primary' : ''
                              }`}
                            >
                              <div className="flex items-center justify-between">
                                <span className="text-sm font-bold text-white font-mono">{s.name}</span>
                                <span className="text-[9px] text-primary/60 font-mono uppercase px-1.5 py-0.5 rounded-md bg-primary/5 border border-primary/10">
                                  {s.category}
                                </span>
                              </div>
                              {s.description && (
                                <span className="text-[10px] text-muted-foreground font-mono truncate">
                                  {s.description}
                                </span>
                              )}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  </>
                )}
                <p className="text-[9px] text-muted-foreground mt-1 font-mono uppercase tracking-widest">Selected Symbol</p>
              </div>
              <div>
                <select
                  value={form.strategy}
                  onChange={e => set('strategy', e.target.value)}
                  className="w-full px-3 py-2.5 rounded-xl bg-white/5 border border-white/8 text-sm text-white focus:outline-none focus:border-primary/50 transition-all font-mono"
                >
                  {STRATEGIES.map(s => <option key={s} value={s} className="bg-[#0d0d14]">{s.replace('_', ' ').toUpperCase()}</option>)}
                </select>
                <p className="text-[9px] text-muted-foreground mt-1 font-mono">STRATEGY</p>
              </div>
            </div>

            {/* Volume Slider */}
            <div className="px-3 py-3 rounded-xl bg-white/3 border border-white/6 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest">Volume (Lot Size)</span>
                <span className="text-sm font-mono font-semibold text-white tabular-nums">
                  {form.qty.toFixed(volDecimals)}
                </span>
              </div>
              <input
                type="range"
                min={volMin}
                max={volMax}
                step={volStep}
                value={form.qty}
                onChange={e => set('qty', parseFloat(e.target.value))}
                className="w-full accent-primary"
              />
              <div className="flex justify-between text-[9px] font-mono text-muted-foreground">
                <span>MIN {volMin.toFixed(volDecimals)}</span>
                <span>MAX {volMax.toFixed(volDecimals)}</span>
              </div>
            </div>
          </section>

          {/* Allocation & Risk */}
          <section className="space-y-3">
            <label className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground flex items-center gap-2">
              <Shield className="w-3 h-3" /> Allocation & Risk
            </label>
            <div className="space-y-3">
              <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-emerald-500/5 border border-emerald-500/15">
                  <Wifi className="w-3 h-3 text-emerald-400 mt-0.5 shrink-0" />
                  <p className="text-[9px] font-mono text-emerald-400/80 leading-relaxed">
                    Trades execute on the MT5 account currently authenticated in your terminal.
                  </p>
                </div>

              <div className="relative">
                <div className="absolute left-3 top-1/2 -translate-y-1/2 text-[10px] font-mono text-muted-foreground">$</div>
                <input
                  type="number"
                  placeholder="Capital Allocation"
                  value={form.capital_allocation}
                  min={0}
                  max={maxAllocation > 0 ? maxAllocation : undefined}
                  onChange={e => {
                    const val = parseFloat(e.target.value) || 0;
                    set('capital_allocation', maxAllocation > 0 ? Math.min(val, maxAllocation) : val);
                  }}
                  className={`w-full pl-7 pr-3 py-2.5 rounded-xl bg-white/5 border text-sm text-white placeholder-muted-foreground focus:outline-none transition-all font-mono ${
                    overAllocated
                      ? 'border-red-500/60 focus:border-red-500 focus:ring-1 focus:ring-red-500/20'
                      : 'border-white/8 focus:border-primary/50 focus:ring-1 focus:ring-primary/20'
                  }`}
                />
                <div className="flex justify-between mt-1 px-1">
                  <p className="text-[9px] text-muted-foreground font-mono uppercase">CAPITAL ALLOCATION</p>
                  {accountInfo && (
                    <p className={`text-[9px] font-mono ${overAllocated ? 'text-red-400' : 'text-primary/60'}`}>
                      MAX AVAIL: ${maxAllocation.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                    </p>
                  )}
                </div>
                {overAllocated && (
                  <p className="text-[9px] text-red-400 font-mono mt-1 flex items-center gap-1">
                    <AlertTriangle className="w-2.5 h-2.5" /> Exceeds available capital
                  </p>
                )}
              </div>
            </div>
          </section>

          {/* Leverage Settings */}
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Zap className="w-3 h-3 text-violet-400" />
                <span className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest">Scalper Leverage Mode</span>
              </div>
              <button
                onClick={() => set('leverage_mode_enabled', !form.leverage_mode_enabled)}
                className={`w-10 h-5 rounded-full transition-all relative ${form.leverage_mode_enabled ? 'bg-violet-500' : 'bg-white/10'}`}
              >
                <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all ${form.leverage_mode_enabled ? 'left-5' : 'left-0.5'}`} />
              </button>
            </div>

            {form.leverage_mode_enabled && (
              <div className="space-y-3 p-3 rounded-xl bg-violet-500/5 border border-violet-500/10 animate-in slide-in-from-top-1 duration-200">
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1">
                    <span className="text-[9px] font-mono text-muted-foreground uppercase">Isolated Risk ($)</span>
                    <input
                      type="number"
                      value={form.isolated_risk_usd}
                      onChange={e => set('isolated_risk_usd', parseFloat(e.target.value) || 0)}
                      className="w-full px-3 py-2 rounded-xl bg-white/5 border border-white/8 text-sm text-white font-mono focus:outline-none focus:border-violet-500/50"
                    />
                  </div>
                  <div className="space-y-1">
                    <span className="text-[9px] font-mono text-muted-foreground uppercase">Net Profit Target ($)</span>
                    <input
                      type="number"
                      value={form.net_profit_target_usd}
                      onChange={e => set('net_profit_target_usd', parseFloat(e.target.value) || 0)}
                      className="w-full px-3 py-2 rounded-xl bg-white/5 border border-white/8 text-sm text-white font-mono focus:outline-none focus:border-violet-500/50"
                    />
                  </div>
                </div>
                <div className="space-y-1">
                  <span className="text-[9px] font-mono text-muted-foreground uppercase">Trade Take Profit ($)</span>
                  <input
                    type="number"
                    value={form.take_profit_usd}
                    onChange={e => set('take_profit_usd', parseFloat(e.target.value) || 0)}
                    className="w-full px-3 py-2 rounded-xl bg-white/5 border border-white/8 text-sm text-white font-mono focus:outline-none focus:border-violet-500/50"
                  />
                  <p className="text-[8px] font-mono text-muted-foreground/60 italic mt-0.5">
                    Closes individual trades when profit hits this amount.
                  </p>
                </div>
                <div className="space-y-1">
                  <div className="flex justify-between">
                    <span className="text-[9px] font-mono text-muted-foreground uppercase">Leverage Factor</span>
                    <span className="text-xs font-mono text-violet-400">{form.leverage_factor}x</span>
                  </div>
                  <input
                    type="range"
                    min={1}
                    max={100}
                    step={1}
                    value={form.leverage_factor}
                    onChange={e => set('leverage_factor', parseInt(e.target.value))}
                    className="w-full accent-violet-500"
                  />
                </div>
              </div>
            )}
          </section>

          {/* Sub-Agents */}
          <section className="space-y-3">
            <label className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground flex items-center gap-2">
              <BrainCircuit className="w-3 h-3" /> Sub-Agent Pool
            </label>
            <div className="grid grid-cols-2 gap-2">
              {ALL_AGENTS.map(agent => (
                <button
                  key={agent}
                  onClick={() => toggleAgent(agent)}
                  className={`py-2 px-3 rounded-xl text-xs font-mono font-medium transition-all border flex items-center gap-2 ${
                    form.sub_agents.includes(agent)
                      ? 'bg-primary/20 border-primary/50 text-primary'
                      : 'bg-white/5 border-white/8 text-muted-foreground hover:border-white/20'
                  }`}
                >
                  <span className={`w-1.5 h-1.5 rounded-full ${form.sub_agents.includes(agent) ? 'bg-primary animate-pulse' : 'bg-muted-foreground/30'}`} />
                  {agent.toUpperCase()}
                </button>
              ))}
            </div>
          </section>

          {/* Tags */}
          <section className="space-y-2">
            <label className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground flex items-center gap-2">
              <Wifi className="w-3 h-3" /> Tags
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={tagInput}
                onChange={e => setTagInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && addTag()}
                placeholder="e.g. crypto, aggressive"
                className="flex-1 px-3 py-2 rounded-xl bg-white/5 border border-white/8 text-xs text-white placeholder-muted-foreground focus:outline-none focus:border-primary/50 transition-all font-mono"
              />
              <button onClick={addTag} className="px-3 py-2 rounded-xl bg-white/5 border border-white/8 text-xs text-muted-foreground hover:text-white transition-colors">+</button>
            </div>
            {form.tags.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {form.tags.map(tag => (
                  <span key={tag} onClick={() => set('tags', form.tags.filter(t => t !== tag))}
                    className="px-2 py-0.5 rounded-full bg-primary/10 border border-primary/20 text-[10px] text-primary font-mono cursor-pointer hover:bg-red-500/10 hover:border-red-500/30 hover:text-red-400 transition-colors">
                    #{tag} ×
                  </span>
                ))}
              </div>
            )}
          </section>

          {/* Advanced Toggle */}
          <button
            onClick={() => setAdvanced(!advanced)}
            className="w-full flex items-center justify-between px-3 py-2.5 rounded-xl bg-white/3 border border-white/6 text-[10px] font-mono uppercase tracking-widest text-muted-foreground hover:text-white hover:border-white/12 transition-all"
          >
            <span className="flex items-center gap-2"><BarChart2 className="w-3 h-3" /> Advanced Parameters</span>
            {advanced ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          </button>

          {advanced && (
            <section className="space-y-3 animate-in fade-in duration-200">
              {[
                { key: 'stop_loss_pct' as const, label: 'Stop Loss %', min: 0.25, max: 5.0, step: 0.25, type: 'float' },
                { key: 'bb_period' as const, label: 'BB Period', min: 8, max: 100, step: 1, type: 'int' },
                { key: 'bb_std_dev' as const, label: 'BB Std Dev', min: 1.0, max: 3.5, step: 0.1, type: 'float' },
                { key: 'ai_interval_minutes' as const, label: 'AI Interval (min)', min: 5, max: 1440, step: 5, type: 'int' },
              ].map(({ key, label, min, max, step, type }) => (
                <div key={key} className="flex items-center gap-3">
                  <span className="text-[10px] font-mono text-muted-foreground w-36 shrink-0">{label}</span>
                  <input
                    type="range"
                    min={min} max={max} step={step}
                    value={form[key] as number}
                    onChange={e => set(key, type === 'int' ? parseInt(e.target.value) : parseFloat(e.target.value))}
                    className="flex-1 accent-primary"
                  />
                  <span className="text-xs font-mono text-white w-10 text-right tabular-nums">
                    {(form[key] as number).toFixed(type === 'float' ? 1 : 0)}
                  </span>
                </div>
              ))}
              <div className="flex items-center justify-between pt-1">
                <span className="text-[10px] font-mono text-muted-foreground">Fibonacci Enabled</span>
                <button
                  onClick={() => set('fib_enabled', !form.fib_enabled)}
                  className={`w-10 h-5 rounded-full transition-all relative ${form.fib_enabled ? 'bg-primary' : 'bg-white/10'}`}
                >
                  <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all ${form.fib_enabled ? 'left-5' : 'left-0.5'}`} />
                </button>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-mono text-muted-foreground">AI Brain Enabled</span>
                <button
                  onClick={() => set('ai_brain_enabled', !form.ai_brain_enabled)}
                  className={`w-10 h-5 rounded-full transition-all relative ${form.ai_brain_enabled ? 'bg-violet-500' : 'bg-white/10'}`}
                >
                  <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all ${form.ai_brain_enabled ? 'left-5' : 'left-0.5'}`} />
                </button>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-mono text-muted-foreground">Short Selling</span>
                <button
                  onClick={() => set('short_selling_enabled', !form.short_selling_enabled)}
                  className={`w-10 h-5 rounded-full transition-all relative ${form.short_selling_enabled ? 'bg-orange-500' : 'bg-white/10'}`}
                >
                  <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all ${form.short_selling_enabled ? 'left-5' : 'left-0.5'}`} />
                </button>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-mono text-muted-foreground">Auto-start on deployment</span>
                <button
                  onClick={() => set('auto_start', !form.auto_start)}
                  className={`w-10 h-5 rounded-full transition-all relative ${form.auto_start ? 'bg-emerald-500' : 'bg-white/10'}`}
                >
                  <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all ${form.auto_start ? 'left-5' : 'left-0.5'}`} />
                </button>
              </div>


            </section>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-white/8 flex items-center justify-between gap-3">
          {deployBot.isError && (
            <p className="text-xs text-red-400 font-mono flex-1">
              {(deployBot.error as any)?.response?.data?.detail || 'Deploy failed'}
            </p>
          )}
          <div className="flex gap-2 ml-auto">
            <button onClick={onClose} className="px-4 py-2 rounded-xl border border-white/8 text-xs text-muted-foreground hover:text-white hover:border-white/20 transition-all font-mono">
              CANCEL
            </button>
            <button
              onClick={handleDeploy}
              disabled={!canDeploy}
              className="px-5 py-2 rounded-xl bg-primary text-primary-foreground text-xs font-mono font-semibold hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center gap-2"
            >
              <Rocket className="w-3.5 h-3.5" />
              {deployBot.isPending ? 'DEPLOYING...' : 'DEPLOY BOT'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
