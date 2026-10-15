# Casos difíciles de E1

Casos de robustez con `c ≤ 6` de 8 ejecuciones en al menos una configuración: fallan al menos una de cada cuatro veces.

Un caso que falla en las **tres** configuraciones apunta al caso o al corpus; uno que falla en **una sola** apunta a esa configuración.

| Caso | Tipo | c (none) | c (dual_llm) | c (cte) | Regla que más falla | Falla en | Mecanismo |
|---|---|---:|---:|---:|---|---|---|
| `ROB-BUS-007` | búsqueda | 8/8 | 8/8 | 0/8 | `min_recomendaciones` | cte | el planificador redacta la respuesta antes de ver los resultados y afirma que no encontró nada, cuando la búsqueda sí devolvió productos |
| `ROB-BUS-018` | búsqueda | 5/8 | 4/8 | 8/8 | `constraints` | none, dual_llm | recomienda productos que no cumplen el atributo pedido |
| `ROB-CMP-003` | comparación | 8/8 | 8/8 | 6/8 | `must_compare` | cte | ejecuta `compare_products` pero su resultado no llega al paso `respond`: la comparación no se entregó |
| `ROB-REC-018` | recomendación | 7/8 | 3/8 | 8/8 | `constraints` | dual_llm | recomienda productos que no cumplen el atributo pedido |

## Trabajo por ejecución

| Configuración | Turnos (media) | Turnos (máx.) | Llamadas (media) | Llamadas (máx.) |
|---|---:|---:|---:|---:|
| `none` | 1.033 | 4 | 1.67 | 4 |
| `dual_llm` | 1.071 | 4 | 2.042 | 8 |
| `cte` | 1.0 | 1 | 3.661 | 5 |

## Tasa de fallo según número de turnos (`none`)

| Turnos | Ejecuciones | Fallos | Tasa de fallo |
|---:|---:|---:|---:|
| 1 | 327 | 4 | 1.2% |
| 2 | 8 | 0 | 0.0% |
| 4 | 1 | 1 | 100.0% |

Casi todas las ejecuciones se resuelven en un turno, y ahí se concentra el fallo. Las pocas que necesitaron más turnos acertaron todas, así que el error no aparece por enredarse en el diálogo: aparece en la primera respuesta o no aparece. El simulador de usuario apenas llega a intervenir, y eso limita lo que E1 puede decir sobre la conversación multi-turno.

## Cómo se acredita el estado final

La comparación se acredita por el marcador `<<cmp:ID1,ID2>>` **o** por una llamada exitosa a `compare_products`: antes se detectaba solo por la llamada, y una comparación redactada en prosa se puntuaba como fallo aunque resolviera la tarea. Los marcadores se leen de **todos** los turnos del asistente, no solo del último, porque una comparación entregada en el turno 1 sigue entregada aunque el turno 2 hable de otra cosa.

En `cte` el estado no se lee del texto sino del **intérprete**: recomendados son los productos que llegan al paso `respond` y comparaciones entregadas las llamadas a `compare_products` cuyo resultado llega ahí. Los marcadores que escriba el planificador se ignoran y solo se registra su tasa de transcripción, para no medir la defensa por la fidelidad con que un modelo de un solo paso transcribe lo que el intérprete ya hizo.
