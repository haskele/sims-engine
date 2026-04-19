import { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';

export default function StackControl({ team, value, onChange }) {
  const [expanded, setExpanded] = useState(false);
  const stacks = {
    '3man': { min: value?.stack_3?.min ?? 0, max: value?.stack_3?.max ?? 100 },
    '4man': { min: value?.stack_4?.min ?? 0, max: value?.stack_4?.max ?? 100 },
    '5man': { min: value?.stack_5?.min ?? 0, max: value?.stack_5?.max ?? 100 },
  };

  const handleChange = (stackType, field, val) => {
    const updated = {
      ...stacks,
      [stackType]: { ...stacks[stackType], [field]: Math.max(0, Math.min(100, Number(val) || 0)) },
    };
    onChange?.(updated);
  };

  return (
    <div className="border border-gray-800 rounded-lg overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-3 py-2 bg-gray-900 hover:bg-gray-800/80 transition-colors"
      >
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold text-gray-200">{team}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-mono text-gray-500">
            {(() => {
              const parts = [];
              for (const [key, label] of [['3man', '3+'], ['4man', '4+'], ['5man', '5+']]) {
                if (stacks[key].min > 0 || stacks[key].max < 100) {
                  parts.push(`${label}:${stacks[key].min}-${stacks[key].max}%`);
                }
              }
              return parts.length > 0 ? parts.join(', ') : 'no constraints';
            })()}
          </span>
          {expanded ? (
            <ChevronUp className="w-3.5 h-3.5 text-gray-500" />
          ) : (
            <ChevronDown className="w-3.5 h-3.5 text-gray-500" />
          )}
        </div>
      </button>

      {expanded && (
        <div className="px-3 py-2 space-y-2 bg-gray-950 border-t border-gray-800">
          {['3man', '4man', '5man'].map((stackType) => (
            <div key={stackType} className="flex items-center gap-3">
              <span className="text-xs text-gray-400 w-14 shrink-0">
                {stackType.replace('man', '-man')}
              </span>
              <div className="flex items-center gap-1.5">
                <label className="text-[10px] text-gray-500">Min</label>
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={stacks[stackType].min}
                  onChange={(e) => handleChange(stackType, 'min', e.target.value)}
                  className="w-14 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs font-mono text-gray-200 focus:outline-none focus:border-blue-500"
                />
                <span className="text-[10px] text-gray-600">%</span>
              </div>
              <div className="flex items-center gap-1.5">
                <label className="text-[10px] text-gray-500">Max</label>
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={stacks[stackType].max}
                  onChange={(e) => handleChange(stackType, 'max', e.target.value)}
                  className="w-14 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs font-mono text-gray-200 focus:outline-none focus:border-blue-500"
                />
                <span className="text-[10px] text-gray-600">%</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
