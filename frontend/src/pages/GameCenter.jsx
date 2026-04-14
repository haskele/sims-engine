import { Check, AlertCircle, Cloud, Sun, Thermometer, Wind, MapPin } from 'lucide-react';

const mockGames = [
  {
    id: 1,
    away: { abbr: 'NYY', name: 'Yankees' },
    home: { abbr: 'BOS', name: 'Red Sox' },
    time: '1:10 PM ET',
    venue: 'Fenway Park',
    vegasLine: 'NYY -145',
    total: 9.0,
    weather: { temp: 62, condition: 'Partly Cloudy', wind: '12 mph out to CF' },
    awayPitcher: {
      name: 'Gerrit Cole', hand: 'R', record: '6-2', era: '2.89', whip: '0.98',
      k9: '10.8', ip: '84.0', fip: '2.65',
    },
    homePitcher: {
      name: 'Brayan Bello', hand: 'R', record: '5-3', era: '3.42', whip: '1.15',
      k9: '8.2', ip: '76.1', fip: '3.55',
    },
    awayLineup: [
      { order: 1, name: 'Anthony Volpe', pos: 'SS', avg: '.268', ops: '.745', confirmed: true },
      { order: 2, name: 'Aaron Judge', pos: 'RF', avg: '.322', ops: '1.085', confirmed: true },
      { order: 3, name: 'Juan Soto', pos: 'LF', avg: '.298', ops: '.985', confirmed: true },
      { order: 4, name: 'Giancarlo Stanton', pos: 'DH', avg: '.245', ops: '.825', confirmed: true },
      { order: 5, name: 'Anthony Rizzo', pos: '1B', avg: '.232', ops: '.715', confirmed: true },
      { order: 6, name: 'Gleyber Torres', pos: '2B', avg: '.255', ops: '.748', confirmed: true },
      { order: 7, name: 'Alex Verdugo', pos: 'CF', avg: '.241', ops: '.682', confirmed: true },
      { order: 8, name: 'DJ LeMahieu', pos: '3B', avg: '.228', ops: '.668', confirmed: false },
      { order: 9, name: 'Jose Trevino', pos: 'C', avg: '.218', ops: '.612', confirmed: false },
    ],
    homeLineup: [
      { order: 1, name: 'Jarren Duran', pos: 'CF', avg: '.285', ops: '.815', confirmed: true },
      { order: 2, name: 'Tyler O\'Neill', pos: 'LF', avg: '.262', ops: '.825', confirmed: true },
      { order: 3, name: 'Rafael Devers', pos: '3B', avg: '.288', ops: '.918', confirmed: true },
      { order: 4, name: 'Masataka Yoshida', pos: 'DH', avg: '.295', ops: '.838', confirmed: true },
      { order: 5, name: 'Triston Casas', pos: '1B', avg: '.255', ops: '.842', confirmed: true },
      { order: 6, name: 'Connor Wong', pos: 'C', avg: '.248', ops: '.735', confirmed: true },
      { order: 7, name: 'Ceddanne Rafaela', pos: 'SS', avg: '.242', ops: '.698', confirmed: false },
      { order: 8, name: 'Enmanuel Valdez', pos: '2B', avg: '.235', ops: '.702', confirmed: false },
      { order: 9, name: 'Wilyer Abreu', pos: 'RF', avg: '.252', ops: '.742', confirmed: false },
    ],
  },
  {
    id: 2,
    away: { abbr: 'LAD', name: 'Dodgers' },
    home: { abbr: 'SF', name: 'Giants' },
    time: '4:05 PM ET',
    venue: 'Oracle Park',
    vegasLine: 'LAD -165',
    total: 7.5,
    weather: { temp: 58, condition: 'Overcast', wind: '8 mph in from CF' },
    awayPitcher: {
      name: 'Yoshinobu Yamamoto', hand: 'R', record: '7-1', era: '2.55', whip: '0.92',
      k9: '9.5', ip: '78.0', fip: '2.78',
    },
    homePitcher: {
      name: 'Logan Webb', hand: 'R', record: '5-4', era: '3.15', whip: '1.08',
      k9: '7.8', ip: '88.2', fip: '3.22',
    },
    awayLineup: [
      { order: 1, name: 'Mookie Betts', pos: 'SS', avg: '.295', ops: '.962', confirmed: true },
      { order: 2, name: 'Freddie Freeman', pos: '1B', avg: '.305', ops: '.945', confirmed: true },
      { order: 3, name: 'Shohei Ohtani', pos: 'DH', avg: '.312', ops: '1.045', confirmed: true },
      { order: 4, name: 'Teoscar Hernandez', pos: 'LF', avg: '.275', ops: '.845', confirmed: true },
      { order: 5, name: 'Max Muncy', pos: '3B', avg: '.242', ops: '.815', confirmed: true },
      { order: 6, name: 'Will Smith', pos: 'C', avg: '.262', ops: '.798', confirmed: true },
      { order: 7, name: 'James Outman', pos: 'CF', avg: '.228', ops: '.718', confirmed: false },
      { order: 8, name: 'Gavin Lux', pos: '2B', avg: '.245', ops: '.695', confirmed: false },
      { order: 9, name: 'Jason Heyward', pos: 'RF', avg: '.218', ops: '.665', confirmed: false },
    ],
    homeLineup: [
      { order: 1, name: 'Jung Hoo Lee', pos: 'CF', avg: '.275', ops: '.782', confirmed: true },
      { order: 2, name: 'Matt Chapman', pos: '3B', avg: '.258', ops: '.815', confirmed: true },
      { order: 3, name: 'Jorge Soler', pos: 'DH', avg: '.248', ops: '.835', confirmed: true },
      { order: 4, name: 'Heliot Ramos', pos: 'RF', avg: '.268', ops: '.798', confirmed: true },
      { order: 5, name: 'LaMonte Wade Jr.', pos: '1B', avg: '.255', ops: '.762', confirmed: false },
      { order: 6, name: 'Patrick Bailey', pos: 'C', avg: '.242', ops: '.725', confirmed: false },
      { order: 7, name: 'Michael Conforto', pos: 'LF', avg: '.235', ops: '.715', confirmed: false },
      { order: 8, name: 'Nick Ahmed', pos: 'SS', avg: '.215', ops: '.598', confirmed: false },
      { order: 9, name: 'Thairo Estrada', pos: '2B', avg: '.242', ops: '.685', confirmed: false },
    ],
  },
  {
    id: 3,
    away: { abbr: 'ATL', name: 'Braves' },
    home: { abbr: 'NYM', name: 'Mets' },
    time: '7:10 PM ET',
    venue: 'Citi Field',
    vegasLine: 'ATL -130',
    total: 8.5,
    weather: { temp: 71, condition: 'Clear', wind: '6 mph out to LF' },
    awayPitcher: {
      name: 'Chris Sale', hand: 'L', record: '8-1', era: '2.45', whip: '0.95',
      k9: '11.2', ip: '92.0', fip: '2.52',
    },
    homePitcher: {
      name: 'Kodai Senga', hand: 'R', record: '4-3', era: '3.28', whip: '1.05',
      k9: '9.8', ip: '62.1', fip: '3.15',
    },
    awayLineup: [
      { order: 1, name: 'Ronald Acuna Jr.', pos: 'RF', avg: '.298', ops: '.985', confirmed: true },
      { order: 2, name: 'Austin Riley', pos: '3B', avg: '.275', ops: '.865', confirmed: true },
      { order: 3, name: 'Matt Olson', pos: '1B', avg: '.252', ops: '.842', confirmed: true },
      { order: 4, name: 'Marcell Ozuna', pos: 'DH', avg: '.268', ops: '.888', confirmed: true },
      { order: 5, name: 'Ozzie Albies', pos: '2B', avg: '.278', ops: '.815', confirmed: true },
      { order: 6, name: 'Michael Harris II', pos: 'CF', avg: '.262', ops: '.758', confirmed: true },
      { order: 7, name: 'Sean Murphy', pos: 'C', avg: '.248', ops: '.775', confirmed: false },
      { order: 8, name: 'Orlando Arcia', pos: 'SS', avg: '.238', ops: '.692', confirmed: false },
      { order: 9, name: 'Jarred Kelenic', pos: 'LF', avg: '.225', ops: '.668', confirmed: false },
    ],
    homeLineup: [
      { order: 1, name: 'Francisco Lindor', pos: 'SS', avg: '.272', ops: '.825', confirmed: true },
      { order: 2, name: 'Juan Soto', pos: 'RF', avg: '.298', ops: '.985', confirmed: true },
      { order: 3, name: 'Pete Alonso', pos: '1B', avg: '.248', ops: '.825', confirmed: true },
      { order: 4, name: 'Brandon Nimmo', pos: 'LF', avg: '.265', ops: '.798', confirmed: true },
      { order: 5, name: 'J.D. Martinez', pos: 'DH', avg: '.255', ops: '.812', confirmed: true },
      { order: 6, name: 'Mark Vientos', pos: '3B', avg: '.258', ops: '.788', confirmed: false },
      { order: 7, name: 'Jeff McNeil', pos: '2B', avg: '.242', ops: '.695', confirmed: false },
      { order: 8, name: 'Francisco Alvarez', pos: 'C', avg: '.225', ops: '.735', confirmed: false },
      { order: 9, name: 'Tyrone Taylor', pos: 'CF', avg: '.218', ops: '.662', confirmed: false },
    ],
  },
  {
    id: 4,
    away: { abbr: 'HOU', name: 'Astros' },
    home: { abbr: 'TEX', name: 'Rangers' },
    time: '8:05 PM ET',
    venue: 'Globe Life Field',
    vegasLine: 'TEX -125',
    total: 8.0,
    weather: { temp: 72, condition: 'Dome', wind: 'N/A (retractable roof)' },
    awayPitcher: {
      name: 'Framber Valdez', hand: 'L', record: '4-4', era: '3.65', whip: '1.22',
      k9: '7.5', ip: '72.0', fip: '3.82',
    },
    homePitcher: {
      name: 'Nathan Eovaldi', hand: 'R', record: '5-2', era: '3.12', whip: '1.05',
      k9: '8.8', ip: '80.2', fip: '3.28',
    },
    awayLineup: [
      { order: 1, name: 'Jose Altuve', pos: '2B', avg: '.288', ops: '.832', confirmed: true },
      { order: 2, name: 'Kyle Tucker', pos: 'LF', avg: '.278', ops: '.895', confirmed: true },
      { order: 3, name: 'Yordan Alvarez', pos: 'DH', avg: '.285', ops: '.945', confirmed: true },
      { order: 4, name: 'Alex Bregman', pos: '3B', avg: '.262', ops: '.802', confirmed: true },
      { order: 5, name: 'Jeremy Pena', pos: 'SS', avg: '.248', ops: '.728', confirmed: false },
      { order: 6, name: 'Yainer Diaz', pos: 'C', avg: '.268', ops: '.778', confirmed: false },
      { order: 7, name: 'Jake Meyers', pos: 'CF', avg: '.245', ops: '.712', confirmed: false },
      { order: 8, name: 'Mauricio Dubon', pos: 'RF', avg: '.238', ops: '.682', confirmed: false },
      { order: 9, name: 'Jon Singleton', pos: '1B', avg: '.222', ops: '.725', confirmed: false },
    ],
    homeLineup: [
      { order: 1, name: 'Marcus Semien', pos: '2B', avg: '.268', ops: '.792', confirmed: true },
      { order: 2, name: 'Corey Seager', pos: 'SS', avg: '.282', ops: '.912', confirmed: true },
      { order: 3, name: 'Josh Jung', pos: '3B', avg: '.275', ops: '.855', confirmed: true },
      { order: 4, name: 'Wyatt Langford', pos: 'LF', avg: '.258', ops: '.808', confirmed: true },
      { order: 5, name: 'Adolis Garcia', pos: 'RF', avg: '.245', ops: '.792', confirmed: true },
      { order: 6, name: 'Nathaniel Lowe', pos: '1B', avg: '.262', ops: '.775', confirmed: false },
      { order: 7, name: 'Jonah Heim', pos: 'C', avg: '.238', ops: '.718', confirmed: false },
      { order: 8, name: 'Leody Taveras', pos: 'CF', avg: '.225', ops: '.665', confirmed: false },
      { order: 9, name: 'Evan Carter', pos: 'DH', avg: '.242', ops: '.742', confirmed: false },
    ],
  },
];

