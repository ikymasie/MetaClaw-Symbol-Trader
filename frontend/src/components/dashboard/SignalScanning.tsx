'use client';

import { motion } from 'framer-motion';
import { Search, Radar, Shield, Cpu, Activity, Zap } from 'lucide-react';

export function SignalScanning() {
  return (
    <div className="flex flex-col items-center justify-center py-20 px-6 rounded-3xl border border-white/5 bg-card/20 relative overflow-hidden">
      {/* Background Radar Effect */}
      <div className="absolute inset-0 pointer-events-none">
        <motion.div
          initial={{ scale: 0, opacity: 0.5 }}
          animate={{ scale: 2, opacity: 0 }}
          transition={{ duration: 4, repeat: Infinity, ease: "easeOut" }}
          className="absolute inset-0 m-auto w-[500px] h-[500px] rounded-full border border-primary/20"
        />
        <motion.div
          initial={{ scale: 0, opacity: 0.5 }}
          animate={{ scale: 2, opacity: 0 }}
          transition={{ duration: 4, repeat: Infinity, ease: "easeOut", delay: 2 }}
          className="absolute inset-0 m-auto w-[500px] h-[500px] rounded-full border border-sky-500/20"
        />
      </div>

      {/* Central Icon */}
      <div className="relative mb-8">
        <div className="w-24 h-24 rounded-3xl bg-primary/10 border border-primary/20 flex items-center justify-center relative z-10">
          <Radar className="w-10 h-10 text-primary animate-pulse" />
        </div>
        
        {/* Orbiting particles */}
        {[0, 72, 144, 216, 288].map((angle, i) => (
          <motion.div
            key={i}
            animate={{ rotate: 360 }}
            transition={{ duration: 10 + i * 2, repeat: Infinity, ease: "linear" }}
            className="absolute inset-0 pointer-events-none"
          >
            <div 
              style={{ transform: `translateX(70px) rotate(-${angle}deg)` }}
              className="w-1.5 h-1.5 rounded-full bg-primary/40"
            />
          </motion.div>
        ))}
      </div>

      {/* Text Info */}
      <div className="text-center space-y-3 relative z-10 max-w-md">
        <h2 className="text-xl font-bold text-white tracking-tight">Scanning for Alpha Signals</h2>
        <p className="text-sm font-mono text-muted-foreground leading-relaxed">
          The Multi-Agent Engine is active and patrolling the market. Select an operational bot from the fleet to observe its live deliberation pipeline.
        </p>
      </div>

      {/* Scanning Stats Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-12 relative z-10 w-full max-w-2xl">
        <ScanStat icon={<Search className="w-3.5 h-3.5 text-sky-400" />} label="MONITORING" value="482 SYMBOLS" />
        <ScanStat icon={<Cpu className="w-3.5 h-3.5 text-amber-400" />} label="MAS ENGINE" value="PATROLLING" />
        <ScanStat icon={<Shield className="w-3.5 h-3.5 text-emerald-400" />} label="RISK PROTOCOL" value="SHIELDED" />
        <ScanStat icon={<Zap className="w-3.5 h-3.5 text-rose-400" />} label="LATENCY" value="34ms" />
      </div>
    </div>
  );
}

function ScanStat({ icon, label, value }: { icon: React.ReactNode, label: string, value: string }) {
  return (
    <div className="flex flex-col gap-1.5 p-4 rounded-2xl bg-white/[0.03] border border-white/5 backdrop-blur-sm">
      <div className="flex items-center gap-2 opacity-50">
        {icon}
        <span className="text-[9px] font-mono text-zinc-300 uppercase tracking-widest">{label}</span>
      </div>
      <span className="text-[10px] font-mono font-bold text-white">{value}</span>
    </div>
  );
}
