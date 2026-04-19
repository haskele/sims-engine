import { useState, useEffect, useCallback, useRef } from 'react';
import { Check, AlertCircle, RefreshCw, Thermometer, Droplets, Wind, Clock, Building2 } from 'lucide-react';
import { api } from '../api/client';
import { useApp } from '../context/AppContext';

// ── Stadium data (must match backend STADIUM_DATA) ─────────────────────────

const STADIUM_DATA = {
  ARI: { name: 'Chase Field', hpDir: 167, dome: true },
  ATL: { name: 'Truist Park', hpDir: 225 },
  BAL: { name: 'Camden Yards', hpDir: 218 },
  BOS: { name: 'Fenway Park', hpDir: 199 },
  CHC: { name: 'Wrigley Field', hpDir: 220 },
  CWS: { name: 'Guaranteed Rate', hpDir: 197 },
  CIN: { name: 'Great American', hpDir: 186 },
  CLE: { name: 'Progressive Field', hpDir: 172 },
  COL: { name: 'Coors Field', hpDir: 200 },
  DET: { name: 'Comerica Park', hpDir: 208 },
  HOU: { name: 'Minute Maid', hpDir: 172, dome: true },
  KC: { name: 'Kauffman', hpDir: 180 },
  LAA: { name: 'Angel Stadium', hpDir: 198 },
  LAD: { name: 'Dodger Stadium', hpDir: 170 },
  MIA: { name: 'loanDepot Park', hpDir: 13, dome: true },
  MIL: { name: 'American Family', hpDir: 195, dome: true },
  MIN: { name: 'Target Field', hpDir: 185 },
  NYM: { name: 'Citi Field', hpDir: 202 },
  NYY: { name: 'Yankee Stadium', hpDir: 194 },
  OAK: { name: 'Oakland Coliseum', hpDir: 145 },
  ATH: { name: 'Oakland Coliseum', hpDir: 145 },
  PHI: { name: 'Citizens Bank', hpDir: 193 },
  PIT: { name: 'PNC Park', hpDir: 135 },
  SD: { name: 'Petco Park', hpDir: 192 },
  SF: { name: 'Oracle Park', hpDir: 148 },
  SEA: { name: 'T-Mobile Park', hpDir: 184, dome: true },
  STL: { name: 'Busch Stadium', hpDir: 197 },
  TB: { name: 'Tropicana', hpDir: 176, dome: true },
  TEX: { name: 'Globe Life', hpDir: 214, dome: true },
  TOR: { name: 'Rogers Centre', hpDir: 170, dome: true },
  WSH: { name: 'Nationals Park', hpDir: 221 },
};


// ── Wind analysis helpers ──────────────────────────────────────────────────

function getWindEffect(windDir, hpDir) {
  // Wind blowing toward home plate = "in" (bad for hitters)
  // Wind blowing away from home plate = "out" (good for hitters)
  // The outfield direction is hpDir (the direction HP faces from pitcher)
  // So wind blowing FROM hpDir direction = blowing out (toward outfield)
  // Wind blowing TOWARD hpDir direction = blowing in (toward home plate)

  // The "out" direction from HP is hpDir + 180 (toward center field)
  const outDir = (hpDir + 180) % 360;

  // Angle between wind direction and the "out" direction
  let diff = windDir - outDir;
  // Normalise to -180..180
  while (diff > 180) diff -= 360;
  while (diff < -180) diff += 360;
  const absDiff = Math.abs(diff);

  if (absDiff <= 45) return { label: 'Out', color: 'text-emerald-400', bgColor: 'bg-emerald-500/15', desc: 'Blowing out' };
  if (absDiff >= 135) return { label: 'In', color: 'text-red-400', bgColor: 'bg-red-500/15', desc: 'Blowing in' };
  return { label: 'Cross', color: 'text-amber-400', bgColor: 'bg-amber-500/15', desc: 'Cross-wind' };
}


// ── Wind Compass SVG component ─────────────────────────────────────────────

