# Financial Copilot

Estoy desarrollando una herramienta para organizar ingresos, gastos, deudas y metas, consultar material financiero educativo y comparar escenarios de ahorro. Hoy mantengo una API y una aplicación web en desarrollo. Todavía no las publiqué, no las conecté a un proveedor de identidad real y no las validé con participantes.

## Qué implementé

- **Cuentas con identidad gestionada.** Las rutas `/v1` exigen un token de acceso OIDC (JWT). Verifico firma por JWKS, emisor, audiencia, expiración y rotación de claves. La cuenta sale del token; la URL y el cuerpo no aceptan identificadores de persona. Retiré las rutas anteriores que tomaban un `user_id` del cliente.
- **Perfil, metas y planes v1.** Los importes son Decimal con moneda explícita. Los planes se calculan con el núcleo de `app/finance/`, que mantiene un presupuesto por moneda y reparte el saldo actual y el excedente mensual una sola vez: reserva, deuda de tasa alta y metas.
- **Planes versionados, escenarios y revisión mensual.** Cada plan es una versión con un snapshot mínimo y tipado, la política y la versión del motor, y se puede reproducir. Los escenarios no modifican el plan vigente: adoptarlos es una acción explícita que crea otra versión. Registro avances por meta y mes sin contar dos veces un aporte, y comparo lo previsto con lo registrado. Las creaciones exigen `Idempotency-Key`. Las reglas están en [planes y revisión](docs/PLANES_Y_REVISION.md).
- **Persistencia en PostgreSQL** con SQLAlchemy y migraciones versionadas de Alembic (`migrations/`), con restricciones e índices. Para desarrollo y pruebas también acepto SQLite; producción exige PostgreSQL.
- **Privacidad.** Exportación (`GET /v1/me/export`), borrado con recibo de evidencia (`DELETE /v1/me`), retención, auditoría sin contenido financiero y reaplicación de borrados tras restaurar un backup.
- **Corpus público curado** para preguntas educativas (`POST /v1/knowledge/query`). Los documentos privados quedan fuera de esta etapa: no hay ingesta por HTTP y la base solo admite el corpus público.
- **Entorno de producción** que se niega a arrancar con configuración insegura, y CORS con orígenes explícitos.
- **Aplicación web** (`web/`, React, TypeScript y Vite) con alta progresiva, situación actual, plan mensual, metas, escenarios, revisión mensual, «Cómo lo calculé» y cuenta. No calcula importes en el navegador. Los detalles están en [la experiencia web](docs/EXPERIENCIA_WEB.md).

Los contratos y las rutas retiradas están en [la migración de contratos](docs/MIGRACION_CONTRATOS.md). El contrato de identidad, los almacenes, la retención y los backups están en [identidad y privacidad](docs/IDENTIDAD_Y_PRIVACIDAD.md).

El motor de recomendaciones y el catálogo ilustrativo siguen como módulos internos con pruebas, sin ruta pública. Cuando habilito el modelo de lenguaje en ese motor, puede agregar texto, pero no importes ni acciones del plan.

## Límites actuales

- La API no sirve la aplicación web: en `/` muestra un aviso y la aplicación se compila y se publica aparte. La interfaz anterior de `public/` quedó sin uso.
- No elegí proveedor de identidad ni probé contra su JWKS real.
- No agregué políticas de fila de PostgreSQL. El aislamiento depende de los repositorios y de la matriz de pruebas.
- El rate limiting se guarda en memoria del proceso.
- El índice Chroma es local y no admite varios procesos, así que la imagen corre un solo worker.
- `vercel.json` corresponde al despliegue anterior y no lo actualicé.
- El plan usa reglas y supuestos explícitos; no es un pronóstico ni asesoramiento profesional. El catálogo es ilustrativo.

## Ejecución local

Uso Python 3.11 como referencia de la integración continua.

