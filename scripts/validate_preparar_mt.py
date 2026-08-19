from pathlib import Path
import pandas as pd

from app.preparar_mt import list_preparations

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
EXPECTED = {"Alto": 4628, "Medio": 4213, "Bajo": 2164}


def main():
    decisiones = pd.read_csv(DATA / "decisiones_cliente.csv.gz")
    catalogo = pd.read_csv(DATA / "catalogo_ofertas_entrega.csv")
    recomendaciones = pd.read_csv(DATA / "fase_3_recomendaciones_nbo.csv")

    assert len(recomendaciones) == 13650, f"Regresion MT: {len(recomendaciones)} recomendaciones"

    total, items = list_preparations(
        decisions=decisiones,
        catalog=catalogo,
        limit=500,
        offset=0,
        potential=None,
        search=None,
    )
    assert total == 11005, f"Universo Preparar MT inesperado: {total}"

    counts = {}
    for p in ["Alto", "Medio", "Bajo"]:
        c, _ = list_preparations(
            decisiones, catalogo, limit=1, offset=0, potential=p, search=None
        )
        counts[p] = c
    assert counts == EXPECTED, f"Distribucion Preparar MT inesperada: {counts}"
    assert sum(counts.values()) == total

    main_by_id = decisiones.set_index(decisiones["cliente_id"].astype(str), drop=False)

    _, sample = list_preparations(
        decisiones,
        catalogo,
        limit=min(500, total),
        offset=0,
        potential=None,
        search=None,
    )
    for item in sample:
        assert item["estado"] == "Preparar para MT"
        assert item["accion_recomendada"] == "Migrar a Postpago"
        assert item["potencial"] in {"Alto", "Medio", "Bajo"}
        assert item["oferta_recomendada_id"] in {"OF001", "OF002", "OF003", "OF004"}
        assert "score_mt" not in item
        assert "score_nbo_mt" not in item
        assert item["consumo_datos_gb_prom"] >= 10
        assert item["ruta_mt"]["resultado"] == "Habilitado para evaluación posterior de Movistar Total"

        source = main_by_id.loc[str(item["cliente_id"])]
        if isinstance(source, pd.DataFrame):
            source = source.iloc[0]
        assert str(source["tipo_cliente"]).lower() == "prepago"
        assert bool(source["tiene_internet_hogar"])
        assert not bool(source["es_movistar_total"])
        assert str(source["oferta_recomendada_id"]) == str(item["oferta_recomendada_id"])
        assert str(source["oferta_recomendada"]) == str(item["oferta_recomendada"])

    print("MT_RECOMMENDATIONS", len(recomendaciones))
    print("PREPARAR_MT_TOTAL", total)
    print("PREPARAR_MT_ALTO", counts["Alto"])
    print("PREPARAR_MT_MEDIO", counts["Medio"])
    print("PREPARAR_MT_BAJO", counts["Bajo"])
    print("TOP_EXAMPLES")
    for item in items[:5]:
        print(
            item["cliente_id"],
            item["consumo_datos_gb_prom"],
            item["oferta_recomendada_id"],
            item["potencial"],
            item["historial_movil_disponible"],
        )


if __name__ == "__main__":
    main()