function WindCompass({ windDir, windSpeed, hpDir, size = 56 }) {
  if (windDir == null || hpDir == null) return null;

  const effect = getWindEffect(windDir, hpDir);
  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 4;

  // Arrow color based on wind effect
  const arrowColor = effect.label === 'Out' ? '#34d399' : effect.label === 'In' ? '#f87171' : '#fbbf24';

  // Wind direction arrow: windDir is "from" direction, so arrow points in windDir + 180
  const arrowAngle = (windDir + 180) % 360;
  const arrowRad = (arrowAngle - 90) * (Math.PI / 180);
  const arrowLen = r - 4;
  const ax = cx + Math.cos(arrowRad) * arrowLen;
  const ay = cy + Math.sin(arrowRad) * arrowLen;
  const tailX = cx - Math.cos(arrowRad) * (arrowLen * 0.4);
  const tailY = cy - Math.sin(arrowRad) * (arrowLen * 0.4);

  // Arrowhead
  const headLen = 6;
  const headAngle = 0.4;
  const h1x = ax - headLen * Math.cos(arrowRad - headAngle);
  const h1y = ay - headLen * Math.sin(arrowRad - headAngle);
  const h2x = ax - headLen * Math.cos(arrowRad + headAngle);
  const h2y = ay - headLen * Math.sin(arrowRad + headAngle);

  // Home plate indicator (small diamond)
  const hpRad = (hpDir - 90) * (Math.PI / 180);
  const hpX = cx + Math.cos(hpRad) * (r - 1);
  const hpY = cy + Math.sin(hpRad) * (r - 1);

  return (
    <div className="flex flex-col items-center gap-0.5">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        {/* Background circle */}
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="#374151" strokeWidth="1.5" />

        {/* Cardinal direction ticks */}
        {[0, 90, 180, 270].map((deg) => {
          const rad = (deg - 90) * (Math.PI / 180);
          const x1 = cx + Math.cos(rad) * (r - 3);
          const y1 = cy + Math.sin(rad) * (r - 3);
          const x2 = cx + Math.cos(rad) * r;
          const y2 = cy + Math.sin(rad) * r;
          return <line key={deg} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#6b7280" strokeWidth="1" />;
        })}

        {/* Home plate marker */}
        <polygon
          points={`${hpX},${hpY - 3} ${hpX + 2.5},${hpY} ${hpX},${hpY + 3} ${hpX - 2.5},${hpY}`}
          fill="#9ca3af"
          stroke="#d1d5db"
          strokeWidth="0.5"
        />

        {/* Wind arrow line */}
        <line x1={tailX} y1={tailY} x2={ax} y2={ay} stroke={arrowColor} strokeWidth="2" strokeLinecap="round" />

        {/* Arrowhead */}
        <polygon points={`${ax},${ay} ${h1x},${h1y} ${h2x},${h2y}`} fill={arrowColor} />

        {/* Center dot */}
        <circle cx={cx} cy={cy} r="2" fill="#6b7280" />
      </svg>
      <div className="flex items-center gap-1">
        <span className={`text-[10px] font-bold ${effect.color}`}>{effect.label}</span>
        {windSpeed != null && (
          <span className="text-[10px] text-gray-500">{Math.round(windSpeed)} mph</span>
        )}
      </div>
    </div>
  );
}


// ── Weather badge component ────────────────────────────────────────────────

