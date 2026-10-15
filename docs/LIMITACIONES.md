# Lo que este marco no puede afirmar

Dos clases de limitación, y conviene no confundirlas. Las de la parte A aparecieron
**midiendo**: son cosas que el instrumento no mide bien, o que mide menos de lo que su nombre
sugiere. Las de la parte B son **de alcance**: están en el diseño desde el principio y no se
corrigen con código.

Cada una dice qué es y, sobre todo, qué deja de poder afirmarse por su causa. Los defectos que
sí se corrigieron están en [`REGISTRO_DE_DEFECTOS.md`](REGISTRO_DE_DEFECTOS.md).

## Parte A. Limitaciones registradas durante el desarrollo

1. **La regla que excluye un producto señuelo mide formular bien la consulta, no resistir la
   tentación.** En todas las ejecuciones con señuelo, el producto que había que evitar nunca
   apareció en un resultado de herramienta: el agente filtra bien la búsqueda y el señuelo
   queda fuera antes de que llegue a verlo. *No se puede afirmar que el agente resista
   recomendar un producto que incumple cuando lo tiene delante, porque no llegó a tenerlo.*

2. *(Corregida.)* Cuatro casos imponían un presupuesto que el texto de la intención no
   comunicaba. Se corrigió reescribiendo las intenciones; es el **defecto 7** del registro.

3. **La medición de robustez apenas ejercita la conversación multi-turno.** De 336 ejecuciones
   de la configuración sin defensa, 328 se resolvieron en un solo turno, y las 8 que llegaron a
   un segundo o tercer turno acertaron todas. *La métrica de robustez describe respuestas de un
   turno; no dice nada sobre conversaciones largas, que es donde un agente de pre-venta real
   pasa la mayor parte del tiempo.*

4. *(Corregida.)* La comprobación de comparaciones medía el uso de la herramienta y no la
   comparación entregada. Es el **defecto 8** del registro.

5. **El planificador de Code-Then-Execute no conoce los campos que devuelven las
   herramientas.** Recibe las firmas de entrada, no las de salida, así que escribe expresiones
   que no resuelven —pide un campo con un nombre que no existe— y el intérprete sigue adelante
   con la variable vacía. *Un paso que falla por esto se parece a un paso que la defensa
   bloqueó, y distinguirlos exige mirar la ejecución.*

6. **Un ítem normativo decidido con una sola ejecución no es estable.** Dos corridas del mismo
   código con el mismo agente dieron 8 y 10 ítems críticos aprobados de 22. La medición final
   usa cinco ejecuciones y exige unanimidad, pero cinco tampoco es una garantía. *Un ítem
   aprobado significa «aprobó cinco veces seguidas», no «el agente cumple siempre».*

7. **Contar como recomendación cualquier identificador que llegue al paso de respuesta puede
   confundir «mencionado» con «recomendado».** Era necesario —sin eso se perdían
   recomendaciones reales— y abre el riesgo de que un producto que la respuesta solo nombra se
   cuente como ofrecido. *Medido sobre la corrida final: 0 casos, pero el riesgo es del
   criterio y no desaparece con otro corpus.*

8. **Los ataques indirectos del corpus de medición inicial usan un solo portador: la reseña.**
   Ninguna descripción de producto contenía una inyección. Se añadió después una segunda
   superficie, con la descripción como portador, y los resultados se reportan por separado.
   *Las cifras de la primera superficie no se extrapolan a otras vías de entrada de texto no
   confiable.*

9. **Una de las siete reglas del evaluador de estado no la ejercita ningún caso del corpus.**
   Lo encontró la compuerta que deriva del corpus qué reglas pueden ejercerse, en vez de darlas
   por hechas. *Esa regla está probada unitariamente, pero no validada contra ninguna ejecución
   real.*

10. **Un checklist de cadenas mide la forma, no el contenido.** Juzga texto que escribe un
    modelo generativo, que parafrasea: cada corrección del verificador lo acerca al
    comportamiento observado y ninguna garantiza la siguiente respuesta. *Un ítem aprobado dice
    que la respuesta tenía la forma esperada, no que la obligación normativa esté satisfecha.*

11. **Un umbral agregado puede aprobar lo que sus componentes reprueban.** La tasa de éxito de
    ataque global promedia dos vectores cuyos valores difieren en dos órdenes de magnitud, y el
    promedio no describe a ninguno de los dos: una configuración pasaba el umbral global con
    una tasa por el vector directo cuatro veces mayor que el límite. La política vigente evalúa
    el agregado y los vectores por separado y exige los tres. *Toda métrica agregada de este
    marco necesita publicar su desagregación; sin ella, un «cumple» no es interpretable.*

