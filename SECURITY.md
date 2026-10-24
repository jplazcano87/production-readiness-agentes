# Política de seguridad

Este repositorio es un artefacto de investigación sobre la seguridad de agentes basados en
modelos de lenguaje, así que conviene separar dos cosas que aquí se parecen: un **defecto del
software** y un **ataque que funciona**. Las dos interesan y las dos van por el mismo canal
privado.

## Alcance

Sí entran:

- **Vulnerabilidades del arnés o del código**: ejecución de código a partir de datos del corpus
  o de una respuesta del modelo, escapes del sandbox de herramientas, filtración de la clave de
  API o de variables de entorno en registros o transcripciones, lectura o escritura de archivos
  fuera del árbol del proyecto.
- **Formas nuevas de eludir las defensas** medidas aquí (`prompt_only`, `dual_llm`, `cte`),
  sobre todo si funcionan contra las configuraciones que en este repositorio aprueban. Una
  elusión reproducible es material para una **familia de ataque nueva** del corpus, y se trata
  como un aporte, no como una molestia.
- **Dependencias** con vulnerabilidades conocidas que este proyecto alcance de verdad.

No entran, y van en un issue público:

- Que el agente evaluado responda mal, invente un dato o reprube un ítem del checklist. Eso es
  el objeto de estudio: está medido y publicado.
- Que las plantillas de ataque del corpus existan. Se publican a propósito, con fines de
  evaluación defensiva, como hacen AgentDojo e InjecAgent.
- Vulnerabilidades de la API o de los modelos de Anthropic. Eso se reporta a Anthropic.

## Cómo reportar

Usa el **reporte privado de vulnerabilidades de GitHub**, en la pestaña Security del
repositorio: *Report a vulnerability*. **No abras un issue público**, ni describas el problema
en un pull request, hasta que esté corregido o acordemos que no hace falta.

Si no puedes usar ese canal, escribe a **jlazcanoc@estudiante.uc.cl** indicando en el asunto que
es un reporte de seguridad.

Ayuda incluir: qué versión o commit, qué pasa, cómo reproducirlo y qué consigue quien lo
explota. Si el reporte es una elusión de una defensa, incluye la carga y en qué configuración
funciona; si pudiste medirla, cuántas de cuántas ejecuciones.

**Nunca incluyas una clave de API en el reporte.** Si la tuya quedó expuesta por un defecto de
este proyecto, revócala primero y después escribe.

## Qué esperar

El proyecto lo mantiene una persona con dedicación parcial, así que no hay plazos garantizados.
El compromiso es acusar recibo en una semana y decir qué pensamos hacer, incluso si la respuesta
es que no se va a corregir.

Las correcciones se publican sobre la **versión vigente**, hoy la 1.1.0. Las versiones
anteriores no reciben parches. Si el defecto afecta a algo que ya se midió, la corrección no
reescribe los resultados publicados: se registra en
[`docs/REGISTRO_DE_DEFECTOS.md`](docs/REGISTRO_DE_DEFECTOS.md) y, si cambia lo que las cifras
significan, se mide de nuevo con una versión nueva y las dos quedan comparables.

Si tu reporte termina en una corrección o en una familia de ataque nueva, apareces en el
`CHANGELOG.md` con el crédito, salvo que prefieras que no.
