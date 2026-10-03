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
python -m pip install -r requirements-dev.lock
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Separé las dependencias en cuatro archivos. `requirements.txt` fija las dependencias directas de ejecución y `requirements-dev.txt` agrega `pytest` y `httpx`. Generé `requirements.lock` y `requirements-dev.lock` con `uv pip compile --universal` para Python 3.11, acotando las transitivas con las versiones de un entorno donde la suite pasó. La imagen Docker instala `requirements.lock` y el flujo de integración continua instala `requirements-dev.lock`.

Abro la interfaz en `http://127.0.0.1:8000/` y los contratos en `http://127.0.0.1:8000/docs`. También puedo usar `docker compose up --build` para desarrollo local.

## Configuración

Uso el entorno o un `.env` local que no publico. Parto de `.env.example`, que no contiene claves y usa los mismos nombres que `Settings` en `app/core/config.py`.

| Variable | Uso que le doy |
|---|---|
| `OFFLINE_MODE=true` | Fuerzo la ejecución sin llamadas al proveedor. |
| `OPENAI_API_KEY` | Habilito las integraciones existentes de embeddings y generación. |
| `OPENAI_MODEL` | Selecciono el modelo de generación. |
| `DATA_DIR` | Defino el directorio persistente. |
| `SQLITE_PATH` | Defino la ubicación de SQLite. |
| `CHROMA_DIR` | Defino la ubicación del índice vectorial. |
| `ALLOWED_ORIGINS` | Configuro una lista JSON de orígenes permitidos. |

Corregí Compose para que use `DATA_DIR`, `SQLITE_PATH` y `CHROMA_DIR`; antes definía variables que `Settings` no leía. La base sigue en `/app/data/app.db` dentro del volumen. En el despliegue serverless actual `/tmp/data` es temporal; no lo trato como almacenamiento durable.

## Datos generados

No versiono `data/app.db` ni `data/chroma/`: los genera la aplicación al ejecutarse y pueden contener información cargada. Retiré del árbol actual los cuatro archivos de índice de `data/chroma/` que había versionado; las copias locales siguen en disco. Esos archivos permanecen en el historial de Git, que no reescribí.

## Organización

Mantengo API en `app/main.py`, casos de uso en `app/services/`, contratos en `app/schemas/`, repositorios en `app/data/`, cálculo en `app/reasoning/`, catálogo en `app/opportunity_engine/`, recuperación en `app/rag/` e interfaz en `public/`.

## Verificación

Ejecuto la suite con `python -m pytest -q`. El 3 de octubre de 2026 instalé `requirements-dev.lock` en un entorno limpio de Python 3.11 en Windows y obtuve 46 pruebas aprobadas. Ese mismo día construí la imagen Docker sin errores. Levanté un contenedor en modo offline con las variables de Compose: `/health` respondió 200, el chequeo de salud quedó en `healthy`, la aplicación creó SQLite y Chroma en `/app/data` y la imagen no incluía datos locales. No ejecuté la suite dentro del contenedor.

Las pruebas de fragmentación ejecutan cada caso en un proceso aislado con tiempo máximo, para detectar bucles en el divisor alternativo.

## Evolución

Dejé mis hallazgos en [la auditoría](docs/AUDITORIA_PRODUCTO.md) y mi estrategia en [el plan de producto](docs/PLAN_PRODUCTO.md). Distingo lo implementado de lo propuesto.
