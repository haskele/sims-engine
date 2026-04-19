import { useState } from 'react';
import { X, Check } from 'lucide-react';
import { formatSalary, formatDecimal, formatPct } from '../utils/formatting';
import { POSITION_COLORS } from '../utils/constants';

export default function PlayerRow({ player, playerType, onToggleExclude, onUpdateProjection, isOdd }) {
  const [editing, setEditing] = useState(null); // 'floor' | 'median' | 'ceiling' | null
  const [editValue, setEditValue] = useState('');

  const handleStartEdit = (field) => {
    setEditing(field);
    setEditValue(String(player[field]));
  };

  const handleSaveEdit = () => {
    if (editing && editValue !== '') {
      onUpdateProjection?.(player.id, { [editing]: parseFloat(editValue) });
    }
    setEditing(null);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') handleSaveEdit();
    if (e.key === 'Escape') setEditing(null);
  };

  // For multi-position players (e.g. "2B/OF"), use the first position's color
  const primaryPos = player.position.split('/')[0];
  const posColor = POSITION_COLORS[player.position] || POSITION_COLORS[primaryPos] || '#6b7280';

  return (
    <tr className={`${isOdd ? 'bg-gray-900/50' : 'bg-gray-950'} hover:bg-gray-800/50 transition-colors`}>
      {/* Exclude */}
      <td className="px-2 py-1.5 w-8">
        <button
          onClick={() => onToggleExclude?.(player.id)}
          className={`p-0.5 rounded transition-colors ${
            player.excluded ? 'text-red-400' : 'text-gray-600 hover:text-gray-400'
          }`}
          title="Exclude"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </td>

      {/* Player Name */}
      <td className="px-3 py-1.5">
        <div className="flex items-center gap-2">
          <span
            className="text-[10px] font-bold px-1.5 py-0.5 rounded"
            style={{ backgroundColor: `${posColor}20`, color: posColor }}
          >
            {player.position}
          </span>
          <span className={`text-sm ${player.excluded ? 'text-gray-600 line-through' : 'text-gray-100'}`}>
            {player.name}
          </span>
          {player.openerStatus === 'PO' && (
            <span className="text-[9px] font-bold px-1 py-0.5 rounded bg-amber-500/15 text-amber-400 leading-none">
              PO
            </span>
          )}
          {player.openerStatus === 'PLR' && (
            <span className="text-[9px] font-bold px-1 py-0.5 rounded bg-blue-500/15 text-blue-400 leading-none">
              PLR
            </span>
          )}
        </div>
      </td>

      {/* Team */}
      <td className="px-3 py-1.5">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-mono text-gray-300">{player.team}</span>
          {player.teamTotal && (
            <span className="text-[10px] font-mono text-gray-500">({player.teamTotal})</span>
          )}
        </div>
      </td>

      {/* Opponent */}
      <td className="px-3 py-1.5 text-xs text-gray-500">
        {player.handedness && <span className="mr-1">vs {player.handedness}</span>}
        {player.opponent}
      </td>

      {/* Salary */}
      <td className="px-3 py-1.5 text-xs font-mono text-gray-300 text-right">
        {formatSalary(player.salary)}
      </td>

      {/* Pitcher: ERA + K/9 + K Prop  |  Hitter: Order */}
      {playerType === 'pitchers' ? (
        <>
          <td className="px-3 py-1.5 text-right">
            <span className="text-xs font-mono text-gray-300">
              {player.era != null ? formatDecimal(player.era, 2) : '--'}
            </span>
          </td>
          <td className="px-3 py-1.5 text-right">
            <span className="text-xs font-mono text-gray-300">
              {player.k9 != null ? formatDecimal(player.k9, 1) : '--'}
            </span>
          </td>
          <td className="px-2 py-1.5 text-center">
            <span className="text-[11px] font-mono text-cyan-400 whitespace-nowrap">
              {player.kLine || '--'}
            </span>
          </td>
        </>
      ) : (
        <td className="px-3 py-1.5 text-center">
          {player.lineupStatus === 'out' ? (
            <span className="text-xs font-mono font-semibold text-red-400">NA</span>
          ) : player.order ? (
            <span className={`text-xs font-mono font-semibold ${
              player.lineupStatus === 'confirmed' ? 'text-emerald-400' :
              player.lineupStatus === 'expected' ? 'text-amber-400' :
              'text-gray-400'
            }`}>
              {player.order}
            </span>
          ) : (
            <span className="text-xs text-gray-600">--</span>
          )}
        </td>
      )}

      {/* Floor */}
      <td className="px-3 py-1.5 text-right">
        {editing === 'floor' ? (
          <input
            type="number"
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onBlur={handleSaveEdit}
            onKeyDown={handleKeyDown}
            className="w-14 bg-gray-800 border border-blue-500 rounded px-1.5 py-0.5 text-xs font-mono text-gray-100 text-right focus:outline-none"
            autoFocus
          />
        ) : (
          <span
            className="inline-edit-cell text-xs font-mono text-purple-400"
            onClick={() => handleStartEdit('floor')}
          >
            {formatDecimal(player.floor)}
          </span>
        )}
      </td>

      {/* Median */}
      <td className="px-3 py-1.5 text-right">
        {editing === 'median' ? (
          <input
            type="number"
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onBlur={handleSaveEdit}
            onKeyDown={handleKeyDown}
            className="w-14 bg-gray-800 border border-blue-500 rounded px-1.5 py-0.5 text-xs font-mono text-gray-100 text-right focus:outline-none"
            autoFocus
          />
        ) : (
          <span
            className="inline-edit-cell text-xs font-mono text-gray-100 font-semibold"
            onClick={() => handleStartEdit('median')}
          >
            {formatDecimal(player.median)}
          </span>
        )}
      </td>

      {/* Ceiling */}
      <td className="px-3 py-1.5 text-right">
        {editing === 'ceiling' ? (
          <input
            type="number"
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onBlur={handleSaveEdit}
            onKeyDown={handleKeyDown}
            className="w-14 bg-gray-800 border border-blue-500 rounded px-1.5 py-0.5 text-xs font-mono text-gray-100 text-right focus:outline-none"
            autoFocus
          />
        ) : (
          <span
            className="inline-edit-cell text-xs font-mono text-amber-400"
            onClick={() => handleStartEdit('ceiling')}
          >
            {formatDecimal(player.ceiling)}
          </span>
        )}
      </td>

      {/* Proj Own% */}
      <td className="px-3 py-1.5 text-right">
        <span className="text-xs font-mono text-gray-400">{formatPct(player.ownership)}</span>
      </td>

      {/* Value */}
      <td className="px-3 py-1.5 text-right">
        <span className={`text-xs font-mono ${player.value >= 4 ? 'text-emerald-400' : player.value >= 3 ? 'text-gray-200' : 'text-gray-500'}`}>
          {formatDecimal(player.value, 2)}x
        </span>
      </td>

      {/* Batter DK Props: HR 1+, 2+ TB, 2+ HRR (only for hitters) */}
      {playerType === 'hitters' && (
        <>
          <td className="px-2 py-1.5 text-center">
            <span className="text-[11px] font-mono text-cyan-400 whitespace-nowrap">
              {player.hrLine || '--'}
            </span>
          </td>
          <td className="px-2 py-1.5 text-center">
            <span className="text-[11px] font-mono text-cyan-400 whitespace-nowrap">
              {player.tbLine || '--'}
            </span>
          </td>
          <td className="px-2 py-1.5 text-center">
            <span className="text-[11px] font-mono text-cyan-400 whitespace-nowrap">
              {player.hrrLine || '--'}
            </span>
          </td>
        </>
      )}

      {/* Min Exp */}
      <td className="px-2 py-1.5 text-right">
        {editing === 'minExp' ? (
          <input
            type="number"
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onBlur={handleSaveEdit}
            onKeyDown={handleKeyDown}
            className="w-12 bg-gray-800 border border-blue-500 rounded px-1 py-0.5 text-xs font-mono text-gray-100 text-right focus:outline-none"
            autoFocus
            min={0}
            max={100}
          />
        ) : (
          <span
            className="inline-edit-cell text-xs font-mono text-gray-400"
            onClick={() => handleStartEdit('minExp')}
          >
            {player.minExp ?? 0}
          </span>
        )}
      </td>

      {/* Max Exp */}
      <td className="px-2 py-1.5 text-right">
        {editing === 'maxExp' ? (
          <input
            type="number"
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onBlur={handleSaveEdit}
            onKeyDown={handleKeyDown}
            className="w-12 bg-gray-800 border border-blue-500 rounded px-1 py-0.5 text-xs font-mono text-gray-100 text-right focus:outline-none"
            autoFocus
            min={0}
            max={100}
          />
        ) : (
          <span
            className="inline-edit-cell text-xs font-mono text-gray-400"
            onClick={() => handleStartEdit('maxExp')}
          >
            {player.maxExp ?? 100}
          </span>
        )}
      </td>

      {/* Status */}
      <td className="px-3 py-1.5 text-center">
        {player.lineupStatus === 'confirmed' && player.confirmed ? (
          <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded">
            <Check className="w-3 h-3" /> IN
          </span>
        ) : player.lineupStatus === 'expected' && player.confirmed ? (
          <span className="text-[10px] font-semibold text-amber-400 bg-amber-500/10 px-1.5 py-0.5 rounded">
            EXP
          </span>
        ) : player.lineupStatus === 'out' ? (
          <span className="text-[10px] font-semibold text-red-400 bg-red-500/10 px-1.5 py-0.5 rounded">
            OUT
          </span>
        ) : (
          <span className="text-[10px] font-semibold text-gray-500 bg-gray-500/10 px-1.5 py-0.5 rounded">
            —
          </span>
        )}
      </td>
    </tr>
  );
}
