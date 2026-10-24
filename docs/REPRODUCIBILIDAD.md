# Reproducibilidad

Qué se puede volver a producir desde este repositorio, qué no, y con qué exactitud en cada
caso. La distinción importa: hay artefactos que se rehacen byte a byte sin gastar un peso, y
hay otros que no se pueden rehacer en absoluto, porque exigen volver a llamar a un modelo que
no es determinista.

## Lo que se rehace sin llamar a la API

Doce pasos. El verificador los ejecuta y compara cada archivo que escriben con el publicado.

```bash
python scripts/verificar_equivalencia.py --completo
```

| Paso | Qué reescribe |
|---|---|
| `make_splits.py --check` | las particiones de la versión vigente y su resumen |
| `corpus_stats.py` | las estadísticas descriptivas del corpus |
| `make_figures.py --informe` | las cinco figuras del informe |
| `make_tables.py` | las dos tablas de resultados por configuración |
| `e1_analisis_casos.py` | la tabla de casos difíciles |
| `e1_veracidad_retro.py` | el ítem de veracidad aplicado a las ejecuciones de E1 ya medidas |
| `e2_vista_combinada.py` | la vista combinada de seguridad |
| `e2_reclasificar.py --entrada e2_security` | la corrida de Sonnet releída con el criterio vigente |
| `e2_reclasificar.py --entrada e2_security_haiku` | lo mismo con la corrida de Haiku |
| `e6_kappa_ciego.py` | el resultado de la anotación a ciegas |
| `e6_exploratorio.py` | las lecturas exploratorias de esa anotación |
| `run_e5.py --todas --sufijo v0.3.0` | los cuatro veredictos y su tabla |

Son doce pasos y diecinueve archivos. Markdown y CSV se comparan **byte a byte**; los PNG,
**píxel a píxel**, porque matplotlib escribe la fecha de creación en los metadatos del archivo;
los JSON, **campo a campo**.

### Los campos que se ignoran, y por qué

Dos listas, en el propio script, y la diferencia entre ellas es deliberada.

**Volátiles**, siete campos que cambian solos en cada ejecución:
`metadata.timestamp`, `metadata.git_commit`, `metadata.git_dirty`, y los cuatro
`versiones.por_resultado.*.timestamp` que el veredicto copia de los resultados que agrega.

**Descriptivos**, uno: `metadata.reclasificado.motivo`. No cambia solo, lo cambia una edición, y
por eso va en su propia lista y de una en una. Su texto citaba un identificador de un registro
de desarrollo que no se publica y se reescribió con la explicación; lo que decide, la
clasificación de cada ejecución, es idéntico en las 1.176 observaciones de Sonnet y las 882 de
Haiku.

Todo lo que no esté en esas dos listas tiene que coincidir.

### El aislamiento forma parte de la comprobación

`prf.infra.paths` resuelve la raíz del proyecto subiendo desde el archivo del paquete hasta el
`pyproject.toml` que lo contiene. Con una instalación **editable**, ese archivo vive en el
repositorio, así que un script escribe ahí aunque se lance desde otro directorio: cambiar de
directorio de trabajo no aísla nada.

Por eso el modo completo:

1. prepara una copia desechable del árbol en un directorio temporal;
2. crea **su propio entorno virtual** dentro de la copia e instala el paquete **no editable**,
   con lo que la raíz cae en el directorio de trabajo, que es la copia;
3. lo comprueba antes de correr nada: una sonda verifica que `prf.__file__` y `paths.root`
   estén dentro de la copia, y si no, se detiene;
4. compara `git status` y `HEAD` del repositorio real antes y después, y falla si algo cambió;
5. comprueba además que ningún paso tocó un artefacto congelado que no hubiera declarado.

## La referencia de salida de herramientas

`docs/SALIDA_DE_HERRAMIENTAS.json` fija, para un caso de cada dimensión, lo que devuelven
`search_catalog`, `get_product` y `get_reviews` en **dos capas**:

| Capa | Qué contiene | Qué protege |
|---|---|---|
| `del_sandbox` | lo que pasa por `dispatch`, ya sin las anotaciones del andamiaje | que el agente no vuelva a recibir cada ataque indirecto etiquetado como ataque |
| `con_la_defensa_que_quita_la_descripcion` | la parte determinista de `dual_llm` y `cte` | que la descripción comercial no vuelva a llegar al modelo privilegiado |

