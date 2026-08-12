from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .config import (
    API_DESCRIPTION,
    API_TITLE,
    API_VERSION,
    allowed_origins,
)
from .repository import get_repository

app = FastAPI(
    title=API_TITLE,
    version=API_VERSION,
    description=API_DESCRIPTION,
)

origins = allowed_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)

# Importante para Render: el repositorio NO se carga al importar el módulo.
# Así Uvicorn puede abrir el puerto inmediatamente.


@app.get("/", tags=["Sistema"])
def root():
    return {
        "name": API_TITLE,
        "version": API_VERSION,
        "docs": "/docs",
        "health": "/health",
        "api": "/api/v1",
    }


@app.get("/health", tags=["Sistema"])
def health():
    return {
        "status": "ok",
        "api_version": API_VERSION,
    }


@app.get("/api/v1/info", tags=["Sistema"])
def info():
    return get_repository().resumen


@app.get("/api/v1/recomendaciones", tags=["Recomendaciones"])
def listar_recomendaciones(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    prioridad: str | None = None,
    oferta: str | None = None,
    canal: str | None = None,
    score_min: float | None = Query(None, ge=0, le=1),
    departamento: str | None = None,
    search: str | None = None,
    sort_by: str = "score_nbo",
    descending: bool = True,
):
    total, items = get_repository().list_recommendations(
        limit=limit,
        offset=offset,
        prioridad=prioridad,
        oferta=oferta,
        canal=canal,
        score_min=score_min,
        departamento=departamento,
        search=search,
        sort_by=sort_by,
        descending=descending,
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
    }


@app.get("/api/v1/clientes/{cliente_id}/decision", tags=["Clientes"])
def decision_cliente(cliente_id: str):
    result = get_repository().get_client_decision(cliente_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Cliente no encontrado en la base de clientes."
        )
    return result


@app.get("/api/v1/clientes/{cliente_id}", tags=["Clientes"])
def cliente_360(cliente_id: str):
    result = get_repository().get_client360(cliente_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Cliente no encontrado en el universo elegible MT."
        )
    return result


@app.get("/api/v1/clientes/{cliente_id}/recomendacion", tags=["Clientes"])
def recomendacion_cliente(cliente_id: str):
    result = get_repository().get_recommendation(cliente_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="No existe recomendación NBO MT para este cliente."
        )
    return result


@app.get("/api/v1/clientes/{cliente_id}/top3", tags=["Clientes"])
def top3_cliente(cliente_id: str):
    result = get_repository().get_top3(cliente_id)
    if not result:
        raise HTTPException(
            status_code=404,
            detail="No existen alternativas NBO MT para este cliente."
        )
    return {
        "cliente_id": cliente_id,
        "alternativas": result,
    }


@app.get("/api/v1/ofertas/resumen", tags=["Analytics"])
def resumen_ofertas():
    return get_repository().summary_offers()


@app.get("/api/v1/canales/resumen", tags=["Analytics"])
def resumen_canales():
    return get_repository().summary_channels()


@app.get("/api/v1/prioridades/resumen", tags=["Analytics"])
def resumen_prioridades():
    return get_repository().summary_priorities()
