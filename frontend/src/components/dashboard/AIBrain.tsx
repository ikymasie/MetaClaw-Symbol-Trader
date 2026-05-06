import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useAIStatus, useAIDecisions, useTriggerAI } from '@/hooks/useTrading';
import { Button } from '@/components/ui/button';
import { BrainCircuit, Loader2, Play, AlertCircle } from 'lucide-react';

export function AIBrain() {
  const { data: status, isLoading: statusLoading } = useAIStatus();
  const { data: decisions, isLoading: decisionsLoading } = useAIDecisions();
  const triggerAI = useTriggerAI();

  if (statusLoading || decisionsLoading) {
    return (
      <Card className="h-full flex items-center justify-center bg-slate-900 border-slate-800">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
      </Card>
    );
  }

  const isEnabled = status?.enabled;
  const state = status?.state;

  return (
    <Card className="h-full flex flex-col bg-slate-900 border-slate-800 text-slate-100 overflow-hidden">
      <CardHeader className="flex flex-row items-center justify-between pb-2 border-b border-slate-800 bg-slate-900/50">
        <div className="space-y-1">
          <CardTitle className="flex items-center gap-2 text-primary font-mono text-sm uppercase tracking-wider">
            <BrainCircuit className="h-4 w-4" />
            AI Operations
          </CardTitle>
          <CardDescription className="text-slate-400 text-xs">
            {isEnabled ? 'Autonomous Optimization Active' : 'AI Offline'}
          </CardDescription>
        </div>
        <Button 
          size="sm" 
          variant={state === 'analysing' ? 'secondary' : 'default'}
          className="h-8 gap-2 bg-primary/20 hover:bg-primary/30 text-primary border border-primary/20"
          onClick={() => triggerAI.mutate()}
          disabled={!isEnabled || state === 'analysing' || triggerAI.isPending}
        >
          {state === 'analysing' || triggerAI.isPending ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Play className="h-3 w-3" />
          )}
          {state === 'analysing' ? 'Optimizing...' : 'Force'}
        </Button>
      </CardHeader>
      
      <CardContent className="flex-1 overflow-y-auto p-4 space-y-4">
        {!decisions?.decisions || decisions.decisions.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 text-slate-500 gap-2">
            <AlertCircle className="h-6 w-6" />
            <p className="text-sm">No AI decisions recorded.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {decisions.decisions.map((d: any, i: number) => (
              <div key={i} className="p-3 rounded-lg border border-slate-800 bg-slate-950/50 space-y-2">
                <div className="flex justify-between items-start">
                  <div className="text-xs font-mono text-slate-400">
                    {new Date(d.timestamp).toLocaleString()}
                  </div>
                  <div className={`text-[10px] uppercase px-1.5 py-0.5 rounded font-mono ${
                    d.applied ? 'bg-green-500/10 text-green-400 border border-green-500/20' : 'bg-slate-800 text-slate-400 border border-slate-700'
                  }`}>
                    {d.applied ? 'Applied' : 'Rejected'}
                  </div>
                </div>
                
                <div className="text-xs text-slate-300">
                  <span className="font-semibold text-slate-500">Trigger:</span> {d.trigger}
                </div>
                
                <div className="flex justify-between text-xs border-b border-slate-800/50 pb-1">
                  <div><span className="font-semibold text-slate-500">WR:</span> {d.win_rate_before?.toFixed(1)}%</div>
                  <div><span className="font-semibold text-slate-500">PnL:</span> ${d.daily_pnl_before?.toFixed(2)}</div>
                </div>

                <div className="text-xs text-slate-300 italic pt-1">
                  {d.reasoning}
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
