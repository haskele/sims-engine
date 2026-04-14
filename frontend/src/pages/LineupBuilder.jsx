import { useState } from 'react';
import { Wrench, Download, RefreshCw, Zap } from 'lucide-react';
import LineupCard from '../components/LineupCard';
import ExposureSlider from '../components/ExposureSlider';
import StackControl from '../components/StackControl';
import { formatSalary, formatDecimal, formatPct } from '../utils/formatting';

const mockExposurePlayers = [
  { name: 'Aaron Judge', min: 20, max: 80 },
  { name: 'Shohei Ohtani', min: 15, max: 70 },
  { name: 'Mookie Betts', min: 10, max: 60 },
  { name: 'Gerrit Cole', min: 25, max: 85 },
  { name: 'Zack Wheeler', min: 20, max: 75 },
  { name: 'Trea Turner', min: 5, max: 50 },
  { name: 'Corey Seager', min: 10, max: 55 },
  { name: 'Rafael Devers', min: 5, max: 45 },
  { name: 'Juan Soto', min: 10, max: 60 },
  { name: 'Freddie Freeman', min: 15, max: 65 },
];

const stackTeams = ['LAD', 'NYY', 'ATL', 'PHI', 'TEX', 'BAL', 'MIN', 'MIL', 'CHC', 'CIN'];

const mockLineups = [
  {
    id: 1,
    players: [
      { name: 'Gerrit Cole', position: 'P', rosterPosition: 'P', team: 'NYY', salary: 10200, median: 21.8 },
      { name: 'Zack Wheeler', position: 'P', rosterPosition: 'P', team: 'PHI', salary: 10000, median: 22.5 },
      { name: 'J.T. Realmuto', position: 'C', rosterPosition: 'C', team: 'PHI', salary: 4000, median: 5.8 },
      { name: 'Shohei Ohtani', position: '1B', rosterPosition: '1B', team: 'LAD', salary: 6500, median: 11.5 },
      { name: 'Marcus Semien', position: '2B', rosterPosition: '2B', team: 'TEX', salary: 4800, median: 8.2 },
      { name: 'Rafael Devers', position: '3B', rosterPosition: '3B', team: 'BOS', salary: 5300, median: 8.8 },
      { name: 'Trea Turner', position: 'SS', rosterPosition: 'SS', team: 'PHI', salary: 5200, median: 9.1 },
      { name: 'Aaron Judge', position: 'OF', rosterPosition: 'OF', team: 'NYY', salary: 6200, median: 10.8 },
      { name: 'Mookie Betts', position: 'OF', rosterPosition: 'OF', team: 'LAD', salary: 5900, median: 10.2 },
      { name: 'Christian Yelich', position: 'OF', rosterPosition: 'OF', team: 'MIL', salary: 4500, median: 7.5 },
    ],
  },
  {
    id: 2,
    players: [
      { name: 'Tarik Skubal', position: 'P', rosterPosition: 'P', team: 'DET', salary: 9600, median: 21.0 },
      { name: 'Corbin Burnes', position: 'P', rosterPosition: 'P', team: 'BAL', salary: 9400, median: 20.0 },
      { name: 'Adley Rutschman', position: 'C', rosterPosition: 'C', team: 'BAL', salary: 4100, median: 6.2 },
      { name: 'Bryce Harper', position: '1B', rosterPosition: '1B', team: 'PHI', salary: 5400, median: 9.2 },
      { name: 'Ozzie Albies', position: '2B', rosterPosition: '2B', team: 'ATL', salary: 4400, median: 6.5 },
      { name: 'Jose Ramirez', position: '3B', rosterPosition: '3B', team: 'CLE', salary: 5100, median: 8.5 },
      { name: 'Gunnar Henderson', position: 'SS', rosterPosition: 'SS', team: 'BAL', salary: 5200, median: 8.8 },
      { name: 'Ronald Acuna Jr.', position: 'OF', rosterPosition: 'OF', team: 'ATL', salary: 5800, median: 9.8 },
      { name: 'Kyle Tucker', position: 'OF', rosterPosition: 'OF', team: 'HOU', salary: 5100, median: 8.6 },
      { name: 'Ian Happ', position: 'OF', rosterPosition: 'OF', team: 'CHC', salary: 4200, median: 6.8 },
    ],
  },
  {
    id: 3,
    players: [
      { name: 'Chris Sale', position: 'P', rosterPosition: 'P', team: 'ATL', salary: 9500, median: 19.8 },
      { name: 'Logan Gilbert', position: 'P', rosterPosition: 'P', team: 'SEA', salary: 8800, median: 18.5 },
      { name: 'Salvador Perez', position: 'C', rosterPosition: 'C', team: 'KC', salary: 3800, median: 5.5 },
      { name: 'Matt Olson', position: '1B', rosterPosition: '1B', team: 'ATL', salary: 5100, median: 8.7 },
      { name: 'Marcus Semien', position: '2B', rosterPosition: '2B', team: 'TEX', salary: 4800, median: 8.2 },
      { name: 'Corey Seager', position: '3B', rosterPosition: '3B', team: 'TEX', salary: 5400, median: 8.9 },
      { name: 'Bobby Witt Jr.', position: 'SS', rosterPosition: 'SS', team: 'KC', salary: 5500, median: 9.3 },
      { name: 'Juan Soto', position: 'OF', rosterPosition: 'OF', team: 'NYM', salary: 5700, median: 9.6 },
      { name: 'Yordan Alvarez', position: 'OF', rosterPosition: 'OF', team: 'HOU', salary: 5300, median: 9.0 },
      { name: 'Julio Rodriguez', position: 'OF', rosterPosition: 'OF', team: 'SEA', salary: 4900, median: 7.8 },
    ],
  },
  {
    id: 4,
    players: [
      { name: 'Yoshinobu Yamamoto', position: 'P', rosterPosition: 'P', team: 'LAD', salary: 9800, median: 20.5 },
      { name: 'Framber Valdez', position: 'P', rosterPosition: 'P', team: 'HOU', salary: 8500, median: 17.0 },
      { name: 'J.T. Realmuto', position: 'C', rosterPosition: 'C', team: 'PHI', salary: 4000, median: 5.8 },
      { name: 'Freddie Freeman', position: '1B', rosterPosition: '1B', team: 'LAD', salary: 5600, median: 9.5 },
      { name: 'Ozzie Albies', position: '2B', rosterPosition: '2B', team: 'ATL', salary: 4400, median: 6.5 },
      { name: 'Rafael Devers', position: '3B', rosterPosition: '3B', team: 'BOS', salary: 5300, median: 8.8 },
      { name: 'Elly De La Cruz', position: 'SS', rosterPosition: 'SS', team: 'CIN', salary: 5000, median: 7.5 },
      { name: 'Mookie Betts', position: 'OF', rosterPosition: 'OF', team: 'LAD', salary: 5900, median: 10.2 },
      { name: 'Adolis Garcia', position: 'OF', rosterPosition: 'OF', team: 'TEX', salary: 4600, median: 7.2 },
      { name: 'Byron Buxton', position: 'OF', rosterPosition: 'OF', team: 'MIN', salary: 4400, median: 6.8 },
    ],
  },
];

