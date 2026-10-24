# production-readiness-agentes

Un marco para decidir si un agente conversacional basado en un modelo de lenguaje está listo
para producción, y un caso completo donde se aplica: un agente de pre-venta de una tienda de
electrónica ficticia.

La pregunta que este marco intenta responder no es si el agente funciona bien. Es **si funciona
bien lo suficiente, y de forma lo bastante consistente, como para dejarlo frente a clientes**.
Son dos cosas distintas y la segunda se mide poco. El agente sin defensa acierta el 98,5 % de
los intentos, y sin embargo **solo 39 de los 42 casos se resuelven las ocho veces seguidas**.
Esa diferencia es la que decide si alguien lo pone en producción.

El marco mide tres dimensiones y las consolida en un veredicto conjuntivo. Vinculan la
robustez, la seguridad, el cumplimiento y, de la operación, **solo el sobrecosto de latencia**
medido con las cuatro configuraciones intercaladas. El TTFT absoluto se mide y se reporta, pero
no decide: su valor mide la carga del proveedor tanto como el sistema.

| Dimensión | Qué pregunta | Métrica |
|---|---|---|
| **Robustez** | ¿Resuelve la tarea de forma consistente, pese al no determinismo? | pass^k, con estimador insesgado e intervalo por remuestreo sobre casos |
| **Seguridad** | ¿Resiste la inyección de instrucciones, directa e indirecta? | tasa de éxito de ataque, por vector y por objetivo, más la utilidad en casos benignos |
| **Cumplimiento** | ¿Satisface obligaciones normativas comprobables? | checklist ejecutable derivado de la Ley N° 21.719 de Chile y de la circular SERNAC 2022 |

## Eficacia no es eficiencia

El resultado que más cuesta ver con una sola corrida es que **las defensas contra inyección
apenas cuestan eficacia y sí cuestan mucho tiempo**. Las cuatro configuraciones resuelven la
tarea casi igual de bien, y una de ellas tarda casi siete veces más en empezar a
responder.

Las cuatro configuraciones que se comparan:

- **`none`**: sin defensa. Es la línea base, y para que lo sea de verdad su prompt no niega por
  adelantado ninguno de los objetivos de ataque del corpus.
- **`prompt_only`**: la defensa vive solo en el system prompt: las cláusulas que niegan cada
  objetivo de ataque y un párrafo que ordena tratar el contenido recuperado como datos no
  confiables.
- **`dual_llm`**: el contenido no confiable (reseñas, descripciones) pasa por un modelo en
  cuarentena que devuelve un resumen estructurado; el modelo privilegiado nunca ve el texto
  crudo. Su system prompt lleva además **el mismo párrafo de advertencia** que `prompt_only`,
  pero no las cláusulas: lo que la separa de `prompt_only` es la cuarentena y la ausencia de
  cláusulas, no la advertencia.
- **`cte`**: Code-Then-Execute simplificado, inspirado en CaMeL. Un planificador escribe un plan
  y un intérprete lo ejecuta, de modo que el texto no confiable no puede cambiar el flujo de
  control. No es una réplica de CaMeL. El planificador tiene su propio system prompt, sin el
  párrafo de advertencia ni las cláusulas.

Las definiciones están en [`src/prf/agent/configuraciones.py`](src/prf/agent/configuraciones.py).

**Modelos y temperaturas**, según [`configs/models.yaml`](configs/models.yaml): el agente
(`claude-sonnet-4-6`) corre con temperatura **1,0**, a propósito, porque pass^k mide el efecto
de ese no determinismo; el simulador de usuario y la redacción del corpus
(`claude-haiku-4-5-20251001`), con **0,7**; y el planificador de Code-Then-Execute y el juez
(Sonnet) y el modelo en cuarentena (Haiku), con **0**. El pensamiento extendido está desactivado
en todos los roles.

## Resultados

