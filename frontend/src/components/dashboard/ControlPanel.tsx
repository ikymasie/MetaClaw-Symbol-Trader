'use client';

import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Play, Square, Settings, RefreshCcw } from "lucide-react";
import { useStartBot, useStopBot, useUpdateConfig } from "@/hooks/useTrading";

interface ControlPanelProps {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  config?: Record<string, any>;
  status?: string;
}

export function ControlPanel({ config, status }: ControlPanelProps) {

  const [stopLoss, setStopLoss] = useState(config?.stop_loss_pct || 1.0);
  const [bbPeriod, setBbPeriod] = useState(config?.bb_period || 20);
  const [demoMode, setDemoMode] = useState(config?.demo_mode ?? true);
  const [symbol, setSymbol] = useState(config?.symbol || "SPY");

  const startMutation = useStartBot();
  const stopMutation = useStopBot();
  const configMutation = useUpdateConfig();

  const isRunning = status === 'RUNNING' || status === 'STARTING';
  const isCritical = status === 'CRITICAL_STOP';

  useEffect(() => {
    if (config) {
      setStopLoss(config.stop_loss_pct);
      setBbPeriod(config.bb_period);
      setDemoMode(config.demo_mode);
      setSymbol(config.symbol);
    }
  }, [config]);

  const handleUpdateConfig = () => {
    configMutation.mutate({
      stop_loss_pct: stopLoss,
      bb_period: bbPeriod,
      symbol: symbol
    });
  };

  return (
    <Card className="bg-card/40 border-primary/10">
      <CardHeader className="pb-3 flex flex-row items-center justify-between">
        <CardTitle className="text-sm font-medium">Strategy Control</CardTitle>
        <Settings className="w-4 h-4 text-muted-foreground" />
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="flex gap-4">
          {!isRunning ? (
            <Button 
              className="flex-1 bg-green-600 hover:bg-green-700 text-white font-bold"
              onClick={() => startMutation.mutate(demoMode)}
              disabled={startMutation.isPending}
            >
              <Play className="w-4 h-4 mr-2 fill-current" />
              {isCritical ? "RESET & START" : "START ENGINE"}
            </Button>
          ) : (
            <Button 
              variant="destructive" 
              className="flex-1 font-bold animate-pulse hover:animate-none"
              onClick={() => stopMutation.mutate()}
              disabled={stopMutation.isPending}
            >
              <Square className="w-4 h-4 mr-2 fill-current" />
              PANIC STOP
            </Button>
          )}
        </div>

        <div className="flex items-center justify-between space-x-2 py-2 border-y border-border/50">
          <div className="space-y-0.5">
            <Label htmlFor="demo-mode">Demo Trading</Label>
            <p className="text-[10px] text-muted-foreground">
              Use simulated price feed and execution
            </p>
          </div>
          <Switch 
            id="demo-mode" 
            checked={demoMode} 
            onCheckedChange={setDemoMode}
            disabled={isRunning}
          />
        </div>

        <div className="space-y-4 pt-2">
          <div className="space-y-2">
            <div className="flex justify-between">
              <Label className="text-xs">Symbol</Label>
              <span className="text-[10px] font-mono text-primary uppercase">{symbol}</span>
            </div>
            <Input 
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              disabled={isRunning}
              className="h-8 text-xs font-mono"
            />
          </div>

          <div className="space-y-2">
            <div className="flex justify-between">
              <Label className="text-xs">Stop Loss %</Label>
              <span className="text-[10px] font-mono text-primary">{stopLoss}%</span>
            </div>
            <Slider 
              value={[stopLoss]} 
              min={0.1} 
              max={5.0} 
              step={0.1} 
              onValueChange={(val) => {
                const v = Array.isArray(val) ? val[0] : val;
                setStopLoss(typeof v === 'number' ? v : v);
              }}

            />
          </div>

          <div className="space-y-2">
            <div className="flex justify-between">
              <Label className="text-xs">BB Period</Label>
              <span className="text-[10px] font-mono text-primary">{bbPeriod}</span>
            </div>
            <Input 
              type="number"
              value={bbPeriod}
              onChange={(e) => setBbPeriod(parseInt(e.target.value))}
              className="h-8 text-xs"
            />
          </div>

          <Button 
            variant="outline" 
            size="sm" 
            className="w-full text-xs h-8"
            onClick={handleUpdateConfig}
            disabled={configMutation.isPending}
          >
            <RefreshCcw className={`w-3 h-3 mr-2 ${configMutation.isPending ? 'animate-spin' : ''}`} />
            Apply Settings
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