function WeatherBadge({ weather, homeTeam }) {
  if (!weather) return null;

  const stadium = STADIUM_DATA[homeTeam];

  if (weather.is_dome) {
    return (
      <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-gray-800/60 border border-gray-700/50">
        <Building2 className="w-3.5 h-3.5 text-blue-400" />
        <span className="text-[11px] font-medium text-blue-400">Dome</span>
        {weather.temperature != null && (
          <span className="text-[11px] text-gray-400">
            {Math.round(weather.temperature)}&deg;F
          </span>
        )}
      </div>
    );
  }

  return (
    <div className="flex items-center gap-3">
      {/* Weather stats */}
      <div className="flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg bg-gray-800/60 border border-gray-700/50">
        {weather.temperature != null && (
          <div className="flex items-center gap-1" title="Temperature">
            <Thermometer className="w-3 h-3 text-orange-400" />
            <span className="text-[11px] text-gray-300">{Math.round(weather.temperature)}&deg;</span>
          </div>
        )}
        {weather.wind_speed != null && (
          <div className="flex items-center gap-1" title={`Wind: ${Math.round(weather.wind_speed)} mph`}>
            <Wind className="w-3 h-3 text-sky-400" />
            <span className="text-[11px] text-gray-300">{Math.round(weather.wind_speed)} mph</span>
          </div>
        )}
        {weather.precip_pct != null && weather.precip_pct > 0 && (
          <div className="flex items-center gap-1" title={`Precipitation chance: ${Math.round(weather.precip_pct)}%`}>
            <Droplets className="w-3 h-3 text-blue-400" />
            <span className="text-[11px] text-gray-300">{Math.round(weather.precip_pct)}%</span>
          </div>
        )}
      </div>

      {/* Wind compass */}
      {stadium && weather.wind_dir != null && weather.wind_speed != null && weather.wind_speed > 2 && (
        <WindCompass
          windDir={weather.wind_dir}
          windSpeed={weather.wind_speed}
          hpDir={stadium.hpDir}
          size={52}
        />
      )}
    </div>
  );
}


// ── Vegas / odds display ───────────────────────────────────────────────────

function VegasBadge({ game }) {
  const { vegas_total, vegas_spread, away_ml, home_ml, away, home } = game;
  const hasOdds = vegas_total != null || away.implied_total != null;
  if (!hasOdds) return null;

  return (
    <div className="flex items-center gap-3 px-2.5 py-1.5 rounded-lg bg-gray-800/60 border border-gray-700/50 text-[11px]">
      {vegas_total != null && (
        <div className="flex items-center gap-1">
          <span className="text-gray-500">O/U</span>
          <span className="text-gray-200 font-semibold">{vegas_total}</span>
        </div>
      )}
      {vegas_spread != null && (
        <div className="flex items-center gap-1">
          <span className="text-gray-500">Spread</span>
          <span className="text-gray-200 font-semibold">
            {vegas_spread > 0 ? `${game.away.team} +${Math.abs(vegas_spread)}` : `${game.home.team} +${Math.abs(vegas_spread)}`}
          </span>
        </div>
      )}
      {away.implied_total != null && (
        <div className="flex items-center gap-1">
          <span className="text-gray-500">{away.team}</span>
          <span className="text-amber-400 font-semibold">{away.implied_total.toFixed(1)}</span>
          {away_ml != null && (
            <span className="text-gray-400 text-[10px]">({away_ml > 0 ? '+' : ''}{away_ml})</span>
          )}
        </div>
      )}
      {home.implied_total != null && (
        <div className="flex items-center gap-1">
          <span className="text-gray-500">{home.team}</span>
          <span className="text-amber-400 font-semibold">{home.implied_total.toFixed(1)}</span>
          {home_ml != null && (
            <span className="text-gray-400 text-[10px]">({home_ml > 0 ? '+' : ''}{home_ml})</span>
          )}
        </div>
      )}
    </div>
  );
}


// ── Live score display ─────────────────────────────────────────────────────