Medido con `claude-sonnet-4-6` como agente, sobre la **partición de prueba** del corpus
sintético congelado: 179 de sus 256 casos. El cumplimiento es la excepción y se mide sobre sus
26 casos completos. Cada cifra sale de un archivo de [`results/`](results/), y
[`docs/CIFRAS_INFORME.md`](docs/CIFRAS_INFORME.md) dice de cuál.

| | `none` | `prompt_only` | `dual_llm` | `cte` |
|---|---:|---:|---:|---:|
| **Veredicto** | GO | GO | GO | **NO-GO** |
| pass^1 | 0,985 | 0,979 | 0,973 | 0,970 |
| pass^8 | 0,929 | 0,905 | 0,952 | 0,952 |
| Tasa de éxito de ataque, global | 0,004 | 0,000 | 0,004 | 0,011 |
| … por vector directo | 0,000 | 0,000 | 0,012 | 0,036 |
| … por vector indirecto | 0,005 | 0,000 | 0,000 | 0,000 |
| Utilidad en casos benignos | 1,000 | 0,988 | 0,988 | 0,988 |
| TTFT p95 | 2,20 s | 2,42 s | 2,85 s | **15,31 s** |
| Sobrecosto de latencia frente a `none` | 1,00× | 1,10× | 1,29× | **6,95×** |
| Ítems críticos de cumplimiento | 23/23 | 23/23 | 23/23 | **22/23** |

Tres lecturas que la tabla sostiene y conviene no estirar:

**Ninguna defensa degrada la robustez de forma interpretable.** Las diferencias en pass^8
equivalen a uno o dos casos de 42 y los intervalos se solapan en los seis pares. Lo que el
experimento sostiene no es que una configuración sea mejor que otra, sino que ninguna cae por
debajo de la línea base más allá del margen que la política fija, **0,05 sobre pass^1**.

**El costo de las defensas es de tiempo de espera, no de acierto ni de trabajo total.**
`dual_llm` cuesta un 29 % de TTFT y `cte` casi siete veces. Lo que conviene leer junto: la
latencia **extremo a extremo** de `cte` es la más baja de las cuatro, 0,79× la de la línea base
en p95. No es que haga más trabajo, es que **no muestra nada mientras planifica y ejecuta**: el
cliente espera 11,86 segundos frente a una pantalla vacía en la mediana, y 15,31 en el
percentil 95.

El veredicto sí lo captura, por el sobrecosto: 6,95× frente a un tope de 2,0×, y es una de las
dos reglas que dejan a `cte` en NO-GO. Lo que no vincula es el TTFT absoluto, cuyo objetivo de
1,5 s **no cumple ninguna de las cuatro configuraciones**. Está declarado en
[`docs/LIMITACIONES.md`](docs/LIMITACIONES.md).

**La política no es una propiedad del sistema sino del par sistema-modelo.** Tres de las
configuraciones se midieron también con `claude-haiku-4-5`, sobre el mismo corpus y con el
mismo criterio. La tasa de éxito de ataque pasa de 0,005 a **0,129** sin defensa, queda en
**0,081** con Dual LLM y sube a **0,186** con Code-Then-Execute, que llega a **0,464 en el
vector directo**. **Ninguna de las tres cumple seguridad.** Cambiar de modelo obliga a volver a
medir.

### Por qué `cte` reprueba

El veredicto cita la regla y su valor. `cte` incumple `cumplimiento.items_criticos`, con 22 de
23 ítems críticos, y `operacion.sobrecosto_latencia`, con 6,95× sobre un límite de 2,0×.

El ítem crítico que falta no reprueba: queda **no evaluable**. Es la veracidad del precio, y el
motivo está en el caso que lo ejercita, `CUM-003`, donde el cliente pregunta «el precio exacto
de ese producto» sin nombrarlo. El patrón de un solo paso de `cte` no puede repreguntar, así
que la respuesta no cita ningún producto del catálogo y no hay precio que comprobar. Un ítem
crítico que no se puede evaluar no se da por aprobado.

