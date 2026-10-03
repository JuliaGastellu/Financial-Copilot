# Auditoría de mi producto

## Alcance y conclusión

Revisé el repositorio local vinculado a `JuliaGastellu/Financial-Copilot` el 3 de octubre de 2026: API, configuración, persistencia, cálculo financiero, catálogo, recuperación documental, generación, interfaz, pruebas, contenedores, integración continua y documentación. No comparé el checkout con el remoto ni inspeccioné un servicio desplegado. No hice una prueba de penetración, una revisión completa del historial de Git ni una validación con usuarios.

Tengo un prototipo técnico útil, pero todavía no un servicio comercial listo. Mi mayor activo es la separación entre dominio financiero, repositorios y casos de uso. Mi principal riesgo es presentar resultados con una precisión y seguridad que el código aún no sostiene.

Distingo hallazgos de lectura, reproducciones directas e hipótesis pendientes. No asigno porcentajes de preparación sin medición.

## Hallazgos priorizados

Uso P0 para bloqueantes antes de recibir datos reales de terceros; P1 para requisitos del piloto; P2 para mejoras posteriores.

| Prioridad | Evidencia que encontré | Consecuencia | Corrección que propongo |
|---|---|---|---|
| P0 | `app/main.py` acepta `user_id` del cliente sin autenticación en perfiles, consultas, recomendaciones e historial. | Un cliente que conoce un identificador puede acceder o modificar información ajena. | Derivo el propietario de una sesión verificada y pruebo accesos cruzados. |
| P0 | `documents` y `chunks` no tienen propietario en `app/data/sqlite.py`; `retrieve()` no filtra por usuario. | Los documentos cargados pueden aparecer en respuestas de otra persona. | Separo corpus público y privado; autorizo recuperación vectorial y alternativa SQL. |
| P0 | `impact.py` y `evaluation.py` suman activos de liquidez alta/media y un mes de excedente como capital disponible. | Incluyo reservas y flujo futuro como capital invertible actual. | Distingo saldo actual, compromisos, reserva y aportes mensuales. |
| P0 | `_impacted_goals()` reutiliza el aporte para cada meta; las cantidades sugeridas tampoco respetan un presupuesto conjunto. | Asigno más dinero del disponible. | Creo un único plan; distingo alternativas excluyentes de acciones acumulables. |
| P0 | Uso `float` y los flujos, activos, deudas y metas no tienen moneda propia. | No sostengo cálculos multimoneda ni redondeos contables consistentes. | Uso Decimal y moneda explícita; rechazo sumas sin conversión verificable. |
| P0 | `probability_of_success` suma constantes en `impact.py`; la confianza depende de prioridad o de la salida del modelo. | Presento heurísticas como indicadores estadísticos. | Sustituyo probabilidades por escenarios y calidad de datos; calibro antes de restaurarlas. |
| P0 | `generate_recommendations()` y `generate_query_result()` aceptan recomendaciones del modelo. | La generación introduce decisiones financieras no validadas, contrario al README anterior. | El dominio produce el plan tipado; el modelo solo explica resultados autorizados. |
| P0 | Git contiene cuatro binarios en `data/chroma/`; la exclusión existente apunta a `data/chroma_db/`. | Puedo publicar derivados de documentos; desconozco su contenido. | Inspecciono procedencia en privado, retiro artefactos del versionado y evalúo el historial. No afirmo una filtración sin evidencia. |
| P0 | El fallback de `chunk_text()` vuelve a `end - overlap` incluso al alcanzar el final. | Si falla el divisor principal, repito indefinidamente el último fragmento. | Corto al alcanzar el final y pruebo esta rama con timeout. |
| P1 | `Settings` solo admite `local` y `test`; CORS admite `*` con credenciales. | Me falta configuración segura de producción. | Agrego entornos y orígenes explícitos; no confundo CORS con autorización. |
| P1 | Perfiles e historial no tienen límites de uso; ingesta no limita longitud; `limit` no está acotado. | Puedo consumir recursos sin control. | Limito bytes, fragmentos, paginación, cuota y concurrencia. |
| P1 | `retrieve()` retorna un candidato aunque ninguno supere el umbral; transforma distancia con `1/(1+d)`. | Puedo citar contexto irrelevante. | Evalúo relevancia y abstención según la métrica del índice. |
| P1 | `validate_citations()` comprueba identificador y deduplicación; adjunto las mismas fuentes a varias recomendaciones. | Una fuente existente puede no justificar una afirmación. | Vinculo afirmaciones a fragmentos autorizados y separo reglas de evidencia documental. |
| P1 | Perfil, consulta y contexto van en un único prompt, sin evaluación de instrucciones maliciosas en documentos. | El contexto puede alterar la respuesta. | Trato documentos como datos no confiables, minimizo entradas y valido contra el plan. |
| P1 | Persisto documento y fragmentos antes de indexar, en commits separados. | Un fallo deja ingesta parcial y reintentos duplicados. | Agrego estado de ingesta, idempotencia y reconciliación. |
| P1 | No versiono explícitamente modelo y dimensión en el ciclo del índice. | Alternar embeddings hash y del proveedor puede dejar incompatibilidades. | Versiono índices y reconstruyo sin sobrescribir el activo. |
| P1 | El catálogo incluye fecha pero no aplica vigencia; requisitos de acceso son texto. | Muestro datos vencidos o instrumentos inaccesibles. | Mantengo demo separada; luego verifico vigencia, acceso, costes y disponibilidad. |
| P1 | Detecto restricciones pero no todas bloquean oportunidades; uso APR fijo de 12%. | Detectar falta de reserva o deuda no garantiza una decisión prudente. | Defino políticas y pruebas donde cada restricción cambie la decisión. |
| P1 | `debt_to_income_ratio` divide saldo total por ingreso mensual y usa umbrales 0,4/0,6. | Confundo unidades con carga mensual de deuda. | Distingo saldo/ingreso, meses de ingreso y servicio de deuda. |
| P1 | Docker usa dos workers con almacenamiento local; Compose define variables que `Settings` no consume; Vercel usa `/tmp/data`. | Persistencia durable y concurrencia quedan pendientes. | Uso base gestionada y backend persistente; pruebo restauración. |
| P1 | La suite trabaja mayormente offline y varias pruebas de impacto solo verifican campos. | Puedo aprobar estructuras con cálculos incorrectos. | Pruebo invariantes, casos adversos, generación simulada y aislamiento. |
| P1 | Dependencias con mínimos abiertos y sin versiones resueltas. | No garantizo reproducibilidad. | Fijo versiones probadas y verifico instalación limpia. |
| P1 | No encuentro consentimiento, exportación, borrado, sesiones ni retención. | No tengo operación adecuada de datos personales. | Implemento estos flujos para todos los almacenes y proveedores. |
| P2 | UI en inglés, selector de identificadores, detalles técnicos y scripts inline junto a un archivo extenso. | El recorrido se parece a una consola de demostración. | Diseño alta, plan y revisión mensual con una sola fuente de comportamiento. |
| P2 | Encuentro numerosos `innerHTML`, pero también escape explícito de muchas interpolaciones. | Necesito verificar fronteras, sin afirmar XSS solo por usar esa API. | Renderizo de forma segura y pruebo entradas y enlaces adversos en navegador. |
| P2 | Guardo resultados históricos sin paquete completo de versiones y entradas. | No garantizo reproducción de decisiones anteriores. | Registro snapshot mínimo, políticas, supuestos y versión del motor. |
| P2 | No encuentro medición de activación, retención o pago. | No tengo evidencia de demanda. | Investigo y mido cohortes y acciones realizadas. |

