# Explicación segura y recuperación educativa

Describo lo que implementé para explicar planes con un proveedor de texto sin que tome decisiones, y para responder preguntas educativas solo con el corpus público curado. También incluyo cómo lo evalué y qué límites encontré.

## Explicación de planes

`POST /v1/plans/{id}/explanation` explica un plan ya calculado. Solo puede pedirla la persona dueña del plan, y la ruta tiene límite de solicitudes.

- **Interfaz desacoplada** (`app/explain/provider.py`): tiene un proveedor deshabilitado (por defecto) y otro compatible con la API de chat de OpenAI, que usa salida JSON, temperatura 0, timeout y límite de tokens de salida. El cálculo del plan no depende de esta interfaz.
- **Datos que se envían** (`app/explain/facts.py`): solo hechos del resultado del plan, cada uno con un identificador:
  - importes del presupuesto mensual;
  - estado y aportes de cada meta;
  - restricciones y próxima acción.

  Las metas viajan como `meta-1`, `meta-2`, y sus nombres reales se restituyen en el servidor después de validar. No se envían identificadores de la cuenta, nombres de activos o deudas, saldos detallados, texto libre de la persona ni documentos del corpus.
- **Salida tipada** (`app/explain/validation.py`): un resumen y hasta 6 puntos, cada uno con los hechos que cita. Rechazo la salida si:
  - no respeta el esquema;
  - cita hechos inexistentes;
  - un número no coincide con un hecho citado en el mismo punto (los montos positivos tampoco pueden aparecer con signo negativo);
  - nombra una moneda que no está entre los hechos citados;
  - le atribuye a una meta otra prioridad;
  - niega restricciones que el plan tiene;
  - menciona probabilidades, porcentajes, garantías, inversiones, compra o venta, préstamos o cambios al plan;
  - repite instrucciones dirigidas al sistema.
- **Plantilla determinística** (`app/explain/template.py`): produce la misma estructura a partir de los hechos, pasa la misma validación y se usa ante cualquier problema.
- **Controles** (`app/explain/service.py`), en este orden:
  - caché por plan, versión de instrucciones, proveedor y modelo;
  - cuota diaria por cuenta, en llamadas (20) y tokens (40.000);
  - estimación del tamaño de entrada (máximo 3.000 tokens);
  - timeout de 15 s;
  - hasta 2 reintentos con espera creciente, solo ante errores transitorios;
  - límite de 700 tokens de salida.

  Una salida que contradice el plan no se reintenta: se entrega la plantilla y se registra el motivo (`fallback_reason`).

La aplicación web muestra la explicación en «Cómo lo calculé» y aclara si el texto lo redactó el proveedor y fue verificado, o si es la explicación estándar.

## Recuperación educativa

`POST /v1/knowledge/query` responde con oraciones literales del corpus. No genera texto: cada afirmación lleva la cita del fragmento del que sale, con editor, fuente, fecha de publicación y vigencia.

- **Procedencia y vigencia:** cada documento exige editor, fuente, fecha de publicación, fecha de revisión y vigencia (`scripts/ingest_public_corpus.py`, con encabezado en el archivo). Solo recupero documentos aprobados y vigentes. La migración `0003` deja los documentos anteriores como pendientes y sin vigencia.
- **Instrucciones maliciosas:** los fragmentos con instrucciones dirigidas al sistema se guardan con una marca para auditoría, pero no se indexan ni se recuperan. Además, filtro esas oraciones al componer la respuesta. Como la respuesta es extractiva, un documento no puede cambiar el comportamiento del sistema.
- **Fuera de alcance:** los pedidos de recomendación personal de inversión terminan en abstención con `out_of_scope`.
- **Abstención sin evidencia:**
  - La búsqueda vectorial solo propone candidatos sobre un umbral de similitud coseno de 0,1. No devuelvo candidatos por debajo del umbral por obligación.
  - La decisión de responder es léxica: cada término de la pregunta pesa según su rareza en el corpus (IDF), y los términos que no aparecen en el corpus pesan al máximo.
  - Exijo que las oraciones elegidas cubran al menos el 60% de ese peso; si no, me abstengo.
  - Descarto palabras de formulación («cuál», «diferencia», «pasa») y el plural simple.
- **Filtros dentro de la consulta:** corpus, aprobación, vigencia y marcas se aplican en el índice vectorial (corpus y vigencia) y en SQL. Además confirmo en SQL cada fragmento que devuelve el índice.
- **Índices versionados:** cada combinación de modelo y dimensión de embeddings tiene su colección (`public-corpus-hash-v2-768`) y un registro en `vector_indexes`. Si el índice activo es de otro modelo, la ingesta se rechaza y la recuperación usa la búsqueda en SQL. `scripts/reindex_corpus.py` construye el índice del modelo configurado sin tocar el activo y lo activa al terminar.
- **Embedding local `hash-v2`:** pasa a minúsculas, quita tildes, descarta palabras vacías y el plural simple. Es una bolsa de palabras con hash: no capta sinónimos ni paráfrasis.

## Evaluación

Los casos están versionados en `evals/cases_v1.json`, con un corpus ficticio en `evals/corpus_v1/`:

- **30 casos educativos:**
  - 16 respondibles, cada uno con el documento que debe citar;
  - 8 sin evidencia en el corpus;
  - 4 pedidos de recomendación personal;
  - 1 tema que solo aparece en un documento vencido;
  - 1 tema que solo aparece en un documento con instrucciones maliciosas.
- **30 casos de explicación:** 10 perfiles ficticios con 22 guiones del proveedor simulado:
  - fiel y error transitorio que se recupera;
  - cifra alterada, cifra redondeada, cifra inventada, cifras de metas intercambiadas;
  - moneda equivocada, prioridad cambiada, restricciones negadas;
  - consejo de inversión, préstamo, probabilidad, porcentaje, garantía, eco de instrucciones;
  - JSON inválido, hecho inexistente, punto sin citas, tiempo agotado.

  17 de esos casos son críticos.

