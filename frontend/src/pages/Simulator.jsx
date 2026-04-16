import { useState, useEffect, useRef, useCallback } from 'react';
import { PlayCircle, BarChart3, TrendingUp, DollarSign, Target, Activity, AlertCircle, RefreshCw, Trophy, Users, Upload, Loader2, XCircle } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import { api, AbortError } from '../api/client';
import { formatCurrency, formatDecimal, formatPct } from '../utils/formatting';
import PayoutDisplay from '../components/PayoutDisplay';
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

export default function Simulator() {
  const { site, selectedSlate, getCurrentBuild, uploadedContests } = useApp();
  const currentBuild = getCurrentBuild();
  const lineups = currentBuild?.lineups || [];

  // Contest config (manual or from DK entries)
  const [contests, setContests] = useState([]);
  const [selectedContest, setSelectedContest] = useState(null);
  const [hasUploadedEntries, setHasUploadedEntries] = useState(false);
  const [loadingContests, setLoadingContests] = useState(true);
  const [manualEntryFee, setManualEntryFee] = useState(20);
  const [manualFieldSize, setManualFieldSize] = useState(1000);

  // Entries for selected contest
  const [contestEntries, setContestEntries] = useState([]);
  const [loadingEntries, setLoadingEntries] = useState(false);

  // Sim controls
  const [numSims, setNumSims] = useState(10000);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);

  // Results
  const [results, setResults] = useState(null);
  const [resultSort, setResultSort] = useState('avg_roi');
  const [resultSortDir, setResultSortDir] = useState('desc');

  // Abort controller for cancellation
  const abortRef = useRef(null);

  // Cleanup on unmount — cancel any in-flight sim
  useEffect(() => {
    return () => {
      if (abortRef.current) abortRef.current.abort();
    };
  }, []);

  // Load contests: prefer server-uploaded entries, fall back to context-persisted contests
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
            setSelectedContest(data[0]);
            setLoadingContests(false);
            return;
          }
        }
      } catch {
        // server unavailable — fall through to context
      }

      // Fall back to context-persisted contests
      if (!cancelled && uploadedContests.length > 0) {
        setHasUploadedEntries(true);
        setContests(uploadedContests);
        setSelectedContest(uploadedContests[0]);
      }

      if (!cancelled) setLoadingContests(false);
    }
    load();
    return () => { cancelled = true; };
  }, [uploadedContests]);

  // Load entries when selected contest changes
  useEffect(() => {
    if (!selectedContest?.contest_id) {
      setContestEntries([]);
      return;
    }
    let cancelled = false;
    async function loadEntries() {
      setLoadingEntries(true);
      try {
        const entries = await api.getDkEntries(selectedContest.contest_id);
        if (!cancelled) setContestEntries(entries || []);
      } catch {
        if (!cancelled) setContestEntries([]);
      } finally {
        if (!cancelled) setLoadingEntries(false);
      }
    }
    loadEntries();
    return () => { cancelled = true; };
  }, [selectedContest?.contest_id]);

  const handleCancel = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setRunning(false);
  }, []);

  const handleRun = async () => {
    if (lineups.length === 0) return;

    // Cancel any prior run
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setRunning(true);
    setError(null);
    setResults(null);

    try {
      let contestConfig;
      if (selectedContest) {
        contestConfig = {
          entry_fee: selectedContest.entry_fee,
          field_size: selectedContest.field_size || 1000,
          game_type: selectedContest.game_type || 'classic',
          max_entries: selectedContest.max_entries_per_user || 150,
          payout_structure: selectedContest.payout_structure || [],
          contest_id: selectedContest.contest_id,
        };
      } else {
        contestConfig = {
          entry_fee: manualEntryFee,
          field_size: manualFieldSize,
          game_type: 'classic',
          max_entries: 150,
          payout_structure: [],
        };
      }

      const userLineups = lineups.map(lu =>
        lu.players.map(p => ({
          name: p.name,
          position: p.position || p.rosterPosition,
          salary: p.salary,
          team: p.team,
        }))
      );

      const data = await api.runInlineSimulation({
        sim_count: numSims,
        site,
        slate_id: selectedSlate?.slate_id || null,
        contest_config: contestConfig,
        user_lineups: userLineups,
      }, controller.signal);

      setResults(data);
    } catch (err) {
      if (err instanceof AbortError || err.name === 'AbortError') return;
      setError(err.message || 'Simulation failed');
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setRunning(false);
    }
  };

  const handleResultSort = (key) => {
    if (resultSort === key) {
      setResultSortDir(resultSortDir === 'desc' ? 'asc' : 'desc');
    } else {
      setResultSort(key);
      setResultSortDir('desc');
    }
  };

  const sortedLineupResults = results?.per_lineup
    ? [...results.per_lineup].sort((a, b) => {
        const aVal = a[resultSort] ?? 0;
        const bVal = b[resultSort] ?? 0;
        return resultSortDir === 'desc' ? bVal - aVal : aVal - bVal;
      })
    : [];

  // Chart data from roi_distribution
  const chartData = results?.roi_distribution?.map(bin => ({
    range: `${bin.bin_start > 0 ? '+' : ''}${Math.round(bin.bin_start)}%`,
    count: bin.count,
    color: roiColor((bin.bin_start + bin.bin_end) / 2),
  })) || [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-gray-100">Simulator</h1>
        <p className="text-sm text-gray-500 mt-0.5">Contest simulation engine</p>
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
              <p className="text-xs text-gray-500">
                From {currentBuild?.name || 'Build 1'}
              </p>
            )}
          </div>

          {/* Contest selection */}
          {loadingContests ? (
            <div className="rounded-lg border border-gray-800 bg-gray-900 p-4 flex items-center justify-center gap-2">
              <Loader2 className="w-4 h-4 text-gray-500 animate-spin" />
              <span className="text-xs text-gray-500">Loading contests...</span>
            </div>
          ) : hasUploadedEntries && contests.length > 0 ? (
            <div className="space-y-3">
              {/* Contest list */}
              <div className="rounded-lg border border-gray-800 bg-gray-900 p-4 space-y-2">
                <span className="text-xs font-semibold text-gray-300">Select Contest</span>
                {contests.map(c => {
                  const isSelected = selectedContest?.contest_id === c.contest_id;
                  const fee = typeof c.entry_fee === 'number' ? c.entry_fee : parseFloat(c.entry_fee) || 0;
                  return (
                    <button
                      key={c.contest_id}
                      onClick={() => setSelectedContest(c)}
                      className={`w-full text-left rounded-lg p-3 transition-colors border ${
                        isSelected
                          ? 'bg-blue-950/40 border-blue-700'
                          : 'bg-gray-950 border-gray-800 hover:border-gray-700'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex items-center gap-2 min-w-0">
                          <Trophy className={`w-3.5 h-3.5 shrink-0 ${isSelected ? 'text-blue-400' : 'text-gray-600'}`} />
                          <span className={`text-xs font-semibold truncate ${isSelected ? 'text-gray-100' : 'text-gray-300'}`}>
                            {c.contest_name}
                          </span>
                        </div>
                        <span className="text-xs font-mono font-bold text-gray-100 shrink-0">
                          ${fee.toFixed(0)}
                        </span>
                      </div>
                      <div className="flex items-center gap-2 mt-1.5 ml-[22px] text-[10px] text-gray-500">
                        <span className="flex items-center gap-1">
                          <Users className="w-3 h-3" />
                          {c.field_size ? c.field_size.toLocaleString() : '--'}
                        </span>
                        <span className="text-gray-700">|</span>
                        <span className="text-blue-400 font-mono font-semibold">
                          {c.entry_count || 0} entr{(c.entry_count || 0) !== 1 ? 'ies' : 'y'}
                        </span>
                        {c.prize_pool && (
                          <>
                            <span className="text-gray-700">|</span>
                            <span className="text-emerald-400 font-mono">{formatCurrency(c.prize_pool)}</span>
                          </>
                        )}
                      </div>
                    </button>
                  );
                })}
              </div>

              {/* Selected contest details */}
              {selectedContest && (
                <div className="rounded-lg border border-gray-800 bg-gray-900 p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-gray-300">Contest Details</span>
                    {loadingEntries && (
                      <Loader2 className="w-3.5 h-3.5 text-gray-500 animate-spin" />
                    )}
                  </div>

                  {/* Stats grid */}
                  <div className="grid grid-cols-2 gap-2">
                    <div className="rounded-md bg-gray-950 p-2.5">
                      <div className="text-[9px] uppercase tracking-wider text-gray-500 mb-0.5">Entry Fee</div>
                      <div className="text-sm font-bold font-mono text-gray-100">
                        {formatCurrency(selectedContest.entry_fee, 2)}
                      </div>
                    </div>
                    <div className="rounded-md bg-gray-950 p-2.5">
                      <div className="text-[9px] uppercase tracking-wider text-gray-500 mb-0.5">Field Size</div>
                      <div className="text-sm font-bold font-mono text-gray-100">
                        {selectedContest.field_size ? selectedContest.field_size.toLocaleString() : '--'}
                      </div>
                    </div>
                    <div className="rounded-md bg-gray-950 p-2.5">
                      <div className="text-[9px] uppercase tracking-wider text-gray-500 mb-0.5">Your Entries</div>
                      <div className="text-sm font-bold font-mono text-blue-400">
                        {selectedContest.entry_count || 0}
                      </div>
                    </div>
                    <div className="rounded-md bg-gray-950 p-2.5">
                      <div className="text-[9px] uppercase tracking-wider text-gray-500 mb-0.5">Prize Pool</div>
                      <div className="text-sm font-bold font-mono text-emerald-400">
                        {selectedContest.prize_pool ? formatCurrency(selectedContest.prize_pool) : '--'}
                      </div>
                    </div>
                  </div>

                  {/* Top 3 prizes from payout structure */}
                  {selectedContest.payout_structure && selectedContest.payout_structure.length > 0 && (
                    <PayoutDisplay payoutStructure={selectedContest.payout_structure} />
                  )}

                  {/* Entry count callout */}
                  {!loadingEntries && contestEntries.length > 0 && (
                    <div className="flex items-center gap-2 rounded-md bg-blue-950/30 border border-blue-900/50 px-3 py-2">
                      <Users className="w-3.5 h-3.5 text-blue-400" />
                      <span className="text-xs text-blue-300 font-semibold">
                        {contestEntries.length} entr{contestEntries.length !== 1 ? 'ies' : 'y'} in this contest
                      </span>
                    </div>
                  )}
                </div>
              )}
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
                  to auto-populate contest details, or configure manually below.
                </p>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-gray-400">Entry Fee ($)</span>
                <input
                  type="number"
                  value={manualEntryFee}
                  onChange={(e) => setManualEntryFee(Number(e.target.value))}
                  className="w-20 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs font-mono text-gray-200 text-right focus:outline-none focus:border-blue-500"
                  min={1}
                />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-gray-400">Field Size</span>
                <input
                  type="number"
                  value={manualFieldSize}
                  onChange={(e) => setManualFieldSize(Number(e.target.value))}
                  className="w-24 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs font-mono text-gray-200 text-right focus:outline-none focus:border-blue-500"
                  min={10}
                  step={100}
                />
              </div>
            </div>
          )}

          {/* Sim count */}
          <div className="rounded-lg border border-gray-800 bg-gray-900 p-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-gray-300">Simulations</span>
              <span className="text-sm font-mono font-bold text-blue-400">{numSims.toLocaleString()}</span>
            </div>
            <input
              type="range"
              min={1000}
              max={100000}
              step={1000}
              value={numSims}
              onChange={(e) => setNumSims(Number(e.target.value))}
              className="w-full"
            />
            <div className="flex justify-between text-[10px] text-gray-600 font-mono">
              <span>1K</span>
              <span>25K</span>
              <span>50K</span>
              <span>100K</span>
            </div>
          </div>

          {/* Run / Cancel button */}
          {running ? (
            <button
              onClick={handleCancel}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg bg-red-600 text-white font-semibold text-sm hover:bg-red-500 transition-colors"
            >
              <XCircle className="w-4 h-4" />
              Cancel Simulation
            </button>
          ) : (
            <button
              onClick={handleRun}
              disabled={lineups.length === 0}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg bg-emerald-600 text-white font-semibold text-sm hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <PlayCircle className="w-4 h-4" />
              Run Simulation
            </button>
          )}

          {error && (
            <div className="rounded-lg border border-red-800 bg-red-900/20 px-3 py-2 text-xs text-red-400">
              {error}
            </div>
          )}
        </div>

        {/* Results panel */}
        <div className="md:col-span-2 space-y-4">
          {results ? (
            <>
              {/* Key metrics */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[10px] uppercase tracking-wider text-gray-500">Avg ROI</span>
                    <TrendingUp className="w-4 h-4 text-emerald-400" />
                  </div>
                  <div className={`text-2xl font-bold font-mono ${results.overall.avg_roi >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {results.overall.avg_roi > 0 ? '+' : ''}{formatDecimal(results.overall.avg_roi)}%
                  </div>
                  <div className="text-[10px] text-gray-500 mt-1">across {numSims.toLocaleString()} sims</div>
                </div>
                <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[10px] uppercase tracking-wider text-gray-500">Cash Rate</span>
                    <DollarSign className="w-4 h-4 text-blue-400" />
                  </div>
                  <div className="text-2xl font-bold font-mono text-blue-400">{formatDecimal(results.overall.cash_rate)}%</div>
                  <div className="text-[10px] text-gray-500 mt-1">ITM frequency</div>
                </div>
                <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[10px] uppercase tracking-wider text-gray-500">Win Rate</span>
                    <Target className="w-4 h-4 text-amber-400" />
                  </div>
                  <div className="text-2xl font-bold font-mono text-amber-400">{formatPct(results.overall.win_rate, 2)}</div>
                  <div className="text-[10px] text-gray-500 mt-1">1st place</div>
                </div>
                <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[10px] uppercase tracking-wider text-gray-500">Top ROI</span>
                    <Activity className="w-4 h-4 text-purple-400" />
                  </div>
                  <div className="text-2xl font-bold font-mono text-purple-400">
                    {results.overall.top_roi > 0 ? '+' : ''}{formatDecimal(results.overall.top_roi)}%
                  </div>
                  <div className="text-[10px] text-gray-500 mt-1">best sim</div>
                </div>
              </div>

              {/* ROI Distribution Chart */}
              {chartData.length > 0 && (
                <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
                  <h3 className="text-xs font-semibold text-gray-400 mb-4 flex items-center gap-2">
                    <BarChart3 className="w-4 h-4" />
                    ROI Distribution
                  </h3>
                  <div className="h-56">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={chartData} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                        <XAxis
                          dataKey="range"
                          tick={{ fontSize: 10, fill: '#6b7280' }}
                          axisLine={{ stroke: '#374151' }}
                          tickLine={{ stroke: '#374151' }}
                        />
                        <YAxis
                          tick={{ fontSize: 10, fill: '#6b7280' }}
                          axisLine={{ stroke: '#374151' }}
                          tickLine={{ stroke: '#374151' }}
                        />
                        <Tooltip content={<CustomTooltip />} />
                        <Bar dataKey="count" radius={[3, 3, 0, 0]}>
                          {chartData.map((entry, index) => (
                            <Cell key={index} fill={entry.color} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}

              {/* Lineup results table */}
              <div className="rounded-lg border border-gray-800 bg-gray-900 overflow-hidden">
                <div className="px-4 py-2.5 border-b border-gray-800">
                  <h3 className="text-xs font-semibold text-gray-400">
                    Lineup Results ({sortedLineupResults.length} lineups)
                  </h3>
                </div>
                <div className="data-table-container overflow-x-auto" style={{ maxHeight: '400px' }}>
                  <table className="w-full text-left min-w-[700px]">
                    <thead>
                      <tr className="bg-gray-900">
                        {[
                          { key: 'lineup_index', label: 'Lineup #', align: '' },
                          { key: 'avg_profit', label: 'Avg Pts', align: 'text-right' },
                          { key: 'p25_roi', label: 'Bottom 25% ROI', align: 'text-right' },
                          { key: 'avg_roi', label: 'Avg ROI', align: 'text-right' },
                          { key: 'p75_roi', label: 'Top 75% ROI', align: 'text-right' },
                          { key: 'top_roi', label: 'Top ROI', align: 'text-right' },
                          { key: 'cash_rate', label: 'Cash Rate', align: 'text-right' },
                          { key: 'win_rate', label: 'Win Rate', align: 'text-right' },
                        ].map((col) => (
                          <th
                            key={col.key}
                            onClick={() => handleResultSort(col.key)}
                            className={`px-3 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-500 bg-gray-900 cursor-pointer hover:text-gray-300 ${col.align}`}
                          >
                            {col.label}
                            {resultSort === col.key && (
                              <span className="text-blue-400 ml-0.5">
                                {resultSortDir === 'desc' ? '\u25BC' : '\u25B2'}
                              </span>
                            )}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {sortedLineupResults.map((r, i) => (
                        <tr
                          key={r.lineup_index}
                          className={`${i % 2 === 0 ? 'bg-gray-950' : 'bg-gray-900/50'} hover:bg-gray-800/50 transition-colors`}
                        >
                          <td className="px-3 py-2 text-xs text-gray-300">#{r.lineup_index + 1}</td>
                          <td className="px-3 py-2 text-xs font-mono text-gray-200 text-right">
                            {formatCurrency(r.avg_profit)}
                          </td>
                          <td className="px-3 py-2 text-right">
                            <span className={`text-xs font-mono font-semibold ${r.p25_roi >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                              {r.p25_roi > 0 ? '+' : ''}{formatDecimal(r.p25_roi)}%
                            </span>
                          </td>
                          <td className="px-3 py-2 text-right">
                            <span className={`text-xs font-mono font-semibold ${r.avg_roi >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                              {r.avg_roi > 0 ? '+' : ''}{formatDecimal(r.avg_roi)}%
                            </span>
                          </td>
                          <td className="px-3 py-2 text-right">
                            <span className={`text-xs font-mono font-semibold ${r.p75_roi >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                              {r.p75_roi > 0 ? '+' : ''}{formatDecimal(r.p75_roi)}%
                            </span>
                          </td>
                          <td className="px-3 py-2 text-right">
                            <span className={`text-xs font-mono font-semibold ${r.top_roi >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                              {r.top_roi > 0 ? '+' : ''}{formatDecimal(r.top_roi)}%
                            </span>
                          </td>
                          <td className="px-3 py-2 text-xs font-mono text-gray-300 text-right">{formatDecimal(r.cash_rate)}%</td>
                          <td className="px-3 py-2 text-xs font-mono text-gray-400 text-right">{formatPct(r.win_rate, 2)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Elapsed time */}
              {results.elapsed_seconds && (
                <p className="text-[10px] text-gray-600 text-right">
                  Completed in {results.elapsed_seconds}s
                </p>
              )}
            </>
          ) : (
            <div className="flex flex-col items-center justify-center h-96 text-gray-500">
              <BarChart3 className="w-12 h-12 mb-4 text-gray-700" />
              <p className="text-sm">
                {lineups.length === 0
                  ? 'Build lineups on the Lineup Builder tab first'
                  : 'Configure and run a simulation to see results'}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
