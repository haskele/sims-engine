import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import SiteSwitcher from './SiteSwitcher';
import { Settings, Calendar, Clock } from 'lucide-react';

export default function Layout() {
  const [sidebarExpanded, setSidebarExpanded] = useState(false);

  const today = new Date().toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  });

  return (
    <div className="min-h-screen bg-gray-950">
      <Sidebar expanded={sidebarExpanded} onToggle={setSidebarExpanded} />

      {/* Top bar */}
      <header
        className={`fixed top-0 right-0 h-14 bg-gray-900/80 backdrop-blur-md border-b border-gray-800 z-30 flex items-center justify-between px-6 transition-all ${
          sidebarExpanded ? 'left-56' : 'left-16'
        }`}
      >
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 text-sm text-gray-400">
            <Calendar className="w-4 h-4" />
            <span>{today}</span>
          </div>
          <div className="w-px h-5 bg-gray-700" />
          <div className="flex items-center gap-2 text-sm text-gray-400">
            <Clock className="w-4 h-4" />
            <span>Main Slate</span>
            <span className="text-gray-600">|</span>
            <span className="text-emerald-400 font-mono text-xs">12 games</span>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <SiteSwitcher />
          <button className="p-2 text-gray-400 hover:text-gray-100 hover:bg-gray-800 rounded-lg transition-colors">
            <Settings className="w-4 h-4" />
          </button>
        </div>
      </header>

      {/* Main content */}
      <main
        className={`pt-14 min-h-screen transition-all ${
          sidebarExpanded ? 'ml-56' : 'ml-16'
        }`}
      >
        <div className="p-6">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
