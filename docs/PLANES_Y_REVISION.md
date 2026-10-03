# Planes, escenarios y revisión mensual

Describo las reglas que implementé para versionar planes, simular escenarios, registrar avances y revisar el mes. No ejecuto operaciones financieras ni me conecto con bancos.

## Versiones de plan

Cada cuenta tiene un solo plan vigente (`active`). Las demás versiones quedan como `superseded`. Calcular un plan (`POST /v1/plans`) o adoptar un escenario crea una versión nueva con número correlativo y marca la anterior como reemplazada en la misma transacción. Nunca edito una versión existente.

Cada versión guarda:

- **Snapshot mínimo (`PlanSnapshotV1`):** monedas, flujos, saldos, deudas, compromisos, meses de reserva y metas. Reemplazo los nombres de activos, deudas y compromisos por etiquetas (`asset-1`) y omito país y tolerancia al riesgo, que el cálculo no usa.
- **Fecha del cálculo, versión de la política y versión del motor** (`ENGINE_VERSION` en `app/finance/__init__.py`).
- **Resultado (`PlanResultV1`):** presupuestos, asignaciones, restricciones, supuestos, datos faltantes y escenarios de referencia.
- **Huella de las entradas:** permite avisar cuando el plan quedó desactualizado.

Guardo snapshot y resultado como JSON, pero los valido contra modelos Pydantic cerrados al escribir y al leer. Un campo que no está en el contrato es un error.

`GET /v1/plans/{id}/reproduction` recalcula el plan desde su snapshot y lo compara con el resultado guardado. Si cambió la versión de la política o del motor, informo que no puedo reproducirlo con el motor actual. No uso una versión distinta en silencio.

Los planes creados antes de esta etapa quedan como versiones `legacy`: muestro sus datos básicos, pero no son reproducibles porque no guardaban entradas.

## Plan desactualizado

`GET /v1/plans/current` devuelve el plan vigente y `freshness` con estos motivos:

- `inputs_changed`: cambiaron el perfil, las metas o los avances registrados.
- `policy_changed` o `engine_changed`: cambió la versión de la política o del motor.
- `legacy_plan`: el plan vigente no guarda entradas.

Un plan desactualizado no se recalcula solo. La persona decide si crea una versión nueva.

## Escenarios

`POST /v1/scenarios` aplica cambios de ingreso, gasto y rendimiento (en fracciones; -0.2 es una caída de 20%) sobre el snapshot de un plan concreto. El resultado incluye la comparación con ese plan por moneda y por meta. Simular no modifica el plan.

`POST /v1/scenarios/{id}/adoption` es la única forma de llevar un escenario al plan. Crea una versión nueva con el mismo snapshot más los parámetros del escenario. Las restricciones son:

- Si el plan base ya no está vigente, respondo 409 `plan_superseded`: hay que simular de nuevo sobre el plan actual.
- Un escenario se adopta una sola vez.
- Adoptar no cambia el perfil de la persona, solo las hipótesis del plan.

## Avances sin doble conteo

`POST /v1/progress` registra un aporte a una meta en un mes, en la moneda de la meta. `source` indica de dónde salió el dinero:

- `monthly_surplus`: dinero nuevo del excedente.
- `existing_balance`: dinero que ya figuraba en los saldos declarados.

Un aporte se cuenta una sola vez:

1. Suma al ahorro de su meta mientras la persona no actualice el ahorro declarado de esa meta. Cuando lo cambia (`PUT /v1/goals/{id}` con otro `saved`), asumo que el valor nuevo ya incluye los aportes registrados hasta ese momento.
2. Si salió del excedente, también suma al saldo líquido como «aporte no conciliado» mientras la persona no actualice los saldos del perfil. Así el saldo libre no baja por un dinero que en realidad entró.
3. Si salió de un saldo ya declarado, no agrego liquidez: el dinero solo cambia de destino y el saldo libre baja.

## Revisión mensual

`GET /v1/reviews/{YYYY-MM}` compara, por meta, el aporte mensual previsto en el plan vigente con lo registrado ese mes. Los estados son:

- `met`, `partial` o `not_recorded`, cuando el plan preveía un aporte.
- `not_planned` o `extra`, cuando el plan no preveía aporte.
- `not_in_plan`, para metas creadas después del plan.

La respuesta incluye totales por moneda y el estado de actualización del plan.

## Idempotencia

Crear planes, escenarios, adopciones y avances exige el encabezado `Idempotency-Key` (8 a 128 caracteres):

- Un reintento con la misma clave y el mismo cuerpo devuelve el recurso original con `Idempotent-Replayed: true`.
- La misma clave con otro cuerpo devuelve 422 `idempotency_key_reused`.
- Las claves son por cuenta y se conservan 7 días.
- Guardo la clave en la misma transacción que el recurso, de modo que reintentos simultáneos crean un solo recurso.

## Paginación y errores

Los listados devuelven `{items, next_cursor}`, con un máximo de 50 elementos por página y un cursor opaco.

Los errores de estas rutas incluyen `detail` y un `code` estable: `profile_required`, `plan_superseded`, `scenario_already_adopted`, `plan_active`, `currency_mismatch`, `future_period`, `invalid_cursor`, `idempotency_key_required`, `idempotency_key_invalid`, `idempotency_key_reused` y `not_found`.
