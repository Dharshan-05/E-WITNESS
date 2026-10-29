import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { TimeSeriesChart } from '../components/analytics/TimeSeriesChart';
import type { TimeSeriesBucket } from '../types/analytics';

describe('TimeSeriesChart Component', () => {
  const mockData: TimeSeriesBucket[] = [
    { bucket_start: '2026-10-01T00:00:00Z', bucket_end: '2026-10-02T00:00:00Z', count: 10 },
    { bucket_start: '2026-10-02T00:00:00Z', bucket_end: '2026-10-03T00:00:00Z', count: 25 },
    { bucket_start: '2026-10-03T00:00:00Z', bucket_end: '2026-10-04T00:00:00Z', count: 18 },
  ];

  it('renders title, subtitle, SVG chart, and truthful axes', () => {
    render(
      <TimeSeriesChart
        title="Incident Frequency"
        subtitle="Daily volume over the past 3 days."
        data={mockData}
        valueLabel="Reports"
      />
    );

    expect(screen.getByText('Incident Frequency')).toBeInTheDocument();
    expect(screen.getByText('Daily volume over the past 3 days.')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: /Incident Frequency chart/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/Incident Frequency visualization/i)).toBeInTheDocument();
  });

  it('renders accessible data table when Accessible Table button is toggled', () => {
    render(
      <TimeSeriesChart
        title="Incident Frequency"
        data={mockData}
        valueLabel="Incidents"
      />
    );

    const toggleBtn = screen.getByRole('button', { name: /Accessible Table/i });
    expect(toggleBtn).toBeInTheDocument();

    // Click to display accessible table
    fireEvent.click(toggleBtn);

    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getByText('2026-10-01T00:00:00Z')).toBeInTheDocument();
    expect(screen.getByText('25')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Hide Table/i })).toBeInTheDocument();
  });

  it('displays empty state when data array is empty', () => {
    render(
      <TimeSeriesChart
        title="Investigation Volume"
        data={[]}
      />
    );

    expect(screen.getByText('Investigation Volume')).toBeInTheDocument();
    expect(screen.getByText(/No recorded activity in selected observation period/i)).toBeInTheDocument();
  });
});
