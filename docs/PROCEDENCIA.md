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

### «El mismo código»: las dos corridas de latencia en frío no lo eran

Varios textos dicen que el p95 del TTFT de `none` en frío, 5,55 s y 2,20 s, salió de dos
corridas «del mismo código», «con el mismo código y el mismo corpus» o «sin que nada del agente lo
explique»: `configs/thresholds.yaml`, en tres lugares; `tables/e2_e3_summary.md`;
`tables/e5_verdict_v0.3.0.md`; los cuatro `results/e5_verdict_<config>.json`; y los textos que
generan `scripts/make_tables.py` y `scripts/run_e5.py`. Los congelados no se corrigen, y los dos
scripts tampoco, porque el verificador rehace con ellos tablas y veredictos publicados y el texto
regenerado dejaría de coincidir.

**No fue el mismo código.** La corrida de 5,55 s (`results/e3_latency_v2.2.0.json`, retirada; ver
la sección [«Cifras del informe que se apoyan en el repositorio de desarrollo»](#cifras-del-informe-que-se-apoyan-en-el-repositorio-de-desarrollo)) usó el agente **2.2.0** y el corpus **v1.1**; la de 2,20 s
(`results/e3_latency.json`), el **3.0.1** y el **v1.2**. Entre medio, en el commit
`28f6756cf34e333d466dbbcdc5cbb74f307b0ff8` del 2026-09-08 a las 17:19:56 UTC, las cláusulas
defensivas **salieron del prompt base**, que pasó de 1.513 a 1.021 caracteres.

**Lo que sí fue igual** es lo que la comparación necesita:

- **El diseño de la medición:** 20 casos de la partición de prueba × 5 repeticiones, en frío y
  con el orden intercalado.
- **El prefijo de catálogo:** el índice compacto es anterior a las dos corridas, y
  `catalog.json` es idéntico en v1.1 y v1.2. La entrada media por llamada fue de **6.292** tokens
  en una y **6.246** en la otra, un 0,7 % de diferencia.
- **Las condiciones de caché y streaming:** sin caché y con streaming en las dos, en el 100 % de
  las llamadas registradas, con los contadores de caché en cero.

La lectura exacta es: dos corridas con el mismo diseño, el mismo prefijo de catálogo y las mismas
condiciones de caché y streaming, separadas por el paso del agente 2.2.0 al 3.0.1.

### `data/templates/attacks/dev/direct.yaml`: «contra un agente sin ninguna cláusula»

El comentario de cabecera dice que las plantillas de v1.0 fracasaban en el 100 % de las
ejecuciones contra un agente sin ninguna cláusula defensiva. Lo que lo sostiene es la **versión
declarada del agente**, no una huella: `results/e2_dev_none_3.0.0.json` declara el agente 3.0.0,
que es el que saca las cláusulas del prompt base, pero corrió con `git_dirty: true`, sobre un
commit que todavía las tenía, y sin huella de prompt, que entonces no existía. Ver la tabla de la
sección [«Cifras del informe que se apoyan en el repositorio de desarrollo»](#cifras-del-informe-que-se-apoyan-en-el-repositorio-de-desarrollo).

### `docs/E2_PORTADOR_PREREGISTRO.md`: la calibración se escribió al cerrarla

La sección de calibración de ese documento se escribió **al cerrar** la calibración: el archivo
nace 3 minutos y 23 segundos después de la tercera ronda. Lo que aplica es un criterio que ya
estaba escrito desde septiembre en el registro de trabajo interno. Las horas están en la sección
[«Cifras del informe que se apoyan en el repositorio de desarrollo»](#cifras-del-informe-que-se-apoyan-en-el-repositorio-de-desarrollo). El documento no se edita: un prerregistro no se corrige con lo que pasó después.

### `configs/models.yaml` remite a un `CLAUDE.md` que no es este

Dos comentarios del archivo remiten a un `CLAUDE.md` para las decisiones cerradas sobre los
modelos. Es el del repositorio de desarrollo, que no se publica: el `CLAUDE.md` de este
repositorio solo remite a `AGENTS.md`. Lo que esas líneas deciden, qué modelo cumple cada rol y
con qué identificador, está en el mismo `models.yaml`.

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

## Cifras del informe que se apoyan en el repositorio de desarrollo

El informe marca como **«registro de desarrollo»** las cifras que no se pueden comprobar en este
repositorio, porque el archivo que las sostiene es un resultado intermedio retirado o el registro
de trabajo interno. **El repositorio privado de desarrollo queda archivado y no se borra.** La
tabla da, para cada cifra, el archivo, el commit, la fecha y el SHA-256 del archivo en ese commit
(`git show <commit>:<ruta> | shasum -a 256`), de modo que, si alguien lo pide, se pueda
comprobar que el archivo que se muestra es el mismo. Es el mismo patrón que la sección «Artefactos
retenidos» usa con los archivos que no se publican.

| Cifra, como la dice el informe | Archivo en el repositorio privado | Commit | Fecha | SHA-256 en ese commit | Qué dice el archivo |
|---|---|---|---|---|---|
| Costo total **USD 275,26**: 161,34 en diagnósticos, calibración y corridas superadas, y 113,92 en corridas finales | reconstrucción sobre los 79 JSON de `results/` que existieron en cualquier rama, más el gasto que no está en ninguna metadata | árbol de referencia `126ab2d3488ff30e2c2a80e01f6e34e583d15fd4` | 2026-10-15 | no aplica: es una suma sobre muchos archivos | 44 corridas contadas una vez cada una suman 269,22; más 6,04 fuera de la metadata, 275,26. De los 269,22, **115,17** están en JSON de este repositorio y **154,05** en JSON retirados. La regla está en la sección 8 de [`CIFRAS_INFORME.md`](CIFRAS_INFORME.md) |
| p95 del TTFT de `none` en frío de **5,55 s** | `results/e3_latency_v2.2.0.json` | `d6110d06f16d44bb0bace57c879d0aa24fd0da42` | 2026-09-08 (resultado 17:00:46 UTC) | `35d2476183b61115f70730a61a2e30eb853de3a9a811ea81abf63cb83245cff5` | p50 2,05 s y p95 5,55 s; agente 2.2.0, corpus v1.1; 20 casos × 5, en frío, con streaming y sin caché. La corrida de **2,20 s** es pública: `results/e3_latency.json` |
| Índice de catálogo de **10.353 a 4.365 tokens** | registro de trabajo interno | `761cacd38cd228be30e584543f0cc71e343ae8d5` | 2026-09-07 (13:19:44 UTC) | `01200f24f07af23b312c71db334e75f627b183b33e58f1859cc82e371a748820` | 22.550 caracteres y 10.353 tokens antes; 9.327 caracteres y 4.365 tokens después. El 4.365 también está en `tests/test_corpus_congelado.py`, que es público |
| Con una sola ejecución, `prompt_only` aprobó **22 de 22** ítems críticos | `results/e4_compliance_prompt_only_n1.json` | `4e68a4e20212a9d73848707c9d1dc5642b9fa164` | 2026-09-10 (resultado 2026-09-08 20:43:51 UTC) | `e67c62e0cb8093fad8966d8494e4ef0e2c4ab18df382396767420542dfc91509` | 22/22 críticos y 27/27 ítems; checklist 1.0.0, agente 3.0.0, corpus v1.2 |
| Línea base de E1, corrida 1 de 6 | `results/e1_baseline_v1.0.json` | `fe63a61827d4eb1d8cf12ee67580bc53a873401f` | 2026-09-07 (15:23:41 UTC) | `17ac248449e4076d0a272e200574d666180920979d9492e023ea9cb373bc9cca` | corpus v1.0, sin versión de agente; pass^1 `none`/`dual_llm`/`cte` 0,9107 / 0,9018 / 0,9524; comparación `none` 0,8839 y `cte` 1,0000: **ventaja de `cte` 0,116**. USD 18,82 |
| Línea base de E1, corrida 2 de 6 | `results/e1_baseline_v1.1_sin_cmp.json` | `68d224efb22aaa98122384b54a93cd9b1d7e028c` | 2026-09-07 (17:58:14 UTC) | `549b8cee8d036e094bfeb974d3c6fbe54b469748600953b0bff9edbc94e02018` | corpus v1.1; 0,9494 / 0,9435 / 0,9702; comparación 0,9196 y 1,0000: **ventaja 0,080**. USD 18,85 |
| Línea base de E1, corrida 3 de 6 | `results/e1_baseline_v1.1_cmp_marcador.json` | `ee0d9f53e6fc6b1b8cb55d6b50670d50b0854522` | 2026-09-07 (19:51:34 UTC) | `b9f6bac568e47f31d18744e01ed38ab0f20156c8ddfb59ea7edd8b6666210ea7` | corpus v1.1, con el marcador de comparación; 0,9702 / 0,9732 / 0,9286; comparación 0,9732 y 0,9018: la ventaja **se invierte**. USD 19,45 |
| Línea base de E1, corrida 4 de 6 | `results/e1_baseline_v2.0.0.json` | `0b93ee822fa9e907bfbb1385f6d110d207bf39ab` | 2026-09-07 (23:31:07 UTC) | `7c962021c439c0d2f6cb049137d2cd2f2c7b4f991623d8b063c1ee04ba381e09` | agente y evaluador 2.0.0, corpus v1.1; 0,9762 / 0,9732 / 0,9732; comparación 1,0000 y 0,9821. USD 19,92 |
| Línea base de E1, corrida 5 de 6 | `results/e1_baseline_v2.1.0.json` | `d6110d06f16d44bb0bace57c879d0aa24fd0da42` | 2026-09-08 (13:21:29 UTC) | `d552b2f4070759385b8a85f5172f9fea0d0a0c0866d41329d142999974991060` | agente y evaluador 2.1.0, corpus v1.1; 0,9673 / 0,9762 / 0,9732; comparación 0,9821 y 0,9911. USD 19,56. La corrida 6 es la publicada, `results/e1_baseline.json` |
| ASR **0,000 en 60 ejecuciones** con las plantillas de v1.0 | `results/e2_dev_none_3.0.0.json` | `1ee505b4e8031773e0f4169ac97e984500cf0aeb` | 2026-09-08 (resultado 17:17:48 UTC) | `c862cc788182eee0a9f22d504d66c7b765a7d9df4bb9a1dc1d30a3ed6815d3c8` | corpus v1.1, partición de desarrollo, 30 casos × 2, 0 éxitos. Declara el agente **3.0.0** con `git_dirty: true` y **sin huella de prompt**, porque esa huella todavía no existía: lo que sostiene que corrió sin cláusulas defensivas es la versión declarada del agente |
| Umbral anclado al IC: **0,783** con la línea base de v1.0 y **0,914** con la publicada | `results/e1_baseline_v1.0.json` | `fe63a61827d4eb1d8cf12ee67580bc53a873401f` | 2026-09-07 | `17ac248449e4076d0a272e200574d666180920979d9492e023ea9cb373bc9cca` | límite inferior del IC de pass^1 de `none` 0,8333; menos el margen de 0,05, **0,7833**. Con `results/e1_baseline.json`, que es público, 0,9643 − 0,05 = **0,9143** |

### El pre-vuelo: cinco versiones y qué corrida cubre cada pase

`scripts/prevuelo.py` escribe siempre en el mismo archivo y lo sobrescribe, así que las pasadas
anteriores solo sobreviven en el historial del repositorio privado. Las dos últimas son las que
este repositorio publica.

| Versión | Commit | Fecha | Agente | Aprobado | USD | Ejecuciones | SHA-256 |
|---|---|---|---|---|---:|---:|---|
| `results/prevuelo.json`, 1 | `74f7829ca161cfe71b5f36f4955b6298584de1ee` | 2026-09-08 | 3.0.0 | no | 2,5513 | 104 | `3f21c87830c0cde6870baf4fc6b4ee84291c7f699be8925a3e83c4cf02011b74` |
| `results/prevuelo.json`, 2 | `7e085575643bdeb6ff5540d1fee93464b446c20d` | 2026-09-08 | 3.0.0 | no | 2,4774 | 97 | `3fc1ec9a79e3e4bb8e10ec98c47d8b8ef596998566b239427c9a3ee3bc964753` |
| `results/prevuelo.json`, 3 | `f0f2e272acb0b8dc223639635f5135bae794fd3f` | 2026-09-08 | 3.0.0 | **sí** | 2,6422 | 105 | `b16c70027317b19b3d0aadea393487d87d6de67c8cf20ce9ddf4fc4a18c84cb7` |
| `results/prevuelo_aprobado.json` | `d6110d06f16d44bb0bace57c879d0aa24fd0da42` | 2026-09-08 | 3.0.0 | **sí** | 2,6422 | 105 | `b16c70027317b19b3d0aadea393487d87d6de67c8cf20ce9ddf4fc4a18c84cb7`, copia idéntica de la versión 3; **publicado** |
| `results/prevuelo.json`, 4 | `ab20a93978fb8f9f644f6643f78c17cd6bbc0fde` | 2026-10-11 | 3.0.1 | **sí** | 2,5995 | 104 | `1ea41f39e680f536256fee7d1de0a5abe0735c9cf88d406c4a7a0b7f5bfaa637`; **publicado** |

| Corrida final | Pase aprobado que la precede |
|---|---|
| E1 (`none`, `dual_llm`, `cte`), 2026-09-08 | el del agente 3.0.0 |
| E2 con Sonnet, 2026-09-08 | el mismo |
| E2 con Haiku, 2026-09-08 | el mismo |
| E3b con caché, 2026-09-09 | el mismo |
| E4 con cinco ejecuciones, 2026-09-10 | el mismo |
| E3 en frío, 2026-09-11 | el mismo |
| E1 `prompt_only`, 2026-10-11 | el del agente 3.0.1 |
| E2 portador descripción, 2026-10-11 | **ninguno** |
| `CUM-026`, 2026-10-11 | **ninguno** |

Es decir: **un pase aprobado precedió a cada bloque de corridas finales**, no a cada corrida, y
las dos corridas de octubre de E2 portador descripción y de `CUM-026` no tienen registro de
pre-vuelo.

### El criterio de salida de las calibraciones: cuándo quedó escrito

El criterio de salida, detenerse al llegar a una tasa de éxito sobre entregadas de 0,15 o con un
tope de tres rondas, quedó escrito por primera vez en el registro de trabajo interno, en el
commit `1ee505b4e8031773e0f4169ac97e984500cf0aeb`, el **2026-09-08 a las 18:00:31 UTC**, con SHA-256
`271143825b2a3561c0308077b5a071ab51545f28fd8e91bb800fd9cbfb72aff4`, y en el mismo commit en el
script que reporta cada ronda. No hay registro anterior en ningún documento ni en ningún código.

| Calibración | Ronda 1 | Ronda 2 | Ronda 3 | Primer registro escrito del criterio |
|---|---|---|---|---|
| Ataques de v1.2, septiembre | 2026-09-08 17:38:13 UTC | 17:45:50 | 17:51:54 | `1ee505b4…`, 18:00:31: **9 minutos después** de la ronda 3 |
| Portador descripción, octubre | 2026-10-11 16:21:07 UTC | 16:26:11 | 17:03:32 | el criterio genérico **ya estaba escrito**: seguía en el registro de trabajo interno en `660c49afbd2cf013ca3bed2a87925169b0473933`, a las 16:10:33, 11 minutos antes de la ronda 1. `docs/E2_PORTADOR_PREREGISTRO.md` nace en `591cd70f431ffc5a9f81ba21bc2e39e176308939` a las 17:06:55, **3 minutos y 23 segundos después** de la ronda 3, con SHA-256 `2620d51fdcfea047c3c52a3135a391e68f3b4d4aa0b940e8899f6ef3d401f632` en ese commit |

De la calibración de septiembre **no se puede decir que el tope estuviera prerregistrado**. De la
de octubre sí se puede decir que se le aplicó un criterio que ya estaba escrito, siempre que se
diga también que el documento que la declara se escribió al cerrarla. El
`docs/E2_PORTADOR_PREREGISTRO.md` de este repositorio es una revisión posterior de ese documento,
así que su huella actual no es la de la tabla.

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
