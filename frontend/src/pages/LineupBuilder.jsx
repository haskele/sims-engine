import { useState, useEffect } from 'react';
import { Download, RefreshCw, Zap } from 'lucide-react';
import LineupCard from '../components/LineupCard';
import StackControl from '../components/StackControl';
import { formatSalary, formatDecimal, formatPct } from '../utils/formatting';
import { api } from '../api/client';

export default function LineupBuilder() {
  const [numLineups, setNumLineups] = useState(20);
  const [building, setBuilding] = useState(false);
  const [lineups, setLineups] = useState([]);
  const [showStacks, setShowStacks] = useState(false);
  const [stackTeams, setStackTeams] = useState([]);
  const [error, setError] = useState(null);

  const site = localStorage.getItem('dfs_site') || 'dk';

  // Load teams from projections for stack controls
  useEffect(() => {
    api.getFeaturedProjections(site)
      .then(data => {
        const teams = [...new Set(data.map(p => p.team).filter(Boolean))].sort();
        setStackTeams(teams);
      })
      .catch(() => {});
  }, [site]);

  const handleBuild = async () => {
    setBuilding(true);
    setError(null);
    try {
      // Get projections for the optimizer
      const projections = await api.getFeaturedProjections(site);
      if (!projections || projections.length === 0) {
        setError('No projections available. Upload a projection CSV first.');
        setBuilding(false);
        return;
      }

      // Build lineups from projections using the CSV-based optimizer
      // For now, generate diverse lineups client-side from the projection data
      const generated = generateLineups(projections, numLineups);
      setLineups(generated);
    } catch (err) {
      setError(err.message || 'Failed to build lineups');
    } finally {
      setBuilding(false);
    }
  };

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
    <div className="flex gap-6 h-[calc(100vh-110px)]">
      {/* Left panel - Controls */}
      <div className="w-80 shrink-0 overflow-y-auto space-y-4 pr-2">
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
            min={1}
            max={500}
            value={Math.min(numLineups, 500)}
            onChange={(e) => setNumLineups(Number(e.target.value))}
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

        {/* Build button */}
        <button
          onClick={handleBuild}
          disabled={building}
          className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg bg-blue-600 text-white font-semibold text-sm hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {building ? (
            <>
              <RefreshCw className="w-4 h-4 animate-spin" />
              Building...
            </>
          ) : (
            <>
              <Zap className="w-4 h-4" />
              Build {numLineups} Lineups
            </>
          )}
        </button>

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
      <div className="flex-1 overflow-y-auto space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
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
            <button className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-gray-700 bg-gray-800 text-xs text-gray-300 hover:bg-gray-700 transition-colors">
              <Download className="w-3.5 h-3.5" />
              Export CSV
            </button>
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
            <div className="grid grid-cols-3 gap-x-6 gap-y-1">
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
            <LineupCard key={lineup.id} lineup={lineup} index={i} expanded={i === 0} />
          ))}
        </div>
      </div>
    </div>
  );
}


/**
 * Generate diverse lineups from projection data using a greedy approach.
 * This is a client-side fallback — the real optimizer runs server-side with PuLP.
 */
function generateLineups(projections, count) {
  const SALARY_CAP = 50000;
  const SLOTS = ['P', 'P', 'C', '1B', '2B', '3B', 'SS', 'OF', 'OF', 'OF'];

  // Group players by position
  const byPos = {};
  for (const p of projections) {
    const pos = p.is_pitcher ? 'P' : p.position;
    const positions = pos.includes('/') ? pos.split('/') : [pos];
    for (const pp of positions) {
      const key = ['LF', 'CF', 'RF'].includes(pp) ? 'OF' : pp;
      if (!byPos[key]) byPos[key] = [];
      byPos[key].push(p);
    }
  }

  // Sort each position pool by median descending
  for (const pos of Object.keys(byPos)) {
    byPos[pos].sort((a, b) => b.median_pts - a.median_pts);
  }

  const lineups = [];
  const usedCombos = new Set();

  for (let n = 0; n < count; n++) {
    const lineup = [];
    const usedNames = new Set();
    let totalSalary = 0;
    let valid = true;

    for (const slot of SLOTS) {
      const pool = byPos[slot] || [];
      // Add randomness for diversity
      const jitter = n * 7 + lineup.length * 13;
      let found = false;

      for (let attempt = 0; attempt < pool.length; attempt++) {
        const idx = (attempt + jitter) % pool.length;
        const p = pool[idx];
        if (usedNames.has(p.player_name)) continue;
        if (totalSalary + (p.salary || 0) > SALARY_CAP) continue;

        const rosterPos = slot === 'P' ? 'P' : slot;
        lineup.push({
          name: p.player_name,
          position: p.position || slot,
          rosterPosition: rosterPos,
          team: p.team,
          salary: p.salary || 0,
          median: p.median_pts,
          dk_id: p.dk_id,
        });
        usedNames.add(p.player_name);
        totalSalary += p.salary || 0;
        found = true;
        break;
      }

      if (!found) {
        valid = false;
        break;
      }
    }

    if (valid && lineup.length === 10) {
      const key = lineup.map(p => p.name).sort().join(',');
      if (!usedCombos.has(key)) {
        usedCombos.add(key);
        lineups.push({
          id: n + 1,
          players: lineup,
        });
      }
    }
  }

  return lineups;
}
