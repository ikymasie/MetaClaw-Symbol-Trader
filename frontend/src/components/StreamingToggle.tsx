'use client';

import { useStreaming } from '@/contexts/StreamingContext';
import { Pause, Play, Loader2 } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

/**
 * StreamingToggle — a compact play/pause button for the StatusBar that
 * controls **all** WebSocket data streams globally.
 */
export function StreamingToggle() {
  const { isStreaming, toggle, isTransitioning, stats } = useStreaming();

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={toggle}
        disabled={isTransitioning}
        className={`
          relative flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-mono font-bold
          transition-all duration-300 cursor-pointer
          ${isStreaming
            ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/20'
            : 'bg-amber-500/10 border-amber-500/30 text-amber-400 hover:bg-amber-500/20'
          }
          disabled:opacity-50 disabled:cursor-not-allowed
        `}
        title={isStreaming ? 'Pause all data streams' : 'Resume all data streams'}
      >
        <AnimatePresence mode="wait">
          {isTransitioning ? (
            <motion.span
              key="loading"
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.8 }}
              transition={{ duration: 0.15 }}
            >
              <Loader2 className="w-3 h-3 animate-spin" />
            </motion.span>
          ) : isStreaming ? (
            <motion.span
              key="pause"
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.8 }}
              transition={{ duration: 0.15 }}
            >
              <Pause className="w-3 h-3" />
            </motion.span>
          ) : (
            <motion.span
              key="play"
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.8 }}
              transition={{ duration: 0.15 }}
            >
              <Play className="w-3 h-3" />
            </motion.span>
          )}
        </AnimatePresence>
        <span>{isStreaming ? 'STREAMING' : 'PAUSED'}</span>
      </button>

      {/* Stats tooltip area */}
      {stats.ticker && (
        <span className="text-[10px] font-mono text-zinc-500 hidden lg:inline">
          {stats.ticker.messages_received.toLocaleString()} msgs
          {stats.ticker.messages_dropped > 0 && (
            <span className="text-amber-500 ml-1">
              ({stats.ticker.messages_dropped} dropped)
            </span>
          )}
        </span>
      )}
    </div>
  );
}
