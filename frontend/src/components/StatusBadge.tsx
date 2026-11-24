interface StatusBadgeProps {
  status: string;
}

const STYLE_MAP: Record<string, string> = {
  passed: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  go: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  approved: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  valid: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  stable: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  failed: 'border-rose-200 bg-rose-50 text-rose-700',
  no_go: 'border-rose-200 bg-rose-50 text-rose-700',
  blocked: 'border-rose-200 bg-rose-50 text-rose-700',
  rejected: 'border-rose-200 bg-rose-50 text-rose-700',
  high: 'border-rose-200 bg-rose-50 text-rose-700',
  pending: 'border-amber-200 bg-amber-50 text-amber-800',
  pending_approval: 'border-amber-200 bg-amber-50 text-amber-800',
  warning: 'border-amber-200 bg-amber-50 text-amber-800',
  flaky: 'border-amber-200 bg-amber-50 text-amber-800',
  evaluating: 'border-indigo-200 bg-indigo-50 text-indigo-700',
  draft: 'border-slate-200 bg-slate-100 text-slate-700',
  rolled_back: 'border-purple-200 bg-purple-50 text-purple-700',
  medium: 'border-amber-200 bg-amber-50 text-amber-800',
  low: 'border-slate-200 bg-slate-100 text-slate-700',
};

export function StatusBadge({ status }: StatusBadgeProps) {
  const key = status.toLowerCase();
  const classes = STYLE_MAP[key] || 'border-slate-200 bg-slate-50 text-slate-700';
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${classes}`}
    >
      {status.replace(/_/g, ' ')}
    </span>
  );
}
