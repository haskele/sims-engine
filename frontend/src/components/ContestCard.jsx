import { Trophy, Users, DollarSign } from 'lucide-react';
import { formatCurrency, formatCompact } from '../utils/formatting';

export default function ContestCard({ contest, onClick, selected = false }) {
  return (
    <div
      onClick={onClick}
      className={`rounded-lg border p-4 cursor-pointer transition-all hover:border-gray-600 ${
        selected
          ? 'border-blue-500 bg-blue-500/5'
          : 'border-gray-800 bg-gray-900'
      }`}
    >
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-100">{contest.name}</h3>
          <p className="text-xs text-gray-500 mt-0.5">{contest.site}</p>
        </div>
        <Trophy className={`w-4 h-4 ${selected ? 'text-blue-400' : 'text-gray-600'}`} />
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-0.5">Entry</div>
          <div className="text-sm font-mono text-gray-200">{formatCurrency(contest.entryFee)}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-0.5">Field</div>
          <div className="text-sm font-mono text-gray-200 flex items-center gap-1">
            <Users className="w-3 h-3 text-gray-500" />
            {formatCompact(contest.fieldSize)}
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-0.5">Prize</div>
          <div className="text-sm font-mono text-emerald-400 flex items-center gap-1">
            <DollarSign className="w-3 h-3" />
            {formatCompact(contest.prizePool)}
          </div>
        </div>
      </div>

      {contest.entries && (
        <div className="mt-3 pt-2 border-t border-gray-800">
          <span className="text-xs text-gray-500">
            {contest.entries} {contest.entries === 1 ? 'entry' : 'entries'}
          </span>
        </div>
      )}
    </div>
  );
}
