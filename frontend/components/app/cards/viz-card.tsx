'use client';

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { ChartSpec } from './card-types';

// Accessible, distinct series colors (work on dark; not red/green-only).
const PALETTE = ['var(--viz)', 'var(--context)', 'var(--decision)', 'var(--transcription)'];

const AXIS = 'var(--muted-foreground)';
const GRID = 'var(--border)';

function seriesColor(index: number, explicit?: string): string {
  return explicit || PALETTE[index % PALETTE.length];
}

/** Renders a chart spec (line / area / bar) with legend + tooltip. Includes a
 *  visually-hidden data table for screen readers (charts alone aren't a11y-friendly). */
export function VizChart({ spec }: { spec: ChartSpec }) {
  const { chart, xKey, series, data, unit } = spec;

  const tooltip = (
    <Tooltip
      contentStyle={{
        background: 'var(--popover)',
        border: '1px solid var(--border)',
        borderRadius: 8,
        fontSize: 12,
      }}
      labelStyle={{ color: 'var(--foreground)' }}
      itemStyle={{ color: 'var(--foreground)' }}
      cursor={{ fill: 'var(--muted)', opacity: 0.3 }}
    />
  );
  const grid = <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />;
  const xAxis = <XAxis dataKey={xKey} stroke={AXIS} tick={{ fontSize: 11 }} tickLine={false} />;
  const yAxis = (
    <YAxis
      stroke={AXIS}
      tick={{ fontSize: 11 }}
      tickLine={false}
      width={36}
      tickFormatter={(v) => (unit ? `${v}` : `${v}`)}
    />
  );
  const legend = <Legend wrapperStyle={{ fontSize: 11 }} iconType="plainline" />;

  return (
    <>
      <div className="h-44 w-full min-w-0">
        <ResponsiveContainer width="100%" height="100%" debounce={1}>
          {chart === 'line' ? (
            <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
              {grid}
              {xAxis}
              {yAxis}
              {tooltip}
              {legend}
              {series.map((s, i) => (
                <Line
                  key={s.key}
                  type="monotone"
                  dataKey={s.key}
                  name={s.label ?? s.key}
                  stroke={seriesColor(i, s.color)}
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          ) : chart === 'area' ? (
            <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
              {grid}
              {xAxis}
              {yAxis}
              {tooltip}
              {legend}
              {series.map((s, i) => (
                <Area
                  key={s.key}
                  type="monotone"
                  dataKey={s.key}
                  name={s.label ?? s.key}
                  stroke={seriesColor(i, s.color)}
                  fill={seriesColor(i, s.color)}
                  fillOpacity={0.2}
                  strokeWidth={2}
                  isAnimationActive={false}
                />
              ))}
            </AreaChart>
          ) : (
            <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
              {grid}
              {xAxis}
              {yAxis}
              {tooltip}
              {legend}
              {series.map((s, i) => (
                <Bar
                  key={s.key}
                  dataKey={s.key}
                  name={s.label ?? s.key}
                  fill={seriesColor(i, s.color)}
                  radius={[3, 3, 0, 0]}
                  isAnimationActive={false}
                />
              ))}
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>

      {/* Screen-reader data table fallback */}
      <table className="sr-only">
        <caption>{spec.caption ?? 'Chart data'}</caption>
        <thead>
          <tr>
            <th>{xKey}</th>
            {series.map((s) => (
              <th key={s.key}>{s.label ?? s.key}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row, r) => (
            <tr key={r}>
              <td>{String(row[xKey])}</td>
              {series.map((s) => (
                <td key={s.key}>{String(row[s.key])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
