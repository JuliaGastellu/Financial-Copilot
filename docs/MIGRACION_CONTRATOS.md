# Migración de contratos: núcleo financiero

Describo los cambios de contrato que introduje al reemplazar las estimaciones anteriores por el dominio de `app/finance/`. No necesité migrar el esquema SQL: perfiles y decisiones se guardan como JSON y los campos nuevos son opcionales.

## Perfiles (`PUT /profiles/{user_id}`)

Mantengo compatibilidad con los perfiles existentes. Todos los campos nuevos son opcionales:

| Campo | Uso |
|---|---|
| `currency` | Moneda base ISO 4217. Si falta, uso `preferences.currency` y después USD; el plan lo informa como supuesto. |
| `cashflow.currency` | Moneda del flujo principal. Si falta, uso la moneda base. |
| `cashflow.minimum_payments_included_in_expenses` | `true` si los pagos mínimos ya están en los gastos. Si falta, los sumo a las salidas y lo informo como supuesto. |
| `additional_cashflows` | Ingresos y gastos en otras monedas; uno por moneda. |
| `assets[].currency`, `liabilities[].currency`, `goals[].currency` | Moneda de cada importe; por defecto, la base. |
| `commitments` | `monthly` resta del flujo mensual; `reserved_balance` aparta saldo actual. |
| `emergency_reserve_months` | Meses de salidas que la persona quiere reservar (0 a 24). Si falta, uso 3 y lo informo. |

Validaciones nuevas: rechazo NaN e infinitos con 422 y valido códigos de moneda de tres letras. El 422 ya no devuelve el valor recibido. Ahora guardo `target_date` en formato ISO; antes el guardado fallaba al serializar fechas.

## Plan (`GET /plans/{user_id}`, nuevo)

Devuelvo el plan completo: presupuesto por moneda, asignaciones, metas, restricciones con su efecto, supuestos, datos faltantes y tres escenarios determinísticos. Expreso cada importe como `{"amount": "<decimal>", "currency": "<ISO>"}`. El endpoint tiene límite de solicitudes (`RATE_LIMIT_PLANS`, por defecto `20/minute`).

## Recomendaciones (`POST /recommendations`)

| Antes | Ahora |
|---|---|
| `impacted_goals[].probability_of_success` y `confidence` | Eliminados. Cada meta informa `status`, `monthly_allocation`, `required_monthly`, `shortfall_monthly`, `months_to_goal` y `months_left`. |
| `projected_impact.time_delta` y `confidence` | Eliminados. `projected_impact` contiene `explanation`, `assumptions` y `missing_data`. |
| Las mismas metas y el mismo aporte se repetían en cada recomendación. | Solo la recomendación con `plan_action: "goals"` lista metas; los importes salen de un único presupuesto. |
| `suggested_amount` calculado por título o como 10% del capital. | Solo las acciones del plan (`emergency_reserve`, `high_apr_debt`, `goals`) tienen importe. |
| — | `allocation_kind`: `simultaneous` (suman dentro del excedente), `alternative` (entradas del catálogo, excluyentes entre sí y sin importe) o `informational`. |
| `decision_context.available_capital` sumaba activos de liquidez alta y media más un mes de excedente. | Es el saldo actual de liquidez alta no asignado, después de compromisos, ahorros de metas, reserva, deuda de tasa alta y metas. Agrego `available_capital_currency`. |
| — | `decision_context.plan` contiene el plan completo, `policy_version` y `as_of`. |

Cuando habilito el modelo de lenguaje, solo acepto `title`, `rationale`, `actions` y `risks` de su respuesta. Las acciones con importe siempre salen del plan.

## Métricas (`metrics`)

Siguen siendo números para no romper clientes, ahora calculados desde el plan en la moneda base:

- Quité `debt_to_income_ratio`: dividía el saldo total por el ingreso mensual y lo comparaba con umbrales de carga mensual. Lo reemplazo por `debt_balance_to_monthly_income`, en meses de ingreso y sin umbral.
- `liquid_assets` solo incluye liquidez alta.
- `free_cashflow` es el excedente mensual después de gastos, pagos mínimos no incluidos y compromisos mensuales.
- `emergency_fund_months` usa liquidez alta no reservada ni ahorrada para metas, dividida por las salidas mensuales.
- Agrego `currency`, `monthly_outflow`, `debt_to_assets_ratio` y `metric_units`.

## Restricciones

Cada restricción incluye `currency`, `effect` y `blocks_new_investment`. Quité `high_debt_to_income_ratio`. Agregué `zero_income`, `commitments_exceed_liquid_balance`, `goal_shortfall` y `goal_currency_without_income`. Mantengo el identificador `insufficient_emergency_fund`.

## Consultas (`POST /query`)

Eliminé `confidence`: era una constante (0,35, 0,15, 0,3 o 0,12) o un valor propuesto por el modelo, sin calibración.

## Decisiones guardadas (`GET /decisions/{user_id}`)

No reescribo registros anteriores. Al leerlos quito `probability_of_success` y `confidence` en cualquier nivel y agrego `decision_context.legacy_indicators_removed`. Esos registros conservan el resto de su contenido, incluido el capital calculado con la regla anterior.

## Catálogo de oportunidades

Uso el mismo capital disponible que el plan. Rechazo instrumentos cuando hay una restricción bloqueante en su moneda (`blocked_by_constraint:<id>`) o cuando el plan no tiene presupuesto en esa moneda. Los pesos de puntaje no cambiaron.