Cubre un hueco que las otras comprobaciones dejan abierto. Las huellas del manifiesto cubren los
archivos del corpus y las de los prompts cubren el prefijo de la petición, pero entre medio está
**el código que sirve esos datos**: un campo nuevo en un modelo, un filtro que deja pasar una
clave más o un orden de resultados distinto cambian lo que el agente ve sin tocar ni el corpus
ni el prompt. Los dos defectos más graves del instrumento vivían justo ahí.

Lo que la cuarentena resume con un modelo queda fuera, porque exigiría llamar a la API.

### Cómo regenerarla si un cambio legítimo la altera

Igual que el manifiesto: de forma explícita y con motivo, nunca en silencio.

```bash
python scripts/verificar_equivalencia.py --generar-salida-herramientas
```

El comando **falla si el archivo ya existe**. Regenerarla exige borrarla a mano, y el pull
request que lo haga tiene que explicar en su descripción qué cambió en lo que el agente recibe y
por qué ese cambio es correcto. Un cambio en esta referencia no es un detalle de formato: es un
cambio en la entrada de todas las mediciones.

## Lo que necesita la API, y por qué no es byte a byte

Los seis experimentos. Los modelos no son deterministas ni con temperatura cero, así que
**volver a correr E1 a E6 no reproduce los mismos archivos**: reproduce, si el marco está bien
hecho, las mismas conclusiones dentro de los intervalos publicados.

```bash
python scripts/run_e1.py --dry-run     # siempre primero
python scripts/prevuelo.py             # estáticas, dinámicas y costo, antes de gastar
python scripts/run_e1.py
```

Lo que sí se puede comprobar sin volver a medir:

- **El corpus es el mismo**: cada versión lleva su hash de contenido y el manifiesto lo fija.
- **El agente es el mismo**: las huellas de los system prompts se comparan con las que dejó
  congeladas la corrida final.
- **La puntuación es la misma**: la evaluación de estado y el checklist son deterministas y se
  reaplican sobre las transcripciones persistidas, sin llamar a la API.
- **Lo que costó**: cada resultado registra los tokens y el costo real de su corrida.

### Qué se salta, y dónde

La suite corre **sin ningún fallo** en el repositorio, en un clon del repositorio público y en
una copia sin historial. Lo que cambia entre los tres es qué se salta, y cada salto imprime su
motivo. Por categoría, que es lo estable: los conteos cambian con cada prueba nueva.

- **Solo en una copia sin historial** (el ZIP de la release, la copia de Zenodo): las pruebas que
  le preguntan a git qué archivos están versionados para comprobar las reglas de publicación.
  Sin `.git` esa pregunta no tiene respuesta. El motivo del salto es **la ausencia de `.git`**,
  no un error de git: si `.git` está y git falla, la prueba falla. En el repositorio y en su CI
  corren siempre.
- **En cualquier clon del repositorio público**, y también en una copia sin historial: la
  regresión que compara la copia redactada con el original retenido, y la que comprueba la
  huella del HTML de anotación que se entregó. Las dos piden archivos que no se publican: los
  originales retenidos, por el teléfono que inventó el modelo, y un entregable que se genera y
  no se versiona.
- **En cualquier entorno, incluido este repositorio**: las del registro de lo congelado para la
  corrida final, que solo corren cuando el `HEAD` es el tag de esa corrida. En el repositorio
  público ese tag no existe, porque los tags del repositorio privado no viajan; aquí se saltan
  en cuanto el `HEAD` avanza, que es casi siempre.

## Versiones

### Lo que fija el bloqueo

`requirements-lock.txt` fija 40 dependencias con `==`, generado con `uv pip freeze` desde el
entorno del repositorio. Entre ellas `anthropic==1.4.0`, `pydantic==2.13.5`, `numpy==2.4.6`,
`pandas==3.0.5`, `matplotlib==3.11.1` y `scipy==1.17.1`.

Se generó con **Python 3.11.16 sobre macOS (arm64)**. Las ruedas de `numpy`, `scipy`,
`matplotlib` y `pandas` son específicas de plataforma, así que en Linux o Windows el instalador
resolverá otras del mismo número de versión. Para esos entornos, `pyproject.toml` declara los
mínimos y deja resolver: el bloqueo existe para reproducir, no para instalar.

### El vacío conocido

**Los resultados congelados no registran la versión del SDK ni de ninguna dependencia.** Su
metadata lleva la semilla, el corpus y su hash, el modelo, las versiones del agente, del
evaluador y del criterio de ataque, el commit y el modo de API, pero no el entorno de Python.
Es una omisión del diseño de la metadata y se declara como tal.

