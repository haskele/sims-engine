import { useLocalStorage } from '../hooks/useLocalStorage';

export default function SiteSwitcher() {
  const [site, setSite] = useLocalStorage('dfs-site', 'dk');

  return (
    <div className="flex items-center bg-gray-800 rounded-lg p-0.5">
      <button
        onClick={() => setSite('dk')}
        className={`px-3 py-1.5 rounded-md text-xs font-semibold tracking-wide transition-all ${
          site === 'dk'
            ? 'bg-emerald-600 text-white shadow-sm'
            : 'text-gray-400 hover:text-gray-200'
        }`}
      >
        DraftKings
      </button>
      <button
        onClick={() => setSite('fd')}
        className={`px-3 py-1.5 rounded-md text-xs font-semibold tracking-wide transition-all ${
          site === 'fd'
            ? 'bg-blue-600 text-white shadow-sm'
            : 'text-gray-400 hover:text-gray-200'
        }`}
      >
        FanDuel
      </button>
    </div>
  );
}

export function useSite() {
  const [site] = useLocalStorage('dfs-site', 'dk');
  return site;
}
