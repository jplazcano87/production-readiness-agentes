"""Estilo común de las figuras del informe.

Las figuras se imprimen en un documento académico, probablemente en blanco y negro. De
ahí las tres reglas que gobiernan este módulo:

1. **La identidad nunca depende del color.** Las series se distinguen por tono de gris y
   por textura, y siempre llevan leyenda. Un lector daltónico o una impresión en escala de
   grises leen exactamente lo mismo.
2. **La textura va a 45° y 135°, nunca horizontal ni vertical**: esas dos orientaciones se
   confunden con la rejilla y con el borde de la barra.
3. **Una serie no lleva leyenda**: el título ya la nombra, y una leyenda de un elemento
   solo gasta espacio.

Parámetros fijados por el plan: fondo blanco, 200 dpi, ancho 6,5 pulgadas, títulos en
español.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # sin pantalla: los scripts corren en terminal
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import ticker  # noqa: E402
from matplotlib.axes import Axes  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

ANCHO_PULGADAS = 6.5
DPI = 200

# Escala de grises ordenada: más oscuro = más peso visual. No codifica ninguna semántica.
TINTA = "#1a1a1a"
TINTA_SUAVE = "#595959"
RELLENO = "#767676"
RELLENO_CLARO = "#c7c7c7"
REJILLA = "#d9d9d9"

# Texturas para separar series en impresión monocroma: 45° y su espejo a 135°, nunca
# horizontal ni vertical (se confundirían con la rejilla y con el borde de la barra). Misma
# densidad en las dos para que ninguna serie pese visualmente más que la otra.
TEXTURAS = ("/" * 3, chr(92) * 3)

ESTILO: dict[str, Any] = {
    "figure.dpi": DPI,
    "savefig.dpi": DPI,
    "figure.facecolor": "white",
    "savefig.facecolor": "white",
    "axes.facecolor": "white",
    "font.size": 8,
    "axes.titlesize": 9,
    "axes.labelsize": 8,
    "xtick.labelsize": 7.5,
    "ytick.labelsize": 7.5,
    "legend.fontsize": 7.5,
    "axes.labelcolor": TINTA,
    "axes.edgecolor": TINTA_SUAVE,
    "text.color": TINTA,
    "xtick.color": TINTA_SUAVE,
    "ytick.color": TINTA_SUAVE,
    "axes.grid": True,
    "axes.grid.axis": "y",
    "grid.color": REJILLA,
    "grid.linewidth": 0.6,
    "axes.axisbelow": True,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "legend.frameon": False,
    "hatch.linewidth": 0.6,
}


def aplicar_estilo() -> None:
    """Fija el estilo global. Se llama una vez por script."""
    plt.rcParams.update(ESTILO)


def figura(alto: float, ancho: float = ANCHO_PULGADAS, **kwargs: Any) -> tuple[Figure, Any]:
    """Crea una figura del ancho de la caja de texto del informe."""
    return plt.subplots(figsize=(ancho, alto), **kwargs)


def guardar(fig: Figure, destino: Path | str) -> Path:
    """Guarda en PNG con el ancho exacto y cierra la figura.

    Sin `bbox_inches="tight"` a propósito: ese modo recorta o **ensancha** la imagen según
    lo que sobresalga, y dos figuras del mismo informe acabarían con anchos distintos. El
    ancho es un parámetro del documento, no un resultado del contenido.
    """
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destino, dpi=DPI, facecolor="white")
    plt.close(fig)
    return destino


class _ComaDecimal(ticker.Formatter):
    """Formateador de eje con coma decimal y el mismo número de decimales en todas las marcas.

    Matplotlib escribe `0.05` y el documento escribe `0,05`. Mezclar las dos notaciones en el
    mismo trabajo obliga al lector a decidir en cada cifra cuál está leyendo, y en un número
    como 1.500 la diferencia no es de estilo: es de tres órdenes de magnitud.

    Los decimales se igualan **dentro de cada eje**, no por marca: un eje rotulado
    `0 · 0,05 · 0,1 · 0,15 · 0,2` se lee peor que `0,00 · 0,05 · 0,10 · 0,15 · 0,20`, porque
    obliga a comparar cifras de distinta precisión aparente. Se decide con las marcas que el
    localizador haya elegido, así que funciona igual si cambia la escala.
    """

    # Hereda de `ticker.Formatter` y no es un simple invocable: `set_major_formatter` envuelve
    # los invocables en un `FuncFormatter`, que ignora `set_locs`, así que los decimales se
    # quedaban en cero y el eje salía rotulado «0 · 0 · 0 · 1».

    def __init__(self) -> None:
        super().__init__()
        self.decimales = 0

    def set_locs(self, locs: Sequence[float]) -> None:
        self.decimales = max((self._decimales_de(v) for v in locs), default=0)

    @staticmethod
    def _decimales_de(valor: float) -> int:
        texto = f"{valor:.10f}".rstrip("0")
        entero, _, fraccion = texto.partition(".")
        return len(fraccion)

    def __call__(self, valor: float, pos: int | None = None) -> str:
        return f"{valor:.{self.decimales}f}".replace(".", ",")


def coma_decimal(ax: Axes, ejes: str = "xy") -> None:
    """Pone coma decimal en los ejes indicados, que es la convención del informe."""
    if "x" in ejes:
        ax.xaxis.set_major_formatter(_ComaDecimal())
    if "y" in ejes:
        ax.yaxis.set_major_formatter(_ComaDecimal())


def numero(valor: float, decimales: int = 2) -> str:
    """Un valor suelto con coma decimal, para etiquetas directas y anotaciones."""
    return f"{valor:.{decimales}f}".replace(".", ",")


def etiquetar_barras(
    ax: Axes,
    barras: Iterable[Rectangle],
    *,
    formato: str = "{:.0f}",
    separacion: float = 0.01,
) -> None:
    """Rotula cada barra con su valor.

    Las etiquetas directas evitan que el lector tenga que estimar contra el eje, que es la
    principal fuente de error de lectura en un gráfico de barras impreso.
    """
    tope = max((b.get_height() for b in barras), default=0)
    for barra in barras:
        altura = barra.get_height()
        ax.text(
            barra.get_x() + barra.get_width() / 2,
            altura + tope * separacion,
            formato.format(altura),
            ha="center",
            va="bottom",
            fontsize=7,
            color=TINTA,
        )


def sin_marcos(ax: Axes) -> None:
    """Deja solo los ejes izquierdo e inferior, en tinta suave, y la rejilla al fondo."""
    # `axes.axisbelow` en rcParams no siempre gana frente a un `grid()` posterior: se fija
    # aquí para que ninguna línea de rejilla cruce por encima de una barra.
    ax.set_axisbelow(True)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    for lado in ("left", "bottom"):
        ax.spines[lado].set_color(TINTA_SUAVE)
        ax.spines[lado].set_linewidth(0.8)


__all__ = [
    "ANCHO_PULGADAS",
    "DPI",
    "coma_decimal",
    "numero",
    "ESTILO",
    "RELLENO",
    "RELLENO_CLARO",
    "TEXTURAS",
    "TINTA",
    "TINTA_SUAVE",
    "aplicar_estilo",
    "etiquetar_barras",
    "figura",
    "guardar",
    "sin_marcos",
]
