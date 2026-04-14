import { useState } from 'react';
import { Lock, X, Check } from 'lucide-react';
import { formatSalary, formatDecimal, formatPct } from '../utils/formatting';
import { POSITION_COLORS } from '../utils/constants';

export default function PlayerRow({ player, onToggleLock, onToggleExclude, onUpdateProjection, isOdd }) {
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

  const posColor = POSITION_COLORS[player.position] || '#6b7280';

  return (
    <tr className={`${isOdd ? 'bg-gray-900/50' : 'bg-gray-950'} hover:bg-gray-800/50 transition-colors`}>
      {/* Lock / Exclude */}
      <td className="px-2 py-1.5 w-10">
        <div className="flex items-center gap-1">
          <button
            onClick={() => onToggleLock?.(player.id)}
            className={`p-0.5 rounded transition-colors ${
              player.locked ? 'text-emerald-400' : 'text-gray-600 hover:text-gray-400'
            }`}
            title="Lock"
          >
            <Lock className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => onToggleExclude?.(player.id)}
            className={`p-0.5 rounded transition-colors ${
              player.excluded ? 'text-red-400' : 'text-gray-600 hover:text-gray-400'
            }`}
            title="Exclude"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
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

      {/* Order */}
      <td className="px-3 py-1.5 text-center">
        {player.order ? (
          <span className={`text-xs font-mono ${player.confirmed ? 'text-emerald-400' : 'text-amber-400'}`}>
            {player.order}
          </span>
        ) : (
          <span className="text-xs text-gray-600">--</span>
        )}
      </td>

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

      {/* Status */}
      <td className="px-3 py-1.5 text-center">
        {player.confirmed ? (
          <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded">
            <Check className="w-3 h-3" /> IN
          </span>
        ) : (
          <span className="text-[10px] font-semibold text-amber-400 bg-amber-500/10 px-1.5 py-0.5 rounded">
            PROJ
          </span>
        )}
      </td>
    </tr>
  );
}
