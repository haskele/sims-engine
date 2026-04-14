import { useState } from 'react';
import { PlayCircle, BarChart3, TrendingUp, DollarSign, Target, Activity } from 'lucide-react';
import SimProgress from '../components/SimProgress';
import ContestCard from '../components/ContestCard';
import StatBadge from '../components/StatBadge';
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

const mockContests = [
  { id: 1, name: 'DK $15 Main Slate MME', site: 'DraftKings', entryFee: 15, fieldSize: 12543, prizePool: 150000, entries: 20 },
  { id: 2, name: 'DK $5 Single Entry', site: 'DraftKings', entryFee: 5, fieldSize: 45000, prizePool: 200000, entries: 1 },
  { id: 3, name: 'DK $44 3-Entry Max', site: 'DraftKings', entryFee: 44, fieldSize: 3200, prizePool: 120000, entries: 3 },
];

const mockDistribution = [
  { range: '-100%', count: 120, color: '#ef4444' },
  { range: '-80%', count: 85, color: '#ef4444' },
  { range: '-60%', count: 140, color: '#ef4444' },
  { range: '-40%', count: 210, color: '#f59e0b' },
  { range: '-20%', count: 380, color: '#f59e0b' },
  { range: '0%', count: 520, color: '#6b7280' },
  { range: '+20%', count: 450, color: '#10b981' },
  { range: '+40%', count: 310, color: '#10b981' },
  { range: '+60%', count: 180, color: '#10b981' },
  { range: '+80%', count: 95, color: '#10b981' },
  { range: '+100%', count: 55, color: '#22c55e' },
  { range: '+150%', count: 30, color: '#22c55e' },
  { range: '+200%+', count: 15, color: '#22c55e' },
];

const mockLineupResults = [
  { id: 1, label: 'Lineup #1', avgPts: 142.5, avgROI: 18.3, cashRate: 72.1, winRate: 0.12, top10Rate: 2.4 },
  { id: 2, label: 'Lineup #2', avgPts: 138.2, avgROI: 12.7, cashRate: 68.5, winRate: 0.08, top10Rate: 1.9 },
  { id: 3, label: 'Lineup #3', avgPts: 145.1, avgROI: 22.5, cashRate: 75.3, winRate: 0.18, top10Rate: 3.1 },
  { id: 4, label: 'Lineup #4', avgPts: 135.8, avgROI: 8.4, cashRate: 62.0, winRate: 0.05, top10Rate: 1.2 },
  { id: 5, label: 'Lineup #5', avgPts: 140.3, avgROI: 15.1, cashRate: 69.8, winRate: 0.10, top10Rate: 2.0 },
  { id: 6, label: 'Lineup #6', avgPts: 137.0, avgROI: 10.2, cashRate: 64.2, winRate: 0.06, top10Rate: 1.5 },
  { id: 7, label: 'Lineup #7', avgPts: 143.8, avgROI: 20.1, cashRate: 73.5, winRate: 0.14, top10Rate: 2.8 },
  { id: 8, label: 'Lineup #8', avgPts: 132.5, avgROI: 5.3, cashRate: 58.1, winRate: 0.03, top10Rate: 0.9 },
  { id: 9, label: 'Lineup #9', avgPts: 141.2, avgROI: 16.8, cashRate: 70.5, winRate: 0.11, top10Rate: 2.2 },
  { id: 10, label: 'Lineup #10', avgPts: 139.5, avgROI: 13.9, cashRate: 67.3, winRate: 0.09, top10Rate: 1.8 },
];

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

