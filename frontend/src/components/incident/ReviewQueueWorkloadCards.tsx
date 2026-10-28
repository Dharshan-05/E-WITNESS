import React from 'react';
import { Clock, UserCheck, UserMinus, AlertCircle, CheckCircle, Layers } from 'lucide-react';
import { Card, CardContent } from '../ui/Card';
import type { ReviewQueueWorkloadSummary } from '../../types/incident';

interface ReviewQueueWorkloadCardsProps {
  summary: ReviewQueueWorkloadSummary | null;
  isLoading?: boolean;
}

export const ReviewQueueWorkloadCards: React.FC<ReviewQueueWorkloadCardsProps> = ({
  summary,
  isLoading = false,
}) => {
  const cards = [
    {
      label: 'Pending Triage',
      value: summary?.pending ?? 0,
      icon: <Clock className="h-5 w-5 text-indigo-600" />,
      bg: 'bg-indigo-50 border-indigo-100',
      badge: 'Needs Review',
    },
    {
      label: 'Unassigned',
      value: summary?.unassigned ?? 0,
      icon: <UserMinus className="h-5 w-5 text-amber-600" />,
      bg: 'bg-amber-50 border-amber-100',
      badge: 'Action Required',
    },
    {
      label: 'Assigned',
      value: summary?.assigned ?? 0,
      icon: <UserCheck className="h-5 w-5 text-blue-600" />,
      bg: 'bg-blue-50 border-blue-100',
      badge: 'In Progress',
    },
    {
      label: 'Overdue Reviews',
      value: summary?.overdue ?? 0,
      icon: <AlertCircle className="h-5 w-5 text-rose-600" />,
      bg: 'bg-rose-50 border-rose-100',
      badge: summary && summary.overdue > 0 ? 'Urgent' : 'Normal',
    },
    {
      label: 'Completed',
      value: summary?.completed ?? 0,
      icon: <CheckCircle className="h-5 w-5 text-emerald-600" />,
      bg: 'bg-emerald-50 border-emerald-100',
      badge: 'Resolved',
    },
    {
      label: 'Total Queue',
      value: summary?.total ?? 0,
      icon: <Layers className="h-5 w-5 text-slate-600" />,
      bg: 'bg-slate-50 border-slate-200',
      badge: 'Scope Total',
    },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
      {cards.map((card) => (
        <Card key={card.label} className={`border ${card.bg}`}>
          <CardContent className="p-3.5">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider truncate">
                {card.label}
              </span>
              <div className="p-1 rounded-md bg-white/80 shadow-xs">{card.icon}</div>
            </div>
            {isLoading ? (
              <div className="h-7 w-12 bg-slate-200/60 animate-pulse rounded my-0.5" />
            ) : (
              <div className="text-2xl font-bold text-slate-900">{card.value}</div>
            )}
            <div className="text-[10px] text-slate-500 mt-1 font-medium">{card.badge}</div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
};
