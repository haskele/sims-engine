import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { PlayCircle, BarChart3, TrendingUp, DollarSign, Target, Activity, AlertCircle, Trophy, Users, Upload, Loader2, XCircle, Download, Edit3, Check, ChevronDown, ChevronUp, Settings2, Briefcase } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import { api, AbortError } from '../api/client';
import { formatCurrency, formatDecimal, formatPct } from '../utils/formatting';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts';

const CustomTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 shadow-xl">
        <p className="text-xs font-mono text-gray-200">{label} ROI</p>
        <p className="text-xs font-mono text-blue-400">{payload[0].value} sims</p>
      </div>
    );
  }
  return null;
};

function roiColor(val) {
  if (val >= 50) return '#22c55e';
  if (val >= 0) return '#10b981';
  if (val >= -50) return '#f59e0b';
  return '#ef4444';
}

const SIM_LOADING_STAGES = [
  { pct: 0,  icon: '\u26BE', text: 'Warming up the bullpen...' },
  { pct: 12, icon: '\uD83D\uDCB0', text: 'Generating 1,000 opponents who all have the same lineup...' },
  { pct: 25, icon: '\uD83E\uDD16', text: 'Simulating the guy who stacks MIN/COL at Coors every slate...' },
  { pct: 38, icon: '\uD83D\uDCA8', text: 'Running the numbers... your "chalk" lineup is in 47% of fields' },
  { pct: 52, icon: '\uD83D\uDCC8', text: 'Your ceiling game just hit... in 3 out of 10,000 sims' },
  { pct: 65, icon: '\uD83E\uDD1E', text: 'Calculating the odds your SP gets pulled in the 4th...' },
  { pct: 78, icon: '\uD83D\uDD25', text: 'Your bring-back hitter just went 4-for-4 in sim #7,241' },
  { pct: 90, icon: '\uD83D\uDCCA', text: 'Crunching final numbers... your optimizer says "good luck"' },
  { pct: 97, icon: '\u2705', text: 'Wrapping up... moment of truth incoming' },
];

function SimLoadingDisplay({ progress }) {
  const stage = [...SIM_LOADING_STAGES].reverse().find(s => progress >= s.pct) || SIM_LOADING_STAGES[0];

  return (
    <div className="flex flex-col items-center justify-center h-96 px-8">
      <div className="text-5xl mb-6 animate-bounce" style={{ animationDuration: '1.5s' }}>
        {stage.icon}
      </div>
      <div className="w-full max-w-md mb-4">
        <div className="h-2.5 bg-gray-800 rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-700 ease-out"
            style={{
              width: `${Math.min(progress, 100)}%`,
              background: progress < 50
                ? 'linear-gradient(90deg, #3b82f6, #6366f1)'
                : progress < 85
                ? 'linear-gradient(90deg, #6366f1, #8b5cf6)'
                : 'linear-gradient(90deg, #8b5cf6, #22c55e)',
            }}
          />
        </div>
        <div className="flex justify-between mt-1.5">
          <span className="text-[10px] font-mono text-gray-600">{Math.round(progress)}%</span>
          <span className="text-[10px] font-mono text-gray-600">Simulating all contests...</span>
        </div>
      </div>
      <p className="text-sm text-gray-400 text-center max-w-sm transition-opacity duration-500">
        {stage.text}
      </p>
    </div>
  );
}

function simStorageKey(userId, date, slateId, buildId) {
  return `dfs-sim-results-${userId}-${date}-${slateId}-b${buildId || 0}`;
}

function saveSimResults(userId, date, slateId, buildId, data) {
  if (!userId || !date || !slateId) return;
  try { localStorage.setItem(simStorageKey(userId, date, slateId, buildId), JSON.stringify(data)); }
  catch { /* storage full */ }
}

