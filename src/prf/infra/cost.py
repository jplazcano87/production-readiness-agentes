"""Contabilidad de tokens y estimación de costo en USD.

Todo script que llame a la API tiene `--dry-run`, que
imprime tokens y costo estimado sin llamar a la API. Este módulo es la implementación
compartida de esa estimación, para que todos los scripts reporten lo mismo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from prf.infra.config import ModelsConfig

_MTOK = 1_000_000


@dataclass(frozen=True)
class Usage:
    """Tokens de una llamada o de un agregado de llamadas."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_creation_tokens=self.cache_creation_tokens + other.cache_creation_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
        )

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_tokens
            + self.cache_read_tokens
        )

    @classmethod
    def from_sdk(cls, usage: Any) -> Usage:
        """Construye `Usage` desde el objeto `usage` del SDK.

        Los campos de caché pueden venir ausentes o en `None` según el modelo y la
        petición; se normalizan a 0.
        """

        def _get(name: str) -> int:
            value = getattr(usage, name, None)
            if value is None and isinstance(usage, dict):
                value = usage.get(name)
            return int(value or 0)

        return cls(
            input_tokens=_get("input_tokens"),
            output_tokens=_get("output_tokens"),
            cache_creation_tokens=_get("cache_creation_input_tokens"),
            cache_read_tokens=_get("cache_read_input_tokens"),
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "cache_read_tokens": self.cache_read_tokens,
        }


@dataclass(frozen=True)
class CostEstimate:
    """Costo estimado de un conjunto de llamadas homogéneo (mismo modelo y modo)."""

    concepto: str
    model: str
    n_llamadas: int
    usage: Usage
    batch: bool
    usd: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "concepto": self.concepto,
            "model": self.model,
            "n_llamadas": self.n_llamadas,
            "batch": self.batch,
            "usd": round(self.usd, 6),
            **self.usage.to_dict(),
        }


def estimate_cost_usd(
    models: ModelsConfig,
    model_id: str,
    usage: Usage,
    *,
    batch: bool = False,
) -> float:
    """Costo en USD de `usage` para `model_id`.

    Los tokens de escritura y de lectura de caché se cobran sobre la tarifa de entrada,
    con los multiplicadores declarados en `configs/models.yaml`. El descuento de Batch API
    se aplica al total.
    """
    price = models.price(model_id)
    mult = models.pricing_multipliers

    usd = (
        usage.input_tokens * price.input_per_mtok
        + usage.cache_creation_tokens * price.input_per_mtok * mult.cache_write
        + usage.cache_read_tokens * price.input_per_mtok * mult.cache_read
        + usage.output_tokens * price.output_per_mtok
    ) / _MTOK

    if batch:
        usd *= mult.batch
    return usd


def make_estimate(
    models: ModelsConfig,
    *,
    concepto: str,
    model_id: str,
    n_llamadas: int,
    usage_por_llamada: Usage,
    batch: bool = False,
) -> CostEstimate:
    """Escala el uso de una llamada por `n_llamadas` y calcula su costo."""
    total = Usage(
        input_tokens=usage_por_llamada.input_tokens * n_llamadas,
        output_tokens=usage_por_llamada.output_tokens * n_llamadas,
        cache_creation_tokens=usage_por_llamada.cache_creation_tokens * n_llamadas,
        cache_read_tokens=usage_por_llamada.cache_read_tokens * n_llamadas,
    )
    return CostEstimate(
        concepto=concepto,
        model=model_id,
        n_llamadas=n_llamadas,
        usage=total,
        batch=batch,
        usd=estimate_cost_usd(models, model_id, total, batch=batch),
    )


@dataclass
class DryRunReport:
    """Acumula estimaciones y las imprime como tabla."""

    titulo: str
    items: list[CostEstimate] = field(default_factory=list)
    notas: list[str] = field(default_factory=list)

    def add(self, item: CostEstimate) -> None:
        self.items.append(item)

    @property
    def total_usd(self) -> float:
        return sum(item.usd for item in self.items)

    @property
    def total_usage(self) -> Usage:
        """La suma del uso de tokens de todos los ítems estimados."""
        total = Usage()
        for item in self.items:
            total = total + item.usage
        return total

    def to_dict(self) -> dict[str, Any]:
        return {
            "titulo": self.titulo,
            "items": [item.to_dict() for item in self.items],
            "total_usd": round(self.total_usd, 4),
            "total_tokens": self.total_usage.to_dict(),
            "notas": list(self.notas),
        }

    def __str__(self) -> str:
        return format_dry_run_report(self)


def _miles(valor: int) -> str:
    """Separador de miles con punto, como se usa en español de Chile."""
    return f"{valor:,}".replace(",", ".")


def _tokens_entrada(usage: Usage) -> int:
    """Tokens que se facturan como entrada, incluida la caché."""
    return usage.input_tokens + usage.cache_creation_tokens + usage.cache_read_tokens


def format_dry_run_report(report: DryRunReport) -> str:
    """Tabla de texto plano con el costo estimado, para imprimir en `--dry-run`."""
    encabezados = ("Concepto", "Modelo", "Llamadas", "Tok. entrada", "Tok. salida", "Modo", "USD")
    filas = [
        (
            item.concepto,
            item.model,
            _miles(item.n_llamadas),
            _miles(_tokens_entrada(item.usage)),
            _miles(item.usage.output_tokens),
            "batch" if item.batch else "tiempo real",
            f"{item.usd:,.4f}".replace(",", "."),
        )
        for item in report.items
    ]
    anchos = [
        max(len(encabezados[i]), *(len(fila[i]) for fila in filas))
        if filas
        else len(encabezados[i])
        for i in range(len(encabezados))
    ]

    def _linea(valores: tuple[str, ...]) -> str:
        return "  ".join(valor.ljust(anchos[i]) for i, valor in enumerate(valores)).rstrip()

    partes = [
        f"[--dry-run] {report.titulo}",
        "",
        _linea(encabezados),
        "  ".join("-" * ancho for ancho in anchos),
    ]
    partes.extend(_linea(fila) for fila in filas)
    total = report.total_usage
    partes.extend(
        [
            "",
            f"Total llamadas: {sum(i.n_llamadas for i in report.items)}",
            (
                f"Total tokens: entrada {_miles(_tokens_entrada(total))} "
                f"(caché: escritura {_miles(total.cache_creation_tokens)}, "
                f"lectura {_miles(total.cache_read_tokens)}) / "
                f"salida {_miles(total.output_tokens)}"
            ),
            f"Costo estimado: USD {report.total_usd:,.4f}".replace(",", "."),
            "",
            "Estimación, no factura: los tokens de salida son una cota superior por `max_tokens`",
            "y el ahorro real de caché depende de los aciertos.",
        ]
    )
    partes.extend(f"Nota: {nota}" for nota in report.notas)
    return "\n".join(partes)


__all__ = [
    "CostEstimate",
    "DryRunReport",
    "Usage",
    "estimate_cost_usd",
    "format_dry_run_report",
    "make_estimate",
]
