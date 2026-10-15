"""Seguimiento opcional con MLflow.

Decisión cerrada: `results/*.json` es la fuente de verdad y el repositorio debe
funcionar sin MLflow. El seguimiento se activa solo con `--mlflow`; si la dependencia
no está instalada, se informa y se continúa sin ella.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from prf.infra.paths import paths


class Tracker:
    """Fachada sobre MLflow que degrada a no-op cuando está desactivado o ausente."""

    def __init__(self, enabled: bool = False, *, experiment: str = "prf-agente-preventa") -> None:
        self.enabled = enabled
        self.experiment = experiment
        self._mlflow: Any | None = None
        if not enabled:
            return
        try:
            import mlflow  # noqa: PLC0415 - importación deliberadamente perezosa
        except ImportError:
            print(
                "[mlflow] no está instalado; se continúa sin seguimiento. "
                'Instálalo con: pip install -e ".[tracking]"'
            )
            self.enabled = False
            return
        self._mlflow = mlflow
        mlflow.set_tracking_uri(f"file:{paths.mlruns}")
        mlflow.set_experiment(experiment)

    @contextmanager
    def run(self, nombre: str) -> Iterator[Tracker]:
        """Abre una corrida de seguimiento, o no hace nada si el seguimiento está apagado."""
        if not self.enabled or self._mlflow is None:
            yield self
            return
        with self._mlflow.start_run(run_name=nombre):
            yield self

    def log_params(self, params: dict[str, Any]) -> None:
        if self.enabled and self._mlflow is not None:
            self._mlflow.log_params({k: str(v) for k, v in params.items()})

    def log_metrics(self, metrics: dict[str, float]) -> None:
        if self.enabled and self._mlflow is not None:
            self._mlflow.log_metrics(
                {k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))}
            )

    def log_artifact(self, ruta: Path | str) -> None:
        if self.enabled and self._mlflow is not None:
            self._mlflow.log_artifact(str(ruta))


__all__ = ["Tracker"]
