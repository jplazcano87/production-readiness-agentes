"""pass^k y pass@k: dos métricas distintas que suelen confundirse.

- **pass^k** (τ-bench) mide **fiabilidad**: la probabilidad de que las `k` ejecuciones
  elegidas tengan éxito **todas**. Es la que responde a PI1, porque un agente que atiende a
  un cliente no puede acertar «alguna de ocho veces»: tiene que acertar la vez que le toca.
- **pass@k** (HumanEval) mide **alcanzabilidad**: la probabilidad de que **al menos una** de
  `k` acierte. Sirve cuando alguien filtra las salidas después; aquí no hay nadie filtrando.

Con `n` ejecuciones de un caso, de las cuales `c` tuvieron éxito, los estimadores
insesgados son:

    pass^k = C(c, k) / C(n, k)          probabilidad de que las k elegidas acierten todas
    pass@k = 1 − C(n−c, k) / C(n, k)    probabilidad de que al menos una acierte

Se calculan de forma exacta con enteros (`math.comb`), no simulando: para n = 8 el espacio
de subconjuntos es pequeño y una estimación por muestreo añadiría ruido a una cantidad que
tiene forma cerrada.

El agregado sobre varios casos es la **media de los pass^k por caso**, no el pass^k de los
éxitos agrupados: cada caso es una unidad de observación y agrupar mezclaría casos fáciles
con difíciles.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def _validar(n: int, c: int, k: int) -> None:
    if n <= 0:
        raise ValueError(f"n debe ser positivo, recibió {n}")
    if not 0 <= c <= n:
        raise ValueError(f"c debe estar entre 0 y n={n}, recibió {c}")
    if not 1 <= k <= n:
        raise ValueError(f"k debe estar entre 1 y n={n}, recibió {k}")


def passk(n: int, c: int, k: int) -> float:
    """pass^k: probabilidad de que `k` ejecuciones elegidas al azar acierten **todas**.

    `C(c, k) / C(n, k)`. Vale 0 en cuanto `c < k`, porque no hay forma de elegir `k`
    aciertos entre menos de `k`.
    """
    _validar(n, c, k)
    if c < k:
        return 0.0
    return math.comb(c, k) / math.comb(n, k)


def pass_at_k(n: int, c: int, k: int) -> float:
    """pass@k: probabilidad de que **al menos una** de `k` ejecuciones acierte.

    `1 − C(n−c, k) / C(n, k)`. Se incluye para poder contrastar ambas métricas en el
    informe: la diferencia entre las dos es justamente el argumento de por qué la
    fiabilidad de un agente no se mide con pass@k.
    """
    _validar(n, c, k)
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def passk_por_caso(exitos_por_caso: Sequence[int], n: int, k: int) -> list[float]:
    """pass^k de cada caso, en el mismo orden."""
    return [passk(n, c, k) for c in exitos_por_caso]


def passk_agregado(exitos_por_caso: Sequence[int], n: int, k: int) -> float:
    """Media de los pass^k por caso.

    No es lo mismo que el pass^k de los éxitos agrupados: agrupar trataría a los casos
    fáciles y difíciles como una sola población y el resultado dependería de cuántas
    ejecuciones aportó cada uno.
    """
    if not exitos_por_caso:
        raise ValueError("no hay casos sobre los que agregar")
    valores = passk_por_caso(exitos_por_caso, n, k)
    return sum(valores) / len(valores)


def curva_passk(exitos_por_caso: Sequence[int], n: int, ks: Sequence[int]) -> dict[int, float]:
    """pass^k agregado para cada `k`. Es la curva de la figura 4."""
    return {k: passk_agregado(exitos_por_caso, n, k) for k in ks}


def exitos_desde_matriz(matriz: Sequence[Sequence[bool | int]]) -> list[int]:
    """Convierte una matriz caso × ejecución (0/1) en el número de éxitos por caso."""
    return [sum(1 for valor in fila if valor) for fila in matriz]


__all__ = [
    "curva_passk",
    "exitos_desde_matriz",
    "pass_at_k",
    "passk",
    "passk_agregado",
    "passk_por_caso",
]
