from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from threading import Lock
from typing import Optional
from uuid import uuid4

import numpy as np
import pandas as pd

from .config import DATA_DIR, DEFAULT_RANGO_INCREMENTO, RANGOS_INCREMENTO


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


def _clean_nested(value):
    if isinstance(value, dict):
        return {k: _clean_nested(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean_nested(v) for v in value]
    return _clean_value(value)


def _normalizar_rango_incremento(rango: Optional[str]) -> str:
    value = str(rango or DEFAULT_RANGO_INCREMENTO).strip().lower()
    return value if value in RANGOS_INCREMENTO else DEFAULT_RANGO_INCREMENTO


def _mask_rango_incremento(variacion: pd.Series, rango: Optional[str]) -> pd.Series:
    """Devuelve la máscara del rango solicitado sobre variación mensual positiva."""
    values = pd.to_numeric(variacion, errors="coerce").fillna(0).round(2)
    selected = _normalizar_rango_incremento(rango)

    if selected == "cualquiera":
        return values > 0
    if selected == "menos_10":
        return (values > 0) & (values < 10)
    if selected == "desde_20":
        return values >= 20
    if selected == "desde_40":
        return values >= 40
    # Default: desde_10
    return values >= 10


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

        # Catálogo: se usa para construir rebates consistentes con el portafolio real
        # del desafío. Si el archivo no estuviera presente, el resto del motor sigue vivo.
        catalogo_path = DATA_DIR / "catalogo_ofertas_entrega.csv"
        self.catalogo = (
            pd.read_csv(catalogo_path)
            if catalogo_path.exists()
            else pd.DataFrame()
        )
        if not self.catalogo.empty and "oferta_id" in self.catalogo.columns:
            self.catalogo["oferta_id"] = self.catalogo["oferta_id"].astype(str)

        # Trazabilidad funcional del prototipo. El archivo es append-only y permite
        # reconstruir el recorrido oferta -> rechazo -> rebate -> resultado.
        # Nota: en Render el filesystem puede ser efímero entre redeploys; para una
        # implementación productiva esta misma interfaz debe apuntar a una BD.
        self._gestiones_path = DATA_DIR / "gestiones_comerciales.jsonl"
        self._gestiones_lock = Lock()

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

            variacion = pd.to_numeric(
                df.get("variacion_mensual"), errors="coerce"
            ).fillna(0).round(2)
            # Indicador técnico: cualquier variación positiva. El rango comercial
            # se decide dinámicamente en cada consulta.
            df["incremento_precio"] = variacion > 0

            self._decisiones = df.set_index("cliente_id", drop=False)
        return self._decisiones

    def list_client_decisions(
        self,
        limit: int = 100,
        offset: int = 0,
        search: Optional[str] = None,
        elegible_mt: Optional[bool] = None,
        tipo_cliente: Optional[str] = None,
        solo_incremento: bool = False,
        rango_incremento: str = DEFAULT_RANGO_INCREMENTO,
        sort_by: str = "score_nbo_mt",
        descending: bool = True,
    ) -> tuple[int, list[dict]]:
        """Vista Clientes: top comercial por defecto + búsqueda universal.

        Comportamiento intencional:
        - Sin `search`: muestra SOLO clientes elegibles MT, ordenados por Score NBO
          de mayor a menor. Si `solo_incremento=true`, aplica `rango_incremento`.
        - Con `search`: busca en los 100k clientes, incluso si no son aptos MT,
          ya tienen MT o no tienen incremento. La búsqueda universal tiene
          prioridad sobre el switch `solo_incremento`.

        `/api/v1/recomendaciones` no se modifica y continúa siendo exclusivamente
        la cola comercial de elegibles Movistar Total.
        """
        df = self._load_decisiones().reset_index(drop=True)

        q = str(search or "").strip().lower()
        searching = bool(q)

        if searching:
            # Búsqueda universal: cualquier cliente de la base puede aparecer.
            df = df[
                df["cliente_id"]
                .astype(str)
                .str.lower()
                .str.contains(q, na=False, regex=False)
            ].copy()

            # Si existe coincidencia exacta, la colocamos primero.
            df["_exact_search"] = (
                df["cliente_id"].astype(str).str.lower().eq(q)
            )
            df = df.sort_values(
                ["_exact_search", "cliente_id"],
                ascending=[False, True],
                na_position="last",
            ).drop(columns=["_exact_search"])

            # Importante: NO aplicamos solo_incremento aquí. Esto permite encontrar
            # a un cliente no apto MT aunque el switch haya quedado activado.
            if elegible_mt is not None and "elegible_mt" in df.columns:
                df = df[df["elegible_mt"].fillna(False).astype(bool) == bool(elegible_mt)]

            if tipo_cliente and "tipo_cliente" in df.columns:
                df = df[
                    df["tipo_cliente"]
                    .astype(str)
                    .str.lower()
                    .eq(str(tipo_cliente).lower())
                ]

        else:
            # Estado por defecto de Clientes = ranking comercial MT, no los 100k.
            if "elegible_mt" in df.columns:
                df = df[df["elegible_mt"].fillna(False).astype(bool)]

            if tipo_cliente and "tipo_cliente" in df.columns:
                df = df[
                    df["tipo_cliente"]
                    .astype(str)
                    .str.lower()
                    .eq(str(tipo_cliente).lower())
                ]

            if solo_incremento:
                df = df[_mask_rango_incremento(df["variacion_mensual"], rango_incremento)]

            # En la vista por defecto SIEMPRE manda el Score NBO.
            if "score_nbo_mt" in df.columns:
                df = df.sort_values(
                    ["score_nbo_mt", "cliente_id"],
                    ascending=[False, True],
                    na_position="last",
                )
            else:
                df = df.sort_values("cliente_id", ascending=True)

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

    def _catalog_offer(self, oferta_id: Optional[str]) -> Optional[dict]:
        if not oferta_id or self.catalogo.empty or "oferta_id" not in self.catalogo.columns:
            return None
        rows = self.catalogo[self.catalogo["oferta_id"].astype(str) == str(oferta_id)]
        if rows.empty:
            return None
        return _record_clean(rows.iloc[0].to_dict())

    @staticmethod
    def _fit_for_usage(gb: Optional[float], consumo: Optional[float]) -> dict:
        if gb is None or consumo is None:
            return {
                "adecuacion": "Sin historial",
                "deficit_gb": None,
                "margen_gb": None,
            }
        capacidad = float(gb)
        uso = float(consumo)
        if capacidad >= 9999:
            return {"adecuacion": "Adecuado", "deficit_gb": 0.0, "margen_gb": None}
        margen = round(capacidad - uso, 3)
        if margen >= 0:
            return {"adecuacion": "Adecuado", "deficit_gb": 0.0, "margen_gb": margen}
        return {
            "adecuacion": "Limitado",
            "deficit_gb": round(abs(margen), 3),
            "margen_gb": margen,
        }

    def _rebate_option_from_offer(
        self,
        row: pd.Series,
        oferta: dict,
        tipo: str,
    ) -> dict:
        oferta_id = str(oferta.get("oferta_id"))
        nombre = oferta.get("nombre_oferta") or oferta_id
        precio = float(oferta.get("precio_mensual") or 0)
        gb = oferta.get("gb_incluidos")
        gb = None if gb is None else float(gb)
        total_actual = float(row.get("total_actual") or 0)
        consumo = row.get("consumo_datos_gb_prom")
        consumo = None if pd.isna(consumo) else float(consumo)

        tipo_oferta = str(oferta.get("tipo_oferta") or "").lower()
        es_mt = bool(oferta.get("es_movistar_total")) or tipo_oferta == "movistar_total"

        if es_mt:
            total_resultante = precio
        elif tipo_oferta == "plan_movil":
            hogar = row.get("hogar_actual_precio")
            hogar = 0.0 if hogar is None or pd.isna(hogar) else float(hogar)
            total_resultante = precio + hogar
        else:
            total_resultante = precio

        total_resultante = round(total_resultante, 2)
        variacion = round(total_resultante - total_actual, 2)
        fit = self._fit_for_usage(gb, consumo)

        if tipo == "precio":
            if fit["adecuacion"] == "Limitado":
                mensaje = (
                    f"Esta alternativa reduce el precio, pero quedaría aproximadamente "
                    f"{fit['deficit_gb']:.1f} GB/mes por debajo de tu consumo promedio."
                )
                speech = (
                    f"Si prefieres priorizar el ahorro, podemos revisar {nombre}. "
                    f"Pagarías S/{total_resultante:.2f} al mes. Ten en cuenta que su "
                    f"capacidad quedaría aproximadamente {fit['deficit_gb']:.1f} GB por "
                    "debajo de tu consumo habitual."
                )
            else:
                mensaje = "Alternativa de menor precio que mantiene cobertura suficiente del consumo observado."
                speech = (
                    f"Si prefieres priorizar el ahorro, {nombre} es una alternativa de "
                    f"S/{total_resultante:.2f} al mes y mantiene cobertura suficiente "
                    "para tu consumo observado."
                )
        else:
            mensaje = "Alternativa con mayor capacidad de datos para dar más holgura frente al consumo observado."
            speech = (
                f"Si prefieres tener más capacidad de datos, podemos revisar {nombre}. "
                f"La opción quedaría en S/{total_resultante:.2f} al mes y te da mayor "
                "holgura frente a tu consumo habitual."
            )

        return {
            "tipo": tipo,
            "titulo": "Prioriza pagar menos" if tipo == "precio" else "Prioriza más capacidad de datos",
            "disponible": True,
            "accion": "cambiar_oferta",
            "oferta_id": oferta_id,
            "oferta": nombre,
            "precio": round(precio, 2),
            "gb": gb,
            "total_resultante": total_resultante,
            "variacion_mensual": variacion,
            "adecuacion": fit["adecuacion"],
            "deficit_gb": fit["deficit_gb"],
            "margen_gb": fit["margen_gb"],
            "mensaje": mensaje,
            "speech_sugerido": speech,
        }

    def get_rebate_options(self, cliente_id: str) -> dict:
        """Devuelve dos caminos de rebate: precio y capacidad.

        La elección NO intenta adivinar la preferencia del cliente. Se activa después
        del rechazo, cuando el asesor identifica si prioriza pagar menos o disponer
        de mayor capacidad de datos.
        """
        df = self._load_decisiones()
        key = str(cliente_id)
        if key not in df.index:
            return {"precio": None, "capacidad": None}

        row = df.loc[key]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]

        principal_id = row.get("oferta_recomendada_id")
        if principal_id is None or pd.isna(principal_id):
            return {"precio": None, "capacidad": None}
        principal_id = str(principal_id)
        principal = self._catalog_offer(principal_id)
        if principal is None:
            return {"precio": None, "capacidad": None}

        tipo = str(principal.get("tipo_oferta") or "").lower()
        es_mt = bool(principal.get("es_movistar_total")) or tipo == "movistar_total"

        if self.catalogo.empty:
            return {"precio": None, "capacidad": None}

        if es_mt:
            familia = self.catalogo[
                self.catalogo.get("es_movistar_total", False).fillna(False).astype(bool)
            ].copy()
        elif tipo == "plan_movil":
            familia = self.catalogo[
                self.catalogo.get("tipo_oferta", "").astype(str).str.lower().eq("plan_movil")
            ].copy()
        else:
            return {"precio": None, "capacidad": None}

        if familia.empty:
            return {"precio": None, "capacidad": None}

        familia["precio_mensual"] = pd.to_numeric(familia["precio_mensual"], errors="coerce")
        familia["gb_incluidos"] = pd.to_numeric(familia["gb_incluidos"], errors="coerce")
        principal_precio = float(principal.get("precio_mensual") or 0)
        principal_gb = float(principal.get("gb_incluidos") or 0)

        cheaper = familia[familia["precio_mensual"] < principal_precio].sort_values(
            "precio_mensual", ascending=False
        )
        if not cheaper.empty:
            rebate_precio = self._rebate_option_from_offer(
                row, _record_clean(cheaper.iloc[0].to_dict()), "precio"
            )
        else:
            total_actual = round(float(row.get("total_actual") or 0), 2)
            rebate_precio = {
                "tipo": "precio",
                "titulo": "Prioriza pagar menos",
                "disponible": True,
                "accion": "mantener_situacion_actual",
                "oferta_id": None,
                "oferta": "Mantener situación actual",
                "precio": total_actual,
                "gb": row.get("consumo_datos_gb_prom"),
                "total_resultante": total_actual,
                "variacion_mensual": 0.0,
                "adecuacion": "Mantener",
                "deficit_gb": None,
                "margen_gb": None,
                "mensaje": "La recomendación principal ya es la alternativa de menor precio de esta familia. Si el cliente prioriza pagar menos, se puede mantener su situación actual.",
                "speech_sugerido": "Si hoy prefieres no aumentar tu pago, podemos mantener tus servicios actuales y dejar la alternativa recomendada para una próxima evaluación.",
            }

        if principal_gb >= 9999:
            higher = familia.iloc[0:0]
        else:
            higher = familia[familia["gb_incluidos"] > principal_gb].sort_values(
                ["gb_incluidos", "precio_mensual"], ascending=[True, True]
            )

        if not higher.empty:
            rebate_capacidad = self._rebate_option_from_offer(
                row, _record_clean(higher.iloc[0].to_dict()), "capacidad"
            )
        else:
            rebate_capacidad = {
                "tipo": "capacidad",
                "titulo": "Prioriza más capacidad de datos",
                "disponible": False,
                "accion": "sin_alternativa_superior",
                "oferta_id": principal_id,
                "oferta": principal.get("nombre_oferta") or principal_id,
                "precio": round(principal_precio, 2),
                "gb": principal_gb,
                "total_resultante": row.get("total_con_recomendacion"),
                "variacion_mensual": row.get("variacion_mensual"),
                "adecuacion": row.get("adecuacion"),
                "deficit_gb": row.get("deficit_gb"),
                "margen_gb": row.get("margen_gb"),
                "mensaje": "La recomendación principal ya ofrece la máxima capacidad disponible dentro de esta familia de ofertas.",
                "speech_sugerido": "La opción que te recomendé ya es la alternativa con mayor capacidad disponible, por lo que no necesitas subir a otro nivel para obtener más datos.",
            }

        return _clean_nested({"precio": rebate_precio, "capacidad": rebate_capacidad})

    def _read_gestiones(self, cliente_id: Optional[str] = None) -> list[dict]:
        if not self._gestiones_path.exists():
            return []
        rows: list[dict] = []
        with self._gestiones_lock:
            with open(self._gestiones_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if cliente_id is None or str(item.get("cliente_id")) == str(cliente_id):
                        rows.append(item)
        return rows

    @staticmethod
    def _estado_desde_evento(evento: Optional[str]) -> str:
        mapping = {
            "oferta_presentada": "Ofrecida",
            "oferta_aceptada": "Aceptada",
            "oferta_rechazada": "Rechazada",
            "rebate_presentado": "Rebate ofrecido",
            "rebate_aceptado": "Aceptada vía rebate",
            "rebate_rechazado": "Rechazada definitiva",
        }
        return mapping.get(str(evento or "").lower(), "Pendiente")

    def get_historial_gestion(self, cliente_id: str) -> list[dict]:
        rows = self._read_gestiones(str(cliente_id))
        return sorted(rows, key=lambda x: str(x.get("fecha_hora") or ""))

    def get_estado_gestion(self, cliente_id: str) -> str:
        rows = self.get_historial_gestion(cliente_id)
        if not rows:
            return "Pendiente"
        return self._estado_desde_evento(rows[-1].get("evento"))

    def registrar_gestion(
        self,
        cliente_id: str,
        evento: str,
        canal: Optional[str] = None,
        motivo_rechazo: Optional[str] = None,
        tipo_rebate: Optional[str] = None,
        oferta_rebate_id: Optional[str] = None,
        comentario: Optional[str] = None,
    ) -> dict:
        eventos_validos = {
            "oferta_presentada",
            "oferta_aceptada",
            "oferta_rechazada",
            "rebate_presentado",
            "rebate_aceptado",
            "rebate_rechazado",
        }
        evento = str(evento or "").strip().lower()
        if evento not in eventos_validos:
            raise ValueError(f"Evento no válido: {evento}")

        df = self._load_decisiones()
        key = str(cliente_id)
        if key not in df.index:
            raise ValueError(f"Cliente no encontrado: {key}")

        if evento == "oferta_rechazada" and not str(motivo_rechazo or "").strip():
            raise ValueError("El motivo_rechazo es obligatorio cuando la oferta es rechazada")

        if evento.startswith("rebate_"):
            tipo_rebate = str(tipo_rebate or "").strip().lower()
            if tipo_rebate not in {"precio", "capacidad"}:
                raise ValueError("tipo_rebate debe ser 'precio' o 'capacidad'")

        row = df.loc[key]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]

        registro = {
            "gestion_id": str(uuid4()),
            "fecha_hora": datetime.now(timezone.utc).isoformat(),
            "cliente_id": key,
            "evento": evento,
            "estado_resultante": self._estado_desde_evento(evento),
            "oferta_principal_id": _clean_value(row.get("oferta_recomendada_id")),
            "oferta_principal": _clean_value(row.get("oferta_recomendada")),
            "canal": canal or _clean_value(row.get("canal_sugerido")),
            "motivo_rechazo": str(motivo_rechazo).strip() if motivo_rechazo else None,
            "tipo_rebate": tipo_rebate,
            "oferta_rebate_id": oferta_rebate_id,
            "comentario": str(comentario).strip() if comentario else None,
        }

        self._gestiones_path.parent.mkdir(parents=True, exist_ok=True)
        with self._gestiones_lock:
            with open(self._gestiones_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(registro, ensure_ascii=False) + "\n")

        return registro

    def get_funnel_gestiones(self) -> dict:
        rows = self._read_gestiones()
        by_client: dict[str, set[str]] = {}
        for row in rows:
            cid = str(row.get("cliente_id"))
            by_client.setdefault(cid, set()).add(str(row.get("evento")))

        values = list(by_client.values())
        return {
            "priorizados": int(len(self.recomendaciones)),
            "gestionados": len(values),
            "ofrecidos": sum(1 for ev in values if ev & {"oferta_presentada", "oferta_aceptada", "oferta_rechazada", "rebate_presentado", "rebate_aceptado", "rebate_rechazado"}),
            "aceptados_principal": sum(1 for ev in values if "oferta_aceptada" in ev),
            "rechazados_principal": sum(1 for ev in values if "oferta_rechazada" in ev),
            "con_rebate": sum(1 for ev in values if ev & {"rebate_presentado", "rebate_aceptado", "rebate_rechazado"}),
            "aceptados_rebate": sum(1 for ev in values if "rebate_aceptado" in ev),
            "rechazados_definitivos": sum(1 for ev in values if "rebate_rechazado" in ev),
        }

    def get_client_decision(self, cliente_id: str) -> Optional[dict]:
        df = self._load_decisiones()
        key = str(cliente_id)
        if key not in df.index:
            return None
        row = df.loc[key]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        decision = _record_clean(row.to_dict())
        decision["rebates"] = self.get_rebate_options(key)
        historial = self.get_historial_gestion(key)
        decision["trazabilidad"] = {
            "estado_actual": self.get_estado_gestion(key),
            "historial": historial,
        }
        return _clean_nested(decision)

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
        rango_incremento: str = DEFAULT_RANGO_INCREMENTO,
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
            # Fuente única para el filtro económico: la capa universal contiene
            # la variación mensual equivalente para cada cliente elegible MT.
            decisiones = self._load_decisiones()
            elegibles = decisiones["elegible_mt"].fillna(False).astype(bool)
            rango_mask = _mask_rango_incremento(
                decisiones["variacion_mensual"], rango_incremento
            )
            ids_filtrados = decisiones[elegibles & rango_mask].index
            df = df[df["cliente_id"].isin(ids_filtrados)]

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
