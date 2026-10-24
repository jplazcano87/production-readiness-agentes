# Registro de cambios

Formato de [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/). Las versiones siguen
[SemVer](https://semver.org/lang/es/).

Este archivo registra los cambios **del repositorio como software**. Los defectos que la
investigación encontró en sí misma y en el sistema que evalúa, con lo que cada uno cambió, están
en [`docs/REGISTRO_DE_DEFECTOS.md`](docs/REGISTRO_DE_DEFECTOS.md), que es otra cosa y se lee
aparte.

Las versiones de los componentes no siguen a la del paquete: el agente, el evaluador, el
criterio de ataque, el checklist y la política de aceptación llevan la suya, declarada en la
metadata de cada resultado, y describen con qué se midió.

## [Unreleased]

### Añadido

- El DOI de Zenodo en `CITATION.cff` y en los dos README: el de todas las versiones,
  `10.5281/zenodo.23403716`, y el de la versión 1.0.0, `10.5281/zenodo.23403717`. El registro de Zenodo se creó desde la
  release `v1.0.0`, que es el commit que publica esta versión; la entrada de abajo no cambia,
  porque el software publicado es el mismo.
- **La validación del criterio de ataque 1.2.0, reproducible desde el repositorio**, en
  `data/annotation/criterio_1.2.0/`:
  - la lista del **hold-out**: las 40 candidatas de la raíz de `results/runs_e2/`, las 4
    excluidas con el archivo público que justifica cada una y los dos veredictos recalculados
    (`scripts/e2_holdout_criterio.py`);
  - la **auditoría de falsos negativos repetida**, porque la muestra original no se conservó: la
    población de 1.304 y una muestra de 40 con la semilla del proyecto
    (`scripts/e2_muestra_auditoria_fn.py`), prerregistradas en el commit `f079bdf` antes de leer
    nada;
  - la regla de lectura, el generador de la hoja a ciegas (`scripts/e2_hoja_lectura_criterio.py`)
    y la lectura de las 76 ejecuciones, tal como se recibió, con su correspondencia;
  - `results/e2_auditoria_criterio_1.2.0.json`, que rehace sin API
    `scripts/e2_auditoria_criterio.py`: 0 falsos negativos de 40, IC 95 % [0, 0,088]; en el
    hold-out, precisión 0,333 con el criterio 1.0.0 y 1,00 con el 1.2.0, y recall 0,50 del 1.2.0
    sobre lo leído.
- Seis entradas nuevas en `docs/MANIFIESTO_ARTEFACTOS.json`, que pasa a cubrir la huella de los
  124 artefactos congelados y las 5 colecciones: el resultado y los cinco CSV. Ninguna entrada
  existente cambia. El verificador rehace en su copia aislada los tres pasos que los producen.
- Pruebas: `tests/test_hoja_lectura_criterio.py`, que la hoja no filtre configuración, modelo,
  fuente ni veredictos, y `tests/test_auditoria_criterio.py`, que cada pieza salga de la
  anterior.

### Corregido

Solo documentación, comentarios y docstrings. **Ningún artefacto congelado cambia y ninguna
cifra publicada cambia**: `docs/MANIFIESTO_ARTEFACTOS.json` queda igual, y los conteos de 32
defectos, 16 limitaciones de desarrollo y 7 de alcance siguen valiendo.

- `docs/CIFRAS_INFORME.md` §7, `docs/LIMITACIONES.md` (limitación 14) y una nota al pie de
  `docs/REGISTRO_DE_DEFECTOS.md` sobre el defecto 19: pass^k deja de presentarse como cota
  inferior de la utilidad percibida, como ya hacía el README. La fila 19 del registro no se
  reescribe.
- `docs/CIFRAS_INFORME.md` §7: la κ entre juez y anotación del autor es 1,0, como da
  `results/e6_judge_agreement.json`, y no «sin definir».
- `docs/LIMITACIONES.md` (limitación 2): fueron cinco intenciones, no cuatro casos, como dicen el
  defecto 7 y el manifiesto de v1.1.
- `docs/DATASHEET.md`: los dos DOI de Zenodo, en lugar de «No hay DOI todavía».
- `docs/PROCEDENCIA.md`: sección nueva sobre metadatos congelados que se leen con una
  corrección: el corpus que declara `results/e2_security_v1.3.json`, las tres versiones de los
  resultados de E4 con el checklist 1.2.0, la versión del agente de E4 en
  `configs/congelado_corrida_final.json`, las 26 transcripciones que son 25, los campos de diseño
  de `configs/experiments.yaml` y el comentario desactualizado de `src/prf/agent/prompts.py`.
- `docs/CIFRAS_INFORME.md` §8 bis: el 0/27 de la ronda 2 de calibración del portador descripción
  es con el criterio 1.2.0; el archivo guarda la lectura literal, 1/27.
- `docs/CIFRAS_INFORME.md`, tabla 3: nota sobre `unauthorized_promise`, que se mide por la
  invocación efectiva de `apply_discount` o `send_message` y no por lo que la respuesta promete.
- README, en los dos idiomas: qué lleva el system prompt de cada configuración, incluido el
  párrafo de advertencia que también recibe `dual_llm`, y la temperatura de cada rol.
- `scripts/calibrate_thresholds.py` y un comentario de `tests/test_config.py`: la cifra del umbral
  descartado es 0,914, la del changelog de `configs/thresholds.yaml`, y la precisión es ±0,02.
- `data/generators/casos_seguridad.py`: el docstring de `correo_simulado` ya no dice que
  `example.cl` esté reservado. El código no cambia.

## [1.0.0] - 2026-10-15

Primera versión pública. El contenido medido no cambia: ningún resultado, ninguna
transcripción, ningún archivo del corpus y ningún texto de prompt se tocó para publicar. Lo que
cambia es todo lo que rodea a eso.

### Añadido

- **Verificador de equivalencia** (`scripts/verificar_equivalencia.py`): comprueba las huellas
  de los 118 artefactos congelados y las 5 colecciones, y en modo `--completo` rehace doce
  pasos sin API en una copia aislada del árbol, con su propio entorno virtual y el paquete
  instalado no editable, y compara Markdown y CSV byte a byte, PNG píxel a píxel y JSON campo a
  campo. Comprueba además el contrato de rutas del informe, las huellas de los prompts, lo que
  las herramientas entregan al agente y que ningún archivo publicable traiga el número retenido.
- **`docs/MANIFIESTO_ARTEFACTOS.json`**: el SHA-256 de cada artefacto congelado, los hashes de
  árbol de las colecciones y el registro de lo retenido. Solo gana entradas.
- **Las 86 transcripciones de la raíz de `results/runs_e2/`**: las 60 de la compuerta del
  modelo pequeño, que su resultado declara y ningún directorio por corrida recogió,
  `SEG-BEN-040__cte__2`, de la corrida final con Sonnet, y las 25 del piloto de la corrida con
  Haiku, que bloqueó esa corrida y obligó a corregir dos defectos del arnés.
- Con `SEG-BEN-040__cte__2` recuperada, la cobertura de transcripciones de E2 sube a **1.403 de
  1.428**: `docs/CIFRAS_INFORME.md` lo registra y explica por qué la metadata congelada sigue
  declarando 1.402.
- **Las tres rondas de calibración de los ataques de v1.2** (`results/e2_cal_r{1,2,3}.json`),
  de septiembre: 30 casos de la partición de desarrollo por 2 ejecuciones sobre `none`, con
  tasas de éxito de 0,017, 0,050 y 0,050. Son la evidencia de que la fuerza de los ataques se
  ajustó sin ejecutar la partición de prueba. Sus transcripciones no existen, y
  `docs/PROCEDENCIA.md` explica por qué.
- **Las transcripciones de las ejecuciones medidas**, en los cinco directorios de
  `results/runs_*/`: `runs_e1` (1.348 archivos), `runs_e2` (2.451), `runs_e3` (400), `runs_e4`
  (726) y `runs_e4_v2.0.0` (50). Los tres primeros no estaban bajo control de versiones y son
  4.199 archivos nuevos; los dos de E4 ya estaban. Es lo que permite reaplicar el evaluador y el
  checklist sin llamar a la API.
  - `runs_e1` son las 1.344 ejecuciones de la partición de prueba (42 casos × 8 repeticiones ×
    4 configuraciones), más 4 de la partición de desarrollo que son las pantallas de práctica
    del instrumento de anotación.
  - `runs_e2` se reparte en `e2_security` (1.150), `e2_security_haiku` (882),
    `e2_portador_descripcion` (252) y las tres rondas de calibración del portador descripción
    (27 cada una).
  - **No se publican**: las ejecuciones de la partición de desarrollo de E1 (104, salvo las 4 de
    arriba), los tres directorios de E1 de versiones anteriores del agente
    (`results/runs_e1_*/`) y los tres originales retenidos por el teléfono que inventó el
    modelo, que se publican como copias `.redactado.json`.
  - En la raíz de `runs_e2/`, donde el arnés escribía antes de usar un directorio por corrida,
    quedan 86 archivos y se publican los 86: las 60 que declara
    `results/e2_compuerta_haiku.json`, `SEG-BEN-040__cte__2`, que es la única de las 26
    ejecuciones de E2 con Sonnet sin ruta declarada cuyo archivo sigue siendo el suyo, y las 25
    del piloto de la corrida con Haiku, que no son la medición: corrieron con el agente 3.0.0 y
    lo medido es con 3.0.1. `docs/PROCEDENCIA.md` explica las tres, incluida la advertencia de
    que las rutas que declaran las rondas de calibración llevan a las transcripciones de la
    compuerta.
- **Documentación**: `README.md` y su traducción `README.en.md`;
  `docs/REPRODUCIBILIDAD.md`, `docs/PROCEDENCIA.md`, `docs/DATASHEET.md`,
  `docs/LIMITACIONES.md` y `docs/REGISTRO_DE_DEFECTOS.md` con los 32 defectos.
- **Archivos de comunidad**: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant 3.0),
  `SECURITY.md`, `CITATION.cff` y este registro. `AGENTS.md` queda con las instrucciones
  operativas para un agente y remite a `CONTRIBUTING.md` para la política.
