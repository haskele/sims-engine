export default function SimProgress({ current, total, label = 'Running simulation...', eta = null }) {
  const pct = total > 0 ? Math.min((current / total) * 100, 100) : 0;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-sm">
        <span className="text-gray-300">{label}</span>
        <div className="flex items-center gap-3">
          {eta && <span className="text-gray-500 text-xs font-mono">ETA: {eta}</span>}
          <span className="text-gray-400 font-mono text-xs">
            {current.toLocaleString()} / {total.toLocaleString()}
          </span>
        </div>
      </div>
      <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
        <div
          className="h-full bg-gradient-to-r from-blue-600 to-emerald-500 rounded-full transition-all duration-300 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="text-right">
        <span className="text-xs font-mono text-gray-500">{pct.toFixed(1)}%</span>
      </div>
    </div>
  );
}
