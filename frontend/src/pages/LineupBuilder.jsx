import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { Download, RefreshCw, Zap, Trash2, XCircle, Users, List, Lock, Unlock, Loader2, Layers } from 'lucide-react';
import LineupCard from '../components/LineupCard';
import LineupEditor from '../components/LineupEditor';
import StackControl from '../components/StackControl';
import { formatSalary, formatDecimal, formatPct } from '../utils/formatting';
import { api, AbortError } from '../api/client';
import { useApp } from '../context/AppContext';

const BUILD_LOADING_STAGES = [
  { pct: 0,  icon: '\u2699\uFE0F', text: 'Firing up the optimizer...' },
  { pct: 10, icon: '\uD83E\uDDE0', text: 'Teaching PuLP about salary caps...' },
  { pct: 20, icon: '\uD83D\uDCB5', text: 'Spending every last dollar of your salary cap...' },
  { pct: 35, icon: '\uD83C\uDFB2', text: 'Adding some spice to keep things interesting...' },
  { pct: 50, icon: '\uD83D\uDD04', text: 'Greedy phase engaged — cranking out lineups...' },
  { pct: 65, icon: '\u26BE', text: 'Stacking hitters like it\'s Coors Field every night...' },
  { pct: 80, icon: '\uD83D\uDCCA', text: 'Almost there — polishing the final builds...' },
  { pct: 92, icon: '\u2705', text: 'Wrapping up — your lineup pool is nearly ready' },
];

function BuildLoadingDisplay({ progress, count }) {
  const stage = [...BUILD_LOADING_STAGES].reverse().find(s => progress >= s.pct) || BUILD_LOADING_STAGES[0];
  return (
    <div className="flex flex-col items-center justify-center py-16 px-8">
      <div className="text-4xl mb-5 animate-bounce" style={{ animationDuration: '1.5s' }}>
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
          <span className="text-[10px] font-mono text-gray-600">Building {count} lineups...</span>
        </div>
      </div>
      <p className="text-sm text-gray-400 text-center max-w-sm">{stage.text}</p>
    </div>
  );
}