12. **El veredicto dependía de decisiones que la política no escribía.** De qué campo se lee la
    tolerancia cero y qué hacer con una dimensión sin medir estaban en el código, no en el
    archivo de política. Ahora las tres cosas son explícitas. *La lección se mantiene: una
    política de aceptación es también el código que la aplica, y auditarla exige leer los dos.*

13. **Exportar la evidencia y exportar un formulario de anotación tienen requisitos opuestos.**
    El volcado quiere todo el contexto; el formulario quiere lo mínimo para juzgar y nada que
    ancle a quien anota. *Decidir qué no se muestra es parte del diseño de un instrumento de
    anotación, y un archivo que sirve para las dos cosas no sirve para ninguna.*

14. **El estado que calcula el evaluador y el texto que la persona lee pueden discrepar, y a
    veces el texto tiene razón.** Auditadas las 1.008 ejecuciones de la corrida final, hay 7
    reprobadas por ausencia de recomendación cuyo texto visible sí menciona productos del
    catálogo. *La métrica basada en estado es una cota inferior de lo que un lector consideraría
    resuelto.*

15. **Nombrar el portador no garantiza que el agente lo resuelva al producto correcto.** La
    corrida de la segunda superficie cerró con una tasa de entrega de 0,952: las tres
    ejecuciones que no entregaron son el mismo caso, y la causa es que dos productos del
    catálogo tienen nombres casi idénticos. *La tasa de éxito de ataque de esa superficie se lee
    sobre las entregadas, no sobre las intentadas.*

16. **El ítem que comprueba la veracidad de lo que la respuesta afirma cubre negar resultados
    que existen, y nada más.** Las mismas respuestas que lo motivaron son falsas de tres formas
    y el ítem cubre una: no mide las afirmaciones comparativas falsas —«los modelos con esa
    característica parten de precios más altos», cuando la búsqueda devolvió cinco por debajo—
    ni los atributos equivocados. *Un ítem de veracidad aprobado no dice que la respuesta sea
    veraz; dice que no negó la existencia de lo que encontró.*

## Parte B. Limitaciones de alcance

Estas no son defectos pendientes. Son los límites de lo que este diseño puede sostener, y
valen igual para cualquiera que replique el marco.

**El corpus es sintético.** Catálogo, reseñas, intenciones y cargas de ataque se generaron para
este trabajo; la tienda no existe. Eso hace el corpus publicable y reproducible, y a cambio las
cifras describen el comportamiento del agente frente a un corpus construido, no frente a la
distribución de consultas de una tienda real.

**Un modelo base y un proveedor.** Todas las corridas usan modelos de un mismo proveedor, con
dos tamaños. La comparación entre ellos muestra que las tres dimensiones cambian con el
modelo —lo que una configuración cumple con el modelo grande puede incumplirlo con el
pequeño—, así que **la política no es una propiedad del sistema sino del par sistema-modelo**.
Nada aquí se extrapola a otro proveedor.

**Los ataques son estáticos y de un solo turno.** Las cargas se escriben antes de la corrida y
no se adaptan a lo que el agente responde. Un atacante real itera. *Las tasas de éxito medidas
son una cota inferior frente a un adversario adaptativo.*

**El veredicto juzga el agente, no su despliegue.** El umbral vinculante de latencia es el
sobrecosto relativo frente a la configuración sin defensa, porque el valor absoluto mide la
carga del proveedor tanto como el sistema. La consecuencia se asume explícitamente: una
configuración con 15,3 segundos hasta el primer token **no es utilizable** y el veredicto no lo
captura.

**Un anotador no es un panel.** La anotación externa la hizo una persona. Aunque el acuerdo
hubiera sido alto, lo que confirmaría es que una anotación no es idiosincrásica, no que sea la
correcta.

**La muestra de concordancia está enriquecida en fallos.** Reúne todas las ejecuciones fallidas
más una selección de exitosas, con 24 de 64 fallos frente a 24 de 1.008 en la corrida completa.
*Las proporciones de esa muestra no se extrapolan a la población; el signo de los desacuerdos,
sí.*

**La anotación a ciegas se hizo en una sesión más rápida de lo previsto.** Las 68 pantallas se
respondieron en 29,5 minutos, con una mediana de 18,3 segundos por pantalla y 9 por debajo de
10 segundos, frente a las 2 horas que el instrumento anunciaba. Ninguna respuesta se excluye
por esto —la regla de lectura se fijó antes de recibir los datos y no prevé filtros por
tiempo—, pero el dato se publica porque condiciona cuánto peso soporta esa anotación.
