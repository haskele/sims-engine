import { useState, useEffect, useRef, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Trophy,
  Users,
  DollarSign,
  PlayCircle,
  ChevronDown,
  ChevronRight,
  Upload,
  ArrowRight,
  AlertCircle,
  Loader2,
  CheckCircle2,
  FileText,
  RefreshCw,
  ArrowLeftRight,
  X,
  TrendingUp,
  TrendingDown,
  BarChart3,
  Layers,
} from 'lucide-react';
import { api } from '../api/client';
import { useApp } from '../context/AppContext';
import { formatCurrency, formatCompact } from '../utils/formatting';

// ── Live Data Sub-components ─────────────────────────────────────────────

function CollapsibleSection({ title, icon: Icon, isOpen, onToggle, badge, children }) {
  return (
    <div className="border-t border-gray-800">
      <button
        onClick={onToggle}
        className="flex items-center justify-between w-full px-5 py-2.5 text-xs text-gray-400 hover:text-gray-200 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Icon className="w-3.5 h-3.5" />
          <span className="font-semibold uppercase tracking-wider">{title}</span>
          {badge && (
            <span className="px-1.5 py-0.5 rounded bg-gray-800 text-[10px] font-mono text-gray-400">
              {badge}
            </span>
          )}
        </div>
        {isOpen ? (
          <ChevronDown className="w-3.5 h-3.5" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5" />
        )}
      </button>
      {isOpen && <div className="px-5 pb-4">{children}</div>}
    </div>
  );
}

function LeaderboardSection({ liveData }) {
  if (!liveData?.entries_scoring?.length) {
    return <div className="text-xs text-gray-500 italic py-2">No scoring data available</div>;
  }

  const { entries_scoring, leader_score } = liveData;

  return (
    <div className="space-y-2">
      {/* Leader reference */}
      <div className="flex items-center justify-between text-[10px] text-gray-500 px-2 py-1 rounded bg-gray-950">
        <span>Contest Leader (est.)</span>
        <span className="font-mono text-blue-400 font-bold">{leader_score.toFixed(1)} pts</span>
      </div>

      {/* Column headers */}
      <div className="grid grid-cols-12 gap-1 text-[10px] uppercase tracking-wider text-gray-500 px-2">
        <div className="col-span-2">Rank</div>
        <div className="col-span-4">Entry</div>
        <div className="col-span-3 text-right">Score</div>
        <div className="col-span-3 text-right">Payout</div>
      </div>

      {/* Entry rows */}
      <div className="space-y-0.5 max-h-60 overflow-y-auto">
        {entries_scoring.map((entry) => {
          const inMoney = entry.payout > 0;
          return (
            <div
              key={entry.entry_id}
              className={`grid grid-cols-12 gap-1 items-center rounded px-2 py-1.5 text-xs ${
                inMoney ? 'bg-emerald-950/40 border border-emerald-900/50' : 'bg-gray-950'
              }`}
            >
              <div className="col-span-2 font-mono font-bold text-gray-300">
                #{entry.rank}
              </div>
              <div className="col-span-4 font-mono text-gray-400 truncate text-[11px]">
                ...{entry.entry_id.slice(-6)}
              </div>
              <div className="col-span-3 text-right font-mono font-bold text-gray-100">
                {entry.score.toFixed(1)}
              </div>
              <div className={`col-span-3 text-right font-mono font-bold ${
                inMoney ? 'text-emerald-400' : 'text-gray-600'
              }`}>
                {inMoney ? formatCurrency(entry.payout, 0) : '--'}
              </div>
            </div>
          );
        })}
      </div>

      {/* Summary */}
      <div className="flex items-center justify-between text-[10px] text-gray-500 px-2 pt-1">
        <span>{entries_scoring.length} entries tracked</span>
        <span className="font-mono text-emerald-400">
          {entries_scoring.filter(e => e.payout > 0).length} in the money
        </span>
      </div>
    </div>
  );
}

