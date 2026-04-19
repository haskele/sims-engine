const BASE_URL = import.meta.env.PROD
  ? 'https://baseball-dfs-sims.fly.dev'
  : '/api';

const PROJ_PREFIX = import.meta.env.VITE_USE_STAGING === 'true'
  ? '/staging/projections'
  : '/projections';

const DEFAULT_TIMEOUT = 30000;
const LONG_TIMEOUT = 300000;

class AbortError extends Error {
  constructor(message = 'Request was cancelled') {
    super(message);
    this.name = 'AbortError';
  }
}

async function fetchApi(endpoint, options = {}) {
  const { signal, timeout = DEFAULT_TIMEOUT, ...fetchOpts } = options;

  let controller;
  let timeoutId;

  if (signal) {
    controller = null;
  } else {
    controller = new AbortController();
    timeoutId = setTimeout(() => controller.abort(), timeout);
  }

  const fetchSignal = signal || controller?.signal;

  try {
    const response = await fetch(`${BASE_URL}${endpoint}`, {
      headers: { 'Content-Type': 'application/json', ...fetchOpts.headers },
      ...fetchOpts,
      signal: fetchSignal,
    });
    if (!response.ok) {
      const text = await response.text().catch(() => '');
      throw new Error(text || `API Error: ${response.status}`);
    }
    return response.json();
  } catch (err) {
    if (err.name === 'AbortError') {
      throw new AbortError();
    }
    throw err;
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
  }
}

