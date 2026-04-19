import { useState, useEffect, useMemo } from 'react';
import { Filter, Download, RefreshCw, Loader2 } from 'lucide-react';
import { formatSalary, formatDecimal, formatPct } from '../utils/formatting';
import { POSITIONS, POSITION_COLORS } from '../utils/constants';
import PlayerRow from '../components/PlayerRow';
import { api } from '../api/client';
import { useApp } from '../context/AppContext';

function StackExpInput({ team, stackSize, values, onChange }) {
  return (
    <>
      <td className="px-1 py-1">
        <input
          type="number"
          value={values.min}
          onChange={(e) => onChange(team, stackSize, 'min', e.target.value)}
          className="w-11 bg-gray-800 border border-gray-700 rounded px-1 py-0.5 text-[11px] font-mono text-gray-300 text-center focus:outline-none focus:border-blue-500"
          min={0} max={100}
        />
      </td>
      <td className="px-1 py-1">
        <input
          type="number"
          value={values.max}
          onChange={(e) => onChange(team, stackSize, 'max', e.target.value)}
          className="w-11 bg-gray-800 border border-gray-700 rounded px-1 py-0.5 text-[11px] font-mono text-gray-300 text-center focus:outline-none focus:border-blue-500"
          min={0} max={100}
        />
      </td>
    </>
  );
}

