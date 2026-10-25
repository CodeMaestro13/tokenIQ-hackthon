'use client';
import { useEffect, useRef } from 'react';
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
  createSeriesMarkers,
  ColorType,
  type UTCTimestamp,
} from 'lightweight-charts';
import type { Snapshot } from '@/lib/types';
import { ema } from '@/lib/indicators';
export default function MarketChart({ data }: { data: Snapshot }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof createChart> | null>(null);
  const series = useRef<any>(null); // Chart series API types vary by series definition.
  const fast = useRef<any>(null),
    slow = useRef<any>(null),
    volume = useRef<any>(null),
    markers = useRef<any>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, {
      autoSize: true,
      height: 350,
      layout: {
        background: { type: ColorType.Solid, color: '#101b2c' },
        textColor: '#7e91aa',
        fontFamily: 'monospace',
        attributionLogo: true,
      },
      grid: { vertLines: { color: '#1a293c' }, horzLines: { color: '#1a293c' } },
      rightPriceScale: { borderColor: '#263449' },
      timeScale: { borderColor: '#263449', timeVisible: true },
      crosshair: { vertLine: { color: '#58718e' }, horzLine: { color: '#58718e' } },
    });
    chartRef.current = chart;
    series.current = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981',
      downColor: '#ef6375',
      borderVisible: false,
      wickUpColor: '#10b981',
      wickDownColor: '#ef6375',
    });
    fast.current = chart.addSeries(LineSeries, {
      color: '#38bdf8',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    slow.current = chart.addSeries(LineSeries, {
      color: '#a78bfa',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    volume.current = chart.addSeries(HistogramSeries, {
      priceScaleId: 'volume',
      priceFormat: { type: 'volume' },
    });
    chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.86, bottom: 0 } });
    markers.current = createSeriesMarkers(series.current, []);
    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, []);
  useEffect(() => {
    if (!chartRef.current || !series.current) return;
    series.current.setData(data.candles.map((c) => ({ ...c, time: c.time as UTCTimestamp })));
    fast.current.setData(ema(data.candles, data.config.fast_period));
    slow.current.setData(ema(data.candles, data.config.slow_period));
    volume.current.setData(
      data.candles.map((c) => ({
        time: c.time,
        value: c.volume || 0,
        color: c.close >= c.open ? '#10b98130' : '#ef637530',
      })),
    );
    const start = data.candles[0]?.time || 0,
      end = data.candles.at(-1)?.time || 0;
    markers.current.setMarkers(
      data.decisions
        .filter((d) => d.candle_time >= start && d.candle_time <= end)
        .sort((a, b) => a.candle_time - b.candle_time)
        .map((d) => ({
          time: d.candle_time,
          position: d.side === 'BUY' ? 'belowBar' : 'aboveBar',
          color: d.side === 'BUY' ? '#10b981' : '#ef6375',
          shape: d.side === 'BUY' ? 'arrowUp' : 'arrowDown',
          text: d.side,
        })),
    );
    const lines = data.positions
      .flatMap((p) => [
        { price: p.entry_price, color: '#38bdf8', title: 'Entry' },
        { price: p.stop_loss, color: '#ef6375', title: 'Stop loss' },
        { price: p.take_profit, color: '#10b981', title: 'Take profit' },
      ])
      .map((l) =>
        series.current.createPriceLine({
          ...l,
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: true,
        }),
      );
    return () => lines.forEach((l) => series.current?.removePriceLine(l));
  }, [data]);
  return (
    <div ref={ref} className="market-chart" aria-label="Candlestick chart with EMA overlays" />
  );
}
