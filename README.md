# Financial Copilot

Estoy desarrollando una herramienta para organizar ingresos, gastos, deudas y metas, consultar documentación financiera y explicar escenarios de ahorro. Hoy mantengo un prototipo local; todavía no lo considero apto para recibir datos personales de terceros en un servicio público.

## Qué implementé

Implementé una API FastAPI, perfiles e historial en SQLite, ingesta de texto y HTML, recuperación documental con Chroma, reglas financieras, comparación de un catálogo ilustrativo y una interfaz web. Mantengo pruebas automatizadas y un flujo de integración continua.

Puedo ejecutar el prototipo sin clave de proveedor: uso representaciones de texto basadas en hash y respuestas extractivas. Cuando habilito el modelo de lenguaje, actualmente también puede generar recomendaciones. Por eso no presento todo el comportamiento como determinístico.

## Límites actuales

Todavía no implementé autenticación ni autorización por propietario. Los documentos comparten un índice global. Tengo que corregir estimaciones de capital, asignaciones a metas e indicadores de confianza. El catálogo es ilustrativo y no representa cotizaciones vigentes. No uso este prototipo para ejecutar operaciones ni ofrecer asesoramiento profesional.

## Ejecución local

Uso Python 3.11 como referencia del flujo de integración continua.

```bash
python -m venv .venv
```

En Windows activo el entorno con `.venv\Scripts\Activate.ps1`; en Linux o macOS uso `source .venv/bin/activate`.

```bash
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Abro la interfaz en `http://127.0.0.1:8000/` y los contratos en `http://127.0.0.1:8000/docs`. También puedo usar `docker compose up --build` para desarrollo local.

## Configuración

Uso el entorno o un `.env` local que no publico.

| Variable | Uso que le doy |
|---|---|
| `OFFLINE_MODE=true` | Fuerzo la ejecución sin llamadas al proveedor. |
| `OPENAI_API_KEY` | Habilito las integraciones existentes de embeddings y generación. |
| `OPENAI_MODEL` | Selecciono el modelo de generación. |
| `DATA_DIR` | Defino el directorio persistente. |
| `SQLITE_PATH` | Defino la ubicación de SQLite. |
| `CHROMA_DIR` | Defino la ubicación del índice vectorial. |
| `ALLOWED_ORIGINS` | Configuro una lista JSON de orígenes permitidos. |

Tengo pendiente corregir los nombres de variables de almacenamiento en Compose. En el despliegue serverless actual `/tmp/data` es temporal; no lo trato como almacenamiento durable.

## Organización

Mantengo API en `app/main.py`, casos de uso en `app/services/`, contratos en `app/schemas/`, repositorios en `app/data/`, cálculo en `app/reasoning/`, catálogo en `app/opportunity_engine/`, recuperación en `app/rag/` e interfaz en `public/`.

## Verificación

Ejecuto la suite con `python -m pytest -q`. En la revisión del 3 de octubre de 2026 validé la sintaxis de 46 archivos Python y reproduje inconsistencias de asignación mediante ejecución directa. No pude ejecutar la suite completa porque el intérprete accesible no tenía `pytest`; no reporto pruebas aprobadas.

## Evolución

Dejé mis hallazgos en [la auditoría](docs/AUDITORIA_PRODUCTO.md) y mi estrategia en [el plan de producto](docs/PLAN_PRODUCTO.md). Distingo lo implementado de lo propuesto.
