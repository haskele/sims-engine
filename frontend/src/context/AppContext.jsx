import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../api/client';

const AppContext = createContext(null);

// Fake user accounts for testing
const FAKE_USERS = [
  { id: 'user-1', name: 'Player 1', color: '#3b82f6' },
  { id: 'user-2', name: 'Player 2', color: '#10b981' },
  { id: 'user-3', name: 'Player 3', color: '#f59e0b' },
  { id: 'user-4', name: 'Player 4', color: '#ef4444' },
  { id: 'user-5', name: 'Player 5', color: '#8b5cf6' },
];

let nextBuildId = 1;

function createEmptyBuild(name) {
  return { id: nextBuildId++, name, lineups: [] };
}

function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function buildsKey(userId, date, slateId) {
  return `dfs-builds-${userId}-${date}-${slateId}`;
}

function buildIndexKey(userId, date, slateId) {
  return `dfs-build-idx-${userId}-${date}-${slateId}`;
}

function contestsKey(userId, date, slateId) {
  return `dfs-contests-${userId}-${date}-${slateId}`;
}

function exposuresKey(userId, date, slateId) {
  return `dfs-exposures-${userId}-${date}-${slateId}`;
}

function stackExposuresKey(userId, date, slateId) {
  return `dfs-stack-exposures-${userId}-${date}-${slateId}`;
}

function saveExposuresToStorage(userId, date, slateId, exposures) {
  if (!userId || !date || !slateId) return;
  try { localStorage.setItem(exposuresKey(userId, date, slateId), JSON.stringify(exposures)); }
  catch { /* storage full, ignore */ }
}

function loadExposuresFromStorage(userId, date, slateId) {
  if (!userId || !date || !slateId) return null;
  try {
    const raw = localStorage.getItem(exposuresKey(userId, date, slateId));
    if (raw) return JSON.parse(raw);
  } catch { /* corrupt data, ignore */ }
  return null;
}

function saveStackExposuresToStorage(userId, date, slateId, exposures) {
  if (!userId || !date || !slateId) return;
  try { localStorage.setItem(stackExposuresKey(userId, date, slateId), JSON.stringify(exposures)); }
  catch { /* storage full, ignore */ }
}

function loadStackExposuresFromStorage(userId, date, slateId) {
  if (!userId || !date || !slateId) return null;
  try {
    const raw = localStorage.getItem(stackExposuresKey(userId, date, slateId));
    if (raw) return JSON.parse(raw);
  } catch { /* corrupt data, ignore */ }
  return null;
}

function saveBuildsToStorage(userId, date, slateId, builds) {
  if (!userId || !date || !slateId) return;
  try { localStorage.setItem(buildsKey(userId, date, slateId), JSON.stringify(builds)); }
  catch { /* storage full, ignore */ }
}

function loadBuildsFromStorage(userId, date, slateId) {
  if (!userId || !date || !slateId) return null;
  try {
    const raw = localStorage.getItem(buildsKey(userId, date, slateId));
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) {
        // Ensure nextBuildId stays ahead of loaded ids
        parsed.forEach(b => { if (b.id >= nextBuildId) nextBuildId = b.id + 1; });
        return parsed;
      }
    }
  } catch { /* corrupt data, ignore */ }
  return null;
}

function saveBuildIndex(userId, date, slateId, idx) {
  if (!userId || !date || !slateId) return;
  try { localStorage.setItem(buildIndexKey(userId, date, slateId), String(idx)); }
  catch { /* storage full, ignore */ }
}

function loadBuildIndex(userId, date, slateId) {
  if (!userId || !date || !slateId) return 0;
  try {
    const raw = localStorage.getItem(buildIndexKey(userId, date, slateId));
    if (raw != null) return parseInt(raw, 10) || 0;
  } catch { /* corrupt, ignore */ }
  return 0;
}

function saveContestsToStorage(userId, date, slateId, contests) {
  if (!userId || !date || !slateId) return;
  try { localStorage.setItem(contestsKey(userId, date, slateId), JSON.stringify(contests)); }
  catch { /* storage full, ignore */ }
}

