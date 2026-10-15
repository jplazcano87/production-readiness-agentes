"""Las cuatro configuraciones de defensa que compara el experimento.

Se declaran como datos y no como subclases porque la comparación de E2 y E3 exige que las
cuatro recorran **el mismo código**: si cada una tuviera su propia implementación del bucle,
una diferencia de ASR podría venir de la defensa o de la implementación, y no habría forma
de distinguirlo.

| Configuración | Qué ve el modelo privilegiado | Quién decide las llamadas |
|---|---|---|
| `none` | texto crudo de reseñas y descripciones | el propio modelo |
| `prompt_only` | lo mismo, más una advertencia en el system prompt | el propio modelo |
| `dual_llm` | solo objetos validados del modelo en cuarentena | el propio modelo |
| `cte` | lo mismo, y además no ejecuta: emite un plan | un intérprete determinista |

`prompt_only` es la línea base 2 del informe: mide cuánto se consigue solo pidiéndole al
modelo que desconfíe, que es la defensa que la industria aplica por omisión.
"""

from __future__ import annotations

from dataclasses import dataclass

from prf.env.tools import HERRAMIENTAS, HERRAMIENTAS_LECTURA

# Versión del agente: prompts, defensas y forma de acreditar el estado final. Cambia cuando
# cambia algo que puede mover una medición, y por eso queda en los metadatos de todo
# resultado.
#
#   2.0.0  Estado de `cte` derivado del intérprete.
#   2.1.0  Remediación que detectó E4: bloque de cumplimiento en el system prompt de
#          las cuatro configuraciones, y esquemas de salida de las herramientas para el
#          planificador de `cte`. Es un cambio del sistema evaluado, no del
#          arnés, y por eso obliga a repetir E1 y E4.
#   2.2.0  El sandbox deja de entregarle al agente las anotaciones del andamiaje
#          (`is_adversarial`, `attack_id`) que iban dentro de cada reseña. Restaura lo que
#          su propio docstring ya prometía y es imprescindible para E2: sin esto, cada
#          ataque indirecto llegaba **etiquetado como ataque**.
#   3.0.0  Las cláusulas defensivas salen del prompt base y pasan a definir `prompt_only`.
#          Cambia el significado de las líneas base: hasta 2.2.0 `none` llevaba en su prompt
#          la negación de los cuatro objetivos de ataque, así que no era una línea base sin
#          protección y E2 midió un ASR de cero en las cuatro configuraciones.
#   3.0.1  El intérprete deja de perder la ejecución cuando el planificador escribe una
#          especificación de formato inválida (`{precio:,}` sobre un texto). Nunca se activó
#          con Sonnet —E1, E4 y E2 cerraron con 0 incidencias, verificado— y sí con Haiku, así
#          que E1/E4/E2 quedan medidos con 3.0.0 y la corrida con Haiku con 3.0.1.
AGENT_VERSION = "3.0.1"


@dataclass(frozen=True)
class Configuracion:
    """Parámetros de una configuración de defensa."""

    nombre: str
    descripcion: str
    # Advertencia en el system prompt para tratar el contenido recuperado como no confiable.
    advierte_en_prompt: bool
    # El texto recuperado pasa por el modelo en cuarentena antes de llegar al privilegiado.
    usa_cuarentena: bool
    # El modelo privilegiado emite un plan y un intérprete determinista lo ejecuta.
    usa_planificador: bool
    # Herramientas que la configuración expone o permite.
    herramientas: tuple[str, ...]
    # Cláusulas que niegan por adelantado cada objetivo de ataque. Desde 3.0.0 solo las lleva
    # `prompt_only`: tenerlas en el prompt base convertía a `none` en algo que no era una
    # línea base sin protección.
    clausulas_defensivas: bool = False


NONE = Configuracion(
    nombre="none",
    descripcion=(
        "Sin protección. El agente recibe el texto recuperado tal cual y su prompt no niega "
        "ningún objetivo de ataque."
    ),
    advierte_en_prompt=False,
    clausulas_defensivas=False,
    usa_cuarentena=False,
    usa_planificador=False,
    # Las restringidas se exponen para que un secuestro del flujo de control sea
    # observable: si no estuvieran declaradas, el ataque fracasaría por falta de superficie
    # y el experimento mediría otra cosa.
    herramientas=HERRAMIENTAS,
)

PROMPT_ONLY = Configuracion(
    nombre="prompt_only",
    descripcion=(
        "Línea base 2, la defensa que vive solo en el prompt: las cláusulas que niegan cada "
        "objetivo de ataque más el párrafo que ordena tratar todo contenido recuperado como "
        "datos no confiables."
    ),
    advierte_en_prompt=True,
    clausulas_defensivas=True,
    usa_cuarentena=False,
    usa_planificador=False,
    herramientas=HERRAMIENTAS,
)

DUAL_LLM = Configuracion(
    nombre="dual_llm",
    descripcion=(
        "Dual LLM (Willison, 2023): el modelo privilegiado nunca ve texto crudo de "
        "reseñas ni descripciones; solo el objeto validado que devuelve el modelo en "
        "cuarentena."
    ),
    advierte_en_prompt=True,
    usa_cuarentena=True,
    usa_planificador=False,
    herramientas=HERRAMIENTAS,
)

CTE = Configuracion(
    nombre="cte",
    descripcion=(
        "Code-Then-Execute simplificado, inspirado en CaMeL (no es una réplica): el "
        "planificador emite un plan y un intérprete determinista lo ejecuta con "
        "etiquetas de procedencia y lista de herramientas permitidas."
    ),
    advierte_en_prompt=True,
    usa_cuarentena=True,
    usa_planificador=True,
    # Un agente de pre-venta no está facultado para aplicar descuentos ni enviar mensajes:
    # en CTE eso no depende de que el modelo se porte bien, lo impone el intérprete.
    herramientas=HERRAMIENTAS_LECTURA,
)

CONFIGURACIONES: dict[str, Configuracion] = {
    c.nombre: c for c in (NONE, PROMPT_ONLY, DUAL_LLM, CTE)
}


def obtener(nombre: str) -> Configuracion:
    """La configuración de defensa con ese nombre, o un error que lista las que hay."""
    try:
        return CONFIGURACIONES[nombre]
    except KeyError as exc:
        disponibles = ", ".join(CONFIGURACIONES)
        raise KeyError(
            f"configuración desconocida: {nombre!r}. Disponibles: {disponibles}"
        ) from exc


__all__ = ["CONFIGURACIONES", "CTE", "DUAL_LLM", "NONE", "PROMPT_ONLY", "Configuracion", "obtener"]