- **Herramientas**: `.pre-commit-config.yaml` con doce ganchos, incluido el escaneo de secretos,
  y `requirements-lock.txt` con las 40 dependencias fijadas.
- **Automatización de GitHub**: `.github/workflows/ci.yml` con pruebas y estilo en Python 3.11 y
  3.12, el verificador de equivalencia en su modo completo y el escaneo de secretos, con las
  acciones fijadas por SHA y el token de solo lectura; `dependabot.yml` mensual para las
  acciones de GitHub; plantillas de issue para error, mejora y discrepancia en un resultado, con
  los issues en blanco desactivados y lo de seguridad derivado al canal privado; plantilla de
  pull request con la compuerta; y `CODEOWNERS`.
- `requirements-lock.txt` pasa a estar **congelado** en `docs/MANIFIESTO_ARTEFACTOS.json`: es el
  registro del entorno de las corridas de octubre, así que modificarlo falla en las pruebas y en
  el CI. El entorno aislado del verificador y el trabajo de equivalencia lo usan como
  restricción (`pip install -c`), de modo que la comparación de figuras no dependa de qué
  versión de la pila de dibujo se resuelva ese día.
- **Pruebas** de las reglas de publicación y de cada cifra de los dos README, leída desde
  `results/` en el momento de correr. La suite completa pasa sin red.

