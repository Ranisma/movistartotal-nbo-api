from __future__ import annotations

import json
from functools import lru_cache
from typing import Optional

import numpy as np
import pandas as pd

from .config import DATA_DIR


def _clean_value(v):
    if pd.isna(v):
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


def _record_clean(record: dict) -> dict:
    return {k: _clean_value(v) for k, v in record.items()}


class NBORepository:
    def __init__(self):
        # Mantiene intacto el universo comercial actual de elegibles MT.
        self.recomendaciones = pd.read_csv(DATA_DIR / "fase_3_recomendaciones_nbo.csv")
        self.top3 = pd.read_csv(DATA_DIR / "fase_3_top3_por_cliente.csv")
        self.resumen_ofertas = pd.read_csv(DATA_DIR / "fase_3_resumen_ofertas.csv")
        self.resumen_canales = pd.read_csv(DATA_DIR / "fase_3_resumen_canales.csv")
        self.prioridades = pd.read_csv(DATA_DIR / "fase_3_prioridades.csv")

        with open(DATA_DIR / "fase_3_resumen.json", "r", encoding="utf-8") as f:
            self.resumen = json.load(f)

        self.recomendaciones["cliente_id"] = self.recomendaciones["cliente_id"].astype(str)
        self.top3["cliente_id"] = self.top3["cliente_id"].astype(str)

        # La capa universal (100k clientes) se carga SOLO cuando se consulta.
        self._decisiones = None

    def _load_decisiones(self):
        if self._decisiones is None:
            df = pd.read_csv(DATA_DIR / "decisiones_cliente.csv.gz")
            df["cliente_id"] = df["cliente_id"].astype(str)
            self._decisiones = df.set_index("cliente_id", drop=False)
        return self._decisiones

    def get_client_decision(self, cliente_id: str) -> Optional[dict]:
        df = self._load_decisiones()
        key = str(cliente_id)
        if key not in df.index:
            return None
        row = df.loc[key]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        return _record_clean(row.to_dict())

    def get_recommendation(self, cliente_id: str) -> Optional[dict]:
        rows = self.recomendaciones[self.recomendaciones["cliente_id"] == str(cliente_id)]
        if rows.empty:
            return None
        return _record_clean(rows.iloc[0].to_dict())

    def get_top3(self, cliente_id: str) -> list[dict]:
        rows = (
            self.top3[self.top3["cliente_id"] == str(cliente_id)]
            .sort_values("ranking_oferta")
        )
        return [_record_clean(x) for x in rows.to_dict(orient="records")]

    def get_client360(self, cliente_id: str) -> Optional[dict]:
        rec = self.get_recommendation(cliente_id)
        if rec is None:
            return None

        profile_fields = [
            "cliente_id",
            "tipo_cliente",
            "antiguedad_meses",
            "plan_actual_id",
            "monto_facturado_prom",
            "edad_rango",
            "ubicacion_departamento",
            "es_usuario_app",
            "consumo_datos_gb_prom",
            "consumo_voz_min_prom",
            "dias_mora_prom",
            "n_reclamos",
            "canal_mas_usado",
            "hist_ofertas_previas",
            "hist_aceptaciones_previas",
            "hist_rechazos_previos",
            "hist_tasa_aceptacion_previa",
        ]

        profile = {k: rec.get(k) for k in profile_fields if k in rec}
        return {
            "cliente_id": str(cliente_id),
            "perfil": profile,
            "recomendacion": rec,
            "alternativas": self.get_top3(cliente_id),
        }

    def list_recommendations(
        self,
        limit: int = 50,
        offset: int = 0,
        prioridad: Optional[str] = None,
        oferta: Optional[str] = None,
        canal: Optional[str] = None,
        score_min: Optional[float] = None,
        departamento: Optional[str] = None,
        search: Optional[str] = None,
        sort_by: str = "score_nbo",
        descending: bool = True,
    ) -> tuple[int, list[dict]]:
        df = self.recomendaciones

        if prioridad:
            df = df[df["prioridad"].astype(str).str.lower() == prioridad.lower()]
        if oferta:
            df = df[df["oferta_recomendada"].astype(str).str.lower().str.contains(oferta.lower(), na=False)]
        if canal:
            df = df[df["canal_recomendado"].astype(str).str.lower() == canal.lower()]
        if score_min is not None:
            df = df[df["score_nbo"] >= score_min]
        if departamento and "ubicacion_departamento" in df.columns:
            df = df[
                df["ubicacion_departamento"].astype(str).str.lower().str.contains(
                    departamento.lower(), na=False
                )
            ]
        if search:
            df = df[
                df["cliente_id"].astype(str).str.lower().str.contains(
                    search.lower(), na=False
                )
            ]

        allowed_sort = {
            "score_nbo",
            "cliente_id",
            "prioridad",
            "oferta_recomendada",
            "canal_recomendado",
            "monto_facturado_prom",
            "antiguedad_meses",
        }
        if sort_by not in allowed_sort or sort_by not in df.columns:
            sort_by = "score_nbo"

        df = df.sort_values(sort_by, ascending=not descending)
        total = len(df)
        page = df.iloc[offset: offset + limit]
        return total, [_record_clean(x) for x in page.to_dict(orient="records")]

    def summary_offers(self) -> list[dict]:
        return [_record_clean(x) for x in self.resumen_ofertas.to_dict(orient="records")]

    def summary_channels(self) -> list[dict]:
        return [_record_clean(x) for x in self.resumen_canales.to_dict(orient="records")]

    def summary_priorities(self) -> list[dict]:
        return [_record_clean(x) for x in self.prioridades.to_dict(orient="records")]


@lru_cache(maxsize=1)
def get_repository() -> NBORepository:
    return NBORepository()
