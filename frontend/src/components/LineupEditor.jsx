import { useState, useMemo } from 'react';
import { X, UserPlus, Save, XCircle, Search } from 'lucide-react';
import { formatSalary, formatDecimal } from '../utils/formatting';
import { POSITION_COLORS, DK_CONFIG } from '../utils/constants';

const SALARY_CAP = DK_CONFIG.salaryCap;
const ROSTER_SLOTS = DK_CONFIG.positions; // ["P","P","C","1B","2B","3B","SS","OF","OF","OF"]

/**
 * Determine if a player is eligible for a given roster slot.
 * - Slot "P" matches position "P", "SP", "RP"
 * - Slot "OF" matches "OF", "LF", "CF", "RF"
 * - Otherwise, slot must appear in the player's "/" delimited position string
 */
function isEligible(playerPosition, slotName) {
  if (!playerPosition) return false;
  const parts = playerPosition.split('/').map(s => s.trim());

  if (slotName === 'P') {
    return parts.some(p => p === 'P' || p === 'SP' || p === 'RP');
  }
  if (slotName === 'OF') {
    return parts.some(p => p === 'OF' || p === 'LF' || p === 'CF' || p === 'RF');
  }
  return parts.includes(slotName);
}

export default function LineupEditor({ lineup, playerPool, onSave, onCancel }) {
  // Working copy of the lineup players array (same length as ROSTER_SLOTS, may have nulls)
  const [slots, setSlots] = useState(() => {
    const initial = ROSTER_SLOTS.map(() => null);
    if (lineup?.players) {
      lineup.players.forEach((p, i) => {
        if (i < initial.length) initial[i] = { ...p };
      });
    }
    return initial;
  });

  // Which slot index is currently selecting a player (-1 = none)
  const [selectingSlot, setSelectingSlot] = useState(-1);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortKey, setSortKey] = useState('median'); // 'median' | 'salary' | 'name'
  const [sortDir, setSortDir] = useState('desc');

  // Computed totals
  const totalSalary = slots.reduce((sum, p) => sum + (p?.salary || 0), 0);
  const remaining = SALARY_CAP - totalSalary;
  const totalProj = slots.reduce((sum, p) => sum + (p?.median || 0), 0);
  const filledCount = slots.filter(Boolean).length;
  const isComplete = filledCount === ROSTER_SLOTS.length;
  const isOverCap = remaining < 0;

  // Players already in the lineup (by name to prevent duplicates)
  const usedNames = useMemo(
    () => new Set(slots.filter(Boolean).map(p => p.name)),
    [slots]
  );

  // Filtered + sorted player list for the selector
  const filteredPlayers = useMemo(() => {
    if (selectingSlot < 0) return [];
    const slotName = ROSTER_SLOTS[selectingSlot];

    return playerPool
      .filter(p => {
        // Must be eligible for the slot
        if (!isEligible(p.position, slotName)) return false;
        // Not already in lineup
        if (usedNames.has(p.player_name)) return false;
        // Salary must not exceed remaining cap (considering we removed the current slot's player)
        const currentSlotSalary = slots[selectingSlot]?.salary || 0;
        const availableBudget = remaining + currentSlotSalary;
        if (p.salary > availableBudget) return false;
        // Search filter
        if (searchQuery) {
          const q = searchQuery.toLowerCase();
          if (!p.player_name.toLowerCase().includes(q) && !p.team.toLowerCase().includes(q)) {
            return false;
          }
        }
        return true;
      })
      .sort((a, b) => {
        let aVal, bVal;
        if (sortKey === 'median') { aVal = a.median_pts; bVal = b.median_pts; }
        else if (sortKey === 'salary') { aVal = a.salary; bVal = b.salary; }
        else { aVal = a.player_name; bVal = b.player_name; }

        if (typeof aVal === 'string') {
          return sortDir === 'asc' ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
        }
        return sortDir === 'desc' ? bVal - aVal : aVal - bVal;
      });
  }, [selectingSlot, playerPool, usedNames, remaining, slots, searchQuery, sortKey, sortDir]);

  const removePlayer = (idx) => {
    setSlots(prev => prev.map((p, i) => (i === idx ? null : p)));
  };

  const selectPlayer = (poolPlayer) => {
    if (selectingSlot < 0) return;
    const slotName = ROSTER_SLOTS[selectingSlot];
    setSlots(prev =>
      prev.map((p, i) =>
        i === selectingSlot
          ? {
              name: poolPlayer.player_name,
              position: poolPlayer.position,
              rosterPosition: slotName,
              team: poolPlayer.team,
              salary: poolPlayer.salary || 0,
              median: poolPlayer.median_pts || 0,
              dk_id: poolPlayer.dk_id,
            }
          : p
      )
    );
    setSelectingSlot(-1);
    setSearchQuery('');
  };

  const handleSave = () => {
    if (!isComplete || isOverCap) return;
    onSave({
      ...lineup,
      players: slots,
    });
  };

  const toggleSort = (key) => {
    if (sortKey === key) {
      setSortDir(d => (d === 'desc' ? 'asc' : 'desc'));
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="bg-gray-950 border border-gray-800 rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-800 bg-gray-900/80">
          <div className="flex items-center gap-4">
            <h2 className="text-sm font-bold text-gray-100">Edit Lineup #{lineup.id}</h2>
            <div className="flex items-center gap-3">
              <div className="text-xs text-gray-500">
                Salary:{' '}
                <span className={`font-mono font-semibold ${isOverCap ? 'text-red-400' : 'text-gray-200'}`}>
                  {formatSalary(totalSalary)}
                </span>
                <span className="text-gray-600 mx-1">/</span>
                <span className="font-mono text-gray-500">{formatSalary(SALARY_CAP)}</span>
              </div>
              <div className="text-xs text-gray-500">
                Rem:{' '}
                <span className={`font-mono font-semibold ${remaining >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {formatSalary(remaining)}
                </span>
              </div>
              <div className="text-xs text-gray-500">
                Proj:{' '}
                <span className="font-mono font-semibold text-emerald-400">
                  {formatDecimal(totalProj)}
                </span>
              </div>
            </div>
          </div>
          <button
            onClick={onCancel}
            className="p-1 text-gray-500 hover:text-gray-300 transition-colors"
          >
            <XCircle className="w-5 h-5" />
          </button>
        </div>

        {/* Roster Slots */}
        <div className="flex-1 overflow-y-auto">
          <div className="divide-y divide-gray-800/60">
            {ROSTER_SLOTS.map((slotName, idx) => {
              const player = slots[idx];
              const posColor = POSITION_COLORS[slotName] || '#6b7280';
              const isSelecting = selectingSlot === idx;

              return (
                <div key={idx}>
                  <div
                    className={`flex items-center justify-between px-4 py-2 transition-colors ${
                      isSelecting ? 'bg-blue-950/30 border-l-2 border-l-blue-500' : 'hover:bg-gray-900/60'
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <span
                        className="text-[10px] font-bold w-7 text-center py-0.5 rounded"
                        style={{ backgroundColor: `${posColor}20`, color: posColor }}
                      >
                        {slotName}
                      </span>
                      {player ? (
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-gray-200 font-medium">{player.name}</span>
                          <span className="text-[10px] text-gray-500 font-mono">{player.team}</span>
                          <span className="text-[10px] text-gray-600 font-mono">
                            {player.position !== slotName && `(${player.position})`}
                          </span>
                        </div>
                      ) : (
                        <span className="text-xs text-gray-600 italic">Empty</span>
                      )}
                    </div>
                    <div className="flex items-center gap-3">
                      {player && (
                        <>
                          <span className="text-xs font-mono text-gray-400">{formatSalary(player.salary)}</span>
                          <span className="text-xs font-mono text-emerald-400 w-10 text-right">
                            {formatDecimal(player.median)}
                          </span>
                        </>
                      )}
                      <div className="flex items-center gap-1">
                        {player && (
                          <button
                            onClick={() => removePlayer(idx)}
                            className="p-0.5 text-gray-600 hover:text-red-400 transition-colors"
                            title="Remove player"
                          >
                            <X className="w-3.5 h-3.5" />
                          </button>
                        )}
                        <button
                          onClick={() => {
                            setSelectingSlot(isSelecting ? -1 : idx);
                            setSearchQuery('');
                          }}
                          className={`p-0.5 transition-colors ${
                            isSelecting
                              ? 'text-blue-400 hover:text-blue-300'
                              : 'text-gray-600 hover:text-blue-400'
                          }`}
                          title={player ? 'Replace player' : 'Select player'}
                        >
                          <UserPlus className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>
                  </div>

                  {/* Inline player selector */}
                  {isSelecting && (
                    <div className="bg-gray-900/80 border-t border-gray-800/60">
                      {/* Search + sort */}
                      <div className="flex items-center gap-2 px-4 py-2 border-b border-gray-800/40">
                        <div className="relative flex-1">
                          <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500" />
                          <input
                            type="text"
                            value={searchQuery}
                            onChange={e => setSearchQuery(e.target.value)}
                            placeholder="Search players..."
                            className="w-full bg-gray-800 border border-gray-700 rounded pl-7 pr-2 py-1 text-xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500"
                            autoFocus
                          />
                        </div>
                        <div className="flex items-center gap-1">
                          {['median', 'salary', 'name'].map(key => (
                            <button
                              key={key}
                              onClick={() => toggleSort(key)}
                              className={`px-2 py-0.5 text-[10px] rounded transition-colors ${
                                sortKey === key
                                  ? 'bg-blue-600/30 text-blue-400'
                                  : 'text-gray-500 hover:text-gray-300'
                              }`}
                            >
                              {key === 'median' ? 'Proj' : key === 'salary' ? 'Sal' : 'Name'}
                              {sortKey === key && (
                                <span className="ml-0.5">{sortDir === 'desc' ? '↓' : '↑'}</span>
                              )}
                            </button>
                          ))}
                        </div>
                      </div>

                      {/* Player list */}
                      <div className="max-h-48 overflow-y-auto">
                        {filteredPlayers.length === 0 ? (
                          <div className="px-4 py-3 text-xs text-gray-600 text-center">
                            No eligible players found
                          </div>
                        ) : (
                          filteredPlayers.map((p, pi) => {
                            const pPosColor = POSITION_COLORS[p.position?.split('/')[0]] || '#6b7280';
                            return (
                              <div
                                key={p.player_name + p.team}
                                onClick={() => selectPlayer(p)}
                                className={`flex items-center justify-between px-4 py-1.5 cursor-pointer transition-colors ${
                                  pi % 2 === 0 ? 'bg-gray-900/40' : 'bg-gray-950/40'
                                } hover:bg-blue-950/30`}
                              >
                                <div className="flex items-center gap-2">
                                  <span
                                    className="text-[9px] font-bold w-8 text-center py-0.5 rounded"
                                    style={{ backgroundColor: `${pPosColor}15`, color: pPosColor }}
                                  >
                                    {p.position}
                                  </span>
                                  <span className="text-xs text-gray-200">{p.player_name}</span>
                                  <span className="text-[10px] text-gray-500 font-mono">{p.team}</span>
                                  {p.opp_team && (
                                    <span className="text-[10px] text-gray-600">{p.is_home === false ? `@ ${p.opp_team}` : `vs ${p.opp_team}`}</span>
                                  )}
                                </div>
                                <div className="flex items-center gap-4">
                                  <span className="text-xs font-mono text-gray-400 w-14 text-right">
                                    {formatSalary(p.salary || 0)}
                                  </span>
                                  <span className="text-xs font-mono text-emerald-400 w-10 text-right">
                                    {formatDecimal(p.median_pts || 0)}
                                  </span>
                                </div>
                              </div>
                            );
                          })
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-5 py-3 border-t border-gray-800 bg-gray-900/80">
          <div className="text-xs text-gray-500">
            {filledCount}/{ROSTER_SLOTS.length} slots filled
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onCancel}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-700 text-xs text-gray-400 hover:bg-gray-800 hover:text-gray-200 transition-colors"
            >
              <XCircle className="w-3.5 h-3.5" />
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={!isComplete || isOverCap}
              className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-blue-600 text-xs text-white font-semibold hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <Save className="w-3.5 h-3.5" />
              Save Lineup
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
