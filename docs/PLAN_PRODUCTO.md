# Mi estrategia de producto

## Enfoque

Quiero transformar el prototipo en un planificador personal que convierta ingresos, gastos, deudas y metas en un plan mensual verificable. Mi promesa es: «Entiendo cuánto puedo destinar a mis metas, qué reserva debo conservar y cómo cambia mi plan si varían mis ingresos».

Propongo comenzar con profesionales de ingresos variables en Argentina que usan planillas y ahorran en ARS y USD. Es una hipótesis por cercanía para investigar, no demanda demostrada. Si encuentro mejor acceso y disposición a pagar en otro segmento, reviso el mercado antes de adaptar políticas.

## Validación del problema

En las primeras dos semanas entrevisto a 15 personas. Pregunto por su última decisión real, la herramienta que usan, tiempo invertido y qué pasó cuando cambió el ingreso. Evito basarme solo en respuestas sobre intención futura.

Busco al menos 8 relatos de un problema mensual y 5 personas dispuestas a probar después de resolver privacidad. Son criterios propuestos, no resultados. Presento una landing con ejemplo ficticio y lista de espera sin datos financieros. Si no encuentro dolor recurrente, cambio segmento o promesa antes de ampliar el software.

## Referencias y diferenciación

Consulté fuentes el 3 de octubre de 2026. YNAB ya ofrece presupuesto y [seguimiento de metas](https://www.ynab.com/features/goal-tracking). No considero que un chat o una barra de progreso sean ventaja suficiente.

| Alternativa | Ventaja que reconozco | Hipótesis que quiero validar |
|---|---|---|
| Planilla propia | Flexibilidad y hábito existente. | Reduzco mantenimiento y detecto errores de presupuesto. |
| Aplicación de presupuesto | Experiencia madura y seguimiento recurrente. | Resuelvo ingresos variables y contexto local con supuestos claros. |
| Herramienta conversacional general | Respuestas rápidas. | Mantengo estado y cálculos reproducibles. |
| Atención profesional | Criterio humano en casos complejos. | Facilito organización y seguimiento sin sustituirla. |

No hice investigación exhaustiva de competidores ni estimo tamaño de mercado sin datos.

## Alcance del primer producto

Incluyo cuenta segura, consentimiento, alta progresiva, moneda explícita, reserva elegida por la persona, deudas, metas y un presupuesto común. Entrego plan mensual, faltantes y hasta tres escenarios de ingreso, gasto y aporte. Permito registrar avance y revisar el mes siguiente.

Mantengo ARS y USD separados. Solo consolido con tipo de cambio explícito, fecha y procedencia; si falta o está vencido, no sumo monedas. No invento cotizaciones.

Empiezo con datos manuales. Agrego CSV después de validar el dominio, con vista previa, deduplicación, confirmación y reversión. Los documentos privados quedan fuera del piloto si no garantizo aislamiento y eliminación.

Dejo fuera ejecución de inversiones, recomendaciones personalizadas de instrumentos, integraciones bancarias, trading, cripto, aplicación nativa y predicción de rendimientos. Puedo responder preguntas educativas sobre un corpus público curado con fecha y referencias.

## Experiencia

1. Explico el tratamiento de datos y ofrezco una demo ficticia.
2. Pido ingreso, gasto, reserva y una meta; permito completar el resto después.
3. Muestro situación, aporte posible y próxima acción.
4. Explico fórmulas, supuestos, faltantes y fecha en «Cómo lo calculé».
5. Comparo escenarios sin sobrescribir el plan; confirmo su adopción.
6. Registro avance mensual y comparo con el plan anterior.

Uso castellano claro, importes con moneda, teclado, foco, contraste y diseño móvil. Distingo desconocido de cero y doy estados de carga, error, vacío y resultado vencido.

## Arquitectura objetivo

Conservo FastAPI modular y cálculo puro, independiente de red. Propongo React, TypeScript y Vite para la aplicación autenticada; una landing estática es suficiente inicialmente. No necesito renderizado de servidor para el recorrido personal.

Uso PostgreSQL para perfiles, metas, planes y eventos mínimos. Integro identidad gestionada y verifico firma, emisor, audiencia y expiración en el backend. Derivo propiedad de la sesión; aíslo todas las consultas. Si agrego políticas de fila, pruebo también conexiones que puedan eludirlas.

Si habilito recuperación documental, evalúo consolidar vectores con pgvector mediante un ensayo frente a Chroma. Separo corpus público y privado. Para originales privados uso almacenamiento de objetos y URLs temporales autorizadas.

Despliego frontend estático y backend en un servicio persistente con TLS y base gestionada. Elijo proveedor tras verificar región, coste y transferencias de datos. No uso `/tmp` como persistencia. No introduzco microservicios ni Kubernetes para el piloto.

## Dominio y API

Modelo propietario, snapshot, saldo, deuda, meta, presupuesto del periodo, plan, asignación, escenario y avance. Cada importe tiene Decimal y moneda. Cada conversión tiene tasa, fecha y origen. Registro si pagos mínimos ya están incluidos en gastos.

Separo capital actual e ingreso futuro. Reservo compromisos sin contabilizar dos veces fondos asignados a metas o emergencia. La imposibilidad de alcanzar una meta es un resultado válido. Retiro probabilidades y confianza sin calibración.

Versiono motor y políticas; guardo entradas mínimas que permitan reproducir cada plan. Diseño exportación y borrado, incluyendo índices y tratamiento de backups.

Propongo contratos `/v1/me`, `/v1/profile`, `/v1/goals`, `/v1/plans`, `/v1/scenarios` y exportación/borrado. Limito API anterior a demo local o la retiro: no dejo una ruta alternativa sin autorización.

## Generación y evaluación

No necesito entrenar un modelo para el lanzamiento. El dominio decide cantidades y prioridades; la generación explica el plan o responde preguntas educativas. Envío solo datos necesarios y valido salida estructurada. Si altera cifras, contradice el plan o inventa fuentes, uso plantilla.

Defino timeout, reintentos acotados, cuota por cuenta y apagado del proveedor sin inutilizar los cálculos. Creo 60 casos ficticios: límites financieros, múltiples metas, monedas, datos ausentes, preguntas sin evidencia, fallos e instrucciones maliciosas.

Exijo cero accesos cruzados y cero violaciones de presupuesto en pruebas. Propongo al menos 95% de afirmaciones comprobables respaldadas en el conjunto educativo y abstención en todos los casos preparados sin evidencia. Reporto denominadores y límites; no considero que un conjunto pequeño pruebe seguridad general.

## Privacidad y alcance comercial

Para Argentina tomo como referencia [derechos explicados por la AAIP](https://www.argentina.gob.ar/aaip/datospersonales/derechos) y [Ley 25.326](https://www.argentina.gob.ar/normativa/nacional/64790/texto). Antes del piloto identifico finalidad, proveedores, transferencias, retención y derechos. Solicito revisión profesional del tratamiento concreto; una pantalla no acredita cumplimiento.

La CNV describe participantes autorizados en sus [registros públicos](https://www.argentina.gob.ar/cnv/registros-publicos). Infiero que debo revisar profesionalmente cualquier futura recomendación personalizada de instrumentos. No considero suficiente llamarla educativa si su comportamiento es asesoramiento.

No vendo datos financieros ni incorporo comisiones por instrumentos a la primera hipótesis de ingresos.

## Roadmap

Estimo 12 a 16 semanas de dedicación principal para una beta pagada pequeña, sujeto a investigación y revisión legal. Avanzo por comprobaciones, no solo por fechas.

| Etapa | Tiempo orientativo | Trabajo | Condición de salida |
|---|---|---|---|
| Investigación y contención | Semanas 1–2 | Entrevistas, alcance, inventario público y fallback de fragmentación. | Evidencia del problema y ningún dato privado conocido en artefactos públicos. |
| Núcleo financiero | Semanas 2–4 | Decimal, monedas, reservas, presupuesto y escenarios. | Invariantes aprobadas y probabilidades sin calibrar retiradas. |
| Identidad y datos | Semanas 4–6 | Cuenta, autorización, PostgreSQL, migraciones, exportación y borrado. | Aislamiento y restauración comprobados. |
| Experiencia | Semanas 6–8 | Alta, plan, escenarios y revisión mensual. | Al menos 5 de 6 participantes completan plan sin ayuda. |
| Explicación y operación | Semanas 8–10 | Evaluación, cuotas, observabilidad y fallback. | Sin contradicciones críticas y rollback probado. |
| Piloto y cobro | Semanas 10–16 | 20–30 participantes, cohortes, precio y pagos. | Uso recurrente, cobros comprobados y operación apta. |

Si falla seguridad o cálculo, pospongo datos reales. Si falla investigación, reviso enfoque antes de ampliar.

## Adquisición, precio y economía

Recluto desde comunidades de profesionales independientes, contactos y contenido de planificación. Busco 2 o 3 comunidades accesibles y realizo sesiones individuales; no presupongo acuerdos.

Pruebo demo gratuita y plan personal con historial y escenarios. Experimento con equivalentes a USD 5, 8 y 12 mensuales, con cobro local y condiciones claras. Son hipótesis propias, no precios de mercado comprobados. Resuelvo medio de pago e impuestos antes de cobrar.

Mido hosting, base, almacenamiento, generación, comisiones, soporte, impuestos y devoluciones. Como ejemplo, USD 8 de ingreso menos USD 2 variables deja USD 6 de contribución: USD 120 fijos requieren 20 cuentas para infraestructura, sin remunerar mi trabajo ni adquisición. No lo presento como rentabilidad.

Evito chat ilimitado. Si el margen no alcanza, reduzco llamadas, reviso precio o retiro funcionalidades costosas.

## Métricas

Mi métrica principal es personas que revisan el plan y registran avance de una meta durante el mes.

| Métrica | Definición | Umbral inicial propuesto |
|---|---|---|
| Activación | Perfil mínimo y primer plan guardado en 24 h desde registro. | 60% del piloto. |
| Tiempo a valor | Mediana de inicio de alta a primer plan válido. | Menos de 5 minutos. |
| Retención a 30 días | Activados que revisan o actualizan entre días 25 y 35. | 40%, con denominador explícito. |
| Acción registrada | Activados que registran aporte o avance en 30 días. | 30%. |
| Pago | Activados que pagan el precio ofrecido en piloto comercial autorizado. | Al menos 5; no confundo intención con cobro. |
| Integridad | Violaciones de presupuesto o mezcla monetaria sin conversión. | Cero. |

No considero que una cohorte pequeña demuestre ajuste al mercado. Ante baja retención investigo resultado, hábito y confianza antes de comprar tráfico.

## Operación y lanzamiento

Registro errores y latencias sin perfiles o documentos completos; mido coste por explicación. Propongo p95 menor a 2 s para cálculo y 10 s para explicación, con carga representativa. Son objetivos, no resultados actuales.

Antes de cobrar verifico TLS, secretos fuera de Git, permisos, backup y restore. Propongo RPO de 24 h y RTO de 4 h para el piloto y ensayo si los cumplo. Documento incidentes, soporte, cancelación y reembolsos.

Mi próxima decisión es validar segmento mientras corrijo el núcleo. Una interfaz nueva no alcanza: necesito cálculo correcto, privacidad comprobada y uso repetido.
