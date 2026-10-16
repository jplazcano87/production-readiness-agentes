# Procedencia de los artefactos

De dónde sale cada cosa que hay en este repositorio, con qué versión se produjo y qué se
decidió no publicar. Existe porque el repositorio público **no lleva el historial** del
repositorio privado donde se hizo la investigación: sin este documento, varias cosas del árbol
quedarían sin explicación.

## Cómo se creó este repositorio

El árbol se exportó desde un repositorio privado de desarrollo, sin historia, con
`git archive`. Ese repositorio queda archivado y no se publica: contiene el registro de trabajo,
el plan por etapas y material de proceso que no pertenece a una publicación.

| | |
|---|---|
| Commit de origen de la exportación | `ae78cd2dcbfae33a9929a76bd8600144e9e835a7` |
| Fecha de la exportación | 2026-10-15 |

**El árbol exportado es idéntico a ese commit salvo este registro**, y «este registro» son
**tres archivos**:

| Archivo | Qué cambia |
|---|---|
| `docs/PROCEDENCIA.md` | la tabla de arriba, que anota el commit de origen y la fecha, y esta frase |
| `CHANGELOG.md` | tres conteos de archivos que habían quedado viejos |
| `tests/test_archivos_de_comunidad.py` | la prueba que cuenta esos archivos en el árbol y los compara con el registro de cambios, para que no vuelvan a desalinearse |

Nada más cambia entre ese commit y el que se exporta, y la verificación de la exportación lo
comprueba archivo por archivo: si el diff trae un cuarto, falla.

Lo que esa tabla y esta frase no inventan está en los archivos de siempre: la fecha de
publicación en `CITATION.cff`, la misma fecha en la entrada 1.0.0 de `CHANGELOG.md`, y una prueba
que exige que las tres coincidan.

## Qué generó cada artefacto

| Artefacto | Lo produce | Con qué versión |
|---|---|---|
| `data/corpus/v1.*/` | `data/generators/build_corpus.py` | capa programática con semilla `20260906`; el texto, redactado con `claude-haiku-4-5-20251001` |
| `data/splits/v1.*/` | `scripts/make_splits.py` | misma semilla; las particiones heredan la asignación de la versión base |
| `results/e1_*.json` | `scripts/run_e1.py` | agente 3.0.0 y 3.0.1, evaluador 2.1.1 |
| `results/e2_*.json` | `scripts/run_e2.py`, más `e2_reclasificar.py` y `e2_vista_combinada.py` sin API | criterio de ataque 1.0.0 y 1.2.0 |
| `results/e2_cal_r{1,2,3}.json` | `scripts/run_e2.py` sobre el corpus de trabajo que armaba `scripts/calibrar_ataques.py`, un script de un solo uso que **no se publica** porque lee ese corpus | agente 3.0.0, corpus de trabajo `v1.2-dev` |
| `results/e3_*.json` | `scripts/run_e3.py` | siempre en tiempo real, con streaming y sin caché |
| `results/e4_*.json` | `scripts/run_e4.py`, más `e4_combinar.py` sin API | checklist 1.1.0 y 1.2.0 |
| `results/e5_verdict_*.json` | `scripts/run_e5.py`, sin API | política v0.2.2 y v0.3.0 |
| `results/e6_*.json` | `scripts/run_e6.py`, `e6_agreement.py`, `e6_kappa_ciego.py`, `e6_exploratorio.py` | instrumento de anotación 1.1 |
| `results/runs_*/` | las transcripciones que persiste cada experimento | |
| `tables/`, `figures/informe/` | `make_tables.py`, `make_figures.py`, `corpus_stats.py`, `e1_analisis_casos.py`, `run_e5.py`, `e6_agreement.py` | derivados; el verificador los rehace y los compara |

Cada resultado declara en su metadata la semilla, la versión y el hash del corpus, el modelo,
las versiones del agente, del evaluador y del criterio de ataque, el commit y el modo de API.
**No declara la versión del SDK ni de las dependencias**; eso está explicado en
[`REPRODUCIBILIDAD.md`](REPRODUCIBILIDAD.md).

## Las tres rondas de calibración de los ataques, y por qué no traen transcripciones

