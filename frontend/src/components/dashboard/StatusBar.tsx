'use client';

import { Badge } from "@/components/ui/badge";
import { Activity, Circle, Clock, Wifi, WifiOff } from "lucide-react";
import moment from "moment";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { StreamingToggle } from "@/components/StreamingToggle";

export function StatusBar({ status, message, symbol, demoMode }: {
  status: string;
  message: string;
  symbol: string;
  demoMode: boolean;
}) {
  const queryClient = useQueryClient();
  const [wsAlive, setWsAlive] = useState(false);

  // Derive WS liveness from how fresh the last pushed timestamp is
  useEffect(() => {
    const check = () => {
      const cached: any = queryClient.getQueryData(['trading-status']);
      if (cached?.timestamp) {
        const ageMs = Date.now() - new Date(cached.timestamp).getTime();
        setWsAlive(ageMs < 3000); // alive if updated within last 3s
      } else {
        setWsAlive(false);
      }
    };
    check();
    const id = setInterval(check, 1000);
    return () => clearInterval(id);
  }, [queryClient]);

  const getStatusColor = (s: string) => {
    switch (s) {
      case 'RUNNING':       return 'bg-green-500';
      case 'CRITICAL_STOP': return 'bg-red-500 animate-pulse';
      case 'ORGAN_FAILURE': return 'bg-orange-500 animate-pulse';
      case 'IDLE':          return 'bg-yellow-500';
      default:              return 'bg-zinc-500';
    }
  };

  return (
    <div className="flex items-center justify-between px-6 py-2 border-b bg-card/50 backdrop-blur-sm sticky top-0 z-50">
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-primary" />
          <span className="font-bold text-lg tracking-tight">TradeClaw</span>
        </div>
        <div className="h-4 w-px bg-border mx-2" />
        <div className="flex items-center gap-2">
          <Circle className={`w-2 h-2 fill-current ${getStatusColor(status)}`} />
          <span className="text-sm font-medium">{status}</span>
        </div>
        {symbol && (
          <Badge variant="outline" className="font-mono">{symbol}</Badge>
        )}
        {demoMode && (
          <Badge variant="secondary" className="bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 border-blue-500/20">
            DEMO MODE
          </Badge>
        )}
      </div>

      <div className="flex items-center gap-6">
        <div className="text-sm text-muted-foreground italic truncate max-w-[400px]">
          {message || "System standby"}
        </div>

        {/* WebSocket live-feed indicator */}
        <div className={`flex items-center gap-1.5 text-xs font-mono ${wsAlive ? 'text-emerald-400' : 'text-amber-400'}`}>
          {wsAlive
            ? <><Wifi className="w-3 h-3" /><span className="animate-pulse">LIVE</span></>
            : <><WifiOff className="w-3 h-3" /><span>RECONNECTING</span></>
          }
        </div>

        {/* Global streaming play/pause toggle */}
        <StreamingToggle />

        <div className="flex items-center gap-2 text-xs text-muted-foreground font-mono">
          <Clock className="w-3 h-3" />
          {moment().format('HH:mm:ss')}
        </div>
      </div>
    </div>
  );
}

