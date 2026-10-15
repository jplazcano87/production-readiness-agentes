"""Intervalos de confianza por bootstrap sobre casos.

El remuestreo es **sobre casos, no sobre ejecuciones**. Un caso aporta `n` ejecuciones
correlacionadas entre sí —comparten intención, restricciones y catálogo—, así que tratarlas
como observaciones independientes estrecharía el intervalo de forma artificial y haría
parecer más precisa una medición que no lo es. La unidad de observación es el caso.

Se usa el intervalo percentil, que no supone normalidad. Con 42 casos y 1.000 remuestreos
es lo apropiado: pass^k está acotado en [0, 1] y su distribución se apelmaza contra los
extremos, donde un intervalo normal daría límites fuera de rango.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class IntervaloConfianza:
    """Estimación puntual y sus límites."""

    valor: float
    inferior: float
    superior: float
    confianza: float
    n_remuestreos: int
    n_casos: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "valor": round(self.valor, 6),
            "ic_inferior": round(self.inferior, 6),
            "ic_superior": round(self.superior, 6),
            "confianza": self.confianza,
            "n_remuestreos": self.n_remuestreos,
            "n_casos": self.n_casos,
        }


def bootstrap_ic(
    observaciones: Sequence[Any],
    estadistico: Callable[[Sequence[Any]], float],
    *,
    n_remuestreos: int = 1000,
    confianza: float = 0.95,
    seed: int = 20260906,
) -> IntervaloConfianza:
    """IC percentil del `estadistico` calculado sobre `observaciones` (una por caso).

    La semilla es fija: un intervalo de confianza que cambia entre ejecuciones del mismo
    análisis no es reproducible, y el informe cita sus límites.
    """
    if not observaciones:
        raise ValueError("no hay observaciones sobre las que remuestrear")
    if not 0 < confianza < 1:
        raise ValueError(f"la confianza debe estar en (0, 1), recibió {confianza}")

    rng = random.Random(seed)
    n = len(observaciones)
    valor = estadistico(observaciones)

    if n == 1:
        return IntervaloConfianza(valor, valor, valor, confianza, 0, 1)

    replicas = []
    for _ in range(n_remuestreos):
        muestra = [observaciones[rng.randrange(n)] for _ in range(n)]
        replicas.append(estadistico(muestra))
    replicas.sort()

    alfa = (1 - confianza) / 2
    inferior = replicas[max(0, int(alfa * n_remuestreos))]
    superior = replicas[min(n_remuestreos - 1, int((1 - alfa) * n_remuestreos))]
    return IntervaloConfianza(valor, inferior, superior, confianza, n_remuestreos, n)


__all__ = ["IntervaloConfianza", "bootstrap_ic"]
