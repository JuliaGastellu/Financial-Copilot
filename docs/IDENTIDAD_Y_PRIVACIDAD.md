# Identidad, aislamiento y privacidad

Describo lo que implementé en esta etapa y lo que todavía falta. No desplegué el servicio ni lo conecté a un proveedor de identidad real. Lo verifiqué con dobles locales, SQLite y PostgreSQL 16 en Docker.

## Contrato de identidad

Elegí OpenID Connect con tokens de acceso JWT firmados por el proveedor y enviados como `Authorization: Bearer <token>`. Es el contrato que ofrecen los proveedores gestionados habituales, como Auth0, Microsoft Entra ID, Amazon Cognito, Keycloak o Zitadel. Por eso no ato el código a un SDK propietario. Elijo el proveedor concreto después de comparar región, costo y transferencias de datos, como indica el plan.

En `app/auth/tokens.py` verifico:

- **Algoritmo:** acepto solo algoritmos asimétricos de una lista permitida (por defecto RS256). Rechazo `none` y HS256, incluso si alguien los agrega a la configuración, y así evito la confusión entre clave pública y secreto.
- **Firma:** uso la clave pública del JWKS del emisor que corresponde al `kid` del encabezado. Sin `kid`, rechazo el token.
- **Claims:** exijo `iss` igual al emisor configurado, `aud` con la audiencia de esta API, y `exp`, `iat` y `sub`. Valido `nbf` si está presente. Tolero 30 segundos de desfase de reloj y rechazo tokens emitidos hace más de una hora.
- **Rotación de claves:** cacheo el JWKS 10 minutos. Si llega un `kid` desconocido, recargo como máximo cada 30 segundos, para que tokens falsos no multipliquen las descargas. Una clave retirada deja de valer cuando vence la caché.

El propietario sale solo del par (`iss`, `sub`), que asocio a un UUID interno en la tabla `users`. Las rutas v1 no tienen identificadores de persona en la URL, y los cuerpos rechazan campos desconocidos. Un `user_id`, `owner_id`, `sub` o `subject` en el cuerpo devuelve 422. Ignoro encabezados como `X-User-Id` y parámetros de consulta.

Requisitos para elegir proveedor: que emita tokens de acceso JWT (no opacos) con una audiencia propia para esta API y publique un JWKS por https.

Para desarrollo local, `scripts/dev_identity.py` genera claves en `data/dev_identity/`, que no se versiona, y emite tokens. Producción rechaza un JWKS por `file:` o por http.

## Aislamiento

- **Consultas:** cada consulta sobre datos personales incluye `user_id = :owner` en el WHERE (`app/data/accounts.py`). Un recurso ajeno responde igual que uno inexistente: 404 con `Not found.`.
- **Base de datos:** las claves foráneas usan `ON DELETE CASCADE` hacia `users`. Las restricciones `CHECK` impiden importes negativos, prioridades inválidas y plazos fuera de rango.
- **Pendiente:** no agregué políticas de fila de PostgreSQL (RLS). El aislamiento depende de la capa de repositorios y de las pruebas de la matriz de acceso.

## Documentos

Dejé los documentos privados fuera de esta etapa:

- Eliminé la ingesta por HTTP. El corpus público curado se carga con `scripts/ingest_public_corpus.py`.
- Las tablas `documents` y `chunks` solo admiten `corpus = 'public'`, por una restricción de base de datos.
- La recuperación filtra el corpus dentro de la búsqueda vectorial y de la consulta SQL alternativa, no después de recuperar.
- `/v1/knowledge/query` exige un token, pero no usa el perfil ni datos de la cuenta.

## Almacenes y borrado

