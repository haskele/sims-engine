import { useState, useMemo } from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import SiteSwitcher from './SiteSwitcher';
import { useApp, FAKE_USERS } from '../context/AppContext';
import { Settings, Calendar, ChevronDown, Plus, Menu, User } from 'lucide-react';

function daysAgo(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function todayStr() {
  return new Date().toISOString().slice(0, 10);
}

export default function Layout() {
  const [sidebarExpanded, setSidebarExpanded] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const { slates, selectedSlate, setSelectedSlate, selectedDate, setSelectedDate, builds, currentBuildIndex, setCurrentBuildIndex, createBuild, getCurrentBuild, userId, setUserId, currentUser } = useApp();

  const minDate = useMemo(() => daysAgo(30), []);
  const maxDate = useMemo(() => todayStr(), []);

  const currentBuild = getCurrentBuild();
  const lineupCount = currentBuild?.lineups?.length || 0;

  return (
    <div className="min-h-screen bg-gray-950">
      <Sidebar
        expanded={sidebarExpanded}
        onToggle={setSidebarExpanded}
        mobileOpen={mobileMenuOpen}
        onMobileClose={() => setMobileMenuOpen(false)}
      />

      {/* Top bar */}
      <header
        className={`fixed top-0 right-0 h-14 bg-gray-900/80 backdrop-blur-md border-b border-gray-800 z-30 flex items-center justify-between px-3 md:px-6 transition-all
          left-0 md:left-16 ${sidebarExpanded ? 'md:left-56' : 'md:left-16'}
        `}
      >
        <div className="flex items-center gap-2 md:gap-4 overflow-x-auto min-w-0">
          {/* Hamburger - mobile only */}
          <button
            onClick={() => setMobileMenuOpen(true)}
            className="p-2 text-gray-400 hover:text-gray-100 hover:bg-gray-800 rounded-lg transition-colors md:hidden shrink-0"
          >
            <Menu className="w-5 h-5" />
          </button>

          <div className="flex items-center gap-2 text-sm text-gray-400 shrink-0">
            <Calendar className="w-4 h-4 hidden sm:block" />
            <input
              type="date"
              value={selectedDate}
              min={minDate}
              max={maxDate}
              onChange={(e) => setSelectedDate(e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded-lg px-2 py-1 text-xs text-gray-200 focus:outline-none focus:border-blue-500 [color-scheme:dark]"
            />
          </div>
          <div className="w-px h-5 bg-gray-700 hidden sm:block shrink-0" />

          {/* Slate selector */}
          <div className="flex items-center gap-2 shrink-0">
            {slates.length > 0 ? (
              <select
                value={selectedSlate?.slate_id || ''}
                onChange={(e) => {
                  const slate = slates.find(s => s.slate_id === e.target.value);
                  if (slate) setSelectedSlate(slate);
                }}
                className="bg-gray-800 border border-gray-700 rounded-lg px-2 md:px-3 py-1.5 text-xs text-gray-200 focus:outline-none focus:border-blue-500 max-w-[140px] md:max-w-none"
              >
                {slates.map(s => (
                  <option key={s.slate_id} value={s.slate_id}>
                    {s.is_historical ? '[H] ' : ''}{s.name} ({s.game_count} games)
                  </option>
                ))}
              </select>
            ) : (
              <span className="text-xs text-gray-500">No slates</span>
            )}
          </div>

          <div className="w-px h-5 bg-gray-700 hidden sm:block shrink-0" />

          {/* Build selector */}
          <div className="flex items-center gap-1.5 shrink-0">
            <select
              value={currentBuildIndex}
              onChange={(e) => setCurrentBuildIndex(Number(e.target.value))}
              className="bg-gray-800 border border-gray-700 rounded-lg px-2 md:px-3 py-1.5 text-xs text-gray-200 focus:outline-none focus:border-blue-500 max-w-[120px] md:max-w-none"
            >
              {builds.map((b, i) => (
                <option key={b.id} value={i}>
                  {b.name}{b.lineups.length > 0 ? ` (${b.lineups.length} lineups)` : ''}
                </option>
              ))}
            </select>
            <button
              onClick={createBuild}
              className="p-1.5 rounded-lg border border-gray-700 bg-gray-800 text-gray-400 hover:text-gray-200 hover:bg-gray-700 transition-colors"
              title="New Build"
            >
              <Plus className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        <div className="flex items-center gap-2 md:gap-4 shrink-0">
          <SiteSwitcher />
          {/* User account selector */}
          <div className="flex items-center gap-1.5">
            <div
              className="w-2 h-2 rounded-full shrink-0"
              style={{ backgroundColor: currentUser.color }}
            />
            <select
              value={userId}
              onChange={(e) => setUserId(e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-xs text-gray-200 focus:outline-none focus:border-blue-500 max-w-[100px] md:max-w-none"
            >
              {FAKE_USERS.map(u => (
                <option key={u.id} value={u.id}>{u.name}</option>
              ))}
            </select>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main
        className={`pt-14 min-h-screen transition-all
          ml-0 md:ml-16 ${sidebarExpanded ? 'md:ml-56' : 'md:ml-16'}
        `}
      >
        <div className="p-3 md:p-6">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
