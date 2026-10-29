import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { KPIStatCard } from '../components/analytics/KPIStatCard';

describe('KPIStatCard Component', () => {
  it('renders title, formatted value, sublabel, and accessibility attributes', () => {
    render(
      <KPIStatCard
        title="Total Incidents"
        value={1250}
        sublabel="Scoped across current observation window"
        variant="primary"
        tooltip="Verified count from database"
      />
    );

    expect(screen.getByText('Total Incidents')).toBeInTheDocument();
    expect(screen.getByText('1,250')).toBeInTheDocument();
    expect(screen.getByText('Scoped across current observation window')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: /Total Incidents: 1250/i })).toBeInTheDocument();
  });

  it('renders loading skeleton when loading prop is true', () => {
    render(
      <KPIStatCard
        title="Active Cases"
        value={15}
        loading={true}
      />
    );

    const skeleton = screen.getByLabelText(/Loading Active Cases/i);
    expect(skeleton).toBeInTheDocument();
    expect(skeleton).toHaveAttribute('aria-busy', 'true');
    expect(screen.queryByText('15')).not.toBeInTheDocument();
  });

  it('renders string values directly without numeric formatting error', () => {
    render(
      <KPIStatCard
        title="System Uptime"
        value="99.98%"
        variant="success"
      />
    );

    expect(screen.getByText('99.98%')).toBeInTheDocument();
  });
});
