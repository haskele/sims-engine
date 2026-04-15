import { useState, useEffect } from 'react';
import { Check, AlertCircle, Cloud, Sun, MapPin, RefreshCw } from 'lucide-react';
import { api } from '../api/client';

function LineupTable({ team, status, pitcher, batters }) {
  const isConfirmed = status === 'confirmed';
  const hasBatters = batters && batters.length > 0;

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-gray-400">{team} Lineup</span>
        <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${
          isConfirmed
            ? 'bg-emerald-500/10 text-emerald-400'
            : 'bg-amber-500/10 text-amber-400'
        }`}>
          {isConfirmed ? 'Confirmed' : 'Expected'}
        </span>
      </div>

      {/* Starting Pitcher */}
      {pitcher && (
        <div className="flex items-center justify-between px-2 py-1.5 mb-1 rounded bg-gray-950 border border-gray-800/50">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-mono text-gray-600 w-4">SP</span>
            <span className={`text-[10px] font-bold px-1 py-0.5 rounded ${
              pitcher.handedness === 'L' ? 'bg-blue-500/15 text-blue-400' : 'bg-red-500/15 text-red-400'
            }`}>
              {pitcher.handedness || '?'}
            </span>
            <span className="text-xs font-semibold text-gray-200">{pitcher.name}</span>
          </div>
          {isConfirmed ? (
            <Check className="w-3 h-3 text-emerald-500" />
          ) : (
            <AlertCircle className="w-3 h-3 text-amber-500 opacity-50" />
          )}
        </div>
      )}

      {/* Batting Order */}
      {hasBatters ? (
        <div className="space-y-0">
          {batters.map((player, i) => (
            <div
              key={i}
              className={`flex items-center justify-between px-2 py-1 rounded ${
                i % 2 === 0 ? 'bg-gray-950' : ''
              }`}
            >
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-mono text-gray-600 w-4">{player.batting_order}</span>
                <span className="text-[10px] font-bold text-gray-500 w-6">{player.position}</span>
                <span className="text-xs text-gray-200">{player.name}</span>
                <span className={`text-[10px] px-1 py-0.5 rounded ${
                  player.handedness === 'L' ? 'text-blue-400/60' : player.handedness === 'S' ? 'text-purple-400/60' : 'text-gray-600'
                }`}>
                  {player.handedness}
                </span>
              </div>
              <Check className="w-3 h-3 text-emerald-500" />
            </div>
          ))}
        </div>
      ) : (
        <div className="text-xs text-gray-600 px-2 py-4 text-center italic">
          Lineup not yet posted
        </div>
      )}
    </div>
  );
}

function GameCard({ game }) {
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900 overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-lg font-bold text-gray-100">{game.away.team}</span>
          <span className="text-xs text-gray-600">@</span>
          <span className="text-lg font-bold text-gray-100">{game.home.team}</span>
        </div>
        <div className="flex items-center gap-2">
          {game.away.status === 'confirmed' && game.home.status === 'confirmed' ? (
            <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400">
              Both Confirmed
            </span>
          ) : (
            <>
              {game.away.status === 'confirmed' && (
                <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400">
                  {game.away.team} Confirmed
                </span>
              )}
              {game.home.status === 'confirmed' && (
                <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400">
                  {game.home.team} Confirmed
                </span>
              )}
            </>
          )}
        </div>
      </div>

      {/* Lineups */}
      <div className="px-4 py-3 grid grid-cols-2 gap-4">
        <LineupTable
          team={game.away.team}
          status={game.away.status}
          pitcher={game.away.pitcher}
          batters={game.away.batters}
        />
        <LineupTable
          team={game.home.team}
          status={game.home.status}
          pitcher={game.home.pitcher}
          batters={game.home.batters}
        />
      </div>
    </div>
  );
}

export default function GameCenter() {
  const [games, setGames] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  const loadGames = async (forceRefresh = false) => {
    try {
      if (forceRefresh) setRefreshing(true);
      else setLoading(true);
      const data = await api.getGameLineups(forceRefresh);
      setGames(data);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    loadGames();
    // Auto-refresh every 2 minutes
    const interval = setInterval(() => loadGames(true), 120000);
    return () => clearInterval(interval);
  }, []);

  const confirmedCount = games.reduce((acc, g) => {
    if (g.away.status === 'confirmed') acc++;
    if (g.home.status === 'confirmed') acc++;
    return acc;
  }, 0);
  const totalTeams = games.length * 2;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-100">Game Center</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {games.length} games &middot; {confirmedCount}/{totalTeams} lineups confirmed
          </p>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 text-xs text-gray-500">
            <div className="flex items-center gap-1.5">
              <Check className="w-3.5 h-3.5 text-emerald-500" />
              <span>Confirmed</span>
            </div>
            <div className="flex items-center gap-1.5 ml-3">
              <AlertCircle className="w-3.5 h-3.5 text-amber-500" />
              <span>Expected</span>
            </div>
          </div>
          <button
            onClick={() => loadGames(true)}
            disabled={refreshing}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-700 bg-gray-800 text-xs text-gray-300 hover:bg-gray-700 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      {loading && !games.length ? (
        <div className="text-center py-12 text-gray-500">
          <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2" />
          Loading lineups...
        </div>
      ) : error ? (
        <div className="text-center py-12 text-red-400">
          Failed to load lineups: {error}
        </div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {games.map((game, i) => (
            <GameCard key={i} game={game} />
          ))}
        </div>
      )}
    </div>
  );
}
