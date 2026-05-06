'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  X, Rocket, ChevronRight, ChevronLeft, RefreshCw,
  Zap, Shield, Brain, BarChart2, TrendingUp,
  ArrowRight, Check, Loader2, Sparkles
} from 'lucide-react';
import { api } from '@/lib/api';
import { useDeployBot } from '@/hooks/useFleet';

// ─────────────────────────────────────────────────────────
// DATA
// ─────────────────────────────────────────────────────────

const CATEGORIES = [
  { id: 'Equities',    label: 'Equities',    icon: '📈', color: 'from-blue-500/20 to-blue-500/5',   border: 'border-blue-500/30',   glow: 'shadow-blue-500/20' },
  { id: 'ETFs',        label: 'ETFs',         icon: '🏦', color: 'from-indigo-500/20 to-indigo-500/5', border: 'border-indigo-500/30', glow: 'shadow-indigo-500/20' },
  { id: 'Crypto',      label: 'Crypto',       icon: '₿',  color: 'from-orange-500/20 to-orange-500/5', border: 'border-orange-500/30', glow: 'shadow-orange-500/20' },
  { id: 'Forex',       label: 'Forex',        icon: '💱', color: 'from-cyan-500/20 to-cyan-500/5',   border: 'border-cyan-500/30',   glow: 'shadow-cyan-500/20' },
  { id: 'Commodities', label: 'Commodities',  icon: '🥇', color: 'from-yellow-500/20 to-yellow-500/5', border: 'border-yellow-500/30', glow: 'shadow-yellow-500/20' },
];

const SYMBOLS_BY_CATEGORY: Record<string, { ticker: string; name: string; flag?: string }[]> = {
  Equities: [
    { ticker: 'AAPL',  name: 'Apple' },
    { ticker: 'NVDA',  name: 'Nvidia' },
    { ticker: 'MSFT',  name: 'Microsoft' },
    { ticker: 'TSLA',  name: 'Tesla' },
    { ticker: 'AMZN',  name: 'Amazon' },
    { ticker: 'GOOGL', name: 'Alphabet' },
    { ticker: 'META',  name: 'Meta' },
    { ticker: 'NFLX',  name: 'Netflix' },
    { ticker: 'AMD',   name: 'AMD' },
    { ticker: 'BABA',  name: 'Alibaba' },
  ],
  ETFs: [
    { ticker: 'SPY',  name: 'S&P 500' },
    { ticker: 'QQQ',  name: 'Nasdaq 100' },
    { ticker: 'IWM',  name: 'Russell 2000' },
    { ticker: 'DIA',  name: 'Dow Jones' },
    { ticker: 'GLD',  name: 'Gold ETF' },
    { ticker: 'SLV',  name: 'Silver ETF' },
    { ticker: 'XLF',  name: 'Financials' },
    { ticker: 'XLT',  name: 'Technology' },
    { ticker: 'ARKK', name: 'ARK Innov.' },
    { ticker: 'VTI',  name: 'Total Mkt' },
  ],
  Crypto: [
    { ticker: 'BTC/USD', name: 'Bitcoin' },
    { ticker: 'ETH/USD', name: 'Ethereum' },
    { ticker: 'SOL/USD', name: 'Solana' },
    { ticker: 'XRP/USD', name: 'Ripple' },
    { ticker: 'ADA/USD', name: 'Cardano' },
    { ticker: 'DOGE/USD',name: 'Dogecoin' },
    { ticker: 'AVAX/USD',name: 'Avalanche' },
    { ticker: 'DOT/USD', name: 'Polkadot' },
    { ticker: 'LINK/USD',name: 'Chainlink' },
    { ticker: 'UNI/USD', name: 'Uniswap' },
  ],
  Forex: [
    { ticker: 'EUR/USD', name: 'EUR/USD', flag: '🇪🇺' },
    { ticker: 'GBP/USD', name: 'GBP/USD', flag: '🇬🇧' },
    { ticker: 'USD/JPY', name: 'USD/JPY', flag: '🇯🇵' },
    { ticker: 'AUD/USD', name: 'AUD/USD', flag: '🇦🇺' },
    { ticker: 'USD/CAD', name: 'USD/CAD', flag: '🇨🇦' },
    { ticker: 'USD/CHF', name: 'USD/CHF', flag: '🇨🇭' },
    { ticker: 'NZD/USD', name: 'NZD/USD', flag: '🇳🇿' },
    { ticker: 'EUR/GBP', name: 'EUR/GBP', flag: '🇪🇺' },
    { ticker: 'EUR/JPY', name: 'EUR/JPY', flag: '🇪🇺' },
    { ticker: 'GBP/JPY', name: 'GBP/JPY', flag: '🇬🇧' },
  ],
  Commodities: [
    { ticker: 'GLD',   name: 'Gold ETF' },
    { ticker: 'SLV',   name: 'Silver ETF' },
    { ticker: 'USO',   name: 'Oil ETF' },
    { ticker: 'UNG',   name: 'Nat Gas ETF' },
    { ticker: 'WEAT',  name: 'Wheat ETF' },
    { ticker: 'CORN',  name: 'Corn ETF' },
    { ticker: 'SOYB',  name: 'Soybean ETF' },
    { ticker: 'CPER',  name: 'Copper ETF' },
    { ticker: 'PPLT',  name: 'Platinum ETF' },
    { ticker: 'PALL',  name: 'Palladium ETF' },
  ],
};

