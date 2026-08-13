from __future__ import annotations

from typing import Any


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalizar_rebates_decision(decision: dict | None) -> dict | None:
    """Corrige rebates que no representan una mejora real frente a la principal.

    Regla comercial:
    - "Mantener situación actual" solo es un rebate de precio válido cuando el
      total actual es realmente menor que el total de la recomendación principal.
    - Si la principal ya cuesta menos (o lo mismo) que la situación actual y no
      existe otra oferta de la familia más barata, no se inventa una segunda opción:
      se informa que la principal ya es la alternativa de menor precio disponible.

    La función no cambia la oferta principal ni el rebate de capacidad.
    """
    if not isinstance(decision, dict):
        return decision

    result = dict(decision)
    rebates = dict(result.get("rebates") or {})
    precio = rebates.get("precio")

    if not isinstance(precio, dict):
        return result

    if precio.get("accion") != "mantener_situacion_actual":
        return result

    total_actual = _to_float(result.get("total_actual"))
    total_principal = _to_float(result.get("total_con_recomendacion"))

    if total_actual is None or total_principal is None:
        return result

    # Mantener la situación actual sí es coherente cuando realmente cuesta menos.
    if total_actual < total_principal - 0.009:
        return result

    ahorro = round(max(0.0, total_actual - total_principal), 2)
    principal_nombre = result.get("oferta_recomendada") or "la recomendación principal"

    if ahorro > 0:
        mensaje = (
            f"{principal_nombre} ya es la alternativa de menor precio disponible "
            f"y además reduce el pago actual en S/{ahorro:.2f} al mes. No existe "
            "un rebate de precio adicional dentro de esta familia."
        )
        speech = (
            f"La opción que te recomendé ya es la alternativa de menor precio "
            f"disponible y te permite ahorrar aproximadamente S/{ahorro:.2f} al mes "
            "frente a lo que pagas hoy."
        )
    else:
        mensaje = (
            f"{principal_nombre} ya es la alternativa de menor precio disponible. "
            "No existe un rebate de precio adicional que reduzca el pago mensual."
        )
        speech = (
            "La opción que te recomendé ya es la alternativa de menor precio "
            "disponible dentro de esta familia; no hay una opción adicional que "
            "reduzca más el pago mensual."
        )

    rebates["precio"] = {
        "tipo": "precio",
        "titulo": "Prioriza pagar menos",
        "disponible": False,
        "accion": "principal_ya_es_mas_economica",
        "oferta_id": result.get("oferta_recomendada_id"),
        "oferta": principal_nombre,
        "precio": _to_float(result.get("precio_recomendado")),
        "gb": _to_float(result.get("gb_recomendados")),
        "total_resultante": round(total_principal, 2),
        "variacion_mensual": _to_float(result.get("variacion_mensual")),
        "adecuacion": result.get("adecuacion"),
        "deficit_gb": _to_float(result.get("deficit_gb")),
        "margen_gb": _to_float(result.get("margen_gb")),
        "mensaje": mensaje,
        "speech_sugerido": speech,
    }

    result["rebates"] = rebates
    return result
