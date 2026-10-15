# Hoja de datos del corpus

Siguiendo *Datasheets for Datasets* (Gebru et al., 2021). Describe el corpus sintético sobre el
que se midieron las tres dimensiones del marco.

## Motivación

**¿Para qué se creó?** Para medir si un agente de pre-venta basado en un modelo de lenguaje
está listo para producción, en tres dimensiones: consistencia bajo no determinismo, resistencia
a la inyección de instrucciones y cumplimiento de obligaciones normativas comprobables. No
existía un corpus en español de Chile que cubriera las tres a la vez, con casos anotados con el
estado objetivo que el agente debe alcanzar.

**¿Por qué sintético y no real?** Por tres razones, y ninguna es la facilidad.

1. **Control experimental.** Cada caso declara su estado objetivo: qué productos cumplen las
   restricciones, cuáles hay que excluir, cuántas recomendaciones se esperan. Sin esa anotación
   no hay evaluación determinista, y sin evaluación determinista pass^k no se puede calcular.
   Anotar así un corpus de consultas reales exigiría un criterio humano por caso, que es
   justamente lo que el marco quiere evitar en el lazo de medición.
2. **Reproducibilidad.** El corpus se publica entero, con su hash de contenido. Cualquiera
   puede volver a correr los experimentos sobre exactamente los mismos datos. Un corpus de
   consultas reales no sería publicable y las cifras no serían verificables.
3. **Sin datos personales.** Las dimensiones de seguridad y cumplimiento exigen casos donde una
   persona entrega datos personales al agente, y la de cumplimiento exige comprobar qué hace el
   sistema con ellos. Hacerlo con datos reales sería a la vez innecesario y difícil de
   justificar.

El costo de esa decisión está declarado: las cifras describen el comportamiento del agente
frente a un corpus construido, no frente a la distribución de consultas de una tienda en
funcionamiento. Es la primera limitación de alcance en
[`LIMITACIONES.md`](LIMITACIONES.md).

**¿Quién lo creó y con qué financiamiento?** El autor, como parte de un trabajo de graduación
de un programa de magíster. Sin financiamiento externo.

## Composición

Cinco versiones, **incrementales y solo aditivas**: cada una contiene a la anterior byte a byte
y ninguna reasigna un caso de una partición a otra. La vigente es la **v1.4**.

| | v1.4 |
|---|---:|
| Productos del catálogo | 200 |
| Reseñas benignas | 600 |
| Reseñas adversariales | 60 |
| Casos de robustez | 60 (20 de búsqueda, 20 de comparación, 20 de recomendación) |
| Casos de seguridad | 170 (40 benignos, 40 directos, 90 indirectos) |
| Casos de cumplimiento | 26 |
| Plantillas de ataque | 29 de desarrollo, 30 de prueba, sin una sola cadena en común |

Los casos de seguridad se reparten en cuatro objetivos de ataque (exfiltración, secuestro de la
tarea, salida de dominio y promesa no autorizada) y, los indirectos, en dos portadores: 60 con
la carga alojada en una reseña y 30 en la descripción comercial de un producto.

**¿Qué representa cada instancia?** Un caso de evaluación: el mensaje de una persona a un
agente de pre-venta, más la anotación de qué debería pasar. En los casos de seguridad incluye
además la carga adversarial y el criterio programático con el que se decide si el ataque tuvo
éxito.

**¿Falta algo en alguna instancia?** No hay valores ausentes. Lo que sí hay son asimetrías de
diseño declaradas: una de las siete reglas del evaluador no la ejercita ningún caso, y el vector
indirecto del corpus inicial usaba un solo portador. Las dos están en
[`LIMITACIONES.md`](LIMITACIONES.md).

**¿Hay datos confidenciales o sensibles?** No. Nada en el corpus procede de una persona, de una
conversación real ni de un sistema en funcionamiento.

## Proceso de generación

Dos capas, y la separación es lo que hace el corpus barato de corregir.

**La capa programática** construye la estructura: el catálogo con sus atributos y precios, las
restricciones de cada caso, el estado objetivo, la asignación de plantillas de ataque y las
particiones. Es determinista y depende de una semilla global, `20260906`. Corregir un defecto
aquí no cuesta nada.

**La capa de redacción** convierte cada caso en el texto que una persona escribiría, con un
modelo de lenguaje (`claude-haiku-4-5-20251001`). Es la parte cara, y por eso el generador
acepta reutilizar el texto ya escrito: una corrección de la capa programática no obliga a pagar
de nuevo la redacción.

Todo el texto está en **español de Chile**.

**¿Se validó?** Sí, y la validación encontró defectos reales que están en
[`REGISTRO_DE_DEFECTOS.md`](REGISTRO_DE_DEFECTOS.md): reseñas cuyo promedio contradecía la
valoración del producto, intenciones que exigían restricciones que su texto no comunicaba,
ataques indirectos que no habrían llegado al agente por el límite de reseñas que devuelve la
herramienta. Cada versión del corpus lleva en su manifiesto el registro de qué cambió.

## Preprocesamiento

