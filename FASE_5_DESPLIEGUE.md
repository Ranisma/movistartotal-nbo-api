# Fase 5 — Despliegue público y conexión con Figma Make

## Estado

El backend ya está preparado como Web Service de Render.

Configuración incluida:

- `render.yaml`
- `.python-version`
- health check `/health`
- Uvicorn escuchando en `0.0.0.0:$PORT`
- CORS configurable mediante `NBO_ALLOWED_ORIGINS`
- conector TypeScript para Figma Make

---

## OPCIÓN RECOMENDADA: Render + GitHub

### 1. Crea un repositorio en GitHub

Crea un repositorio, por ejemplo:

`movistar-total-nbo-api`

Sube **el contenido de esta carpeta a la raíz del repositorio**.

La raíz debe verse así:

```text
app/
data/
render.yaml
requirements.txt
.python-version
README.md
figma_make_api.ts
```

No subas la carpeta contenedora como una subcarpeta adicional si vas a usar
el `render.yaml` sin modificarlo.

### 2. En Render

1. Crea/inicia sesión en Render.
2. Elige `New` → `Blueprint` o `Web Service`.
3. Conecta el repositorio GitHub.
4. Si utilizas Blueprint, Render leerá `render.yaml`.
5. Confirma el servicio `movistar-total-nbo-api`.
6. Inicia el deploy.

Configuración equivalente si lo haces manualmente:

- Runtime: Python
- Build Command: `pip install -r requirements.txt`
- Start Command:
  `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Health Check Path: `/health`

### 3. Verifica la URL pública

Render asignará una URL parecida a:

`https://movistar-total-nbo-api.onrender.com`

Comprueba:

`https://...onrender.com/health`

Debe responder aproximadamente:

```json
{
  "status": "ok",
  "api_version": "1.1.0",
  "recomendaciones_cargadas": 13650
}
```

Luego visita:

`https://...onrender.com/docs`

Ahí aparecerá Swagger con todos los endpoints.

---

## 4. Conectar Figma Make

Abre `figma_make_api.ts`.

Cambia:

```ts
export const API_BASE_URL = "https://TU-SERVICIO.onrender.com";
```

por la URL de Render.

En Figma Make, pide que utilice ese módulo para reemplazar los datos mock.

Mapeo sugerido:

### Dashboard

`GET /api/v1/recomendaciones?limit=10`

### Clientes

`GET /api/v1/recomendaciones?limit=50&offset=0`

Filtros:

- `prioridad`
- `oferta`
- `canal`
- `score_min`
- `departamento`
- `search`

### Perfil 360°

`GET /api/v1/clientes/{cliente_id}`

### Recomendaciones

`GET /api/v1/clientes/{cliente_id}/top3`

### Analytics

- `/api/v1/ofertas/resumen`
- `/api/v1/canales/resumen`
- `/api/v1/prioridades/resumen`

---

## Prompt para Figma Make

Una vez que tengas la URL de Render, puedes indicarle:

```text
Replace the mock customer and NBO data with my external REST API.

Base URL:
https://TU-SERVICIO.onrender.com

Use these endpoints:

GET /api/v1/recomendaciones
GET /api/v1/clientes/{cliente_id}
GET /api/v1/clientes/{cliente_id}/top3
GET /api/v1/ofertas/resumen
GET /api/v1/canales/resumen
GET /api/v1/prioridades/resumen

Requirements:
- Dashboard must load the highest-score customers from the API.
- Clientes must use server-side search, filtering and pagination.
- Perfil 360 must load the selected customer by cliente_id.
- Recomendaciones must use the real Top 3 returned by the API.
- Analytics must use the three summary endpoints.
- Preserve the existing visual design.
- Add loading, error, empty and retry states.
- Do not use mock customer data after the API is connected.
```

---

## CORS

Para el hackathon el valor por defecto es `*`, lo que permite que Figma Make
consuma la API fácilmente.

Después, si quieres restringirlo, crea en Render:

`NBO_ALLOWED_ORIGINS`

Ejemplo:

`https://tu-app.figma.site,https://otro-dominio.com`

---

## Nota sobre Render Free

El plan gratuito es apropiado para demo/hackathon, pero puede dormirse cuando
permanece inactivo. El primer request después de un periodo de inactividad
puede tardar más.

Para una demo importante, abre `/health` unos minutos antes.
