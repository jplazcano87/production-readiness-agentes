"""Rutas del repositorio, resueltas desde la ubicación del paquete.

Se resuelven una sola vez para que los scripts funcionen sin importar el directorio
de trabajo desde el que se invoquen.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def _find_root() -> Path:
    """Sube desde este archivo hasta el directorio que contiene `pyproject.toml`."""
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    # Instalación fuera del árbol del repositorio: se usa el directorio de trabajo.
    return Path.cwd()


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def configs(self) -> Path:
        return self.root / "configs"

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def corpus(self) -> Path:
        return self.data / "corpus"

    @property
    def splits(self) -> Path:
        return self.data / "splits"

    @property
    def templates(self) -> Path:
        return self.data / "templates"

    @property
    def annotation(self) -> Path:
        return self.data / "annotation"

    @property
    def results(self) -> Path:
        return self.root / "results"

    @property
    def figures(self) -> Path:
        return self.root / "figures"

    @property
    def tables(self) -> Path:
        return self.root / "tables"

    @property
    def mlruns(self) -> Path:
        return self.root / "mlruns"

    def corpus_version(self, version: str) -> Path:
        return self.corpus / version

    def splits_version(self, version: str) -> Path:
        return self.splits / version


paths = Paths(root=_find_root())

__all__ = ["Paths", "paths"]
