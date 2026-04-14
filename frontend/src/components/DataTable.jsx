import { useState, useMemo } from 'react';
import { ChevronUp, ChevronDown, Search } from 'lucide-react';

export default function DataTable({
  columns,
  data,
  defaultSort = null,
  defaultSortDir = 'desc',
  searchable = false,
  searchPlaceholder = 'Search...',
  compact = false,
  maxHeight = 'calc(100vh - 280px)',
  rowClassName,
  onRowClick,
}) {
  const [sortKey, setSortKey] = useState(defaultSort);
  const [sortDir, setSortDir] = useState(defaultSortDir);
  const [searchQuery, setSearchQuery] = useState('');

  const handleSort = (key) => {
    if (!key) return;
    if (sortKey === key) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };

  const filteredData = useMemo(() => {
    if (!searchQuery.trim()) return data;
    const q = searchQuery.toLowerCase();
    return data.filter((row) =>
      columns.some((col) => {
        const val = col.accessor ? row[col.accessor] : '';
        return String(val).toLowerCase().includes(q);
      })
    );
  }, [data, searchQuery, columns]);

  const sortedData = useMemo(() => {
    if (!sortKey) return filteredData;
    const col = columns.find((c) => c.accessor === sortKey);
    return [...filteredData].sort((a, b) => {
      let aVal = a[sortKey];
      let bVal = b[sortKey];
      if (col?.sortValue) {
        aVal = col.sortValue(a);
        bVal = col.sortValue(b);
      }
      if (aVal == null) return 1;
      if (bVal == null) return -1;
      if (typeof aVal === 'string') {
        return sortDir === 'asc'
          ? aVal.localeCompare(bVal)
          : bVal.localeCompare(aVal);
      }
      return sortDir === 'asc' ? aVal - bVal : bVal - aVal;
    });
  }, [filteredData, sortKey, sortDir, columns]);

  const py = compact ? 'py-1' : 'py-1.5';

  return (
    <div>
      {searchable && (
        <div className="relative mb-3">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
          <input
            type="text"
            placeholder={searchPlaceholder}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-gray-800 border border-gray-700 rounded-lg pl-10 pr-4 py-2 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500"
          />
        </div>
      )}

      <div className="data-table-container rounded-lg border border-gray-800" style={{ maxHeight }}>
        <table className="w-full text-left">
          <thead>
            <tr className="bg-gray-900">
              {columns.map((col) => (
                <th
                  key={col.accessor || col.id}
                  className={`px-3 ${py} text-[10px] uppercase tracking-wider font-semibold text-gray-500 bg-gray-900 select-none ${
                    col.sortable !== false ? 'cursor-pointer hover:text-gray-300' : ''
                  } ${col.headerClassName || ''}`}
                  style={{ width: col.width, minWidth: col.minWidth }}
                  onClick={() => col.sortable !== false && col.accessor && handleSort(col.accessor)}
                >
                  <div className={`flex items-center gap-1 ${col.align === 'right' ? 'justify-end' : col.align === 'center' ? 'justify-center' : ''}`}>
                    <span>{col.header}</span>
                    {col.sortable !== false && col.accessor && sortKey === col.accessor && (
                      sortDir === 'asc' ? (
                        <ChevronUp className="w-3 h-3 text-blue-400" />
                      ) : (
                        <ChevronDown className="w-3 h-3 text-blue-400" />
                      )
                    )}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sortedData.map((row, i) => (
              <tr
                key={row.id || i}
                className={`${
                  i % 2 === 0 ? 'bg-gray-950' : 'bg-gray-900/50'
                } hover:bg-gray-800/50 transition-colors ${
                  onRowClick ? 'cursor-pointer' : ''
                } ${rowClassName ? rowClassName(row, i) : ''}`}
                onClick={() => onRowClick?.(row, i)}
              >
                {columns.map((col) => (
                  <td
                    key={col.accessor || col.id}
                    className={`px-3 ${py} text-xs ${col.className || ''} ${
                      col.align === 'right' ? 'text-right' : col.align === 'center' ? 'text-center' : ''
                    }`}
                  >
                    {col.render ? col.render(row, i) : row[col.accessor]}
                  </td>
                ))}
              </tr>
            ))}
            {sortedData.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="px-3 py-8 text-center text-sm text-gray-500">
                  No data to display
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {searchable && (
        <div className="mt-2 text-xs text-gray-500">
          {sortedData.length} of {data.length} players
        </div>
      )}
    </div>
  );
}
