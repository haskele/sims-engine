import { useState, useEffect, useRef, useCallback } from 'react';
import { Download, RefreshCw, Zap, Trash2, XCircle } from 'lucide-react';
import LineupCard from '../components/LineupCard';
import LineupEditor from '../components/LineupEditor';
import StackControl from '../components/StackControl';
import { formatSalary, formatDecimal, formatPct } from '../utils/formatting';
import { api, AbortError } from '../api/client';
import { useApp } from '../context/AppContext';

export default function LineupBuilder() {
  const { site, selectedSlate, getCurrentBuild, updateCurrentBuildLineups, stackExposures, selectedDate } = useApp();
  const [numLineups, setNumLineups] = useState(20);
  const [variance, setVariance] = useState(0.15);
  const [skew, setSkew] = useState('neutral');
  const [building, setBuilding] = useState(false);
  const [showStacks, setShowStacks] = useState(false);
  const [stackTeams, setStackTeams] = useState([]);
  const [error, setError] = useState(null);
  const [confirmClear, setConfirmClear] = useState(false);

  // Player pool cache for the editor
  const [playerPool, setPlayerPool] = useState([]);
  const playerPoolSlateRef = useRef(null);

  // Abort controller for cancelling builds
  const abortRef = useRef(null);

  useEffect(() => {
    return () => {
      if (abortRef.current) abortRef.current.abort();
    };
  }, []);

  const handleCancel = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setBuilding(false);
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

      const result = await api.buildLineupsCSV({
        site,
        n_lineups: numLineups,
        min_unique: 3,
        objective: 'median_pts',
        variance,
        skew,
        target_date: selectedDate,
        stack_exposures: stackConfig,
      }, controller.signal);

      if (!result.lineups || result.lineups.length === 0) {
        setError('No lineups generated. Upload a projection CSV first.');
        setBuilding(false);
        return;
      }

      const generated = result.lineups.map((lu, i) => ({
        id: i + 1,
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
      updateCurrentBuildLineups(generated);
    } catch (err) {
      if (err instanceof AbortError || err.name === 'AbortError') return;
      setError(err.message || 'Failed to build lineups');
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setBuilding(false);
    }
  };

  const handleClear = () => {
    if (confirmClear) {
      updateCurrentBuildLineups([]);
      setConfirmClear(false);
    } else {
      setConfirmClear(true);
    }
  };

  const cancelClear = () => setConfirmClear(false);

  const avgSalary = lineups.length > 0
    ? lineups.reduce((sum, l) => sum + l.players.reduce((s, p) => s + p.salary, 0), 0) / lineups.length
    : 0;

  const avgProj = lineups.length > 0
    ? lineups.reduce((sum, l) => sum + l.players.reduce((s, p) => s + p.median, 0), 0) / lineups.length
    : 0;

  // Calculate exposure
  const exposureMap = {};
  lineups.forEach((l) => {
    l.players.forEach((p) => {
      exposureMap[p.name] = (exposureMap[p.name] || 0) + 1;
    });
  });

  const exposureList = Object.entries(exposureMap)
    .map(([name, count]) => ({ name, count, pct: (count / lineups.length) * 100 }))
    .sort((a, b) => b.pct - a.pct)
    .slice(0, 15);

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
              numLineups <= 100 ? ((numLineups - 1) / 99) * 50 :
              numLineups <= 500 ? 50 + ((numLineups - 100) / 400) * 50 :
              100
            }
            onChange={(e) => {
              const pct = Number(e.target.value);
              let val;
              if (pct <= 50) {
                val = Math.round(1 + (pct / 50) * 99);
              } else {
                val = Math.round(100 + ((pct - 50) / 50) * 400);
              }
              setNumLineups(val);
            }}
            className="w-full"
          />
          <div className="flex justify-between text-[10px] text-gray-600 font-mono">
            <span>1</span>
            <span>100</span>
            <span>250</span>
            <span>500</span>
          </div>
          <p className="text-[10px] text-gray-600">
            Or type any number above for larger pools
          </p>
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
                <StackControl key={team} team={team} onChange={() => {}} />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Right panel - Lineups */}
      <div className="flex-1 overflow-y-auto space-y-4 min-w-0">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2 sm:gap-4">
            <h2 className="text-sm font-semibold text-gray-300">
              Generated Lineups ({lineups.length})
            </h2>
            {lineups.length > 0 && (
              <div className="flex items-center gap-3">
                <div className="text-xs text-gray-500">
                  Avg Salary: <span className="font-mono text-gray-300">{formatSalary(Math.round(avgSalary))}</span>
                </div>
                <div className="text-xs text-gray-500">
                  Avg Proj: <span className="font-mono text-emerald-400">{formatDecimal(avgProj)}</span>
                </div>
              </div>
            )}
          </div>
          {lineups.length > 0 && (
            <div className="flex items-center gap-2">
              {confirmClear ? (
                <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-red-800/50 bg-gray-800 text-xs">
                  <span className="text-gray-400">Clear all?</span>
                  <button
                    onClick={handleClear}
                    className="text-red-400 hover:text-red-300 font-medium"
                  >
                    Yes
                  </button>
                  <span className="text-gray-600">/</span>
                  <button
                    onClick={cancelClear}
                    className="text-gray-400 hover:text-gray-300"
                  >
                    No
                  </button>
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
        </div>

        {lineups.length === 0 && !building && (
          <div className="text-center py-20 text-gray-600">
            <Zap className="w-10 h-10 mx-auto mb-3 opacity-30" />
            <p className="text-sm">Click "Build Lineups" to generate optimized lineups</p>
            <p className="text-xs mt-1">Set exposure limits on the Projections tab</p>
          </div>
        )}

        {/* Exposure breakdown */}
        {exposureList.length > 0 && (
          <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
            <h3 className="text-xs font-semibold text-gray-400 mb-3">Exposure Breakdown</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-1">
              {exposureList.map((e) => (
                <div key={e.name} className="flex items-center justify-between">
                  <span className="text-xs text-gray-300 truncate mr-2">{e.name}</span>
                  <div className="flex items-center gap-2">
                    <div className="w-16 h-1.5 bg-gray-800 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-blue-500 rounded-full"
                        style={{ width: `${e.pct}%` }}
                      />
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

        {/* Lineup cards */}
        <div className="space-y-2">
          {lineups.map((lineup, i) => (
            <LineupCard
              key={lineup.id}
              lineup={lineup}
              index={i}
              expanded={i === 0}
              onEdit={handleEditLineup}
            />
          ))}
        </div>
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


