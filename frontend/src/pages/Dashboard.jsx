import { Link } from 'react-router-dom';
import { useApp, FAKE_USERS } from '../context/AppContext';
import {
  TableProperties,
  Users,
  PlayCircle,
  Tv2,
  Upload,
  ArrowRight,
  UserCircle,
  CalendarDays,
  Layers,
  ChevronRight,
  Zap,
  BarChart3,
} from 'lucide-react';

const STEPS = [
  {
    num: 1,
    title: 'Select a Date & Slate',
    desc: 'Use the header bar to pick today\'s date and choose a slate (Main, Night, etc). All pages read from these global selectors.',
    icon: CalendarDays,
    color: 'text-blue-400',
    bg: 'bg-blue-500/10',
    border: 'border-blue-500/20',
  },
  {
    num: 2,
    title: 'Review Projections',
    desc: 'The Projections tab shows hitters, pitchers, and team stacks with SaberSim data, DK props, and lineup status. Edit projections inline and set exposure limits.',
    icon: TableProperties,
    color: 'text-emerald-400',
    bg: 'bg-emerald-500/10',
    border: 'border-emerald-500/20',
    link: '/projections',
  },
  {
    num: 3,
    title: 'Import Contests',
    desc: 'Upload your DraftKings entries CSV to load contest details, entry counts, field sizes, and payout structures. These carry into the simulator.',
    icon: Upload,
    color: 'text-amber-400',
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/20',
    link: '/contests',
  },
  {
    num: 4,
    title: 'Build Lineups',
    desc: 'Configure the optimizer — set lineup count, variance, skew, and team stack exposures on the Teams tab. The optimizer uses progressive constraint relaxation to handle infeasible ownership targets.',
    icon: Users,
    color: 'text-purple-400',
    bg: 'bg-purple-500/10',
    border: 'border-purple-500/20',
    link: '/lineups',
  },
  {
    num: 5,
    title: 'Simulate & Analyze',
    desc: 'Run Monte Carlo simulations against your imported contests. See per-lineup ROI, cash rates, and distribution charts to evaluate your portfolio.',
    icon: PlayCircle,
    color: 'text-rose-400',
    bg: 'bg-rose-500/10',
    border: 'border-rose-500/20',
    link: '/simulator',
  },
];

export default function Dashboard() {
  const { currentUser, userId, selectedSlate, getCurrentBuild, uploadedContests } = useApp();
  const currentBuild = getCurrentBuild();
  const lineupCount = currentBuild?.lineups?.length || 0;
  const contestCount = uploadedContests?.length || 0;

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      {/* Welcome header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-100">
          Welcome to Sims Life DFS
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          Baseball DFS lineup optimizer, simulator, and contest analysis tool.
        </p>
      </div>

      {/* Current session card */}
      <div className="rounded-xl border border-gray-800 bg-gray-900 p-5">
        <div className="flex items-center gap-3 mb-4">
          <div
            className="w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold text-white"
            style={{ backgroundColor: currentUser.color }}
          >
            {currentUser.name.split(' ').map(w => w[0]).join('')}
          </div>
          <div>
            <div className="text-sm font-semibold text-gray-100">{currentUser.name}</div>
            <div className="text-xs text-gray-500">
              Switch users in the top-right dropdown — each user gets their own builds, contests, and settings
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="rounded-lg bg-gray-950 px-3 py-2.5">
            <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-0.5">Slate</div>
            <div className="text-sm font-mono text-gray-200 truncate">
              {selectedSlate?.name || 'None selected'}
            </div>
          </div>
          <div className="rounded-lg bg-gray-950 px-3 py-2.5">
            <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-0.5">Build</div>
            <div className="text-sm font-mono text-gray-200">
              {currentBuild?.name || 'Build 1'}
            </div>
          </div>
          <div className="rounded-lg bg-gray-950 px-3 py-2.5">
            <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-0.5">Lineups</div>
            <div className={`text-sm font-mono ${lineupCount > 0 ? 'text-emerald-400' : 'text-gray-500'}`}>
              {lineupCount > 0 ? lineupCount : 'None yet'}
            </div>
          </div>
          <div className="rounded-lg bg-gray-950 px-3 py-2.5">
            <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-0.5">Contests</div>
            <div className={`text-sm font-mono ${contestCount > 0 ? 'text-blue-400' : 'text-gray-500'}`}>
              {contestCount > 0 ? contestCount : 'None uploaded'}
            </div>
          </div>
        </div>
      </div>

      {/* How it works */}
      <div>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">How It Works</h2>
        <div className="space-y-3">
          {STEPS.map((step) => (
            <div
              key={step.num}
              className={`rounded-lg border ${step.border} ${step.bg} p-4 flex items-start gap-4`}
            >
              <div className={`shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${step.bg} border ${step.border}`}>
                <span className={`text-sm font-bold ${step.color}`}>{step.num}</span>
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <step.icon className={`w-4 h-4 ${step.color}`} />
                  <h3 className={`text-sm font-semibold ${step.color}`}>{step.title}</h3>
                </div>
                <p className="text-xs text-gray-400 mt-1 leading-relaxed">{step.desc}</p>
              </div>
              {step.link && (
                <Link
                  to={step.link}
                  className="shrink-0 self-center p-2 rounded-lg hover:bg-gray-800/50 transition-colors"
                >
                  <ArrowRight className={`w-4 h-4 ${step.color}`} />
                </Link>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Multi-user note */}
      <div className="rounded-lg border border-gray-800 bg-gray-900/50 p-4">
        <div className="flex items-start gap-3">
          <UserCircle className="w-5 h-5 text-gray-500 shrink-0 mt-0.5" />
          <div>
            <h3 className="text-xs font-semibold text-gray-300 mb-1">Multi-User Testing</h3>
            <p className="text-xs text-gray-500 leading-relaxed">
              This tool includes {FAKE_USERS.length} test accounts accessible from the header dropdown.
              Each account maintains its own lineup builds and uploaded contests per slate.
              Switch between accounts to test different strategies side-by-side
              without overwriting each other's work.
            </p>
            <div className="flex items-center gap-3 mt-3">
              {FAKE_USERS.map(u => (
                <div key={u.id} className="flex items-center gap-1.5">
                  <div
                    className="w-2.5 h-2.5 rounded-full"
                    style={{ backgroundColor: u.color }}
                  />
                  <span className={`text-[11px] font-mono ${u.id === userId ? 'text-gray-200 font-semibold' : 'text-gray-500'}`}>
                    {u.name}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Quick links */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pb-4">
        {[
          { to: '/projections', label: 'Projections', icon: TableProperties, color: 'text-emerald-400' },
          { to: '/lineups', label: 'Build Lineups', icon: Zap, color: 'text-purple-400' },
          { to: '/games', label: 'Game Center', icon: Tv2, color: 'text-blue-400' },
          { to: '/simulator', label: 'Simulator', icon: BarChart3, color: 'text-rose-400' },
        ].map(({ to, label, icon: Icon, color }) => (
          <Link
            key={to}
            to={to}
            className="flex items-center gap-2.5 px-4 py-3 rounded-lg border border-gray-800 bg-gray-900 hover:bg-gray-800 hover:border-gray-700 transition-all group"
          >
            <Icon className={`w-4 h-4 ${color}`} />
            <span className="text-xs font-semibold text-gray-300 group-hover:text-gray-100">{label}</span>
            <ChevronRight className="w-3.5 h-3.5 text-gray-600 ml-auto group-hover:text-gray-400 transition-colors" />
          </Link>
        ))}
      </div>
    </div>
  );
}
