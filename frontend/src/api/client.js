const BASE_URL = import.meta.env.PROD
  ? 'https://baseball-dfs-sims.fly.dev'
  : '/api';

async function fetchApi(endpoint, options = {}) {
  const response = await fetch(`${BASE_URL}${endpoint}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!response.ok) throw new Error(`API Error: ${response.status}`);
  return response.json();
}

export const api = {
  // Slates & Projections
  getSlates: (site = 'dk', date) => {
    const params = new URLSearchParams({ site });
    if (date) params.set('target_date', date);
    return fetchApi(`/projections/slates?${params}`);
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
  buildLineups: (config) => fetchApi('/lineups/optimize', { method: 'POST', body: JSON.stringify(config) }),
  exportLineups: (lineupIds, site) => fetchApi(`/lineups/export/dk`, { method: 'GET' }),

  // Simulator
  runSimulation: (config) => fetchApi('/simulations/', { method: 'POST', body: JSON.stringify(config) }),
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
  getLineupStatus: (forceRefresh = false) => {
    const params = forceRefresh ? '?force_refresh=true' : '';
    return fetchApi(`/projections/lineups/status${params}`);
  },
  getGameLineups: (forceRefresh = false) => {
    const params = forceRefresh ? '?force_refresh=true' : '';
    return fetchApi(`/projections/lineups/games${params}`);
  },

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

  // Health
  health: () => fetchApi('/health'),
};
