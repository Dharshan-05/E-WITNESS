import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { DistributionBarChart } from '../components/analytics/DistributionBarChart';

describe('DistributionBarChart Component', () => {
  const mockDistribution = {
    physical_altercation: 20,
    theft: 15,
    harassment: 10,
    trespassing: 5,
  };

  it('renders category entries with formatted labels, counts, and percentages', () => {
    render(
      <DistributionBarChart
        title="Incident Categories"
        subtitle="Distribution of categorized campus infractions."
        data={mockDistribution}
      />
    );

    expect(screen.getByText('Incident Categories')).toBeInTheDocument();
    expect(screen.getByText('Distribution of categorized campus infractions.')).toBeInTheDocument();
    expect(screen.getByText('Total: 50')).toBeInTheDocument();

    // Check formatted key names
    expect(screen.getByText('Physical Altercation')).toBeInTheDocument();
    expect(screen.getByText('Theft')).toBeInTheDocument();

    // 20 / 50 = 40%
    expect(screen.getByText(/40\.0%/i)).toBeInTheDocument();
  });

  it('renders progressbar elements with proper ARIA accessibility values', () => {
    render(
      <DistributionBarChart
        title="Severity"
        data={{ high: 30, low: 70 }}
      />
    );

    const progressBars = screen.getAllByRole('progressbar');
    expect(progressBars.length).toBe(2);

    expect(progressBars[0]).toHaveAttribute('aria-valuenow', '70');
    expect(progressBars[0]).toHaveAttribute('aria-valuemin', '0');
    expect(progressBars[0]).toHaveAttribute('aria-valuemax', '100');
  });

  it('renders empty fallback when data object is empty', () => {
    render(
      <DistributionBarChart
        title="Empty Distribution"
        data={{}}
        emptyMessage="No infractions reported in this interval."
      />
    );

    expect(screen.getByText('No infractions reported in this interval.')).toBeInTheDocument();
  });
});