### Qué se pudo reconstruir, y qué no

Las fechas de instalación de los paquetes (`*.dist-info/INSTALLER`) comparadas con la marca de
tiempo de cada corrida dan este cuadro:

| Cuándo | Qué |
|---|---|
| 2026-09-07 a 2026-09-11 | las corridas de E1, E2 (Sonnet y Haiku), E3, E4 y el juez de E6 |
| **2026-09-28** | **se reinstalaron 38 paquetes**, la pila de cálculo entera |
| 2026-10-11 | se añadieron 3 paquetes del navegador, para el instrumento de anotación |
| 2026-10-11 a 2026-10-14 | las corridas de `prompt_only`, del portador descripción, del caso de cumplimiento nuevo y de la anotación a ciegas |

De ahí se sigue, con precisión:

- Para las corridas de **octubre**, el bloqueo **es** su entorno: nada se instaló después.
- Para las corridas de **septiembre**, no se puede afirmar lo mismo. Hubo una reinstalación
  posterior. Las fechas no dicen si las versiones cambiaron, solo que los archivos se
  reescribieron: una reinstalación de las mismas versiones deja la misma huella.

### Lo que sí se puede afirmar sobre esas corridas

**El rodeo del SDK está comprobado contra el paquete instalado.**
`src/prf/infra/client.py` lleva desde antes de las corridas de septiembre un rodeo: envía
`temperature`, `top_p` y `top_k` por `extra_body` en lugar de pasarlos como argumentos. En el
`anthropic` 1.4.0 instalado eso es necesario y suficiente: la firma de
`Messages.create` no acepta ninguno de los tres y sí acepta `extra_body`. Lo que no se puede
comprobar sin red es en qué versión desaparecieron de la firma, así que de aquí **no se deduce
una cota inferior** para el entorno de septiembre; solo que el código ya enviaba esos campos
por `extra_body` cuando se midió.

**La pila numérica se comporta igual.** Los doce pasos sin API rehacen los artefactos
publicados con el entorno de hoy, **las cinco figuras del informe píxel a píxel incluidas**, y
varios de esos pasos recalculan intervalos de confianza, percentiles y bootstrap sobre las
mismas transcripciones. Para `numpy`, `scipy`, `pandas` y `matplotlib` eso es evidencia directa
de que producen los mismos números y los mismos gráficos que la pila con que se midió. No es
una prueba de que las versiones fueran idénticas; es una prueba de que la diferencia, si la
hubo, no afecta a ningún resultado publicado.

### El modo completo en otra plataforma, y qué se hará si difiere

Las cinco figuras se comparan **píxel a píxel**, y eso se verificó en la plataforma donde se
generaron: macOS arm64, con las versiones de `requirements-lock.txt`. El CI corre la misma
comparación en Linux, sin aflojarla, y hay una razón para esperar que coincida y otra para no
darlo por hecho: las ruedas de `matplotlib` traen su propia copia de la tipografía y de la
biblioteca de trazado, lo que hace el renderizado estable entre plataformas, pero una rueda
compilada para otra arquitectura puede trazar de forma distinta aunque la versión sea la misma.

Desde el PR de la automatización, el entorno aislado instala con `requirements-lock.txt` como
**restricción** (`pip install -c`), así que las versiones de la pila de dibujo son las mismas que
produjeron las figuras y lo único que queda distinto entre macOS y Linux es la rueda. Las 40
versiones del bloqueo tienen rueda para Linux y Python 3.11, comprobado contra PyPI.

Si alguna vez difiere, **la comparación no se afloja**. Lo que se hace es esto, en este orden:

1. Leer el mensaje del verificador, que ahora dice cuántos canales difieren, en qué proporción y
   cuál es la diferencia máxima. Unos pocos canales con delta pequeño es renderizado; muchos
   canales o un delta grande es que la figura cambió de datos, que es un defecto y se registra.
2. Si es renderizado, se declara aquí la plataforma de referencia y las versiones con que la
   igualdad píxel a píxel se sostiene, y la comparación de figuras se exige en esa plataforma,
   no en todas.
3. Lo que **no** se hace es introducir una tolerancia silenciosa: una comparación con holgura
   que nadie fijó de antemano deja de distinguir las dos cosas del punto 1, que es justamente
   para lo que existe.

