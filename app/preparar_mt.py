from __future__ import annotations

from functools import lru_cache
from threading import Lock
from typing import Optional

import pandas as pd

from .config import DATA_DIR
from .repository import NBORepository

MOBILE_OFFER_TYPE = "plan_movil"
MOBILE_OFFER_IDS = {"OF001", "OF002", "OF003", "OF004"}
MIN_PREPARATION_GB = 10.0
POTENTIAL_ORDER = {"Alto": 0, "Medio": 1, "Bajo": 2}

# Render ejecuta endpoints sync de FastAPI en un thread pool. En un arranque frío,
# varias consultas simultáneas podían entrar a NBORepository._load_decisiones()
# antes de que la primera terminara y descomprimir varias veces el CSV universal
# de 100k clientes. Ese DataFrame ocupa ~175 MB y el pico podía terminar en OOM/137.
# Compartimos una única carga por proceso y serializamos únicamente el primer load.
_DECISIONS_LOAD_LOCK = Lock()
_SHARED_DECISIONS: Optional[pd.DataFrame] = None
_ORIGINAL_LOAD_DECISIONES = NBORepository._load_decisiones


def _load_decisiones_once(self: NBORepository) -> pd.DataFrame:
    global _SHARED_DECISIONS

    if self._decisiones is not None:
        return self._decisiones

    if _SHARED_DECISIONS is not None:
        self._decisiones = _SHARED_DECISIONS
        return self._decisiones

    with _DECISIONS_LOAD_LOCK:
        if _SHARED_DECISIONS is None:
            _SHARED_DECISIONS = _ORIGINAL_LOAD_DECISIONES(self)
        self._decisiones = _SHARED_DECISIONS

    return self._decisiones


# El parche se instala al importar este módulo, antes de aceptar tráfico HTTP.
# No precarga el dataset: conserva el comportamiento lazy del backend.
if NBORepository._load_decisiones is not _load_decisiones_once:
    NBORepository._load_decisiones = _load_decisiones_once


# La cola Preparar MT es determinista mientras vive el proceso. Se construye una sola
# vez y luego filtros/paginación trabajan sobre 11,005 referencias, no sobre 100k filas.
_PREPARATIONS_LOCK = Lock()
_PREPARATIONS_CACHE: Optional[tuple[dict, ...]] = None
_PREPARATIONS_BY_ID: Optional[dict[str, dict]] = None


def _bool_value(value) -> bool:
    if pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "si", "sí", "yes"}
    return bool(value)


def _number(value, default: float = 0.0) -> float:
    if value is None or pd.isna(value):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return default if pd.isna(parsed) else parsed


def _optional_number(value) -> Optional[float]:
    if value is None or pd.isna(value):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(parsed) else parsed


def _text(value) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _downgrade(level: str) -> str:
    return "Medio" if level == "Alto" else "Bajo"


def _is_candidate_base(row: pd.Series) -> bool:
    return (
        _text(row.get("tipo_cliente")).lower() == "prepago"
        and _bool_value(row.get("tiene_internet_hogar"))
        and not _bool_value(row.get("es_movistar_total"))
    )


def _main_mobile_recommendation(row: pd.Series) -> Optional[dict]:
    offer_id = _text(row.get("oferta_recomendada_id"))
    offer_type = _text(row.get("tipo_oferta_recomendada")).lower()
    if offer_type != MOBILE_OFFER_TYPE or offer_id not in MOBILE_OFFER_IDS:
        return None
    return {
        "oferta_id": offer_id,
        "nombre_oferta": row.get("oferta_recomendada"),
        "precio_mensual": _number(row.get("precio_recomendado")),
        "gb_incluidos": _number(row.get("gb_recomendados")),
        "adecuacion": row.get("adecuacion"),
        "variacion_mensual": _number(row.get("variacion_mensual")),
        "motivo_recomendacion": row.get("motivo_recomendacion"),
    }


@lru_cache(maxsize=1)
def _load_preparation_context() -> dict[str, dict]:
    path = DATA_DIR / "preparar_mt_contexto.csv.gz"
    if not path.exists():
        return {}
    context = pd.read_csv(path, compression="gzip")
    if context.empty or "cliente_id" not in context.columns:
        return {}
    context["cliente_id"] = context["cliente_id"].astype(str)
    context = context.drop_duplicates(subset=["cliente_id"], keep="last")
    return context.set_index("cliente_id").to_dict(orient="index")


