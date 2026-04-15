import { useState } from 'react';

export default function ExposureSlider({ playerName, min = 0, max = 100, onChange }) {
  const [minVal, setMinVal] = useState(min);
  const [maxVal, setMaxVal] = useState(max);

  const handleMinChange = (e) => {
    let val = e.target.value === '' ? 0 : Number(e.target.value);
    val = Math.max(0, Math.min(val, 100));
    setMinVal(val);
    onChange?.({ min: val, max: maxVal });
  };

  const handleMaxChange = (e) => {
    let val = e.target.value === '' ? 0 : Number(e.target.value);
    val = Math.max(0, Math.min(val, 100));
    setMaxVal(val);
    onChange?.({ min: minVal, max: val });
  };

  const handleMinBlur = () => {
    if (minVal > maxVal) {
      setMinVal(maxVal);
      onChange?.({ min: maxVal, max: maxVal });
    }
  };

  const handleMaxBlur = () => {
    if (maxVal < minVal) {
      setMaxVal(minVal);
      onChange?.({ min: minVal, max: minVal });
    }
  };

  const getColor = (val) => {
    if (val < 25) return 'text-red-400';
    if (val < 50) return 'text-amber-400';
    return 'text-emerald-400';
  };

  return (
    <div className="flex items-center gap-3 py-1">
      {playerName && (
        <span className="text-xs text-gray-300 w-32 truncate shrink-0">{playerName}</span>
      )}
      <div className="flex items-center gap-1.5">
        <label className="text-[10px] text-gray-500">Min</label>
        <input
          type="number"
          min={0}
          max={100}
          value={minVal}
          onChange={handleMinChange}
          onBlur={handleMinBlur}
          className={`w-14 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs font-mono text-center focus:outline-none focus:border-blue-500 ${getColor(minVal)}`}
        />
        <span className="text-[10px] text-gray-600">%</span>
      </div>
      <div className="flex-1 h-1 bg-gray-700 rounded mx-1 relative">
        <div
          className="absolute h-full bg-gradient-to-r from-blue-600 to-emerald-500 rounded"
          style={{
            left: `${minVal}%`,
            right: `${100 - maxVal}%`,
          }}
        />
      </div>
      <div className="flex items-center gap-1.5">
        <label className="text-[10px] text-gray-500">Max</label>
        <input
          type="number"
          min={0}
          max={100}
          value={maxVal}
          onChange={handleMaxChange}
          onBlur={handleMaxBlur}
          className={`w-14 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs font-mono text-center focus:outline-none focus:border-blue-500 ${getColor(maxVal)}`}
        />
        <span className="text-[10px] text-gray-600">%</span>
      </div>
    </div>
  );
}
