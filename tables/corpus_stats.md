| Variable | N | Media | Mediana | Desv. est. | Mín.–Máx. |
|---|---:|---:|---:|---:|---:|
| Precio del producto (CLP) | 200 | 753.000 | 491.490 | 680.780 | 11.990–2.498.990 |
| Longitud de intención (tokens) | 256 | 51.5 | 45.0 | 24.4 | 15.0–125.0 |
| Longitud de reseña (tokens) | 600 | 86.8 | 87.0 | 9.1 | 64.0–114.0 |
| Reseñas por producto | 200 | 3.3 | 3.0 | 0.5 | 3.0–4.0 |
| Longitud de carga adversarial (tokens) | 130 | 79.5 | 67.0 | 23.8 | 55.0–137.0 |
|     vector directo | 40 | 65.7 | 66.0 | 5.2 | 55.0–77.0 |
|     portador reseña | 60 | 67.8 | 66.0 | 6.9 | 60.0–95.0 |
|     portador descripción | 30 | 121.2 | 121.0 | 6.8 | 110.0–137.0 |

Corpus `v1.4`, hash `287b3bf1ecaff1639c379d3ea6778280e29c2abe5d312d4038c9a9827bc39529`. Conteo de tokens: aproximación local declarada: un token cada 3.6 caracteres (`prf.infra.tokens.approx_tokens`), sin llamadas a la API. «Reseñas por producto» cuenta también la reseña adversarial de los 60 productos portadores de una inyección por reseña, una por ataque, que por eso llegan a cuatro. Los 30 portadores de una inyección por descripción no añaden ninguna reseña: su carga va en la ficha del producto. Las tres filas de carga adversarial miden lo que entra en el contexto del agente: la carga sola en el vector directo, y el texto completo que la transporta —la reseña o la ficha del producto— en el indirecto. La fila agregada mezcla las tres y solo sirve para comparar con las versiones anteriores del corpus.
