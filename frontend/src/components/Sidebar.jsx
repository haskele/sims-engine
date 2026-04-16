import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  TableProperties,
  Users,
  PlayCircle,
  Tv2,
  Upload,
  Trophy,
  History,
} from 'lucide-react';

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/projections', icon: TableProperties, label: 'Projections' },
  { to: '/lineups', icon: Users, label: 'Lineups' },
  { to: '/simulator', icon: PlayCircle, label: 'Simulator' },
  { to: '/games', icon: Tv2, label: 'Game Center' },
  { to: '/contests', icon: Upload, label: 'Contests' },
  { to: '/my-contests', icon: Trophy, label: 'My Contests' },
  { to: '/backtesting', icon: History, label: 'Backtesting' },
];

export default function Sidebar({ expanded, onToggle, mobileOpen, onMobileClose }) {
  return (
    <>
      {/* Mobile backdrop */}
      {mobileOpen && (
        <div
          className="fixed inset-0 bg-black/60 z-40 md:hidden"
          onClick={onMobileClose}
        />
      )}

      <aside
        onMouseEnter={() => onToggle(true)}
        onMouseLeave={() => onToggle(false)}
        className={`fixed left-0 top-0 h-screen bg-gray-900 border-r border-gray-800 z-50 flex flex-col sidebar-transition
          ${expanded ? 'w-56' : 'w-16'}
          ${mobileOpen ? 'translate-x-0 w-56' : '-translate-x-full'}
          md:translate-x-0
        `}
      >
        {/* Logo */}
        <div className="flex items-center h-14 px-4 border-b border-gray-800 shrink-0">
          <img src="/logo.png" alt="Sims Life" className="w-7 h-7 rounded-md shrink-0" />
          {(expanded || mobileOpen) && (
            <span className="ml-3 text-sm font-bold text-white tracking-wide whitespace-nowrap">
              Sims Life DFS
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
              onClick={onMobileClose}
              className={({ isActive }) =>
                `flex items-center h-10 px-4 mx-2 rounded-lg transition-colors group ${
                  isActive
                    ? 'bg-gray-800 text-emerald-400'
                    : 'text-gray-400 hover:text-gray-100 hover:bg-gray-800/60'
                }`
              }
            >
              <Icon className="w-5 h-5 shrink-0" />
              {(expanded || mobileOpen) && (
                <span className="ml-3 text-sm font-medium whitespace-nowrap">
                  {label}
                </span>
              )}
            </NavLink>
          ))}
        </nav>

        {/* Version */}
        <div className="px-4 py-3 border-t border-gray-800 shrink-0">
          {(expanded || mobileOpen) ? (
            <span className="text-[10px] text-gray-600 font-mono">v0.1.0-alpha</span>
          ) : (
            <span className="text-[10px] text-gray-600 font-mono block text-center">0.1</span>
          )}
        </div>
      </aside>
    </>
  );
}
