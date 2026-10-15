"""Intervalos de confianza para proporciones, y por qué el bootstrap no sirve en cero.

El bootstrap remuestrea la muestra observada. Si la muestra son 210 ceros, **toda** remuestra
es 210 ceros y el intervalo sale `[0,000, 0,000]`: no expresa certeza sino una degeneración
del método. Publicar eso al lado de un ASR de cero afirmaría que el riesgo es exactamente nulo,
que es justo lo que 210 ejecuciones sin un solo éxito no permiten concluir.

Para una proporción hay intervalos exactos que sí lo permiten:

- **Clopper-Pearson** es exacto y conservador, y es el que corresponde cuando la proporción
  observada toca un extremo (0 o 1). Con 0 de 210, el límite superior al 95 % es 0,017: el ASR
  real podría ser uno de cada sesenta y este experimento no lo habría visto.
- **Wilson** tiene mejor cobertura en el resto del rango y no se sale de [0, 1] como haría el
  intervalo normal. Es el que se usa cuando hay al menos un éxito y al menos un fallo.

`ic_proporcion` elige por esa regla y **declara el método en el resultado**, para que la tabla
del informe pueda citarlo. El bootstrap sobre casos se conserva donde mide otra cosa: en pass^k
la unidad de remuestreo es el caso y el estadístico no es una proporción simple.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scipy.stats import beta, norm


@dataclass(frozen=True)
class IC:
    """Intervalo para una proporción, con el método que lo produjo."""

    valor: float
    ic_inferior: float
    ic_superior: float
    n: int
    exitos: int
    metodo: str
    confianza: float = 0.95

    def to_dict(self) -> dict[str, Any]:
        return {
            "valor": round(self.valor, 6),
            "ic_inferior": round(self.ic_inferior, 6),
            "ic_superior": round(self.ic_superior, 6),
            "n": self.n,
            "exitos": self.exitos,
            "metodo": self.metodo,
            "confianza": self.confianza,
        }


def clopper_pearson(exitos: int, n: int, confianza: float = 0.95) -> tuple[float, float]:
    """Intervalo exacto, el que corresponde cuando la proporción toca 0 o 1."""
    if n <= 0:
        return 0.0, 1.0
    alfa = 1 - confianza
    inferior = 0.0 if exitos == 0 else float(beta.ppf(alfa / 2, exitos, n - exitos + 1))
    superior = 1.0 if exitos == n else float(beta.ppf(1 - alfa / 2, exitos + 1, n - exitos))
    return inferior, superior


def wilson(exitos: int, n: int, confianza: float = 0.95) -> tuple[float, float]:
    """Intervalo de Wilson: buena cobertura en el interior del rango y siempre en [0, 1]."""
    if n <= 0:
        return 0.0, 1.0
    z = float(norm.ppf(1 - (1 - confianza) / 2))
    p = exitos / n
    denominador = 1 + z**2 / n
    centro = (p + z**2 / (2 * n)) / denominador
    radio = z * ((p * (1 - p) / n + z**2 / (4 * n**2)) ** 0.5) / denominador
    return max(0.0, centro - radio), min(1.0, centro + radio)


def ic_proporcion(exitos: int, n: int, confianza: float = 0.95) -> IC:
    """Intervalo para una proporción, eligiendo el método según dónde caiga.

    Clopper-Pearson en los extremos —donde el bootstrap degenera y Wilson pierde cobertura—
    y Wilson en el resto. El método elegido viaja en el resultado.
    """
    if n <= 0:
        return IC(0.0, 0.0, 1.0, 0, 0, "sin_datos", confianza)
    en_el_extremo = exitos == 0 or exitos == n
    inferior, superior = (
        clopper_pearson(exitos, n, confianza) if en_el_extremo else wilson(exitos, n, confianza)
    )
    return IC(
        valor=exitos / n,
        ic_inferior=inferior,
        ic_superior=superior,
        n=n,
        exitos=exitos,
        metodo="clopper_pearson" if en_el_extremo else "wilson",
        confianza=confianza,
    )


__all__ = ["IC", "clopper_pearson", "ic_proporcion", "wilson"]
