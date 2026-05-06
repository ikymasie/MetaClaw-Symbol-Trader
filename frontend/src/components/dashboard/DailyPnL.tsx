'use client';

import { 
  Bar, 
  BarChart, 
  ResponsiveContainer, 
  Tooltip, 
  XAxis, 
  YAxis,
  CartesianGrid,
  Cell
} from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import moment from "moment";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function DailyPnL({ trades }: { trades?: Record<string, any>[] }) {
  const chartData = trades?.filter(t => t.side === 'SELL').map(t => ({
    time: moment(t.timestamp).format('HH:mm'),
    pnl: t.pnl
  })).reverse() || [];

  return (
    <Card className="bg-card/40 border-primary/10 h-full">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">Realized P&L per Trade</CardTitle>
      </CardHeader>
      <CardContent className="h-[200px] p-0 overflow-hidden">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#27272a" />
            <XAxis 
              dataKey="time" 
              fontSize={10} 
              tickLine={false} 
              axisLine={false}
            />
            <YAxis 
              fontSize={10} 
              tickLine={false} 
              axisLine={false} 
              tickFormatter={(val) => `$${val}`}
            />
            <Tooltip 
              contentStyle={{ backgroundColor: '#18181b', border: '1px solid #27272a', fontSize: '12px' }}
              cursor={{ fill: 'rgba(255, 255, 255, 0.05)' }}
              formatter={(val) => [`$${Number(val).toFixed(2)}`, 'PnL']}

            />
            <Bar dataKey="pnl" radius={[4, 4, 0, 0]}>
              {chartData.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={entry.pnl >= 0 ? '#10b981' : '#f43f5e'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
