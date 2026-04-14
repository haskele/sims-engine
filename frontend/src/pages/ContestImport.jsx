import { useState, useRef } from 'react';
import { Upload, FileText, Hash, ArrowRight, Check, AlertCircle, Trophy, Users, DollarSign } from 'lucide-react';
import { formatCurrency, formatCompact } from '../utils/formatting';
import { Link } from 'react-router-dom';

const mockPayoutTable = [
  { place: '1st', payout: 30000 },
  { place: '2nd', payout: 15000 },
  { place: '3rd', payout: 10000 },
  { place: '4th-5th', payout: 5000 },
  { place: '6th-10th', payout: 2500 },
  { place: '11th-25th', payout: 1000 },
  { place: '26th-50th', payout: 500 },
  { place: '51st-100th', payout: 250 },
  { place: '101st-250th', payout: 100 },
  { place: '251st-500th', payout: 50 },
  { place: '501st-1000th', payout: 30 },
  { place: '1001st-2500th', payout: 20 },
];

export default function ContestImport() {
  const [mode, setMode] = useState('upload'); // 'upload' | 'manual'
  const [dragOver, setDragOver] = useState(false);
  const [uploaded, setUploaded] = useState(false);
  const [contestId, setContestId] = useState('');
  const [numEntries, setNumEntries] = useState(20);
  const fileInputRef = useRef(null);

  const mockImportedContest = {
    name: 'DK $15 Main Slate MME',
    site: 'DraftKings',
    entryFee: 15,
    fieldSize: 12543,
    prizePool: 150000,
    maxEntries: 150,
    numEntries: 20,
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    // Simulate upload
    setTimeout(() => setUploaded(true), 800);
  };

  const handleFileSelect = () => {
    // Simulate upload
    setTimeout(() => setUploaded(true), 800);
  };

  const handleManualImport = () => {
    if (contestId.trim()) {
      setUploaded(true);
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-bold text-gray-100">Contest Import</h1>
        <p className="text-sm text-gray-500 mt-0.5">Upload a contest CSV or enter a contest ID</p>
      </div>

      {/* Mode toggle */}
      <div className="flex items-center gap-1 bg-gray-900 rounded-lg p-1 border border-gray-800 w-fit">
        <button
          onClick={() => { setMode('upload'); setUploaded(false); }}
          className={`flex items-center gap-2 px-4 py-2 rounded-md text-xs font-semibold transition-colors ${
            mode === 'upload' ? 'bg-gray-800 text-white' : 'text-gray-400 hover:text-gray-200'
          }`}
        >
          <Upload className="w-3.5 h-3.5" />
          Upload CSV
        </button>
        <button
          onClick={() => { setMode('manual'); setUploaded(false); }}
          className={`flex items-center gap-2 px-4 py-2 rounded-md text-xs font-semibold transition-colors ${
            mode === 'manual' ? 'bg-gray-800 text-white' : 'text-gray-400 hover:text-gray-200'
          }`}
        >
          <Hash className="w-3.5 h-3.5" />
          Contest ID
        </button>
      </div>

      {!uploaded ? (
        <>
          {mode === 'upload' ? (
            <div
              className={`drop-zone rounded-lg p-12 flex flex-col items-center justify-center cursor-pointer ${
                dragOver ? 'drag-over' : ''
              }`}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv"
                className="hidden"
                onChange={handleFileSelect}
              />
              <FileText className="w-12 h-12 text-gray-600 mb-4" />
              <p className="text-sm text-gray-300 mb-1">Drop your contest CSV here</p>
              <p className="text-xs text-gray-500">or click to browse files</p>
              <p className="text-[10px] text-gray-600 mt-3">Supports DraftKings and FanDuel export formats</p>
            </div>
          ) : (
            <div className="rounded-lg border border-gray-800 bg-gray-900 p-6 space-y-4">
              <div>
                <label className="block text-xs text-gray-400 mb-1.5">Contest ID</label>
                <input
                  type="text"
                  value={contestId}
                  onChange={(e) => setContestId(e.target.value)}
                  placeholder="e.g., 12345678"
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1.5">Number of Entries</label>
                <input
                  type="number"
                  value={numEntries}
                  onChange={(e) => setNumEntries(Number(e.target.value))}
                  min={1}
                  max={150}
                  className="w-32 bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-sm font-mono text-gray-200 focus:outline-none focus:border-blue-500"
                />
              </div>
              <button
                onClick={handleManualImport}
                disabled={!contestId.trim()}
                className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                Import Contest
                <ArrowRight className="w-4 h-4" />
              </button>
            </div>
          )}
        </>
      ) : (
        /* Post-import: Contest details */
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-emerald-400 text-sm">
            <Check className="w-4 h-4" />
            Contest imported successfully
          </div>

          {/* Contest summary */}
          <div className="rounded-lg border border-gray-800 bg-gray-900 p-6">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-lg font-bold text-gray-100">{mockImportedContest.name}</h2>
                <p className="text-xs text-gray-500 mt-0.5">{mockImportedContest.site}</p>
              </div>
              <Trophy className="w-6 h-6 text-amber-400" />
            </div>

            <div className="grid grid-cols-4 gap-4 mb-6">
              <div className="rounded-lg bg-gray-950 p-3">
                <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">Entry Fee</div>
                <div className="text-lg font-bold font-mono text-gray-100">{formatCurrency(mockImportedContest.entryFee)}</div>
              </div>
              <div className="rounded-lg bg-gray-950 p-3">
                <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">Field Size</div>
                <div className="text-lg font-bold font-mono text-gray-100 flex items-center gap-1.5">
                  <Users className="w-4 h-4 text-gray-500" />
                  {formatCompact(mockImportedContest.fieldSize)}
                </div>
              </div>
              <div className="rounded-lg bg-gray-950 p-3">
                <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">Prize Pool</div>
                <div className="text-lg font-bold font-mono text-emerald-400">{formatCurrency(mockImportedContest.prizePool)}</div>
              </div>
              <div className="rounded-lg bg-gray-950 p-3">
                <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">Your Entries</div>
                <div className="text-lg font-bold font-mono text-blue-400">
                  {mockImportedContest.numEntries}
                  <span className="text-xs text-gray-500 font-normal ml-1">/ {mockImportedContest.maxEntries}</span>
                </div>
              </div>
            </div>

            {/* Payout table */}
            <div>
              <h3 className="text-xs font-semibold text-gray-400 mb-3">Payout Structure</h3>
              <div className="grid grid-cols-4 gap-x-6 gap-y-1">
                {mockPayoutTable.map((row) => (
                  <div key={row.place} className="flex items-center justify-between py-1">
                    <span className="text-xs text-gray-400">{row.place}</span>
                    <span className="text-xs font-mono text-emerald-400">{formatCurrency(row.payout)}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-3">
            <Link
              to="/lineups"
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-emerald-600 text-white text-sm font-semibold hover:bg-emerald-500 transition-colors"
            >
              Proceed to Build Lineups
              <ArrowRight className="w-4 h-4" />
            </Link>
            <Link
              to="/simulator"
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg border border-gray-700 bg-gray-800 text-sm text-gray-300 font-semibold hover:bg-gray-700 transition-colors"
            >
              Go to Simulator
              <ArrowRight className="w-4 h-4" />
            </Link>
            <button
              onClick={() => setUploaded(false)}
              className="px-4 py-2.5 text-xs text-gray-500 hover:text-gray-300 transition-colors"
            >
              Import Another
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
