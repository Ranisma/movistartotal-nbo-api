from __future__ import annotations

from functools import lru_cache
from typing import Optional

import pandas as pd

from .config import DATA_DIR

MOBILE_OFFER_TYPE = "plan_movil"
MOBILE_OFFER_IDS = {"OF001", "OF002", "OF003", "OF004"}
MIN_PREPARATION_GB = 10.0
POTENTIAL_ORDER = {"Alto": 0, "Medio": 1, "Bajo": 2}


def _bool_value(value) -> bool:
    if pd.isna(value): return False
    if isinstance(value, str): return value.strip().lower() in {"true", "1", "si", "sí", "yes"}
    return bool(value)


def _number(value, default: float = 0.0) -> float:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return default if pd.isna(parsed) else float(parsed)


def _optional_number(value) -> Optional[float]:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return None if pd.isna(parsed) else float(parsed)


def _text(value) -> str:
    if value is None or pd.isna(value): return ""
    return str(value).strip()


def _downgrade(level: str) -> str:
    return "Medio" if level == "Alto" else "Bajo"


def _is_candidate_base(row: pd.Series) -> bool:
    return _text(row.get("tipo_cliente")).lower() == "prepago" and _bool_value(row.get("tiene_internet_hogar")) and not _bool_value(row.get("es_movistar_total"))


def _main_mobile_recommendation(row: pd.Series) -> Optional[dict]:
    offer_id = _text(row.get("oferta_recomendada_id"))
    offer_type = _text(row.get("tipo_oferta_recomendada")).lower()
    if offer_type != MOBILE_OFFER_TYPE or offer_id not in MOBILE_OFFER_IDS: return None
    return {"oferta_id": offer_id, "nombre_oferta": row.get("oferta_recomendada"), "precio_mensual": _number(row.get("precio_recomendado")), "gb_incluidos": _number(row.get("gb_recomendados")), "adecuacion": row.get("adecuacion"), "variacion_mensual": _number(row.get("variacion_mensual")), "motivo_recomendacion": row.get("motivo_recomendacion")}


@lru_cache(maxsize=1)
def _load_preparation_context() -> dict[str, dict]:
    path = DATA_DIR / "preparar_mt_contexto.csv"
    if not path.exists(): return {}
    context = pd.read_csv(path)
    if context.empty or "cliente_id" not in context.columns: return {}
    context["cliente_id"] = context["cliente_id"].astype(str)
    return context.set_index("cliente_id").to_dict(orient="index")


def _rejection_effect(level: str, context: dict, target_offer_id: str, reasons: list[str]) -> str:
    context_target = _text(context.get("oferta_recomendada_id"))
    same_days = _optional_number(context.get("dias_desde_rechazo_misma_oferta"))
    same_reason = _text(context.get("motivo_rechazo_misma_oferta")).lower()
    if context_target == target_offer_id and same_days is not None and same_days <= 90:
        if same_days <= 30 and same_reason in {"no_necesita", "ya_tiene_similar"}:
            reasons.append("Rechazó recientemente esta misma oferta por falta de necesidad o por contar con una alternativa similar")
            return "Bajo"
        if same_reason in {"no_necesita", "ya_tiene_similar", "no_confia", "precio", "otro"}:
            reasons.append("Existe un rechazo reciente de la misma oferta móvil")
            return _downgrade(level)
        if same_reason == "mal_momento": reasons.append("El rechazo de esta oferta fue por momento de contacto, no por falta de encaje")
        return level
    family_days = _optional_number(context.get("dias_desde_ultimo_rechazo_movil"))
    family_reason = _text(context.get("ultimo_motivo_rechazo_movil")).lower()
    if family_days is None or family_days > 90: return level
    if family_days <= 30 and family_reason in {"no_necesita", "ya_tiene_similar"}:
        reasons.append("Existe un rechazo móvil muy reciente por falta de necesidad o por contar con una alternativa similar")
        return "Bajo"
    if family_reason in {"no_necesita", "ya_tiene_similar", "no_confia", "precio", "otro"}:
        reasons.append("Existe un rechazo reciente dentro de la familia de planes móviles")
        return _downgrade(level)
    if family_reason == "mal_momento": reasons.append("El último rechazo móvil fue por momento de contacto, por lo que no se penaliza el encaje de la oferta")
    return level