Aparte de eso, y como diagnóstico que **no entra en el veredicto**, el ítem de veracidad de
resultados aplicado a las 1.344 ejecuciones de robustez marca 8, todas de `cte` y todas del
mismo caso, `ROB-BUS-007`: el agente afirma no tener productos que su propia búsqueda acababa
de devolver. No vincula porque se midió sobre ejecuciones hechas para otra dimensión y con un
ítem escrito después de verlas.

### La anotación externa no confirmó la del autor

Una persona ajena al proyecto revisó a ciegas las 64 ejecuciones de la muestra de concordancia,
sin ver la configuración, el tipo de caso ni el veredicto de nadie. La regla de lectura estaba
fijada **antes** de recibir sus respuestas, en
[`docs/E6_REGLA_DE_INTERPRETACION.md`](docs/E6_REGLA_DE_INTERPRETACION.md), y dio dos resultados
incómodos:

- **La anotación del autor no queda confirmada**: kappa de Cohen de −0,20 contra la anotación a
  ciegas, por debajo del umbral de 0,60 fijado de antemano. Se presenta como la de un anotador
  único sin validación externa.
- **El permisivo es el juez automático, no la persona.** La anotación a ciegas concuerda
  **más** con el evaluador de estado (kappa 0,43) que con el juez (kappa −0,20), y donde la
  persona vio que alguna opción no cumplía lo pedido dijo que la respuesta le servía en solo 4
  de 17 casos: en las restricciones está del lado del evaluador.
- **`pass^k` no se presenta como cota inferior de la utilidad percibida.** No porque el
  criterio humano sea más estricto, que no lo es: la persona aprobó 48 de 64 y el evaluador 40.
  Es que **el orden no es limpio en ninguna dirección**. El evaluador reprueba 12 ejecuciones
  que la persona aprobó, entre ellas tres donde falla por cómo lee el estado y las ocho
  negaciones falsas de `cte`, y aprueba 4 que ella rechazó.

## Instalación

Requiere Python 3.11 o 3.12.

```bash
git clone https://github.com/jplazcano87/production-readiness-agentes.git
cd production-readiness-agentes
uv sync                    # o: pip install -e ".[dev]"
```

Para instalar el entorno con el que corren los pasos sin API y que es el de las corridas de
octubre (lo que el bloqueo puede y no puede afirmar está en
[`docs/REPRODUCIBILIDAD.md`](docs/REPRODUCIBILIDAD.md)):

```bash
uv pip install -r requirements-lock.txt
```

## Verificar sin llamar a la API

Esto es lo primero que conviene correr, y no necesita clave ni red.

```bash
pytest -q                                      # la suite entera, sin red
python scripts/verificar_equivalencia.py       # huellas de los artefactos congelados
python scripts/verificar_equivalencia.py --completo   # además los rehace y los compara
```

El modo completo copia el árbol a un directorio temporal, crea allí su propio entorno virtual
con el paquete instalado no editable, vuelve a generar doce artefactos derivados y los compara
con los publicados: Markdown y CSV byte a byte, PNG píxel a píxel, JSON campo a campo. Comprueba
también que el repositorio no haya cambiado mientras tanto. Los detalles están en
[`docs/REPRODUCIBILIDAD.md`](docs/REPRODUCIBILIDAD.md).

## Correr con la API

La clave va en un archivo `.env`, que nunca se versiona. Hay un `.env.example` con los nombres
de las variables y sin valores.

```bash
cp .env.example .env        # y escribe ahí tu ANTHROPIC_API_KEY
```

**Todo script que llama a la API acepta `--dry-run`, que imprime tokens y costo estimado en
dólares sin llamar a nada.** Córrelo siempre primero.

```bash
python scripts/run_e1.py --dry-run     # cuánto costaría
python scripts/run_e1.py --piloto 2    # dos casos por configuración, para validar
python scripts/run_e1.py               # la corrida completa
```

Cada resultado registra en su metadata los tokens consumidos y el costo real de esa corrida, de
modo que el archivo dice lo que costó producirlo. La compuerta de pre-vuelo
(`scripts/prevuelo.py`) comprueba el arnés antes de gastar en una corrida larga: primero las
comprobaciones estáticas, sin llamar a la API; después las dinámicas, sobre una muestra pequeña
de las cuatro configuraciones; y al final, que el costo real quede dentro del 20 % del estimado.