const PERSONALITIES = [
  {
    id: 'elephant',
    name: 'Patient Elephant',
    tagline: 'Slow and unstoppable',
    image: '/animals/elephant.png',
    riskLevel: 1,
    riskColor: 'from-cyan-400 to-teal-500',
    glowColor: 'shadow-cyan-500/40',
    borderColor: 'border-cyan-500/60',
    bgColor: 'from-cyan-950/60 to-[#0d0d14]',
    traits: ['Ultra-tight stops', 'Patient entries', '4-agent council'],
    description: 'Maximum capital preservation. Waits for perfect storms.',
    strategy: 'mean_reversion',
    strategyLabel: 'Value Guardian',
    huntingDescription: 'Waits for "oversold" signals. Slow, safe, and deliberate.',
  },
  {
    id: 'buffalo',
    name: 'Grazing Buffalo',
    tagline: 'Strength through discipline',
    image: '/animals/buffalo.png',
    riskLevel: 2,
    riskColor: 'from-emerald-400 to-green-500',
    glowColor: 'shadow-emerald-500/40',
    borderColor: 'border-emerald-500/60',
    bgColor: 'from-emerald-950/60 to-[#0d0d14]',
    traits: ['Conservative sizing', 'AND-gated signals', '5-agent quorum'],
    description: 'Methodical herd instinct. Moves only with full conviction.',
    strategy: 'combined',
    strategyLabel: 'Balanced Hunter',
    huntingDescription: 'Uses multiple indicators to find high-probability setups.',
  },
  {
    id: 'rhino',
    name: 'Steady Rhino',
    tagline: 'Charges when confident',
    image: '/animals/rhino.png',
    riskLevel: 3,
    riskColor: 'from-amber-400 to-yellow-500',
    glowColor: 'shadow-amber-500/40',
    borderColor: 'border-amber-500/60',
    bgColor: 'from-amber-950/60 to-[#0d0d14]',
    traits: ['Balanced risk', 'OR-gated Fib', 'Fast AI cycles'],
    description: 'Armoured patience meets decisive momentum strikes.',
    strategy: 'trend_following',
    strategyLabel: 'Momentum Charge',
    huntingDescription: 'Identifies strong trends and rides the wave while it stays hot.',
  },
  {
    id: 'leopard',
    name: 'Prowling Leopard',
    tagline: 'Silent, precise, lethal',
    image: '/animals/leopard.png',
    riskLevel: 4,
    riskColor: 'from-orange-400 to-amber-500',
    glowColor: 'shadow-orange-500/40',
    borderColor: 'border-orange-500/60',
    bgColor: 'from-orange-950/60 to-[#0d0d14]',
    traits: ['High-qty entries', 'Tight Fib levels', '30-min AI scans'],
    description: 'Stealthy accumulation. Strikes from Fibonacci ambush.',
    strategy: 'mean_reversion',
    strategyLabel: 'Rapid Scalper',
    huntingDescription: 'Fires fast trades on quick bounces. High frequency, tight exits.',
  },
  {
    id: 'lion',
    name: 'Hungry Lion',
    tagline: 'Apex-mode, no mercy',
    image: '/animals/lion.png',
    riskLevel: 5,
    riskColor: 'from-red-400 to-rose-500',
    glowColor: 'shadow-red-500/40',
    borderColor: 'border-red-500/60',
    bgColor: 'from-red-950/60 to-[#0d0d14]',
    traits: ['Max position size', 'All 5 agents', '20-min AI cycles'],
    description: 'Apex predator. Full aggression. Territory is everything.',
    strategy: 'combined',
    strategyLabel: 'Apex Predator',
    huntingDescription: 'Maximum aggression. Uses all high-power strategies at once.',
  },
];

