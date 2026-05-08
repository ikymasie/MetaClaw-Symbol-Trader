'use client';

import { useMarketData } from '@/hooks/useFleet';
import { TradingChart } from '@/components/dashboard/TradingChart';
import { Loader2, TrendingUp, TrendingDown, Info } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';

export default function BNBPage() {
  const { data, isLoading, error } = useMarketData('BNB');

  if (isLoading) {
    return (
      <div className="flex h-[calc(100vh-64px)] items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
          <p className="text-sm font-mono text-muted-foreground uppercase tracking-widest">
            Fetching BNB/USD Pulse...
          </p>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex h-[calc(100vh-64px)] items-center justify-center p-6 text-center">
        <div className="max-w-md space-y-4">
          <Info className="w-12 h-12 text-rose-500 mx-auto" />
          <h2 className="text-xl font-bold text-white uppercase tracking-tighter">Market Data Unavailable</h2>
          <p className="text-sm text-zinc-400 font-mono">
            Could not retrieve historical bars for BNB. Ensure your MT5 API keys support Crypto data and check balance.
          </p>
        </div>
      </div>
    );
  }

  const latestPrice = data.price_data[data.price_data.length - 1];
  const prevPrice = data.price_data[data.price_data.length - 2];
  const change = latestPrice.close - prevPrice.close;
  const changePct = (change / prevPrice.close) * 100;

  return (
    <div className="min-h-screen bg-background p-6 space-y-6">
      {/* Header Info */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-full bg-amber-500/20 flex items-center justify-center border border-amber-500/30">
              <span className="text-amber-500 font-bold text-sm">B</span>
            </div>
            <h1 className="text-3xl font-black text-white tracking-tighter uppercase italic">
              BNB / <span className="text-primary">USD</span>
            </h1>
          </div>
          <p className="text-xs font-mono text-muted-foreground tracking-widest opacity-60">
            BINANCE COIN • MT5 MARKET DATA • 1m TIMEFRAME
          </p>
        </div>

        <div className="flex items-center gap-6">
          <div className="text-right">
            <div className="text-[10px] font-mono text-muted-foreground uppercase tracking-wider">Spot Price</div>
            <div className="text-2xl font-black text-white tabular-nums">
              ${latestPrice.close.toLocaleString(undefined, { minimumFractionDigits: 2 })}
            </div>
          </div>
          <div className="text-right">
            <div className="text-[10px] font-mono text-muted-foreground uppercase tracking-wider">24h Change</div>
            <div className={`text-lg font-bold flex items-center justify-end gap-1 ${change >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {change >= 0 ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
              {changePct.toFixed(2)}%
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Main Chart */}
        <div className="lg:col-span-3 h-[600px]">
          <TradingChart 
            priceData={data.price_data} 
            bollingerData={data.bollinger} 
            markers={[]} 
          />
        </div>

        {/* Sidebar Status */}
        <div className="space-y-4">
          <Card className="bg-card/40 border-primary/10">
            <CardContent className="p-4 space-y-4">
              <h3 className="text-xs font-bold text-white uppercase tracking-widest border-b border-white/5 pb-2">Technical Pulse</h3>
              
              <div className="space-y-4">
                <div className="flex justify-between items-center text-[11px] font-mono">
                  <span className="text-muted-foreground uppercase">Volatility (BB Width)</span>
                  <span className="text-white">
                    {((data.bollinger[data.bollinger.length - 1].upper - data.bollinger[data.bollinger.length - 1].lower) / data.bollinger[data.bollinger.length - 1].middle * 100).toFixed(2)}%
                  </span>
                </div>
                <div className="flex justify-between items-center text-[11px] font-mono">
                  <span className="text-muted-foreground uppercase">Trend Bias</span>
                  <span className={latestPrice.close > data.bollinger[data.bollinger.length - 1].middle ? 'text-emerald-400' : 'text-rose-400'}>
                    {latestPrice.close > data.bollinger[data.bollinger.length - 1].middle ? 'BULLISH' : 'BEARISH'}
                  </span>
                </div>
              </div>
            </CardContent>
          </Card>

          <div className="p-4 rounded-xl border border-white/5 bg-white/2 text-[10px] font-mono text-zinc-500 leading-relaxed">
            <p className="uppercase font-bold mb-2 text-zinc-400 opacity-80">Execution Note</p>
            You can deploy a specialized mean-reversion bot for BNB directly from the <span className="text-primary hover:underline cursor-pointer">Fleet Command</span>. Current chart uses MT5's historical minute bars.
          </div>
        </div>
      </div>
    </div>
  );
}