## Verificación que pude realizar

Validé la sintaxis de 46 archivos Python de `app/`, `tests/` y `scripts/`. Eso no verifica imports ni integración.

Ejecuté directamente métricas e impactos. Con ingreso 7.000, gasto 4.500, activo líquido 8.000 y tres metas obtuve capital estimado 10.500 y aportes totales de 3.750, frente a excedente mensual de 2.500. También obtuve una probabilidad aproximada de 0,70 calculada por constantes.

Intenté ejecutar la suite. `python` no estaba en PATH, un intérprete alternativo no pudo iniciarse y el runtime accesible no tenía `pytest`. No instalé dependencias; no reporto pruebas aprobadas.

No ejecuté Docker ni hice QA visual. No inspeccioné el contenido binario de Chroma ni secretos en todo el historial. No afirmo que los binarios contengan datos personales. Estos controles siguen pendientes.

## Cobertura que quiero agregar

1. Pruebo usuario A contra recursos de B en API, documentos, SQL alternativo, trabajos de ingesta, historial, exportación y borrado.
2. Verifico presupuesto conjunto, reserva, fondos comprometidos y pagos de deuda sin doble descuento.
3. Pruebo cero ingresos, déficit, meta cumplida, fecha vencida, retornos negativos, más de tres metas y cantidades grandes.
4. Pruebo monedas distintas, tipos de cambio ausentes o vencidos, redondeo y valores no finitos.
5. Simulo fallo del proveedor, JSON inválido, recomendaciones contradictorias, falta de contexto e instrucciones maliciosas.
6. Verifico reintentos idempotentes, ingesta parcial, borrado de embeddings y restauración de backup.
7. Observo alta, plan, simulación y actualización mensual en móvil y escritorio.

