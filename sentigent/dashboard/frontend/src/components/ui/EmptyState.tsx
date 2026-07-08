interface EmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
}

export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-6 text-center">
      {icon && (
        <div className="relative mb-5">
          {/* Glow ring */}
          <div className="absolute inset-0 rounded-2xl bg-accent/10 blur-xl scale-150 pointer-events-none" />
          <div className="relative w-14 h-14 rounded-2xl bg-bg-elevated border border-bg-border flex items-center justify-center text-muted">
            {icon}
          </div>
        </div>
      )}
      <h3 className="text-sm font-semibold text-white mb-1.5">{title}</h3>
      {description && (
        <p className="text-xs text-muted max-w-xs leading-relaxed">{description}</p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
