'use client';

import { useState, useRef, useEffect } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Zap, Bot, LayoutDashboard, Radio, Activity, 
  ChevronDown, Wallet, TrendingUp, TrendingDown, 
  DollarSign, CreditCard, Power, Loader2, Coffee
} from 'lucide-react';
import { useFleetStatus, useMT5Account } from '@/hooks/useFleet';
import { FleetStatus } from '@/lib/api';
import { motion, AnimatePresence } from 'framer-motion';
import { SystemResourceMonitor } from '@/components/SystemResourceMonitor';


const links = [
  { href: '/',               label: 'DASHBOARD',     icon: <LayoutDashboard className="w-3.5 h-3.5" /> },
  { href: '/bnb',            label: 'BNB PULSE',     icon: <Zap className="w-3.5 h-3.5 text-amber-400" /> },
  { href: '/fleet',          label: 'FLEET COMMAND', icon: <Bot className="w-3.5 h-3.5" /> },
  { href: '/ticker',         label: 'LIVE TICKER',   icon: <Activity className="w-3.5 h-3.5" /> },
  { href: '/situation-room', label: 'SITUATION ROOM',icon: <Radio className="w-3.5 h-3.5" /> },
];

function ServerPowerButton() {
  const [isRunning, setIsRunning] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  // Poll server state every 3s
  useEffect(() => {
    let mounted = true;
    const checkState = async () => {
      try {
        const res = await fetch('/api/server');
        const data = await res.json();
        if (mounted) {
          setIsRunning(data.running);
          setIsLoading(false);
        }
      } catch {
        if (mounted) {
          setIsRunning(false);
          setIsLoading(false);
        }
      }
    };
    checkState();
    const interval = setInterval(checkState, 3000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  const toggleServer = async () => {
    if (isLoading) return;
    setIsLoading(true);
    const action = isRunning ? 'stop' : 'start';
    try {
      const res = await fetch('/api/server', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }),
      });
      const data = await res.json();
      setIsRunning(data.running);
    } catch (e) {
      console.error(e);
    }
    // Set a timeout to allow the server time to fully bind or unbind ports after cmd
    setTimeout(() => setIsLoading(false), 2000);
  };

  return (
    <button
      onClick={toggleServer}
      disabled={isLoading}
      className={`flex items-center gap-2 px-3 py-2 rounded-xl border transition-all duration-300 w-[140px] justify-center group relative overflow-hidden ${
        isLoading ? 'bg-white/5 border-white/5 cursor-wait' :
        isRunning 
          ? 'bg-emerald-500/10 border-emerald-500/25 hover:bg-emerald-500/20 shadow-[0_0_15px_rgba(16,185,129,0.1)]' 
          : 'bg-rose-500/10 border-rose-500/25 hover:bg-rose-500/20'
      }`}
    >
      {isLoading ? (
        <Loader2 className="w-3.5 h-3.5 text-muted-foreground animate-spin shrink-0" />
      ) : (
        <Power className={`w-3.5 h-3.5 shrink-0 transition-transform group-hover:scale-110 ${isRunning ? 'text-emerald-400' : 'text-rose-400'}`} />
      )}
      
      <span className={`text-[10px] font-mono font-bold tracking-widest uppercase flex-1 text-left ${isLoading ? 'text-muted-foreground' : isRunning ? 'text-emerald-400' : 'text-rose-400'}`}>
        {isLoading ? 'WORKING...' : isRunning ? 'SYS ONLINE' : 'SYS OFFLINE'}
      </span>

      {/* Gloss effect overlay */}
      <div className="absolute inset-0 bg-gradient-to-tr from-white/0 via-white/5 to-white/0 opacity-0 group-hover:opacity-100 transition-opacity" />
    </button>
  );
}

