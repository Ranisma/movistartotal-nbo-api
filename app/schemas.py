from typing import Optional, Any
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    api_version: str
    recomendaciones_cargadas: int


class RecommendationResponse(BaseModel):
    cliente_id: str
    oferta_recomendada_id: Optional[str] = None
    oferta_recomendada: Optional[str] = None
    canal_recomendado: Optional[str] = None
    score_nbo: Optional[float] = None
    score_propension_base: Optional[float] = None
    prioridad: Optional[str] = None
    precio_recomendado: Optional[float] = None
    ahorro_pct_recomendado: Optional[float] = None
    gb_recomendados: Optional[float] = None
    explicacion_operativa: Optional[str] = None


class Client360Response(BaseModel):
    cliente_id: str
    perfil: dict[str, Any]
    recomendacion: RecommendationResponse
    alternativas: list[dict[str, Any]]


class PaginatedResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[dict[str, Any]]


class ApiInfoResponse(BaseModel):
    fase: int
    estado: str
    fecha_scoring: str
    clientes_elegibles_mt: int
    ofertas_mt_evaluadas: int
    canales_evaluados: list[str]
    combinaciones_evaluadas: int
    recomendaciones_finales: int
    modelo_propension_base: str
    ranker_operativo: str
    ranker_test_auc_elegible_mt: float
    ranker_test_pr_auc_elegible_mt: float