function WeatherBadge({ weather }) {
  const icon = weather.condition.includes('Clear') || weather.condition.includes('Sunny')
    ? <Sun className="w-3.5 h-3.5 text-amber-400" />
    : weather.condition.includes('Dome')
    ? <MapPin className="w-3.5 h-3.5 text-gray-400" />
    : <Cloud className="w-3.5 h-3.5 text-gray-400" />;

  return (
    <div className="flex items-center gap-3 text-xs text-gray-400">
      <div className="flex items-center gap-1">{icon}<span>{weather.temp}°F</span></div>
      <div className="flex items-center gap-1"><Wind className="w-3.5 h-3.5" /><span>{weather.wind}</span></div>
    </div>
  );
}

function PitcherCard({ pitcher, side }) {
  return (
    <div className="flex-1 p-3 rounded-lg bg-gray-950">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
            pitcher.hand === 'L' ? 'bg-blue-500/15 text-blue-400' : 'bg-red-500/15 text-red-400'
          }`}>
            {pitcher.hand}HP
          </span>
          <span className="text-sm font-semibold text-gray-100">{pitcher.name}</span>
        </div>
        <span className="text-xs font-mono text-gray-500">{pitcher.record}</span>
      </div>
      <div className="grid grid-cols-4 gap-2">
        {[
          { label: 'ERA', value: pitcher.era },
          { label: 'WHIP', value: pitcher.whip },
          { label: 'K/9', value: pitcher.k9 },
          { label: 'FIP', value: pitcher.fip },
        ].map((stat) => (
          <div key={stat.label} className="text-center">
            <div className="text-[10px] uppercase tracking-wider text-gray-600">{stat.label}</div>
            <div className="text-xs font-mono text-gray-300">{stat.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function LineupTable({ lineup, teamAbbr }) {
  const confirmedCount = lineup.filter(p => p.confirmed).length;
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-gray-400">{teamAbbr} Lineup</span>
        <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${
          confirmedCount === 9
            ? 'bg-emerald-500/10 text-emerald-400'
            : 'bg-amber-500/10 text-amber-400'
        }`}>
          {confirmedCount}/9 Confirmed
        </span>
      </div>
      <div className="space-y-0">
        {lineup.map((player, i) => (
          <div
            key={i}
            className={`flex items-center justify-between px-2 py-1 rounded ${
              i % 2 === 0 ? 'bg-gray-950' : ''
            }`}
          >
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-mono text-gray-600 w-4">{player.order}</span>
              <span className="text-[10px] font-bold text-gray-500 w-6">{player.pos}</span>
              <span className={`text-xs ${player.confirmed ? 'text-gray-200' : 'text-gray-500'}`}>
                {player.name}
              </span>
              {player.confirmed ? (
                <Check className="w-3 h-3 text-emerald-500" />
              ) : (
                <AlertCircle className="w-3 h-3 text-amber-500 opacity-50" />
              )}
            </div>
            <div className="flex items-center gap-3 text-[10px] font-mono text-gray-500">
              <span>{player.avg}</span>
              <span className="text-gray-400">{player.ops}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function GameCard({ game }) {
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900 overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-lg font-bold text-gray-100">{game.away.abbr}</span>
          <span className="text-xs text-gray-600">@</span>
          <span className="text-lg font-bold text-gray-100">{game.home.abbr}</span>
        </div>
        <div className="text-right">
          <div className="text-xs font-mono text-gray-400">{game.time}</div>
          <div className="text-[10px] text-gray-600">{game.venue}</div>
        </div>
      </div>

      {/* Vegas & Weather */}
      <div className="px-4 py-2 border-b border-gray-800 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div>
            <span className="text-[10px] text-gray-500 mr-1.5">Line</span>
            <span className="text-xs font-mono text-gray-300">{game.vegasLine}</span>
          </div>
          <div>
            <span className="text-[10px] text-gray-500 mr-1.5">O/U</span>
            <span className="text-xs font-mono text-gray-300">{game.total}</span>
          </div>
        </div>
        <WeatherBadge weather={game.weather} />
      </div>

      {/* Pitchers */}
      <div className="px-4 py-3 border-b border-gray-800">
        <div className="flex gap-3">
          <PitcherCard pitcher={game.awayPitcher} side="away" />
          <PitcherCard pitcher={game.homePitcher} side="home" />
        </div>
      </div>

      {/* Lineups */}
      <div className="px-4 py-3 grid grid-cols-2 gap-4">
        <LineupTable lineup={game.awayLineup} teamAbbr={game.away.abbr} />
        <LineupTable lineup={game.homeLineup} teamAbbr={game.home.abbr} />
      </div>
    </div>
  );
}

export default function GameCenter() {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-100">Game Center</h1>
          <p className="text-sm text-gray-500 mt-0.5">{mockGames.length} games on today's slate</p>
        </div>
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <div className="flex items-center gap-1.5">
            <Check className="w-3.5 h-3.5 text-emerald-500" />
            <span>Confirmed</span>
          </div>
          <div className="flex items-center gap-1.5 ml-3">
            <AlertCircle className="w-3.5 h-3.5 text-amber-500" />
            <span>Projected</span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {mockGames.map((game) => (
          <GameCard key={game.id} game={game} />
        ))}
      </div>
    </div>
  );
}