`results/e2_cal_r{1,2,3}.json` son la calibración de la fuerza de los ataques de la versión
v1.2, de septiembre: tres rondas de 30 casos por 2 ejecuciones sobre `none`, **todos de la
partición de desarrollo**, con tasas de éxito de 0,017, 0,050 y 0,050. Se publican porque
sostienen una afirmación del informe que de otro modo habría que creer: que ese ajuste se hizo
sin ejecutar nunca la partición de prueba.

Dos cosas que hay que saber para leerlas:

- **Corrieron sobre un corpus de trabajo, `v1.2-dev`, que no se publica.** No era un corpus
  congelado: reutilizaba el catálogo, las reseñas benignas y la parte benigna de cada intención
  del corpus anterior, y regeneraba solo las cargas adversariales, que es lo que se estaba
  ajustando. Cuando la calibración superó su criterio se escribió el corpus v1.2 de verdad, que
  sí está publicado con su hash.
- **Sus transcripciones no existen, y las rutas que declaran llevan a otra corrida.** Las tres
  rondas declaran las mismas 60 rutas en la raíz de `results/runs_e2/`, porque el arnés de
  entonces escribía ahí y no en un directorio por corrida, así que cada ronda sobreescribió a la
  anterior. Lo que hoy ocupa esas 60 rutas, y lo que este repositorio publica en ellas, son las
  transcripciones de otra corrida del mismo día: la compuerta del modelo pequeño,
  `results/e2_compuerta_haiku.json`, que las sobreescribió a su vez.

  Dicho sin rodeos: **quien siga las rutas que declaran `results/e2_cal_r{1,2,3}.json` va a abrir
  ejecuciones de la compuerta, no de la calibración.** Los tres resultados están congelados y no
  se corrigen, así que el aviso vive aquí. Lo verificable es que esos 60 archivos coinciden con
  las observaciones de la compuerta en los cuatro contadores de tokens y en el veredicto del
  ataque, 60 de 60, y con ninguna ronda: los éxitos de los archivos son 12 y los de las rondas
  1, 3 y 3. `tests/test_results.py` lo fija.

  Lo que queda de las rondas es su resultado, con una observación por ejecución: identificador,
  veredicto del ataque, motivo y tokens.

## Las 26 ejecuciones de E2 con Sonnet que no declaran transcripción, y la que sí está

`results/e2_security.json` tiene 1.176 observaciones y **26 de ellas traen `transcripcion` en
`null`**. No hay que deducir por qué: el propio resultado lo declara en
`metadata.transcripciones_perdidas`, con el número, el motivo y la lista de `run_id`, y en
`metadata.cobertura_de_transcripciones`, con 1.150 verificadas de 1.176. El 8 de septiembre esa
corrida escribió sus transcripciones en la raíz de `results/runs_e2/` y, minutos después, el
piloto de la corrida con el modelo pequeño escribió las suyas en el mismo directorio; los
`run_id` se repiten entre corridas. El comentario que lo explica está en `scripts/run_e2.py`,
junto al código que lo impide, y el arnés pasa a usar un directorio por corrida.

De esas 26, **una no se había perdido**: `SEG-BEN-040__cte__2`. El piloto escribía una sola
ejecución por caso, siempre con sufijo `__0`, así que este archivo, con sufijo `__2`, no estaba
entre los que pisó. Se publica en su ruta, `results/runs_e2/SEG-BEN-040__cte__2.json`, y coincide
con su observación en los cuatro contadores de tokens, la configuración, el tipo de caso, el
veredicto del ataque, el número de turnos y el de llamadas.

Así que el campo congelado cuenta **una de más**: la lista de perdidas se armó por ruta, con los
`run_id` que el piloto podía haber pisado, no comprobando el contenido de cada archivo. No se
corrige, porque corregirlo rompería el hash de un artefacto medido, y además la dirección del
error es la segura: declara menos cobertura de la que hay. Con esta publicación, de las 1.176
ejecuciones de E2 con Sonnet **1.151 tienen su transcripción publicada**, una más que las 1.150
que el resultado declara.

Las otras 25 no se recuperan: lo que hay en esas rutas es el piloto del modelo pequeño, que se
publica y se explica abajo. Entre ellas está `SEG-DIR-015__cte__0`, el único éxito de ataque de
E2 con Sonnet sin transcripción, que el informe reporta como tal y conserva por conservadurismo.

## El piloto de la corrida con Haiku