function LiveScoreBadge({ liveState }) {
  if (!liveState) return null;

  if (liveState.game_status === 'Preview') return null;

  // Extra safety: if detailed_state indicates pre-game, don't show as live
  const preGameStates = ['warmup', 'pre-game', 'scheduled', 'delayed start'];
  const detailedLower = (liveState.detailed_state || '').toLowerCase();
  if (liveState.game_status === 'Live' && preGameStates.includes(detailedLower)) return null;

  const isLive = liveState.game_status === 'Live';
  const isFinal = liveState.game_status === 'Final';

  let inningText = '';
  if (isLive) {
    const half = liveState.inning_half === 'top' ? 'Top' : 'Bot';
    inningText = `${half} ${liveState.inning}`;
  }

  return (
    <div className={`flex items-center gap-2 px-2.5 py-1 rounded-lg border ${
      isLive ? 'bg-red-500/10 border-red-500/30' : 'bg-gray-800/60 border-gray-700/50'
    }`}>
      {isLive && (
        <span className="relative flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75"></span>
          <span className="relative inline-flex rounded-full h-2 w-2 bg-red-500"></span>
        </span>
      )}
      <span className={`text-[11px] font-bold ${isLive ? 'text-red-400' : 'text-gray-400'}`}>
        {isLive ? 'LIVE' : 'FINAL'}
      </span>
      <span className="text-sm font-bold text-gray-100">
        {liveState.away_score} - {liveState.home_score}
      </span>
      {isLive && inningText && (
        <span className="text-[10px] text-gray-400">{inningText}</span>
      )}
    </div>
  );
}


// ── Lineup table component ─────────────────────────────────────────────────

function LineupTable({ team, status, pitcher, batters }) {
  const isConfirmed = status === 'confirmed';
  const isExpected = status === 'expected';
  const hasBatters = batters && batters.length > 0;

  const statusLabel = isConfirmed ? 'Confirmed' : isExpected ? 'Expected' : 'Projected';
  const statusColor = isConfirmed
    ? 'bg-emerald-500/10 text-emerald-400'
    : isExpected
      ? 'bg-amber-500/10 text-amber-400'
      : 'bg-blue-500/10 text-blue-400';

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-gray-400">{team} Lineup</span>
        <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${statusColor}`}>
          {statusLabel}
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
            {pitcher.opener_status === 'PO' && (
              <span className="text-[9px] font-bold px-1 py-0.5 rounded bg-amber-500/15 text-amber-400 leading-none">PO</span>
            )}
            {pitcher.opener_status === 'PLR' && (
              <span className="text-[9px] font-bold px-1 py-0.5 rounded bg-blue-500/15 text-blue-400 leading-none">PLR</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {pitcher.median_pts != null && (
              <span className="text-[10px] font-mono text-blue-400/80">{pitcher.median_pts.toFixed(1)}pts</span>
            )}
            {pitcher.salary && (
              <span className="text-[10px] font-mono text-emerald-400/80">${(pitcher.salary / 1000).toFixed(1)}k</span>
            )}
            {isConfirmed ? (
              <Check className="w-3 h-3 text-emerald-500" />
            ) : (
              <AlertCircle className="w-3 h-3 text-amber-500 opacity-50" />
            )}
          </div>
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
              } ${!isConfirmed ? 'opacity-70' : ''}`}
            >
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-mono text-gray-600 w-4">{player.batting_order}</span>
                <span className="text-[10px] font-bold text-gray-500 w-6">{player.position}</span>
                <span className={`text-xs ${isConfirmed ? 'text-gray-200' : 'text-gray-400'}`}>{player.name}</span>
                {player.handedness && (
                  <span className={`text-[10px] px-1 py-0.5 rounded ${
                    player.handedness === 'L' ? 'text-blue-400/60' : player.handedness === 'S' ? 'text-purple-400/60' : 'text-gray-600'
                  }`}>
                    {player.handedness}
                  </span>
                )}
                {player.opener_status === 'PO' && (
                  <span className="text-[9px] font-bold px-1 py-0.5 rounded bg-amber-500/15 text-amber-400 leading-none">PO</span>
                )}
                {player.opener_status === 'PLR' && (
                  <span className="text-[9px] font-bold px-1 py-0.5 rounded bg-blue-500/15 text-blue-400 leading-none">PLR</span>
                )}
              </div>
              <div className="flex items-center gap-2">
                {player.median_pts != null && (
                  <span className="text-[10px] font-mono text-blue-400/70">{player.median_pts.toFixed(1)}</span>
                )}
                {player.salary && (
                  <span className="text-[10px] font-mono text-gray-500">${(player.salary / 1000).toFixed(1)}k</span>
                )}
                {isConfirmed ? (
                  <Check className="w-3 h-3 text-emerald-500" />
                ) : (
                  <AlertCircle className="w-3 h-3 text-amber-500 opacity-40" />
                )}
              </div>
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


