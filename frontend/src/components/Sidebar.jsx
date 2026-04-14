import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  TableProperties,
  Users,
  PlayCircle,
  Tv2,
  Upload,
  History,
  Zap,
} from 'lucide-react';

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/projections', icon: TableProperties, label: 'Projections' },
  { to: '/lineups', icon: Users, label: 'Lineups' },
  { to: '/simulator', icon: PlayCircle, label: 'Simulator' },
  { to: '/games', icon: Tv2, label: 'Game Center' },
  { to: '/contests', icon: Upload, label: 'Contests' },
  { to: '/backtesting', icon: History, label: 'Backtesting' },
];

export default function Sidebar({ expanded, onToggle }) {
  return (
    <aside
      onMouseEnter={() => onToggle(true)}
      onMouseLeave={() => onToggle(false)}
      className={`fixed left-0 top-0 h-screen bg-gray-900 border-r border-gray-800 z-40 flex flex-col sidebar-transition ${
        expanded ? 'w-56' : 'w-16'
      }`}
    >
      {/* Logo */}
      <div className="flex items-center h-14 px-4 border-b border-gray-800 shrink-0">
        <Zap className="w-6 h-6 text-emerald-500 shrink-0" />
        {expanded && (
          <span className="ml-3 text-sm font-bold text-white tracking-wide whitespace-nowrap">
            DFS Simulator
          </span>
        )}
      </div>

      {/* Nav links */}
      <nav className="flex-1 py-3 space-y-0.5 overflow-hidden">
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `flex items-center h-10 px-4 mx-2 rounded-lg transition-colors group ${
                isActive
                  ? 'bg-gray-800 text-emerald-400'
                  : 'text-gray-400 hover:text-gray-100 hover:bg-gray-800/60'
              }`
            }
          >
            <Icon className="w-5 h-5 shrink-0" />
            {expanded && (
              <span className="ml-3 text-sm font-medium whitespace-nowrap">
                {label}
              </span>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Version */}
      <div className="px-4 py-3 border-t border-gray-800 shrink-0">
        {expanded ? (
          <span className="text-[10px] text-gray-600 font-mono">v0.1.0-alpha</span>
        ) : (
          <span className="text-[10px] text-gray-600 font-mono block text-center">0.1</span>
        )}
      </div>
    </aside>
  );
}
