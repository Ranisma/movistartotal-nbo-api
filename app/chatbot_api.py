from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .repository import get_repository


router = APIRouter(prefix="/api/v1", tags=["FOCO Assistant"])


class ChatbotRequest(BaseModel):
    pregunta: str = Field(..., min_length=1, max_length=800)


def _contexto_nbo_seguro(decision: dict) -> str:
    """Construye el contexto del chatbot únicamente con datos del motor NBO.

    El frontend no puede inyectar precios, ofertas ni atributos del cliente:
    solo envía la pregunta. El backend obtiene la decisión real y arma el
    contexto que recibe FOCO Assistant.
    """
    campos = {
        "cliente_id": decision.get("cliente_id"),
        "tipo_cliente": decision.get("tipo_cliente"),
        "antiguedad_meses": decision.get("antiguedad_meses"),
        "estado_mt": decision.get("estado_mt"),
        "motivo_no_elegible_mt": decision.get("motivo_no_elegible_mt"),
        "consumo_datos_gb_prom": decision.get("consumo_datos_gb_prom"),
        "plan_actual_id": decision.get("plan_actual_id"),
        "plan_actual_nombre": decision.get("plan_actual_nombre"),
        "total_actual": decision.get("total_actual"),
        "decision_tipo": decision.get("decision_tipo"),
        "oferta_recomendada_id": decision.get("oferta_recomendada_id"),
        "oferta_recomendada": decision.get("oferta_recomendada"),
        "precio_recomendado": decision.get("precio_recomendado"),
        "total_con_recomendacion": decision.get("total_con_recomendacion"),
        "variacion_mensual": decision.get("variacion_mensual"),
        "adecuacion": decision.get("adecuacion"),
        "deficit_gb": decision.get("deficit_gb"),
        "margen_gb": decision.get("margen_gb"),
        "motivo_recomendacion": decision.get("motivo_recomendacion"),
        "explicacion_operativa": decision.get("explicacion_operativa"),
        "canal_sugerido": decision.get("canal_sugerido"),
        "prioridad_cliente": decision.get("prioridad_cliente"),
        "score_nbo": decision.get("score_nbo"),
        "rebates": decision.get("rebates"),
    }

    # Evita enviar claves completamente vacías y mantiene el contexto compacto.
    campos = {k: v for k, v in campos.items() if v is not None}
    return json.dumps(campos, ensure_ascii=False, indent=2)


@router.post("/clientes/{cliente_id}/chatbot")
def consultar_foco_assistant(cliente_id: str, payload: ChatbotRequest):
    decision = get_repository().get_client_decision(cliente_id)
    if decision is None:
        raise HTTPException(
            status_code=404,
            detail="Cliente no encontrado en la base de clientes.",
        )

    contexto = _contexto_nbo_seguro(decision)

    # Importación diferida: la API NBO puede arrancar aunque OpenAI esté
    # temporalmente sin configurar. Solo este endpoint depende del chatbot.
    try:
        from .chatbot import consultar_chatbot
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="FOCO Assistant no está disponible en este momento.",
        ) from exc

    respuesta = consultar_chatbot(
        pregunta=payload.pregunta.strip(),
        contexto_cliente=contexto,
    )

    return {
        "cliente_id": cliente_id,
        "respuesta": respuesta,
        "fuente_contexto": "motor_nbo",
    }