export default function Projections() {
  const { site, selectedSlate, selectedDate, stackExposures, setStackExposures, playerExposures, setPlayerExposures } = useApp();
  const [players, setPlayers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [playerType, setPlayerType] = useState('hitters'); // 'hitters' | 'pitchers' | 'teams'
  const [posFilter, setPosFilter] = useState('ALL');
  const [teamFilter, setTeamFilter] = useState('ALL');
  const [salaryMin, setSalaryMin] = useState(2000);
  const [salaryMax, setSalaryMax] = useState(15000);
  const [minProj, setMinProj] = useState(0);
  const [sortKey, setSortKey] = useState('median');
  const [sortDir, setSortDir] = useState('desc');
  const [searchQuery, setSearchQuery] = useState('');
  const [hideRPs, setHideRPs] = useState(true); // Hide relief pitchers by default

  // Load projections when slate changes
  useEffect(() => {
    if (!selectedSlate) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    api.getSlateProjections(selectedSlate.slate_id, site, selectedDate)
      .then(data => {
        if (!data || data.length === 0) {
          // Historical slate with no saved projection data
          setPlayers([]);
          setError(selectedSlate.is_historical
            ? 'Projection data not available for this historical slate. GameCenter view may still have snapshot data.'
            : null);
          setLoading(false);
          return;
        }
        const mapped = data.map((p, i) => ({
          id: i + 1,
          name: p.player_name,
          position: p.position || 'UTIL',
          team: p.team,
          opponent: p.opp_team ? (p.is_home === false ? `@${p.opp_team}` : p.opp_team) : '—',
          salary: p.salary || 0,
          order: p.batting_order,
          floor: p.floor_pts,
          median: p.median_pts,
          ceiling: p.ceiling_pts,
          ownership: p.projected_ownership || 0,
          value: p.salary > 0 ? +(p.median_pts / (p.salary / 1000)).toFixed(2) : 0,
          confirmed: p.is_confirmed,
          lineupStatus: p.lineup_status || 'unknown', // "confirmed", "expected", "out", "unknown"
          isPitcher: p.is_pitcher,
          era: p.season_era,
          k9: p.season_k9,
          avg: p.season_avg,
          ops: p.season_ops,
          gamesInLog: p.games_in_log,
          impliedTotal: p.implied_total,
          teamImplied: p.team_implied,
          temperature: p.temperature,
          minExp: playerExposures[p.player_name]?.min ?? p.min_exposure ?? 0,
          maxExp: playerExposures[p.player_name]?.max ?? p.max_exposure ?? 100,
          locked: false,
          excluded: false,
          kLine: p.k_line || null,
          hrLine: p.hr_line || null,
          tbLine: p.tb_line || null,
          hrrLine: p.hrr_line || null,
          openerStatus: p.opener_status || null,
          rpRole: p.rp_role || null,
        }));
        setPlayers(mapped);
        setLoading(false);
      })
      .catch(err => {
        setError(err.message);
        setLoading(false);
      });
  }, [site, selectedSlate, selectedDate]);

  const filteredPlayers = useMemo(() => {
    return players.filter((p) => {
      // Tab filter: hitters vs pitchers
      if (playerType === 'hitters' && p.isPitcher && !p.excluded) return false;
      if (playerType === 'pitchers' && !p.isPitcher && !p.excluded) return false;
      if (p.excluded) return true; // always show excluded so user can un-exclude
      // Remove hitters not in a confirmed lineup (team lineup is confirmed but player is out)
      if (!p.isPitcher && p.lineupStatus === 'out' && p.confirmed === false && !p.locked) return false;
      // Hide RPs filter: only show SP, PO, PLR, or pitchers without an rp_role (starters)
      if (playerType === 'pitchers' && hideRPs && p.isPitcher) {
        const isStarter = p.position === 'SP';
        const isOpener = p.openerStatus === 'PO';
        const isLongReliever = p.openerStatus === 'PLR';
        const hasNoRPRole = !p.rpRole; // null rp_role means they're a starter
        if (!isStarter && !isOpener && !isLongReliever && !hasNoRPRole) return false;
      }
      if (posFilter !== 'ALL') {
        if (playerType === 'hitters') {
          if (!p.position.split('/').includes(posFilter)) return false;
        }
        // Pitchers tab has no sub-position filter
      }
      if (teamFilter !== 'ALL' && p.team !== teamFilter) return false;
      if (p.salary < salaryMin || p.salary > salaryMax) return false;
      if (p.median < minProj) return false;
      if (searchQuery && !p.name.toLowerCase().includes(searchQuery.toLowerCase())) return false;
      return true;
    });
  }, [players, playerType, posFilter, teamFilter, salaryMin, salaryMax, minProj, searchQuery, hideRPs]);

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

  const handleToggleExclude = (id) => {
    setPlayers(players.map(p => p.id === id ? { ...p, excluded: !p.excluded, locked: false } : p));
  };

  const handleUpdateProjection = (id, updates) => {
    setPlayers(players.map(p => {
      if (p.id !== id) return p;
      const updated = { ...p, ...updates };
      if ('minExp' in updates || 'maxExp' in updates) {
        setPlayerExposures(prev => ({
          ...prev,
          [p.name]: {
            min: 'minExp' in updates ? updates.minExp : (prev[p.name]?.min ?? p.minExp ?? 0),
            max: 'maxExp' in updates ? updates.maxExp : (prev[p.name]?.max ?? p.maxExp ?? 100),
          },
        }));
      }
      return updated;
    }));
  };

  const uniqueTeams = [...new Set(players.map(p => p.team))].sort();
  const excludedCount = players.filter(p => p.excluded).length;
  const pitcherCount = players.filter(p => p.isPitcher).length;
  const hitterCount = players.filter(p => !p.isPitcher).length;
  const confirmedCount = players.filter(p => p.confirmed).length;

  // Team-level aggregates for the Teams tab
  const teamData = useMemo(() => {
    const teams = {};
    for (const p of players) {
      if (!p.team) continue;
      if (!teams[p.team]) {
        teams[p.team] = {
          team: p.team,
          opponent: p.opponent,
          impliedTotal: p.impliedTotal || p.teamImplied || null,
          hitters: [],
          pitcher: null,
          totalOwnership: 0,
          avgMedian: 0,
        };
      }
      if (p.isPitcher) {
        teams[p.team].pitcher = p;
      } else {
        teams[p.team].hitters.push(p);
      }
      teams[p.team].totalOwnership += (p.ownership || 0);
    }
    // Compute averages
    for (const t of Object.values(teams)) {
      const batters = t.hitters.filter(h => h.order && h.order <= 9);
      t.avgMedian = batters.length > 0
        ? batters.reduce((s, h) => s + h.median, 0) / batters.length
        : 0;
      t.stackOwn = t.totalOwnership;
    }
    return Object.values(teams).sort((a, b) => (b.impliedTotal || 0) - (a.impliedTotal || 0));
  }, [players]);

  const handleStackExposureChange = (team, stackSize, field, value) => {
    setStackExposures(prev => ({
      ...prev,
      [team]: {
        ...(prev[team] || {}),
        [`stack_${stackSize}`]: {
          ...(prev[team]?.[`stack_${stackSize}`] || { min: 0, max: 100 }),
          [field]: Math.max(0, Math.min(100, Number(value) || 0)),
        },
      },
    }));
  };

  const hitterColumns = [
    { key: 'exclude', label: '', width: 'w-8', sortable: false },
    { key: 'name', label: 'Player', sortable: true },
    { key: 'team', label: 'Team', sortable: true },
    { key: 'opponent', label: 'Opp', sortable: true },
    { key: 'salary', label: 'Salary', align: 'right', sortable: true },
    { key: 'order', label: 'Order', align: 'center', sortable: true },
    { key: 'floor', label: 'Bot 25%', align: 'right', sortable: true },
    { key: 'median', label: 'Median', align: 'right', sortable: true },
    { key: 'ceiling', label: 'Top 25%', align: 'right', sortable: true },
    { key: 'ownership', label: 'Own%', align: 'right', sortable: true },
    { key: 'value', label: 'Value', align: 'right', sortable: true },
    { key: 'hrLine', label: 'HR 1+', align: 'center', sortable: false },
    { key: 'tbLine', label: '2+ TB', align: 'center', sortable: false },
    { key: 'hrrLine', label: '2+ HRR', align: 'center', sortable: false },
    { key: 'minExp', label: 'Min%', align: 'right', sortable: true },
    { key: 'maxExp', label: 'Max%', align: 'right', sortable: true },
    { key: 'confirmed', label: 'Status', align: 'center', sortable: true },
  ];

  const pitcherColumns = [
    { key: 'exclude', label: '', width: 'w-8', sortable: false },
    { key: 'name', label: 'Player', sortable: true },
    { key: 'team', label: 'Team', sortable: true },
    { key: 'opponent', label: 'Opp', sortable: true },
    { key: 'salary', label: 'Salary', align: 'right', sortable: true },
    { key: 'era', label: 'ERA', align: 'right', sortable: true },
    { key: 'k9', label: 'K/9', align: 'right', sortable: true },
    { key: 'kLine', label: 'K Prop', align: 'center', sortable: false },
    { key: 'floor', label: 'Bot 25%', align: 'right', sortable: true },
    { key: 'median', label: 'Median', align: 'right', sortable: true },
    { key: 'ceiling', label: 'Top 25%', align: 'right', sortable: true },
    { key: 'ownership', label: 'Own%', align: 'right', sortable: true },
    { key: 'value', label: 'Value', align: 'right', sortable: true },
    { key: 'minExp', label: 'Min%', align: 'right', sortable: true },
    { key: 'maxExp', label: 'Max%', align: 'right', sortable: true },
    { key: 'confirmed', label: 'Status', align: 'center', sortable: true },
  ];

  const columns = playerType === 'pitchers' ? pitcherColumns : hitterColumns;

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
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
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
                {excludedCount > 0 && <span className="text-red-400 ml-2">{excludedCount} excluded</span>}
              </>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => { if (selectedSlate) { setLoading(true); setError(null); api.getSlateProjections(selectedSlate.slate_id, site).then(data => { setPlayers(data.map((p, i) => ({ id: i + 1, name: p.player_name, position: p.position || 'UTIL', team: p.team, opponent: p.opp_team || '—', salary: p.salary || 0, order: p.batting_order, floor: p.floor_pts, median: p.median_pts, ceiling: p.ceiling_pts, ownership: p.projected_ownership || 0, value: p.salary > 0 ? +(p.median_pts / (p.salary / 1000)).toFixed(2) : 0, confirmed: p.is_confirmed, lineupStatus: p.lineup_status || 'unknown', isPitcher: p.is_pitcher, era: p.season_era, k9: p.season_k9, avg: p.season_avg, ops: p.season_ops, gamesInLog: p.games_in_log, impliedTotal: p.implied_total, teamImplied: p.team_implied, temperature: p.temperature, minExp: playerExposures[p.player_name]?.min ?? p.min_exposure ?? 0, maxExp: playerExposures[p.player_name]?.max ?? p.max_exposure ?? 100, locked: false, excluded: false, openerStatus: p.opener_status || null, rpRole: p.rp_role || null }))); setLoading(false); }).catch(err => { setError(err.message); setLoading(false); }); } }}
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

      {/* Hitters / Pitchers / Teams tab switcher */}
      <div className="flex items-center gap-1 bg-gray-900 rounded-lg p-1 border border-gray-800 w-full sm:w-fit">
        <button
          onClick={() => { setPlayerType('hitters'); setPosFilter('ALL'); }}
          className={`flex-1 sm:flex-none px-4 py-1.5 rounded-md text-xs font-semibold transition-colors ${
            playerType === 'hitters'
              ? 'bg-gray-800 text-white shadow-sm'
              : 'text-gray-400 hover:text-gray-200'
          }`}
        >
          Hitters
          <span className={`ml-1.5 text-[10px] font-mono ${playerType === 'hitters' ? 'text-blue-400' : 'text-gray-500'}`}>
            {hitterCount}
          </span>
        </button>
        <button
          onClick={() => { setPlayerType('pitchers'); setPosFilter('ALL'); }}
          className={`flex-1 sm:flex-none px-4 py-1.5 rounded-md text-xs font-semibold transition-colors ${
            playerType === 'pitchers'
              ? 'bg-gray-800 text-white shadow-sm'
              : 'text-gray-400 hover:text-gray-200'
          }`}
        >
          Pitchers
          <span className={`ml-1.5 text-[10px] font-mono ${playerType === 'pitchers' ? 'text-blue-400' : 'text-gray-500'}`}>
            {pitcherCount}
          </span>
        </button>
        <button
          onClick={() => { setPlayerType('teams'); setPosFilter('ALL'); }}
          className={`flex-1 sm:flex-none px-4 py-1.5 rounded-md text-xs font-semibold transition-colors ${
            playerType === 'teams'
              ? 'bg-gray-800 text-white shadow-sm'
              : 'text-gray-400 hover:text-gray-200'
          }`}
        >
          Teams
          <span className={`ml-1.5 text-[10px] font-mono ${playerType === 'teams' ? 'text-blue-400' : 'text-gray-500'}`}>
            {uniqueTeams.length}
          </span>
        </button>
      </div>

      {/* Filters (hidden for teams tab) */}
      {playerType !== 'teams' && (
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-gray-500" />
          </div>

          <input
            type="text"
            placeholder="Search player..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500 w-full sm:w-48"
          />

          {playerType === 'hitters' && (
            <select
              value={posFilter}
              onChange={(e) => setPosFilter(e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-gray-200 focus:outline-none focus:border-blue-500"
            >
              <option value="ALL">All Positions</option>
              <option value="C">C</option>
              <option value="1B">1B</option>
              <option value="2B">2B</option>
              <option value="3B">3B</option>
              <option value="SS">SS</option>
              <option value="OF">OF</option>
            </select>
          )}

          {playerType === 'pitchers' && (
            <label className="flex items-center gap-1.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={hideRPs}
                onChange={(e) => setHideRPs(e.target.checked)}
                className="w-3.5 h-3.5 rounded border-gray-600 bg-gray-800 text-blue-500 focus:ring-blue-500 focus:ring-offset-0 cursor-pointer"
              />
              <span className="text-xs text-gray-400">Hide RPs</span>
            </label>
          )}

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
      )}

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

      {/* Error / historical notice */}
      {error && !loading && (
        <div className={`rounded-lg border px-4 py-3 text-sm ${
          error.includes('historical')
            ? 'border-amber-800 bg-amber-900/20 text-amber-400'
            : 'border-red-800 bg-red-900/20 text-red-400'
        }`}>
          {error.includes('historical') ? error : `Failed to load projections: ${error}`}
        </div>
      )}

      {/* Player Table (hitters/pitchers) */}
      {!loading && !error && playerType !== 'teams' && (
        <div className="data-table-container rounded-lg border border-gray-800 overflow-x-auto" style={{ maxHeight: 'calc(100vh - 280px)' }}>
          <table className="w-full text-left min-w-[800px]">
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
                  playerType={playerType}
                  isOdd={i % 2 === 1}
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

      {/* Teams Tab View */}
      {!loading && !error && playerType === 'teams' && (
        <div className="space-y-3" style={{ maxHeight: 'calc(100vh - 240px)', overflowY: 'auto' }}>
          {/* Teams table */}
          <div className="rounded-lg border border-gray-800 overflow-x-auto">
            <table className="w-full text-left min-w-[900px]">
              <thead>
                <tr className="bg-gray-900">
                  <th className="px-3 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-500">Team</th>
                  <th className="px-3 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-500">Opp</th>
                  <th className="px-3 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-500 text-right">Implied Runs</th>
                  <th className="px-3 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-500 text-right">Avg Median</th>
                  <th className="px-3 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-500 text-center">SP</th>
                  <th className="px-3 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-500 text-right">Total Own%</th>
                  <th className="px-2 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-500 text-center" colSpan={2}>3-Stack</th>
                  <th className="px-2 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-500 text-center" colSpan={2}>4-Stack</th>
                  <th className="px-2 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-500 text-center" colSpan={2}>5-Stack</th>
                </tr>
                <tr className="bg-gray-900/50">
                  <th colSpan={6}></th>
                  <th className="px-1 py-1 text-[9px] text-gray-600 text-center">Min</th>
                  <th className="px-1 py-1 text-[9px] text-gray-600 text-center">Max</th>
                  <th className="px-1 py-1 text-[9px] text-gray-600 text-center">Min</th>
                  <th className="px-1 py-1 text-[9px] text-gray-600 text-center">Max</th>
                  <th className="px-1 py-1 text-[9px] text-gray-600 text-center">Min</th>
                  <th className="px-1 py-1 text-[9px] text-gray-600 text-center">Max</th>
                </tr>
              </thead>
              <tbody>
                {teamData.map((team, i) => {
                  const se = stackExposures[team.team] || {};
                  return (
                    <tr key={team.team} className={`${i % 2 === 1 ? 'bg-gray-900/50' : 'bg-gray-950'} hover:bg-gray-800/50 transition-colors`}>
                      <td className="px-3 py-2">
                        <span className="text-sm font-semibold text-gray-100">{team.team}</span>
                      </td>
                      <td className="px-3 py-2 text-xs text-gray-500">{team.opponent}</td>
                      <td className="px-3 py-2 text-right">
                        <span className={`text-sm font-mono font-semibold ${
                          team.impliedTotal >= 5 ? 'text-emerald-400' :
                          team.impliedTotal >= 4 ? 'text-amber-400' :
                          'text-gray-400'
                        }`}>
                          {team.impliedTotal != null ? team.impliedTotal.toFixed(1) : '--'}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right">
                        <span className="text-xs font-mono text-gray-300">{team.avgMedian.toFixed(1)}</span>
                      </td>
                      <td className="px-3 py-2 text-center">
                        <span className="text-xs text-gray-300">{team.pitcher?.name || '--'}</span>
                        {team.pitcher?.openerStatus === 'PO' && (
                          <span className="ml-1 text-[9px] font-bold px-1 py-0.5 rounded bg-amber-500/15 text-amber-400 leading-none">PO</span>
                        )}
                        {team.pitcher?.openerStatus === 'PLR' && (
                          <span className="ml-1 text-[9px] font-bold px-1 py-0.5 rounded bg-blue-500/15 text-blue-400 leading-none">PLR</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <span className="text-xs font-mono text-gray-400">{team.stackOwn.toFixed(0)}%</span>
                      </td>
                      {/* Stack exposure inputs */}
                      {[3, 4, 5].map(sz => (
                        <StackExpInput
                          key={`${team.team}-${sz}`}
                          team={team.team}
                          stackSize={sz}
                          values={se[`stack_${sz}`] || { min: 0, max: 100 }}
                          onChange={handleStackExposureChange}
                        />
                      ))}
                    </tr>
                  );
                })}
                {teamData.length === 0 && (
                  <tr>
                    <td colSpan={12} className="px-4 py-12 text-center text-sm text-gray-500">
                      No team data available
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Team roster details (expanded by default) */}
          <div className="space-y-2">
            {teamData.map(team => (
              <div key={team.team} className="rounded-lg border border-gray-800 bg-gray-900/30 overflow-hidden">
                <div className="px-4 py-2 flex items-center justify-between bg-gray-900/50">
                  <div className="flex items-center gap-3">
                    <span className="text-sm font-bold text-gray-100">{team.team}</span>
                    <span className="text-xs text-gray-500">{team.opponent?.startsWith('@') ? team.opponent : `vs ${team.opponent}`}</span>
                    {team.impliedTotal && (
                      <span className="text-xs font-mono text-amber-400">{team.impliedTotal.toFixed(1)} runs</span>
                    )}
                  </div>
                  {team.pitcher && (
                    <span className="text-xs text-gray-400">
                      SP: {team.pitcher.name}
                      {team.pitcher.openerStatus === 'PO' && (
                        <span className="ml-1 text-[9px] font-bold px-1 py-0.5 rounded bg-amber-500/15 text-amber-400 leading-none">PO</span>
                      )}
                      {team.pitcher.openerStatus === 'PLR' && (
                        <span className="ml-1 text-[9px] font-bold px-1 py-0.5 rounded bg-blue-500/15 text-blue-400 leading-none">PLR</span>
                      )}
                    </span>
                  )}
                </div>
                <div className="px-4 py-2">
                  <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2">
                    {team.hitters.sort((a, b) => (a.order || 99) - (b.order || 99)).map(h => (
                      <div key={h.id} className="flex items-center gap-2 py-1 px-2 rounded bg-gray-800/50 text-xs">
                        <span className={`font-mono font-bold w-4 text-center ${
                          h.lineupStatus === 'confirmed' ? 'text-emerald-400' :
                          h.lineupStatus === 'expected' ? 'text-amber-400' :
                          'text-gray-600'
                        }`}>
                          {h.order || '-'}
                        </span>
                        <span className="text-gray-200 truncate flex-1">{h.name}</span>
                        {h.openerStatus === 'PO' && (
                          <span className="text-[9px] font-bold px-1 py-0.5 rounded bg-amber-500/15 text-amber-400 leading-none">PO</span>
                        )}
                        {h.openerStatus === 'PLR' && (
                          <span className="text-[9px] font-bold px-1 py-0.5 rounded bg-blue-500/15 text-blue-400 leading-none">PLR</span>
                        )}
                        <span className="text-gray-500 font-mono">{h.median.toFixed(1)}</span>
                        <span className="text-gray-600 font-mono text-[10px]">{(h.ownership || 0).toFixed(0)}%</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