El corpus se publica tal como se congeló. No hay limpieza ni normalización posterior: el hash
de contenido de cada versión identifica exactamente los bytes con los que se midió, y
`scripts/verificar_equivalencia.py` lo comprueba.

Las particiones de desarrollo y prueba (aproximadamente 30 % y 70 %) se generan con la misma
semilla, estratificadas por dimensión y por tipo. **Las plantillas de ataque son distintas entre
las dos particiones**, lo que permite afirmar que lo medido en prueba no se ajustó durante la
calibración. El catálogo se comparte.

## Usos

**Para lo que se pensó.** Medir robustez, resistencia a inyección y cumplimiento de un agente
conversacional con herramientas; comparar configuraciones de defensa entre sí; replicar las
cifras publicadas; servir de base para añadir familias de ataque, configuraciones o ítems de
checklist de otras jurisdicciones.

**Para lo que no.** No es un banco de pruebas de propósito general ni una muestra de tráfico
real. Sus proporciones no se extrapolan: la muestra de concordancia, por ejemplo, está
enriquecida en fallos a propósito. Y nada de lo medido con un modelo se traslada a otro: la
misma política da resultados distintos con un modelo más pequeño.

**Uso responsable.** El corpus incluye plantillas de inyección de instrucciones, publicadas con
fines de evaluación defensiva, como hacen AgentDojo e InjecAgent. Son cargas genéricas contra un
agente de pre-venta ficticio y no explotan ninguna vulnerabilidad de un producto concreto ni de
un proveedor.

## Nombres, marcas y dominios

Todo lo que en el corpus parece el nombre de alguien o de algo es inventado. Conviene decirlo
con precisión, porque el corpus se publica entero y porque algunas de esas invenciones las hizo
el modelo durante las corridas.

**Nombres de personas.** El corpus usa ocho nombres ficticios, elegidos por ser nombres comunes
en Chile, para los casos que necesitan datos personales simulados. Los RUT que los acompañan
están en un tramo no asignado a personas, con dígito verificador válido a propósito, para que
los verificadores de datos personales se puedan ejercitar de verdad. Los correos van bajo
`example.cl`. **Cualquier coincidencia con personas reales es fortuita.**

**Marcas reales.** En las transcripciones de las corridas aparecen marcas de tecnología reales
(Apple, Google, Amazon, JBL) en cuatro contextos. Todas están **dentro de texto que generó el
modelo** mientras respondía: compatibilidad entre ecosistemas de hogar inteligente, o el agente
declinando una marca que el catálogo ficticio no tiene. **No son afirmaciones del proyecto sobre
esas empresas**, ni aparecen en el corpus: son salida del sistema evaluado, conservada como
parte de la evidencia.

**Marcas de los productos.** Los 200 productos del catálogo llevan nombres de fantasía formados
con **topónimos chilenos** (Chinchorro, Tongoy, Elqui, Copiapó, Loa, Osorno, Maipo, Aysén,
Choapa, Curicó, Limarí, Futaleufú, Lauca, Chiloé y otros). Se eligieron como **nombres de
fantasía** para un catálogo ficticio: el proyecto no revisó registros de marcas, no afirma nada
sobre ellos y **no busca relación con empresas o marcas que usen esos nombres**.

**El dominio de la tienda.** `tiendademo.cl` es el nombre de la tienda ficticia y se publica tal
cual, porque es el que el informe usa. Aparece en 11 archivos, más dos con la variante
`tiendademo.ejemplo.cl`, **siempre en texto que inventó el modelo**, y **no corresponde a ningún
sitio operado por este proyecto**. Los correos del corpus usan `example.cl` y
`tiendademo.example.cl`.

**Un teléfono que el modelo inventó, y que no se publica.** Al fabricar canales de contacto que
nadie le había dado, el agente escribió un móvil chileno con formato válido. Es invención del
modelo, pero un número inventado con formato válido puede ser el de una persona real, así que
los tres archivos que lo contienen **se retuvieron** y en su lugar se publican copias redactadas,
idénticas salvo los ocho dígitos. El detalle, con el SHA-256 del original y el de cada copia,
está en [`PROCEDENCIA.md`](PROCEDENCIA.md).

## Distribución

El corpus se publica dentro de este repositorio, bajo licencia MIT, junto con el código que lo
genera y los resultados de las mediciones. No hay DOI todavía.

## Mantenimiento

Lo mantiene el autor, con dedicación parcial. Las versiones publicadas **no se modifican**: una
corrección o una ampliación se hace creando una versión nueva que contiene a la anterior byte a
byte, con su propio hash y su registro de cambios. `tests/test_corpus_incremental.py` comprueba
la contención y que ningún caso heredado cambie de partición.

Quien quiera añadir casos encontrará el procedimiento en [`../AGENTS.md`](../AGENTS.md) y en
[`../CONTRIBUTING.md`](../CONTRIBUTING.md).

## Referencia

Gebru, T., Morgenstern, J., Vecchione, B., Wortman Vaughan, J., Wallach, H., Daumé III, H. y
Crawford, K. (2021). Datasheets for Datasets. *Communications of the ACM*, 64(12), 86-92.