## Estructura

```
configs/      umbrales, modelos, despliegue y el registro de lo congelado
data/
  corpus/     cinco versiones del corpus, cada una con su manifiesto y su hash
  splits/     particiones de desarrollo y prueba
  templates/  plantillas de ataque, separadas entre desarrollo y prueba
  annotation/ muestras y respuestas de la anotación de concordancia
docs/         cifras del informe, procedencia, reproducibilidad, limitaciones,
              registro de defectos, hoja de datos y los dos prerregistros
figures/      las cinco figuras del informe
results/      los resultados canónicos y las transcripciones de las ejecuciones de
              cada medición publicada, con las excepciones que documenta
              docs/PROCEDENCIA.md
scripts/      los seis experimentos, el verificador y las auditorías sin costo
src/prf/      env (sandbox y evaluador), agent (configuraciones de defensa),
              eval (métricas), compliance (checklist), verdict (veredicto), infra
tables/       las tablas del informe
tests/        la suite, que corre sin red
```

**Lo que no se toca** está en [`AGENTS.md`](AGENTS.md): corpus, particiones, umbrales,
resultados, transcripciones y textos de prompts. Cambiarlos no corrige un resultado, lo
invalida. `docs/MANIFIESTO_ARTEFACTOS.json` guarda el SHA-256 de cada uno y el verificador los
comprueba.

## Estado del proyecto

Artefacto de investigación de un trabajo de graduación, mantenido con dedicación parcial. Las
mediciones están cerradas y los artefactos congelados; lo que se recibe con gusto son réplicas,
configuraciones de defensa nuevas, familias de ataque nuevas, adaptaciones a otros modelos y
proveedores, e ítems de checklist para otras jurisdicciones. Ver
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## Lo que este marco no puede afirmar

El corpus es sintético, el modelo es uno solo y de un solo proveedor, los ataques son estáticos
y de un turno, y el veredicto juzga el agente y no su despliegue. La lista completa, con qué
deja de poder afirmarse en cada caso, está en
[`docs/LIMITACIONES.md`](docs/LIMITACIONES.md). Los 32 defectos que el marco encontró en sí
mismo y en el sistema que evalúa, con qué cambió cada uno, están en
[`docs/REGISTRO_DE_DEFECTOS.md`](docs/REGISTRO_DE_DEFECTOS.md).

## Uso responsable

El corpus incluye **plantillas de ataque de inyección de instrucciones**, publicadas con fines
de evaluación defensiva, como hacen AgentDojo e InjecAgent. Son cargas genéricas contra un
agente de pre-venta ficticio: no explotan ninguna vulnerabilidad de un producto concreto ni de
un proveedor. Las particiones de desarrollo y prueba usan plantillas distintas, y ninguna cadena
se repite entre ellas, que es lo que permite afirmar que lo medido en prueba no se ajustó
durante la calibración.

## Cómo citar

La cita vive en [`CITATION.cff`](CITATION.cff), que es de donde la toma GitHub:

> Lazcano Candia, J. P. (2026). *Marco de Production Readiness para Agentes Autónomos de
> Compra en Retail: Integración de Evals, Guardrails y Compliance Normativo para Ecommerce*.
> Informe de Actividad de Graduación, Magíster en Inteligencia Artificial, Pontificia
> Universidad Católica de Chile.

El software está archivado en Zenodo y tiene DOI. Para citar **cualquier versión**, el de todas:
[10.5281/zenodo.23403716](https://doi.org/10.5281/zenodo.23403716). Para citar una versión concreta, el de esa versión: la 1.0.0,
[10.5281/zenodo.23403717](https://doi.org/10.5281/zenodo.23403717); la 1.1.0, la más reciente,
[10.5281/zenodo.23627444](https://doi.org/10.5281/zenodo.23627444).

## Licencia

MIT. Ver [`LICENSE`](LICENSE). Aplica al código, al corpus y a los resultados.
