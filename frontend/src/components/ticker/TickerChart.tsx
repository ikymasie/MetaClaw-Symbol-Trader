'use client';

import { useEffect, useRef, useCallback } from 'react';
import {
  createChart,
  ColorType,
  CandlestickSeries,
  LineSeries,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
} from 'lightweight-charts';
import type { MT5Bar, TickerBotContext } from '@/hooks/useMT5Ticker';

interface TickerChartProps {
  bars: MT5Bar[];
  bots: TickerBotContext[];
  className?: string;
}

function isoToUtcTimestamp(iso: string): number {
  return Math.floor(new Date(iso).getTime() / 1000) as number;
}

export function TickerChart({ bars, bots, className }: TickerChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const upperBBRef = useRef<ISeriesApi<'Line'> | null>(null);
  const midBBRef = useRef<ISeriesApi<'Line'> | null>(null);
  const lowerBBRef = useRef<ISeriesApi<'Line'> | null>(null);

  // --- Chart initialization (runs once) ---
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#a1a1aa',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.04)' },
        horzLines: { color: 'rgba(255,255,255,0.04)' },
      },
      crosshair: {
        vertLine: { color: 'rgba(255,255,255,0.12)' },
        horzLine: { color: 'rgba(255,255,255,0.12)' },
      },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.08)' },
      timeScale: {
        borderColor: 'rgba(255,255,255,0.08)',
        timeVisible: true,
        secondsVisible: false,
      },
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
    });

    const candle = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderVisible: false,
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    });

    const upper = chart.addSeries(LineSeries, {
      color: 'rgba(99,102,241,0.55)',
      lineWidth: 1,
      lineStyle: 2,
      title: 'BB Upper',
    });
    const mid = chart.addSeries(LineSeries, {
      color: 'rgba(99,102,241,0.30)',
      lineWidth: 1,
      title: 'BB Mid',
    });
    const lower = chart.addSeries(LineSeries, {
      color: 'rgba(99,102,241,0.55)',
      lineWidth: 1,
      lineStyle: 2,
      title: 'BB Lower',
    });

    chartRef.current = chart;
    candleRef.current = candle;
    upperBBRef.current = upper;
    midBBRef.current = mid;
    lowerBBRef.current = lower;

    const ro = new ResizeObserver(() => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        });
      }
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
    };
  }, []);

  // --- Bar data updates ---
  useEffect(() => {
    if (!candleRef.current || bars.length === 0) return;

    const sorted = [...bars]
      .map((b) => ({
        time: isoToUtcTimestamp(b.time) as any,
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      }))
      .sort((a, b) => a.time - b.time);

    // Deduplicate by time
    const dedupe = sorted.filter(
      (v, i, arr) => i === 0 || v.time !== arr[i - 1].time
    );

    candleRef.current.setData(dedupe);
    // Keep chart scrolled to current bar
    chartRef.current?.timeScale().scrollToRealTime();
  }, [bars]);

  // --- Bollinger overlay from last bot ---
  useEffect(() => {
    if (!upperBBRef.current) return;

    // Gather all bollinger_last points from every bot
    const bbPoints: Array<{ time: number; upper: number; middle: number; lower: number }> = [];
    for (const bot of bots) {
      const bb = bot.bollinger_last;
      if (bb?.upper && bb?.middle && bb?.lower && bb?.time) {
        bbPoints.push({
          time: isoToUtcTimestamp(bb.time),
          upper: bb.upper,
          middle: bb.middle,
          lower: bb.lower,
        });
      }
    }

    if (bbPoints.length > 0) {
      bbPoints.sort((a, b) => a.time - b.time);
      upperBBRef.current?.setData(bbPoints.map((p) => ({ time: p.time as any, value: p.upper })));
      midBBRef.current?.setData(bbPoints.map((p) => ({ time: p.time as any, value: p.middle })));
      lowerBBRef.current?.setData(bbPoints.map((p) => ({ time: p.time as any, value: p.lower })));
    }
  }, [bots]);

  // --- Trade markers overlay ---
  useEffect(() => {
    if (!candleRef.current) return;

    const allMarkers: any[] = [];
    for (const bot of bots) {
      for (const m of bot.markers ?? []) {
        allMarkers.push({
          time: isoToUtcTimestamp(m.time) as any,
          position: m.position ?? 'belowBar',
          color: m.color ?? '#f59e0b',
          shape: m.shape ?? 'circle',
          text: m.text ?? '',
        });
      }
    }

    if (allMarkers.length > 0) {
      allMarkers.sort((a, b) => a.time - b.time);
      createSeriesMarkers(candleRef.current, allMarkers);
    }
  }, [bots]);

  return (
    <div
      ref={containerRef}
      className={className ?? 'w-full h-full'}
      style={{ minHeight: 0 }}
    />
  );
}