function AccountOverview() {
  const [isOpen, setIsOpen] = useState(false);
  const { data: acc, isLoading } = useMT5Account();
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  if (isLoading || !acc) return (
    <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-white/4 border border-white/8 animate-pulse">
      <div className="w-16 h-3 bg-white/10 rounded" />
    </div>
  );

  const isPositive = acc.daily_pnl >= 0;

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2.5 px-3 py-2 rounded-xl bg-white/4 border border-white/8 hover:bg-white/8 transition-all group"
      >
        <Wallet className="w-3.5 h-3.5 text-muted-foreground group-hover:text-primary transition-colors" />
        <div className="flex flex-col items-start leading-none">
          <span className="text-[10px] font-mono font-bold text-white tabular-nums">
            ${acc.equity.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
          <span className={`text-[8px] font-mono font-medium ${isPositive ? 'text-emerald-400' : 'text-rose-400'}`}>
            {isPositive ? '+' : ''}{acc.daily_pnl_pct}%
          </span>
        </div>
        <ChevronDown className={`w-3 h-3 text-muted-foreground transition-transform duration-300 ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: 10, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 10, scale: 0.95 }}
            className="absolute right-0 mt-2 w-72 rounded-2xl bg-slate-950/90 backdrop-blur-2xl border border-white/10 shadow-2xl p-4 z-50 overflow-hidden"
          >
            {/* Background Glow */}
            <div className="absolute top-0 right-0 w-32 h-32 bg-primary/10 rounded-full blur-[60px] -mr-16 -mt-16 pointer-events-none" />
            
            <div className="flex items-center justify-between mb-4 pb-2 border-b border-white/5">
              <span className="text-[10px] font-bold text-white tracking-widest uppercase">Portfolio Snapshot</span>
              <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/20">
                <div className="w-1 h-1 rounded-full bg-emerald-400 animate-pulse" />
                <span className="text-[8px] font-bold text-emerald-400 uppercase">{acc.status}</span>
              </div>
            </div>

            <div className="space-y-4">
              {/* Main Equity Row */}
              <div className="flex items-center justify-between bg-white/5 p-3 rounded-xl border border-white/5">
                <div className="flex flex-col">
                  <span className="text-[9px] text-muted-foreground uppercase font-mono">Total Equity</span>
                  <span className="text-lg font-bold text-white tabular-nums">${acc.equity.toLocaleString()}</span>
                </div>
                <div className={`flex flex-col items-end ${isPositive ? 'text-emerald-400' : 'text-rose-400'}`}>
                   <span className="text-[9px] uppercase font-mono">Daily PnL</span>
                   <div className="flex items-center gap-1">
                     {isPositive ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                     <span className="text-sm font-bold tabular-nums">${Math.abs(acc.daily_pnl).toLocaleString()}</span>
                   </div>
                </div>
              </div>

              {/* Account Details Mesh */}
              <div className="grid grid-cols-2 gap-2">
                <div className="bg-white/3 border border-white/5 p-2 rounded-lg">
                  <div className="flex items-center gap-1.5 mb-1">
                    <CreditCard className="w-3 h-3 text-primary" />
                    <span className="text-[8px] text-muted-foreground uppercase tracking-wider">Buying Power</span>
                  </div>
                  <span className="text-xs font-bold text-white tabular-nums">${acc.buying_power.toLocaleString()}</span>
                </div>
                <div className="bg-white/3 border border-white/5 p-2 rounded-lg">
                  <div className="flex items-center gap-1.5 mb-1">
                    <DollarSign className="w-3 h-3 text-amber-400" />
                    <span className="text-[8px] text-muted-foreground uppercase tracking-wider">Available Cash</span>
                  </div>
                  <span className="text-xs font-bold text-white tabular-nums">${acc.cash.toLocaleString()}</span>
                </div>
              </div>

              {/* Day Trading Details */}
              <div className="pt-2 border-t border-white/5">
                 <div className="flex items-center justify-between text-[9px] text-muted-foreground mb-1 uppercase tracking-tighter">
                   <span>Day Trading Buying Power</span>
                   <span className="text-white font-mono">${acc.daytrading_buying_power.toLocaleString()}</span>
                 </div>
                 <div className="flex items-center justify-between text-[9px] text-muted-foreground uppercase tracking-tighter">
                   <span>Reg-T Buying Power</span>
                   <span className="text-white font-mono">${acc.regt_buying_power.toLocaleString()}</span>
                 </div>
              </div>

              <div className="text-[8px] text-center text-muted-foreground italic pt-1">
                Last updated: {new Date().toLocaleTimeString()} (5m interval)
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function NavBar() {
  const path = usePathname();
  const { data: fleet } = useFleetStatus();

  const fleetData = fleet as FleetStatus | undefined;
  const running = fleetData?.summary?.running_bots ?? 0;
  const total   = fleetData?.summary?.total_bots   ?? 0;

  return (
    <nav className="border-b border-white/8 bg-background/90 backdrop-blur-xl px-6 py-3 flex items-center gap-6 relative z-50">
      {/* Brand */}
      <div className="flex items-center gap-2 mr-4">
        <div className="w-7 h-7 rounded-lg bg-primary/20 flex items-center justify-center">
          <Zap className="w-3.5 h-3.5 text-primary" />
        </div>
        <span className="text-sm font-bold text-white tracking-wider">TRADE<span className="text-primary">CLAW</span></span>
      </div>

      {/* Links */}
      <div className="flex items-center gap-1">
        {links.map(({ href, label, icon }) => {
          const active = path === href;
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-2 px-3 py-2 rounded-xl text-[10px] font-mono font-semibold tracking-widest transition-all ${
                active
                  ? 'bg-primary/20 text-primary border border-primary/30'
                  : 'text-muted-foreground hover:text-white hover:bg-white/5 border border-transparent'
              }`}
            >
              {icon}
              {label}
            </Link>
          );
        })}
      </div>

      <div className="ml-auto flex items-center gap-3">
        {/* Donation Button */}
        <a
          href="https://paypal.me/digitallandscape"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 px-3 py-2 rounded-xl bg-amber-500/10 border border-amber-500/20 hover:bg-amber-500/20 transition-all group mr-2"
          title="Buy Developer a Coffee"
        >
          <Coffee className="w-3.5 h-3.5 text-amber-400 group-hover:scale-110 transition-transform" />
          <span className="text-[10px] font-mono font-bold text-amber-400 tracking-wider hidden sm:inline">COFFEE</span>
        </a>

        {/* Global Backend Power Control */}
        <ServerPowerButton />

        {/* CPU & RAM Monitor */}
        <SystemResourceMonitor />

        {/* MT5 Account Overview */}
        <AccountOverview />

        {/* Fleet live indicator */}
        {total > 0 && (
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-xl bg-white/4 border border-white/8 h-[38px]">
            <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${running > 0 ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500'}`} />
            <span className="text-[9px] font-mono text-muted-foreground uppercase tracking-widest">Fleet</span>
            <span className="text-[10px] font-mono font-semibold text-white tabular-nums">
              {running}/{total}
            </span>
          </div>
        )}
      </div>
    </nav>
  );
}

