from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

API_TITLE = "Movistar Total — NBO Intelligence API"
API_VERSION = "1.7.0"
API_DESCRIPTION = (
    "API pública para el motor Next Best Offer de Movistar Total y la capa "
    "Next Best Decision para consulta universal de clientes, elegibilidad MT, "
    "prioridad comercial, top de oportunidades y búsqueda universal de clientes."
)


# Rangos admitidos por los filtros de incremento de precio.
# El valor por defecto evita que diferencias nominales (p. ej. S/0.10)
# dominen la revisión comercial, pero siguen disponibles mediante menos_10.
DEFAULT_RANGO_INCREMENTO = "desde_10"
RANGOS_INCREMENTO = {
    "cualquiera",
    "menos_10",
    "desde_10",
    "desde_20",
    "desde_40",
}

def allowed_origins():
    raw = os.getenv("NBO_ALLOWED_ORIGINS", "*").strip()
    if raw == "*":
        return ["*"]
    return [x.strip() for x in raw.split(",") if x.strip()]
