"""Reanudación, tope de gasto y piloto: lo que una corrida larga necesita para fallar bien.

Tres cosas que este proyecto aprendió a golpes y que hasta ahora estaban repartidas por cada
guion o simplemente no estaban:

- **Reanudar.** Una corrida de mil ejecuciones que muere en la 860 —pasó -- no puede obligar a
  pagar las 860 otra vez. Cada ejecución se persiste al terminar, y `--reanudar` salta las que
  ya tienen su archivo en vez de volver a llamar a la API.
- **Tope de gasto.** El `--dry-run` es una estimación, no una factura, y puede quedarse corta.
  Un tope en `1,3 ×` la estimación detiene la corrida y **guarda el estado** en vez de dejar
  que un error de cálculo se convierta en una sorpresa en la factura.
- **Piloto.** Antes de la corrida completa se ejecuta un puñado de casos y se comprueba que el
  arnés funciona. Un fallo sistemático detectado en la ejecución 12 cuesta un dólar; detectado
  al final, cuesta la corrida entera y un día.

El estado vive en `results/estado_<salida>.json` y es legible: dice qué se hizo, cuánto se
gastó y por qué se detuvo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FACTOR_TOPE = 1.3


class TopeDeGasto(RuntimeError):
    """El gasto acumulado superó el tope. La corrida se detiene con el estado guardado."""


class PilotoFallido(RuntimeError):
    """El piloto no cumplió sus criterios: no se sigue con la corrida completa."""


@dataclass
class EstadoCorrida:
    """Lo hecho, lo gastado y el tope, persistido junto a los resultados."""

    salida: str
    directorio: Path
    estimacion_usd: float
    factor_tope: float = FACTOR_TOPE
    hechas: set[str] = field(default_factory=set)
    detenida_por: str | None = None

    @property
    def tope_usd(self) -> float:
        return self.estimacion_usd * self.factor_tope

    @property
    def archivo(self) -> Path:
        return self.directorio / f"estado_{self.salida}.json"

    # ------------------------------------------------------------------ reanudar

    def cargar(self, directorio_runs: Path, ids_esperados: list[str]) -> int:
        """Marca como hechas las ejecuciones que ya tienen su archivo persistido.

        Se comprueba contra el disco y no contra el estado guardado: el archivo de una
        ejecución es la evidencia de que ocurrió, y confiar en un contador aparte permitiría
        saltarse una ejecución que en realidad no se hizo.
        """
        self.hechas = {
            run_id for run_id in ids_esperados if (directorio_runs / f"{run_id}.json").is_file()
        }
        return len(self.hechas)

    def pendiente(self, run_id: str) -> bool:
        return run_id not in self.hechas

    # -------------------------------------------------------------------- gasto

    def comprobar_gasto(self, costo_usd: float) -> None:
        """Detiene la corrida si el gasto acumulado supera el tope."""
        if costo_usd > self.tope_usd:
            self.detenida_por = (
                f"gasto acumulado USD {costo_usd:.2f} sobre un tope de "
                f"USD {self.tope_usd:.2f} ({self.factor_tope:g}× la estimación de "
                f"USD {self.estimacion_usd:.2f})"
            )
            self.guardar(costo_usd)
            raise TopeDeGasto(self.detenida_por)

    def guardar(self, costo_usd: float, extra: dict[str, Any] | None = None) -> Path:
        self.directorio.mkdir(parents=True, exist_ok=True)
        self.archivo.write_text(
            json.dumps(
                {
                    "salida": self.salida,
                    "n_hechas": len(self.hechas),
                    "costo_usd": round(costo_usd, 4),
                    "estimacion_usd": round(self.estimacion_usd, 4),
                    "tope_usd": round(self.tope_usd, 4),
                    "detenida_por": self.detenida_por,
                    **(extra or {}),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return self.archivo


# --------------------------------------------------------------------------- piloto

UMBRAL_UTILIDAD = 0.9
UMBRAL_ENTREGA = 0.9


def verificar_piloto(metricas: dict[str, float | int | None]) -> list[str]:
    """Criterios del piloto sobre las métricas que el experimento sí produce.

    Devuelve la lista de incumplimientos, vacía si todo pasa. Un criterio cuya métrica es
    `None` **no aplica** a ese experimento y no se inventa: E1 no tiene utilidad benigna ni
    entrega de cargas, y fingir que las tiene sería peor que no comprobarlas.
    """
    fallos: list[str] = []
    utilidad = metricas.get("utilidad_benigna")
    entrega = metricas.get("entrega")
    errores = metricas.get("errores") or 0

    if utilidad is not None and utilidad < UMBRAL_UTILIDAD:
        fallos.append(f"utilidad benigna {utilidad:.3f} < {UMBRAL_UTILIDAD}")
    if entrega is not None and entrega < UMBRAL_ENTREGA:
        fallos.append(f"entrega de cargas {entrega:.3f} < {UMBRAL_ENTREGA}")
    if errores:
        fallos.append(f"{errores} ejecuciones con error del arnés")
    return fallos


def resumen_piloto(metricas: dict[str, float | int | None]) -> str:
    """Una línea con las métricas del piloto, para decidir si seguir con la corrida larga."""
    partes = []
    for clave, etiqueta in (
        ("utilidad_benigna", "utilidad benigna"),
        ("entrega", "entrega"),
    ):
        valor = metricas.get(clave)
        partes.append(f"{etiqueta} {'no aplica' if valor is None else f'{valor:.3f}'}")
    partes.append(f"errores {metricas.get('errores') or 0}")
    return " · ".join(partes)


__all__ = [
    "EstadoCorrida",
    "FACTOR_TOPE",
    "PilotoFallido",
    "TopeDeGasto",
    "UMBRAL_ENTREGA",
    "UMBRAL_UTILIDAD",
    "resumen_piloto",
    "verificar_piloto",
]
