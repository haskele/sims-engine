import { useState, useEffect, useCallback } from 'react';
import { X, ChevronRight } from 'lucide-react';
import { formatCurrency } from '../utils/formatting';

function ordinal(n) {
  const s = ['th', 'st', 'nd', 'rd'];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

function formatPosition(minPos, maxPos) {
  if (minPos === maxPos) return ordinal(minPos);
  return `${ordinal(minPos)} - ${ordinal(maxPos)}`;
}

function normalizeTier(tier, index) {
  return {
    minPosition: tier.minPosition || tier.MinPosition || tier.place || index + 1,
    maxPosition: tier.maxPosition || tier.MaxPosition || tier.minPosition || tier.MinPosition || tier.place || index + 1,
    payout: Number(tier.payout || tier.Payout || tier.prize || 0),
  };
}

export default function PayoutDisplay({ payoutStructure = [] }) {
  const [open, setOpen] = useState(false);

  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Escape') setOpen(false);
  }, []);

  useEffect(() => {
    if (open) {
      document.addEventListener('keydown', handleKeyDown);
      document.body.style.overflow = 'hidden';
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = '';
    };
  }, [open, handleKeyDown]);

  if (!payoutStructure || payoutStructure.length === 0) {
    return <span className="text-gray-500">--</span>;
  }

  const normalized = payoutStructure.map((t, i) => normalizeTier(t, i));
  const top3 = normalized.slice(0, Math.min(3, normalized.length));

  return (
    <>
      <div className="space-y-1">
        {top3.map((tier, i) => (
          <div key={i} className="flex items-center justify-between text-xs">
            <span className="text-gray-400">{ordinal(tier.minPosition)}:</span>
            <span className="font-mono text-emerald-400 ml-2">{formatCurrency(tier.payout, 2)}</span>
          </div>
        ))}
        {normalized.length > 3 && (
          <button
            onClick={() => setOpen(true)}
            className="flex items-center gap-0.5 text-[10px] text-blue-400 hover:text-blue-300 transition-colors mt-1"
          >
            View All ({normalized.length} tiers)
            <ChevronRight className="w-3 h-3" />
          </button>
        )}
      </div>

      {/* Full payout modal */}
      {open && (
        <div
          className="fixed inset-0 z-50 flex items-end sm:items-center justify-center"
          onClick={() => setOpen(false)}
        >
          {/* Backdrop */}
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />

          {/* Modal panel */}
          <div
            className="relative w-full sm:max-w-md max-h-[80vh] bg-gray-900 border border-gray-700 rounded-t-2xl sm:rounded-2xl shadow-2xl flex flex-col animate-slide-up"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800 shrink-0">
              <h3 className="text-sm font-bold text-gray-100">Payout Structure</h3>
              <button
                onClick={() => setOpen(false)}
                className="p-1 rounded-lg hover:bg-gray-800 text-gray-400 hover:text-gray-200 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Table */}
            <div className="overflow-y-auto flex-1 px-5 py-3">
              <table className="w-full">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wider text-gray-500">
                    <th className="text-left pb-2 font-semibold">Position</th>
                    <th className="text-right pb-2 font-semibold">Payout</th>
                  </tr>
                </thead>
                <tbody>
                  {normalized.map((tier, i) => (
                    <tr
                      key={i}
                      className={`${i % 2 === 0 ? 'bg-gray-950/50' : ''} transition-colors`}
                    >
                      <td className="py-1.5 px-2 text-xs text-gray-300 rounded-l">
                        {formatPosition(tier.minPosition, tier.maxPosition)}
                      </td>
                      <td className="py-1.5 px-2 text-xs font-mono text-emerald-400 text-right rounded-r">
                        {formatCurrency(tier.payout, 2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Footer */}
            <div className="px-5 py-3 border-t border-gray-800 shrink-0">
              <div className="flex items-center justify-between text-xs text-gray-500">
                <span>{normalized.length} payout tiers</span>
                <span className="font-mono">
                  Total: {formatCurrency(normalized.reduce((sum, t) => {
                    const count = t.maxPosition - t.minPosition + 1;
                    return sum + t.payout * count;
                  }, 0), 2)}
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      <style>{`
        @keyframes slideUp {
          from { transform: translateY(100%); opacity: 0; }
          to { transform: translateY(0); opacity: 1; }
        }
        @media (min-width: 640px) {
          @keyframes slideUp {
            from { transform: scale(0.95); opacity: 0; }
            to { transform: scale(1); opacity: 1; }
          }
        }
        .animate-slide-up {
          animation: slideUp 0.2s ease-out;
        }
      `}</style>
    </>
  );
}
