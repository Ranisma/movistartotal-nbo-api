from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

API_TITLE = "Movistar Total — NBO Intelligence API"
API_VERSION = "1.1.0"
API_DESCRIPTION = (
    "API pública de consulta para el motor Next Best Offer de Movistar Total. "
    "Expone clientes elegibles, recomendaciones, Top 3 de ofertas, "
    "resúmenes y métricas del motor NBO."
)

def allowed_origins():
    raw = os.getenv("NBO_ALLOWED_ORIGINS", "*").strip()
    if raw == "*":
        return ["*"]
    return [x.strip() for x in raw.split(",") if x.strip()]
