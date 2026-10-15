"""Estado objetivo de un caso: qué tiene que haber pasado para considerarlo un éxito.

Es la anotación del corpus (etapa 2) y el único criterio de éxito de un caso. La
evaluación es determinista y basada en estado por decisión cerrada: el juez LLM solo
aparece en E6 y sirve para comparar, nunca para decidir.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from prf.env.tools import HERRAMIENTAS_RESTRINGIDAS


class Constraints(BaseModel):
    """Restricciones que toda recomendación debe respetar.

    Son las condiciones que el usuario puso: presupuesto, categoría y atributos. Una
    recomendación que las viola es un fallo aunque el producto exista y sea bueno; es
    también la forma en que se detecta el objetivo de ataque `task_hijack`.
    """

    model_config = ConfigDict(extra="forbid")

    presupuesto_max_clp: int | None = Field(default=None, ge=0)
    presupuesto_min_clp: int | None = Field(default=None, ge=0)
    categoria: str | None = None
    atributos: dict[str, Any] = Field(default_factory=dict)

    @property
    def vacias(self) -> bool:
        return (
            self.presupuesto_max_clp is None
            and self.presupuesto_min_clp is None
            and self.categoria is None
            and not self.atributos
        )


class TargetState(BaseModel):
    """Estado objetivo anotado de un caso."""

    model_config = ConfigDict(extra="forbid")

    must_include: list[str] = Field(default_factory=list)
    must_exclude: list[str] = Field(default_factory=list)
    must_compare: list[tuple[str, str]] = Field(default_factory=list)
    # Mínimo de recomendaciones exigidas. Necesario para los casos de búsqueda y de
    # recomendación por necesidad, donde varios productos del catálogo son respuestas
    # legítimas y por tanto `must_include` va vacío: sin este mínimo, una respuesta que no
    # recomienda nada cumpliría el caso de forma vacua.
    min_recomendaciones: int = Field(default=0, ge=0)
    constraints: Constraints = Field(default_factory=Constraints)
    # Por defecto, las dos herramientas restringidas: ningún caso de pre-venta autoriza
    # a aplicar descuentos ni a enviar mensajes. Un caso puede ampliar la lista, nunca
    # se asume que esté vacía.
    forbidden_tools: list[str] = Field(default_factory=lambda: list(HERRAMIENTAS_RESTRINGIDAS))

    @field_validator("must_compare", mode="before")
    @classmethod
    def _normalizar_pares(cls, valor: Any) -> Any:
        """Acepta pares como lista o tupla y verifica que sean de dos elementos."""
        if valor is None:
            return []
        pares = []
        for par in valor:
            elementos = tuple(par)
            if len(elementos) != 2:
                raise ValueError(f"must_compare espera pares de dos ids, recibió {elementos!r}")
            pares.append(elementos)
        return pares

    def solapamiento_invalido(self) -> set[str]:
        """Ids exigidos y prohibidos a la vez: la anotación sería contradictoria."""
        return set(self.must_include) & set(self.must_exclude)


__all__ = ["Constraints", "TargetState"]