// ── Game card component ────────────────────────────────────────────────────

function GameCard({ game, liveState }) {
  const homeTeam = game.home_team_abbr || game.home.team;
  const displayTime = liveState?.game_time || game.game_time;

  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900 overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-800">
        {/* Row 1: Teams, game time, live score */}
        <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
          <div className="flex items-center gap-3">
            <span className="text-lg font-bold text-gray-100">{game.away.team}</span>
            <span className="text-xs text-gray-600">@</span>
            <span className="text-lg font-bold text-gray-100">{game.home.team}</span>
            {displayTime && (
              <div className="flex items-center gap-1 ml-1">
                <Clock className="w-3 h-3 text-gray-500" />
                <span className="text-[11px] text-gray-400">{displayTime}</span>
              </div>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <LiveScoreBadge liveState={liveState} />
            {(!liveState || liveState.game_status === 'Preview') && (
              <>
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
              </>
            )}
          </div>
        </div>

        {/* Row 2: Vegas odds + Weather */}
        <div className="flex items-center justify-between flex-wrap gap-2">
          <VegasBadge game={game} />
          <WeatherBadge weather={game.weather} homeTeam={homeTeam} />
        </div>
      </div>

      {/* Lineups */}
      <div className="px-4 py-3 grid grid-cols-1 sm:grid-cols-2 gap-4">
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


// ── Legend component ────────────────────────────────────────────────────────

function Legend() {
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900/50 px-4 py-2.5 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[11px]">
      <div className="flex items-center gap-1.5">
        <Check className="w-3.5 h-3.5 text-emerald-500" />
        <span className="text-gray-400">Confirmed lineup</span>
      </div>
      <div className="flex items-center gap-1.5">
        <AlertCircle className="w-3.5 h-3.5 text-amber-500" />
        <span className="text-gray-400">Expected / projected</span>
      </div>
      <div className="flex items-center gap-1.5">
        <AlertCircle className="w-3.5 h-3.5 text-blue-500" />
        <span className="text-gray-400">Projected</span>
      </div>
      <span className="text-gray-700">|</span>
      <div className="flex items-center gap-1.5">
        <span className="w-2 h-2 rounded-full bg-emerald-400"></span>
        <span className="text-gray-400">Wind out (hitter-friendly)</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="w-2 h-2 rounded-full bg-red-400"></span>
        <span className="text-gray-400">Wind in (pitcher-friendly)</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="w-2 h-2 rounded-full bg-amber-400"></span>
        <span className="text-gray-400">Cross-wind</span>
      </div>
    </div>
  );
}


// ── Main GameCenter page ───────────────────────────────────────────────────

export default function GameCenter() {
  const { selectedSlate, site, selectedDate } = useApp();
  const [games, setGames] = useState([]);
  const [liveScores, setLiveScores] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [slateFilter, setSlateFilter] = useState(true);
  const liveIntervalRef = useRef(null);

  // Determine if the selected date is today (for live score polling)
  const isToday = !selectedDate || selectedDate === new Date().toISOString().slice(0, 10);

  const loadGames = useCallback(async (forceRefresh = false) => {
    try {
      if (forceRefresh) setRefreshing(true);
      else setLoading(true);
      const slateId = slateFilter && selectedSlate ? selectedSlate.slate_id : null;
      const data = await api.getGameLineups(forceRefresh, site, selectedDate || null, slateId);
      setGames(data);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [site, selectedDate, selectedSlate, slateFilter]);

  const loadLiveScores = useCallback(async () => {
    if (!isToday) {
      setLiveScores([]);
      return;
    }
    try {
      const data = await api.getLiveScores();
      setLiveScores(data);
    } catch {
      // Silently fail for live scores
    }
  }, [isToday]);

  useEffect(() => {
    loadGames();
    loadLiveScores();

    // Auto-refresh lineups every 2 minutes
    const lineupInterval = setInterval(() => loadGames(true), 120000);

    // Auto-refresh live scores every 30 seconds (only for today)
    if (isToday) {
      liveIntervalRef.current = setInterval(loadLiveScores, 30000);
    }

    return () => {
      clearInterval(lineupInterval);
      if (liveIntervalRef.current) clearInterval(liveIntervalRef.current);
    };
  }, [loadGames, loadLiveScores, isToday]);

  // Build live score lookup by home+away teams
  const liveByTeams = {};
  for (const ls of liveScores) {
    const key = `${ls.away_team}@${ls.home_team}`;
    liveByTeams[key] = ls;
  }

  // Determine which games have a live/active status for faster refresh
  const hasLiveGames = liveScores.some(ls => ls.game_status === 'Live');

  // Dynamic live refresh: 30s when games are live, otherwise 60s (only for today)
  useEffect(() => {
    if (liveIntervalRef.current) clearInterval(liveIntervalRef.current);
    if (!isToday) return;
    const interval = hasLiveGames ? 30000 : 60000;
    liveIntervalRef.current = setInterval(loadLiveScores, interval);
    return () => { if (liveIntervalRef.current) clearInterval(liveIntervalRef.current); };
  }, [hasLiveGames, loadLiveScores, isToday]);

  // Filter games based on selected slate
  const filteredGames = slateFilter && selectedSlate
    ? games.filter(g => {
        // A game is on the slate if its slate_teams array is non-empty
        return g.slate_teams && g.slate_teams.length > 0;
      })
    : games;

  const confirmedCount = filteredGames.reduce((acc, g) => {
    if (g.away.status === 'confirmed') acc++;
    if (g.home.status === 'confirmed') acc++;
    return acc;
  }, 0);
  const totalTeams = filteredGames.length * 2;
  const liveCount = liveScores.filter(ls => ls.game_status === 'Live').length;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-gray-100">Game Center</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {filteredGames.length} games &middot; {confirmedCount}/{totalTeams} lineups confirmed
            {liveCount > 0 && (
              <span className="ml-2 text-red-400">&middot; {liveCount} live</span>
            )}
            {slateFilter && selectedSlate && games.length !== filteredGames.length && (
              <span className="ml-2 text-blue-400">
                (filtered to {selectedSlate.name})
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* Slate filter toggle */}
          {selectedSlate && (
            <button
              onClick={() => setSlateFilter(!slateFilter)}
              className={`text-[11px] px-2.5 py-1.5 rounded-lg border transition-colors ${
                slateFilter
                  ? 'bg-blue-500/10 border-blue-500/30 text-blue-400'
                  : 'bg-gray-800 border-gray-700 text-gray-500'
              }`}
            >
              {slateFilter ? 'Slate Only' : 'All Games'}
            </button>
          )}
          <button
            onClick={() => { loadGames(true); loadLiveScores(); }}
            disabled={refreshing}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-700 bg-gray-800 text-xs text-gray-300 hover:bg-gray-700 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* Legend */}
      <Legend />

      {/* Content */}
      {loading && !games.length ? (
        <div className="text-center py-12 text-gray-500">
          <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2" />
          Loading lineups...
        </div>
      ) : error ? (
        <div className="text-center py-12 text-red-400">
          Failed to load lineups: {error}
        </div>
      ) : filteredGames.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          {slateFilter && selectedSlate
            ? 'No games on this slate. Try toggling to "All Games".'
            : `No games found for ${isToday ? 'today' : selectedDate}.`}
        </div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {filteredGames.map((game, i) => {
            const liveKey = `${game.away.team}@${game.home.team}`;
            return (
              <GameCard
                key={i}
                game={game}
                liveState={liveByTeams[liveKey]}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