export const api = {
  // Slates & Projections
  getSlates: (site = 'dk', date) => {
    const params = new URLSearchParams({ site });
    if (date) params.set('target_date', date);
    return fetchApi(`${PROJ_PREFIX}/slates?${params}`);
  },
  getSlateHistory: (days = 30, site = 'dk') => {
    const params = new URLSearchParams({ days: String(days), site });
    return fetchApi(`/projections/slates/history?${params}`);
  },
  getFeaturedProjections: (site = 'dk', date) => {
    const params = new URLSearchParams({ site });
    if (date) params.set('target_date', date);
    return fetchApi(`${PROJ_PREFIX}/slates/featured/projections?${params}`);
  },
  getSlateProjections: (slateId, site = 'dk', date) => {
    const params = new URLSearchParams({ site });
    if (date) params.set('target_date', date);
    return fetchApi(`${PROJ_PREFIX}/slates/${slateId}/projections?${params}`);
  },
  updateProjection: (projId, data) => fetchApi(`/projections/${projId}`, { method: 'PATCH', body: JSON.stringify(data) }),

  // Players
  getPlayers: (slateId, site) => fetchApi(`/players?slate_id=${slateId}&site=${site}`),

  // Contests
  getContests: (site) => fetchApi(`/contests?site=${site}`),
  importContest: (data) => fetchApi('/contests/import', { method: 'POST', body: JSON.stringify(data) }),

  // Lineups
  buildLineups: (config, signal) => fetchApi('/lineups/optimize', { method: 'POST', body: JSON.stringify(config), signal, timeout: LONG_TIMEOUT }),
  buildLineupsCSV: (config, signal) => {
    const endpoint = import.meta.env.VITE_USE_STAGING === 'true'
      ? '/lineups/optimize-staging'
      : '/lineups/optimize-csv';
    return fetchApi(endpoint, { method: 'POST', body: JSON.stringify(config), signal, timeout: LONG_TIMEOUT });
  },
  exportLineups: (lineupIds, site) => fetchApi(`/lineups/export/dk`, { method: 'GET' }),

  // Simulator
  runInlineSimulation: (config, signal) => fetchApi('/simulations/run-inline', { method: 'POST', body: JSON.stringify(config), signal, timeout: LONG_TIMEOUT }),
  runContestSim: (config, signal) => fetchApi('/simulations/contest-sim', { method: 'POST', body: JSON.stringify(config), signal, timeout: LONG_TIMEOUT }),
  runPortfolioSim: (config, signal) => fetchApi('/simulations/portfolio-sim', { method: 'POST', body: JSON.stringify(config), signal, timeout: LONG_TIMEOUT }),
  assignLineups: (contestId, assignments) => fetchApi('/simulations/assign-lineups', { method: 'POST', body: JSON.stringify({ contest_id: contestId, assignments }) }),
  updateEntryLineup: (contestId, entryId, lineupIndex) => fetchApi('/simulations/update-entry', { method: 'POST', body: JSON.stringify({ contest_id: contestId, entry_id: entryId, lineup_index: lineupIndex }) }),
  getSimResults: (contestId) => fetchApi(`/simulations/results/${contestId}`),
  exportSimCSV: (contestId) => {
    const url = `${BASE_URL}/simulations/export-csv?contest_id=${contestId}`;
    return fetch(url).then(r => {
      if (!r.ok) throw new Error(`Export failed: ${r.status}`);
      return r.text();
    });
  },
  exportAllCSV: () => {
    return fetch(`${BASE_URL}/simulations/export-all-csv`, { method: 'POST' }).then(r => {
      if (!r.ok) throw new Error(`Export failed: ${r.status}`);
      return r.text();
    });
  },

  // Games
  getGames: (date) => fetchApi(`/games?date=${date}`),

  // Data Pipeline
  runDailyPipeline: (date, site = 'dk') => {
    const params = new URLSearchParams({ site });
    if (date) params.set('target_date', date);
    return fetchApi(`/pipeline/run-daily?${params}`, { method: 'POST' });
  },

  // Lineup Status & Game Lineups
  getLineupStatus: (forceRefresh = false, date = null) => {
    const params = new URLSearchParams();
    if (forceRefresh) params.set('force_refresh', 'true');
    if (date) params.set('target_date', date);
    const qs = params.toString();
    return fetchApi(`/projections/lineups/status${qs ? '?' + qs : ''}`);
  },
  getGameLineups: (forceRefresh = false, site = 'dk', date = null, slateId = null) => {
    const params = new URLSearchParams();
    if (forceRefresh) params.set('force_refresh', 'true');
    if (site) params.set('site', site);
    if (date) params.set('target_date', date);
    if (slateId) params.set('slate_id', slateId);
    const qs = params.toString();
    return fetchApi(`${PROJ_PREFIX}/lineups/games${qs ? '?' + qs : ''}`);
  },
  getLiveScores: () => fetchApi(`${PROJ_PREFIX}/lineups/games/live`),

  // DK Entries
  uploadDkEntries: async (file) => {
    const formData = new FormData();
    formData.append('file', file);
    const response = await fetch(`${BASE_URL}/dk-entries/upload`, { method: 'POST', body: formData });
    if (!response.ok) throw new Error(`API Error: ${response.status}`);
    return response.json();
  },
  getDkContests: () => fetchApi('/dk-entries/contests'),
  getDkEntries: (contestId) => {
    const params = contestId ? `?contest_id=${contestId}` : '';
    return fetchApi(`/dk-entries/entries${params}`);
  },
  getDkEntriesStatus: () => fetchApi('/dk-entries/status'),
  getContestLive: (contestId) => fetchApi(`/dk-entries/contests/${contestId}/live`),

  // Late Swap
  checkLateSwap: (lineup, excludedPlayers = [], site = 'dk', date = null) =>
    fetchApi('/lineups/late-swap', {
      method: 'POST',
      body: JSON.stringify({
        lineup,
        excluded_players: excludedPlayers,
        site,
        target_date: date,
      }),
    }),

  // Quick-Run Simulation (from My Contests)
  quickRunSim: (contestId, userLineups, simCount = 5000, site = 'dk', date = null, signal = null) =>
    fetchApi('/simulations/quick-run', {
      method: 'POST',
      body: JSON.stringify({
        contest_id: contestId,
        user_lineups: userLineups,
        sim_count: simCount,
        site,
        target_date: date,
      }),
      signal,
      timeout: LONG_TIMEOUT,
    }),

  // Health
  health: () => fetchApi('/health'),
};

export { AbortError };
