"""Huella de lo que cada configuración le pone delante al modelo.

Un system prompt que cambia sin que nadie lo note invalida la comparación entre
configuraciones: la diferencia medida deja de ser la defensa y pasa a ser el texto. Estas
huellas son un resumen estable de ese texto, para poder afirmar —antes de gastar en una
corrida larga, y después— que el agente es el mismo que se congeló.

No sustituyen a `tests/test_registro_invariante.py`, que compara **toda** la conversación que
llega al modelo. Aquí solo se resume el system prompt, que es lo que se puede calcular sin
ejecutar nada y por eso sirve de compuerta.
"""

from __future__ import annotations

import hashlib
from typing import Any

from prf.agent.configuraciones import CONFIGURACIONES, Configuracion
from prf.agent.prompts import (
    SISTEMA_PLANIFICADOR,
    bloque_cumplimiento,
    sistema_agente,
)


def _sha(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


def system_prompt(config: Configuracion, despliegue: dict[str, Any]) -> str:
    """El system prompt conversacional de una configuración, sin el bloque de catálogo.

    El catálogo se excluye a propósito: depende del corpus, que tiene su propio hash, y
    mezclarlo aquí haría que un cambio de corpus se confundiera con un cambio de prompt.
    """
    return sistema_agente(
        advierte=config.advierte_en_prompt,
        cuarentena=config.usa_cuarentena,
        despliegue=despliegue,
        clausulas_defensivas=config.clausulas_defensivas,
    )


def huellas(despliegue: dict[str, Any]) -> dict[str, str]:
    """Huella por configuración, más la del planificador de `cte`.

    El planificador va aparte porque su modelo **no** ve `SISTEMA_BASE`: cambiar el prompt
    conversacional no lo toca, y al revés. Confundirlos escondería justamente eso.
    """
    salida = {n: _sha(system_prompt(c, despliegue)) for n, c in sorted(CONFIGURACIONES.items())}
    salida["cte_planificador"] = _sha(
        SISTEMA_PLANIFICADOR + "\n\n" + bloque_cumplimiento(despliegue)
    )
    return salida


__all__ = ["huellas", "system_prompt"]
