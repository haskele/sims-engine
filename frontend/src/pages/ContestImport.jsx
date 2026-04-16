import { useState, useRef } from 'react';
import { Upload, FileText, Hash, ArrowRight, Check, AlertCircle, Trophy, Users, DollarSign, Loader2 } from 'lucide-react';
import { formatCurrency, formatCompact } from '../utils/formatting';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import PayoutDisplay from '../components/PayoutDisplay';
import { useApp } from '../context/AppContext';

export default function ContestImport() {
  const { uploadedContests, setUploadedContests } = useApp();
  const [mode, setMode] = useState('upload'); // 'upload' | 'manual'
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploaded, setUploaded] = useState(uploadedContests.length > 0);
  const [uploadResult, setUploadResult] = useState(
    uploadedContests.length > 0 ? { contests: uploadedContests, total_entries: uploadedContests.reduce((s, c) => s + (c.entry_count || 0), 0) } : null
  );
  const [error, setError] = useState(null);
  const [skippedRows, setSkippedRows] = useState([]);
  const [contestId, setContestId] = useState('');
  const [numEntries, setNumEntries] = useState(20);
  const fileInputRef = useRef(null);

  const handleUpload = async (file) => {
    if (!file) return;
    setUploading(true);
    setError(null);
    setSkippedRows([]);
    try {
      const result = await api.uploadDkEntries(file);
      setUploadResult(result);
      setUploaded(true);
      // Save contests to context (persists per user+slate)
      if (result.contests) {
        setUploadedContests(result.contests);
      }
      // Show skipped rows if any
      if (result.skipped_rows && result.skipped_rows.length > 0) {
        setSkippedRows(result.skipped_rows);
      }
    } catch (err) {
      setError(err.message || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleUpload(file);
  };

  const handleFileSelect = (e) => {
    const file = e.target.files[0];
    if (file) handleUpload(file);
  };

  const handleManualImport = () => {
    if (contestId.trim()) {
      setUploaded(true);
    }
  };

  const contests = uploadResult?.contests || [];
  const totalEntries = uploadResult?.total_entries || 0;

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-bold text-gray-100">Contest Import</h1>
        <p className="text-sm text-gray-500 mt-0.5">Upload a DraftKings entries CSV to configure contests for simulation</p>
      </div>

      {/* Mode toggle */}
      <div className="flex items-center gap-1 bg-gray-900 rounded-lg p-1 border border-gray-800 w-fit">
        <button
          onClick={() => { setMode('upload'); setUploaded(false); setError(null); }}
          className={`flex items-center gap-2 px-4 py-2 rounded-md text-xs font-semibold transition-colors ${
            mode === 'upload' ? 'bg-gray-800 text-white' : 'text-gray-400 hover:text-gray-200'
          }`}
        >
          <Upload className="w-3.5 h-3.5" />
          Upload CSV
        </button>
        <button
          onClick={() => { setMode('manual'); setUploaded(false); setError(null); }}
          className={`flex items-center gap-2 px-4 py-2 rounded-md text-xs font-semibold transition-colors ${
            mode === 'manual' ? 'bg-gray-800 text-white' : 'text-gray-400 hover:text-gray-200'
          }`}
        >
          <Hash className="w-3.5 h-3.5" />
          Contest ID
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-800 bg-red-900/20 px-4 py-3 text-sm text-red-400 flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      {!uploaded ? (
        <>
          {mode === 'upload' ? (
            <div
              className={`drop-zone rounded-lg p-6 sm:p-12 flex flex-col items-center justify-center cursor-pointer ${
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
              {uploading ? (
                <>
                  <Loader2 className="w-12 h-12 text-blue-500 animate-spin mb-4" />
                  <p className="text-sm text-gray-300">Uploading and parsing entries...</p>
                </>
              ) : (
                <>
                  <FileText className="w-12 h-12 text-gray-600 mb-4" />
                  <p className="text-sm text-gray-300 mb-1">Drop your DK entries CSV here</p>
                  <p className="text-xs text-gray-500">or click to browse files</p>
                  <p className="text-[10px] text-gray-600 mt-3">Download from DraftKings: My Contests &rarr; Export Entries</p>
                </>
              )}
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
            {contests.length > 0
              ? `Imported ${totalEntries} entries across ${contests.length} contest${contests.length > 1 ? 's' : ''}`
              : 'Contest imported successfully'}
          </div>

          {/* Skipped rows alert */}
          {skippedRows.length > 0 && (
            <div className="rounded-lg border border-amber-800 bg-amber-900/20 px-4 py-3 text-sm text-amber-400 flex items-start gap-2">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <div>
                <p className="font-medium">Some rows were skipped due to incomplete data:</p>
                <p className="text-xs text-amber-500 mt-1">
                  Row{skippedRows.length > 1 ? 's' : ''} {skippedRows.join(', ')}
                </p>
              </div>
            </div>
          )}

          {/* Contest list */}
          {contests.map((contest, i) => (
            <div key={contest.contest_id || i} className="rounded-lg border border-gray-800 bg-gray-900 p-6">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h2 className="text-lg font-bold text-gray-100">{contest.contest_name}</h2>
                  <p className="text-xs text-gray-500 mt-0.5">DraftKings &middot; {contest.game_type || 'classic'}</p>
                </div>
                <Trophy className="w-6 h-6 text-amber-400" />
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
                <div className="rounded-lg bg-gray-950 p-3">
                  <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">Entry Fee</div>
                  <div className="text-lg font-bold font-mono text-gray-100">
                    ${typeof contest.entry_fee === 'number' ? contest.entry_fee.toFixed(2) : contest.entry_fee}
                  </div>
                </div>
                <div className="rounded-lg bg-gray-950 p-3">
                  <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">Field Size</div>
                  <div className="text-lg font-bold font-mono text-gray-100 flex items-center gap-1.5">
                    <Users className="w-4 h-4 text-gray-500" />
                    {contest.field_size ? contest.field_size.toLocaleString() : '—'}
                  </div>
                </div>
                <div className="rounded-lg bg-gray-950 p-3">
                  <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">Your Entries</div>
                  <div className="text-lg font-bold font-mono text-blue-400">
                    {contest.entry_count}
                    {contest.max_entries_per_user && (
                      <span className="text-xs text-gray-500 font-normal ml-1">/ {contest.max_entries_per_user}</span>
                    )}
                  </div>
                </div>
                <div className="rounded-lg bg-gray-950 p-3">
                  <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">Prize Pool</div>
                  <div className="text-lg font-bold font-mono text-emerald-400">
                    {contest.prize_pool ? formatCurrency(contest.prize_pool) : '—'}
                  </div>
                </div>
                <div className="rounded-lg bg-gray-950 p-3">
                  <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">Top Payouts</div>
                  <PayoutDisplay payoutStructure={contest.payout_structure} />
                </div>
              </div>
            </div>
          ))}

          {/* Action buttons */}
          <div className="flex flex-wrap items-center gap-3">
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
              onClick={() => { setUploaded(false); setUploadResult(null); setError(null); setSkippedRows([]); setUploadedContests([]); }}
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