const FORGE_MESSAGES = [
  'Scanning savanna for optimal entry zones…',
  'Awakening spirit animal protocols…',
  'Calibrating Fibonacci instincts…',
  'Assembling expert agent council…',
  'Forging bot identity with AI…',
  'Encoding hunting patterns…',
  'Finalising battle configuration…',
];

type Step = 'category' | 'symbol' | 'personality' | 'forge' | 'review' | 'deploy';

interface WizardResult {
  name: string;
  description: string;
  personality: string;
  animal: string;
  symbol: string;
  category: string;
  config: Record<string, any>;
  ai_generated: boolean;
}

interface Props {
  onClose: () => void;
  onDeployed?: (botId: string) => void;
}

// ─────────────────────────────────────────────────────────
// RISK THERMOMETER
// ─────────────────────────────────────────────────────────
function RiskBar({ level, color }: { level: number; color: string }) {
  return (
    <div className="flex gap-1 items-center">
      {[1, 2, 3, 4, 5].map(i => (
        <div
          key={i}
          className={`h-1.5 flex-1 rounded-full transition-all duration-300 ${
            i <= level
              ? `bg-gradient-to-r ${color} opacity-100`
              : 'bg-white/10'
          }`}
        />
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────
// STEP INDICATOR
// ─────────────────────────────────────────────────────────
const STEPS: { id: Step; label: string }[] = [
  { id: 'category',    label: 'Market' },
  { id: 'symbol',      label: 'Symbol' },
  { id: 'personality', label: 'Spirit' },
  { id: 'forge',       label: 'Forge' },
  { id: 'review',      label: 'Review' },
];

function StepIndicator({ current }: { current: Step }) {
  const idx = STEPS.findIndex(s => s.id === current);
  return (
    <div className="flex items-center gap-1">
      {STEPS.map((s, i) => (
        <div key={s.id} className="flex items-center gap-1">
          <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[9px] font-mono uppercase tracking-widest transition-all ${
            i < idx
              ? 'bg-primary/20 text-primary'
              : i === idx
              ? 'bg-primary text-white'
              : 'text-muted-foreground'
          }`}>
            {i < idx && <Check className="w-2.5 h-2.5" />}
            {s.label}
          </div>
          {i < STEPS.length - 1 && (
            <div className={`w-3 h-px ${i < idx ? 'bg-primary/40' : 'bg-white/10'}`} />
          )}
        </div>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────
// MAIN WIZARD
// ─────────────────────────────────────────────────────────
export function BotWizard({ onClose, onDeployed }: Props) {
  const [step, setStep]           = useState<Step>('category');
  const [category, setCategory]   = useState('');
  const [symbol, setSymbol]       = useState('');
  const [customSymbol, setCustomSymbol] = useState('');
  const [personality, setPersonality] = useState('');
  const [result, setResult]       = useState<WizardResult | null>(null);
  const [forgeMsg, setForgeMsg]   = useState(0);
  const [capitalAllocation, setCapitalAllocation] = useState(10000);
  const [forgeError, setForgeError] = useState('');
  const deployBot = useDeployBot();

  // Cycle through forge messages
  useEffect(() => {
    if (step !== 'forge') return;
    const t = setInterval(() => setForgeMsg(m => (m + 1) % FORGE_MESSAGES.length), 1400);
    return () => clearInterval(t);
  }, [step]);

  const selectedPersonality = PERSONALITIES.find(p => p.id === personality);
  const selectedCategory    = CATEGORIES.find(c => c.id === category);

  // ── AI Forge ──────────────────────────────────────────
  const runForge = useCallback(async () => {
    setStep('forge');
    setForgeError('');
    const sym = customSymbol.trim().toUpperCase() || symbol;
    try {
      const { data } = await api.post('/fleet/wizard/generate', {
        symbol: sym,
        category,
        personality,
        strategy: selectedPersonality?.strategy || 'combined',
      });
      setResult(data);
      setStep('review');
    } catch (err: any) {
      setForgeError(err?.response?.data?.detail || 'Generation failed. Please try again.');
      setStep('personality');
    }
  }, [symbol, customSymbol, category, personality]);

  // ── Deploy ────────────────────────────────────────────
  const handleDeploy = () => {
    if (!result) return;
    const payload = {
      ...result.config,
      name: result.name,
      description: result.description,
      personality: result.personality,
      animal: result.animal,
      category: result.category,
      symbol: result.symbol,
      ai_generated: result.ai_generated,
      capital_allocation: capitalAllocation,
      sub_agents: result.config.sub_agents ?? [],
      tags: result.config.tags ?? [],
      fib_enabled: true,
      ai_brain_enabled: true,
    };
    deployBot.mutate(payload, {
      onSuccess: (res: any) => {
        onDeployed?.(res.bot_id);
        onClose();
      },
    });
  };

  // ─────────────────────────────────────────────────────
  // RENDER STEPS
  // ─────────────────────────────────────────────────────

  const renderCategory = () => (
    <div className="space-y-4 animate-in fade-in duration-300">
      <div className="text-center space-y-1 pb-2">
        <h3 className="text-white font-semibold text-base">Choose your market</h3>
        <p className="text-muted-foreground text-xs">Where does your bot hunt?</p>
      </div>
      <div className="grid grid-cols-1 gap-2.5">
        {CATEGORIES.map(cat => (
          <button
            key={cat.id}
            onClick={() => { setCategory(cat.id); setSymbol(''); setTimeout(() => setStep('symbol'), 180); }}
            className={`relative flex items-center gap-4 p-4 rounded-2xl border bg-gradient-to-r ${cat.color} ${cat.border} hover:shadow-lg ${cat.glow} transition-all duration-200 group text-left`}
          >
            <span className="text-2xl">{cat.icon}</span>
            <div className="flex-1">
              <p className="text-white text-sm font-semibold">{cat.label}</p>
              <p className="text-muted-foreground text-[10px]">
                {SYMBOLS_BY_CATEGORY[cat.id].slice(0, 3).map(s => s.ticker).join(' · ')} + more
              </p>
            </div>
            <ChevronRight className="w-4 h-4 text-muted-foreground group-hover:text-white group-hover:translate-x-0.5 transition-all" />
          </button>
        ))}
      </div>
    </div>
  );

  const renderSymbol = () => {
    const symbols = SYMBOLS_BY_CATEGORY[category] ?? [];
    return (
      <div className="space-y-4 animate-in fade-in duration-300">
        <div className="flex items-center gap-2">
          <button onClick={() => setStep('category')} className="p-1.5 rounded-lg hover:bg-white/5 text-muted-foreground hover:text-white transition-colors">
            <ChevronLeft className="w-4 h-4" />
          </button>
          <div>
            <h3 className="text-white font-semibold text-sm">Pick a symbol</h3>
            <p className="text-muted-foreground text-[10px]">{category} · Select or type your own</p>
          </div>
        </div>
        <div className="grid grid-cols-5 gap-2">
          {symbols.map(s => (
            <button
              key={s.ticker}
              onClick={() => { setSymbol(s.ticker); setCustomSymbol(''); setTimeout(() => setStep('personality'), 180); }}
              className={`flex flex-col items-center gap-1 p-2.5 rounded-xl border transition-all duration-150 ${
                symbol === s.ticker
                  ? 'bg-primary/20 border-primary/60 text-primary'
                  : 'bg-white/3 border-white/8 text-muted-foreground hover:border-white/20 hover:text-white'
              }`}
            >
              <span className="text-[11px] font-mono font-bold text-white truncate w-full text-center">{s.ticker.replace('/USD','')}</span>
              <span className="text-[8px] text-muted-foreground truncate w-full text-center leading-tight">{s.name}</span>
            </button>
          ))}
        </div>
        <div className="flex gap-2 pt-1">
          <div className="relative flex-1">
            <input
              type="text"
              placeholder="Custom symbol e.g. PLTR"
              value={customSymbol}
              onChange={e => { setCustomSymbol(e.target.value.toUpperCase()); setSymbol(''); }}
              className="w-full px-3 py-2.5 rounded-xl bg-white/5 border border-white/10 text-sm text-white placeholder-muted-foreground focus:outline-none focus:border-primary/50 font-mono"
            />
          </div>
          <button
            onClick={() => { if (customSymbol.trim()) setStep('personality'); }}
            disabled={!customSymbol.trim()}
            className="px-4 py-2.5 rounded-xl bg-primary/20 border border-primary/40 text-primary text-xs font-mono font-semibold hover:bg-primary/30 disabled:opacity-30 transition-all flex items-center gap-1.5"
          >
            Next <ChevronRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    );
  };

  const renderPersonality = () => (
    <div className="space-y-3 animate-in fade-in duration-300">
      <div className="flex items-center gap-2">
        <button onClick={() => setStep('symbol')} className="p-1.5 rounded-lg hover:bg-white/5 text-muted-foreground hover:text-white transition-colors">
          <ChevronLeft className="w-4 h-4" />
        </button>
        <div>
          <h3 className="text-white font-semibold text-sm">Choose your spirit animal</h3>
          <p className="text-muted-foreground text-[10px]">How aggressive should your bot hunt?</p>
        </div>
      </div>
      {forgeError && (
        <div className="px-3 py-2 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400 text-xs font-mono">
          ⚠ {forgeError}
        </div>
      )}
      <div className="space-y-2">
        {PERSONALITIES.map(p => (
          <button
            key={p.id}
            onClick={() => setPersonality(p.id)}
            className={`w-full relative overflow-hidden rounded-2xl border transition-all duration-200 group text-left ${
              personality === p.id
                ? `${p.borderColor} shadow-lg ${p.glowColor}`
                : 'border-white/8 hover:border-white/20'
            }`}
          >
            {/* Background image */}
            <div className="absolute inset-0">
              <img src={p.image} alt="" className="w-full h-full object-cover object-center opacity-20 group-hover:opacity-30 transition-opacity" />
              <div className={`absolute inset-0 bg-gradient-to-r ${p.bgColor}`} />
            </div>
            <div className="relative flex items-center gap-4 p-3.5">
              {/* Selection ring */}
              <div className={`w-10 h-10 rounded-xl border-2 flex items-center justify-center shrink-0 transition-all ${
                personality === p.id ? `${p.borderColor} bg-white/10` : 'border-white/15 bg-white/5'
              }`}>
                {personality === p.id
                  ? <Check className="w-4 h-4 text-white" />
                  : <span className="text-lg">{p.id === 'elephant' ? '🐘' : p.id === 'buffalo' ? '🦬' : p.id === 'rhino' ? '🦏' : p.id === 'leopard' ? '🐆' : '🦁'}</span>
                }
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-start justify-between gap-2 mb-0.5">
                  <div>
                    <div className="flex items-center gap-2">
                      <p className="text-white text-sm font-semibold leading-tight">{p.name}</p>
                      <span className="px-1.5 py-0.5 rounded-sm bg-white/10 border border-white/10 text-[7px] font-mono text-primary/80 uppercase tracking-tighter">
                        {p.strategyLabel}
                      </span>
                    </div>
                    <p className="text-muted-foreground text-[10px] italic">{p.tagline}</p>
                  </div>
                  <div className="shrink-0 w-16 pt-1">
                    <RiskBar level={p.riskLevel} color={p.riskColor} />
                  </div>
                </div>
                <p className="text-white/60 text-[9px] mb-1.5 leading-tight">{p.huntingDescription}</p>
                <div className="flex flex-wrap gap-1">
                  {p.traits.map(t => (
                    <span key={t} className="px-1.5 py-0.5 rounded-full bg-white/8 text-[9px] text-muted-foreground font-mono">{t}</span>
                  ))}
                </div>
              </div>
            </div>
          </button>
        ))}
      </div>
      <button
        onClick={runForge}
        disabled={!personality}
        className="w-full py-3 rounded-2xl bg-gradient-to-r from-primary to-violet-500 text-white text-sm font-semibold font-mono hover:opacity-90 disabled:opacity-30 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2 shadow-lg shadow-primary/30"
      >
        <Sparkles className="w-4 h-4" />
        Forge My Bot
        <ArrowRight className="w-4 h-4" />
      </button>
    </div>
  );

  const renderForge = () => (
    <div className="flex flex-col items-center justify-center py-10 space-y-8 animate-in fade-in duration-300">
      {/* Central animated orb */}
      <div className="relative w-32 h-32">
        <div className="absolute inset-0 rounded-full bg-gradient-to-br from-primary to-violet-600 opacity-20 animate-ping" />
        <div className="absolute inset-2 rounded-full bg-gradient-to-br from-primary to-violet-600 opacity-40 animate-pulse" />
        <div className="absolute inset-4 rounded-full bg-gradient-to-br from-primary to-violet-600 flex items-center justify-center">
          {selectedPersonality && (
            <img
              src={selectedPersonality.image}
              alt=""
              className="w-full h-full object-cover rounded-full opacity-80"
            />
          )}
        </div>
        {/* Orbiting dots */}
        <div className="absolute inset-0 animate-spin" style={{ animationDuration: '3s' }}>
          <div className="absolute top-0 left-1/2 -translate-x-1/2 w-2 h-2 rounded-full bg-primary" />
        </div>
        <div className="absolute inset-0 animate-spin" style={{ animationDuration: '5s', animationDirection: 'reverse' }}>
          <div className="absolute bottom-0 left-1/2 -translate-x-1/2 w-1.5 h-1.5 rounded-full bg-violet-400" />
        </div>
      </div>

      <div className="text-center space-y-2">
        <p className="text-white font-semibold text-base">AI Forge Active</p>
        <p className="text-muted-foreground text-xs font-mono px-6 text-center min-h-[2rem] transition-all">
          {FORGE_MESSAGES[forgeMsg]}
        </p>
      </div>

      {/* Symbol + personality badges */}
      <div className="flex items-center gap-2">
        <span className="px-3 py-1 rounded-full bg-white/8 border border-white/12 text-xs font-mono text-white">
          {customSymbol.trim().toUpperCase() || symbol}
        </span>
        <span className="text-muted-foreground text-xs">+</span>
        <span className={`px-3 py-1 rounded-full border text-xs font-mono ${selectedPersonality?.borderColor ?? ''} bg-white/5 text-white`}>
          {selectedPersonality?.name}
        </span>
      </div>

      <Loader2 className="w-5 h-5 text-primary animate-spin" />
    </div>
  );

  const renderReview = () => {
    if (!result) return null;
    const p = PERSONALITIES.find(x => x.id === result.personality)!;
    const cfg = result.config;

    const stats = [
      { label: 'Symbol',    value: result.symbol,                         icon: <BarChart2 className="w-3 h-3" /> },
      { label: 'Category',  value: result.category,                        icon: <TrendingUp className="w-3 h-3" /> },
      { label: 'Strategy',  value: (cfg.strategy ?? 'combined').toUpperCase().replace('_', ' '), icon: <Brain className="w-3 h-3" /> },
      { label: 'Agents',    value: `${(cfg.sub_agents ?? []).length} active`, icon: <Zap className="w-3 h-3" /> },
      { label: 'Stop Loss', value: `${cfg.stop_loss_pct ?? '—'}%`,        icon: <Shield className="w-3 h-3" /> },
      { label: 'Max DD',    value: `${cfg.max_daily_drawdown_pct ?? '—'}%/day`, icon: <Shield className="w-3 h-3" /> },
    ];

    return (
      <div className="space-y-4 animate-in fade-in duration-300">
        {/* Hero card */}
        <div className={`relative overflow-hidden rounded-2xl border ${p.borderColor} shadow-xl ${p.glowColor}`}>
          <img src={p.image} alt="" className="absolute inset-0 w-full h-full object-cover opacity-15" />
          <div className={`absolute inset-0 bg-gradient-to-b ${p.bgColor} opacity-90`} />
          <div className="relative p-4 space-y-2">
            <div className="flex items-start justify-between">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span className="px-1.5 py-0.5 rounded-sm bg-white/10 text-[8px] font-mono uppercase text-muted-foreground tracking-widest">
                    {result.ai_generated ? '✦ AI Generated' : 'Preset'}
                  </span>
                </div>
                <h3 className="text-white font-bold text-lg leading-tight">{result.name}</h3>
                <p className="text-muted-foreground text-[10px] italic font-mono mt-0.5">{p.tagline}</p>
              </div>
              <button
                onClick={runForge}
                className="p-1.5 rounded-lg bg-white/8 hover:bg-white/15 text-muted-foreground hover:text-white transition-all"
                title="Regenerate"
              >
                <RefreshCw className="w-3.5 h-3.5" />
              </button>
            </div>
            <p className="text-white/80 text-xs leading-relaxed">{result.description}</p>
            <div className="flex items-center gap-2 pt-1">
              <span className="text-[9px] font-mono text-muted-foreground uppercase">RISK</span>
              <div className="flex-1">
                <RiskBar level={p.riskLevel} color={p.riskColor} />
              </div>
            </div>
          </div>
        </div>

        {/* Config stats */}
        <div className="grid grid-cols-3 gap-2">
          {stats.map(s => (
            <div key={s.label} className="flex flex-col gap-1 p-3 rounded-xl bg-white/3 border border-white/8">
              <div className="flex items-center gap-1 text-muted-foreground">
                {s.icon}
                <span className="text-[8px] font-mono uppercase tracking-widest">{s.label}</span>
              </div>
              <span className="text-white text-xs font-mono font-semibold truncate">{s.value}</span>
            </div>
          ))}
        </div>

        {/* Capital Allocation */}
        <div className="space-y-3 p-3 rounded-xl bg-white/3 border border-white/8">
          <div className="flex items-center justify-between">
            <label className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground flex items-center gap-2">
              <Shield className="w-3 h-3" /> Capital Allocation
            </label>
            <div className="flex items-center gap-2 bg-white/5 border border-white/10 rounded-lg px-2 py-1">
              <span className="text-muted-foreground text-xs">$</span>
              <input
                type="number"
                min="100"
                max="1000000"
                step="500"
                value={capitalAllocation}
                onChange={(e) => setCapitalAllocation(parseInt(e.target.value) || 0)}
                className="bg-transparent border-none text-right text-xs font-mono font-bold text-primary focus:ring-0 p-0 w-20 appearance-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
              />
            </div>
          </div>
          <input
            type="range"
            min="1000"
            max="100000"
            step="1000"
            value={capitalAllocation > 100000 ? 100000 : capitalAllocation}
            onChange={(e) => setCapitalAllocation(parseInt(e.target.value))}
            className="w-full accent-primary bg-white/10 rounded-lg h-1.5 appearance-none cursor-pointer"
          />
          <div className="flex justify-between text-[8px] font-mono text-muted-foreground uppercase">
            <span>$1k</span>
            <span>Allocation per Bot</span>
            <span>$100k</span>
          </div>
        </div>
      </div>
    );
  };

  // ─────────────────────────────────────────────────────
  // LAYOUT
  // ─────────────────────────────────────────────────────
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/75 backdrop-blur-md" onClick={onClose} />

      {/* Modal */}
      <div className="relative z-10 w-full max-w-md rounded-3xl border border-white/10 bg-[#0a0a12] shadow-2xl shadow-primary/10 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-white/8">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-primary to-violet-500 flex items-center justify-center">
              <span className="text-sm">🦁</span>
            </div>
            <div>
              <h2 className="text-sm font-bold text-white tracking-wide">Savanna Wizard</h2>
              <p className="text-[9px] text-muted-foreground font-mono uppercase tracking-widest">
                AI-Powered Bot Forge
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {step !== 'forge' && <StepIndicator current={step} />}
            <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-white/5 text-muted-foreground hover:text-white transition-colors">
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="p-5 max-h-[72vh] overflow-y-auto">
          {step === 'category'    && renderCategory()}
          {step === 'symbol'      && renderSymbol()}
          {step === 'personality' && renderPersonality()}
          {step === 'forge'       && renderForge()}
          {step === 'review'      && renderReview()}
        </div>

        {/* Footer — only shown on review */}
        {step === 'review' && (
          <div className="px-5 py-4 border-t border-white/8 flex items-center gap-3">
            <button
              onClick={() => setStep('personality')}
              className="px-4 py-2 rounded-xl border border-white/8 text-xs text-muted-foreground hover:text-white hover:border-white/20 transition-all font-mono flex items-center gap-1.5"
            >
              <ChevronLeft className="w-3 h-3" /> Back
            </button>
            <button
              onClick={handleDeploy}
              disabled={deployBot.isPending}
              className="flex-1 py-2.5 rounded-xl bg-gradient-to-r from-primary to-violet-500 text-white text-xs font-mono font-bold hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2 shadow-lg shadow-primary/30"
            >
              {deployBot.isPending ? (
                <><Loader2 className="w-3.5 h-3.5 animate-spin" /> DEPLOYING…</>
              ) : (
                <><Rocket className="w-3.5 h-3.5" /> DEPLOY BOT</>
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