export default function LineupBuilder() {
  const [numLineups, setNumLineups] = useState(20);
  const [building, setBuilding] = useState(false);
  const [lineups, setLineups] = useState(mockLineups);
  const [showExposure, setShowExposure] = useState(true);
  const [showStacks, setShowStacks] = useState(false);

  const handleBuild = () => {
    setBuilding(true);
    setTimeout(() => setBuilding(false), 1500);
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
            <span className="text-sm font-mono font-bold text-blue-400">{numLineups}</span>
          </div>
          <input
            type="range"
            min={1}
            max={150}
            value={numLineups}
            onChange={(e) => setNumLineups(Number(e.target.value))}
            className="w-full"
          />
          <div className="flex justify-between text-[10px] text-gray-600 font-mono">
            <span>1</span>
            <span>50</span>
            <span>100</span>
            <span>150</span>
          </div>
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

        {/* Player Exposure */}
        <div className="rounded-lg border border-gray-800 bg-gray-900 overflow-hidden">
          <button
            onClick={() => setShowExposure(!showExposure)}
            className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-gray-800/40 transition-colors"
          >
            <span className="text-xs font-semibold text-gray-300">Player Exposure</span>
            <span className="text-[10px] text-gray-500">{showExposure ? 'Hide' : 'Show'}</span>
          </button>
          {showExposure && (
            <div className="px-4 pb-3 space-y-1 border-t border-gray-800 pt-2">
              {mockExposurePlayers.map((p) => (
                <ExposureSlider
                  key={p.name}
                  playerName={p.name}
                  min={p.min}
                  max={p.max}
                  onChange={() => {}}
                />
              ))}
            </div>
          )}
        </div>

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
            <div className="flex items-center gap-3">
              <div className="text-xs text-gray-500">
                Avg Salary: <span className="font-mono text-gray-300">{formatSalary(Math.round(avgSalary))}</span>
              </div>
              <div className="text-xs text-gray-500">
                Avg Proj: <span className="font-mono text-emerald-400">{formatDecimal(avgProj)}</span>
              </div>
            </div>
          </div>
          <button className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-gray-700 bg-gray-800 text-xs text-gray-300 hover:bg-gray-700 transition-colors">
            <Download className="w-3.5 h-3.5" />
            Export CSV
          </button>
        </div>

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
