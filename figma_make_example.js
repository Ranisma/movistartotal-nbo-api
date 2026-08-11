const API_BASE_URL = "http://127.0.0.1:8000";

export async function fetchRecommendations({
  limit = 50,
  offset = 0,
  prioridad,
  oferta,
  canal,
  scoreMin,
  search
} = {}) {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });

  if (prioridad) params.set("prioridad", prioridad);
  if (oferta) params.set("oferta", oferta);
  if (canal) params.set("canal", canal);
  if (scoreMin != null) params.set("score_min", String(scoreMin));
  if (search) params.set("search", search);

  const response = await fetch(
    `${API_BASE_URL}/api/v1/recomendaciones?${params.toString()}`
  );

  if (!response.ok) {
    throw new Error(`API error ${response.status}`);
  }

  return response.json();
}

export async function fetchClient360(clienteId) {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/clientes/${encodeURIComponent(clienteId)}`
  );

  if (!response.ok) {
    throw new Error("Cliente no encontrado");
  }

  return response.json();
}
