import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../components/ui/Card';
import { Alert } from '../components/ui/Alert';
import { Skeleton } from '../components/ui/Skeleton';
import { EmptyState } from '../components/ui/EmptyState';
import { ErrorBoundary } from '../components/ui/ErrorBoundary';
import { StatutoryNotice } from '../components/ui/StatutoryNotice';

describe('Shared UI Components (Design System)', () => {
  describe('Button Component', () => {
    it('renders label and handles click events', () => {
      const handleClick = vi.fn();
      render(<Button onClick={handleClick}>Submit Action</Button>);

      const btn = screen.getByRole('button', { name: /Submit Action/i });
      expect(btn).toBeInTheDocument();
      fireEvent.click(btn);
      expect(handleClick).toHaveBeenCalledTimes(1);
    });

    it('disables button and shows spinner when isLoading is true', () => {
      render(<Button isLoading>Processing...</Button>);
      const btn = screen.getByRole('button');
      expect(btn).toBeDisabled();
      expect(btn.querySelector('.animate-spin')).toBeInTheDocument();
    });

    it('applies variant classes correctly', () => {
      const { rerender } = render(<Button variant="danger">Delete</Button>);
      expect(screen.getByRole('button')).toHaveClass('bg-rose-600');

      rerender(<Button variant="outline">Cancel</Button>);
      expect(screen.getByRole('button')).toHaveClass('border-slate-300');
    });
  });

  describe('Badge Component', () => {
    it('renders badge content and variants', () => {
      render(<Badge variant="success">Verified</Badge>);
      const badge = screen.getByText('Verified');
      expect(badge).toBeInTheDocument();
      expect(badge).toHaveClass('bg-emerald-50');
    });
  });

  describe('Card Component', () => {
    it('renders card with structured header and content', () => {
      render(
        <Card>
          <CardHeader>
            <CardTitle>Case File CASE-2026-00001</CardTitle>
            <CardDescription>Formal inquiry into courtyard incident</CardDescription>
          </CardHeader>
          <CardContent>
            <p>Investigation in progress.</p>
          </CardContent>
        </Card>
      );

      expect(screen.getByText('Case File CASE-2026-00001')).toBeInTheDocument();
      expect(screen.getByText('Formal inquiry into courtyard incident')).toBeInTheDocument();
      expect(screen.getByText('Investigation in progress.')).toBeInTheDocument();
    });
  });

  describe('Alert Component', () => {
    it('renders with role="alert" and variant styling', () => {
      render(
        <Alert variant="warning" title="Advisory Warning">
          Human verification required before taking action.
        </Alert>
      );

      const alert = screen.getByRole('alert');
      expect(alert).toBeInTheDocument();
      expect(screen.getByText('Advisory Warning')).toBeInTheDocument();
      expect(screen.getByText(/Human verification required/i)).toBeInTheDocument();
      expect(alert).toHaveClass('bg-amber-50');
    });
  });

  describe('Skeleton Component', () => {
    it('renders skeleton with accessible busy state', () => {
      render(<Skeleton width={200} height={20} data-testid="test-skeleton" />);
      const skeleton = screen.getByTestId('test-skeleton');
      expect(skeleton).toHaveAttribute('aria-busy', 'true');
      expect(skeleton).toHaveClass('animate-pulse');
    });
  });

  describe('EmptyState Component', () => {
    it('renders title, description and action', () => {
      render(
        <EmptyState
          title="No Cases Found"
          description="There are currently no active cases assigned to this department."
          action={<Button size="sm">Create New Case</Button>}
        />
      );

      expect(screen.getByText('No Cases Found')).toBeInTheDocument();
      expect(screen.getByText(/no active cases/i)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Create New Case/i })).toBeInTheDocument();
    });
  });

  describe('StatutoryNotice Component', () => {
    it('renders statutory advisory text', () => {
      render(<StatutoryNotice />);
      expect(screen.getByText(/AI violence detection annotations are probabilistic/i)).toBeInTheDocument();
      expect(screen.getByText(/Biometric facial matching/i)).toBeInTheDocument();
    });
  });

  describe('ErrorBoundary Component', () => {
    it('catches render errors and renders fallback UI', () => {
      // Suppress expected console.error during deliberate throw
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

      const BombComponent = () => {
        throw new Error('Explosive test failure');
      };

      render(
        <ErrorBoundary>
          <BombComponent />
        </ErrorBoundary>
      );

      expect(screen.getByText(/Application Render Error/i)).toBeInTheDocument();
      expect(screen.getByText(/Explosive test failure/i)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Reload Interface/i })).toBeInTheDocument();

      consoleSpy.mockRestore();
    });
  });
});
