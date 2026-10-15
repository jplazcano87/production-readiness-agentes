# Concordancia entre el evaluador de estado, el juez LLM y la anotación humana

Muestra de **64 ejecuciones** de E1: todas las fallidas más 40 exitosas estratificadas por configuración y tipo.

La **kappa de Cohen** es la columna que importa. La concordancia simple sube sola cuando una clase domina —aquí el éxito— porque premia el acuerdo que se obtendría contestando siempre lo mismo; kappa descuenta ese acuerdo por azar, y por eso queda bastante por debajo. Cuando sale `—`, ambos anotadores usaron una sola clase y la métrica no está definida: reportar 0 diría «no hay acuerdo» cuando lo que pasa es que no aplica.

| Par | N | Concordancia simple | Kappa de Cohen |
|---|---:|---:|---:|
| evaluador de estado vs juez LLM | 64 | 0.7500 | 0.3846 |
| evaluador de estado vs anotación humana | 64 | 0.7500 | 0.3846 |
| juez LLM vs anotación humana | 64 | 1.0000 | 1.0000 |

## Dónde discrepan

| Par | Ambos éxito | Ambos fallo | Solo el primero | Solo el segundo |
|---|---:|---:|---:|---:|
| evaluador de estado vs juez LLM | 40 | 8 | 0 | 16 |
| evaluador de estado vs anotación humana | 40 | 8 | 0 | 16 |
| juez LLM vs anotación humana | 56 | 8 | 0 | 0 |

> ### Cómo se recogió esta anotación
>
> El archivo que se anotó traía `judge_reason`, `judge_success` además de la columna por rellenar, así que el veredicto del juez estaba a la vista mientras se anotaba. **La independencia entre anotador y juez no es verificable desde el archivo**, con independencia de cómo se anotara en realidad.
>
> `run_e6.py` exporta también `data/annotation/e6_sample_ciego.csv`, sin las columnas del juez ni la del evaluador de estado. Una ronda sobre ese archivo produciría un acuerdo verificable sin depender del testimonio de quien anota.

## Ronda a ciegas: una persona ajena, sin ver ningún veredicto

La misma muestra, anotada por una persona que no vio configuración, tipo, `run_id`, `case_id` ni veredicto alguno (64 ejecuciones; 68 pantallas con las 4 repeticiones del test-retest, de las que se usa la primera respuesta). La columna comparada es `p2_le_sirve`: si la respuesta le sirve al cliente. La regla de lectura está fijada en [`E6_REGLA_DE_INTERPRETACION.md`](../docs/E6_REGLA_DE_INTERPRETACION.md), escrita **antes** de recibir el archivo, y el resultado completo en [`results/e6_blind.json`](../results/e6_blind.json).

| Par | N | Concordancia simple | Kappa de Cohen | Solo el primero aprueba | Solo el segundo aprueba |
|---|---:|---:|---:|---:|---:|
| anotación del autor vs anotación a ciegas | 64 | 0.6250 | -0.2000 | 16 | 8 |
| juez LLM vs anotación a ciegas | 64 | 0.6250 | -0.2000 | 16 | 8 |
| evaluador de estado vs anotación a ciegas | 64 | 0.7500 | 0.4286 | 4 | 12 |