En la raíz de `results/runs_e2/` hay 25 transcripciones más, del piloto automático de esa
corrida: 9 casos, 3 por tipo, una ejecución por caso y configuración, de la partición de prueba.
Un piloto corre antes de la medición para validar el arnés y abortar antes de gastar, y este
abortó: el verificador lo bloqueó por dos defectos del arnés, no del modelo. Uno perdía la
ejecución completa cuando el planificador escribía una especificación de formato inválida sobre
un valor que ya era texto; el otro es el directorio compartido que hizo que este mismo piloto
pisara 26 transcripciones de la corrida con Sonnet. Los dos se corrigieron, y la corrida medida
salió después con el agente 3.0.1 y un directorio por corrida, reejecutando todos los casos.

Se publican porque son la evidencia de que el piloto hizo su trabajo, y con la advertencia que
las hace legibles: **no son la medición**. Corrieron con el agente 3.0.0 y lo medido es con
3.0.1, sobre el mismo corpus, el mismo criterio y los mismos prompts. Las ejecuciones que entran
en las cifras de E2 con Haiku están en `results/runs_e2/e2_security_haiku/`. De las 27
ejecuciones que el piloto planeaba quedan 25 archivos: las dos que faltan, ambas de `cte`, son
ejecuciones que se perdieron por el primer defecto, que es justamente el que las bloqueó.

Lo que separa unas de otras es comprobable sin fiarse de ninguna etiqueta: las llamadas de estas
25 ocurrieron entre las 22:11:43 y las 22:12:37 UTC del 8 de septiembre de 2026, y las de la
corrida medida empiezan a las 22:22:26, después del cambio que corrigió los dos defectos.
`tests/test_results.py` lo fija.

## Los `git_commit` de `results/` apuntan a un repositorio que no se publica

Cada archivo de `results/` registra en `metadata.git_commit` el commit en que se generó. **Esos
identificadores pertenecen al repositorio privado de desarrollo, que queda archivado**, y no
resuelven contra el historial de este repositorio. Se conservan porque forman parte del
artefacto medido y modificarlos rompería su hash; sirven para ordenar las corridas entre sí, no
para buscarlas en ningún sitio público.

Lo mismo vale para los tags del repositorio privado que la documentación menciona. Son estos:

| Tag | SHA | Fecha | Qué fija |
|---|---|---|---|
| `corrida-final-3.0.0` | `f24ee5f33346c856f0ec783bacbeeee0a100ea8c` | 2026-09-10 | el estado del arnés de las corridas de septiembre: E1 en tres configuraciones, E2 con Sonnet y con Haiku, E3 y E4. La robustez de `prompt_only` no está ahí: se corrió en octubre, con el agente 3.0.1 |
| `policy-v0.3.0` | `850c95ff77a4e04310cb77fea6e72a3e504ecf11` | 2026-10-11 | la política de aceptación, congelada antes de las corridas que la usan |
| `corpus-v1.3` | `591cd70f431ffc5a9f81ba21bc2e39e176308939` | 2026-10-11 | el corpus con la segunda superficie de inyección |
| `corpus-v1.4` | `1e88426af4ef41929e7cd4d2223979ab6ba63eca` | 2026-10-11 | el corpus con el caso del ítem de cumplimiento nuevo |
| `checklist-1.2.0` | `1e88426af4ef41929e7cd4d2223979ab6ba63eca` | 2026-10-11 | el checklist con el ítem de veracidad |

La descripción de cada tag es la que se escribió al crearlo. El mensaje completo del commit al
que apunta no se reproduce aquí.

## Identificadores internos en artefactos congelados

Veinte comentarios dentro de archivos congelados citan identificadores de un registro de
desarrollo que no se publica, de la forma `(D20)` o `(L9)`. **Se conservan porque modificarlos
rompería el hash del artefacto**, y un artefacto cuyo hash no coincide deja de servir para lo
único que está ahí: demostrar que es el que se midió.

Esta tabla los traduce.

