interface CardProps {
  children: React.ReactNode;
  className?: string;
  glow?: boolean;
  hover?: boolean;
}

export function Card({ children, className = "", glow, hover }: CardProps) {
  return (
    <div
      className={`
        bg-bg-surface border border-bg-border rounded-xl overflow-hidden
        ${glow ? "shadow-glow" : "shadow-card"}
        ${hover ? "stat-card cursor-pointer" : ""}
        ${className}
      `}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`px-5 py-3.5 border-b border-bg-border flex items-center justify-between ${className}`}
      style={{ background: "rgba(20, 27, 38, 0.5)" }}
    >
      {children}
    </div>
  );
}

export function CardTitle({
  children,
  icon,
}: {
  children: React.ReactNode;
  icon?: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-2">
      {icon && (
        <span className="text-accent-light p-1 rounded-md bg-accent/10">
          {icon}
        </span>
      )}
      <h2 className="text-sm font-semibold text-white">{children}</h2>
    </div>
  );
}

export function CardBody({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <div className={`p-5 ${className}`}>{children}</div>;
}
