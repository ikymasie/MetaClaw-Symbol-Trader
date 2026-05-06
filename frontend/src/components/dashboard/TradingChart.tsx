'use client';

import { useEffect, useRef } from 'react';
import { createChart, ColorType, CandlestickSeries, LineSeries, createSeriesMarkers, IChartApi, ISeriesApi, CandlestickData, LineData } from 'lightweight-charts';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface TradingChartProps {
  priceData: any[];
  bollingerData: any[];
  markers: any[];
}

export function TradingChart({ priceData, bollingerData, markers }: TradingChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candlestickSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const upperBBSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const middleBBSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const lowerBBSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const markersRef = useRef<any>(null);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#a1a1aa',
      },
      grid: {
        vertLines: { color: '#27272a' },
        horzLines: { color: '#27272a' },
      },
      width: chartContainerRef.current.clientWidth,
      height: 400,
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
      },
    });

    const candlestickSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderVisible: false,
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    });

    const upperBBSeries = chart.addSeries(LineSeries, {
      color: 'rgba(59, 130, 246, 0.5)',
      lineWidth: 1,
      lineStyle: 2, // Dashed
    });

    const middleBBSeries = chart.addSeries(LineSeries, {
      color: 'rgba(59, 130, 246, 0.3)',
      lineWidth: 1,
    });

    const lowerBBSeries = chart.addSeries(LineSeries, {
      color: 'rgba(59, 130, 246, 0.5)',
      lineWidth: 1,
      lineStyle: 2, // Dashed
    });

    chartRef.current = chart;
    candlestickSeriesRef.current = candlestickSeries;
    upperBBSeriesRef.current = upperBBSeries;
    middleBBSeriesRef.current = middleBBSeries;
    lowerBBSeriesRef.current = lowerBBSeries;

    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, []);

  useEffect(() => {
    if (!candlestickSeriesRef.current || !priceData.length) return;

    // Format data for lightweight-charts
    const formattedPriceData = priceData.map(d => ({
      time: Math.floor(new Date(d.time).getTime() / 1000),
      open: d.open,
      high: d.high,
      low: d.low,
      close: d.close,
    })).sort((a, b) => a.time - b.time);

    // Filter duplicates
    const uniquePriceData = formattedPriceData.filter((val, idx, self) => 
      idx === self.findIndex((t) => t.time === val.time)
    );

    candlestickSeriesRef.current.setData(uniquePriceData as CandlestickData[]);

    if (bollingerData.length) {
      const upperData = bollingerData.map(d => ({
        time: Math.floor(new Date(d.time).getTime() / 1000),
        value: d.upper,
      })).filter((val, idx, self) => idx === self.findIndex((t) => t.time === val.time));

      const middleData = bollingerData.map(d => ({
        time: Math.floor(new Date(d.time).getTime() / 1000),
        value: d.middle,
      })).filter((val, idx, self) => idx === self.findIndex((t) => t.time === val.time));

      const lowerData = bollingerData.map(d => ({
        time: Math.floor(new Date(d.time).getTime() / 1000),
        value: d.lower,
      })).filter((val, idx, self) => idx === self.findIndex((t) => t.time === val.time));

      upperBBSeriesRef.current?.setData(upperData as LineData[]);
      middleBBSeriesRef.current?.setData(middleData as LineData[]);
      lowerBBSeriesRef.current?.setData(lowerData as LineData[]);
    }

    if (markers.length && candlestickSeriesRef.current) {
      // Remove previous markers series if any
      if (markersRef.current) {
        try { markersRef.current.detach(); } catch (_) {}
        markersRef.current = null;
      }
      const formattedMarkers = markers.map(m => ({
        time: Math.floor(new Date(m.time).getTime() / 1000) as unknown as import('lightweight-charts').Time,
        position: m.position as 'aboveBar' | 'belowBar' | 'inBar',
        color: m.color as string,
        shape:  m.shape  as 'circle' | 'square' | 'arrowUp' | 'arrowDown',
        text:   m.text   as string | undefined,
      })).filter(m => uniquePriceData.some(p => p.time === (m.time as unknown as number)));

      markersRef.current = createSeriesMarkers(candlestickSeriesRef.current, formattedMarkers);
    }

    // Fit content on initial load or data significant change
    if (uniquePriceData.length > 0) {
        chartRef.current?.timeScale().fitContent();
    }

  }, [priceData, bollingerData, markers]);

  return (
    <Card className="bg-card/40 border-primary/10 overflow-hidden h-full">
      <CardHeader className="py-3 px-4 flex flex-row items-center justify-between border-b bg-muted/10">
        <CardTitle className="text-sm font-medium">Live Terminal</CardTitle>
        <div className="flex items-center gap-2">
           <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
           <span className="text-[10px] text-muted-foreground font-mono">1s TICK</span>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div ref={chartContainerRef} className="w-full" />
      </CardContent>
    </Card>
  );
}
