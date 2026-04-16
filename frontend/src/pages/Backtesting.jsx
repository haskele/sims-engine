import { History, Calendar, TrendingUp, BarChart3, Lock } from 'lucide-react';

export default function Backtesting() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-gray-100">Backtesting</h1>
        <p className="text-sm text-gray-500 mt-0.5">Historical simulation performance review</p>
      </div>

      {/* Coming soon overlay */}
      <div className="rounded-lg border border-gray-800 bg-gray-900 p-12 flex flex-col items-center justify-center text-center">
        <div className="w-16 h-16 rounded-full bg-gray-800 flex items-center justify-center mb-4">
          <Lock className="w-8 h-8 text-gray-600" />
        </div>
        <h2 className="text-lg font-bold text-gray-200 mb-2">Coming Soon</h2>
        <p className="text-sm text-gray-500 max-w-md">
          Backtesting will allow you to review historical simulation performance,
          analyze projection accuracy, and optimize your strategy over time.
        </p>
      </div>

      {/* Mock layout preview */}
      <div className="opacity-40 pointer-events-none space-y-4">
        {/* Date range picker */}
        <div className="rounded-lg border border-gray-800 bg-gray-900 p-4 flex flex-wrap items-center gap-4">
          <Calendar className="w-4 h-4 text-gray-500" />
          <div className="flex items-center gap-2">
            <input
              type="date"
              disabled
              className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-xs text-gray-400"
              defaultValue="2024-06-01"
            />
            <span className="text-gray-600">to</span>
            <input
              type="date"
              disabled
              className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-xs text-gray-400"
              defaultValue="2024-06-30"
            />
          </div>
          <button className="px-3 py-1.5 rounded-lg bg-blue-600 text-white text-xs font-semibold" disabled>
            Analyze
          </button>
        </div>

        {/* Accuracy metrics */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: 'Projection RMSE', value: '4.82', icon: TrendingUp, color: 'text-blue-400' },
            { label: 'Avg ROI (Actual)', value: '+8.3%', icon: TrendingUp, color: 'text-emerald-400' },
            { label: 'Days Analyzed', value: '30', icon: Calendar, color: 'text-purple-400' },
            { label: 'Total Sims', value: '450', icon: BarChart3, color: 'text-amber-400' },
          ].map((stat) => (
            <div key={stat.label} className="rounded-lg border border-gray-800 bg-gray-900 p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] uppercase tracking-wider text-gray-500">{stat.label}</span>
                <stat.icon className={`w-4 h-4 ${stat.color}`} />
              </div>
              <div className={`text-2xl font-bold font-mono ${stat.color}`}>{stat.value}</div>
            </div>
          ))}
        </div>

        {/* Historical results table */}
        <div className="rounded-lg border border-gray-800 bg-gray-900 overflow-x-auto">
          <table className="w-full text-left min-w-[600px]">
            <thead>
              <tr className="border-b border-gray-800">
                {['Date', 'Contest', 'Lineups', 'Projected ROI', 'Actual ROI', 'Cash Rate', 'Best Finish'].map((h) => (
                  <th key={h} className="px-4 py-2 text-[10px] uppercase tracking-wider text-gray-500 font-semibold">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[
                { date: 'Jun 30', contest: 'DK $15 Main', lineups: 20, projROI: '+12.5%', actROI: '+18.2%', cashRate: '72%', bestFinish: '145th' },
                { date: 'Jun 29', contest: 'DK $5 Single', lineups: 1, projROI: '+8.1%', actROI: '-14.5%', cashRate: '0%', bestFinish: '8,542nd' },
                { date: 'Jun 28', contest: 'DK $15 Main', lineups: 20, projROI: '+15.2%', actROI: '+22.8%', cashRate: '80%', bestFinish: '52nd' },
                { date: 'Jun 27', contest: 'FD $9 Main', lineups: 15, projROI: '+10.8%', actROI: '+5.1%', cashRate: '60%', bestFinish: '312th' },
                { date: 'Jun 26', contest: 'DK $44 3-Max', lineups: 3, projROI: '+18.5%', actROI: '+42.1%', cashRate: '100%', bestFinish: '18th' },
              ].map((row, i) => (
                <tr key={i} className={`${i % 2 === 0 ? 'bg-gray-950' : 'bg-gray-900/50'}`}>
                  <td className="px-4 py-2.5 text-xs text-gray-400">{row.date}</td>
                  <td className="px-4 py-2.5 text-xs text-gray-200">{row.contest}</td>
                  <td className="px-4 py-2.5 text-xs font-mono text-gray-300">{row.lineups}</td>
                  <td className="px-4 py-2.5 text-xs font-mono text-gray-400">{row.projROI}</td>
                  <td className="px-4 py-2.5">
                    <span className={`text-xs font-mono font-semibold ${row.actROI.startsWith('+') ? 'text-emerald-400' : 'text-red-400'}`}>
                      {row.actROI}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-xs font-mono text-gray-300">{row.cashRate}</td>
                  <td className="px-4 py-2.5 text-xs text-gray-400">{row.bestFinish}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
