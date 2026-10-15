"""Carga y validación de `configs/*.yaml`.

Los tres archivos de configuración son la única fuente de ids de modelo, precios,
umbrales y tamaños de muestra. Ningún módulo debe llevar esos valores incrustados.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from prf.infra.paths import paths


class ModelRole(BaseModel):
    """Parámetros de inferencia de un rol (agente, juez, cuarentena, ...)."""

    model_config = ConfigDict(protected_namespaces=(), extra="forbid")

    id: str
    max_tokens: int = Field(gt=0)
    temperature: float = Field(ge=0.0, le=1.0)
    thinking: dict[str, Any] | None = None


class Defaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_retries: int = Field(default=5, ge=0)
    backoff_base_s: float = Field(default=1.0, gt=0)
    backoff_max_s: float = Field(default=60.0, gt=0)
    timeout_s: float = Field(default=600.0, gt=0)


class ModelPrice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_per_mtok: float = Field(ge=0)
    output_per_mtok: float = Field(ge=0)


class PricingMultipliers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cache_write: float = Field(default=1.25, ge=0)
    cache_read: float = Field(default=0.10, ge=0)
    batch: float = Field(default=0.50, ge=0)


class ModelsConfig(BaseModel):
    """Contenido de `configs/models.yaml`."""

    model_config = ConfigDict(protected_namespaces=(), extra="forbid")

    defaults: Defaults = Field(default_factory=Defaults)
    roles: dict[str, ModelRole]
    pricing: dict[str, ModelPrice]
    pricing_multipliers: PricingMultipliers = Field(default_factory=PricingMultipliers)

    def role(self, name: str) -> ModelRole:
        """El modelo asignado a un rol, o un error que lista los roles declarados."""
        try:
            return self.roles[name]
        except KeyError as exc:  # pragma: no cover - error de configuración
            disponibles = ", ".join(sorted(self.roles))
            raise KeyError(
                f"rol de modelo desconocido: {name!r}. Disponibles: {disponibles}"
            ) from exc

    def price(self, model_id: str) -> ModelPrice:
        try:
            return self.pricing[model_id]
        except KeyError as exc:  # pragma: no cover - error de configuración
            raise KeyError(
                f"no hay precio declarado para el modelo {model_id!r} en configs/models.yaml"
            ) from exc


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"no existe el archivo de configuración: {path}")
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} debe contener un mapeo YAML en la raíz")
    return data


@cache
def load_models(path: Path | None = None) -> ModelsConfig:
    """Devuelve `configs/models.yaml` validado."""
    return ModelsConfig.model_validate(_read_yaml(path or paths.configs / "models.yaml"))


@cache
def load_thresholds(path: Path | None = None) -> dict[str, Any]:
    """Devuelve `configs/thresholds.yaml` tal cual (dict), verificando lo indispensable.

    No se modela con pydantic a propósito: el archivo es política versionada y debe poder
    crecer (etapa 9) sin romper la carga.
    """
    data = _read_yaml(path or paths.configs / "thresholds.yaml")
    faltantes = [k for k in ("version", "status", "changelog") if k not in data]
    if faltantes:
        raise ValueError(f"thresholds.yaml sin campos obligatorios: {', '.join(faltantes)}")
    return data


@cache
def load_experiments(path: Path | None = None) -> dict[str, Any]:
    """Devuelve `configs/experiments.yaml`."""
    data = _read_yaml(path or paths.configs / "experiments.yaml")
    for clave in ("seed_global", "corpus_version", "experiments"):
        if clave not in data:
            raise ValueError(f"experiments.yaml sin campo obligatorio: {clave}")
    return data


__all__ = [
    "Defaults",
    "ModelPrice",
    "ModelRole",
    "ModelsConfig",
    "PricingMultipliers",
    "load_experiments",
    "load_models",
    "load_thresholds",
]
