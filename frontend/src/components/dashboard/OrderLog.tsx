'use client';

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import moment from "moment";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function OrderLog({ trades }: { trades?: Record<string, any>[] }) {
  return (
    <div className="rounded-md border bg-card/40 overflow-hidden">
      <div className="p-4 border-b bg-muted/30">
        <h3 className="font-semibold text-sm">Execution History</h3>
      </div>
      <div className="h-[280px] overflow-auto">
        <Table>
          <TableHeader className="bg-muted/20 sticky top-0 z-10">
            <TableRow>
              <TableHead className="w-[100px]">Time</TableHead>
              <TableHead>Symbol</TableHead>
              <TableHead>Side</TableHead>
              <TableHead className="text-right">Qty</TableHead>
              <TableHead className="text-right">Price</TableHead>
              <TableHead className="text-right">PnL</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {trades?.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                  No trades recorded today.
                </TableCell>
              </TableRow>
            ) : (
              trades?.map((trade) => (
                <TableRow key={trade.id} className="hover:bg-muted/10 transition-colors">
                  <TableCell className="font-mono text-xs">
                    {moment(trade.timestamp).format('HH:mm:ss')}
                  </TableCell>
                  <TableCell className="font-bold">{trade.symbol}</TableCell>
                  <TableCell>
                    <Badge 
                      className={trade.side === 'BUY' ? 'bg-green-500/10 text-green-400 border border-green-500/20' : 'bg-red-500/10 text-red-400 border border-red-500/20'}
                    >
                      {trade.side}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right font-mono">{trade.qty}</TableCell>
                  <TableCell className="text-right font-mono">
                    ${trade.price.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  </TableCell>
                  <TableCell className={`text-right font-mono font-bold ${trade.pnl > 0 ? 'text-green-400' : trade.pnl < 0 ? 'text-red-400' : ''}`}>
                    {trade.pnl !== 0 ? `${trade.pnl > 0 ? '+' : ''}${trade.pnl.toFixed(2)}` : '—'}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
