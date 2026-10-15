"""Evaluación determinista basada en estado.

Decisión cerrada: el éxito de un caso se decide comparando el estado final de la
conversación con el estado objetivo anotado. Sin modelo, sin heurística difusa y sin
azar: la misma pareja (estado final, estado objetivo) produce siempre el mismo veredicto.
Eso es lo que permite que pass^k mida el no determinismo del agente y no el del evaluador.

Cinco reglas, más una sexta que protege la anotación:

1. `must_include` — todos los ids exigidos aparecen recomendados.
2. `must_exclude` — ninguno de los ids prohibidos aparece recomendado.
3. `must_compare` — cada par exigido se entregó en alguna comparación.
4. `constraints` — ninguna recomendación viola presupuesto, categoría ni atributos.
5. `forbidden_tools` — no se invocó ninguna herramienta prohibida.
6. recomendaciones inexistentes — ningún id recomendado falta del catálogo.
7. `min_recomendaciones` — se entregó al menos el mínimo de recomendaciones exigido.

Las reglas 6 y 7 no están en el enunciado del plan y responden al mismo agujero: un caso
con `must_include` vacío —el de búsqueda y el de recomendación por necesidad, donde varios
productos son respuestas legítimas— lo aprobaría tanto un agente que alucina
`<<rec:P9999>>` como uno que no recomienda nada.
"""

from __future__ import annotations

from typing import Any, TypedDict

from prf.env.catalog import cumple_atributo, normalizar
from prf.env.state import FinalState
from prf.env.target import Constraints, TargetState

# Versión del evaluador: las siete reglas y, sobre todo, **de dónde sale el estado que
# juzgan**. Cambia cuando cambia lo que cuenta como evidencia, porque entonces dos
# resultados dejan de ser comparables aunque midan el mismo agente sobre el mismo corpus.
#
#   1.0.0  Reglas originales; la comparación se acredita solo por la llamada a
#          `compare_products` y los marcadores se leen del último turno.
#   1.1.0  La comparación se acredita también por el marcador `<<cmp:ID1,ID2>>`.
#   2.0.0  En `cte` el estado lo deriva el intérprete y los marcadores del planificador se
#          ignoran; en las conversacionales los marcadores se leen de todos los turnos
#          del asistente, no solo del último.
#   2.1.0  En `cte`, un id de catálogo que llega a `respond` como valor suelto cuenta como
#          recomendación, no solo el objeto producto entero: el planificador suele desglosar
#          los campos y esos productos entran en la respuesta igual. Y los verificadores de
#          cumplimiento ignoran el énfasis de Markdown, que partía las frases que buscan.
#   2.1.1  Los verificadores de cumplimiento no cuentan una frase que aparece dentro de su
#          propia negación: «no solo se avisa a la autoridad» decía lo contrario de lo que
#          se leía.
EVALUATOR_VERSION = "2.1.1"


class Razon(TypedDict):
    """Motivo de fallo de una regla, con los ids que lo provocan."""

    regla: str
    mensaje: str
    ids: list[str]


class Evaluacion(TypedDict):
    """Resultado de `evaluate_state`."""

    success: bool
    reasons: list[Razon]
    reglas: dict[str, bool]


REGLAS = (
    "must_include",
    "must_exclude",
    "must_compare",
    "constraints",
    "forbidden_tools",
    "recomendaciones_existentes",
    "min_recomendaciones",
)


def _razon(regla: str, mensaje: str, ids: list[str] | None = None) -> Razon:
    return {"regla": regla, "mensaje": mensaje, "ids": sorted(ids or [])}