| Token | Dónde aparece | Qué nombra | Dónde está ahora |
|---|---|---|---|
| `D14` | `data/templates/attacks/dev/direct.yaml` | las cláusulas defensivas que estaban en el prompt base y hacían que `none` no fuera una línea base | defecto **15** de [`REGISTRO_DE_DEFECTOS.md`](REGISTRO_DE_DEFECTOS.md) |
| `D15` | `configs/thresholds.yaml` | el intervalo por remuestreo que daba `[0, 0]` sobre una muestra de ceros | defecto **16** |
| `D16` | `configs/thresholds.yaml`, `data/corpus/v1.2/MANIFEST.json`, `results/e5_verdict_<config>.json` | el rediseño de las cargas de ataque de la versión v1.2 y la familia que presenta el centinela como identificador administrativo del propio pedido | no es un defecto; se describe en la sección 3 de [`CIFRAS_INFORME.md`](CIFRAS_INFORME.md) y en [`DATASHEET.md`](DATASHEET.md) |
| `D20` | `results/e4_compliance_<config>.json` (las cuatro) | los cuatro verificadores de cumplimiento que reprobaban respuestas correctas | defecto **20** |
| `D21` | `configs/thresholds.yaml` | el umbral agregado de tasa de éxito de ataque que aprobaba lo que su desagregación reprobaba | defecto **21** |
| `D22` | `configs/thresholds.yaml` | la latencia que se medía y no entraba en la conjunción del veredicto | defecto **22** |
| `D30` | `data/templates/attacks/dev/indirect_descripcion.yaml`, `results/e2_security_criterio1.2.0.json`, `results/e2_security_haiku_criterio1.2.0.json` | el criterio de éxito de ataque que contaba el rechazo como obediencia | defecto **30** |
| `L6` | `configs/experiments.yaml`, `configs/thresholds.yaml` | un ítem normativo decidido con una sola ejecución no es estable | limitación **6** de [`LIMITACIONES.md`](LIMITACIONES.md) |
| `L9` | `configs/congelado_corrida_final.json` | una de las siete reglas del evaluador que ningún caso del corpus ejercita | limitación **9** |

## Los comentarios de los artefactos congelados describen el pasado

Esos mismos archivos llevan comentarios y registros de cambios escritos **en el momento en que
se congelaron**, y describen el estado del proyecto de entonces, no el final. El ejemplo más
visible está en `configs/thresholds.yaml`, que al justificar una regla habla de «los dos GO que
hoy hay»: con la política vigente y las cuatro configuraciones medidas, el veredicto final tiene
**tres** GO y un NO-GO.

No es un error del archivo. Es lo que significa congelar algo: queda como estaba. **Las cifras
vigentes están en [`CIFRAS_INFORME.md`](CIFRAS_INFORME.md)**, que es el documento que se mantiene
al día y que dice, para cada número, de qué archivo sale.

## Metadatos congelados que se leen con una corrección

Algunos campos de archivos congelados dicen algo que, leído solo, lleva a una conclusión
equivocada. **No se corrigen**, por la misma razón que todo lo anterior: cambiarlos rompería el
hash del artefacto medido. Esta sección dice qué campo es, qué vale y por qué. Ninguno cambia una
cifra publicada.

### `results/e2_security_v1.3.json` declara el corpus v1.4

El nombre del archivo y [`CIFRAS_INFORME.md`](CIFRAS_INFORME.md) hablan de v1.3, y
`metadata.corpus_version` dice **v1.4**, con el hash de v1.4 (`287b3bf1…`). La causa es
mecánica: el archivo es una vista combinada, escrita sin API por `scripts/e2_vista_combinada.py`
el 11 de octubre a las 18:05 UTC, después del tag `corpus-v1.4` (17:53), y ese script toma la
versión de `configs/experiments.yaml`, que ya decía v1.4.

**Los casos de seguridad son los mismos.** v1.4 se diferencia de v1.3 solo en
`cases_compliance.jsonl`, al que añade `CUM-026`: `cases_security.jsonl`, `reviews.jsonl`,
`catalog.json` y `cases_robustness.jsonl` son **idénticos byte a byte** entre las dos versiones,
y las líneas `SEG-` de `data/splits/v1.3/test.txt` y `data/splits/v1.4/test.txt` también. Qué
corrida midió qué está en `metadata.vista_combinada.corridas`: los 98 casos de reseña vienen de la
corrida sobre v1.2 y los 21 de descripción, de la corrida sobre v1.3.

### `results/e4_compliance_checklist1.2.0_<config>.json`: tres versiones en un mismo archivo

Los cuatro archivos, y los `e4_reverificado_checklist1.2.0_<config>.json` de los que salen,
declaran:

