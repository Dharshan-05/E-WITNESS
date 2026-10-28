import React, { useState } from 'react';
import { clsx } from 'clsx';
import { Table, AreaChart } from 'lucide-react';
import type { TimeSeriesBucket } from '../../types/analytics';

export interface TimeSeriesChartProps {
  title: string;
  subtitle?: string;
  data: TimeSeriesBucket[];
  valueLabel?: string;
  lineColor?: string;
  fillColor?: string;
  height?: number;
  className?: string;
}

export const TimeSeriesChart: React.FC<TimeSeriesChartProps> = ({
  title,
  subtitle,
  data,
  valueLabel = 'Incidents',
  lineColor = '#4f46e5', // indigo-600
  fillColor = '#e0e7ff', // indigo-100
  height = 200,
  className,
}) => {
  const [showTable, setShowTable] = useState(false);

  if (!data || data.length === 0) {
    return (
      <div className={clsx('rounded-xl border border-slate-200 bg-white p-5 shadow-sm', className)}>
        <h4 className="text-sm font-bold text-slate-900">{title}</h4>
        {subtitle && <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>}
        <div className="flex h-44 flex-col items-center justify-center text-center text-slate-400">
          <AreaChart className="h-8 w-8 mb-2 stroke-1" aria-hidden="true" />
          <p className="text-xs font-medium">No recorded activity in selected observation period.</p>
        </div>
      </div>
    );
  }

  // Calculate scales and coordinate points
  const maxCount = Math.max(...data.map((d) => d.count), 1);
  const chartWidth = 600;
  const chartHeight = height;
  const paddingX = 40;
  const paddingY = 25;

  const innerWidth = chartWidth - paddingX * 2;
  const innerHeight = chartHeight - paddingY * 2;

  const points = data.map((bucket, index) => {
    const x =
      data.length === 1
        ? paddingX + innerWidth / 2
        : paddingX + (index / (data.length - 1)) * innerWidth;
    const y = paddingY + innerHeight - (bucket.count / maxCount) * innerHeight;
    return { x, y, bucket };
  });

  const pathD = points.reduce((acc, point, index) => {
    return `${acc} ${index === 0 ? 'M' : 'L'} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`;
  }, '');

  const areaD =
    data.length > 1
      ? `${pathD} L ${points[points.length - 1].x.toFixed(1)} ${(chartHeight - paddingY).toFixed(1)} L ${points[0].x.toFixed(1)} ${(chartHeight - paddingY).toFixed(1)} Z`
      : '';

  const formatDateLabel = (isoDate: string): string => {
    try {
      const d = new Date(isoDate);
      return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    } catch {
      return isoDate.substring(0, 10);
    }
  };

  return (
    <div
      className={clsx('rounded-xl border border-slate-200 bg-white p-5 shadow-sm flex flex-col', className)}
      role="region"
      aria-label={`${title} chart`}
    >
      <div className="flex items-center justify-between gap-4 mb-3">
        <div>
          <h4 className="text-sm font-bold text-slate-900">{title}</h4>
          {subtitle && <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>}
        </div>
        <button
          type="button"
          onClick={() => setShowTable((prev) => !prev)}
          className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100 hover:text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          aria-expanded={showTable}
          aria-controls={`table-${title.replace(/\s+/g, '-').toLowerCase()}`}
        >
          <Table className="h-3.5 w-3.5" aria-hidden="true" />
          <span>{showTable ? 'Hide Table' : 'Accessible Table'}</span>
        </button>
      </div>

      {showTable ? (
        <div
          id={`table-${title.replace(/\s+/g, '-').toLowerCase()}`}
          className="mt-2 max-h-56 overflow-y-auto rounded-lg border border-slate-200"
        >
          <table className="min-w-full divide-y divide-slate-200 text-left text-xs">
            <thead className="bg-slate-50 font-semibold text-slate-700 sticky top-0">
              <tr>
                <th scope="col" className="px-3 py-2">Interval Start (UTC)</th>
                <th scope="col" className="px-3 py-2">Interval End (UTC)</th>
                <th scope="col" className="px-3 py-2 text-right">{valueLabel}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 bg-white">
              {data.map((b, i) => (
                <tr key={i} className="hover:bg-slate-50">
                  <td className="px-3 py-1.5 font-mono text-slate-600">{b.bucket_start}</td>
                  <td className="px-3 py-1.5 font-mono text-slate-600">{b.bucket_end}</td>
                  <td className="px-3 py-1.5 font-semibold text-slate-900 text-right">{b.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="w-full overflow-hidden">
          <svg
            viewBox={`0 0 ${chartWidth} ${chartHeight}`}
            className="w-full h-auto overflow-visible select-none"
            aria-label={`${title} visualization`}
          >
            {/* Horizontal Grid lines */}
            {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
              const yVal = paddingY + innerHeight * (1 - ratio);
              const labelCount = Math.round(maxCount * ratio);
              return (
                <g key={ratio}>
                  <line
                    x1={paddingX}
                    y1={yVal}
                    x2={chartWidth - paddingX}
                    y2={yVal}
                    stroke="#e2e8f0"
                    strokeWidth="1"
                    strokeDasharray={ratio > 0 ? '4 4' : undefined}
                  />
                  <text
                    x={paddingX - 8}
                    y={yVal + 3}
                    textAnchor="end"
                    className="text-[10px] fill-slate-400 font-mono"
                  >
                    {labelCount}
                  </text>
                </g>
              );
            })}

            {/* Shaded Area */}
            {areaD && <path d={areaD} fill={fillColor} opacity={0.6} />}

            {/* Main Trend Line */}
            <path
              d={pathD}
              fill="none"
              stroke={lineColor}
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />

            {/* Data Point Dots */}
            {points.map((pt, i) => (
              <g key={i} className="group">
                <circle
                  cx={pt.x}
                  cy={pt.y}
                  r="3.5"
                  fill="#ffffff"
                  stroke={lineColor}
                  strokeWidth="2"
                  className="transition-all hover:r-5 cursor-pointer"
                >
                  <title>{`${formatDateLabel(pt.bucket.bucket_start)}: ${pt.bucket.count} ${valueLabel}`}</title>
                </circle>
              </g>
            ))}

            {/* X-axis date labels */}
            {points.length > 0 && (
              <>
                <text
                  x={points[0].x}
                  y={chartHeight - 6}
                  textAnchor="start"
                  className="text-[10px] fill-slate-500 font-medium"
                >
                  {formatDateLabel(points[0].bucket.bucket_start)}
                </text>
                {points.length > 2 && (
                  <text
                    x={points[Math.floor(points.length / 2)].x}
                    y={chartHeight - 6}
                    textAnchor="middle"
                    className="text-[10px] fill-slate-500 font-medium"
                  >
                    {formatDateLabel(points[Math.floor(points.length / 2)].bucket.bucket_start)}
                  </text>
                )}
                {points.length > 1 && (
                  <text
                    x={points[points.length - 1].x}
                    y={chartHeight - 6}
                    textAnchor="end"
                    className="text-[10px] fill-slate-500 font-medium"
                  >
                    {formatDateLabel(points[points.length - 1].bucket.bucket_start)}
                  </text>
                )}
              </>
            )}
          </svg>
        </div>
      )}
    </div>
  );
};