function loadContestsFromStorage(userId, date, slateId) {
  if (!userId || !date || !slateId) return null;
  try {
    const raw = localStorage.getItem(contestsKey(userId, date, slateId));
    if (raw) return JSON.parse(raw);
  } catch { /* corrupt data, ignore */ }
  return null;
}

export { FAKE_USERS };

export function AppProvider({ children }) {
  // Current user
  const [userId, setUserIdRaw] = useState(() => {
    try { return localStorage.getItem('dfs-user-id') || 'user-1'; }
    catch { return 'user-1'; }
  });
  const setUserId = (id) => {
    setUserIdRaw(id);
    localStorage.setItem('dfs-user-id', id);
  };
  const currentUser = FAKE_USERS.find(u => u.id === userId) || FAKE_USERS[0];

  // Site (DK / FD)
  const [site, setSiteRaw] = useState(() => {
    try { return JSON.parse(localStorage.getItem('dfs-site')) || 'dk'; }
    catch { return 'dk'; }
  });
  const setSite = (s) => {
    setSiteRaw(s);
    localStorage.setItem('dfs-site', JSON.stringify(s));
  };

  // Selected date
  const [selectedDate, setSelectedDateRaw] = useState(() => {
    try { return localStorage.getItem('dfs-selected-date') || todayStr(); }
    catch { return todayStr(); }
  });
  const setSelectedDate = (d) => {
    setSelectedDateRaw(d);
    localStorage.setItem('dfs-selected-date', d);
  };

  // Slates
  const [slates, setSlates] = useState([]);
  const [selectedSlate, setSelectedSlateRaw] = useState(() => {
    try { return JSON.parse(localStorage.getItem('dfs-selected-slate')); }
    catch { return null; }
  });
  const setSelectedSlate = (s) => {
    setSelectedSlateRaw(s);
    localStorage.setItem('dfs-selected-slate', JSON.stringify(s));
  };

  // Builds (lineup sets per user+date+slate)
  const [builds, setBuilds] = useState([createEmptyBuild('Build 1')]);
  const [currentBuildIndex, setCurrentBuildIndexRaw] = useState(0);
  const setCurrentBuildIndex = useCallback((idx) => {
    setCurrentBuildIndexRaw(idx);
    saveBuildIndex(userId, selectedDate, selectedSlate?.slate_id, idx);
  }, [userId, selectedDate, selectedSlate?.slate_id]);

  // Uploaded contests (per user+date+slate)
  const [uploadedContests, setUploadedContestsRaw] = useState([]);
  const setUploadedContests = useCallback((contests) => {
    setUploadedContestsRaw(contests);
    saveContestsToStorage(userId, selectedDate, selectedSlate?.slate_id, contests);
  }, [userId, selectedDate, selectedSlate?.slate_id]);

  // Track previous user+date+slate — start null to ensure first load triggers
  const prevComboRef = useRef(null);

  const getCurrentBuild = useCallback(() => builds[currentBuildIndex] || builds[0], [builds, currentBuildIndex]);

  const createBuild = useCallback(() => {
    const newBuild = createEmptyBuild(`Build ${builds.length + 1}`);
    setBuilds(prev => [...prev, newBuild]);
    setCurrentBuildIndex(builds.length);
  }, [builds.length]);

  const updateCurrentBuildLineups = useCallback((lineups) => {
    setBuilds(prev => prev.map((b, i) => i === currentBuildIndex ? { ...b, lineups } : b));
  }, [currentBuildIndex]);

  // Save builds whenever they change
  useEffect(() => {
    saveBuildsToStorage(userId, selectedDate, selectedSlate?.slate_id, builds);
  }, [builds, userId, selectedDate, selectedSlate?.slate_id]);

  // Load builds + contests when user+date+slate combo changes (or on mount)
  useEffect(() => {
    const newSlateId = selectedSlate?.slate_id;
    const prev = prevComboRef.current;
    if (prev && prev.userId === userId && prev.date === selectedDate && prev.slateId === newSlateId) return;

    prevComboRef.current = { userId, date: selectedDate, slateId: newSlateId };

    if (!newSlateId) return;

    const loaded = loadBuildsFromStorage(userId, selectedDate, newSlateId);
    if (loaded) {
      setBuilds(loaded);
      const savedIdx = loadBuildIndex(userId, selectedDate, newSlateId);
      setCurrentBuildIndexRaw(Math.min(savedIdx, loaded.length - 1));
    } else {
      nextBuildId = 1;
      setBuilds([createEmptyBuild('Build 1')]);
      setCurrentBuildIndexRaw(0);
    }

    const loadedContests = loadContestsFromStorage(userId, selectedDate, newSlateId);
    setUploadedContestsRaw(loadedContests || []);

    const loadedExposures = loadExposuresFromStorage(userId, selectedDate, newSlateId);
    setPlayerExposuresRaw(loadedExposures || {});

    const loadedStackExposures = loadStackExposuresFromStorage(userId, selectedDate, newSlateId);
    setStackExposuresRaw(loadedStackExposures || {});
  }, [userId, selectedDate, selectedSlate?.slate_id]);

  // Load slates when site or date changes
  useEffect(() => {
    api.getSlates(site, selectedDate).then(data => {
      if (!Array.isArray(data)) return;
      setSlates(data);
      // Auto-select featured slate if none selected or stale
      if (data.length > 0) {
        const currentId = selectedSlate?.slate_id;
        const stillValid = data.some(s => s.slate_id === currentId);
        if (!stillValid) {
          // Prefer the main slate: highest game_count classic slate
          // Backend now returns slates sorted by game_count desc, so first classic is main
          const classicSlates = data.filter(s => s.game_type === 'classic');
          const main = classicSlates.length > 0
            ? classicSlates.reduce((best, s) => (s.game_count > best.game_count ? s : best), classicSlates[0])
            : data[0];
          setSelectedSlate(main);
        }
      } else {
        setSelectedSlate(null);
      }
    }).catch((err) => {
      // On API failure, keep existing selectedSlate from localStorage if available.
      // This prevents the page from crashing on refresh when the API is temporarily
      // unreachable — the cached slate allows the UI to show a loading/stale state
      // rather than breaking entirely.
      console.warn('Failed to fetch slates:', err?.message || err);
    });
  }, [site, selectedDate]);

  // Exposure settings (shared between Projections and LineupBuilder)
  const [playerExposures, setPlayerExposuresRaw] = useState({});
  const setPlayerExposures = useCallback((exposuresOrFn) => {
    setPlayerExposuresRaw(prev => {
      const next = typeof exposuresOrFn === 'function' ? exposuresOrFn(prev) : exposuresOrFn;
      saveExposuresToStorage(userId, selectedDate, selectedSlate?.slate_id, next);
      return next;
    });
  }, [userId, selectedDate, selectedSlate?.slate_id]);
  const [stackExposures, setStackExposuresRaw] = useState({});
  const setStackExposures = useCallback((exposuresOrFn) => {
    setStackExposuresRaw(prev => {
      const next = typeof exposuresOrFn === 'function' ? exposuresOrFn(prev) : exposuresOrFn;
      saveStackExposuresToStorage(userId, selectedDate, selectedSlate?.slate_id, next);
      return next;
    });
  }, [userId, selectedDate, selectedSlate?.slate_id]);

  const value = {
    userId, setUserId, currentUser,
    site, setSite,
    selectedDate, setSelectedDate,
    slates, selectedSlate, setSelectedSlate,
    builds, currentBuildIndex, setCurrentBuildIndex,
    getCurrentBuild, createBuild, updateCurrentBuildLineups,
    uploadedContests, setUploadedContests,
    playerExposures, setPlayerExposures,
    stackExposures, setStackExposures,
  };

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp must be used within AppProvider');
  return ctx;
}