Ejecuto `python -m evals.run_eval` (proveedor simulado). `tests/test_eval_deterministic.py` corre lo mismo en CI y exige los criterios de salida. El modo `--mode real` usa el proveedor configurado, pero no lo ejecuté: no tengo una clave configurada y no usé servicios reales.

### Resultados del 3 de octubre de 2026, proveedor simulado

| Métrica | Resultado |
|---|---|
| Contradicciones entregadas en casos críticos | 0 de 17 |
| Contradicciones entregadas en total | 0 de 30 |
| Salida del proveedor aceptada / plantilla esperada | 13 aceptadas; 30 de 30 con la fuente esperada |
| Afirmaciones respaldadas (educativas y puntos de explicación) | 100% |
| Abstención en casos diseñados sin evidencia o fuera de alcance | 14 de 14 |
| Respondibles con la cita esperada | 16 de 16 |
| Afirmaciones con instrucciones maliciosas | 0 |
| Latencia educativa p50 / p95 | ~10 ms / ~20 ms |
| Latencia de explicación p50 / p95 (incluye crear el plan) | ~40 ms / ~310 ms |
| Costo | No medido con proveedor real; el ejecutor calcula el costo con los precios por 1.000 tokens que se le pasen y no los inventa |

Estos números miden las defensas y la lógica de recuperación, no la calidad de un modelo. El proveedor simulado no reemplaza una evaluación con un modelo real.

### Ajuste y conjunto reservado

Ajusté las heurísticas de respuesta con los propios casos educativos de `cases_v1`:

- la cobertura por IDF;
- las palabras de formulación;
- el plural simple.

Por eso el 16 de 16 está sobreestimado. Escribí después 12 preguntas nuevas (`evals/holdout_v1.json`) y las corrí una sola vez, sin ajustar nada:

- **Respondibles:** 4 de 8. Fallaron las paráfrasis con vocabulario distinto del corpus, como «baja tan lento» frente a «baja muy lentamente», o «intereses que generan intereses» frente a «intereses generados».
- **Sin evidencia:** 4 de 4 abstenciones correctas.

El sistema es conservador: prefiere abstenerse a responder con evidencia débil. Mejorar la cobertura requiere un modelo de embeddings semántico, y no evalué ninguno.

## Comparación entre Chroma y pgvector

`scripts/evaluate_vector_stores.py` compara los dos almacenes con los mismos vectores `hash-v2` de 768 dimensiones, sobre 20.000 fragmentos sintéticos armados con el vocabulario del corpus y 200 consultas. Mide recall@5 frente a búsqueda exacta. Lo corrí en Windows con PostgreSQL 16 y pgvector en Docker.

| | Chroma (HNSW, coseno) | pgvector (HNSW, `ef_search` 40) | pgvector sin índice (exacto) |
|---|---|---|---|
| recall@5 | 0,85–0,87 | 0,70 | 0,99 |
| Latencia p50 | 48–53 ms | 2,3 ms | 51–53 ms |
| Latencia p95 | 52–69 ms | 3,3 ms | 54–59 ms |
| Construcción | 9 s | 6 s de carga + 24–27 s de índice | 6 s de carga |

Lo que encontré:

- **El índice no se usaba al principio.** En las primeras corridas, con la tabla recién cargada y sin estadísticas, el planificador eligió un recorrido completo con ordenamiento en lugar del índice HNSW. Lo comprobé con `EXPLAIN`. Al correr `ANALYZE`, el índice se usó.
- **Las consultas con filtro necesitan cuidado.** En pgvector, una consulta con `WHERE` y HNSW requiere estadísticas y, según el caso, búsqueda iterativa.
- **El recall de HNSW depende de los parámetros.** Con `ef_search` 40 resultó menor que en Chroma; no probé otros valores.
- **El corpus sintético es adverso para estos índices.** Las palabras se eligen al azar, así que los vectores quedan distribuidos uniformemente y los vecinos se distinguen poco. El corpus real tiene decenas de fragmentos, donde la búsqueda exacta alcanza.

**Decisión:** mantengo Chroma en esta etapa, porque solo guarda el corpus público y es pequeño. Propongo migrar a pgvector en la etapa de operación, por razones operativas más que de velocidad:

- un solo almacén y una sola copia de seguridad;
- filtros de aprobación, vigencia y marcas en la misma transacción SQL;
- se elimina la restricción de un solo proceso que hoy impone Chroma local.

Antes de migrar quiero medir con el corpus real y el modelo de embeddings definitivo, y elegir `ef_search` o búsqueda exacta según el tamaño.

## Límites y fallos que quedan

- No evalué un modelo real. Las métricas del proveedor simulado demuestran que las defensas detectan los errores diseñados, no que un modelo los evite.
- La validación es léxica:
  - no detecta una frase engañosa que no use cifras, monedas, prioridades ni palabras prohibidas;
  - las listas de palabras prohibidas pueden rechazar frases legítimas o dejar pasar variantes no previstas.
- La detección de instrucciones maliciosas usa patrones y puede no reconocer formulaciones nuevas; las respuestas extractivas limitan el impacto, pero no lo eliminan.
- Las respuestas educativas solo copian oraciones, así que no resumen ni conectan ideas. Con el embedding local, la mitad de las preguntas reservadas respondibles terminaron en abstención.
- El cálculo de IDF recorre todo el corpus utilizable en cada consulta. Sirve para un corpus pequeño; para uno grande hay que cachearlo.
- El costo real no está medido.
