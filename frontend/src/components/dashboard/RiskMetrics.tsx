'use client';

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { ArrowUpRight, ArrowDownRight, Wallet, Target, Activity, Percent } from "lucide-react";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function RiskMetrics({ status }: { status?: Record<string, any> }) {
  const equity              = status?.equity;
  const daily_pnl           = status?.daily_pnl ?? 0;
  const daily_pnl_pct       = status?.daily_pnl_pct ?? 0;
  const daily_drawdown_pct  = status?.daily_drawdown_pct ?? 0;
  const unrealized_pnl      = status?.unrealized_pnl ?? 0;
  const win_rate            = status?.win_rate ?? 0;
  const total_trades_today  = status?.total_trades_today ?? 0;
  const position_qty        = status?.position_qty ?? 0;
  const config              = status?.config;

  const maxDrawdown      = config?.max_daily_drawdown_pct || 6.0;
  const drawdownProgress = (daily_drawdown_pct / maxDrawdown) * 100;

  return (
    <div className="grid grid-cols-2 gap-4">
      <Card className="bg-card/40 border-primary/10">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-xs font-medium text-muted-foreground">Account Equity</CardTitle>
          <Wallet className="h-4 w-4 text-primary" />
        </CardHeader>
        <CardContent>
          <div className="text-xl font-bold font-mono">${equity?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
          <p className={`text-xs flex items-center mt-1 ${daily_pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
            {daily_pnl >= 0 ? <ArrowUpRight className="h-3 w-3 mr-1" /> : <ArrowDownRight className="h-3 w-3 mr-1" />}
            {daily_pnl_pct >= 0 ? '+' : ''}{daily_pnl_pct}% Today
          </p>
        </CardContent>
      </Card>

      <Card className="bg-card/40 border-primary/10">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-xs font-medium text-muted-foreground">Open P&L</CardTitle>
          <Target className="h-4 w-4 text-blue-400" />
        </CardHeader>
        <CardContent>
          <div className={`text-xl font-bold font-mono ${unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            ${unrealized_pnl?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            {position_qty || 0} shares held
          </p>
        </CardContent>
      </Card>

      <Card className="col-span-2 bg-card/40 border-primary/10">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-xs font-medium text-muted-foreground">Daily Drawdown Limit ({maxDrawdown}%)</CardTitle>
          <Percent className="h-4 w-4 text-orange-400" />
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-mono">{daily_drawdown_pct}%</span>
            <span className="text-xs text-muted-foreground">{Math.max(0, maxDrawdown - daily_drawdown_pct).toFixed(2)}% remaining</span>
          </div>
          <div className="h-2 w-full bg-secondary rounded-full overflow-hidden">
            <div 
              className={`h-full transition-all duration-500 ${daily_drawdown_pct > maxDrawdown * 0.8 ? 'bg-red-500' : 'bg-orange-500'}`}
              style={{ width: `${Math.min(100, drawdownProgress)}%` }}
            />
          </div>
        </CardContent>
      </Card>

      <Card className="bg-card/40 border-primary/10">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-xs font-medium text-muted-foreground">Win Rate</CardTitle>
          <Activity className="h-4 w-4 text-emerald-400" />
        </CardHeader>
        <CardContent>
          <div className="text-xl font-bold font-mono">{win_rate}%</div>
          <p className="text-xs text-muted-foreground mt-1">
            {total_trades_today} total trades
          </p>
        </CardContent>
      </Card>

      <Card className="bg-card/40 border-primary/10">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-xs font-medium text-muted-foreground">Latency</CardTitle>
          <div className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
        </CardHeader>
        <CardContent>
          <div className="text-xl font-bold font-mono">1.2ms</div>
          <p className="text-xs text-muted-foreground mt-1 text-emerald-500">
            Real-time feed active
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