function loadSimResults(userId, date, slateId, buildId) {
  if (!userId || !date || !slateId) return null;
  try {
    const raw = localStorage.getItem(simStorageKey(userId, date, slateId, buildId));
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

export default function Simulator() {
  const { site, selectedSlate, selectedDate, userId, getCurrentBuild, currentBuildIndex, uploadedContests, playerExposures, setPlayerExposures, stackExposures, setStackExposures } = useApp();
  const currentBuild = getCurrentBuild();
  const buildId = currentBuild?.id || currentBuildIndex;
  const lineups = currentBuild?.lineups || [];

  // Contests
  const [contests, setContests] = useState([]);
  const [hasUploadedEntries, setHasUploadedEntries] = useState(false);
  const [loadingContests, setLoadingContests] = useState(true);
  const [manualEntryFee, setManualEntryFee] = useState(20);
  const [manualFieldSize, setManualFieldSize] = useState(1000);

  // Sim controls (persisted)
  const [numSims, setNumSimsRaw] = useState(() => {
    try { return parseInt(localStorage.getItem('dfs-sim-count'), 10) || 10000; } catch { return 10000; }
  });
  const setNumSims = (v) => { setNumSimsRaw(v); localStorage.setItem('dfs-sim-count', String(v)); };
  const [poolVariance, setPoolVarianceRaw] = useState(() => {
    try { return parseInt(localStorage.getItem('dfs-pool-variance'), 10) ?? 30; } catch { return 30; }
  });
  const setPoolVariance = (v) => { setPoolVarianceRaw(v); localStorage.setItem('dfs-pool-variance', String(v)); };
  const [poolStrategy, setPoolStrategyRaw] = useState(() => {
    try { return localStorage.getItem('dfs-pool-strategy') || 'ownership'; } catch { return 'ownership'; }
  });
  const setPoolStrategy = (v) => { setPoolStrategyRaw(v); localStorage.setItem('dfs-pool-strategy', v); };
  const [allowDuplicates, setAllowDuplicatesRaw] = useState(() => {
    try { return localStorage.getItem('dfs-allow-dup-lineups') === 'true'; } catch { return false; }
  });
  const setAllowDuplicates = (v) => { setAllowDuplicatesRaw(v); localStorage.setItem('dfs-allow-dup-lineups', String(v)); };
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Portfolio results
  const [portfolioResults, setPortfolioResults] = useState(null);
  const [expandedContest, setExpandedContest] = useState(null);
  const [resultSort, setResultSort] = useState('avg_roi');
  const [resultSortDir, setResultSortDir] = useState('desc');
  const [expandedLineup, setExpandedLineup] = useState(null);

  // Entry assignments (keyed by contest_id -> {entry_id: lineup_index})
  const [allAssignments, setAllAssignments] = useState({});
  const [editingEntry, setEditingEntry] = useState(null);
  const [exporting, setExporting] = useState(false);

  // Exposure tab
  const [exposureTab, setExposureTab] = useState('players'); // 'players' | 'teamStacks'
  const [exposureSearch, setExposureSearch] = useState('');
  const [exposureFilter, setExposureFilter] = useState('all'); // 'all' | 'pitchers' | 'hitters'

  // Loading progress
  const [simProgress, setSimProgress] = useState(0);
  const progressRef = useRef(null);
  const abortRef = useRef(null);

  useEffect(() => {
    return () => {
      if (abortRef.current) abortRef.current.abort();
      if (progressRef.current) clearInterval(progressRef.current);
    };
  }, []);

  // Load contests
  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoadingContests(true);
      try {
        const status = await api.getDkEntriesStatus();
        if (cancelled) return;
        if (status.uploaded) {
          setHasUploadedEntries(true);
          const data = await api.getDkContests();
          if (cancelled) return;
          if (Array.isArray(data) && data.length > 0) {
            setContests(data);
            setLoadingContests(false);
            return;
          }
        }
      } catch { /* server unavailable */ }

      if (!cancelled && uploadedContests.length > 0) {
        setHasUploadedEntries(true);
        setContests(uploadedContests);
      }
      if (!cancelled) setLoadingContests(false);
    }
    load();
    return () => { cancelled = true; };
  }, [uploadedContests]);

  // Restore saved results on mount / slate+build change
  useEffect(() => {
    const saved = loadSimResults(userId, selectedDate, selectedSlate?.slate_id, buildId);
    if (saved) {
      setPortfolioResults(saved.portfolioResults || null);
      setAllAssignments(saved.allAssignments || {});
    } else {
      setPortfolioResults(null);
      setAllAssignments({});
    }
  }, [userId, selectedDate, selectedSlate?.slate_id, buildId]);

  // Save results when they change
  useEffect(() => {
    if (portfolioResults) {
      saveSimResults(userId, selectedDate, selectedSlate?.slate_id, buildId, {
        portfolioResults,
        allAssignments,
      });
    }
  }, [portfolioResults, allAssignments, userId, selectedDate, selectedSlate?.slate_id, buildId]);

  const handleCancel = useCallback(() => {
    if (abortRef.current) { abortRef.current.abort(); abortRef.current = null; }
    if (progressRef.current) clearInterval(progressRef.current);
    setSimProgress(0);
    setRunning(false);
  }, []);

  const handleRun = async () => {
    if (lineups.length === 0) return;

    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setRunning(true);
    setError(null);
    setPortfolioResults(null);
    setAllAssignments({});
    setSimProgress(0);

    // Estimate based on ~3s per 10k sims per contest (post-numpy optimization)
    // Contests run in parallel so use max(1, ceil(contests/2)) as multiplier
    const parallelFactor = Math.max(1, Math.ceil(Math.max(contests.length, 1) / 2));
    const estimatedSeconds = Math.max(8, (numSims / 10000) * 3 * parallelFactor);
    const startTime = Date.now();
    if (progressRef.current) clearInterval(progressRef.current);
    progressRef.current = setInterval(() => {
      const elapsed = (Date.now() - startTime) / 1000;
      // Linear progress up to 90%, then slow crawl to 97%
      const linearPct = (elapsed / estimatedSeconds) * 90;
      const pct = linearPct <= 90
        ? linearPct
        : 90 + 7 * (1 - Math.exp(-0.3 * (elapsed - estimatedSeconds)));
      setSimProgress(Math.min(pct, 97));
    }, 300);

    try {
      const userLineups = lineups.map(lu =>
        lu.players.map(p => ({
          name: p.name,
          position: p.position || p.rosterPosition,
          salary: p.salary,
          team: p.team,
          dk_id: p.dk_id || null,
        }))
      );

      let data;

      if (hasUploadedEntries && contests.length > 0) {
        data = await api.runPortfolioSim({
          sim_count: numSims,
          site,
          slate_id: selectedSlate?.slate_id || null,
          user_lineups: userLineups,
          pool_variance: poolVariance / 100,
          pool_strategy: poolStrategy,
          target_date: selectedDate || null,
          allow_cross_contest_duplicates: allowDuplicates,
          contests: contests.map(c => ({
            contest_id: c.contest_id,
            contest_name: c.contest_name,
            entry_fee: c.entry_fee,
            field_size: c.field_size,
            max_entries_per_user: c.max_entries_per_user,
            prize_pool: c.prize_pool,
            payout_structure: c.payout_structure,
            game_type: c.game_type || 'classic',
            entry_count: c.entry_count || 0,
            entry_ids: c.entry_ids || [],
          })),
        }, controller.signal);
      } else {
        // No uploaded entries — single inline sim
        const contestConfig = {
          entry_fee: manualEntryFee,
          field_size: manualFieldSize,
          game_type: 'classic',
          max_entries: 150,
          payout_structure: [],
        };
        const inline = await api.runInlineSimulation({
          sim_count: numSims,
          site,
          slate_id: selectedSlate?.slate_id || null,
          contest_config: contestConfig,
          user_lineups: userLineups,
          pool_variance: poolVariance / 100,
          pool_strategy: poolStrategy,
        }, controller.signal);
        // Wrap inline result as portfolio-like structure
        data = {
          portfolio: {
            total_contests: 1,
            total_entries: userLineups.length,
            total_investment: manualEntryFee * userLineups.length,
            expected_profit: (inline.overall?.avg_roi || 0) / 100 * manualEntryFee * userLineups.length,
            portfolio_roi: inline.overall?.avg_roi || 0,
            avg_cash_rate: inline.overall?.cash_rate || 0,
            avg_top_10_rate: inline.overall?.top_10_rate || 0,
            avg_win_rate: inline.overall?.win_rate || 0,
          },
          lineup_exposure: [],
          contests: [{
            ...inline,
            contest_id: 'manual',
            contest_name: `Manual ($${manualEntryFee} / ${manualFieldSize} field)`,
            entry_count: 0,
            entry_fee: manualEntryFee,
          }],
        };
      }

      setPortfolioResults(data);

      // Collect assignments from all contests
      const assignments = {};
      for (const cr of (data.contests || [])) {
        if (cr.entry_assignments) {
          assignments[cr.contest_id] = cr.entry_assignments;
        }
      }
      setAllAssignments(assignments);

    } catch (err) {
      if (err instanceof AbortError || err.name === 'AbortError') return;
      setError(err.message || 'Simulation failed');
    } finally {
      if (progressRef.current) clearInterval(progressRef.current);
      setSimProgress(100);
      if (abortRef.current === controller) abortRef.current = null;
      setRunning(false);
    }
  };

  const handleResultSort = (key) => {
    if (resultSort === key) setResultSortDir(d => d === 'desc' ? 'asc' : 'desc');
    else { setResultSort(key); setResultSortDir('desc'); }
  };

  const handleEntryAssignmentChange = async (contestId, entryId, lineupIndex) => {
    const updated = { ...allAssignments };
    if (!updated[contestId]) updated[contestId] = {};
    updated[contestId][entryId] = lineupIndex;
    setAllAssignments(updated);
    setEditingEntry(null);

    try { await api.updateEntryLineup(contestId, entryId, lineupIndex); }
    catch { /* local state is primary */ }
  };

  const handleExportAll = async () => {
    setExporting(true);
    try {
      const csvText = await api.exportAllCSV();
      const blob = new Blob([csvText], { type: 'text/csv' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'DKLineups_Portfolio.csv';
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.message || 'Export failed');
    } finally {
      setExporting(false);
    }
  };

  const lineupPlayersFull = (lineupIdx) => {
    if (lineupIdx < 0 || lineupIdx >= lineups.length) return [];
    const lu = lineups[lineupIdx];
    if (!lu?.players?.length) return [];
    return lu.players.map(p => ({
      name: p.name?.split(' ').pop() || '?',
      fullName: p.name || '?',
      pos: p.rosterPosition || p.position || '',
      team: p.team || '',
    }));
  };

  // Compute assigned lineup indices (weighted by how many entries each is assigned to)
  const assignedLineupUsage = useMemo(() => {
    if (!portfolioResults || !allAssignments) return {};
    const usage = {};
    for (const contestAssigns of Object.values(allAssignments)) {
      for (const luIdx of Object.values(contestAssigns)) {
        usage[luIdx] = (usage[luIdx] || 0) + 1;
      }
    }
    return usage;
  }, [portfolioResults, allAssignments]);

  const totalAssignedEntries = useMemo(() =>
    Object.values(assignedLineupUsage).reduce((s, c) => s + c, 0),
  [assignedLineupUsage]);

  // Player exposure across assigned entries
  const simPlayerExposure = useMemo(() => {
    if (totalAssignedEntries === 0) return [];
    const pitcherPos = new Set(['P', 'SP', 'RP']);
    const countMap = {};
    const metaMap = {};
    for (const [luIdxStr, entryCount] of Object.entries(assignedLineupUsage)) {
      const luIdx = parseInt(luIdxStr);
      if (luIdx < 0 || luIdx >= lineups.length) continue;
      const lu = lineups[luIdx];
      if (!lu?.players) continue;
      const seen = new Set();
      lu.players.forEach(p => {
        if (!seen.has(p.name)) {
          seen.add(p.name);
          countMap[p.name] = (countMap[p.name] || 0) + entryCount;
          if (!metaMap[p.name]) {
            metaMap[p.name] = {
              position: p.rosterPosition || p.position || '',
              team: p.team || '',
              salary: p.salary || 0,
              isPitcher: (p.rosterPosition || p.position || '').split('/').some(pos => pitcherPos.has(pos.trim())),
            };
          }
        }
      });
    }
    return Object.entries(countMap)
      .map(([name, count]) => ({
        name,
        count,
        pct: (count / totalAssignedEntries) * 100,
        ...metaMap[name],
        minExp: playerExposures[name]?.min ?? 0,
        maxExp: playerExposures[name]?.max ?? 100,
      }))
      .sort((a, b) => b.pct - a.pct);
  }, [assignedLineupUsage, totalAssignedEntries, lineups, playerExposures]);

  // Team stack exposure across assigned entries
  const simTeamStackExposure = useMemo(() => {
    if (totalAssignedEntries === 0) return [];
    const pitcherPos = new Set(['P', 'SP', 'RP']);
    const teamStats = {};
    for (const [luIdxStr, entryCount] of Object.entries(assignedLineupUsage)) {
      const luIdx = parseInt(luIdxStr);
      if (luIdx < 0 || luIdx >= lineups.length) continue;
      const lu = lineups[luIdx];
      if (!lu?.players) continue;
      const teamCounts = {};
      lu.players.forEach(p => {
        const pos = p.rosterPosition || p.position || '';
        if (p.team && !pos.split('/').some(ps => pitcherPos.has(ps.trim()))) {
          teamCounts[p.team] = (teamCounts[p.team] || 0) + 1;
        }
      });
      for (const [team, count] of Object.entries(teamCounts)) {
        if (!teamStats[team]) teamStats[team] = { stack3: 0, stack4: 0, stack5: 0 };
        if (count >= 3) teamStats[team].stack3 += entryCount;
        if (count >= 4) teamStats[team].stack4 += entryCount;
        if (count >= 5) teamStats[team].stack5 += entryCount;
      }
    }
    return Object.entries(teamStats)
      .map(([team, stats]) => ({
        team,
        stack3: stats.stack3,
        stack4: stats.stack4,
        stack5: stats.stack5,
        stack3Pct: (stats.stack3 / totalAssignedEntries) * 100,
        stack4Pct: (stats.stack4 / totalAssignedEntries) * 100,
        stack5Pct: (stats.stack5 / totalAssignedEntries) * 100,
      }))
      .sort((a, b) => b.stack4Pct - a.stack4Pct || b.stack3Pct - a.stack3Pct);
  }, [assignedLineupUsage, totalAssignedEntries, lineups]);

  const portfolio = portfolioResults?.portfolio;
  const contestResultsList = portfolioResults?.contests || [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-100">Simulator</h1>
          <p className="text-sm text-gray-500 mt-0.5">Portfolio simulation engine</p>
        </div>
        {portfolioResults && hasUploadedEntries && (
          <button
            onClick={handleExportAll}
            disabled={exporting}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-500 disabled:opacity-50 transition-colors"
          >
            {exporting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
            Export All to DK
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Setup panel */}
        <div className="space-y-4">
          <h2 className="text-sm font-semibold text-gray-300">Setup</h2>

          {/* Lineups status */}
          <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold text-gray-300">Lineups</span>
              <span className="text-sm font-mono font-bold text-blue-400">{lineups.length}</span>
            </div>
            {lineups.length === 0 ? (
              <p className="text-xs text-amber-400 flex items-center gap-1.5">
                <AlertCircle className="w-3.5 h-3.5" />
                Build lineups first on the Lineup Builder tab
              </p>
            ) : (
              <p className="text-xs text-gray-500">From {currentBuild?.name || 'Build 1'}</p>
            )}
          </div>

          {/* Contest portfolio summary */}
          {loadingContests ? (
            <div className="rounded-lg border border-gray-800 bg-gray-900 p-4 flex items-center justify-center gap-2">
              <Loader2 className="w-4 h-4 text-gray-500 animate-spin" />
              <span className="text-xs text-gray-500">Loading contests...</span>
            </div>
          ) : hasUploadedEntries && contests.length > 0 ? (
            <div className="rounded-lg border border-gray-800 bg-gray-900 p-4 space-y-3">
              <div className="flex items-center gap-2">
                <Briefcase className="w-3.5 h-3.5 text-blue-400" />
                <span className="text-xs font-semibold text-gray-300">Portfolio</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div className="rounded-md bg-gray-950 p-2.5">
                  <div className="text-[9px] uppercase tracking-wider text-gray-500 mb-0.5">Contests</div>
                  <div className="text-sm font-bold font-mono text-gray-100">{contests.length}</div>
                </div>
                <div className="rounded-md bg-gray-950 p-2.5">
                  <div className="text-[9px] uppercase tracking-wider text-gray-500 mb-0.5">Total Entries</div>
                  <div className="text-sm font-bold font-mono text-blue-400">
                    {contests.reduce((sum, c) => sum + (c.entry_count || 0), 0)}
                  </div>
                </div>
                <div className="rounded-md bg-gray-950 p-2.5">
                  <div className="text-[9px] uppercase tracking-wider text-gray-500 mb-0.5">Investment</div>
                  <div className="text-sm font-bold font-mono text-gray-100">
                    {formatCurrency(contests.reduce((sum, c) => {
                      const fee = typeof c.entry_fee === 'number' ? c.entry_fee : parseFloat(c.entry_fee) || 0;
                      return sum + fee * (c.entry_count || 0);
                    }, 0))}
                  </div>
                </div>
                <div className="rounded-md bg-gray-950 p-2.5">
                  <div className="text-[9px] uppercase tracking-wider text-gray-500 mb-0.5">Prize Pools</div>
                  <div className="text-sm font-bold font-mono text-emerald-400">
                    {formatCurrency(contests.reduce((sum, c) => sum + (c.prize_pool || 0), 0))}
                  </div>
                </div>
              </div>
              {/* Contest list */}
              <div className="space-y-1 max-h-48 overflow-y-auto">
                {contests.map(c => {
                  const fee = typeof c.entry_fee === 'number' ? c.entry_fee : parseFloat(c.entry_fee) || 0;
                  return (
                    <div key={c.contest_id} className="flex items-center justify-between rounded-md bg-gray-950 px-2.5 py-1.5">
                      <div className="flex items-center gap-1.5 min-w-0">
                        <Trophy className="w-3 h-3 text-gray-600 shrink-0" />
                        <span className="text-[10px] text-gray-400 truncate">{c.contest_name}</span>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <span className="text-[10px] font-mono text-blue-400">{c.entry_count || 0}e</span>
                        <span className="text-[10px] font-mono text-gray-500">${fee.toFixed(0)}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : (
            <div className="rounded-lg border border-gray-800 bg-gray-900 p-4 space-y-3">
              <span className="text-xs font-semibold text-gray-300">Contest Config</span>
              <div className="rounded-md bg-amber-950/20 border border-amber-900/40 px-3 py-2">
                <p className="text-[10px] text-amber-400 flex items-center gap-1.5 mb-1">
                  <Upload className="w-3 h-3" />
                  No DK entries uploaded
                </p>
                <p className="text-[10px] text-gray-500">
                  Upload a DK entries CSV on the{' '}
                  <Link to="/contests" className="text-blue-400 hover:text-blue-300 underline">Contests page</Link>{' '}
                  for portfolio sim, or configure manually.
                </p>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-gray-400">Entry Fee ($)</span>
                <input type="number" value={manualEntryFee} onChange={(e) => setManualEntryFee(Number(e.target.value))}
                  className="w-20 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs font-mono text-gray-200 text-right focus:outline-none focus:border-blue-500" min={1} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-gray-400">Field Size</span>
                <input type="number" value={manualFieldSize} onChange={(e) => setManualFieldSize(Number(e.target.value))}
                  className="w-24 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs font-mono text-gray-200 text-right focus:outline-none focus:border-blue-500" min={10} step={100} />
              </div>
            </div>
          )}

          {/* Sim count */}
          <div className="rounded-lg border border-gray-800 bg-gray-900 p-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-gray-300">Simulations per Contest</span>
              <span className="text-sm font-mono font-bold text-blue-400">{numSims.toLocaleString()}</span>
            </div>
            <input type="range" min={1000} max={50000} step={1000} value={numSims}
              onChange={(e) => setNumSims(Number(e.target.value))} className="w-full" />
            <div className="flex justify-between text-[10px] text-gray-600 font-mono">
              <span>1K</span><span>10K</span><span>25K</span><span>50K</span>
            </div>
          </div>

          {/* Pool settings */}
          <div className="rounded-lg border border-gray-800 bg-gray-900 p-4 space-y-3">
            <button onClick={() => setShowAdvanced(!showAdvanced)}
              className="w-full flex items-center justify-between text-xs font-semibold text-gray-300">
              <span className="flex items-center gap-1.5">
                <Settings2 className="w-3.5 h-3.5" />
                Opponent Pool Settings
              </span>
              {showAdvanced ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            </button>
            {showAdvanced && (
              <div className="space-y-3 pt-1">
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-[10px] text-gray-400">Pool Strategy</span>
                  </div>
                  <div className="flex gap-2">
                    {[
                      { value: 'ownership', label: 'Ownership' },
                      { value: 'archetype', label: 'Archetype Mix' },
                    ].map(opt => (
                      <button key={opt.value} onClick={() => setPoolStrategy(opt.value)}
                        className={`flex-1 px-3 py-1.5 rounded-md text-[10px] font-semibold transition-colors border ${
                          poolStrategy === opt.value
                            ? 'bg-blue-950/40 border-blue-700 text-blue-300'
                            : 'bg-gray-950 border-gray-800 text-gray-500 hover:border-gray-700'
                        }`}>
                        {opt.label}
                      </button>
                    ))}
                  </div>
                </div>
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-[10px] text-gray-400">Pool Variance</span>
                    <span className="text-xs font-mono font-bold text-blue-400">{poolVariance}%</span>
                  </div>
                  <input type="range" min={0} max={100} step={5} value={poolVariance}
                    onChange={(e) => setPoolVariance(Number(e.target.value))} className="w-full" />
                  <div className="flex justify-between text-[10px] text-gray-600 font-mono mt-1">
                    <span>Chalk</span><span>Balanced</span><span>Contrarian</span>
                  </div>
                </div>
                <div className="flex items-center justify-between pt-1">
                  <span className="text-[10px] text-gray-400">Allow duplicate lineups across contests</span>
                  <button
                    onClick={() => setAllowDuplicates(!allowDuplicates)}
                    className={`relative w-8 h-4.5 rounded-full transition-colors ${allowDuplicates ? 'bg-blue-600' : 'bg-gray-700'}`}
                  >
                    <span className={`absolute top-0.5 left-0.5 w-3.5 h-3.5 rounded-full bg-white transition-transform ${allowDuplicates ? 'translate-x-3.5' : ''}`} />
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Run / Cancel */}
          {running ? (
            <button onClick={handleCancel}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg bg-red-600 text-white font-semibold text-sm hover:bg-red-500 transition-colors">
              <XCircle className="w-4 h-4" /> Cancel Simulation
            </button>
          ) : (
            <button onClick={handleRun} disabled={lineups.length === 0}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg bg-emerald-600 text-white font-semibold text-sm hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
              <PlayCircle className="w-4 h-4" />
              {hasUploadedEntries && contests.length > 0
                ? `Simulate All ${contests.length} Contests`
                : 'Run Simulation'}
            </button>
          )}

          {error && (
            <div className="rounded-lg border border-red-800 bg-red-900/20 px-3 py-2 text-xs text-red-400">{error}</div>
          )}
        </div>

        {/* Results panel */}
        <div className="md:col-span-2 space-y-4">
          {running ? (
            <SimLoadingDisplay progress={simProgress} />
          ) : portfolioResults ? (
            <>
              {/* Portfolio summary */}
              {portfolio && (
                <div className="rounded-lg border border-blue-900/50 bg-gradient-to-r from-blue-950/40 to-gray-900 p-5">
                  <div className="flex items-center gap-2 mb-4">
                    <Briefcase className="w-4 h-4 text-blue-400" />
                    <h3 className="text-sm font-semibold text-gray-100">Portfolio Summary</h3>
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                    <div>
                      <div className="text-[9px] uppercase tracking-wider text-gray-500 mb-0.5">Avg ROI</div>
                      <div className={`text-xl font-bold font-mono ${portfolio.portfolio_roi >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {portfolio.portfolio_roi > 0 ? '+' : ''}{formatDecimal(portfolio.portfolio_roi)}%
                      </div>
                    </div>
                    <div>
                      <div className="text-[9px] uppercase tracking-wider text-gray-500 mb-0.5">Investment</div>
                      <div className="text-xl font-bold font-mono text-gray-100">{formatCurrency(portfolio.total_investment)}</div>
                    </div>
                    <div>
                      <div className="text-[9px] uppercase tracking-wider text-gray-500 mb-0.5">Expected Profit</div>
                      <div className={`text-xl font-bold font-mono ${portfolio.expected_profit >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {portfolio.expected_profit >= 0 ? '+' : ''}{formatCurrency(portfolio.expected_profit)}
                      </div>
                    </div>
                    <div>
                      <div className="text-[9px] uppercase tracking-wider text-gray-500 mb-0.5">Cash Rate</div>
                      <div className="text-xl font-bold font-mono text-blue-400">{formatDecimal(portfolio.avg_cash_rate)}%</div>
                    </div>
                    <div>
                      <div className="text-[9px] uppercase tracking-wider text-gray-500 mb-0.5">Top 10%</div>
                      <div className="text-xl font-bold font-mono text-purple-400">{formatDecimal(portfolio.avg_top_10_rate || 0)}%</div>
                    </div>
                  </div>
                  <div className="flex items-center gap-4 mt-3 text-[10px] text-gray-500">
                    <span>{portfolio.total_contests} contests</span>
                    <span>{portfolio.total_entries} entries</span>
                    <span>{numSims.toLocaleString()} sims each</span>
                  </div>
                </div>
              )}


              {/* Exposure breakdown */}
              {totalAssignedEntries > 0 && (
                <div className="rounded-lg border border-gray-800 bg-gray-900 overflow-hidden">
                  <div className="px-4 py-3 flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-gray-800">
                    <div className="flex items-center gap-2">
                      <div className="flex items-center bg-gray-950 rounded-lg p-0.5 border border-gray-800">
                        <button onClick={() => setExposureTab('players')}
                          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition-colors ${
                            exposureTab === 'players' ? 'bg-gray-800 text-white shadow-sm' : 'text-gray-400 hover:text-gray-200'
                          }`}>
                          <Users className="w-3.5 h-3.5" /> Player Exposure
                          <span className={`text-[10px] font-mono ${exposureTab === 'players' ? 'text-blue-400' : 'text-gray-500'}`}>{simPlayerExposure.length}</span>
                        </button>
                        <button onClick={() => setExposureTab('teamStacks')}
                          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition-colors ${
                            exposureTab === 'teamStacks' ? 'bg-gray-800 text-white shadow-sm' : 'text-gray-400 hover:text-gray-200'
                          }`}>
                          <Activity className="w-3.5 h-3.5" /> Team Stacks
                          <span className={`text-[10px] font-mono ${exposureTab === 'teamStacks' ? 'text-blue-400' : 'text-gray-500'}`}>{simTeamStackExposure.length}</span>
                        </button>
                      </div>
                      <span className="text-[10px] text-gray-500">{totalAssignedEntries} entries assigned</span>
                    </div>
                    {exposureTab === 'players' && (
                      <div className="flex items-center gap-2">
                        <div className="flex items-center bg-gray-950 rounded-lg p-0.5 border border-gray-800">
                          {['all', 'pitchers', 'hitters'].map(f => (
                            <button key={f} onClick={() => setExposureFilter(f)}
                              className={`px-2.5 py-1 rounded-md text-[10px] font-semibold transition-colors ${
                                exposureFilter === f ? 'bg-gray-800 text-white shadow-sm' : 'text-gray-400 hover:text-gray-200'
                              }`}>
                              {f === 'all' ? 'All' : f === 'pitchers' ? 'Pitchers' : 'Hitters'}
                            </button>
                          ))}
                        </div>
                        <input type="text" placeholder="Search..." value={exposureSearch}
                          onChange={(e) => setExposureSearch(e.target.value)}
                          className="w-36 bg-gray-800 border border-gray-700 rounded-lg px-2.5 py-1 text-xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500" />
                      </div>
                    )}
                  </div>

                  {/* Player Exposure Table */}
                  {exposureTab === 'players' && (
                    <div className="data-table-container overflow-x-auto" style={{ maxHeight: '400px' }}>
                      <table className="w-full text-left min-w-[600px]">
                        <thead>
                          <tr className="bg-gray-950">
                            <th className="px-3 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-500">Player</th>
                            <th className="px-3 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-500">Pos</th>
                            <th className="px-3 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-500">Team</th>
                            <th className="px-2 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-500 text-center">Min %</th>
                            <th className="px-2 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-500 text-center">Max %</th>
                            <th className="px-3 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-500 text-right">Actual</th>
                            <th className="px-3 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-500" style={{ minWidth: 120 }}>Exposure</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(() => {
                            let filtered = simPlayerExposure;
                            if (exposureFilter === 'pitchers') {
                              filtered = filtered.filter(p => p.isPitcher);
                            } else if (exposureFilter === 'hitters') {
                              filtered = filtered.filter(p => !p.isPitcher);
                            }
                            const q = exposureSearch.toLowerCase();
                            if (q) {
                              filtered = filtered.filter(p => p.name.toLowerCase().includes(q) || (p.team || '').toLowerCase().includes(q));
                            }
                            if (filtered.length === 0) {
                              return (
                                <tr><td colSpan={7} className="px-4 py-8 text-center text-sm text-gray-500">No players match</td></tr>
                              );
                            }
                            return filtered.map((p, i) => {
                              const isOverMax = p.pct > p.maxExp;
                              const isUnderMin = p.pct > 0 && p.pct < p.minExp;
                              const barColor = isOverMax ? 'bg-red-500' : isUnderMin ? 'bg-amber-500' : 'bg-blue-500';
                              return (
                                <tr key={p.name} className={`${i % 2 === 0 ? 'bg-gray-950' : 'bg-gray-900/50'} hover:bg-gray-800/50 transition-colors`}>
                                  <td className="px-3 py-1.5 text-xs text-gray-200">{p.name}</td>
                                  <td className="px-3 py-1.5 text-[10px] font-mono text-gray-400">{p.position}</td>
                                  <td className="px-3 py-1.5 text-[10px] font-mono text-gray-400">{p.team}</td>
                                  <td className="px-2 py-1.5 text-center">
                                    <input type="number" value={p.minExp} min={0} max={100}
                                      onChange={(e) => {
                                        const val = Math.max(0, Math.min(100, parseInt(e.target.value) || 0));
                                        setPlayerExposures(prev => ({
                                          ...prev,
                                          [p.name]: { min: val, max: prev[p.name]?.max ?? p.maxExp ?? 100 },
                                        }));
                                      }}
                                      className="w-12 bg-gray-800 border border-gray-700 rounded px-1.5 py-0.5 text-[10px] font-mono text-gray-200 text-center focus:outline-none focus:border-blue-500" />
                                  </td>
                                  <td className="px-2 py-1.5 text-center">
                                    <input type="number" value={p.maxExp} min={0} max={100}
                                      onChange={(e) => {
                                        const val = Math.max(0, Math.min(100, parseInt(e.target.value) || 0));
                                        setPlayerExposures(prev => ({
                                          ...prev,
                                          [p.name]: { min: prev[p.name]?.min ?? p.minExp ?? 0, max: val },
                                        }));
                                      }}
                                      className="w-12 bg-gray-800 border border-gray-700 rounded px-1.5 py-0.5 text-[10px] font-mono text-gray-200 text-center focus:outline-none focus:border-blue-500" />
                                  </td>
                                  <td className="px-3 py-1.5 text-right">
                                    <span className={`text-xs font-mono font-semibold ${
                                      isOverMax ? 'text-red-400' : isUnderMin ? 'text-amber-400' : p.pct > 0 ? 'text-blue-400' : 'text-gray-600'
                                    }`}>
                                      {p.pct > 0 ? formatPct(p.pct, 1) : '—'}
                                    </span>
                                  </td>
                                  <td className="px-3 py-1.5">
                                    <div className="w-full h-1.5 bg-gray-800 rounded-full overflow-hidden">
                                      <div className={`h-full ${barColor} rounded-full`} style={{ width: `${Math.min(p.pct, 100)}%` }} />
                                    </div>
                                  </td>
                                </tr>
                              );
                            });
                          })()}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {/* Team Stacks Table */}
                  {exposureTab === 'teamStacks' && (
                    <div className="data-table-container overflow-x-auto" style={{ maxHeight: '400px' }}>
                      <table className="w-full text-left min-w-[700px]">
                        <thead>
                          <tr className="bg-gray-950">
                            <th className="px-3 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-500">Team</th>
                            <th className="px-2 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-500 text-center" colSpan={3}>3-Man Stack</th>
                            <th className="px-2 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-500 text-center" colSpan={3}>4-Man Stack</th>
                            <th className="px-2 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-500 text-center" colSpan={3}>5-Man Stack</th>
                          </tr>
                          <tr className="bg-gray-950 border-t border-gray-800">
                            <th />
                            {[3, 4, 5].map(sz => (
                              <React.Fragment key={sz}>
                                <th className="px-1 pb-1.5 text-[9px] uppercase text-gray-600 text-center">Min</th>
                                <th className="px-1 pb-1.5 text-[9px] uppercase text-gray-600 text-center">Max</th>
                                <th className="px-1 pb-1.5 text-[9px] uppercase text-gray-600 text-center">Actual</th>
                              </React.Fragment>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {simTeamStackExposure.length === 0 ? (
                            <tr><td colSpan={10} className="px-4 py-8 text-center text-sm text-gray-500">No team stacks found</td></tr>
                          ) : simTeamStackExposure.map((t, i) => {
                            const se = stackExposures[t.team] || {};

                            const renderCell = (size, actualPct) => {
                              const key = `stack_${size}`;
                              const minVal = se[key]?.min ?? 0;
                              const maxVal = se[key]?.max ?? 100;
                              const isOver = actualPct > maxVal;
                              const isUnder = actualPct > 0 && actualPct < minVal;
                              return (
                                <>
                                  <td className="px-1 py-1.5 text-center">
                                    <input type="number" value={minVal} min={0} max={100}
                                      onChange={(e) => {
                                        const val = Math.max(0, Math.min(100, parseInt(e.target.value) || 0));
                                        setStackExposures(prev => ({
                                          ...prev,
                                          [t.team]: { ...prev[t.team], [key]: { min: val, max: prev[t.team]?.[key]?.max ?? 100 } },
                                        }));
                                      }}
                                      className="w-11 bg-gray-800 border border-gray-700 rounded px-1 py-0.5 text-[10px] font-mono text-gray-200 text-center focus:outline-none focus:border-blue-500" />
                                  </td>
                                  <td className="px-1 py-1.5 text-center">
                                    <input type="number" value={maxVal} min={0} max={100}
                                      onChange={(e) => {
                                        const val = Math.max(0, Math.min(100, parseInt(e.target.value) || 0));
                                        setStackExposures(prev => ({
                                          ...prev,
                                          [t.team]: { ...prev[t.team], [key]: { min: prev[t.team]?.[key]?.min ?? 0, max: val } },
                                        }));
                                      }}
                                      className="w-11 bg-gray-800 border border-gray-700 rounded px-1 py-0.5 text-[10px] font-mono text-gray-200 text-center focus:outline-none focus:border-blue-500" />
                                  </td>
                                  <td className="px-1 py-1.5 text-center">
                                    <span className={`text-[10px] font-mono font-semibold ${
                                      isOver ? 'text-red-400' : isUnder ? 'text-amber-400' : actualPct > 0 ? 'text-blue-400' : 'text-gray-600'
                                    }`}>
                                      {actualPct > 0 ? formatPct(actualPct, 0) : '—'}
                                    </span>
                                  </td>
                                </>
                              );
                            };

                            return (
                              <tr key={t.team} className={`${i % 2 === 0 ? 'bg-gray-950' : 'bg-gray-900/50'} hover:bg-gray-800/50 transition-colors`}>
                                <td className="px-3 py-1.5 text-xs font-semibold text-gray-200">{t.team}</td>
                                {renderCell(3, t.stack3Pct)}
                                {renderCell(4, t.stack4Pct)}
                                {renderCell(5, t.stack5Pct)}
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}

              {/* Per-contest results */}
              {contestResultsList.map(cr => {
                const isExpanded = expandedContest === cr.contest_id;
                const contestAssignments = allAssignments[cr.contest_id] || cr.entry_assignments || {};
                const entryIds = Object.keys(contestAssignments);

                const sortedLineups = cr.per_lineup
                  ? [...cr.per_lineup].sort((a, b) => {
                      const aVal = a[resultSort] ?? 0;
                      const bVal = b[resultSort] ?? 0;
                      return resultSortDir === 'desc' ? bVal - aVal : aVal - bVal;
                    })
                  : [];

                const chartData = cr.roi_distribution?.map(bin => ({
                  range: `${bin.bin_start > 0 ? '+' : ''}${Math.round(bin.bin_start)}%`,
                  count: bin.count,
                  color: roiColor((bin.bin_start + bin.bin_end) / 2),
                })) || [];

                const displayOverall = cr.assigned_overall || cr.overall;

                return (
                  <div key={cr.contest_id} className="rounded-lg border border-gray-800 bg-gray-900 overflow-hidden">
                    {/* Contest header - always visible */}
                    <button
                      onClick={() => setExpandedContest(isExpanded ? null : cr.contest_id)}
                      className="w-full px-4 py-3 flex items-center justify-between hover:bg-gray-800/30 transition-colors"
                    >
                      <div className="flex items-center gap-3">
                        <Trophy className="w-4 h-4 text-amber-400" />
                        <div className="text-left">
                          <div className="text-sm font-semibold text-gray-100">{cr.contest_name || 'Contest'}</div>
                          <div className="text-[10px] text-gray-500 mt-0.5">
                            {cr.entry_count || 0} entries &middot; {formatCurrency(cr.entry_fee, 0)} fee
                            {cr.field_size && <> &middot; {cr.field_size.toLocaleString()} field</>}
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-4">
                        <div className="text-right">
                          <div className={`text-sm font-bold font-mono ${(displayOverall?.avg_roi || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            {(displayOverall?.avg_roi || 0) > 0 ? '+' : ''}{formatDecimal(displayOverall?.avg_roi || 0)}%
                          </div>
                          <div className="text-[10px] text-gray-500">avg ROI</div>
                        </div>
                        <div className="text-right">
                          <div className="text-sm font-bold font-mono text-blue-400">{formatDecimal(displayOverall?.cash_rate || 0)}%</div>
                          <div className="text-[10px] text-gray-500">cash</div>
                        </div>
                        {isExpanded ? <ChevronUp className="w-4 h-4 text-gray-500" /> : <ChevronDown className="w-4 h-4 text-gray-500" />}
                      </div>
                    </button>

                    {isExpanded && (
                      <div className="border-t border-gray-800 p-4 space-y-4">
                        {/* Key metrics — show assigned-lineup metrics */}
                        <div className="grid grid-cols-4 gap-3">
                          <div className="rounded-md bg-gray-950 p-3 text-center">
                            <div className="text-[9px] uppercase tracking-wider text-gray-500 mb-1">Avg ROI</div>
                            <div className={`text-lg font-bold font-mono ${(displayOverall?.avg_roi || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                              {(displayOverall?.avg_roi || 0) > 0 ? '+' : ''}{formatDecimal(displayOverall?.avg_roi || 0)}%
                            </div>
                          </div>
                          <div className="rounded-md bg-gray-950 p-3 text-center">
                            <div className="text-[9px] uppercase tracking-wider text-gray-500 mb-1">Cash Rate</div>
                            <div className="text-lg font-bold font-mono text-blue-400">{formatDecimal(displayOverall?.cash_rate || 0)}%</div>
                          </div>
                          <div className="rounded-md bg-gray-950 p-3 text-center">
                            <div className="text-[9px] uppercase tracking-wider text-gray-500 mb-1">Win Rate</div>
                            <div className="text-lg font-bold font-mono text-amber-400">{formatPct(displayOverall?.win_rate || 0, 2)}</div>
                          </div>
                          <div className="rounded-md bg-gray-950 p-3 text-center">
                            <div className="text-[9px] uppercase tracking-wider text-gray-500 mb-1">Top 10%</div>
                            <div className="text-lg font-bold font-mono text-purple-400">
                              {formatDecimal(displayOverall?.top_10_rate || 0)}%
                            </div>
                          </div>
                        </div>

                        {/* Entry assignments */}
                        {entryIds.length > 0 && (
                          <div className="rounded-lg border border-gray-800 overflow-hidden">
                            <div className="px-3 py-2 border-b border-gray-800 flex items-center justify-between bg-gray-950">
                              <span className="text-[10px] font-semibold text-gray-400">Entry Assignments ({entryIds.length})</span>
                            </div>
                            <div className="data-table-container overflow-x-auto" style={{ maxHeight: '250px' }}>
                              <table className="w-full text-left">
                                <thead>
                                  <tr className="bg-gray-950">
                                    <th className="px-3 py-1.5 text-[10px] uppercase tracking-wider font-semibold text-gray-500">Entry</th>
                                    <th className="px-3 py-1.5 text-[10px] uppercase tracking-wider font-semibold text-gray-500">LU #</th>
                                    <th className="px-3 py-1.5 text-[10px] uppercase tracking-wider font-semibold text-gray-500">Lineup</th>
                                    <th className="px-3 py-1.5 text-[10px] uppercase tracking-wider font-semibold text-gray-500 text-right">ROI</th>
                                    <th className="px-3 py-1.5 text-[10px] uppercase tracking-wider font-semibold text-gray-500 text-center w-10"></th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {entryIds.map((entryId, i) => {
                                    const luIdx = contestAssignments[entryId] ?? 0;
                                    const luResult = cr.per_lineup?.find(r => r.lineup_index === luIdx);
                                    const isEdit = editingEntry === `${cr.contest_id}-${entryId}`;
                                    const players = lineupPlayersFull(luIdx);
                                    return (
                                      <tr key={entryId} className={`${i % 2 === 0 ? 'bg-gray-950' : 'bg-gray-900/50'} hover:bg-gray-800/50`}>
                                        <td className="px-3 py-1.5 text-[10px] font-mono text-gray-500">{entryId}</td>
                                        <td className="px-3 py-1.5">
                                          {isEdit ? (
                                            <select value={luIdx}
                                              onChange={(e) => handleEntryAssignmentChange(cr.contest_id, entryId, parseInt(e.target.value))}
                                              onBlur={() => setEditingEntry(null)} autoFocus
                                              className="bg-gray-800 border border-blue-600 rounded px-1.5 py-0.5 text-[10px] font-mono text-gray-200">
                                              {lineups.map((_, idx) => <option key={idx} value={idx}>#{idx + 1}</option>)}
                                            </select>
                                          ) : (
                                            <span className="text-[10px] font-mono font-semibold text-blue-400">#{luIdx + 1}</span>
                                          )}
                                        </td>
                                        <td className="px-3 py-1.5">
                                          <div className="flex flex-wrap gap-0.5">
                                            {players.map((p, pi) => (
                                              <span key={pi} className="inline-flex items-center gap-0.5 px-1 py-0.5 rounded bg-gray-800 text-[8px] font-mono text-gray-300" title={p.fullName}>
                                                <span className="text-gray-600">{p.pos}</span>{p.name}
                                              </span>
                                            ))}
                                          </div>
                                        </td>
                                        <td className="px-3 py-1.5 text-right">
                                          {luResult && (
                                            <span className={`text-[10px] font-mono font-semibold ${luResult.avg_roi >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                              {luResult.avg_roi > 0 ? '+' : ''}{formatDecimal(luResult.avg_roi)}%
                                            </span>
                                          )}
                                        </td>
                                        <td className="px-3 py-1.5 text-center">
                                          <button onClick={() => setEditingEntry(isEdit ? null : `${cr.contest_id}-${entryId}`)}
                                            className="p-0.5 rounded hover:bg-gray-700">
                                            {isEdit ? <Check className="w-3 h-3 text-emerald-400" /> : <Edit3 className="w-3 h-3 text-gray-600" />}
                                          </button>
                                        </td>
                                      </tr>
                                    );
                                  })}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        )}

                        {/* ROI Distribution */}
                        {chartData.length > 0 && (
                          <div>
                            <h4 className="text-[10px] font-semibold text-gray-500 mb-2 flex items-center gap-1.5">
                              <BarChart3 className="w-3 h-3" /> ROI Distribution
                            </h4>
                            <div className="h-40">
                              <ResponsiveContainer width="100%" height="100%">
                                <BarChart data={chartData} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
                                  <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                                  <XAxis dataKey="range" tick={{ fontSize: 9, fill: '#6b7280' }} axisLine={{ stroke: '#374151' }} tickLine={{ stroke: '#374151' }} />
                                  <YAxis tick={{ fontSize: 9, fill: '#6b7280' }} axisLine={{ stroke: '#374151' }} tickLine={{ stroke: '#374151' }} />
                                  <Tooltip content={<CustomTooltip />} />
                                  <Bar dataKey="count" radius={[3, 3, 0, 0]}>
                                    {chartData.map((entry, index) => <Cell key={index} fill={entry.color} />)}
                                  </Bar>
                                </BarChart>
                              </ResponsiveContainer>
                            </div>
                          </div>
                        )}

                        {/* Lineup results */}
                        {sortedLineups.length > 0 && (
                          <div className="rounded-lg border border-gray-800 overflow-hidden">
                            <div className="px-3 py-2 border-b border-gray-800 bg-gray-950">
                              <span className="text-[10px] font-semibold text-gray-400">Lineup Results ({sortedLineups.length})</span>
                            </div>
                            <div className="data-table-container overflow-x-auto" style={{ maxHeight: '300px' }}>
                              <table className="w-full text-left min-w-[500px]">
                                <thead>
                                  <tr className="bg-gray-950">
                                    {[
                                      { key: 'lineup_index', label: '#', align: '' },
                                      { key: 'avg_score', label: 'Avg Score', align: 'text-right' },
                                      { key: 'avg_roi', label: 'Avg ROI', align: 'text-right' },
                                      { key: 'cash_rate', label: 'Cash', align: 'text-right' },
                                      { key: 'top_10_rate', label: 'Top 10%', align: 'text-right' },
                                      { key: 'win_rate', label: 'Win', align: 'text-right' },
                                    ].map(col => (
                                      <th key={col.key} onClick={() => handleResultSort(col.key)}
                                        className={`px-2 py-1.5 text-[9px] uppercase tracking-wider font-semibold text-gray-500 cursor-pointer hover:text-gray-300 ${col.align}`}>
                                        {col.label}
                                        {resultSort === col.key && <span className="text-blue-400 ml-0.5">{resultSortDir === 'desc' ? '\u25BC' : '\u25B2'}</span>}
                                      </th>
                                    ))}
                                  </tr>
                                </thead>
                                <tbody>
                                  {sortedLineups.map((r, i) => {
                                    const isLuExpanded = expandedLineup === `${cr.contest_id}-${r.lineup_index}`;
                                    const players = lineupPlayersFull(r.lineup_index);
                                    return (
                                      <>
                                        <tr key={r.lineup_index}
                                          onClick={() => setExpandedLineup(isLuExpanded ? null : `${cr.contest_id}-${r.lineup_index}`)}
                                          className={`cursor-pointer ${i % 2 === 0 ? 'bg-gray-950' : 'bg-gray-900/50'} hover:bg-gray-800/50`}>
                                          <td className="px-2 py-1.5 text-[10px] text-gray-300 flex items-center gap-0.5">
                                            <ChevronDown className={`w-2.5 h-2.5 text-gray-600 transition-transform ${isLuExpanded ? 'rotate-180' : ''}`} />
                                            #{r.lineup_index + 1}
                                          </td>
                                          <td className="px-2 py-1.5 text-[10px] font-mono text-gray-200 text-right">{formatDecimal(r.avg_score)}</td>
                                          <td className="px-2 py-1.5 text-right">
                                            <span className={`text-[10px] font-mono font-semibold ${r.avg_roi >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                              {r.avg_roi > 0 ? '+' : ''}{formatDecimal(r.avg_roi)}%
                                            </span>
                                          </td>
                                          <td className="px-2 py-1.5 text-[10px] font-mono text-gray-300 text-right">{formatDecimal(r.cash_rate)}%</td>
                                          <td className="px-2 py-1.5 text-[10px] font-mono text-purple-400 text-right">{formatDecimal(r.top_10_rate || 0)}%</td>
                                          <td className="px-2 py-1.5 text-[10px] font-mono text-gray-400 text-right">{formatPct(r.win_rate, 2)}</td>
                                        </tr>
                                        {isLuExpanded && players.length > 0 && (
                                          <tr key={`${r.lineup_index}-d`} className="bg-gray-950/80">
                                            <td colSpan={6} className="px-2 py-2">
                                              <div className="flex flex-wrap gap-1">
                                                {players.map((p, pi) => (
                                                  <span key={pi} className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-gray-800 border border-gray-700">
                                                    <span className="text-[8px] font-mono text-gray-500 uppercase">{p.pos}</span>
                                                    <span className="text-[10px] font-semibold text-gray-200">{p.fullName}</span>
                                                    {p.team && <span className="text-[8px] font-mono text-gray-500">{p.team}</span>}
                                                  </span>
                                                ))}
                                              </div>
                                            </td>
                                          </tr>
                                        )}
                                      </>
                                    );
                                  })}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        )}

                        {cr.elapsed_seconds && (
                          <p className="text-[10px] text-gray-600 text-right">Completed in {cr.elapsed_seconds}s</p>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </>
          ) : (
            <div className="flex flex-col items-center justify-center h-96 text-gray-500">
              <BarChart3 className="w-12 h-12 mb-4 text-gray-700" />
              <p className="text-sm">
                {lineups.length === 0
                  ? 'Build lineups on the Lineup Builder tab first'
                  : hasUploadedEntries
                  ? 'Run a portfolio simulation across all your contests'
                  : 'Configure and run a simulation to see results'}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
