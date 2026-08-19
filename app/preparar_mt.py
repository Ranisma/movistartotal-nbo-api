from __future__ import annotations

from functools import lru_cache
from typing import Optional

import pandas as pd

from .config import DATA_DIR


MOBILE_OFFER_TYPE = "plan_movil"
MOBILE_OFFER_IDS = {"OF001", "OF002", "OF003", "OF004"}
MIN_PREPARATION_GB = 10.0


def _bool_value(value) -> bool:
    if pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "si", "sí", "yes"}
    return bool(value)


def _number(value, default: float = 0.0) -> float:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return default if pd.isna(parsed) else float(parsed)


def _text(value) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _is_candidate_base(row: pd.Series) -> bool:
    return (
        _text(row.get("tipo_cliente")).lower() == "prepago"
        and _bool_value(row.get("tiene_internet_hogar"))
        and not _bool_value(row.get("es_movistar_total"))
    )


def _main_mobile_recommendation(row: pd.Series) -> Optional[dict]:
    """Reutiliza la decisión móvil ya calculada en `decisiones_cliente.csv`.

    Preparar para MT no vuelve a decidir qué plan móvil corresponde. Esa decisión
    pertenece al motor principal y aquí solo se reutiliza para priorizar la acción
    Prepago -> Postpago.
    """
    offer_id = _text(row.get("oferta_recomendada_id"))
    offer_type = _text(row.get("tipo_oferta_recomendada")).lower()
    if offer_type != MOBILE_OFFER_TYPE or offer_id not in MOBILE_OFFER_IDS:
        return None

    return {
        "oferta_id": offer_id,
        "nombre_oferta": row.get("oferta_recomendada"),
        "precio_mensual": _number(row.get("precio_recomendado"), 0.0),
        "gb_incluidos": _number(row.get("gb_recomendados"), 0.0),
        "adecuacion": row.get("adecuacion"),
        "variacion_mensual": _number(row.get("variacion_mensual"), 0.0),
        "motivo_recomendacion": row.get("motivo_recomendacion"),
    }


@lru_cache(maxsize=1)
def _load_mobile_history() -> dict[str, dict]:
    """Deriva historial específico de planes móviles si el CSV está desplegado.

    El archivo no es obligatorio para mantener viva la API. Si no está presente,
    Preparar para MT funciona con señales de la capa de decisiones y declara que el
    historial específico todavía no está disponible.
    """
    path = DATA_DIR / "dataset_nbo_entrenamiento.csv"
    if not path.exists():
        return {}

    history = pd.read_csv(path)
    if history.empty or "cliente_id" not in history.columns:
        return {}

    type_col = "tipo_oferta" if "tipo_oferta" in history.columns else "oferta_tipo"
    if type_col not in history.columns:
        return {}

    mobile = history[
        history[type_col].astype(str).str.lower().eq(MOBILE_OFFER_TYPE)
    ].copy()
    if mobile.empty:
        return {}

    mobile["cliente_id"] = mobile["cliente_id"].astype(str)
    if "fecha" in mobile.columns:
        mobile["_fecha"] = pd.to_datetime(mobile["fecha"], errors="coerce")
        reference_date = mobile["_fecha"].max()
    else:
        mobile["_fecha"] = pd.NaT
        reference_date = pd.NaT

    result: dict[str, dict] = {}
    for cliente_id, group in mobile.groupby("cliente_id", sort=False):
        outcome = group.get("resultado", pd.Series("", index=group.index)).astype(str).str.lower()
        accepted = int(outcome.eq("aceptada").sum())
        rejected = int(outcome.eq("rechazada").sum())
        total = int(len(group))

        rejected_rows = group[outcome.eq("rechazada")].sort_values("_fecha")
        last_rejection = rejected_rows.iloc[-1] if not rejected_rows.empty else None
        last_reason = (
            _text(last_rejection.get("motivo_rechazo")).lower()
            if last_rejection is not None
            else None
        )
        days_since_rejection = None
        if (
            last_rejection is not None
            and pd.notna(reference_date)
            and pd.notna(last_rejection.get("_fecha"))
        ):
            days_since_rejection = int((reference_date - last_rejection["_fecha"]).days)

        latest = group.sort_values("_fecha").iloc[-1]
        result[str(cliente_id)] = {
            "ofertas_movil": total,
            "aceptaciones_movil": accepted,
            "rechazos_movil": rejected,
            "tasa_aceptacion_movil": accepted / total if total else None,
            "ultimo_motivo_rechazo_movil": last_reason,
            "dias_desde_ultimo_rechazo_movil": days_since_rejection,
            "n_reclamos": _number(latest.get("n_reclamos"), 0.0),
            "dias_mora_prom": _number(latest.get("dias_mora_prom"), 0.0),
        }
    return result


