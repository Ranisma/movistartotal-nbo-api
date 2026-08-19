from __future__ import annotations

from typing import Optional

import pandas as pd


MOBILE_OFFER_TYPE = "plan_movil"
MIN_PREPARATION_GB = 10.0


def _bool_value(value) -> bool:
    if pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "si", "sí", "yes"}
    return bool(value)


def _number(row: pd.Series, field: str, default: float = 0.0) -> float:
    value = pd.to_numeric(pd.Series([row.get(field)]), errors="coerce").iloc[0]
    return default if pd.isna(value) else float(value)


def _is_prepaid(row: pd.Series) -> bool:
    return str(row.get("tipo_cliente") or "").strip().lower() == "prepago"


def _has_home_internet(row: pd.Series) -> bool:
    return _bool_value(row.get("tiene_internet_hogar"))


def _is_mt(row: pd.Series) -> bool:
    return _bool_value(row.get("es_movistar_total"))


def _mobile_catalog(catalog: pd.DataFrame) -> pd.DataFrame:
    if catalog.empty or "tipo_oferta" not in catalog.columns:
        return pd.DataFrame()
    offers = catalog[
        catalog["tipo_oferta"].astype(str).str.lower().eq(MOBILE_OFFER_TYPE)
    ].copy()
    if offers.empty:
        return offers
    offers["precio_mensual"] = pd.to_numeric(offers["precio_mensual"], errors="coerce")
    offers["gb_incluidos"] = pd.to_numeric(offers["gb_incluidos"], errors="coerce")
    return offers.dropna(subset=["precio_mensual", "gb_incluidos"]).sort_values(
        ["gb_incluidos", "precio_mensual"], ascending=[True, True]
    )


def _recommend_offer(consumption_gb: float, catalog: pd.DataFrame) -> Optional[dict]:
    offers = _mobile_catalog(catalog)
    if offers.empty:
        return None
    enough = offers[offers["gb_incluidos"] >= consumption_gb]
    selected = enough.iloc[0] if not enough.empty else offers.iloc[-1]
    return selected.to_dict()


def _potential(row: pd.Series, consumption_gb: float) -> tuple[str, float, list[str]]:
    """Heurística explicable; no pretende ser una probabilidad ML de migración."""
    points = 0.0
    reasons: list[str] = []

    # La necesidad móvil es la señal principal. Los clientes por debajo de
    # MIN_PREPARATION_GB no llegan a esta función porque no existe evidencia
    # suficiente de necesidad para impulsar una migración Postpago.
    if consumption_gb >= 25:
        points += 45
        reasons.append(f"Consumo móvil alto: {consumption_gb:.1f} GB/mes")
    else:
        points += 32
        reasons.append(f"Consumo móvil relevante: {consumption_gb:.1f} GB/mes")

    acceptance = _number(row, "hist_tasa_aceptacion_previa", 0.0)
    if acceptance > 1:
        acceptance /= 100.0
    if acceptance >= 0.5:
        points += 20
        reasons.append("Historial comercial favorable")
    elif acceptance >= 0.25:
        points += 10

    tenure = _number(row, "antiguedad_meses", 0.0)
    if tenure >= 12:
        points += 10
        reasons.append("Relación sostenida con Movistar")

    complaints = _number(row, "n_reclamos", _number(row, "num_reclamos_6m", 0.0))
    if complaints >= 3:
        points -= 12
        reasons.append("Reclamos recientes reducen la prioridad comercial")
    elif complaints >= 1:
        points -= 5

    arrears = _number(row, "dias_mora_prom", 0.0)
    if arrears >= 15:
        points -= 15
        reasons.append("Mora observada reduce la prioridad comercial")
    elif arrears > 0:
        points -= 5

    # Primera versión: rechazo comercial agregado. No se presenta como rechazo
    # específico de Postpago hasta disponer de la derivación por familia de oferta.
    rejections = _number(row, "hist_rechazos_previos", 0.0)
    previous_offers = _number(row, "hist_ofertas_previas", 0.0)
    if previous_offers > 0:
        rejection_rate = rejections / previous_offers
        if rejection_rate >= 0.75:
            points -= 18
            reasons.append("Alta tasa histórica de rechazo")
        elif rejection_rate >= 0.5:
            points -= 10
            reasons.append("Historial de rechazo modera la oportunidad")

    points = max(0.0, min(100.0, points))
    if points >= 55:
        return "Alto", points, reasons
    if points >= 32:
        return "Medio", points, reasons
    return "Bajo", points, reasons


def build_preparation(row: pd.Series, catalog: pd.DataFrame) -> Optional[dict]:
    if not _is_prepaid(row) or not _has_home_internet(row) or _is_mt(row):
        return None

    consumption = _number(row, "consumo_datos_gb_prom", 0.0)
    if consumption < MIN_PREPARATION_GB:
        return None

    offer = _recommend_offer(consumption, catalog)
    if offer is None:
        return None

    potential, internal_order, reasons = _potential(row, consumption)
    reasons.insert(0, "Ya cuenta con Internet Hogar Movistar")

    gb = float(offer.get("gb_incluidos") or 0)
    capacity_text = "datos ilimitados" if gb >= 9999 else f"{gb:g} GB"
    reasons.append(f"El plan sugerido ofrece {capacity_text} y cubre el consumo observado")

    return {
        "cliente_id": str(row.get("cliente_id")),
        "estado": "Preparar para MT",
        "accion_recomendada": "Migrar a Postpago",
        "potencial": potential,
        # Solo sirve para ordenar ESTA cola; nunca se expone como Score MT.
        "_orden_preparacion": round(internal_order, 2),
        "oferta_recomendada_id": str(offer.get("oferta_id")),
        "oferta_recomendada": offer.get("nombre_oferta"),
        "precio_recomendado": float(offer.get("precio_mensual")),
        "gb_recomendados": gb,
        "consumo_datos_gb_prom": round(consumption, 3),
        "canal_sugerido": row.get("canal_sugerido") or row.get("canal_mas_usado"),
        "razones": reasons,
        "ruta_mt": {
            "actual": "Prepago + Internet Hogar",
            "accion": "Migración a Postpago",
            "resultado": "Habilitado para evaluación posterior de Movistar Total",
        },
        "nota_metodologica": (
            "El potencial es una priorización heurística explicable, no una probabilidad "
            "ML de migración. El Score NBO MT permanece independiente."
        ),
    }


def list_preparations(
    decisions: pd.DataFrame,
    catalog: pd.DataFrame,
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
    cliente_id: str, decisions: pd.DataFrame, catalog: pd.DataFrame
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
