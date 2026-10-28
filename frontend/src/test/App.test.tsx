import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import App from '../App';

describe('App Root Component', () => {
  it('renders application layout with branding and statutory notices', () => {
    render(<App />);

    // Brand title in Header
    expect(screen.getAllByText('E-WITNESS').length).toBeGreaterThan(0);

    // Main header on Home page
    expect(
      screen.getByText('Institutional Evidence & Investigation Workspace')
    ).toBeInTheDocument();

    // Skip to main content link for accessibility
    expect(screen.getByText('Skip to main content')).toBeInTheDocument();

    // Module cards
    expect(screen.getByRole('heading', { name: 'Incident Intake & Triage' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Case Management' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Evidence Custody' })).toBeInTheDocument();

    // Statutory notice in footer
    expect(
      screen.getByText(/AI predictions are probabilistic investigative leads requiring human review/i)
    ).toBeInTheDocument();
  });
});
