import { useState, useEffect } from 'react';
import {
  Cloud,
  Sun,
  Thermometer,
  TrendingUp,
  Zap,
  Upload,
  Users,
  PlayCircle,
  ArrowRight,
  Clock,
  MapPin,
  Loader2,
  RefreshCw,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';

function WeatherIcon({ temp }) {
  if (temp == null) return <Thermometer className="w-3.5 h-3.5 text-gray-500" />;
  if (temp >= 80) return <Sun className="w-3.5 h-3.5 text-amber-400" />;
  if (temp >= 60) return <Sun className="w-3.5 h-3.5 text-yellow-400" />;
  return <Cloud className="w-3.5 h-3.5 text-blue-400" />;
}

function GameCard({ game }) {
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900 p-3 hover:border-gray-700 transition-colors">
      {/* Venue & Weather */}
      <div className="flex items-center justify-between mb-2.5">
        <div className="flex items-center gap-2">
          <MapPin className="w-3 h-3 text-gray-500" />
          <span className="text-[10px] text-gray-500 truncate max-w-[140px]">{game.venue}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <WeatherIcon temp={game.temperature} />
          <span className="text-[10px] font-mono text-gray-500">
            {game.temperature != null ? `${Math.round(game.temperature)}°` : '—'}
          </span>
        </div>
      </div>

      {/* Matchup */}
      <div className="space-y-1.5 mb-2.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-gray-100">{game.away_team}</span>
            <span className="text-xs text-gray-500 truncate max-w-[100px]">{game.away_pitcher || 'TBD'}</span>
          </div>
          <span className={`text-xs font-mono ${game.away_ml && game.away_ml < 0 ? 'text-emerald-400' : 'text-gray-400'}`}>
            {game.away_ml ? (game.away_ml > 0 ? `+${game.away_ml}` : game.away_ml) : '—'}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-gray-100">{game.home_team}</span>
            <span className="text-xs text-gray-500 truncate max-w-[100px]">{game.home_pitcher || 'TBD'}</span>
          </div>
          <span className={`text-xs font-mono ${game.home_ml && game.home_ml < 0 ? 'text-emerald-400' : 'text-gray-400'}`}>
            {game.home_ml ? (game.home_ml > 0 ? `+${game.home_ml}` : game.home_ml) : '—'}
          </span>
        </div>
      </div>

      {/* Vegas & Implied */}
      <div className="flex items-center justify-between pt-2 border-t border-gray-800">
        <div className="flex items-center gap-3">
          <div>
            <span className="text-[10px] text-gray-500">O/U </span>
            <span className="text-xs font-mono text-gray-300">{game.total || '—'}</span>
          </div>
          {game.away_implied && game.home_implied && (
            <div className="flex items-center gap-1">
              <span className="text-[10px] text-gray-500">{game.away_team}</span>
              <span className="text-xs font-mono text-blue-400">{game.away_implied.toFixed(1)}</span>
              <span className="text-gray-700 mx-0.5">|</span>
              <span className="text-[10px] text-gray-500">{game.home_team}</span>
              <span className="text-xs font-mono text-blue-400">{game.home_implied.toFixed(1)}</span>
            </div>
          )}
        </div>
        <div className="flex items-center gap-1">
          {game.lineup_status === 'confirmed' ? (
            <span className="text-[9px] font-semibold text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded">CONFIRMED</span>
          ) : (
            <span className="text-[9px] font-semibold text-amber-400 bg-amber-500/10 px-1.5 py-0.5 rounded">PROJECTED</span>
          )}
        </div>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const [games, setGames] = useState([]);
  const [loading, setLoading] = useState(true);
  const [slateInfo, setSlateInfo] = useState(null);

  const site = localStorage.getItem('dfs_site') || 'dk';

  useEffect(() => {
    setLoading(true);
    // Fetch projections (which includes game data) and slates in parallel
    Promise.all([
      api.getFeaturedProjections(site),
      api.getSlates(site),
    ]).then(([projections, slates]) => {
      // Extract unique games from projections
      const gameMap = new Map();
      projections.forEach(p => {
        if (p.game_pk && !gameMap.has(p.game_pk)) {
          gameMap.set(p.game_pk, {
            game_pk: p.game_pk,
            venue: p.venue || 'Unknown',
            temperature: p.temperature,
          });
        }
        // Enrich with team data
        if (p.game_pk && gameMap.has(p.game_pk)) {
          const g = gameMap.get(p.game_pk);
          if (p.opp_team) {
            // Try to figure out home/away from pitcher entries
            if (p.is_pitcher) {
              if (!g.away_pitcher) {
                g.away_team = p.team;
                g.away_pitcher = p.player_name;
                g.opp_of_away = p.opp_team;
              } else if (!g.home_pitcher) {
                g.home_team = p.team;
                g.home_pitcher = p.player_name;
              }
            }
          }
          if (p.team_implied != null) {
            if (p.team === g.away_team) g.away_implied = p.team_implied;
            else if (p.team === g.home_team) g.home_implied = p.team_implied;
          }
          if (p.implied_total != null) g.total = p.implied_total;
          g.lineup_status = p.is_confirmed ? 'confirmed' : 'projected';
        }
      });

      // Build cleaner game list from the map
      const gameList = [];
      gameMap.forEach(g => {
        // Fix: if home/away weren't set from pitchers, set from the opp field
        if (!g.home_team && g.opp_of_away) {
          g.home_team = g.opp_of_away;
        }
        gameList.push(g);
      });

      setGames(gameList);
      if (slates.length > 0) {
        setSlateInfo(slates[0]);
      }
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [site]);

  const avgTotal = games.length > 0
    ? (games.reduce((s, g) => s + (g.total || 0), 0) / games.filter(g => g.total).length).toFixed(1)
    : '—';
  const highestTotal = games.length > 0
    ? Math.max(...games.map(g => g.total || 0)).toFixed(1)
    : '—';

  if (loading) {
    return (
      <div className="flex items-center justify-center py-32">
        <div className="text-center">
          <Loader2 className="w-8 h-8 text-blue-500 animate-spin mx-auto mb-3" />
          <p className="text-sm text-gray-400">Loading today's slate...</p>
          <p className="text-xs text-gray-600 mt-1">Fetching games, odds, weather, and projections</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-100">Dashboard</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {slateInfo ? `${slateInfo.name} — ${slateInfo.game_count} Games` : `${games.length} Games`}
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <div className="w-2 h-2 rounded-full bg-emerald-500 pulse-dot" />
          Live Data
        </div>
      </div>

      {/* Quick action buttons */}
      <div className="grid grid-cols-3 gap-3">
        <Link
          to="/contests"
          className="flex items-center gap-3 px-4 py-3 rounded-lg border border-gray-800 bg-gray-900 hover:bg-gray-800 hover:border-gray-700 transition-all group"
        >
          <Upload className="w-5 h-5 text-blue-500" />
          <div>
            <div className="text-sm font-semibold text-gray-200">Import Contest</div>
            <div className="text-xs text-gray-500">Upload CSV or enter ID</div>
          </div>
          <ArrowRight className="w-4 h-4 text-gray-600 ml-auto group-hover:text-gray-400 transition-colors" />
        </Link>
        <Link
          to="/lineups"
          className="flex items-center gap-3 px-4 py-3 rounded-lg border border-gray-800 bg-gray-900 hover:bg-gray-800 hover:border-gray-700 transition-all group"
        >
          <Users className="w-5 h-5 text-emerald-500" />
          <div>
            <div className="text-sm font-semibold text-gray-200">Build Lineups</div>
            <div className="text-xs text-gray-500">Optimizer + stacks</div>
          </div>
          <ArrowRight className="w-4 h-4 text-gray-600 ml-auto group-hover:text-gray-400 transition-colors" />
        </Link>
        <Link
          to="/simulator"
          className="flex items-center gap-3 px-4 py-3 rounded-lg border border-gray-800 bg-gray-900 hover:bg-gray-800 hover:border-gray-700 transition-all group"
        >
          <PlayCircle className="w-5 h-5 text-purple-500" />
          <div>
            <div className="text-sm font-semibold text-gray-200">Run Simulation</div>
            <div className="text-xs text-gray-500">Contest sim engine</div>
          </div>
          <ArrowRight className="w-4 h-4 text-gray-600 ml-auto group-hover:text-gray-400 transition-colors" />
        </Link>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: 'Today\'s Games', value: games.length, icon: Zap, color: 'text-blue-400' },
          { label: 'Avg Total', value: avgTotal, icon: TrendingUp, color: 'text-emerald-400' },
          { label: 'Highest Total', value: highestTotal, icon: TrendingUp, color: 'text-amber-400' },
          { label: 'DK Slates', value: slateInfo ? '17' : '—', icon: PlayCircle, color: 'text-purple-400' },
        ].map((stat) => (
          <div key={stat.label} className="rounded-lg border border-gray-800 bg-gray-900 px-4 py-3">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] uppercase tracking-wider text-gray-500">{stat.label}</span>
              <stat.icon className={`w-4 h-4 ${stat.color}`} />
            </div>
            <div className={`text-2xl font-bold font-mono ${stat.color}`}>{stat.value}</div>
          </div>
        ))}
      </div>

      {/* Games grid */}
      <div>
        <h2 className="text-sm font-semibold text-gray-300 mb-3">Today's Slate</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {games.map((game) => (
            <GameCard key={game.game_pk} game={game} />
          ))}
        </div>
        {games.length === 0 && (
          <div className="text-center py-12 text-sm text-gray-500">No games found for today</div>
        )}
      </div>
    </div>
  );
}