### Nota del 15 de octubre de 2026: qué se observó, y cuándo se fijó el límite

Lo de arriba se escribió antes de correr el modo completo en Linux. Esta nota se añade después,
y hay que leer las dos juntas, porque **el orden importa y no fue el ideal**.

Ese día el modo completo corrió por primera vez en `ubuntu-latest`, con las versiones del
bloqueo. **Cuatro de las cinco figuras salieron idénticas** y una difirió:

| Figura | Canales distintos | De cuántos | Proporción | Delta máximo |
|---|---:|---:|---:|---:|
| `figures/informe/fig1_esquema_marco.png` | 837 | 4.056.000 | 0,021 % | **1** de 255 |

**El límite que hoy aplica el verificador, delta ≤ 1 y menos de un canal por mil, se fijó después
de esa observación, no antes.** El punto 3 de arriba decía que no se introduciría una tolerancia
que nadie hubiera fijado de antemano, y esto es exactamente una tolerancia fijada después. Queda
dicho aquí en lugar de presentarse como un criterio previo.

Las razones por las que se fijó así, que son las que hay que discutir:

- **Un canal sobre 255 en dos canales de cada diez mil es antialiasing, no datos.** El redondeo
  del suavizado de un borde mueve el último bit de los píxeles del contorno. Un cambio de datos
  mueve regiones enteras y con deltas grandes: una barra que cambia de altura, una curva que se
  desplaza, una celda con otro número.
- **La figura que difiere es el esquema del marco, y no grafica ninguna medición.** Dibuja la
  estructura de las tres dimensiones y los umbrales de la política; sus valores vienen de
  `configs/thresholds.yaml`, que es un artefacto congelado y se comprueba por su SHA-256 en
  cualquier plataforma. Las cuatro que sí grafican datos salieron idénticas.
- Los datos que grafican esas cuatro se comprueban **de forma exacta y en cualquier plataforma**
  por otros pasos del verificador, no por la imagen: el corpus de `fig2` y `fig3` por el hash de
  `data/corpus/v1.4/` más `corpus_stats.py` → `tables/corpus_stats.md` byte a byte y
  `make_splits.py --check`; el `pass^k` de `fig4` por el hash de `results/e1_baseline.json` y
  `e1_prompt_only.json` más `e1_analisis_casos.py` → `tables/e1_casos_dificiles.md` byte a byte;
  y la tasa de éxito de ataque y la utilidad de `fig5` por `e2_vista_combinada.py` →
  `results/e2_security_v1.3.json` campo a campo más `make_tables.py` →
  `tables/e2_e3_summary.md` byte a byte.

Cómo quedó, para que se pueda auditar:

- **La plataforma de referencia de las figuras es `Darwin/arm64`**, donde se generaron. Ahí el
  verificador exige igualdad exacta y cualquier diferencia falla.
- En otra plataforma, una diferencia de **delta ≤ 1 y menos de un canal por mil** se declara
  como diferencia de renderizado: se imprime con sus cifras en una sección propia del informe
  del verificador y no hace fallar. Todo lo que pase ese límite falla, en cualquier plataforma.
- Las constantes son `PLATAFORMA_DE_LAS_FIGURAS`, `DELTA_DE_PLATAFORMA` y
  `PROPORCION_DE_PLATAFORMA` en `scripts/verificar_equivalencia.py`, y
  `tests/test_verificar_equivalencia.py` comprueba los tres casos: en su plataforma cualquier
  diferencia falla, fuera de ella un canal se declara, y fuera de ella una diferencia de datos
  sigue fallando.

Lo que esto cuesta, dicho claro: **en Linux, la igualdad de las figuras se comprueba con una
holgura de un canal**, y por lo tanto un cambio que moviera un solo canal de un solo píxel
pasaría ahí. En la plataforma de referencia no pasaría. Las otras comparaciones del modo
completo no cambian: Markdown y CSV siguen byte a byte, y JSON campo a campo.

## Semillas y determinismo

La semilla global es `20260906` y está en `configs/experiments.yaml`. Fija la generación del
corpus, las particiones, el remuestreo de los intervalos y el orden de la muestra de anotación.
Las particiones son **estables entre versiones del corpus**: al reparticionar se le pasa la
asignación de la versión base, porque sin eso añadir un caso rebaraja su estrato y mueve casos
ya medidos.

Lo que la semilla no fija es la respuesta del modelo. Esa es la fuente de no determinismo que
pass^k existe para medir.
