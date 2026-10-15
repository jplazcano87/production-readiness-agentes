"""Argumentos comunes de los scripts de `scripts/`.

Homogeneiza las banderas que exigen las reglas de trabajo: `--dry-run` (obligatoria en
todo script que llame a la API) y `--mlflow` (seguimiento opcional).
"""

from __future__ import annotations

import argparse

CONFIGS = ("none", "prompt_only", "dual_llm", "cte")
SPLITS = ("dev", "test")


def add_common_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Añade los argumentos que comparten todos los scripts que llaman a la API."""
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="No llama a la API: imprime tokens y costo estimado en USD y termina.",
    )
    parser.add_argument(
        "--mlflow",
        action="store_true",
        help="Activa el seguimiento opcional con MLflow (backend local en mlruns/).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Sobrescribe la semilla del experimento definida en configs/experiments.yaml.",
    )
    return parser


def add_config_arg(
    parser: argparse.ArgumentParser, *, required: bool = True
) -> argparse.ArgumentParser:
    parser.add_argument(
        "--config",
        choices=CONFIGS,
        required=required,
        help="Configuración de defensa del agente.",
    )
    return parser


def add_split_arg(
    parser: argparse.ArgumentParser, *, default: str = "test"
) -> argparse.ArgumentParser:
    parser.add_argument(
        "--split",
        choices=SPLITS,
        default=default,
        help="Partición del corpus sobre la que ejecutar.",
    )
    return parser


__all__ = ["CONFIGS", "SPLITS", "add_common_args", "add_config_arg", "add_split_arg"]