def violaciones_de_constraints(producto: Any, constraints: Constraints) -> list[str]:
    """Restricciones que un producto incumple. Lista vacía = las cumple todas."""
    fallas: list[str] = []
    if (
        constraints.presupuesto_max_clp is not None
        and producto.price_clp > constraints.presupuesto_max_clp
    ):
        fallas.append(
            f"precio ${producto.price_clp} supera el presupuesto máximo "
            f"${constraints.presupuesto_max_clp}"
        )
    if (
        constraints.presupuesto_min_clp is not None
        and producto.price_clp < constraints.presupuesto_min_clp
    ):
        fallas.append(
            f"precio ${producto.price_clp} está bajo el mínimo ${constraints.presupuesto_min_clp}"
        )
    if constraints.categoria is not None and normalizar(producto.category) != normalizar(
        constraints.categoria
    ):
        fallas.append(
            f"categoría {producto.category!r} no es la pedida ({constraints.categoria!r})"
        )
    for clave, requisito in constraints.atributos.items():
        if clave not in producto.attributes:
            fallas.append(f"no declara el atributo {clave!r}")
        elif not cumple_atributo(producto.attributes[clave], requisito):
            fallas.append(
                f"atributo {clave!r}={producto.attributes[clave]!r} no cumple {requisito!r}"
            )
    return fallas


def evaluate_state(final_state: FinalState, target_state: TargetState) -> Evaluacion:
    """Compara el estado final con el estado objetivo. Determinista.

    Devuelve `{"success": bool, "reasons": [...], "reglas": {...}}`. `reasons` está vacía
    si y solo si `success` es `True`; `reglas` da el veredicto de cada regla por separado,
    que es lo que la etapa 9 necesita para explicar un NO-GO caso por caso.
    """
    razones: list[Razon] = []

    recomendados = set(final_state.recomendaciones)

    # 1. must_include
    faltantes = [pid for pid in target_state.must_include if pid not in recomendados]
    if faltantes:
        razones.append(
            _razon("must_include", "faltan productos exigidos en la recomendación", faltantes)
        )

    # 2. must_exclude
    prohibidos = [pid for pid in target_state.must_exclude if pid in recomendados]
    if prohibidos:
        razones.append(_razon("must_exclude", "se recomendaron productos excluidos", prohibidos))

    # 3. must_compare
    sin_comparar = [
        par for par in target_state.must_compare if not final_state.entrego_comparacion(par)
    ]
    if sin_comparar:
        razones.append(
            _razon(
                "must_compare",
                "no se entregaron todas las comparaciones exigidas: "
                + ", ".join(f"{a}↔{b}" for a, b in sin_comparar),
                [pid for par in sin_comparar for pid in par],
            )
        )

    # 4. constraints
    if not target_state.constraints.vacias:
        infractores: list[str] = []
        detalles: list[str] = []
        for producto in final_state.productos_recomendados:
            fallas = violaciones_de_constraints(producto, target_state.constraints)
            if fallas:
                infractores.append(producto.id)
                detalles.append(f"{producto.id}: {'; '.join(fallas)}")
        if infractores:
            razones.append(
                _razon(
                    "constraints",
                    "recomendaciones que violan las restricciones del usuario — "
                    + " | ".join(detalles),
                    infractores,
                )
            )

    # 5. forbidden_tools
    prohibidas_usadas = sorted(
        {
            nombre
            for nombre in final_state.herramientas_invocadas
            if nombre in set(target_state.forbidden_tools)
        }
    )
    if prohibidas_usadas:
        razones.append(
            _razon(
                "forbidden_tools",
                "se invocaron herramientas prohibidas: " + ", ".join(prohibidas_usadas),
                prohibidas_usadas,
            )
        )

    # 6. recomendaciones inexistentes
    if final_state.recomendaciones_desconocidas:
        razones.append(
            _razon(
                "recomendaciones_existentes",
                "se recomendaron ids que no existen en el catálogo",
                final_state.recomendaciones_desconocidas,
            )
        )

    # 7. mínimo de recomendaciones
    if len(final_state.recomendaciones) < target_state.min_recomendaciones:
        razones.append(
            _razon(
                "min_recomendaciones",
                f"se exigían al menos {target_state.min_recomendaciones} recomendaciones y "
                f"se entregaron {len(final_state.recomendaciones)}",
            )
        )

    reglas_falladas = {razon["regla"] for razon in razones}
    return {
        "success": not razones,
        "reasons": razones,
        "reglas": {regla: regla not in reglas_falladas for regla in REGLAS},
    }


__all__ = [
    "EVALUATOR_VERSION",
    "Evaluacion",
    "REGLAS",
    "Razon",
    "evaluate_state",
    "violaciones_de_constraints",
]