def _rejection_effect(
    level: str,
    context: dict,
    target_offer_id: str,
    reasons: list[str],
) -> str:
    context_target = _text(context.get("oferta_recomendada_id"))
    same_days = _optional_number(context.get("dias_desde_rechazo_misma_oferta"))
    same_reason = _text(context.get("motivo_rechazo_misma_oferta")).lower()

    if context_target == target_offer_id and same_days is not None and same_days <= 90:
        if same_days <= 30 and same_reason in {"no_necesita", "ya_tiene_similar"}:
            reasons.append(
                "Rechazó recientemente esta misma oferta por falta de necesidad o por contar con una alternativa similar"
            )
            return "Bajo"
        if same_reason in {"no_necesita", "ya_tiene_similar", "no_confia", "precio", "otro"}:
            reasons.append("Existe un rechazo reciente de la misma oferta móvil")
            return _downgrade(level)
        if same_reason == "mal_momento":
            reasons.append(
                "El rechazo de esta oferta fue por momento de contacto, no por falta de encaje"
            )
        return level

    family_days = _optional_number(context.get("dias_desde_ultimo_rechazo_movil"))
    family_reason = _text(context.get("ultimo_motivo_rechazo_movil")).lower()
    if family_days is None or family_days > 90:
        return level
    if family_days <= 30 and family_reason in {"no_necesita", "ya_tiene_similar"}:
        reasons.append(
            "Existe un rechazo móvil muy reciente por falta de necesidad o por contar con una alternativa similar"
        )
        return "Bajo"
    if family_reason in {"no_necesita", "ya_tiene_similar", "no_confia", "precio", "otro"}:
        reasons.append("Existe un rechazo reciente dentro de la familia de planes móviles")
        return _downgrade(level)
    if family_reason == "mal_momento":
        reasons.append(
            "El último rechazo móvil fue por momento de contacto, por lo que no se penaliza el encaje de la oferta"
        )
    return level


def _classify_potential(
    row: pd.Series,
    recommendation: dict,
    context: Optional[dict],
) -> tuple[str, list[str]]:
    consumption = _number(row.get("consumo_datos_gb_prom"))
    reasons: list[str] = []

    if consumption >= 25:
        level = "Alto"
        reasons.append(f"Consumo móvil alto: {consumption:.1f} GB/mes")
    else:
        level = "Medio"
        reasons.append(f"Consumo móvil relevante: {consumption:.1f} GB/mes")

    variation = _number(recommendation.get("variacion_mensual"))
    if variation > 10:
        level = _downgrade(level)
        reasons.append(f"La migración estimada incrementa el gasto mensual en S/{variation:.2f}")
    elif variation <= 0:
        reasons.append("La recomendación no incrementa el gasto mensual estimado")

    if context:
        level = _rejection_effect(
            level,
            context,
            _text(recommendation.get("oferta_id")),
            reasons,
        )
        complaints = _optional_number(context.get("n_reclamos"))
        if complaints is not None and complaints >= 3:
            level = _downgrade(level)
            reasons.append("La cantidad de reclamos reduce la prioridad comercial")
        arrears = _optional_number(context.get("dias_mora_prom"))
        if arrears is not None and arrears >= 15:
            level = _downgrade(level)
            reasons.append("La mora observada reduce la prioridad comercial")

    return level, reasons


