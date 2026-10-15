# Particiones del corpus v1.1

Semilla `20260906`. Partición por `case_id`, estratificada por dimensión y tipo, con una proporción objetivo de 30 % desarrollo y 70 % prueba.

Los casos de seguridad con carga adversarial **no se sortean**: heredan la partición de la plantilla con que fueron construidos (`data/templates/attacks/dev/` o `.../test/`). Es lo que impide que una formulación de ataque vista durante el ajuste reaparezca en la medición.

| Dimensión y tipo | Desarrollo | Prueba | Total |
|---|---:|---:|---:|
| Robustez: búsqueda | 6 | 14 | 20 |
| Robustez: comparación | 6 | 14 | 20 |
| Robustez: recomendación | 6 | 14 | 20 |
| Seguridad: inyección directa | 12 | 28 | 40 |
| Seguridad: inyección indirecta | 18 | 42 | 60 |
| Seguridad: benignos | 12 | 28 | 40 |
| Cumplimiento | 8 | 17 | 25 |
| **Total** | **68** | **157** | **225** |

Proporción efectiva de desarrollo: 30.2% (68 de 225 casos).