### Cambiado

- **Versión del paquete a 1.0.0** en `pyproject.toml`.
- Los tres archivos cuyo contenido incluía un teléfono móvil con formato válido, inventado por
  el modelo, se publican como copias `.redactado.json`, idénticas salvo los ocho dígitos. Los
  originales se retienen, con su SHA-256 en el manifiesto y en `docs/PROCEDENCIA.md`, y
  `tests/test_checklist_regresion_v2_0_0.py` comprueba que la redacción no cambia ninguno de los
  28 estados del checklist.
- La reclasificación de E2 con el criterio de ataque 1.2.0 entra en los pasos que el verificador
  rehace, en lugar de quedar como una corrida manual.
- Legibilidad: ayuda de los scripts, anotaciones de tipo, docstrings y un lector de JSONL y un
  cálculo de SHA-256 únicos, en `src/prf/infra/archivos.py`.

### Corregido

- `scripts/make_tables.py` no escribía el salto de línea final en
  `tables/e1_casos_dificiles.md`, así que el archivo publicado y el regenerado diferían en un
  byte. Se corrigió en el generador, no en el archivo.

### Quitado

Cincuenta archivos y ocho elementos de código, ninguno de ellos parte de lo que se midió. Las
cinco versiones del corpus (v1.0 a v1.4) y sus particiones se publican completas, y ningún
resultado ni transcripción de las corridas finales se retiró.

- **Veintisiete resultados intermedios** de `results/`: las líneas base de versiones anteriores
  del agente (`e1_baseline_v1.0`, `_v1.1_sin_cmp`, `_v1.1_cmp_marcador`, `_v2.0.0`, `_v2.1.0`),
  las corridas de desarrollo (`e1_dev_*`, `e2_dev_none_3.0.0`, `e4_dev_*`), las de una sola
  ejecución por caso (`e4_compliance_*_n1`), y las de checklist 1.0.0 y agente 2.1.0 y 2.2.0.
- **El corpus de desarrollo `v1.3-dev`** y su partición, con que se calibró el portador
  descripción. Las versiones medidas no se tocan.
- **Cuatro scripts de un solo uso** (`scripts/e1_repuntuar.py`, `scripts/calibrar_ataques.py`,
  `scripts/cal_reporte.py` y `data/generators/corregir_intenciones.py`): leen artefactos que no
  se publican, así que en este repositorio no se pueden ejecutar.
- **`configs/thresholds.propuesta.yaml`**, salida intermedia de la calibración de umbrales. El
  script que la produce, `scripts/calibrate_thresholds.py`, se queda: es la procedencia de la
  política.
- **Cuatro figuras de la raíz de `figures/`**, versiones anteriores de las mismas cinco que
  están en `figures/informe/`, que son las que el verificador rehace píxel a píxel. Y dos tablas
  superadas, `tables/corpus_stats_v1.2.md` y `tables/e5_verdict.md`.
- **Material de proceso de `docs/`**: el plan por etapas, con el calendario académico, y el
  registro de trabajo interno. Lo que de ahí pertenece a una publicación quedó reescrito en
  `docs/REGISTRO_DE_DEFECTOS.md` y `docs/LIMITACIONES.md`.
- Dos `.gitkeep` de directorios de plantillas vacíos.
- **Ocho elementos de código que nada usaba**, cada uno con la evidencia de que ninguna ruta de
  ejecución, prueba ni script lo alcanzaba. Ninguno era un campo de datos de un artefacto
  congelado.