def build_preparation(
    row: pd.Series,
    catalog: Optional[pd.DataFrame] = None,
) -> Optional[dict]:
    if not _is_candidate_base(row):
        return None

    consumption = _number(row.get("consumo_datos_gb_prom"))
    if consumption < MIN_PREPARATION_GB:
        return None

    recommendation = _main_mobile_recommendation(row)
    if recommendation is None:
        return None

    adequacy = _text(recommendation.get("adecuacion")).lower()
    if adequacy and adequacy != "adecuado":
        return None

    context = _load_preparation_context().get(str(row.get("cliente_id")))
    potential, reasons = _classify_potential(row, recommendation, context)
    reasons.insert(0, "Ya cuenta con Internet Hogar Movistar")

    return {
        "cliente_id": str(row.get("cliente_id")),
        "estado": "Preparar para MT",
        "accion_recomendada": "Migrar a Postpago",
        "potencial": potential,
        "oferta_recomendada_id": recommendation["oferta_id"],
        "oferta_recomendada": recommendation["nombre_oferta"],
        "precio_recomendado": recommendation["precio_mensual"],
        "gb_recomendados": recommendation["gb_incluidos"],
        "consumo_datos_gb_prom": round(consumption, 3),
        "adecuacion": recommendation["adecuacion"],
        "variacion_mensual": recommendation["variacion_mensual"],
        "canal_sugerido": row.get("canal_sugerido") or row.get("canal_mas_usado"),
        "historial_movil_disponible": context is not None,
        "razones": reasons,
        "ruta_mt": {
            "actual": "Prepago + Internet Hogar",
            "accion": "Migración a Postpago",
            "resultado": "Habilitado para evaluación posterior de Movistar Total",
        },
        "nota_metodologica": (
            "El potencial es una clasificación explicable; no es Score MT ni una probabilidad ML."
        ),
    }


def _candidate_frame(decisions: pd.DataFrame) -> pd.DataFrame:
    """Reduce el universo con operaciones vectorizadas antes de construir dicts."""
    df = decisions.reset_index(drop=True)

    tipo = df["tipo_cliente"].astype(str).str.lower()
    hogar = df["tiene_internet_hogar"].fillna(False).astype(bool)
    mt = df["es_movistar_total"].fillna(False).astype(bool)
    consumo = pd.to_numeric(df["consumo_datos_gb_prom"], errors="coerce").fillna(0)
    offer_type = df["tipo_oferta_recomendada"].astype(str).str.lower()
    offer_id = df["oferta_recomendada_id"].astype(str)

    mask = (
        tipo.eq("prepago")
        & hogar
        & ~mt
        & consumo.ge(MIN_PREPARATION_GB)
        & offer_type.eq(MOBILE_OFFER_TYPE)
        & offer_id.isin(MOBILE_OFFER_IDS)
    )

    if "adecuacion" in df.columns:
        adequacy = df["adecuacion"].fillna("").astype(str).str.lower()
        mask &= adequacy.eq("") | adequacy.eq("adecuado")

    return df.loc[mask]


def _all_preparations(
    decisions: pd.DataFrame,
    catalog: Optional[pd.DataFrame] = None,
) -> tuple[dict, ...]:
    global _PREPARATIONS_CACHE, _PREPARATIONS_BY_ID

    if _PREPARATIONS_CACHE is not None:
        return _PREPARATIONS_CACHE

    with _PREPARATIONS_LOCK:
        if _PREPARATIONS_CACHE is None:
            rows: list[dict] = []
            for _, row in _candidate_frame(decisions).iterrows():
                item = build_preparation(row, catalog)
                if item is not None:
                    rows.append(item)

            rows.sort(
                key=lambda x: (
                    POTENTIAL_ORDER[x["potencial"]],
                    -float(x["consumo_datos_gb_prom"]),
                    float(x.get("variacion_mensual") or 0),
                    x["cliente_id"],
                )
            )
            _PREPARATIONS_CACHE = tuple(rows)
            _PREPARATIONS_BY_ID = {item["cliente_id"]: item for item in rows}

    return _PREPARATIONS_CACHE


def list_preparations(
    decisions: pd.DataFrame,
    catalog: Optional[pd.DataFrame] = None,
    limit: int = 50,
    offset: int = 0,
    potential: Optional[str] = None,
    search: Optional[str] = None,
) -> tuple[int, list[dict]]:
    rows = _all_preparations(decisions, catalog)
    q = str(search or "").strip().lower()
    p = str(potential or "").strip().lower()

    if q or p:
        filtered = [
            item
            for item in rows
            if (not q or q in item["cliente_id"].lower())
            and (not p or item["potencial"].lower() == p)
        ]
    else:
        filtered = rows

    total = len(filtered)
    return total, list(filtered[offset:offset + limit])


def get_preparation(
    cliente_id: str,
    decisions: pd.DataFrame,
    catalog: Optional[pd.DataFrame] = None,
) -> Optional[dict]:
    global _PREPARATIONS_BY_ID
    _all_preparations(decisions, catalog)
    return (_PREPARATIONS_BY_ID or {}).get(str(cliente_id))