def _potential(
    row: pd.Series,
    recommendation: dict,
    mobile_history: Optional[dict],
) -> tuple[str, float, list[str]]:
    """Prioridad explicable dentro de Preparar para MT; no es Score MT ni ML."""
    consumption = _number(row.get("consumo_datos_gb_prom"), 0.0)
    points = 0.0
    reasons: list[str] = []

    # 1) Necesidad móvil observable: señal principal.
    if consumption >= 50:
        points += 50
        reasons.append(f"Consumo móvil muy alto: {consumption:.1f} GB/mes")
    elif consumption >= 25:
        points += 45
        reasons.append(f"Consumo móvil alto: {consumption:.1f} GB/mes")
    else:
        points += 35
        reasons.append(f"Consumo móvil relevante: {consumption:.1f} GB/mes")

    # 2) La recomendación existente debe cubrir el consumo.
    adequacy = _text(recommendation.get("adecuacion")).lower()
    if adequacy == "adecuado":
        points += 10
        reasons.append("La recomendación móvil actual cubre el consumo observado")
    elif adequacy:
        points -= 15
        reasons.append("La recomendación móvil actual requiere revisión de capacidad")

    # 3) Viabilidad económica tomada de la misma decisión de main.
    variation = _number(recommendation.get("variacion_mensual"), 0.0)
    if variation <= 0:
        points += 12
        reasons.append("La recomendación no incrementa el gasto mensual estimado")
    elif variation <= 10:
        points += 5
        reasons.append("El incremento mensual estimado es acotado")
    else:
        points -= 5
        reasons.append(f"La recomendación implica un incremento de S/{variation:.2f}/mes")

    # 4) Relación con Movistar. No crea la oportunidad: solo ordena una necesidad ya observada.
    tenure = _number(row.get("antiguedad_meses"), 0.0)
    if tenure >= 24:
        points += 8
        reasons.append("Relación sostenida con Movistar")
    elif tenure >= 12:
        points += 5

    # 5) Historial específico de planes móviles, solo si el archivo está disponible.
    if mobile_history:
        rate = mobile_history.get("tasa_aceptacion_movil")
        if rate is not None and rate >= 0.5:
            points += 10
            reasons.append("Buena receptividad histórica a ofertas móviles")
        elif rate is not None and rate >= 0.25:
            points += 5

        days = mobile_history.get("dias_desde_ultimo_rechazo_movil")
        if days is not None:
            if days <= 30:
                points -= 15
                reasons.append("Rechazo reciente de una oferta móvil")
            elif days <= 90:
                points -= 8
                reasons.append("Rechazo móvil relativamente reciente")
            else:
                points -= 3

        reason = _text(mobile_history.get("ultimo_motivo_rechazo_movil")).lower()
        reason_penalty = {
            "no_necesita": 12,
            "ya_tiene_similar": 10,
            "no_confia": 7,
            "precio": 5,
            "mal_momento": 2,
            "otro": 3,
        }.get(reason, 0)
        if reason_penalty:
            points -= reason_penalty
            reason_labels = {
                "no_necesita": "El último rechazo móvil fue por falta de necesidad",
                "ya_tiene_similar": "El último rechazo móvil indicó que ya tenía una alternativa similar",
                "no_confia": "El último rechazo móvil estuvo asociado a confianza",
                "precio": "El último rechazo móvil estuvo asociado al precio",
                "mal_momento": "El último rechazo móvil fue por un mal momento de contacto",
                "otro": "Existe un rechazo móvil previo a considerar",
            }
            reasons.append(reason_labels[reason])

        complaints = _number(mobile_history.get("n_reclamos"), 0.0)
        if complaints >= 3:
            points -= 8
            reasons.append("Reclamos recientes reducen la prioridad comercial")
        elif complaints >= 1:
            points -= 3

        arrears = _number(mobile_history.get("dias_mora_prom"), 0.0)
        if arrears >= 15:
            points -= 10
            reasons.append("Mora observada reduce la prioridad comercial")
        elif arrears > 0:
            points -= 4

    points = max(0.0, min(100.0, points))
    if points >= 70:
        return "Alto", points, reasons
    if points >= 50:
        return "Medio", points, reasons
    return "Bajo", points, reasons


