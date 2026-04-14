const BASE_URL = '/api';

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

  // Health
  health: () => fetchApi('/health'),
};
