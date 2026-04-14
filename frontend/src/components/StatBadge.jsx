const colorMap = {
  green: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  red: 'bg-red-500/15 text-red-400 border-red-500/30',
  blue: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
  amber: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  purple: 'bg-purple-500/15 text-purple-400 border-purple-500/30',
  gray: 'bg-gray-500/15 text-gray-400 border-gray-500/30',
  cyan: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30',
};

export default function StatBadge({ label, value, color = 'gray', className = '' }) {
  const colors = colorMap[color] || colorMap.gray;

  return (
    <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-xs font-mono ${colors} ${className}`}>
      {label && <span className="text-[10px] uppercase tracking-wider opacity-70 font-sans">{label}</span>}
      <span className="font-semibold">{value}</span>
    </div>
  );
}