function OwnershipSection({ liveData, userPlayerNames }) {
  if (!liveData?.ownership?.length) {
    return <div className="text-xs text-gray-500 italic py-2">No ownership data available</div>;
  }

  const maxPct = Math.max(...liveData.ownership.map(o => o.ownership_pct), 1);

  return (
    <div className="space-y-1">
      {liveData.ownership.map((player) => {
        const isOnUserLineup = userPlayerNames.has(player.player_name);
        return (
          <div key={player.player_name} className="flex items-center gap-2 px-2 py-1">
            <div className={`w-28 truncate text-xs ${
              isOnUserLineup ? 'text-blue-300 font-semibold' : 'text-gray-400'
            }`}>
              {player.player_name}
              {isOnUserLineup && (
                <span className="ml-1 text-[9px] text-blue-500">(yours)</span>
              )}
            </div>
            <div className="flex-1 h-3 bg-gray-950 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${
                  isOnUserLineup ? 'bg-blue-600' : 'bg-gray-700'
                }`}
                style={{ width: `${(player.ownership_pct / maxPct) * 100}%` }}
              />
            </div>
            <div className="w-12 text-right font-mono text-[11px] text-gray-400">
              {player.ownership_pct.toFixed(1)}%
            </div>
          </div>
        );
      })}
    </div>
  );
}

function StackSection({ liveData }) {
  if (!liveData?.stacks?.length) {
    return <div className="text-xs text-gray-500 italic py-2">No stacks detected (3+ players from same team)</div>;
  }

  return (
    <div className="flex flex-wrap gap-2">
      {liveData.stacks.map((stack, idx) => (
        <div
          key={`${stack.team}-${stack.size}-${idx}`}
          className="flex items-center gap-2 rounded-lg bg-gray-950 border border-gray-800 px-3 py-2"
        >
          <span className="text-xs font-bold text-gray-100">{stack.team}</span>
          <span className="text-[10px] font-mono text-blue-400">{stack.size}-stack</span>
          <span className="text-[10px] text-gray-500">
            ({stack.lineup_count} lineup{stack.lineup_count !== 1 ? 's' : ''})
          </span>
        </div>
      ))}
    </div>
  );
}

export default function MyContests() {
  const navigate = useNavigate();
  const { getCurrentBuild } = useApp();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [contests, setContests] = useState([]);
  const [entriesMap, setEntriesMap] = useState({}); // contestId -> entries[]
  const [expandedContests, setExpandedContests] = useState({});
  const [loadingEntries, setLoadingEntries] = useState({});

  // Late swap state
  const [swapResults, setSwapResults] = useState({}); // contestId -> swap results array
  const [loadingSwaps, setLoadingSwaps] = useState({}); // contestId -> bool
  const [swapError, setSwapError] = useState({}); // contestId -> error string

  // Quick sim state
  const [simResults, setSimResults] = useState({}); // contestId -> sim results
  const [loadingSim, setLoadingSim] = useState({}); // contestId -> bool
  const [simError, setSimError] = useState({}); // contestId -> error string

  // Live tracking state
  const [liveDataMap, setLiveDataMap] = useState({}); // contestId -> live data
  const [loadingLive, setLoadingLive] = useState({}); // contestId -> boolean
  const [expandedLeaderboards, setExpandedLeaderboards] = useState({});
  const [expandedOwnership, setExpandedOwnership] = useState({});
  const [expandedStacks, setExpandedStacks] = useState({});
  const [autoRefresh, setAutoRefresh] = useState(true);
  const refreshTimerRef = useRef(null);

  // Fetch contests on mount
  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const status = await api.getDkEntriesStatus();
        if (!status.uploaded) {
          setContests([]);
          setLoading(false);
          return;
        }
        const data = await api.getDkContests();
        if (!cancelled) setContests(data || []);
      } catch (err) {
        if (!cancelled) setError(err.message || 'Failed to load contests');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, []);

  // Toggle entry expansion and lazy-load entries
  const toggleExpand = async (contestId) => {
    const isExpanding = !expandedContests[contestId];
    setExpandedContests(prev => ({ ...prev, [contestId]: isExpanding }));

    if (isExpanding && !entriesMap[contestId]) {
      setLoadingEntries(prev => ({ ...prev, [contestId]: true }));
      try {
        const entries = await api.getDkEntries(contestId);
        setEntriesMap(prev => ({ ...prev, [contestId]: entries || [] }));
      } catch {
        setEntriesMap(prev => ({ ...prev, [contestId]: [] }));
      } finally {
        setLoadingEntries(prev => ({ ...prev, [contestId]: false }));
      }
    }
  };

  // Fetch live data for a single contest
  const fetchLiveData = useCallback(async (contestId) => {
    setLoadingLive(prev => ({ ...prev, [contestId]: true }));
    try {
      const data = await api.getContestLive(contestId);
      setLiveDataMap(prev => ({ ...prev, [contestId]: data }));
    } catch {
      // Silently fail -- live data is optional
    } finally {
      setLoadingLive(prev => ({ ...prev, [contestId]: false }));
    }
  }, []);

  // Auto-refresh live data every 60s for all contests with open live sections
  useEffect(() => {
    if (!autoRefresh) {
      if (refreshTimerRef.current) clearInterval(refreshTimerRef.current);
      return;
    }

    const hasOpenSections = Object.values(expandedLeaderboards).some(Boolean) ||
      Object.values(expandedOwnership).some(Boolean) ||
      Object.values(expandedStacks).some(Boolean);

    if (!hasOpenSections) {
      if (refreshTimerRef.current) clearInterval(refreshTimerRef.current);
      return;
    }

    refreshTimerRef.current = setInterval(() => {
      const openContestIds = new Set([
        ...Object.entries(expandedLeaderboards).filter(([, v]) => v).map(([k]) => k),
        ...Object.entries(expandedOwnership).filter(([, v]) => v).map(([k]) => k),
        ...Object.entries(expandedStacks).filter(([, v]) => v).map(([k]) => k),
      ]);
      openContestIds.forEach(cid => fetchLiveData(cid));
    }, 60000);

    return () => {
      if (refreshTimerRef.current) clearInterval(refreshTimerRef.current);
    };
  }, [autoRefresh, expandedLeaderboards, expandedOwnership, expandedStacks, fetchLiveData]);

  // Toggle live sections (fetch data on first open)
  const toggleLiveSection = (contestId, setter, currentMap) => {
    const isOpening = !currentMap[contestId];
    setter(prev => ({ ...prev, [contestId]: isOpening }));

    if (isOpening && !liveDataMap[contestId]) {
      fetchLiveData(contestId);
    }
  };

  // Get current lineups from build
  const currentLineups = getCurrentBuild()?.lineups || [];

  // Build set of player names across all current lineups for ownership highlighting
  const userPlayerNames = new Set();
  currentLineups.forEach(lineup => {
    if (lineup?.players) {
      lineup.players.forEach(p => {
        if (p.name || p.Name) userPlayerNames.add(p.name || p.Name);
        if (p.player_name) userPlayerNames.add(p.player_name);
      });
    }
  });

  // Derive lineup assignment for an entry
  // Lineups are assigned by index: entry 0 -> lineup 0, entry 1 -> lineup 1, etc.
  const getAssignedLineup = (entryIndex) => {
    if (entryIndex < currentLineups.length) return currentLineups[entryIndex];
    return null;
  };

  // Check late swaps for a contest
  const handleCheckSwaps = async (contest) => {
    const contestId = contest.contest_id;
    setLoadingSwaps(prev => ({ ...prev, [contestId]: true }));
    setSwapError(prev => ({ ...prev, [contestId]: null }));
    setSwapResults(prev => ({ ...prev, [contestId]: null }));

    try {
      // Load entries if not already loaded
      let entries = entriesMap[contestId];
      if (!entries) {
        entries = await api.getDkEntries(contestId);
        setEntriesMap(prev => ({ ...prev, [contestId]: entries || [] }));
      }

      if (!entries || entries.length === 0) {
        setSwapError(prev => ({ ...prev, [contestId]: 'No entries found for this contest' }));
        return;
      }

      // Check swaps for each entry's lineup
      const results = [];
      for (const entry of entries) {
        const players = entry.players || [];
        if (players.length === 0) continue;

        // Build lineup in the format the API expects
        const lineup = players.map(p => ({
          name: p.name,
          position: p.slot || p.position || 'UTIL',
          salary: p.salary || 0,
          dk_id: p.dk_id || null,
        }));

        try {
          const swapResult = await api.checkLateSwap(lineup, [], 'dk');
          results.push({
            entry_id: entry.entry_id || entry.EntryId,
            ...swapResult,
          });
        } catch (err) {
          results.push({
            entry_id: entry.entry_id || entry.EntryId,
            error: err.message,
          });
        }
      }

      setSwapResults(prev => ({ ...prev, [contestId]: results }));
    } catch (err) {
      setSwapError(prev => ({ ...prev, [contestId]: err.message || 'Failed to check swaps' }));
    } finally {
      setLoadingSwaps(prev => ({ ...prev, [contestId]: false }));
    }
  };

  // Quick-run simulation for a contest
  const handleQuickSim = async (contest) => {
    const contestId = contest.contest_id;
    setLoadingSim(prev => ({ ...prev, [contestId]: true }));
    setSimError(prev => ({ ...prev, [contestId]: null }));
    setSimResults(prev => ({ ...prev, [contestId]: null }));

    try {
      // Load entries if not already loaded
      let entries = entriesMap[contestId];
      if (!entries) {
        entries = await api.getDkEntries(contestId);
        setEntriesMap(prev => ({ ...prev, [contestId]: entries || [] }));
      }

      if (!entries || entries.length === 0) {
        setSimError(prev => ({ ...prev, [contestId]: 'No entries found for this contest' }));
        return;
      }

      // Build user lineups from entries
      const userLineups = entries.map(entry => {
        const players = entry.players || [];
        return players.map(p => ({
          name: p.name,
          position: p.slot || p.position || 'UTIL',
          salary: p.salary || 0,
          team: p.team || '',
        }));
      }).filter(lu => lu.length > 0);

      if (userLineups.length === 0) {
        setSimError(prev => ({ ...prev, [contestId]: 'No valid lineups to simulate' }));
        return;
      }

      const result = await api.quickRunSim(contestId, userLineups, 5000);
      setSimResults(prev => ({ ...prev, [contestId]: result }));
    } catch (err) {
      setSimError(prev => ({ ...prev, [contestId]: err.message || 'Simulation failed' }));
    } finally {
      setLoadingSim(prev => ({ ...prev, [contestId]: false }));
    }
  };

  // Compute summary stats
  const totalContests = contests.length;
  const totalEntries = contests.reduce((sum, c) => sum + (c.entry_count || 0), 0);
  const totalAtRisk = contests.reduce((sum, c) => {
    const fee = typeof c.entry_fee === 'number' ? c.entry_fee : parseFloat(c.entry_fee) || 0;
    return sum + fee * (c.entry_count || 0);
  }, 0);

  // Helper: payout summary from payout_structure
  const getPayoutSummary = (contest) => {
    const ps = contest.payout_structure;
    if (!ps || ps.length === 0) return null;
    const lastTier = ps[ps.length - 1];
    const totalPaidPositions = lastTier.maxPosition || lastTier.MaxPosition || lastTier.max_position || ps.length;
    const topPayout = ps[0]?.payout || ps[0]?.Payout || ps[0]?.prize || 0;
    return { totalPaidPositions, topPayout };
  };

  // Loading state
  if (loading) {
    return (
      <div className="max-w-5xl mx-auto flex items-center justify-center py-32">
        <Loader2 className="w-6 h-6 text-gray-500 animate-spin" />
        <span className="ml-3 text-sm text-gray-500">Loading contests...</span>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="max-w-5xl mx-auto space-y-6">
        <div>
          <h1 className="text-xl font-bold text-gray-100">My Contests</h1>
        </div>
        <div className="rounded-lg border border-red-800 bg-red-900/20 px-4 py-3 text-sm text-red-400 flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      </div>
    );
  }

  // Empty state
  if (contests.length === 0) {
    return (
      <div className="max-w-5xl mx-auto space-y-6">
        <div>
          <h1 className="text-xl font-bold text-gray-100">My Contests</h1>
          <p className="text-sm text-gray-500 mt-0.5">Manage your DraftKings contests and lineup assignments</p>
        </div>
        <div className="rounded-lg border border-gray-800 bg-gray-900 p-10 flex flex-col items-center text-center">
          <div className="w-14 h-14 rounded-full bg-gray-800 flex items-center justify-center mb-4">
            <Upload className="w-7 h-7 text-gray-500" />
          </div>
          <h2 className="text-lg font-semibold text-gray-200 mb-1">No Contests Uploaded</h2>
          <p className="text-sm text-gray-500 mb-5 max-w-md">
            Upload your DraftKings entries CSV on the Contests page to see your contests, entries, and lineup assignments here.
          </p>
          <Link
            to="/contests"
            className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-500 transition-colors"
          >
            Go to Contests
            <ArrowRight className="w-4 h-4" />
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-gray-100">My Contests</h1>
          <div className="flex flex-wrap items-center gap-2 sm:gap-4 mt-1">
            <span className="text-sm text-gray-500">
              {totalContests} contest{totalContests !== 1 ? 's' : ''}
            </span>
            <span className="text-gray-700">|</span>
            <span className="text-sm text-gray-500">
              {totalEntries} entr{totalEntries !== 1 ? 'ies' : 'y'}
            </span>
            <span className="text-gray-700">|</span>
            <span className="text-sm font-mono text-emerald-400">
              {formatCurrency(totalAtRisk, 2)} at risk
            </span>
          </div>
        </div>
        {/* Auto-refresh toggle */}
        <button
          onClick={() => setAutoRefresh(prev => !prev)}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
            autoRefresh
              ? 'bg-blue-600/20 text-blue-400 border border-blue-800'
              : 'bg-gray-800 text-gray-500 border border-gray-700'
          }`}
          title={autoRefresh ? 'Auto-refresh ON (60s)' : 'Auto-refresh OFF'}
        >
          <RefreshCw className={`w-3 h-3 ${autoRefresh ? 'animate-spin' : ''}`} style={autoRefresh ? { animationDuration: '3s' } : {}} />
          {autoRefresh ? 'Live' : 'Paused'}
        </button>
      </div>

      {/* Contest Cards */}
      {contests.map((contest) => {
        const fee = typeof contest.entry_fee === 'number' ? contest.entry_fee : parseFloat(contest.entry_fee) || 0;
        const contestAtRisk = fee * (contest.entry_count || 0);
        const payoutInfo = getPayoutSummary(contest);
        const isExpanded = expandedContests[contest.contest_id];
        const entries = entriesMap[contest.contest_id] || [];
        const isLoadingEntries = loadingEntries[contest.contest_id];
        const liveData = liveDataMap[contest.contest_id];
        const isLiveLoading = loadingLive[contest.contest_id];

        // Count how many entries have lineups assigned
        const assignedCount = Math.min(contest.entry_count || 0, currentLineups.length);

        return (
          <div
            key={contest.contest_id}
            className="rounded-lg border border-gray-800 bg-gray-900"
          >
            {/* Card header */}
            <div className="p-4 sm:p-5">
              <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3 mb-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <Trophy className="w-4 h-4 text-amber-400 shrink-0" />
                    <h2 className="text-base font-bold text-gray-100 truncate">
                      {contest.contest_name}
                    </h2>
                  </div>
                  <p className="text-xs text-gray-500 mt-0.5 ml-6">
                    ID: {contest.contest_id}
                    {liveData?.last_updated && (
                      <span className="ml-3 text-gray-600">
                        Updated {new Date(liveData.last_updated).toLocaleTimeString()}
                      </span>
                    )}
                  </p>
                </div>
                <div className="flex items-center gap-2 shrink-0 sm:ml-3">
                  <button
                    onClick={() => handleCheckSwaps(contest)}
                    disabled={loadingSwaps[contest.contest_id]}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-amber-600 text-white text-xs font-semibold hover:bg-amber-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {loadingSwaps[contest.contest_id] ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <ArrowLeftRight className="w-3.5 h-3.5" />
                    )}
                    Check Swaps
                  </button>
                  <button
                    onClick={() => handleQuickSim(contest)}
                    disabled={loadingSim[contest.contest_id]}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-blue-600 text-white text-xs font-semibold hover:bg-blue-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {loadingSim[contest.contest_id] ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <BarChart3 className="w-3.5 h-3.5" />
                    )}
                    Re-Run Sim
                  </button>
                </div>
              </div>

              {/* Stats row */}
              <div className="grid grid-cols-3 sm:grid-cols-6 gap-3">
                <div className="rounded-lg bg-gray-950 p-3">
                  <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">Entry Fee</div>
                  <div className="text-sm font-bold font-mono text-gray-100">
                    {contest.entry_fee_display || `$${fee.toFixed(2)}`}
                  </div>
                </div>
                <div className="rounded-lg bg-gray-950 p-3">
                  <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">Field Size</div>
                  <div className="text-sm font-bold font-mono text-gray-100 flex items-center gap-1">
                    <Users className="w-3.5 h-3.5 text-gray-500" />
                    {contest.field_size ? contest.field_size.toLocaleString() : '--'}
                  </div>
                </div>
                <div className="rounded-lg bg-gray-950 p-3">
                  <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">Prize Pool</div>
                  <div className="text-sm font-bold font-mono text-emerald-400">
                    {contest.prize_pool ? formatCurrency(contest.prize_pool) : '--'}
                  </div>
                </div>
                <div className="rounded-lg bg-gray-950 p-3">
                  <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">Your Entries</div>
                  <div className="text-sm font-bold font-mono text-blue-400">
                    {contest.entry_count || 0}
                    {contest.max_entries_per_user && (
                      <span className="text-xs text-gray-500 font-normal ml-1">/ {contest.max_entries_per_user}</span>
                    )}
                  </div>
                </div>
                <div className="rounded-lg bg-gray-950 p-3">
                  <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">At Risk</div>
                  <div className="text-sm font-bold font-mono text-emerald-400">
                    {formatCurrency(contestAtRisk, 2)}
                  </div>
                </div>
                <div className="rounded-lg bg-gray-950 p-3">
                  <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">Top Prize</div>
                  <div className="text-sm font-bold font-mono text-amber-400">
                    {payoutInfo ? formatCurrency(payoutInfo.topPayout) : '--'}
                  </div>
                </div>
              </div>

              {/* Payout + lineup status bar */}
              <div className="flex flex-wrap items-center justify-between gap-2 mt-3 pt-3 border-t border-gray-800">
                <div className="flex flex-wrap items-center gap-2 sm:gap-4">
                  {payoutInfo && (
                    <span className="text-xs text-gray-500">
                      <span className="font-mono text-gray-400">{payoutInfo.totalPaidPositions.toLocaleString()}</span> paid positions
                    </span>
                  )}
                  <span className="flex items-center gap-1 text-xs">
                    {assignedCount >= (contest.entry_count || 0) ? (
                      <>
                        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                        <span className="text-emerald-400">
                          All {contest.entry_count} lineup{contest.entry_count !== 1 ? 's' : ''} assigned
                        </span>
                      </>
                    ) : assignedCount > 0 ? (
                      <>
                        <AlertCircle className="w-3.5 h-3.5 text-amber-400" />
                        <span className="text-amber-400">
                          {assignedCount} / {contest.entry_count} lineups assigned
                        </span>
                      </>
                    ) : (
                      <>
                        <AlertCircle className="w-3.5 h-3.5 text-red-400" />
                        <span className="text-red-400">No lineups assigned</span>
                      </>
                    )}
                  </span>
                </div>

                <button
                  onClick={() => toggleExpand(contest.contest_id)}
                  className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-200 transition-colors"
                >
                  {isExpanded ? (
                    <>
                      <ChevronDown className="w-3.5 h-3.5" />
                      Hide Entries
                    </>
                  ) : (
                    <>
                      <ChevronRight className="w-3.5 h-3.5" />
                      View Entries
                    </>
                  )}
                </button>
              </div>
            </div>

            {/* Expanded entries list */}
            {isExpanded && (
              <div className="border-t border-gray-800 px-3 sm:px-5 py-3 overflow-x-auto">
                {isLoadingEntries ? (
                  <div className="flex items-center gap-2 py-4 justify-center">
                    <Loader2 className="w-4 h-4 text-gray-500 animate-spin" />
                    <span className="text-xs text-gray-500">Loading entries...</span>
                  </div>
                ) : entries.length > 0 ? (
                  <div className="space-y-1.5 min-w-[400px]">
                    <div className="grid grid-cols-12 gap-2 text-[10px] uppercase tracking-wider text-gray-500 px-2 pb-1">
                      <div className="col-span-1">#</div>
                      <div className="col-span-3">Entry ID</div>
                      <div className="col-span-8">Assigned Lineup</div>
                    </div>
                    {entries.map((entry, idx) => {
                      const lineup = getAssignedLineup(idx);
                      return (
                        <div
                          key={entry.entry_id || idx}
                          className="grid grid-cols-12 gap-2 items-center rounded-md bg-gray-950 px-2 py-2 text-xs"
                        >
                          <div className="col-span-1 text-gray-500 font-mono">{idx + 1}</div>
                          <div className="col-span-3 font-mono text-gray-300">{entry.entry_id || entry.EntryId || '--'}</div>
                          <div className="col-span-8">
                            {lineup ? (
                              <div className="flex items-center gap-1.5">
                                <CheckCircle2 className="w-3 h-3 text-emerald-400 shrink-0" />
                                <span className="text-gray-300 font-mono text-[11px] truncate">
                                  {lineup.players
                                    ? lineup.players.map(p => p.name?.split(' ').pop() || p.Name?.split(' ').pop()).join(', ')
                                    : 'Lineup assigned'}
                                </span>
                              </div>
                            ) : (
                              <span className="text-gray-600 italic">No lineup assigned</span>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="text-center py-4">
                    <span className="text-xs text-gray-500">
                      {contest.entry_count || 0} entr{(contest.entry_count || 0) !== 1 ? 'ies' : 'y'} in this contest
                    </span>
                  </div>
                )}
              </div>
            )}

            {/* Late Swap Results */}
            {swapError[contest.contest_id] && (
              <div className="border-t border-gray-800 px-5 py-3">
                <div className="flex items-center gap-2 text-sm text-red-400">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  {swapError[contest.contest_id]}
                </div>
              </div>
            )}
            {swapResults[contest.contest_id] && (
              <div className="border-t border-gray-800 px-5 py-4">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-semibold text-gray-200 flex items-center gap-2">
                    <ArrowLeftRight className="w-4 h-4 text-amber-400" />
                    Late Swap Results
                  </h3>
                  <button
                    onClick={() => setSwapResults(prev => ({ ...prev, [contest.contest_id]: null }))}
                    className="text-gray-500 hover:text-gray-300 transition-colors"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
                {swapResults[contest.contest_id].map((result, rIdx) => {
                  if (result.error) {
                    return (
                      <div key={rIdx} className="rounded-md bg-red-900/20 border border-red-800 px-3 py-2 mb-2 text-xs text-red-400">
                        Entry {result.entry_id}: {result.error}
                      </div>
                    );
                  }
                  const hasSwaps = result.swaps && result.swaps.length > 0;
                  return (
                    <div key={rIdx} className="rounded-md bg-gray-950 border border-gray-800 px-3 py-3 mb-2">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-xs font-mono text-gray-400">
                          Entry {result.entry_id}
                        </span>
                        <div className="flex items-center gap-3 text-xs">
                          <span className="text-gray-500">
                            Salary: <span className="font-mono text-gray-300">${(result.total_salary || 0).toLocaleString()}</span>
                          </span>
                          <span className="text-gray-500">
                            Proj: <span className="font-mono text-emerald-400">{(result.total_median || 0).toFixed(1)}</span>
                          </span>
                        </div>
                      </div>
                      {hasSwaps ? (
                        <div className="space-y-1.5">
                          {result.swaps.map((swap, sIdx) => (
                            <div key={sIdx} className="flex items-center gap-2 text-xs">
                              <span className="text-red-400 line-through">{swap.out}</span>
                              <ArrowRight className="w-3 h-3 text-gray-600" />
                              <span className="text-emerald-400 font-medium">{swap.in_player}</span>
                              <span className="text-gray-600">|</span>
                              <span className="text-gray-500">{swap.reason}</span>
                              <span className={`font-mono ${swap.pts_diff >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                {swap.pts_diff >= 0 ? '+' : ''}{swap.pts_diff.toFixed(1)} pts
                              </span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="flex items-center gap-1.5 text-xs text-emerald-400">
                          <CheckCircle2 className="w-3 h-3" />
                          All players active - no swaps needed
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}

            {/* Quick Sim Results */}
            {simError[contest.contest_id] && (
              <div className="border-t border-gray-800 px-5 py-3">
                <div className="flex items-center gap-2 text-sm text-red-400">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  {simError[contest.contest_id]}
                </div>
              </div>
            )}
            {simResults[contest.contest_id] && (
              <div className="border-t border-gray-800 px-5 py-4">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-semibold text-gray-200 flex items-center gap-2">
                    <BarChart3 className="w-4 h-4 text-blue-400" />
                    Simulation Results
                    <span className="text-[10px] font-normal text-gray-500 ml-1">
                      ({simResults[contest.contest_id].overall ? `${(simResults[contest.contest_id].elapsed_seconds || 0).toFixed(1)}s` : ''})
                    </span>
                  </h3>
                  <button
                    onClick={() => setSimResults(prev => ({ ...prev, [contest.contest_id]: null }))}
                    className="text-gray-500 hover:text-gray-300 transition-colors"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
                {(() => {
                  const sim = simResults[contest.contest_id];
                  const overall = sim.overall || {};
                  return (
                    <>
                      {/* Overall stats */}
                      <div className="grid grid-cols-3 sm:grid-cols-6 gap-2 mb-3">
                        <div className="rounded-md bg-gray-950 border border-gray-800 p-2 text-center">
                          <div className="text-[9px] uppercase tracking-wider text-gray-500 mb-0.5">Avg ROI</div>
                          <div className={`text-sm font-bold font-mono ${overall.avg_roi >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            {overall.avg_roi >= 0 ? '+' : ''}{overall.avg_roi}%
                          </div>
                        </div>
                        <div className="rounded-md bg-gray-950 border border-gray-800 p-2 text-center">
                          <div className="text-[9px] uppercase tracking-wider text-gray-500 mb-0.5">Cash Rate</div>
                          <div className="text-sm font-bold font-mono text-gray-100">
                            {overall.cash_rate}%
                          </div>
                        </div>
                        <div className="rounded-md bg-gray-950 border border-gray-800 p-2 text-center">
                          <div className="text-[9px] uppercase tracking-wider text-gray-500 mb-0.5">Win Rate</div>
                          <div className="text-sm font-bold font-mono text-gray-100">
                            {overall.win_rate}%
                          </div>
                        </div>
                        <div className="rounded-md bg-gray-950 border border-gray-800 p-2 text-center">
                          <div className="text-[9px] uppercase tracking-wider text-gray-500 mb-0.5">P25 ROI</div>
                          <div className={`text-sm font-bold font-mono ${overall.p25_roi >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            {overall.p25_roi >= 0 ? '+' : ''}{overall.p25_roi}%
                          </div>
                        </div>
                        <div className="rounded-md bg-gray-950 border border-gray-800 p-2 text-center">
                          <div className="text-[9px] uppercase tracking-wider text-gray-500 mb-0.5">P75 ROI</div>
                          <div className={`text-sm font-bold font-mono ${overall.p75_roi >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            {overall.p75_roi >= 0 ? '+' : ''}{overall.p75_roi}%
                          </div>
                        </div>
                        <div className="rounded-md bg-gray-950 border border-gray-800 p-2 text-center">
                          <div className="text-[9px] uppercase tracking-wider text-gray-500 mb-0.5">Top ROI</div>
                          <div className="text-sm font-bold font-mono text-amber-400">
                            +{overall.top_roi}%
                          </div>
                        </div>
                      </div>

                      {/* Per-lineup breakdown */}
                      {sim.per_lineup && sim.per_lineup.length > 0 && (
                        <div className="space-y-1">
                          <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">Per-Lineup Breakdown</div>
                          <div className="grid grid-cols-12 gap-1 text-[10px] uppercase tracking-wider text-gray-600 px-2">
                            <div className="col-span-1">#</div>
                            <div className="col-span-2 text-right">Avg ROI</div>
                            <div className="col-span-2 text-right">Cash %</div>
                            <div className="col-span-2 text-right">Avg Profit</div>
                            <div className="col-span-2 text-right">Median</div>
                            <div className="col-span-3 text-right">P10 / P90</div>
                          </div>
                          {sim.per_lineup.map((lu, luIdx) => (
                            <div key={luIdx} className="grid grid-cols-12 gap-1 rounded-md bg-gray-950 px-2 py-1.5 text-xs font-mono">
                              <div className="col-span-1 text-gray-500">{luIdx + 1}</div>
                              <div className={`col-span-2 text-right ${lu.avg_roi >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                {lu.avg_roi >= 0 ? '+' : ''}{lu.avg_roi}%
                              </div>
                              <div className="col-span-2 text-right text-gray-300">{lu.cash_rate}%</div>
                              <div className={`col-span-2 text-right ${lu.avg_profit >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                ${lu.avg_profit?.toFixed(0) || '0'}
                              </div>
                              <div className={`col-span-2 text-right ${lu.median_profit >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                ${lu.median_profit?.toFixed(0) || '0'}
                              </div>
                              <div className="col-span-3 text-right text-gray-400">
                                ${lu.p10_profit?.toFixed(0) || '0'} / ${lu.p90_profit?.toFixed(0) || '0'}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  );
                })()}
              </div>
            )}

            {/* ── Live Tracking Sections ────────────────────────────── */}

            {/* Loading indicator for live data (only show when no data yet) */}
            {isLiveLoading && !liveData && (
              <div className="border-t border-gray-800 px-5 py-3 flex items-center gap-2 justify-center">
                <Loader2 className="w-3.5 h-3.5 text-gray-500 animate-spin" />
                <span className="text-[10px] text-gray-500">Loading live data...</span>
              </div>
            )}

            {/* Leaderboard */}
            <CollapsibleSection
              title="Leaderboard"
              icon={Trophy}
              isOpen={expandedLeaderboards[contest.contest_id] || false}
              onToggle={() => toggleLiveSection(contest.contest_id, setExpandedLeaderboards, expandedLeaderboards)}
              badge={liveData ? `${liveData.entries_scoring?.filter(e => e.payout > 0).length || 0} ITM` : null}
            >
              <LeaderboardSection liveData={liveData} />
            </CollapsibleSection>

            {/* Ownership */}
            <CollapsibleSection
              title="Ownership"
              icon={BarChart3}
              isOpen={expandedOwnership[contest.contest_id] || false}
              onToggle={() => toggleLiveSection(contest.contest_id, setExpandedOwnership, expandedOwnership)}
              badge={liveData ? `Top ${liveData.ownership?.length || 0}` : null}
            >
              <OwnershipSection liveData={liveData} userPlayerNames={userPlayerNames} />
            </CollapsibleSection>

            {/* Stacks */}
            <CollapsibleSection
              title="Stacks"
              icon={Layers}
              isOpen={expandedStacks[contest.contest_id] || false}
              onToggle={() => toggleLiveSection(contest.contest_id, setExpandedStacks, expandedStacks)}
              badge={liveData ? `${liveData.stacks?.length || 0}` : null}
            >
              <StackSection liveData={liveData} />
            </CollapsibleSection>
          </div>
        );
      })}
    </div>
  );
}
