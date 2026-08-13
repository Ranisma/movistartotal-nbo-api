from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
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
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Importante para Render: el repositorio NO se carga al importar el módulo.
# Así Uvicorn puede abrir el puerto inmediatamente.


class GestionComercialRequest(BaseModel):
    evento: str
    canal: str | None = None
    motivo_rechazo: str | None = None
    tipo_rebate: str | None = None
    oferta_rebate_id: str | None = None
    comentario: str | None = None


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
    solo_incremento: bool = False,
    rango_incremento: str = "desde_10",
    sort_by: str = "score_nbo",
    descending: bool = True,
):
    """Cola comercial Movistar Total.

    Este endpoint se mantiene restringido al universo elegible MT.
    `solo_incremento=true` activa el filtro económico. `rango_incremento`
    admite: cualquiera, menos_10, desde_10, desde_20 o desde_40.
    Por defecto usa desde_10.
    """
    total, items = get_repository().list_recommendations(
        limit=limit,
        offset=offset,
        prioridad=prioridad,
        oferta=oferta,
        canal=canal,
        score_min=score_min,
        departamento=departamento,
        search=search,
        solo_incremento=solo_incremento,
        rango_incremento=rango_incremento,
        sort_by=sort_by,
        descending=descending,
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "solo_incremento": solo_incremento,
        "rango_incremento": rango_incremento if solo_incremento else None,
        "items": items,
    }


@app.get("/api/v1/clientes-universo", tags=["Clientes"])
def listar_clientes_universo(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    search: str | None = None,
    elegible_mt: bool | None = None,
    tipo_cliente: str | None = None,
    solo_incremento: bool = False,
    rango_incremento: str = "desde_10",
    sort_by: str = "score_nbo_mt",
    descending: bool = True,
):
    """Vista Clientes: top comercial por defecto y búsqueda universal.

    - Sin `search`: devuelve elegibles MT ordenados por Score NBO descendente.
    - Sin `search` + `solo_incremento=true`: mismo ranking, refinado por
      `rango_incremento` (cualquiera, menos_10, desde_10, desde_20, desde_40).
    - Con `search`: busca en los 100k clientes, aunque no sean aptos MT o ya
      tengan MT. En búsqueda, `solo_incremento` no bloquea la coincidencia.
    """
    total, items = get_repository().list_client_decisions(
        limit=limit,
        offset=offset,
        search=search,
        elegible_mt=elegible_mt,
        tipo_cliente=tipo_cliente,
        solo_incremento=solo_incremento,
        rango_incremento=rango_incremento,
        sort_by=sort_by,
        descending=descending,
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "solo_incremento": solo_incremento,
        "rango_incremento": rango_incremento if solo_incremento else None,
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


@app.get("/api/v1/clientes/{cliente_id}/rebates", tags=["Clientes"])
def rebates_cliente(cliente_id: str):
    decision = get_repository().get_client_decision(cliente_id)
    if decision is None:
        raise HTTPException(
            status_code=404,
            detail="Cliente no encontrado en la base de clientes."
        )
    return {
        "cliente_id": cliente_id,
        "oferta_principal_id": decision.get("oferta_recomendada_id"),
        "oferta_principal": decision.get("oferta_recomendada"),
        "rebates": decision.get("rebates", {}),
    }


@app.get("/api/v1/clientes/{cliente_id}/gestiones", tags=["Trazabilidad"])
def historial_gestiones_cliente(cliente_id: str):
    decision = get_repository().get_client_decision(cliente_id)
    if decision is None:
        raise HTTPException(
            status_code=404,
            detail="Cliente no encontrado en la base de clientes."
        )
    return {
        "cliente_id": cliente_id,
        "estado_actual": get_repository().get_estado_gestion(cliente_id),
        "historial": get_repository().get_historial_gestion(cliente_id),
    }


@app.post("/api/v1/clientes/{cliente_id}/gestiones", tags=["Trazabilidad"])
def registrar_gestion_cliente(cliente_id: str, payload: GestionComercialRequest):
    try:
        registro = get_repository().registrar_gestion(
            cliente_id=cliente_id,
            evento=payload.evento,
            canal=payload.canal,
            motivo_rechazo=payload.motivo_rechazo,
            tipo_rebate=payload.tipo_rebate,
            oferta_rebate_id=payload.oferta_rebate_id,
            comentario=payload.comentario,
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if message.startswith("Cliente no encontrado") else 400
        raise HTTPException(status_code=status_code, detail=message) from exc

    return {
        "ok": True,
        "registro": registro,
        "estado_actual": get_repository().get_estado_gestion(cliente_id),
    }


@app.get("/api/v1/gestiones/funnel", tags=["Trazabilidad"])
def funnel_gestiones():
    return get_repository().get_funnel_gestiones()


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


# FOCO Assistant se integra como router separado para no mezclar su lógica
# conversacional con el motor NBO ni afectar el arranque ligero de Render.
from .chatbot_api import router as chatbot_router

app.include_router(chatbot_router)