| Campo | Valor | Qué es |
|---|---|---|
| `checklist_version` (nivel superior) | **1.2.0** | el checklist que emitió los veredictos de los ítems. **Es el que vale** |
| `metadata.checklist_version` | 1.0.0 | el checklist vigente cuando se corrió la medición que produjo las transcripciones, el 10 de septiembre |
| `metadata.repuntuado` | 1.1.0 → 1.2.0 | la última reverificación sin API, con el checklist de antes y el de después |
| `metadata.corpus_version` | v1.4 | el corpus vigente al reverificar, que trae `CUM-026`, el caso del ítem nuevo |
| `metadata.corpus_hash` | `55921b51…`, **el de v1.2** | el corpus sobre el que corrieron las transcripciones |
| `metadata.corpus_version_de_las_transcripciones` | v1.2 | lo mismo, con su nombre |

La explicación está en `scripts/run_e4.py`, en la función que reverifica: mueve el
`checklist_version` del documento y el `corpus_version` de la metadata, y guarda la versión
anterior en `corpus_version_de_las_transcripciones`, pero no toca `metadata.checklist_version`
ni `metadata.corpus_hash`, que se escribieron al correr. Así que el par `corpus_version` v1.4 con
`corpus_hash` de v1.2 **no se lee junto**: el hash va con
`corpus_version_de_las_transcripciones`. El ítem nuevo, `INFORMACION_VERAZ_RESULTADOS`, sí se
midió sobre v1.4, y lo declara `metadata.combinado.item_nuevo.corpus_version`.

### `configs/congelado_corrida_final.json` dice que E4 se midió con el agente 3.0.0

Su `nota_version` dice que «E1, E4 y E2 con Sonnet se midieron con el agente 3.0.0». Para E4 no
es así: la metadata de los cuatro resultados de E4 declara `agent_version` **3.0.1**, y el mismo
archivo lo dice en `agent_versions_en_resultados.e4_compliance`. **Vale la metadata**, que la
escribe la corrida, y no la nota, que se escribió a mano. E1 y E2 con Sonnet sí son 3.0.0. El
registro de cambios de `AGENT_VERSION` en `src/prf/agent/configuraciones.py` repite la misma
frase sobre E4. El parche 3.0.1 no cambia el texto de ningún prompt, así que la diferencia no
afecta a lo medido.

### 26 transcripciones perdidas, que son 25

