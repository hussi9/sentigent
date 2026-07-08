interface Column<T> {
  key: string;
  header: string;
  width?: string;
  render: (row: T) => React.ReactNode;
}

interface TableProps<T> {
  columns: Column<T>[];
  data: T[];
  keyFn: (row: T) => string;
  onRowClick?: (row: T) => void;
  emptyMessage?: string;
}

export function Table<T>({ columns, data, keyFn, onRowClick, emptyMessage }: TableProps<T>) {
  if (data.length === 0) {
    return (
      <div className="text-center py-10 text-xs text-muted">
        {emptyMessage ?? "No data available"}
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-bg-border">
            {columns.map((col) => (
              <th
                key={col.key}
                className="px-4 py-2.5 text-left text-muted font-medium tracking-wide"
                style={col.width ? { width: col.width } : undefined}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row) => (
            <tr
              key={keyFn(row)}
              onClick={() => onRowClick?.(row)}
              className={`
                border-b border-bg-border/50 transition-colors
                ${onRowClick ? "cursor-pointer hover:bg-bg-hover" : "hover:bg-bg-elevated/50"}
              `}
            >
              {columns.map((col) => (
                <td key={col.key} className="px-4 py-2.5 text-white/80">
                  {col.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
