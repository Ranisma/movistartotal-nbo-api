# Fase 4 — API NBO Movistar Total

Esta API expone los resultados de la Fase 3 para que una interfaz web, Figma Make,
React u otro frontend pueda consultar clientes y recomendaciones NBO.

## Qué contiene

- 13,650 clientes elegibles con recomendación final.
- Top 3 de ofertas Movistar Total por cliente.
- Oferta recomendada.
- Canal recomendado.
- Score NBO.
- Prioridad comercial.
- Información 360° resumida del cliente.
- Resúmenes de ofertas, canales y prioridades.

## Instalar

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

## Ejecutar

Desde la carpeta `fase_4_nbo_api`:

```bash
uvicorn app.main:app --reload --port 8000
```

Luego abre:

- Documentación Swagger: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/health`

## Endpoints principales

### Listar recomendaciones

```http
GET /api/v1/recomendaciones
```

Filtros soportados:

```http
GET /api/v1/recomendaciones?prioridad=Muy%20alta&limit=20
GET /api/v1/recomendaciones?canal=Call%20In
GET /api/v1/recomendaciones?score_min=0.80
GET /api/v1/recomendaciones?oferta=Plus
GET /api/v1/recomendaciones?search=CLI000001
```

### Perfil 360° + NBO

```http
GET /api/v1/clientes/CLI000001
```

Devuelve:

```json
{
  "cliente_id": "CLI000001",
  "perfil": {},
  "recomendacion": {},
  "alternativas": []
}
```

### Recomendación única

```http
GET /api/v1/clientes/CLI000001/recomendacion
```

### Top 3

```http
GET /api/v1/clientes/CLI000001/top3
```

### Analytics

```http
GET /api/v1/ofertas/resumen
GET /api/v1/canales/resumen
GET /api/v1/prioridades/resumen
```

## Conexión desde Figma Make / React

Ejemplo en JavaScript:

```javascript
const API = "http://127.0.0.1:8000";

export async function getCliente(clienteId) {
  const response = await fetch(`${API}/api/v1/clientes/${clienteId}`);

  if (!response.ok) {
    throw new Error("Cliente no encontrado");
  }

  return response.json();
}
```

Listado:

```javascript
const response = await fetch(
  `${API}/api/v1/recomendaciones?prioridad=Muy%20alta&limit=20`
);

const data = await response.json();
console.log(data.items);
```

## Importante sobre CORS

Para facilitar el prototipo, la API acepta peticiones GET desde cualquier origen.

En producción NO debe quedar así. Debe reemplazarse:

```python
allow_origins=["*"]
```

por el dominio real del frontend.

## Arquitectura

```text
Figma Make / React
        |
        | HTTPS / JSON
        v
     FastAPI
        |
        +--> recomendaciones NBO
        +--> Top 3
        +--> perfiles 360°
        +--> analytics
        |
        v
CSV Fase 3 (prototipo)
```

Para una versión productiva, los CSV deberían migrarse a PostgreSQL u otra base
transaccional/analítica, pero para el hackathon esta API ya desacopla correctamente
el frontend del motor de datos.
