const BASE_URL = import.meta.env.PROD
  ? 'https://baseball-dfs-sims.fly.dev'
  : '/api';

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
    return fetchApi(`/projections/slates?${params}`);
  },
  getSlateHistory: (days = 30, site = 'dk') => {
    const params = new URLSearchParams({ days: String(days), site });
    return fetchApi(`/projections/slates/history?${params}`);
  },
  getFeaturedProjections: (site = 'dk', date) => {
    const params = new URLSearchParams({ site });
    if (date) params.set('target_date', date);
    return fetchApi(`/projections/slates/featured/projections?${params}`);
  },
  getSlateProjections: (slateId, site = 'dk', date) => {
    const params = new URLSearchParams({ site });
    if (date) params.set('target_date', date);
    return fetchApi(`/projections/slates/${slateId}/projections?${params}`);
  },
  updateProjection: (projId, data) => fetchApi(`/projections/${projId}`, { method: 'PATCH', body: JSON.stringify(data) }),

  // Players
  getPlayers: (slateId, site) => fetchApi(`/players?slate_id=${slateId}&site=${site}`),

  // Contests
  getContests: (site) => fetchApi(`/contests?site=${site}`),
  importContest: (data) => fetchApi('/contests/import', { method: 'POST', body: JSON.stringify(data) }),

  // Lineups
  buildLineups: (config, signal) => fetchApi('/lineups/optimize', { method: 'POST', body: JSON.stringify(config), signal, timeout: LONG_TIMEOUT }),
  buildLineupsCSV: (config, signal) => fetchApi('/lineups/optimize-csv', { method: 'POST', body: JSON.stringify(config), signal, timeout: LONG_TIMEOUT }),
  exportLineups: (lineupIds, site) => fetchApi(`/lineups/export/dk`, { method: 'GET' }),

  // Simulator
  runSimulation: (config, signal) => fetchApi('/simulations/', { method: 'POST', body: JSON.stringify(config), signal, timeout: LONG_TIMEOUT }),
  runInlineSimulation: (config, signal) => fetchApi('/simulations/run-inline', { method: 'POST', body: JSON.stringify(config), signal, timeout: LONG_TIMEOUT }),
  getSimStatus: (simId) => fetchApi(`/simulations/${simId}`),

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
  getGameLineups: (forceRefresh = false, site = 'dk', date = null) => {
    const params = new URLSearchParams();
    if (forceRefresh) params.set('force_refresh', 'true');
    if (site) params.set('site', site);
    if (date) params.set('target_date', date);
    const qs = params.toString();
    return fetchApi(`/projections/lineups/games${qs ? '?' + qs : ''}`);
  },
  getLiveScores: () => fetchApi('/projections/lineups/games/live'),

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