```bash
python -m venv .venv
python -m pip install -r requirements-dev.lock
cp .env.example .env
python scripts/dev_identity.py init
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

En Windows activo el entorno con `.venv\Scripts\Activate.ps1`. Para obtener un token local uso `python scripts/dev_identity.py token --subject demo-person` y lo envío como `Authorization: Bearer <token>`. Las claves locales quedan en `data/dev_identity/`, que no se versiona. Producción las rechaza.

Sin `DATABASE_URL`, uso SQLite en `DATA_DIR/app.db` y aplico migraciones al arrancar. Con Compose levanto PostgreSQL y la API; antes defino `POSTGRES_PASSWORD` en `.env`:

```bash
docker compose up --build
```

Scripts operativos:

| Script | Uso |
|---|---|
| `scripts/migrate.py upgrade|downgrade|current` | Aplico o revierto migraciones. |
| `scripts/ingest_public_corpus.py` | Cargo material público curado. |
| `scripts/import_local_demo.py` | Importo un perfil ficticio del SQLite anterior, con confirmación explícita. |
| `scripts/privacy_maintenance.py` | Aplico retención, exporto recibos y reaplico borrados tras un restore. |
| `scripts/dev_identity.py` | Genero claves y tokens locales. |
| `scripts/dev_oidc_provider.py` | Levanto un proveedor OIDC local para la aplicación web y la QA. |
| `scripts/build_web_demo.py` | Genero los datos ficticios de la demo con la API real. |

## Configuración

Parto de `.env.example`, que no contiene claves.

| Variable | Uso |
|---|---|
| `ENVIRONMENT` | `local`, `test` o `production`. |
| `DATABASE_URL` | URL de SQLAlchemy; en producción, `postgresql+psycopg://...`. |
| `AUTO_MIGRATE` | Aplico migraciones al arrancar; en producción debe ser `false`. |
| `OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_JWKS_URL` | Configuro el proveedor de identidad. |
| `OIDC_ALGORITHMS` | Algoritmos asimétricos permitidos; por defecto `["RS256"]`. |
| `PRIVACY_HASH_KEY` | Clave para seudonimizar recibos de borrado; obligatoria en producción. |
| `PLAN_RETENTION_DAYS`, `AUDIT_RETENTION_DAYS`, `BACKUP_RETENTION_DAYS` | Defino los plazos de retención. |
| `ALLOWED_ORIGINS` | Lista JSON de orígenes; en producción, https explícitos. |
| `DATA_DIR`, `CHROMA_DIR` | Defino los directorios locales del índice y de SQLite. |
| `OFFLINE_MODE`, `OPENAI_API_KEY`, `OPENAI_MODEL` | Controlo las integraciones con el proveedor de modelos. |

Separé las dependencias en `requirements.txt` (directas de ejecución), `requirements-dev.txt` (más `pytest`) y dos archivos de bloqueo generados con `uv pip compile --universal` para Python 3.11. La imagen Docker instala `requirements.lock` y la integración continua instala `requirements-dev.lock`.

## Datos generados

No versiono `data/app.db`, `data/chroma/` ni `data/dev_identity/`. Retiré del árbol los archivos de índice de `data/chroma/` que había versionado antes; siguen en el historial de Git, que no reescribí.

## Organización

- API: `app/main.py` y `app/api/v1.py`.
- Identidad: `app/auth/`.
- Casos de uso: `app/services/`.
- Contratos: `app/schemas/`.
- Repositorios: `app/data/`.
- Esquema y migraciones: `app/db/` y `migrations/`; contratos de planes en `app/schemas/plans_v1.py`.
- Dominio financiero: `app/finance/`.
- Motor de recomendaciones: `app/reasoning/` y `app/opportunity_engine/`.
- Recuperación: `app/rag/`.

## Verificación

Ejecuto `python -m pytest -q`. Con `TEST_DATABASE_URL` apuntando a PostgreSQL, la misma suite corre contra esa base. Con `PG_DOCKER_CONTAINER`, además verifica un backup y un restore reales con `pg_dump`/`pg_restore`. Los resultados de cada etapa están en [la auditoría](docs/AUDITORIA_PRODUCTO.md).

## Evolución

Dejé mis hallazgos en [la auditoría](docs/AUDITORIA_PRODUCTO.md) y mi estrategia en [el plan de producto](docs/PLAN_PRODUCTO.md). Distingo lo implementado de lo propuesto.
