'use client';

import { 
  Area, 
  AreaChart, 
  ResponsiveContainer, 
  Tooltip, 
  XAxis, 
  YAxis,
  CartesianGrid
} from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import moment from "moment";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function EquityCurve({ data }: { data?: Record<string, any>[] }) {

  const chartData = data?.map(d => ({
    time: moment(d.time).format('HH:mm:ss'),
    equity: d.equity
  })) || [];

  return (
    <Card className="bg-card/40 border-primary/10 h-full">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">Equity Curve</CardTitle>
      </CardHeader>
      <CardContent className="h-[200px] p-0 overflow-hidden">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData}>
            <defs>
              <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3}/>
                <stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/>
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#27272a" />
            <XAxis 
              dataKey="time" 
              fontSize={10} 
              tickLine={false} 
              axisLine={false}
              interval="preserveStartEnd"
              minTickGap={30}
            />
            <YAxis 
              fontSize={10} 
              tickLine={false} 
              axisLine={false} 
              domain={['auto', 'auto']}
              tickFormatter={(val) => `$${(val / 1000).toFixed(1)}k`}
            />
            <Tooltip 
              contentStyle={{ backgroundColor: '#18181b', border: '1px solid #27272a', fontSize: '12px' }}
              itemStyle={{ color: '#3b82f6' }}
              formatter={(val) => [`$${Number(val).toLocaleString()}`, 'Equity']}

            />
            <Area 
              type="monotone" 
              dataKey="equity" 
              stroke="#3b82f6" 
              fillOpacity={1} 
              fill="url(#equityGradient)" 
              strokeWidth={2}
            />
          </AreaChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
