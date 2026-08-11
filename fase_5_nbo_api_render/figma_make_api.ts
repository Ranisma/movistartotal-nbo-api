/**
 * Conector listo para Figma Make / React.
 *
 * Cuando Render termine el deploy, reemplaza:
 * https://TU-SERVICIO.onrender.com
 * por la URL pública real.
 */

export const API_BASE_URL = "https://TU-SERVICIO.onrender.com";

async function apiGet(path: string) {
  const response = await fetch(`${API_BASE_URL}${path}`);

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`NBO API ${response.status}: ${body}`);
  }

  return response.json();
}

export async function getDashboardRecommendations(limit = 10) {
  return apiGet(
    `/api/v1/recomendaciones?limit=${limit}&sort_by=score_nbo&descending=true`
  );
}

export async function searchClients(search: string, limit = 50) {
  const q = encodeURIComponent(search);
  return apiGet(`/api/v1/recomendaciones?search=${q}&limit=${limit}`);
}

export async function getClient360(clienteId: string) {
  return apiGet(`/api/v1/clientes/${encodeURIComponent(clienteId)}`);
}

export async function getClientTop3(clienteId: string) {
  return apiGet(`/api/v1/clientes/${encodeURIComponent(clienteId)}/top3`);
}

export async function getOfferAnalytics() {
  return apiGet("/api/v1/ofertas/resumen");
}

export async function getChannelAnalytics() {
  return apiGet("/api/v1/canales/resumen");
}

export async function getPriorityAnalytics() {
  return apiGet("/api/v1/prioridades/resumen");
}