def _classify_potential(row: pd.Series, recommendation: dict, context: Optional[dict]) -> tuple[str, list[str]]:
    consumption = _number(row.get("consumo_datos_gb_prom"))
    reasons: list[str] = []
    if consumption >= 25:
        level = "Alto"; reasons.append(f"Consumo móvil alto: {consumption:.1f} GB/mes")
    else:
        level = "Medio"; reasons.append(f"Consumo móvil relevante: {consumption:.1f} GB/mes")
    variation = _number(recommendation.get("variacion_mensual"))
    if variation > 10:
        level = _downgrade(level); reasons.append(f"La migración estimada incrementa el gasto mensual en S/{variation:.2f}")
    elif variation <= 0: reasons.append("La recomendación no incrementa el gasto mensual estimado")
    if context:
        level = _rejection_effect(level, context, _text(recommendation.get("oferta_id")), reasons)
        complaints = _optional_number(context.get("n_reclamos"))
        if complaints is not None and complaints >= 3:
            level = _downgrade(level); reasons.append("La cantidad de reclamos reduce la prioridad comercial")
        arrears = _optional_number(context.get("dias_mora_prom"))
        if arrears is not None and arrears >= 15:
            level = _downgrade(level); reasons.append("La mora observada reduce la prioridad comercial")
    return level, reasons


def build_preparation(row: pd.Series, catalog: Optional[pd.DataFrame] = None) -> Optional[dict]:
    if not _is_candidate_base(row): return None
    consumption = _number(row.get("consumo_datos_gb_prom"))
    if consumption < MIN_PREPARATION_GB: return None
    recommendation = _main_mobile_recommendation(row)
    if recommendation is None: return None
    adequacy = _text(recommendation.get("adecuacion")).lower()
    if adequacy and adequacy != "adecuado": return None
    context = _load_preparation_context().get(str(row.get("cliente_id")))
    potential, reasons = _classify_potential(row, recommendation, context)
    reasons.insert(0, "Ya cuenta con Internet Hogar Movistar")
    return {"cliente_id": str(row.get("cliente_id")), "estado": "Preparar para MT", "accion_recomendada": "Migrar a Postpago", "potencial": potential, "oferta_recomendada_id": recommendation["oferta_id"], "oferta_recomendada": recommendation["nombre_oferta"], "precio_recomendado": recommendation["precio_mensual"], "gb_recomendados": recommendation["gb_incluidos"], "consumo_datos_gb_prom": round(consumption, 3), "adecuacion": recommendation["adecuacion"], "variacion_mensual": recommendation["variacion_mensual"], "canal_sugerido": row.get("canal_sugerido") or row.get("canal_mas_usado"), "historial_movil_disponible": context is not None, "razones": reasons, "ruta_mt": {"actual": "Prepago + Internet Hogar", "accion": "Migración a Postpago", "resultado": "Habilitado para evaluación posterior de Movistar Total"}, "nota_metodologica": "El potencial es una clasificación explicable; no es Score MT ni una probabilidad ML."}


def list_preparations(decisions: pd.DataFrame, catalog: Optional[pd.DataFrame] = None, limit: int = 50, offset: int = 0, potential: Optional[str] = None, search: Optional[str] = None) -> tuple[int, list[dict]]:
    rows=[]; q=str(search or "").strip().lower()
    for _, row in decisions.reset_index(drop=True).iterrows():
        if q and q not in str(row.get("cliente_id") or "").lower(): continue
        item=build_preparation(row, catalog)
        if item is None or (potential and item["potencial"].lower()!=potential.strip().lower()): continue
        rows.append(item)
    rows.sort(key=lambda x:(POTENTIAL_ORDER[x["potencial"]], -float(x["consumo_datos_gb_prom"]), float(x.get("variacion_mensual") or 0), x["cliente_id"]))
    return len(rows), rows[offset:offset+limit]


def get_preparation(cliente_id: str, decisions: pd.DataFrame, catalog: Optional[pd.DataFrame] = None) -> Optional[dict]:
    key=str(cliente_id)
    if key not in decisions.index: return None
    row=decisions.loc[key]
    if isinstance(row,pd.DataFrame): row=row.iloc[0]
    return build_preparation(row,catalog)
