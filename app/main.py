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
from .rebate_rules import normalizar_rebates_decision
from .preparar_mt import build_preparation, get_preparation, list_preparations

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


def _pick(source: dict | None, fields: list[str]) -> dict:
    source = source or {}
    return {field: source.get(field) for field in fields if field in source}


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
    """Cola comercial Movistar Total. Se mantiene restringida al universo elegible MT."""
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


@app.get("/api/v1/preparar-mt", tags=["Preparar para MT"])
def listar_preparar_mt(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    potencial: str | None = Query(None, pattern="^(Alto|Medio|Bajo)$"),
    search: str | None = None,
):
    """Cola secundaria: Prepago + Internet Hogar con oportunidad de migración.

    Esta cola NO altera ni compite con el Score NBO Movistar Total. El potencial
    Alto/Medio/Bajo solo ordena candidatos dentro del módulo Preparar para MT.
    """
    repo = get_repository()
    total, items = list_preparations(
        decisions=repo._load_decisiones(),
        catalog=repo.catalogo,
        limit=limit,
        offset=offset,
        potential=potencial,
        search=search,
    )
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@app.get("/api/v1/preparar-mt/{cliente_id}", tags=["Preparar para MT"])
def detalle_preparar_mt(cliente_id: str):
    repo = get_repository()
    result = get_preparation(cliente_id, repo._load_decisiones(), repo.catalogo)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="El cliente no pertenece al universo Preparar para MT.",
        )
    return result


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
    """Vista Clientes: top comercial por defecto y búsqueda universal."""
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
        raise HTTPException(status_code=404, detail="Cliente no encontrado en la base de clientes.")
    return normalizar_rebates_decision(result)


@app.get("/api/v1/clientes/{cliente_id}/experiencia", tags=["Experiencia Cliente"])
def contexto_experiencia_cliente(cliente_id: str):
    """Contexto único y compacto para Next AI en Experiencia Cliente.

    La intención del cliente la interpreta el LLM. El backend únicamente devuelve
    datos y alternativas válidas: recomendación principal, rebate por precio,
    rebate por capacidad y situación/ruta hacia Movistar Total.

    Para comprobar Preparar para MT se evalúa únicamente la fila del cliente; este
    endpoint no construye la cola completa de Preparar MT.
    """
    repo = get_repository()
    key = str(cliente_id)

    decision = repo.get_client_decision(key)
    if decision is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado en la base de clientes.")
    decision = normalizar_rebates_decision(decision)

    decisions = repo._load_decisiones()
    row = decisions.loc[key]
    if hasattr(row, "iloc") and getattr(row, "ndim", 1) > 1:
        row = row.iloc[0]

    preparation = build_preparation(row, repo.catalogo)
    recommendation_mt = repo.get_recommendation(key)
    top3_mt = repo.get_top3(key) if recommendation_mt is not None else []

    es_mt = bool(decision.get("es_movistar_total"))
    elegible_mt = bool(decision.get("elegible_mt"))

    if es_mt:
        estado_mt = "Ya tiene MT"
    elif elegible_mt:
        estado_mt = "Apto MT"
    elif preparation is not None:
        estado_mt = "Preparar para MT"
    else:
        estado_mt = "No apto MT"

    perfil = _pick(
        decision,
        [
            "cliente_id",
            "tipo_cliente",
            "antiguedad_meses",
            "ubicacion_departamento",
            "tiene_movil",
            "tiene_hogar",
            "tiene_internet_hogar",
            "es_movistar_total",
            "plan_actual_id",
            "plan_actual_nombre",
            "consumo_datos_gb_prom",
            "monto_facturado_prom",
            "total_actual",
        ],
    )

    decision_comercial = _pick(
        decision,
        [
            "decision_tipo",
            "oferta_recomendada_id",
            "oferta_recomendada",
            "tipo_oferta_recomendada",
            "precio_recomendado",
            "gb_recomendados",
            "total_con_recomendacion",
            "variacion_mensual",
            "adecuacion",
            "margen_gb",
            "deficit_gb",
            "motivo_recomendacion",
            "recomendacion_es_plan_actual",
        ],
    )

    rebates = decision.get("rebates") or {}
    pagar_menos = rebates.get("precio")
    mas_datos = rebates.get("capacidad")

    nbo_mt = None
    if recommendation_mt is not None:
        nbo_mt = {
            "recomendacion": _pick(
                recommendation_mt,
                [
                    "oferta_recomendada_id",
                    "oferta_recomendada",
                    "score_nbo",
                    "prioridad",
                    "canal_recomendado",
                    "precio_recomendado",
                    "motivo_recomendacion",
                ],
            ),
            "top3": top3_mt,
        }

    if estado_mt == "Apto MT":
        opcion_mt = {
            "disponible": True,
            "ruta": "oferta_directa",
            "detalle": nbo_mt,
        }
    elif estado_mt == "Preparar para MT":
        opcion_mt = {
            "disponible": False,
            "ruta": "preparar_para_mt",
            "detalle": preparation,
        }
    elif estado_mt == "Ya tiene MT":
        opcion_mt = {
            "disponible": False,
            "ruta": "ya_tiene_mt",
            "detalle": "El cliente ya cuenta con Movistar Total.",
        }
    else:
        opcion_mt = {
            "disponible": False,
            "ruta": "no_apto",
            "detalle": decision.get("motivo_no_elegible_mt"),
        }

    return {
        "cliente_id": key,
        "perfil": perfil,
        "situacion_mt": {
            "estado": estado_mt,
            "elegible_mt": elegible_mt,
            "es_movistar_total": es_mt,
            "preparar_para_mt": preparation is not None,
            "motivo_no_elegible_mt": decision.get("motivo_no_elegible_mt"),
        },
        "decision_comercial": decision_comercial,
        "opciones_por_intencion": {
            "pagar_menos": pagar_menos,
            "mas_datos": mas_datos,
            "movistar_total": opcion_mt,
        },
        "nbo_mt": nbo_mt,
        "nota": (
            "Las opciones provienen del backend. La intención del cliente y la forma "
            "de explicarlas corresponden a la capa conversacional."
        ),
    }


@app.get("/api/v1/clientes/{cliente_id}/rebates", tags=["Clientes"])
def rebates_cliente(cliente_id: str):
    decision = get_repository().get_client_decision(cliente_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado en la base de clientes.")
    decision = normalizar_rebates_decision(decision)
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
        raise HTTPException(status_code=404, detail="Cliente no encontrado en la base de clientes.")
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
        raise HTTPException(status_code=404, detail="Cliente no encontrado en el universo elegible MT.")
    return result


@app.get("/api/v1/clientes/{cliente_id}/recomendacion", tags=["Clientes"])
def recomendacion_cliente(cliente_id: str):
    result = get_repository().get_recommendation(cliente_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No existe recomendación NBO MT para este cliente.")
    return result


@app.get("/api/v1/clientes/{cliente_id}/top3", tags=["Clientes"])
def top3_cliente(cliente_id: str):
    result = get_repository().get_top3(cliente_id)
    if not result:
        raise HTTPException(status_code=404, detail="No existen alternativas NBO MT para este cliente.")
    return {"cliente_id": cliente_id, "alternativas": result}


@app.get("/api/v1/ofertas/resumen", tags=["Analytics"])
def resumen_ofertas():
    return get_repository().summary_offers()


@app.get("/api/v1/canales/resumen", tags=["Analytics"])
def resumen_canales():
    return get_repository().summary_channels()


@app.get("/api/v1/prioridades/resumen", tags=["Analytics"])
def resumen_prioridades():
    return get_repository().summary_priorities()