export default function LineupBuilder() {
  const { site, selectedSlate, getCurrentBuild, updateCurrentBuildLineups, stackExposures, setStackExposures, selectedDate, playerExposures, setPlayerExposures } = useApp();
  const [numLineups, setNumLineups] = useState(20);
  const [variance, setVariance] = useState(0.15);
  const [skew, setSkew] = useState('neutral');
  const [minSalary, setMinSalary] = useState(site === 'fd' ? 58000 : 45000);
  const [building, setBuilding] = useState(false);
  const [showStacks, setShowStacks] = useState(false);
  const [stackTeams, setStackTeams] = useState([]);
  const [error, setError] = useState(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [rightTab, setRightTab] = useState('lineups'); // 'lineups' | 'exposure' | 'teamExposure'
  const [exposureSearch, setExposureSearch] = useState('');
  const [exposureFilter, setExposureFilter] = useState('all'); // 'all' | 'pitchers' | 'hitters'
  const [lockedLineups, setLockedLineups] = useState(new Set());
  const [buildProgress, setBuildProgress] = useState(0);
  const buildProgressRef = useRef(null);

  // Player pool cache for the editor
  const [playerPool, setPlayerPool] = useState([]);
  const playerPoolSlateRef = useRef(null);

  // Abort controller for cancelling builds
  const abortRef = useRef(null);

  useEffect(() => {
    return () => {
      if (abortRef.current) abortRef.current.abort();
      if (buildProgressRef.current) clearInterval(buildProgressRef.current);
    };
  }, []);

  const handleCancel = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    if (buildProgressRef.current) {
      clearInterval(buildProgressRef.current);
      buildProgressRef.current = null;
    }
    setBuilding(false);
    setBuildProgress(0);
  }, []);

  // Lineup currently being edited (null = editor closed)
  const [editingLineup, setEditingLineup] = useState(null);

  const currentBuild = getCurrentBuild();
  const lineups = currentBuild?.lineups || [];

  // Load teams + player pool from projections for stack controls & editor
  useEffect(() => {
    if (!selectedSlate) return;
    const slateId = selectedSlate.slate_id;
    api.getSlateProjections(slateId, site)
      .then(data => {
        const teams = [...new Set(data.map(p => p.team).filter(Boolean))].sort();
        setStackTeams(teams);
        setPlayerPool(data);
        playerPoolSlateRef.current = slateId;
      })
      .catch(() => {});
  }, [site, selectedSlate]);

  // Open the editor for a lineup, fetching player pool if needed
  const handleEditLineup = async (lineup) => {
    if (selectedSlate && playerPoolSlateRef.current !== selectedSlate.slate_id) {
      try {
        const data = await api.getSlateProjections(selectedSlate.slate_id, site);
        setPlayerPool(data);
        playerPoolSlateRef.current = selectedSlate.slate_id;
      } catch { /* proceed with whatever we have */ }
    }
    setEditingLineup(lineup);
  };

  // Save edited lineup back into the build
  const handleSaveEditedLineup = (updatedLineup) => {
    const newLineups = lineups.map(l =>
      l.id === updatedLineup.id ? updatedLineup : l
    );
    updateCurrentBuildLineups(newLineups);
    setEditingLineup(null);
  };

  const handleBuild = async () => {
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setBuilding(true);
    setError(null);
    setBuildProgress(0);

    // Progress timer — estimate based on lineup count
    const buildCount_est = Math.max(1, numLineups - lockedLineups.size);
    const estimatedSeconds = Math.max(3, (buildCount_est / 20) * 1.5);
    const startTime = Date.now();
    if (buildProgressRef.current) clearInterval(buildProgressRef.current);
    buildProgressRef.current = setInterval(() => {
      const elapsed = (Date.now() - startTime) / 1000;
      const linearPct = (elapsed / estimatedSeconds) * 90;
      const pct = linearPct <= 90
        ? linearPct
        : 90 + 7 * (1 - Math.exp(-0.3 * (elapsed - estimatedSeconds)));
      setBuildProgress(Math.min(pct, 97));
    }, 500);

    try {
      const stackConfig = {};
      for (const [team, config] of Object.entries(stackExposures || {})) {
        const teamConfig = {};
        for (const sz of [3, 4, 5]) {
          const se = config[`stack_${sz}`];
          if (se && (se.min > 0 || se.max < 100)) {
            teamConfig[`stack_${sz}`] = { min_pct: se.min, max_pct: se.max };
          }
        }
        if (Object.keys(teamConfig).length > 0) stackConfig[team] = teamConfig;
      }

      // Build exposure overrides from playerExposures context
      const exposureOverrides = {};
      for (const [name, limits] of Object.entries(playerExposures || {})) {
        const mn = limits.min ?? 0;
        const mx = limits.max ?? 100;
        if (mn > 0 || mx < 100) {
          exposureOverrides[name] = [mn, mx];
        }
      }

      // Preserve locked lineups — only build the remaining count
      const locked = lineups.filter(l => lockedLineups.has(l.id));
      const buildCount = Math.max(1, numLineups - locked.length);

      const result = await api.buildLineupsCSV({
        site,
        n_lineups: buildCount,
        min_unique: 3,
        objective: 'median_pts',
        variance,
        skew,
        target_date: selectedDate,
        slate_id: selectedSlate?.slate_id || null,
        min_salary: minSalary || null,
        stack_exposures: stackConfig,
        exposure_overrides: exposureOverrides,
      }, controller.signal);

      if (!result.lineups || result.lineups.length === 0) {
        setError('No lineups generated. Upload a projection CSV first.');
        setBuilding(false);
        return;
      }

      const startId = locked.length > 0 ? Math.max(...locked.map(l => l.id)) + 1 : 1;
      const generated = result.lineups.map((lu, i) => ({
        id: startId + i,
        players: lu.map(slot => ({
          name: slot.name,
          position: slot.position,
          rosterPosition: slot.position,
          team: slot.team,
          salary: slot.salary,
          median: slot.pts,
          dk_id: slot.dk_id,
        })),
      }));

      // Merge locked lineups (first) with newly generated
      const merged = [...locked, ...generated];
      updateCurrentBuildLineups(merged);

      // Keep locked set (IDs preserved), clear any that no longer exist
      setLockedLineups(prev => {
        const next = new Set();
        for (const id of prev) {
          if (merged.some(l => l.id === id)) next.add(id);
        }
        return next;
      });
    } catch (err) {
      if (err instanceof AbortError || err.name === 'AbortError') return;
      setError(err.message || 'Failed to build lineups');
    } finally {
      if (buildProgressRef.current) clearInterval(buildProgressRef.current);
      buildProgressRef.current = null;
      setBuildProgress(100);
      if (abortRef.current === controller) abortRef.current = null;
      setBuilding(false);
    }
  };

  const handleClear = () => {
    if (confirmClear) {
      updateCurrentBuildLineups([]);
      setLockedLineups(new Set());
      setConfirmClear(false);
    } else {
      setConfirmClear(true);
    }
  };

  const cancelClear = () => setConfirmClear(false);

  const toggleLock = (lineupId) => {
    setLockedLineups(prev => {
      const next = new Set(prev);
      if (next.has(lineupId)) next.delete(lineupId);
      else next.add(lineupId);
      return next;
    });
  };

  const avgSalary = lineups.length > 0
    ? lineups.reduce((sum, l) => sum + l.players.reduce((s, p) => s + p.salary, 0), 0) / lineups.length
    : 0;

  const avgProj = lineups.length > 0
    ? lineups.reduce((sum, l) => sum + l.players.reduce((s, p) => s + p.median, 0), 0) / lineups.length
    : 0;

  // Calculate exposure — count each player once per lineup (Set deduplication handles dual SP slots)
  const fullExposureData = useMemo(() => {
    if (lineups.length === 0) return [];
    const countMap = {};
    const metaMap = {};
    lineups.forEach((l) => {
      const seen = new Set();
      l.players.forEach((p) => {
        if (!seen.has(p.name)) {
          seen.add(p.name);
          countMap[p.name] = (countMap[p.name] || 0) + 1;
          if (!metaMap[p.name]) {
            metaMap[p.name] = { position: p.position, team: p.team, salary: p.salary };
          }
        }
      });
    });
    return Object.entries(countMap)
      .map(([name, count]) => ({
        name,
        count,
        pct: (count / lineups.length) * 100,
        ...metaMap[name],
        minExp: playerExposures[name]?.min ?? 0,
        maxExp: playerExposures[name]?.max ?? 100,
      }))
      .sort((a, b) => b.pct - a.pct);
  }, [lineups, playerExposures]);

  const teamStackData = useMemo(() => {
    if (lineups.length === 0) return [];
    const pitcherPos = new Set(['P', 'SP', 'RP']);
    const teamStats = {};
    lineups.forEach((l) => {
      const teamCounts = {};
      l.players.forEach((p) => {
        if (p.team && !p.position.split('/').some(pos => pitcherPos.has(pos.trim()))) {
          teamCounts[p.team] = (teamCounts[p.team] || 0) + 1;
        }
      });
      for (const [team, count] of Object.entries(teamCounts)) {
        if (!teamStats[team]) teamStats[team] = { stack3: 0, stack4: 0, stack5: 0, totalHitters: 0, hitterCount: count };
        if (count >= 3) teamStats[team].stack3++;
        if (count >= 4) teamStats[team].stack4++;
        if (count >= 5) teamStats[team].stack5++;
        teamStats[team].totalHitters += count;
      }
    });
    return Object.entries(teamStats)
      .map(([team, stats]) => ({
        team,
        stack3: stats.stack3,
        stack4: stats.stack4,
        stack5: stats.stack5,
        stack3Pct: (stats.stack3 / lineups.length) * 100,
        stack4Pct: (stats.stack4 / lineups.length) * 100,
        stack5Pct: (stats.stack5 / lineups.length) * 100,
        avgHitters: stats.totalHitters / lineups.length,
        minStack3: stackExposures[team]?.stack_3?.min ?? 0,
        maxStack3: stackExposures[team]?.stack_3?.max ?? 100,
        minStack4: stackExposures[team]?.stack_4?.min ?? 0,
        maxStack4: stackExposures[team]?.stack_4?.max ?? 100,
        minStack5: stackExposures[team]?.stack_5?.min ?? 0,
        maxStack5: stackExposures[team]?.stack_5?.max ?? 100,
      }))
      .sort((a, b) => b.stack4Pct - a.stack4Pct || b.stack3Pct - a.stack3Pct);
  }, [lineups, stackExposures]);

  const exposureList = fullExposureData.slice(0, 15);

  return (
    <div className="flex flex-col md:flex-row gap-6 md:h-[calc(100vh-110px)]">
      {/* Left panel - Controls */}
      <div className="w-full md:w-80 shrink-0 overflow-y-auto space-y-4 md:pr-2">
        <div>
          <h1 className="text-xl font-bold text-gray-100">Lineup Builder</h1>
          <p className="text-sm text-gray-500 mt-0.5">Optimizer Controls</p>
        </div>

        {/* Number of lineups */}
        <div className="rounded-lg border border-gray-800 bg-gray-900 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-gray-300">Number of Lineups</span>
            <input
              type="number"
              value={numLineups}
              onChange={(e) => setNumLineups(Math.max(1, Number(e.target.value)))}
              className="w-20 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm font-mono font-bold text-blue-400 text-right focus:outline-none focus:border-blue-500"
              min={1}
            />
          </div>
          <input
            type="range"
            min={0}
            max={100}
            value={
              numLineups <= 1 ? 0 :
              numLineups <= 100 ? ((numLineups - 1) / 99) * 33 :
              numLineups <= 500 ? 33 + ((numLineups - 100) / 400) * 33 :
              numLineups <= 2500 ? 66 + ((numLineups - 500) / 2000) * 34 :
              100
            }
            onChange={(e) => {
              const pct = Number(e.target.value);
              let val;
              if (pct <= 33) {
                val = Math.round(1 + (pct / 33) * 99);
              } else if (pct <= 66) {
                val = Math.round(100 + ((pct - 33) / 33) * 400);
              } else {
                val = Math.round(500 + ((pct - 66) / 34) * 2000);
              }
              setNumLineups(val);
            }}
            className="w-full"
          />
          <div className="flex justify-between text-[10px] text-gray-600 font-mono">
            <span>1</span>
            <span>100</span>
            <span>500</span>
            <span>2500</span>
          </div>
        </div>

        {/* Lineup Variance */}
        <div className="rounded-lg border border-gray-800 bg-gray-900 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-gray-300">Lineup Variance</span>
            <span className="text-xs font-mono text-blue-400">{(variance * 100).toFixed(0)}%</span>
          </div>
          <input
            type="range"
            min={0}
            max={100}
            value={variance * 100}
            onChange={(e) => setVariance(Number(e.target.value) / 100)}
            className="w-full"
          />
          <div className="flex justify-between text-[10px] text-gray-600">
            <span>Optimal</span>
            <span>Diverse</span>
          </div>
          <p className="text-[10px] text-gray-600">Higher variance creates more diverse lineups</p>
        </div>

        {/* Projection Skew */}
        <div className="rounded-lg border border-gray-800 bg-gray-900 p-4 space-y-2">
          <span className="text-xs font-semibold text-gray-300">Projection Skew</span>
          <div className="flex gap-1">
            {['floor', 'neutral', 'ceiling'].map((s) => (
              <button
                key={s}
                onClick={() => setSkew(s)}
                className={`flex-1 px-2 py-1.5 rounded text-xs font-semibold transition-colors ${
                  skew === s
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-800 text-gray-400 hover:text-gray-200'
                }`}
              >
                {s === 'floor' ? 'Safe' : s === 'ceiling' ? 'Upside' : 'Balanced'}
              </button>
            ))}
          </div>
        </div>

        {/* Min Salary */}
        <div className="rounded-lg border border-gray-800 bg-gray-900 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-gray-300">Min Salary</span>
            <span className="text-xs font-mono text-blue-400">${(minSalary || 0).toLocaleString()}</span>
          </div>
          <input
            type="range"
            min={site === 'fd' ? 50000 : 40000}
            max={site === 'fd' ? 60000 : 50000}
            step={500}
            value={minSalary}
            onChange={(e) => setMinSalary(Number(e.target.value))}
            className="w-full"
          />
          <div className="flex justify-between text-[10px] text-gray-600 font-mono">
            <span>${(site === 'fd' ? 50000 : 40000).toLocaleString()}</span>
            <span>${(site === 'fd' ? 60000 : 50000).toLocaleString()}</span>
          </div>
          <p className="text-[10px] text-gray-600">Minimum total salary for each lineup</p>
        </div>

        {/* Build / Cancel button */}
        {building ? (
          <button
            onClick={handleCancel}
            className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg bg-red-600 text-white font-semibold text-sm hover:bg-red-500 transition-colors"
          >
            <XCircle className="w-4 h-4" />
            Cancel Build
          </button>
        ) : (
          <button
            onClick={handleBuild}
            className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg bg-blue-600 text-white font-semibold text-sm hover:bg-blue-500 transition-colors"
          >
            <Zap className="w-4 h-4" />
            Build {numLineups} Lineups
            {lockedLineups.size > 0 && (
              <span className="text-blue-200 text-xs">({lockedLineups.size} locked)</span>
            )}
          </button>
        )}

        {lineups.length > 0 && (
          <div className="text-center -mt-2">
            {confirmClear ? (
              <span className="text-xs text-gray-400">
                Clear all lineups?{' '}
                <button onClick={handleClear} className="text-red-400 hover:text-red-300 font-medium">
                  Yes, clear
                </button>
                {' / '}
                <button onClick={cancelClear} className="text-gray-400 hover:text-gray-300">
                  Cancel
                </button>
              </span>
            ) : (
              <button
                onClick={handleClear}
                className="text-[11px] text-gray-500 hover:text-red-400 transition-colors"
              >
                Clear lineups
              </button>
            )}
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-red-800 bg-red-900/20 px-3 py-2 text-xs text-red-400">
            {error}
          </div>
        )}

        {/* Team Stacks */}
        <div className="rounded-lg border border-gray-800 bg-gray-900 overflow-hidden">
          <button
            onClick={() => setShowStacks(!showStacks)}
            className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-gray-800/40 transition-colors"
          >
            <span className="text-xs font-semibold text-gray-300">Team Stacks</span>
            <span className="text-[10px] text-gray-500">{showStacks ? 'Hide' : 'Show'}</span>
          </button>
          {showStacks && (
            <div className="p-3 border-t border-gray-800 space-y-2">
              {stackTeams.map((team) => (
                <StackControl
                  key={team}
                  team={team}
                  value={stackExposures[team]}
                  onChange={(updated) => {
                    setStackExposures(prev => ({
                      ...prev,
                      [team]: {
                        stack_3: { min: updated['3man'].min, max: updated['3man'].max },
                        stack_4: { min: updated['4man'].min, max: updated['4man'].max },
                        stack_5: { min: updated['5man'].min, max: updated['5man'].max },
                      },
                    }));
                  }}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Right panel - Tabbed: Lineups / Player Exposure */}
      <div className="flex-1 overflow-y-auto space-y-4 min-w-0">
        {/* Tab header + actions */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <div className="flex items-center bg-gray-900 rounded-lg p-0.5 border border-gray-800">
              <button
                onClick={() => setRightTab('lineups')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition-colors ${
                  rightTab === 'lineups' ? 'bg-gray-800 text-white shadow-sm' : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                <List className="w-3.5 h-3.5" />
                Lineups
                <span className={`text-[10px] font-mono ${rightTab === 'lineups' ? 'text-blue-400' : 'text-gray-500'}`}>
                  {lineups.length}
                </span>
              </button>
              <button
                onClick={() => setRightTab('exposure')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition-colors ${
                  rightTab === 'exposure' ? 'bg-gray-800 text-white shadow-sm' : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                <Users className="w-3.5 h-3.5" />
                Player Exposure
                <span className={`text-[10px] font-mono ${rightTab === 'exposure' ? 'text-blue-400' : 'text-gray-500'}`}>
                  {fullExposureData.length}
                </span>
              </button>
              <button
                onClick={() => setRightTab('teamExposure')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition-colors ${
                  rightTab === 'teamExposure' ? 'bg-gray-800 text-white shadow-sm' : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                <Layers className="w-3.5 h-3.5" />
                Team Stacks
                <span className={`text-[10px] font-mono ${rightTab === 'teamExposure' ? 'text-blue-400' : 'text-gray-500'}`}>
                  {teamStackData.length}
                </span>
              </button>
            </div>
            {rightTab === 'lineups' && lineups.length > 0 && (
              <div className="flex items-center gap-3 ml-2">
                <div className="text-xs text-gray-500">
                  Avg Salary: <span className="font-mono text-gray-300">{formatSalary(Math.round(avgSalary))}</span>
                </div>
                <div className="text-xs text-gray-500">
                  Avg Proj: <span className="font-mono text-emerald-400">{formatDecimal(avgProj)}</span>
                </div>
              </div>
            )}
          </div>
          {rightTab === 'lineups' && lineups.length > 0 && (
            <div className="flex items-center gap-2">
              {confirmClear ? (
                <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-red-800/50 bg-gray-800 text-xs">
                  <span className="text-gray-400">Clear all?</span>
                  <button onClick={handleClear} className="text-red-400 hover:text-red-300 font-medium">Yes</button>
                  <span className="text-gray-600">/</span>
                  <button onClick={cancelClear} className="text-gray-400 hover:text-gray-300">No</button>
                </div>
              ) : (
                <button
                  onClick={handleClear}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-700 bg-gray-800 text-xs text-red-400/70 hover:text-red-400 hover:border-red-800/50 transition-colors"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  Clear
                </button>
              )}
              <button className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-gray-700 bg-gray-800 text-xs text-gray-300 hover:bg-gray-700 transition-colors">
                <Download className="w-3.5 h-3.5" />
                Export CSV
              </button>
            </div>
          )}
          {rightTab === 'exposure' && (
            <div className="flex items-center gap-2">
              <div className="flex items-center bg-gray-900 rounded-lg p-0.5 border border-gray-800">
                {['all', 'pitchers', 'hitters'].map((f) => (
                  <button
                    key={f}
                    onClick={() => setExposureFilter(f)}
                    className={`px-2.5 py-1 rounded-md text-[10px] font-semibold transition-colors ${
                      exposureFilter === f ? 'bg-gray-800 text-white shadow-sm' : 'text-gray-400 hover:text-gray-200'
                    }`}
                  >
                    {f === 'all' ? 'All' : f === 'pitchers' ? 'Pitchers' : 'Hitters'}
                  </button>
                ))}
              </div>
              <input
                type="text"
                placeholder="Search players..."
                value={exposureSearch}
                onChange={(e) => setExposureSearch(e.target.value)}
                className="w-48 bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500"
              />
            </div>
          )}
        </div>

        {/* Build progress bar */}
        {building && (
          <BuildLoadingDisplay progress={buildProgress} count={numLineups} />
        )}

        {/* Lineups Tab */}
        {rightTab === 'lineups' && !building && (
          <>
            {lineups.length === 0 && (
              <div className="text-center py-20 text-gray-600">
                <Zap className="w-10 h-10 mx-auto mb-3 opacity-30" />
                <p className="text-sm">Click "Build Lineups" to generate optimized lineups</p>
                <p className="text-xs mt-1">Set exposure limits on the Projections tab or the Player Exposure tab</p>
              </div>
            )}

            {/* Top exposure summary */}
            {exposureList.length > 0 && (
              <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-xs font-semibold text-gray-400">Top Exposure</h3>
                  <button
                    onClick={() => setRightTab('exposure')}
                    className="text-[10px] text-blue-400 hover:text-blue-300"
                  >
                    View all &rarr;
                  </button>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-1">
                  {exposureList.map((e) => (
                    <div key={e.name} className="flex items-center justify-between">
                      <span className="text-xs text-gray-300 truncate mr-2">{e.name}</span>
                      <div className="flex items-center gap-2">
                        <div className="w-16 h-1.5 bg-gray-800 rounded-full overflow-hidden">
                          <div className="h-full bg-blue-500 rounded-full" style={{ width: `${e.pct}%` }} />
                        </div>
                        <span className="text-[10px] font-mono text-gray-500 w-8 text-right">
                          {formatPct(e.pct, 0)}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Locked count indicator */}
            {lockedLineups.size > 0 && (
              <div className="flex items-center gap-2 text-xs text-amber-400">
                <Lock className="w-3.5 h-3.5" />
                {lockedLineups.size} lineup{lockedLineups.size !== 1 ? 's' : ''} locked — will be kept on rebuild
              </div>
            )}

            {/* Lineup cards */}
            <div className="space-y-2">
              {lineups.map((lineup, i) => (
                <div key={lineup.id} className="relative">
                  <button
                    onClick={() => toggleLock(lineup.id)}
                    title={lockedLineups.has(lineup.id) ? 'Unlock lineup' : 'Lock lineup'}
                    className={`absolute top-2 right-2 z-10 p-1.5 rounded-md transition-colors ${
                      lockedLineups.has(lineup.id)
                        ? 'bg-amber-500/20 text-amber-400 hover:bg-amber-500/30'
                        : 'bg-gray-800/60 text-gray-600 hover:text-gray-400 hover:bg-gray-800'
                    }`}
                  >
                    {lockedLineups.has(lineup.id) ? <Lock className="w-3.5 h-3.5" /> : <Unlock className="w-3.5 h-3.5" />}
                  </button>
                  <LineupCard
                    lineup={lineup}
                    index={i}
                    expanded={i === 0}
                    onEdit={handleEditLineup}
                  />
                </div>
              ))}
            </div>
          </>
        )}

        {/* Player Exposure Tab */}
        {rightTab === 'exposure' && (
          <div className="rounded-lg border border-gray-800 overflow-hidden">
            <div className="data-table-container overflow-x-auto" style={{ maxHeight: 'calc(100vh - 200px)' }}>
              <table className="w-full text-left min-w-[600px]">
                <thead>
                  <tr className="bg-gray-900">
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
                    const exposureLookup = {};
                    fullExposureData.forEach(e => { exposureLookup[e.name] = e; });

                    // Merge: all players from pool + any that appear in lineups
                    const allPlayers = [];
                    const seen = new Set();
                    // Players with actual exposure first (sorted by pct desc)
                    fullExposureData.forEach(e => {
                      seen.add(e.name);
                      allPlayers.push(e);
                    });
                    // Players from pool with no exposure
                    playerPool.forEach(p => {
                      if (!seen.has(p.player_name || p.name)) {
                        const name = p.player_name || p.name;
                        seen.add(name);
                        allPlayers.push({
                          name,
                          position: p.position || '',
                          team: p.team || '',
                          salary: p.salary || 0,
                          count: 0,
                          pct: 0,
                          minExp: playerExposures[name]?.min ?? 0,
                          maxExp: playerExposures[name]?.max ?? 100,
                        });
                      }
                    });

                    const pitcherPositions = new Set(['P', 'SP', 'RP']);
                    const isPitcher = (pos) => {
                      if (!pos) return false;
                      return pos.split('/').some(p => pitcherPositions.has(p.trim()));
                    };

                    let posFiltered = allPlayers;
                    if (exposureFilter === 'pitchers') {
                      posFiltered = allPlayers.filter(p => isPitcher(p.position));
                    } else if (exposureFilter === 'hitters') {
                      posFiltered = allPlayers.filter(p => !isPitcher(p.position));
                    }

                    const query = exposureSearch.toLowerCase();
                    const filtered = query
                      ? posFiltered.filter(p => p.name.toLowerCase().includes(query) || (p.team || '').toLowerCase().includes(query))
                      : posFiltered;

                    if (filtered.length === 0) {
                      return (
                        <tr>
                          <td colSpan={7} className="px-4 py-12 text-center text-sm text-gray-500">
                            {lineups.length === 0 ? 'Build lineups to see exposure data' : 'No players match search'}
                          </td>
                        </tr>
                      );
                    }

                    return filtered.map((p, i) => {
                      const isOverMax = p.pct > (p.maxExp || 100);
                      const isUnderMin = p.pct > 0 && p.pct < (p.minExp || 0);
                      const barColor = isOverMax ? 'bg-red-500' : isUnderMin ? 'bg-amber-500' : 'bg-blue-500';

                      return (
                        <tr key={p.name} className={`${i % 2 === 0 ? 'bg-gray-950' : 'bg-gray-900/50'} hover:bg-gray-800/50 transition-colors`}>
                          <td className="px-3 py-1.5 text-xs text-gray-200">{p.name}</td>
                          <td className="px-3 py-1.5 text-[10px] font-mono text-gray-400">{p.position}</td>
                          <td className="px-3 py-1.5 text-[10px] font-mono text-gray-400">{p.team}</td>
                          <td className="px-2 py-1.5 text-center">
                            <input
                              type="number"
                              value={p.minExp}
                              min={0}
                              max={100}
                              onChange={(e) => {
                                const val = Math.max(0, Math.min(100, parseInt(e.target.value) || 0));
                                setPlayerExposures(prev => ({
                                  ...prev,
                                  [p.name]: { min: val, max: prev[p.name]?.max ?? p.maxExp ?? 100 },
                                }));
                              }}
                              className="w-12 bg-gray-800 border border-gray-700 rounded px-1.5 py-0.5 text-[10px] font-mono text-gray-200 text-center focus:outline-none focus:border-blue-500"
                            />
                          </td>
                          <td className="px-2 py-1.5 text-center">
                            <input
                              type="number"
                              value={p.maxExp}
                              min={0}
                              max={100}
                              onChange={(e) => {
                                const val = Math.max(0, Math.min(100, parseInt(e.target.value) || 0));
                                setPlayerExposures(prev => ({
                                  ...prev,
                                  [p.name]: { min: prev[p.name]?.min ?? p.minExp ?? 0, max: val },
                                }));
                              }}
                              className="w-12 bg-gray-800 border border-gray-700 rounded px-1.5 py-0.5 text-[10px] font-mono text-gray-200 text-center focus:outline-none focus:border-blue-500"
                            />
                          </td>
                          <td className="px-3 py-1.5 text-right">
                            <span className={`text-xs font-mono font-semibold ${
                              isOverMax ? 'text-red-400' : isUnderMin ? 'text-amber-400' : p.pct > 0 ? 'text-blue-400' : 'text-gray-600'
                            }`}>
                              {p.pct > 0 ? `${formatPct(p.pct, 1)}` : '—'}
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
          </div>
        )}

        {/* Team Stacks Tab */}
        {rightTab === 'teamExposure' && (
          <div className="rounded-lg border border-gray-800 overflow-hidden">
            <div className="data-table-container overflow-x-auto" style={{ maxHeight: 'calc(100vh - 200px)' }}>
              <table className="w-full text-left min-w-[700px]">
                <thead>
                  <tr className="bg-gray-900">
                    <th className="px-3 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-500">Team</th>
                    <th className="px-2 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-500 text-center" colSpan={3}>3-Man Stack</th>
                    <th className="px-2 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-500 text-center" colSpan={3}>4-Man Stack</th>
                    <th className="px-2 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-500 text-center" colSpan={3}>5-Man Stack</th>
                    <th className="px-3 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-500 text-right">Avg Hit</th>
                  </tr>
                  <tr className="bg-gray-900 border-t border-gray-800">
                    <th />
                    {[3, 4, 5].map(sz => (
                      <React.Fragment key={sz}>
                        <th className="px-1 pb-1.5 text-[9px] uppercase text-gray-600 text-center">Min</th>
                        <th className="px-1 pb-1.5 text-[9px] uppercase text-gray-600 text-center">Max</th>
                        <th className="px-1 pb-1.5 text-[9px] uppercase text-gray-600 text-center">Actual</th>
                      </React.Fragment>
                    ))}
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {(() => {
                    const allTeams = [...new Set([
                      ...teamStackData.map(t => t.team),
                      ...stackTeams,
                    ])].sort((a, b) => {
                      const aData = teamStackData.find(t => t.team === a);
                      const bData = teamStackData.find(t => t.team === b);
                      return (bData?.stack4Pct || 0) - (aData?.stack4Pct || 0) || a.localeCompare(b);
                    });

                    if (allTeams.length === 0) {
                      return (
                        <tr>
                          <td colSpan={11} className="px-4 py-12 text-center text-sm text-gray-500">
                            {lineups.length === 0 ? 'Build lineups to see team stack data' : 'No team data available'}
                          </td>
                        </tr>
                      );
                    }

                    return allTeams.map((team, i) => {
                      const data = teamStackData.find(t => t.team === team) || {
                        stack3Pct: 0, stack4Pct: 0, stack5Pct: 0, avgHitters: 0,
                      };
                      const se = stackExposures[team] || {};

                      const renderStackCell = (size, actualPct) => {
                        const key = `stack_${size}`;
                        const minVal = se[key]?.min ?? 0;
                        const maxVal = se[key]?.max ?? 100;
                        const isOver = actualPct > maxVal;
                        const isUnder = actualPct > 0 && actualPct < minVal;

                        return (
                          <>
                            <td className="px-1 py-1.5 text-center">
                              <input
                                type="number"
                                value={minVal}
                                min={0}
                                max={100}
                                onChange={(e) => {
                                  const val = Math.max(0, Math.min(100, parseInt(e.target.value) || 0));
                                  setStackExposures(prev => ({
                                    ...prev,
                                    [team]: {
                                      ...prev[team],
                                      [key]: { min: val, max: prev[team]?.[key]?.max ?? 100 },
                                    },
                                  }));
                                }}
                                className="w-11 bg-gray-800 border border-gray-700 rounded px-1 py-0.5 text-[10px] font-mono text-gray-200 text-center focus:outline-none focus:border-blue-500"
                              />
                            </td>
                            <td className="px-1 py-1.5 text-center">
                              <input
                                type="number"
                                value={maxVal}
                                min={0}
                                max={100}
                                onChange={(e) => {
                                  const val = Math.max(0, Math.min(100, parseInt(e.target.value) || 0));
                                  setStackExposures(prev => ({
                                    ...prev,
                                    [team]: {
                                      ...prev[team],
                                      [key]: { min: prev[team]?.[key]?.min ?? 0, max: val },
                                    },
                                  }));
                                }}
                                className="w-11 bg-gray-800 border border-gray-700 rounded px-1 py-0.5 text-[10px] font-mono text-gray-200 text-center focus:outline-none focus:border-blue-500"
                              />
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
                        <tr key={team} className={`${i % 2 === 0 ? 'bg-gray-950' : 'bg-gray-900/50'} hover:bg-gray-800/50 transition-colors`}>
                          <td className="px-3 py-1.5 text-xs font-semibold text-gray-200">{team}</td>
                          {renderStackCell(3, data.stack3Pct)}
                          {renderStackCell(4, data.stack4Pct)}
                          {renderStackCell(5, data.stack5Pct)}
                          <td className="px-3 py-1.5 text-right">
                            <span className="text-[10px] font-mono text-gray-400">
                              {data.avgHitters > 0 ? data.avgHitters.toFixed(1) : '—'}
                            </span>
                          </td>
                        </tr>
                      );
                    });
                  })()}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* Lineup Editor Modal */}
      {editingLineup && (
        <LineupEditor
          lineup={editingLineup}
          playerPool={playerPool}
          onSave={handleSaveEditedLineup}
          onCancel={() => setEditingLineup(null)}
        />
      )}
    </div>
  );
}