export default function Simulator() {
  const [selectedContest, setSelectedContest] = useState(mockContests[0]);
  const [numSims, setNumSims] = useState(10000);
  const [numLineups, setNumLineups] = useState(20);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [hasResults, setHasResults] = useState(true);
  const [resultSort, setResultSort] = useState('avgROI');
  const [resultSortDir, setResultSortDir] = useState('desc');

  const handleRun = () => {
    setRunning(true);
    setProgress(0);
    setHasResults(false);

    // Simulate progress
    let p = 0;
    const interval = setInterval(() => {
      p += Math.random() * 15;
      if (p >= 100) {
        p = 100;
        clearInterval(interval);
        setRunning(false);
        setHasResults(true);
      }
      setProgress(Math.min(p, 100));
    }, 300);
  };

  const estTime = Math.round((numSims * numLineups) / 50000);

  const sortedResults = [...mockLineupResults].sort((a, b) => {
    const aVal = a[resultSort];
    const bVal = b[resultSort];
    return resultSortDir === 'desc' ? bVal - aVal : aVal - bVal;
  });

  const handleResultSort = (key) => {
    if (resultSort === key) {
      setResultSortDir(resultSortDir === 'desc' ? 'asc' : 'desc');
    } else {
      setResultSort(key);
      setResultSortDir('desc');
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-gray-100">Simulator</h1>
        <p className="text-sm text-gray-500 mt-0.5">Contest simulation engine</p>
      </div>

      <div className="grid grid-cols-3 gap-6">
        {/* Setup panel */}
        <div className="space-y-4">
          <h2 className="text-sm font-semibold text-gray-300">Setup</h2>

          {/* Contest selection */}
          <div className="space-y-2">
            <span className="text-xs text-gray-400">Select Contest</span>
            {mockContests.map((c) => (
              <ContestCard
                key={c.id}
                contest={c}
                selected={selectedContest?.id === c.id}
                onClick={() => setSelectedContest(c)}
              />
            ))}
          </div>

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

          {/* Lineup count */}
          <div className="rounded-lg border border-gray-800 bg-gray-900 p-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-gray-300">Lineup Candidates</span>
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
          </div>

          {/* Estimated time */}
          <div className="rounded-lg border border-gray-800 bg-gray-900 px-4 py-3 flex items-center justify-between">
            <span className="text-xs text-gray-400">Estimated Run Time</span>
            <span className="text-sm font-mono text-gray-200">{estTime < 1 ? '<1' : estTime}s</span>
          </div>

          {/* Run button */}
          <button
            onClick={handleRun}
            disabled={running}
            className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg bg-emerald-600 text-white font-semibold text-sm hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <PlayCircle className="w-4 h-4" />
            {running ? 'Running...' : 'Run Simulation'}
          </button>

          {/* Progress */}
          {running && (
            <SimProgress
              current={Math.round((progress / 100) * numSims)}
              total={numSims}
              label="Simulating contests..."
              eta={`${Math.max(0, Math.round(estTime * (1 - progress / 100)))}s`}
            />
          )}
        </div>

        {/* Results panel */}
        <div className="col-span-2 space-y-4">
          {hasResults ? (
            <>
              {/* Key metrics */}
              <div className="grid grid-cols-4 gap-3">
                <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[10px] uppercase tracking-wider text-gray-500">Avg ROI</span>
                    <TrendingUp className="w-4 h-4 text-emerald-400" />
                  </div>
                  <div className="text-2xl font-bold font-mono text-emerald-400">+14.3%</div>
                  <div className="text-[10px] text-gray-500 mt-1">across {numSims.toLocaleString()} sims</div>
                </div>
                <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[10px] uppercase tracking-wider text-gray-500">Cash Rate</span>
                    <DollarSign className="w-4 h-4 text-blue-400" />
                  </div>
                  <div className="text-2xl font-bold font-mono text-blue-400">68.2%</div>
                  <div className="text-[10px] text-gray-500 mt-1">ITM frequency</div>
                </div>
                <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[10px] uppercase tracking-wider text-gray-500">Win Rate</span>
                    <Target className="w-4 h-4 text-amber-400" />
                  </div>
                  <div className="text-2xl font-bold font-mono text-amber-400">0.09%</div>
                  <div className="text-[10px] text-gray-500 mt-1">1st place</div>
                </div>
                <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[10px] uppercase tracking-wider text-gray-500">ROI Std Dev</span>
                    <Activity className="w-4 h-4 text-purple-400" />
                  </div>
                  <div className="text-2xl font-bold font-mono text-purple-400">42.1%</div>
                  <div className="text-[10px] text-gray-500 mt-1">variance</div>
                </div>
              </div>

              {/* ROI Distribution Chart */}
              <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
                <h3 className="text-xs font-semibold text-gray-400 mb-4 flex items-center gap-2">
                  <BarChart3 className="w-4 h-4" />
                  ROI Distribution
                </h3>
                <div className="h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={mockDistribution} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
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
                        {mockDistribution.map((entry, index) => (
                          <Cell key={index} fill={entry.color} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>

              {/* Lineup results table */}
              <div className="rounded-lg border border-gray-800 bg-gray-900 overflow-hidden">
                <div className="px-4 py-2.5 border-b border-gray-800">
                  <h3 className="text-xs font-semibold text-gray-400">Lineup Results</h3>
                </div>
                <div className="data-table-container" style={{ maxHeight: '320px' }}>
                  <table className="w-full text-left">
                    <thead>
                      <tr className="bg-gray-900">
                        {[
                          { key: 'label', label: 'Lineup', align: '' },
                          { key: 'avgPts', label: 'Avg Pts', align: 'text-right' },
                          { key: 'avgROI', label: 'Avg ROI', align: 'text-right' },
                          { key: 'cashRate', label: 'Cash Rate', align: 'text-right' },
                          { key: 'winRate', label: 'Win Rate', align: 'text-right' },
                          { key: 'top10Rate', label: 'Top 10%', align: 'text-right' },
                        ].map((col) => (
                          <th
                            key={col.key}
                            onClick={() => handleResultSort(col.key)}
                            className={`px-4 py-2 text-[10px] uppercase tracking-wider font-semibold text-gray-500 bg-gray-900 cursor-pointer hover:text-gray-300 ${col.align}`}
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
                      {sortedResults.map((r, i) => (
                        <tr
                          key={r.id}
                          className={`${i % 2 === 0 ? 'bg-gray-950' : 'bg-gray-900/50'} hover:bg-gray-800/50 transition-colors`}
                        >
                          <td className="px-4 py-2 text-xs text-gray-300">{r.label}</td>
                          <td className="px-4 py-2 text-xs font-mono text-gray-200 text-right">{formatDecimal(r.avgPts)}</td>
                          <td className="px-4 py-2 text-right">
                            <span className={`text-xs font-mono font-semibold ${r.avgROI >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                              {r.avgROI > 0 ? '+' : ''}{formatDecimal(r.avgROI)}%
                            </span>
                          </td>
                          <td className="px-4 py-2 text-xs font-mono text-gray-300 text-right">{formatPct(r.cashRate)}</td>
                          <td className="px-4 py-2 text-xs font-mono text-gray-400 text-right">{formatPct(r.winRate, 2)}</td>
                          <td className="px-4 py-2 text-xs font-mono text-gray-400 text-right">{formatPct(r.top10Rate)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          ) : (
            <div className="flex flex-col items-center justify-center h-96 text-gray-500">
              <BarChart3 className="w-12 h-12 mb-4 text-gray-700" />
              <p className="text-sm">Select a contest and run a simulation to see results</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
