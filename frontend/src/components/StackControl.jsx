import { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';

export default function StackControl({ team, onChange }) {
  const [expanded, setExpanded] = useState(false);
  const [stacks, setStacks] = useState({
    '3man': { min: 0, max: 150 },
    '4man': { min: 0, max: 150 },
    '5man': { min: 0, max: 150 },
  });

  const handleChange = (stackType, field, value) => {
    const updated = {
      ...stacks,
      [stackType]: { ...stacks[stackType], [field]: Number(value) },
    };
    setStacks(updated);
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
            {stacks['4man'].min > 0 ? `4+ min:${stacks['4man'].min}` : 'no constraints'}
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
              <div className="flex items-center gap-2">
                <label className="text-[10px] text-gray-500">Min</label>
                <input
                  type="number"
                  min={0}
                  max={150}
                  value={stacks[stackType].min}
                  onChange={(e) => handleChange(stackType, 'min', e.target.value)}
                  className="w-14 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs font-mono text-gray-200 focus:outline-none focus:border-blue-500"
                />
              </div>
              <div className="flex items-center gap-2">
                <label className="text-[10px] text-gray-500">Max</label>
                <input
                  type="number"
                  min={0}
                  max={150}
                  value={stacks[stackType].max}
                  onChange={(e) => handleChange(stackType, 'max', e.target.value)}
                  className="w-14 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs font-mono text-gray-200 focus:outline-none focus:border-blue-500"
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