| Almacén | Datos personales | Tratamiento al borrar la cuenta |
|---|---|---|
| Base relacional: `users`, `profiles`, `goals`, `plans`, `scenarios`, `progress_entries`, `idempotency_keys` | Sí | Borro todo en una transacción y verifico que no quede ninguna fila antes de confirmar. |
| `audit_events` | UUID interno, acción, tipo y resultado; sin importes ni textos | Los conservo hasta `AUDIT_RETENTION_DAYS` (365). Tras el borrado no queda vínculo entre ese UUID y la identidad. |
| `deletion_receipts` | HMAC de (`iss`, `sub`) con `PRIVACY_HASH_KEY`, fecha y conteos | Los conservo mientras pueda existir un backup anterior al borrado: `BACKUP_RETENTION_DAYS` + 30 días. |
| Índice vectorial (Chroma) | No: solo corpus público | No aplica. |
| Logs de aplicación | UUID interno, ruta, estado y duración; nunca contenido del perfil, metas o planes | Siguen la retención del proveedor de logs, que todavía no elegí. |
| Backups | Sí, hasta que expiran | Después de cada restore reaplico los borrados (ver más abajo). |

`DELETE /v1/me` devuelve un recibo con la evidencia por almacén: filas borradas, filas restantes (siempre cero) y el tratamiento de índice, auditoría, logs y backups. Si la persona vuelve a iniciar sesión, obtiene una cuenta nueva y vacía.

`GET /v1/me/export` devuelve en JSON la cuenta, el perfil, las metas, los planes con sus entradas, los escenarios, los avances y los eventos de auditoría propios.

## Retención

`python scripts/privacy_maintenance.py retention` aplica estos plazos:

- Borra las versiones de plan reemplazadas con más de `PLAN_RETENTION_DAYS` (730) y sus escenarios. Nunca borra el plan vigente.
- Borra las claves de idempotencia con más de 7 días.
- Borra los eventos de auditoría con más de `AUDIT_RETENTION_DAYS` (365).
- Borra los recibos que ya no cubren ningún backup.

El perfil y las metas se conservan hasta que la persona los borra. Todavía no definí qué hacer con cuentas inactivas.

## Backups y restore

El procedimiento ante un restore es:

1. Exportar los recibos de la base vigente: `python scripts/privacy_maintenance.py export-receipts --out receipts.json`.
2. Restaurar el backup (`pg_restore`) y aplicar migraciones (`python scripts/migrate.py upgrade`).
3. Reaplicar los borrados: `python scripts/privacy_maintenance.py reapply-deletions --receipts receipts.json`.

Al reaplicar, solo borro cuentas creadas antes del borrado registrado: si la persona volvió a registrarse después, no toco la cuenta nueva.

Lo verifiqué con una prueba automatizada en PostgreSQL 16 (`pg_dump -Fc` y `pg_restore` dentro del contenedor) y con otra en SQLite. Todavía no definí la frecuencia ni el almacenamiento de los backups de producción, ni ensayé RPO y RTO.

## Configuración de producción

Con `ENVIRONMENT=production` la aplicación se niega a arrancar si:

- `DATABASE_URL` no apunta a PostgreSQL;
- `OIDC_ISSUER` u `OIDC_JWKS_URL` no usan https, o falta `OIDC_AUDIENCE`;
- hay algoritmos simétricos;
- falta `PRIVACY_HASH_KEY` o tiene menos de 32 caracteres;
- algún origen de `ALLOWED_ORIGINS` no es https explícito;
- el rate limiting está apagado;
- `AUTO_MIGRATE` está activo.

En producción también oculto `/docs` y `/openapi.json`. CORS no habilita credenciales, porque uso tokens en encabezado y no cookies, y solo permite los encabezados `Authorization`, `Content-Type` y `X-Request-ID`. En local y test rechazo el comodín `*`.

## Pendiente

- Elegir proveedor de identidad y probar contra su JWKS real.
- Políticas de fila (RLS) como segunda barrera.
- Rate limiting compartido entre procesos: hoy se guarda en memoria.
- Logs centralizados con su propia retención.
- Revisión profesional del tratamiento de datos.