`results/e2_security.json`, `results/e2_security_criterio1.2.0.json`,
`results/e2_security_v1.3.json` y los cuatro `results/e5_verdict_v0.3.0_<config>.json`
declaran 26 transcripciones faltantes. Son **25**: una de las 26 se conservó y se publica. El
detalle está arriba, en
[«Las 26 ejecuciones de E2 con Sonnet que no declaran transcripción, y la que sí está»](#las-26-ejecuciones-de-e2-con-sonnet-que-no-declaran-transcripción-y-la-que-sí-está).

### `configs/experiments.yaml` conserva valores del diseño

Tres campos ya no describen lo que se midió:

| Campo | Dice | Lo medido |
|---|---|---|
| `experiments.e6_juez.n_muestra` | 80, con `estratificacion` 40 y 40 | **64**: todas las fallidas más 40 exitosas, porque el agente final falla 24 de 1.008 (defecto 18 de [`REGISTRO_DE_DEFECTOS.md`](REGISTRO_DE_DEFECTOS.md)) |
| `corpus.cumplimiento.n_casos` | 25 | **26** en v1.4, con `CUM-026` |
| `api.modo_preferente` | `batch` | las corridas finales fueron **en tiempo real**: cada resultado lo declara en `metadata.api_mode` |

Ningún script lee esos tres campos: `scripts/run_e6.py` arma la muestra con su propia regla y
escribe el tamaño real en el resultado, y los experimentos toman el número de casos del corpus.
Solo `tests/test_config.py` los compara con los valores escritos. El archivo **no se edita**,
ni siquiera para añadir un comentario, porque está en `docs/MANIFIESTO_ARTEFACTOS.json` con su
hash. Lo mismo vale para los `api_mode: batch` de cada experimento.

### El comentario de `prompts.py` sobre la advertencia

En `src/prf/agent/prompts.py`, el comentario del párrafo `ADVERTENCIA_CONTENIDO_NO_CONFIABLE`
dice que «es lo único que separa `prompt_only` de `none`». Desde el agente 3.0.0 no es cierto:
`prompt_only` lleva además las cláusulas defensivas, y `dual_llm` recibe también ese párrafo
(`advierte_en_prompt=True` en `src/prf/agent/configuraciones.py`), aunque no las cláusulas. En
`cte` la bandera también está activa, pero el planificador tiene su propio system prompt y el
párrafo no le llega. El archivo es congelado, porque sus textos tienen huella, y el comentario
se deja como está; la descripción correcta de las cuatro configuraciones está en el README.

## Artefactos retenidos

Tres archivos **no se publican en su forma original**. Al fabricar canales de contacto que nadie
le había dado, el agente escribió un móvil chileno con formato válido. El número es invención
del modelo, pero un número inventado con formato válido puede ser el de una persona real.

En su lugar se publica una copia con el sufijo `.redactado.json`, idéntica byte a byte salvo los
ocho dígitos del número, reemplazados por un marcador del mismo largo. **Los originales se
conservan en el historial del repositorio privado de desarrollo**, que queda archivado, y su
SHA-256 está aquí para que la retención sea auditable y no un recorte silencioso.

| Original retenido | SHA-256 del original | SHA-256 de la copia publicada |
|---|---|---|
| `results/runs_e4/CUM-025__cte.json` | `0838655818e3880d2efe6161cbe9f2029d3c374f11799024170f14669f455319` | `c3668a4749826aa970f1866c450cbd9d45d34ee34f7a873e005025eb554d5409` |
| `results/runs_e4_v2.0.0/CUM-025__cte.json` | `0838655818e3880d2efe6161cbe9f2029d3c374f11799024170f14669f455319` | `c3668a4749826aa970f1866c450cbd9d45d34ee34f7a873e005025eb554d5409` |
| `results/e4_compliance_cte_v2.0.0.json` | `e67aad15cab6a64cbf197ad133bb8ce56ca4da4555b6f1d12f979c5e15309a0f` | `9a346be6447b46276ad0cf876a2a6540abb3014eafdd36703984a317127d1dd8` |

`docs/MANIFIESTO_ARTEFACTOS.json` guarda los dos: el del original en su sección `retenidos`, con
el motivo, y el de la copia entre los artefactos publicados. El verificador comprueba además que
**ningún archivo publicable contenga un móvil con formato válido**.

### La redacción no cambia lo que se mide, y dónde sí cambia

El checklist 1.2.0 aplicado a las copias redactadas da **el mismo estado en los 28 ítems**, en
las dos configuraciones que esas transcripciones cubren. Hay una sola diferencia, y está en la
evidencia, no en el veredicto: en el ítem `PUNTO_CONTACTO_HUMANO` del caso `CUM-025`, la lista de
canales inventados tiene **un elemento menos**, porque el teléfono redactado ya no parece un
teléfono para el extractor de canales. El ítem **sigue fallando**, por los otros canales que el
agente se inventó en la misma respuesta: un número 600, un correo y un chat.

`tests/test_checklist_regresion_v2_0_0.py` comprueba la igualdad de los 28 estados y se salta
sola donde el original no está, que es este repositorio.

## Consentimiento de la anotación a ciegas

La anotación externa de la muestra de concordancia la hizo una persona ajena al proyecto, que
**autorizó la publicación de sus respuestas anonimizadas el 14 de octubre de 2026**.

Lo que se publica, en `data/annotation/e6_respuestas_ciego.csv`, es una copia byte a byte del
archivo que descargó, con una fila por pantalla y estas columnas: el identificador anónimo de la
pantalla (`C01` a `C68`), las dos respuestas binarias, el comentario libre, la marca de tiempo,
los segundos en pantalla y la versión del instrumento. **No contiene su nombre ni ningún dato
que la identifique**, y el comentario libre viene vacío en las 68 pantallas.

El instrumento se diseñó a ciegas: el HTML que recibió no llevaba la configuración de defensa,
el tipo de caso, el `run_id`, el `case_id` ni el veredicto de nadie. La tabla que traduce el
identificador anónimo al `run_id` se escribió aparte y se publica en
`data/annotation/correspondencia.csv`, ahora que la anotación terminó, porque es lo único que
permite reproducir el cálculo.

Los detalles del instrumento, con las huellas de lo que se entregó y de lo que se recibió, están
en [`E6_INSTRUMENTO.md`](E6_INSTRUMENTO.md), y la regla con que se leyeron las respuestas, fijada
antes de recibirlas, en [`E6_REGLA_DE_INTERPRETACION.md`](E6_REGLA_DE_INTERPRETACION.md).
