import { useState, useEffect, useMemo } from 'react';
import { Filter, Download, RefreshCw, Loader2 } from 'lucide-react';
import { formatSalary, formatDecimal, formatPct } from '../utils/formatting';
import { POSITIONS, POSITION_COLORS } from '../utils/constants';
import PlayerRow from '../components/PlayerRow';
import { api } from '../api/client';

export default function Projections() {
  const [players, setPlayers] = useState([]);
  const [slates, setSlates] = useState([]);
  const [activeSlate, setActiveSlate] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [posFilter, setPosFilter] = useState('ALL');
  const [teamFilter, setTeamFilter] = useState('ALL');
  const [salaryMin, setSalaryMin] = useState(2000);
  const [salaryMax, setSalaryMax] = useState(15000);
  const [minProj, setMinProj] = useState(0);
  const [sortKey, setSortKey] = useState('median');
  const [sortDir, setSortDir] = useState('desc');
  const [searchQuery, setSearchQuery] = useState('');

  const site = localStorage.getItem('dfs_site') || 'dk';

  // Load slates on mount
  useEffect(() => {
    api.getSlates(site).then(data => {
      setSlates(data);
      if (data.length > 0) {
        setActiveSlate(data[0]);
      }
    }).catch(() => {});
  }, [site]);

  // Load projections when slate changes
  useEffect(() => {
    setLoading(true);
    setError(null);
    api.getFeaturedProjections(site)
      .then(data => {
        const mapped = data.map((p, i) => ({
          id: i + 1,
          name: p.player_name,
          position: p.position || 'UTIL',
          team: p.team,
          opponent: p.opp_team || '—',
          salary: p.salary || 0,
          order: p.batting_order,
          floor: p.floor_pts,
          median: p.median_pts,
          ceiling: p.ceiling_pts,
          ownership: p.projected_ownership || 0,
          value: p.salary > 0 ? +(p.median_pts / (p.salary / 1000)).toFixed(2) : 0,
          confirmed: p.is_confirmed,
          isPitcher: p.is_pitcher,
          era: p.season_era,
          k9: p.season_k9,
          avg: p.season_avg,
          ops: p.season_ops,
          gamesInLog: p.games_in_log,
          impliedTotal: p.implied_total,
          teamImplied: p.team_implied,
          temperature: p.temperature,
          minExp: p.min_exposure ?? 0,
          maxExp: p.max_exposure ?? 100,
          locked: false,
          excluded: false,
        }));
        setPlayers(mapped);
        setLoading(false);
      })
      .catch(err => {
        setError(err.message);
        setLoading(false);
      });
  }, [site, activeSlate]);

  const filteredPlayers = useMemo(() => {
    return players.filter((p) => {
      if (p.excluded) return true; // always show excluded so user can un-exclude
      if (posFilter !== 'ALL') {
        if (posFilter === 'P') {
          if (!p.isPitcher) return false;
        } else {
          if (p.isPitcher) return false;
          if (!p.position.includes(posFilter)) return false;
        }
      }
      if (teamFilter !== 'ALL' && p.team !== teamFilter) return false;
      if (p.salary < salaryMin || p.salary > salaryMax) return false;
      if (p.median < minProj) return false;
      if (searchQuery && !p.name.toLowerCase().includes(searchQuery.toLowerCase())) return false;
      return true;
    });
  }, [players, posFilter, teamFilter, salaryMin, salaryMax, minProj, searchQuery]);

  const sortedPlayers = useMemo(() => {
    return [...filteredPlayers].sort((a, b) => {
      const aVal = a[sortKey];
      const bVal = b[sortKey];
      if (aVal == null) return 1;
      if (bVal == null) return -1;
      if (typeof aVal === 'string') return sortDir === 'asc' ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
      return sortDir === 'asc' ? aVal - bVal : bVal - aVal;
    });
  }, [filteredPlayers, sortKey, sortDir]);

  const handleSort = (key) => {
    if (sortKey === key) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };

  const handleToggleLock = (id) => {
    setPlayers(players.map(p => p.id === id ? { ...p, locked: !p.locked, excluded: false } : p));
  };

  const handleToggleExclude = (id) => {
    setPlayers(players.map(p => p.id === id ? { ...p, excluded: !p.excluded, locked: false } : p));
  };

  const handleUpdateProjection = (id, updates) => {
    setPlayers(players.map(p => p.id === id ? { ...p, ...updates } : p));
  };

  const uniqueTeams = [...new Set(players.map(p => p.team))].sort();
  const lockedCount = players.filter(p => p.locked).length;
  const excludedCount = players.filter(p => p.excluded).length;
  const pitcherCount = players.filter(p => p.isPitcher).length;
  const hitterCount = players.filter(p => !p.isPitcher).length;
  const confirmedCount = players.filter(p => p.confirmed).length;

  const columns = [
    { key: 'lock', label: '', width: 'w-10', sortable: false },
    { key: 'name', label: 'Player', sortable: true },
    { key: 'team', label: 'Team', sortable: true },
    { key: 'opponent', label: 'Opp', sortable: true },
    { key: 'salary', label: 'Salary', align: 'right', sortable: true },
    { key: 'order', label: 'Order', align: 'center', sortable: true },
    { key: 'floor', label: 'Floor', align: 'right', sortable: true },
    { key: 'median', label: 'Median', align: 'right', sortable: true },
    { key: 'ceiling', label: 'Ceiling', align: 'right', sortable: true },
    { key: 'ownership', label: 'Own%', align: 'right', sortable: true },
    { key: 'value', label: 'Value', align: 'right', sortable: true },
    { key: 'minExp', label: 'Min%', align: 'right', sortable: true },
    { key: 'maxExp', label: 'Max%', align: 'right', sortable: true },
    { key: 'confirmed', label: 'Status', align: 'center', sortable: true },
  ];

  const SortArrow = ({ colKey }) => {
    if (sortKey !== colKey) return null;
    return sortDir === 'asc' ? (
      <span className="text-blue-400 ml-0.5">&#9650;</span>
    ) : (
      <span className="text-blue-400 ml-0.5">&#9660;</span>
    );
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-100">Projections</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {loading ? 'Loading...' : (
              <>
                {filteredPlayers.length} players
                <span className="text-gray-600 mx-1">|</span>
                <span className="text-blue-400">{pitcherCount} P</span>
                <span className="text-gray-600 mx-1">/</span>
                <span className="text-blue-400">{hitterCount} H</span>
                <span className="text-gray-600 mx-1">|</span>
                <span className="text-emerald-400">{confirmedCount} confirmed</span>
                {lockedCount > 0 && <span className="text-emerald-400 ml-2">{lockedCount} locked</span>}
                {excludedCount > 0 && <span className="text-red-400 ml-2">{excludedCount} excluded</span>}
              </>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* Slate selector */}
          {slates.length > 0 && (
            <select
              value={activeSlate?.slate_id || ''}
              onChange={(e) => setActiveSlate(slates.find(s => s.slate_id === e.target.value))}
              className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-gray-200 focus:outline-none focus:border-blue-500"
            >
              {slates.map(s => (
                <option key={s.slate_id} value={s.slate_id}>{s.name} ({s.game_count} games)</option>
              ))}
            </select>
          )}
          <button
            onClick={() => { setLoading(true); api.getFeaturedProjections(site).then(data => { /* re-trigger */ window.location.reload(); }); }}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-gray-700 bg-gray-800 text-xs text-gray-300 hover:bg-gray-700 transition-colors"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Refresh
          </button>
          <button className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-gray-700 bg-gray-800 text-xs text-gray-300 hover:bg-gray-700 transition-colors">
            <Download className="w-3.5 h-3.5" />
            Export CSV
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Filter className="w-4 h-4 text-gray-500" />
        </div>

        <input
          type="text"
          placeholder="Search player..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500 w-48"
        />

        <select
          value={posFilter}
          onChange={(e) => setPosFilter(e.target.value)}
          className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-gray-200 focus:outline-none focus:border-blue-500"
        >
          <option value="ALL">All Positions</option>
          <option value="P">P</option>
          <option value="C">C</option>
          <option value="1B">1B</option>
          <option value="2B">2B</option>
          <option value="3B">3B</option>
          <option value="SS">SS</option>
          <option value="OF">OF</option>
        </select>

        <select
          value={teamFilter}
          onChange={(e) => setTeamFilter(e.target.value)}
          className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-gray-200 focus:outline-none focus:border-blue-500"
        >
          <option value="ALL">All Teams</option>
          {uniqueTeams.map(team => (
            <option key={team} value={team}>{team}</option>
          ))}
        </select>

        <div className="flex items-center gap-2">
          <span className="text-[10px] text-gray-500 uppercase">Sal</span>
          <input type="number" value={salaryMin} onChange={(e) => setSalaryMin(Number(e.target.value))}
            className="w-16 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs font-mono text-gray-200 focus:outline-none focus:border-blue-500" step={100} />
          <span className="text-gray-600">-</span>
          <input type="number" value={salaryMax} onChange={(e) => setSalaryMax(Number(e.target.value))}
            className="w-16 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs font-mono text-gray-200 focus:outline-none focus:border-blue-500" step={100} />
        </div>

        <div className="flex items-center gap-2">
          <span className="text-[10px] text-gray-500 uppercase">Min Proj</span>
          <input type="number" value={minProj} onChange={(e) => setMinProj(Number(e.target.value))}
            className="w-14 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs font-mono text-gray-200 focus:outline-none focus:border-blue-500" step={0.5} />
        </div>
      </div>

      {/* Loading state */}
      {loading && (
        <div className="flex items-center justify-center py-20">
          <div className="text-center">
            <Loader2 className="w-8 h-8 text-blue-500 animate-spin mx-auto mb-3" />
            <p className="text-sm text-gray-400">Generating projections from live data...</p>
            <p className="text-xs text-gray-600 mt-1">Fetching MLB stats, DK salaries, Vegas lines, weather</p>
          </div>
        </div>
      )}

      {/* Error state */}
      {error && !loading && (
        <div className="rounded-lg border border-red-800 bg-red-900/20 px-4 py-3 text-sm text-red-400">
          Failed to load projections: {error}
        </div>
      )}

      {/* Table */}
      {!loading && !error && (
        <div className="data-table-container rounded-lg border border-gray-800" style={{ maxHeight: 'calc(100vh - 280px)' }}>
          <table className="w-full text-left">
            <thead>
              <tr className="bg-gray-900">
                {columns.map((col) => (
                  <th
                    key={col.key}
                    className={`px-3 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-500 bg-gray-900 select-none ${col.width || ''} ${
                      col.sortable ? 'cursor-pointer hover:text-gray-300' : ''
                    } ${col.align === 'right' ? 'text-right' : col.align === 'center' ? 'text-center' : ''}`}
                    onClick={() => col.sortable && handleSort(col.key)}
                  >
                    {col.label}
                    {col.sortable && <SortArrow colKey={col.key} />}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedPlayers.map((player, i) => (
                <PlayerRow
                  key={player.id}
                  player={player}
                  isOdd={i % 2 === 1}
                  onToggleLock={handleToggleLock}
                  onToggleExclude={handleToggleExclude}
                  onUpdateProjection={handleUpdateProjection}
                />
              ))}
              {sortedPlayers.length === 0 && (
                <tr>
                  <td colSpan={columns.length} className="px-4 py-12 text-center text-sm text-gray-500">
                    No players match the current filters
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
