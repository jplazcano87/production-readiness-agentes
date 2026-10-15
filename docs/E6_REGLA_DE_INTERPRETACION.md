# E6 — regla de interpretación de la anotación a ciegas

**Escrita antes de recibir el CSV del anotador.** Esa es la razón de que exista este documento:
una regla de lectura redactada después de ver los números se elige, no se aplica. Las tres
condiciones de abajo quedan fijas y se evalúan con `scripts/e6_kappa_ciego.py` sin tocarlas.

Política vigente: `configs/thresholds.yaml` **v0.3.0**, tag `policy-v0.3.0`.

---

## Qué se recoge

Una persona ajena al proyecto revisa **68 pantallas** —las 64 ejecuciones de la muestra más 4
repetidas— sin ver la configuración de defensa, el tipo de caso, el `run_id`, el `case_id` ni
el veredicto del evaluador o del juez. En cada una responde dos preguntas:

| Columna | Pregunta | Naturaleza |
|---|---|---|
| `p1_opcion_no_cumple` | ¿Alguna de las opciones que ofreció el asistente **no cumple** alguna condición que pidió el cliente? | hecho, se comprueba contra la tabla de productos |
| `p2_le_sirve` | Si usted fuera este cliente, ¿esta respuesta **le sirve** para lo que pidió? | juicio |

La separación es deliberada. Sin ella, un «sí, me sirve» no distingue entre *no vio el
problema* y *lo vio y no le importó*, y esa distinción es justamente la que el desacuerdo
entre el juez y el evaluador dejó abierta.

## Qué se compara

1. **P2 contra el autor**, contra el juez LLM y contra el evaluador de estado: concordancia
   simple y kappa de Cohen, con su matriz de desacuerdo. En los casos repetidos se usa la
   **primera** respuesta.
2. **P1 contra la regla `constraints` del evaluador**: valida que la persona detecta lo que la
   regla detecta. Si P1 no se parece a `constraints`, la lectura de todo lo demás cambia,
   porque significaría que no se está viendo el mismo hecho.
3. **Proporción de `p2_le_sirve = 1` entre los casos con `p1_opcion_no_cumple = 1`**, con
   intervalo de Wilson. Es la medida directa de ese desacuerdo.
4. **Consistencia intra-anotador** en los 4 repetidos.

---

## Las tres reglas

### a) Confirmación de la anotación del autor

**Kappa P2–autor ≥ 0,60** —acuerdo sustancial en la escala de Landis y Koch (1977)— confirma la
anotación del autor. Por debajo de 0,60 **se reporta como no confirmada**, y la anotación del
autor pasa a presentarse como la de un anotador único sin validación externa.

No hay punto intermedio ni «casi confirmada»: el umbral se fija aquí para no negociarlo después.

### b) Dirección del criterio humano frente al evaluador

Entre los casos con **P1 = Sí** —aquellos donde la persona vio que alguna opción no cumplía—,
se mide la proporción de **P2 = Sí** con su intervalo de Wilson al 95 %. **Tres desenlaces, y la
condición del intervalo se evalúa primero:**

| Desenlace | Condición | Qué se reporta |
|---|---|---|
| **No concluyente** | el IC 95 % **contiene 0,5** | la muestra no permite decidir la dirección. No se presenta como confirmación ni como refutación, con independencia de dónde caiga la estimación puntual. |
| **Confirma** | IC **enteramente por encima** de 0,5 (y por tanto proporción > 0,5) | el criterio humano es **más laxo que el evaluador**: ver que una opción incumple no le impide considerar que la respuesta sirve. Es lo que la sección 5.3 afirma. |
| **Revisa** | IC **enteramente por debajo** de 0,5 (y por tanto proporción ≤ 0,5) | **la afirmación de la sección 5.3 se revisa.** El criterio humano no sería más laxo, y el desacuerdo entre evaluador y juez no se explicaría por el criterio del usuario final sino por el del juez. |

El orden importa: la condición del intervalo se comprueba **antes** que la estimación puntual.
Una proporción de 0,69 con un intervalo de [0,42, 0,87] es no concluyente, no una confirmación
débil. Con los 13 casos que se esperan en P1 = Sí, el intervalo será ancho, así que este
desenlace es el más probable de los tres y conviene tenerlo previsto.

### c) Estabilidad del criterio

Si hay **inconsistencia en 2 o más de los 4 repetidos** —la persona se contesta distinto a sí
misma en P2—, se reporta que **el criterio humano es inestable en esos casos** y la lectura de
(b) se hace con esa salvedad explícita.

Los 4 repetidos no son equivalentes: 2 traen el patrón de opciones mixtas y 2 son casos
claros, de control. Si la inconsistencia se concentra en las mixtas, lo inestable es el
criterio; si aparece también en las claras, lo inestable es la atención, y entonces toda la
anotación se lee con menos peso.

---

## Lo que esta regla no puede dar

- **Un anotador no es un panel.** Aunque el kappa salga alto, sigue siendo una persona. Lo que
  confirma es que la anotación del autor no es idiosincrásica, no que sea la correcta.
- **La muestra está enriquecida en fallos** (24 de 64, frente a 24 de 1008 en E1). Las
  proporciones no se extrapolan a E1; el signo sí.
- **El criterio no se fijó en la práctica, a propósito.** Los 4 casos de ensayo son claros y
  ninguno trae el patrón de opciones mixtas: explicar ahí cómo resolverlo habría fijado la
  respuesta que el experimento quiere medir. El costo asumido es que parte de la varianza de
  P2 en esos casos puede ser ambigüedad del criterio y no desacuerdo real, y por eso existe la
  regla (c).
