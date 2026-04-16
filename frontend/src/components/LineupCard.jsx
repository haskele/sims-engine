import { formatSalary, formatDecimal } from '../utils/formatting';
import { POSITION_COLORS } from '../utils/constants';
import { ChevronDown, ChevronUp, Copy, Pencil } from 'lucide-react';
import { useState } from 'react';

export default function LineupCard({ lineup, index, expanded: initialExpanded = false, onEdit }) {
  const [expanded, setExpanded] = useState(initialExpanded);

  const totalSalary = lineup.players.reduce((sum, p) => sum + p.salary, 0);
  const totalProj = lineup.players.reduce((sum, p) => sum + p.median, 0);
  const salaryCap = 50000;
  const remaining = salaryCap - totalSalary;

  // Compact lineup summary: (SP) M. Fried, (C) G. Sanchez, ...
  const lineupSummary = lineup.players.map(p => {
    const pos = p.rosterPosition || p.position;
    const parts = p.name.split(' ');
    const shortName = parts.length > 1
      ? `${parts[0][0]}. ${parts.slice(1).join(' ')}`
      : p.name;
    return `(${pos}) ${shortName}`;
  }).join(', ');

  return (
    <div className="border border-gray-800 rounded-lg bg-gray-900 overflow-hidden hover:border-gray-700 transition-colors">
      {/* Header */}
      <div
        className="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-gray-800/40 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-3">
          <span className="text-xs font-mono text-gray-500 w-5">#{index + 1}</span>
          <div className="flex items-center gap-4">
            <div>
              <span className="text-[10px] uppercase tracking-wider text-gray-500">Proj</span>
              <span className="ml-1.5 text-sm font-mono font-semibold text-emerald-400">
                {formatDecimal(totalProj)}
              </span>
            </div>
            <div>
              <span className="text-[10px] uppercase tracking-wider text-gray-500">Sal</span>
              <span className="ml-1.5 text-sm font-mono text-gray-300">
                {formatSalary(totalSalary)}
              </span>
            </div>
            <div>
              <span className="text-[10px] uppercase tracking-wider text-gray-500">Rem</span>
              <span className={`ml-1.5 text-xs font-mono ${remaining >= 0 ? 'text-gray-500' : 'text-red-400'}`}>
                {formatSalary(remaining)}
              </span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {onEdit && (
            <button
              onClick={(e) => { e.stopPropagation(); onEdit(lineup); }}
              className="p-1 text-gray-500 hover:text-blue-400 transition-colors"
              title="Edit lineup"
            >
              <Pencil className="w-3.5 h-3.5" />
            </button>
          )}
          <button
            onClick={(e) => { e.stopPropagation(); }}
            className="p-1 text-gray-500 hover:text-gray-300 transition-colors"
            title="Copy lineup"
          >
            <Copy className="w-3.5 h-3.5" />
          </button>
          {expanded ? (
            <ChevronUp className="w-4 h-4 text-gray-500" />
          ) : (
            <ChevronDown className="w-4 h-4 text-gray-500" />
          )}
        </div>
      </div>

      {/* Compact lineup preview (always visible) */}
      {!expanded && (
        <div className="px-3 pb-2 -mt-1">
          <p className="text-[11px] text-gray-500 leading-snug truncate">
            {lineupSummary}
          </p>
        </div>
      )}

      {/* Player list */}
      {expanded && (
        <div className="border-t border-gray-800">
          {lineup.players.map((player, i) => {
            const posColor = POSITION_COLORS[player.position] || '#6b7280';
            return (
              <div
                key={i}
                className={`flex items-center justify-between px-3 py-1.5 ${
                  i % 2 === 0 ? 'bg-gray-900' : 'bg-gray-950'
                } hover:bg-gray-800/40 transition-colors`}
              >
                <div className="flex items-center gap-2">
                  <span
                    className="text-[10px] font-bold w-6 text-center py-0.5 rounded"
                    style={{ backgroundColor: `${posColor}20`, color: posColor }}
                  >
                    {player.rosterPosition || player.position}
                  </span>
                  <span className="text-xs text-gray-200">{player.name}</span>
                  <span className="text-[10px] text-gray-500 font-mono">{player.team}</span>
                </div>
                <div className="flex items-center gap-4">
                  <span className="text-xs font-mono text-gray-400">{formatSalary(player.salary)}</span>
                  <span className="text-xs font-mono text-emerald-400 w-10 text-right">
                    {formatDecimal(player.median)}
                  </span>
                </div>
              </div>
            );
          })}
          {/* Totals row */}
          <div className="flex items-center justify-between px-3 py-2 bg-gray-800/50 border-t border-gray-700">
            <span className="text-xs font-semibold text-gray-300">Total</span>
            <div className="flex items-center gap-4">
              <span className="text-xs font-mono font-semibold text-gray-200">{formatSalary(totalSalary)}</span>
              <span className="text-xs font-mono font-semibold text-emerald-400 w-10 text-right">
                {formatDecimal(totalProj)}
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
