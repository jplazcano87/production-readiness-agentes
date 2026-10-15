"""Consolidación conjuntiva del veredicto go/no-go (etapa 9).

`veredicto.consolidar` aplica las reglas de `configs/thresholds.yaml` a los resultados de E1 a
E4 y devuelve un veredicto que **cita cada regla por su id**, con el valor medido, su intervalo
si el experimento lo calculó, el umbral y las unidades de evidencia que motivan cada fallo.

Ninguna política se decide aquí: el YAML es la política y este paquete la aplica.
"""

from prf.verdict.evidencia import TOPE
from prf.verdict.reglas import CRITICAS, Evaluacion, Regla, cargar_reglas, leer_campo
from prf.verdict.veredicto import (
    GO,
    INDETERMINADO,
    NO_GO,
    Fuentes,
    consolidar,
    evaluar_regla,
    evaluar_tolerancia_cero,
)

__all__ = [
    "CRITICAS",
    "GO",
    "INDETERMINADO",
    "NO_GO",
    "TOPE",
    "Evaluacion",
    "Fuentes",
    "Regla",
    "cargar_reglas",
    "consolidar",
    "evaluar_regla",
    "evaluar_tolerancia_cero",
    "leer_campo",
]
