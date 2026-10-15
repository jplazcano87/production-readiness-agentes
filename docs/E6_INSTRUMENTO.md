# E6 — el instrumento de anotación a ciegas que se entregó

Generado por `scripts/e6_anotacion`, versión **1.1**.
Este archivo se versiona; el HTML no, porque lleva las transcripciones dentro.

## Huellas SHA-256

| Archivo | SHA-256 |
|---|---|
| `exports/e6_ciego/anotacion_e6.html` (entregado) | `57692039f6f4b66f1929d2a15b2898f2b7a21c9f2b708ae97e244e0aa610df2e` |
| `exports/e6_ciego/correspondencia.csv` (NO se entrega) | `c5638e8254aacceecca6a3daf93aeec0457cccf48b6a5ab8102634dc3c98f54f` |
| `data/annotation/e6_sample_ciego.csv` (origen) | `9fc76322c9abc5968bef349a5f25a0370963f05e16ccaf60645cb1f5c83d2e40` |

El HTML es **determinista**: regenerarlo con la misma semilla y el mismo corpus da un
archivo byte a byte idéntico, así que estas huellas se pueden comprobar.

## Con qué se generó

| | |
|---|---|
| Commit del generador | `44a6dcfc3beb2c4caa3660e05c9f81574040659f` |
| Semilla del orden | `20260906` |
| Corpus | `v1.4` |
| Política | `thresholds.yaml` v0.3.0, tag `policy-v0.3.0` |
| Commit del tag de política | `850c95ff77a4e04310cb77fea6e72a3e504ecf11` |
| Pantallas | 68 = 64 de la muestra + 4 repetidas |
| Clave de almacenamiento del navegador | `e6-anotacion-1.0` |

## Las dos preguntas

1. **`p1_opcion_no_cumple`** — ¿Alguna de las opciones que ofreció el asistente NO cumple alguna condición que pidió el cliente (por ejemplo, presupuesto o características)?
2. **`p2_le_sirve`** — Si usted fuera este cliente, ¿esta respuesta le sirve para lo que pidió?

## Repeticiones (test-retest)

Separación mínima de **20** posiciones. test-retest: cada uno se muestra dos veces con id anónimo distinto. Dos traen el patrón de opciones mixtas y dos son claros, como control.

| Primera | Repetición | Separación | Clase |
|---|---|---:|---|
| `C10` | `C44` | 34 | claro (control) |
| `C19` | `C48` | 29 | opciones mixtas |
| `C36` | `C61` | 25 | opciones mixtas |
| `C31` | `C66` | 35 | claro (control) |

## Historial de versiones

Un cambio en el instrumento después de recibir respuestas invalidaría la
comparación, así que la fecha de cada cambio frente a la entrega es parte del
registro.

### Versión 1.1 — 2026-10-12

**Motivo.** En 14 de las 68 pantallas de la muestra y en 3 de las 4 de práctica el asistente nombra productos por su código («el más económico es P0031», «Más barato: P0126») y la tabla no mostraba ningún código, así que quien anota no podía saber de qué producto hablaba la respuesta ni responder la pregunta 1 sobre esa opción.

**Qué cambió.** La tabla de productos lleva el código como primera columna, en la muestra y en la práctica; todo código que el asistente escriba está en la tabla de su caso (`completar_con_codigos_citados`, que lo añade con sus datos del catálogo si no llegó por herramienta); una frase en la pantalla de práctica dice dónde buscarlo; la bienvenida declara 68 pantallas y no 64; cada respuesta guarda la versión del instrumento y la exporta en la columna `version_instrumento`.

**Qué no cambió.** El texto de los turnos **no se tocó**: ni del cliente ni del asistente, y no se reemplazó ningún código por un nombre ni se añadió ninguna aclaración dentro de la respuesta. Se juzga la respuesta que recibió el cliente; reescribirla mejoraría solo las respuestas que usan códigos y sesgaría la comparación entre configuraciones. Tampoco cambian el orden de los casos, la semilla, los identificadores anónimos, el texto de las dos preguntas, la composición de la muestra ni la clave de almacenamiento del navegador (`e6-anotacion-1.0`), para que nadie pierda avance. El catálogo es byte a byte idéntico entre v1.2 y v1.4, así que los datos de la tabla son los mismos que en 1.0.

**Cuándo.** Antes de recibir ninguna respuesta: no existe CSV anotado de la versión 1.0 y el instrumento no se había entregado todavía.

### Versión 1.0 — 2026-10-11

**Motivo.** Primera versión entregable.

**Qué cambió.** 68 pantallas, dos preguntas y cuatro repeticiones para el test-retest.

## Ciegamiento

El HTML no contiene configuración, tipo, run_id, case_id ni veredictos. La correspondencia id_anonimo -> run_id va en correspondencia.csv, que no debe entregarse a quien anota.

La regla con la que se leerán los resultados está fijada **antes** de recibirlos en
[`E6_REGLA_DE_INTERPRETACION.md`](E6_REGLA_DE_INTERPRETACION.md).

## Respuestas recibidas

| | |
|---|---|
| Fecha de recepción | 2026-10-14 |
| Archivo | `data/annotation/e6_respuestas_ciego.csv` |
| SHA-256 | `2d9e09d19e6cc51abcbff424294392940fb289a30fe7a4f148b49ae9cb197774` |
| Filas | 68 |
| Versión del instrumento declarada | 1.1 |
| Tiempo total en pantalla | 1772.8 s (29.5 min) |

Copia byte a byte del archivo recibido. No se edita: el original es la evidencia.

Quien anotó **autorizó la publicación de sus respuestas anonimizadas** el 14 de octubre de 2026. El archivo publicado no contiene su nombre ni ningún dato que la identifique, y el comentario libre viene vacío en las 68 pantallas.
