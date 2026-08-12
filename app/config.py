from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

API_TITLE = "Movistar Total — NBO Intelligence API"
API_VERSION = "1.2.0"
API_DESCRIPTION = (
    "API pública para el motor Next Best Offer de Movistar Total y la capa "
    "Next Best Decision para consulta universal de clientes."
)

def allowed_origins():
    raw = os.getenv("NBO_ALLOWED_ORIGINS", "*").strip()
    if raw == "*":
        return ["*"]
    return [x.strip() for x in raw.split(",") if x.strip()]
