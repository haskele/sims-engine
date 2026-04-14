import { useState } from 'react';

export default function ExposureSlider({ playerName, min = 0, max = 100, onChange }) {
  const [minVal, setMinVal] = useState(min);
  const [maxVal, setMaxVal] = useState(max);

  const handleMinChange = (e) => {
    const val = Math.min(Number(e.target.value), maxVal - 1);
    setMinVal(val);
    onChange?.({ min: val, max: maxVal });
  };

  const handleMaxChange = (e) => {
    const val = Math.max(Number(e.target.value), minVal + 1);
    setMaxVal(val);
    onChange?.({ min: minVal, max: val });
  };

  const getTrackColor = (val) => {
    if (val < 25) return 'text-red-500';
    if (val < 50) return 'text-amber-500';
    return 'text-emerald-500';
  };

  return (
    <div className="flex items-center gap-3 py-1">
      {playerName && (
        <span className="text-xs text-gray-300 w-32 truncate shrink-0">{playerName}</span>
      )}
      <span className={`text-xs font-mono w-8 text-right shrink-0 ${getTrackColor(minVal)}`}>
        {minVal}%
      </span>
      <div className="relative flex-1 h-5">
        <input
          type="range"
          min={0}
          max={100}
          value={minVal}
          onChange={handleMinChange}
          className="absolute inset-0 w-full appearance-none bg-transparent pointer-events-auto z-10"
          style={{ zIndex: minVal > 50 ? 5 : 3 }}
        />
        <input
          type="range"
          min={0}
          max={100}
          value={maxVal}
          onChange={handleMaxChange}
          className="absolute inset-0 w-full appearance-none bg-transparent pointer-events-auto z-10"
          style={{ zIndex: maxVal < 50 ? 5 : 3 }}
        />
        {/* Track fill */}
        <div className="absolute top-1/2 left-0 right-0 h-1 bg-gray-700 rounded -translate-y-1/2">
          <div
            className="absolute h-full bg-gradient-to-r from-blue-600 to-emerald-500 rounded"
            style={{
              left: `${minVal}%`,
              right: `${100 - maxVal}%`,
            }}
          />
        </div>
      </div>
      <span className={`text-xs font-mono w-8 shrink-0 ${getTrackColor(maxVal)}`}>
        {maxVal}%
      </span>
    </div>
  );
}