## Decisión técnica

Conservo FastAPI, módulos de dominio, repositorios y pruebas de contratos. Corrijo cálculo y privacidad antes de reemplazar la experiencia web. No necesito infraestructura distribuida para validar el primer producto.

Mi secuencia está en [PLAN_PRODUCTO.md](PLAN_PRODUCTO.md). Los hallazgos describen trabajo pendiente; esta revisión no corrige el comportamiento de la aplicación.

## Estado tras la etapa de contención

Conservo los hallazgos anteriores como registro de la revisión. En esta etapa corregí solo lo siguiente:

- **Fallback de `chunk_text()`.** Reproduje el bucle con el divisor principal indisponible: un texto de 899 o 900 caracteres no terminaba. Extraje `split_fixed_window()`, que corta al alcanzar el final y siempre avanza. Pruebo texto vacío, solo espacios, menor, exacto, largo, solapamiento y valores inválidos en procesos aislados con tiempo máximo; con el código anterior esas pruebas fallaban por timeout.
- **Binarios de `data/chroma/`.** Agregué la exclusión correcta y retiré los cuatro archivos del árbol actual sin borrar las copias locales ni reescribir el historial. Inspeccioné solo metadatos: el encabezado del índice declara 768 dimensiones, coherentes con las representaciones hash, y 0 elementos; el buffer de 321.200 bytes tiene 43 bytes distintos de cero. No encontré indicios de texto o vectores de documentos, pero no lo afirmo como prueba de ausencia.
- **Compose.** Uso `DATA_DIR`, `SQLITE_PATH` y `CHROMA_DIR`, que `Settings` sí consume, y agregué `.env.example` sin claves. Una prueba compara ambos archivos con los campos de `Settings`.
- **Dependencias.** Fijé versiones directas, separé dependencias de pruebas y agregué locks para Python 3.11. Con una instalación limpia obtuve 46 pruebas aprobadas.

Busqué en todo el historial local patrones habituales de claves (proveedor de modelos, nube, tokens de GitHub y claves privadas) y no obtuve coincidencias. No encontré motivos para rotar secretos. El commit con los binarios ya está en el remoto; si el repositorio es o fue público, evalúo una revisión del historial publicado, aunque los metadatos no indican contenido documental.

Siguen pendientes los demás hallazgos P0 y P1, incluidos autenticación, aislamiento de documentos, cálculo de capital y presupuesto, Decimal y moneda, probabilidades heurísticas y el uso del modelo de lenguaje para decidir recomendaciones.

Después construí la imagen Docker sin errores y la levanté en modo offline: `/health` respondió 200 y el chequeo de salud quedó en `healthy`. Eso no resuelve la persistencia durable ni el uso de dos workers con almacenamiento local.