def build_preparation(row: pd.Series, catalog: Optional[pd.DataFrame] = None) -> Optional[dict]:
    if not _is_candidate_base(row):
        return None

    consumption = _number(row.get("consumo_datos_gb_prom"), 0.0)
    if consumption < MIN_PREPARATION_GB:
        return None

    recommendation = _main_mobile_recommendation(row)
    if recommendation is None:
        return None

    history = _load_mobile_history().get(str(row.get("cliente_id")))
    potential, internal_order, reasons = _potential(row, recommendation, history)
    reasons.insert(0, "Ya cuenta con Internet Hogar Movistar")

    gb = _number(recommendation.get("gb_incluidos"), 0.0)
    capacity_text = "datos ilimitados" if gb >= 9999 else f"{gb:g} GB"

    return {
        "cliente_id": str(row.get("cliente_id")),
        "estado": "Preparar para MT",
        "accion_recomendada": "Migrar a Postpago",
        "potencial": potential,
        # Solo ordena esta cola; nunca se muestra ni se compara con Score NBO MT.
        "_orden_preparacion": round(internal_order, 2),
        "oferta_recomendada_id": recommendation.get("oferta_id"),
        "oferta_recomendada": recommendation.get("nombre_oferta"),
        "precio_recomendado": recommendation.get("precio_mensual"),
        "gb_recomendados": gb,
        "consumo_datos_gb_prom": round(consumption, 3),
        "adecuacion": recommendation.get("adecuacion"),
        "variacion_mensual": recommendation.get("variacion_mensual"),
        "motivo_recomendacion": recommendation.get("motivo_recomendacion"),
        "canal_sugerido": row.get("canal_sugerido") or row.get("canal_mas_usado"),
        "historial_movil_disponible": history is not None,
        "historial_movil": history,
        "razones": reasons,
        "ruta_mt": {
            "actual": "Prepago + Internet Hogar",
            "accion": "Migración a Postpago",
            "resultado": "Habilitado para evaluación posterior de Movistar Total",
        },
        "mensaje_capacidad": f"El plan recomendado por el motor actual ofrece {capacity_text}.",
        "nota_metodologica": (
            "Preparar para MT prioriza una acción previa a Movistar Total. "
            "No recalcula la oferta móvil, no es una probabilidad ML y no modifica el Score NBO MT."
        ),
    }


def list_preparations(
    decisions: pd.DataFrame,
    catalog: Optional[pd.DataFrame] = None,
    limit: int = 50,
    offset: int = 0,
    potential: Optional[str] = None,
    search: Optional[str] = None,
) -> tuple[int, list[dict]]:
    rows: list[dict] = []
    df = decisions.reset_index(drop=True)
    q = str(search or "").strip().lower()

    for _, row in df.iterrows():
        if q and q not in str(row.get("cliente_id") or "").lower():
            continue
        item = build_preparation(row, catalog)
        if item is None:
            continue
        if potential and item["potencial"].lower() != potential.strip().lower():
            continue
        rows.append(item)

    rows.sort(key=lambda x: (-x["_orden_preparacion"], x["cliente_id"]))
    total = len(rows)
    page = rows[offset: offset + limit]
    for item in page:
        item.pop("_orden_preparacion", None)
    return total, page


def get_preparation(
    cliente_id: str,
    decisions: pd.DataFrame,
    catalog: Optional[pd.DataFrame] = None,
) -> Optional[dict]:
    key = str(cliente_id)
    if key not in decisions.index:
        return None
    row = decisions.loc[key]
    if isinstance(row, pd.DataFrame):
        row = row.iloc[0]
    item = build_preparation(row, catalog)
    if item is not None:
        item.pop("_orden_preparacion", None)
    return item
