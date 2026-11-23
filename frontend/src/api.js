// Talks to the backend. All paths are relative, so the same code works in dev and in production.
async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options });
  } catch {
    throw new Error('Cannot reach the backend. Is it running on port 8000?');
  }
  let data = null;
  try {
    data = await res.json();
  } catch {
    /* no body */
  }
  if (!res.ok) throw new Error((data && data.detail) || `Request failed (${res.status}).`);
  return data;
}

export const api = {
  models: () => request('/api/models').then((d) => d.models),
  createDebate: (body) => request('/api/debates', { method: 'POST', body: JSON.stringify(body) }),
  listDebates: () => request('/api/debates').then((d) => d.debates),
  getDebate: (id) => request(`/api/debates/${id}`),
  deleteDebate: (id) => request(`/api/debates/${id}`, { method: 'DELETE' }),
  startBenchmark: (model) => request('/api/benchmarks', { method: 'POST', body: JSON.stringify({ model }) }),
  latestBenchmark: () => request('/api/benchmarks/latest'),
  cancelBenchmark: () => request('/api/benchmarks/cancel', { method: 'POST' }),
  getReport: (id) => request(`/api/debates/${id}/report`, { method: 'POST' }),
  downloadReportUrl: (id, format) => `/api/debates/${id}/report/download?format=${format}`,
};

export function openDebateSocket(id) {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return new WebSocket(`${proto}://${window.location.host}/ws/debates/${id}`);
}
