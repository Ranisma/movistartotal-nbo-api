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
        # Se mantiene intacto el universo comercial actual de elegibles MT.
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

            # Prioridad comercial MT real para quienes sí están en la cola NBO.
            priority_map = (
                self.recomendaciones[["cliente_id", "prioridad"]]
                .drop_duplicates("cliente_id")
                .set_index("cliente_id")["prioridad"]
                if "prioridad" in self.recomendaciones.columns
                else pd.Series(dtype="object")
            )

            score_map = (
                self.recomendaciones[["cliente_id", "score_nbo"]]
                .drop_duplicates("cliente_id")
                .set_index("cliente_id")["score_nbo"]
                if "score_nbo" in self.recomendaciones.columns
                else pd.Series(dtype="float64")
            )

            df["prioridad_mt"] = df["cliente_id"].map(priority_map)
            df["score_nbo_mt"] = df["cliente_id"].map(score_map)

            elegible = df.get("elegible_mt", False)
            if not isinstance(elegible, pd.Series):
                elegible = pd.Series(False, index=df.index)
            elegible = elegible.fillna(False).astype(bool)

            ya_tiene = df.get("es_movistar_total", False)
            if not isinstance(ya_tiene, pd.Series):
                ya_tiene = pd.Series(False, index=df.index)
            ya_tiene = ya_tiene.fillna(False).astype(bool)

            df["prioridad_cliente"] = np.where(
                ya_tiene,
                "Ya tiene MT",
                np.where(
                    elegible,
                    df["prioridad_mt"].fillna("Elegible MT"),
                    "No apto MT",
                ),
            )

            df["estado_mt"] = np.where(
                ya_tiene,
                "Ya tiene MT",
                np.where(elegible, "Apto MT", "No apto MT"),
            )

            variacion = pd.to_numeric(df.get("variacion_mensual"), errors="coerce").fillna(0)
            df["incremento_precio"] = variacion > 0

            self._decisiones = df.set_index("cliente_id", drop=False)
        return self._decisiones

    def list_client_decisions(
        self,
        limit: int = 50,
        offset: int = 0,
        search: Optional[str] = None,
        elegible_mt: Optional[bool] = None,
        tipo_cliente: Optional[str] = None,
        solo_incremento: bool = False,
        sort_by: str = "cliente_id",
        descending: bool = False,
    ) -> tuple[int, list[dict]]:
        """Lista paginada del universo completo de clientes.

        Este listado NO altera /api/v1/recomendaciones: la cola comercial MT
        sigue conteniendo solamente oportunidades elegibles para Movistar Total.
        """
        df = self._load_decisiones().reset_index(drop=True)

        if search:
            q = str(search).strip().lower()
            if q:
                df = df[
                    df["cliente_id"]
                    .astype(str)
                    .str.lower()
                    .str.contains(q, na=False, regex=False)
                ]

        if elegible_mt is not None and "elegible_mt" in df.columns:
            df = df[df["elegible_mt"].fillna(False).astype(bool) == bool(elegible_mt)]

        if tipo_cliente and "tipo_cliente" in df.columns:
            df = df[
                df["tipo_cliente"]
                .astype(str)
                .str.lower()
                .eq(str(tipo_cliente).lower())
            ]

        if solo_incremento:
            df = df[df["incremento_precio"] == True]  # noqa: E712

        allowed_sort = {
            "cliente_id",
            "tipo_cliente",
            "antiguedad_meses",
            "total_actual",
            "elegible_mt",
            "prioridad_cliente",
            "oferta_recomendada",
            "decision_tipo",
            "variacion_mensual",
        }
        if sort_by not in allowed_sort or sort_by not in df.columns:
            sort_by = "cliente_id"

        df = df.sort_values(sort_by, ascending=not descending, na_position="last")
        total = len(df)
        page = df.iloc[offset: offset + limit]

        # La tabla Clientes necesita un resumen ligero, no las 50+ columnas.
        fields = [
            "cliente_id",
            "tipo_cliente",
            "antiguedad_meses",
            "ubicacion_departamento",
            "tiene_movil",
            "tiene_hogar",
            "tiene_internet_hogar",
            "es_movistar_total",
            "elegible_mt",
            "estado_mt",
            "prioridad_cliente",
            "prioridad_mt",
            "score_nbo_mt",
            "motivo_no_elegible_mt",
            "consumo_datos_gb_prom",
            "canal_mas_usado",
            "decision_tipo",
            "canal_sugerido",
            "plan_actual_id",
            "plan_actual_nombre",
            "total_actual",
            "oferta_recomendada_id",
            "oferta_recomendada",
            "precio_recomendado",
            "total_con_recomendacion",
            "variacion_mensual",
            "incremento_precio",
            "recomendacion_es_plan_actual",
            "adecuacion",
        ]
        fields = [field for field in fields if field in page.columns]
        return total, [
            _record_clean(x)
            for x in page[fields].to_dict(orient="records")
        ]

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
        solo_incremento: bool = False,
        sort_by: str = "score_nbo",
        descending: bool = True,
    ) -> tuple[int, list[dict]]:
        # Importante: este DataFrame sigue siendo SOLO el universo elegible MT.
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

        if solo_incremento:
            # Fuente única para el filtro económico: la capa universal ya contiene
            # la variación mensual equivalente para cada cliente elegible MT.
            decisiones = self._load_decisiones()
            positivos = decisiones[
                decisiones["elegible_mt"].fillna(False).astype(bool)
                & decisiones["incremento_precio"]
            ].index
            df = df[df["cliente_id"].isin(positivos)]

        allowed_sort = {
            "score_nbo",
            "cliente_id",
            "prioridad",
            "oferta_recomendada",
            "canal_recomendado",
            "monto_facturado_prom",
            "antiguedad_meses",
            "variacion_mensual_servicios",
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
