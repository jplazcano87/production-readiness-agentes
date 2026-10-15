"""Modelos de datos del sandbox.

`Product` y `Review` son el contenido del corpus congelado (etapa 2). `Origen` y
`ToolCall` son el registro de ejecución: qué se llamó, con qué argumentos y **de dónde
salieron esos argumentos**, que es lo que permite distinguir un flujo legítimo de uno
secuestrado por texto recuperado.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Origen(StrEnum):
    """Procedencia de un valor que entra al agente.

    La distinción operativa es de confianza, no de formato: `USUARIO` y `CATALOGO` son
    datos que el sistema controla; `RESENA` es texto que un tercero pudo escribir y por
    tanto es una superficie de inyección indirecta.
    """

    USUARIO = "usuario"
    CATALOGO = "catalogo"
    RESENA = "resena"  # reseñas y descripciones comerciales: texto escrito por terceros

    @property
    def es_confiable(self) -> bool:
        """`trusted` en la terminología de CaMeL; las reseñas nunca lo son."""
        return self is not Origen.RESENA


class Product(BaseModel):
    """Producto del catálogo sintético."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    category: str
    brand: str
    price_clp: int = Field(ge=0)
    attributes: dict[str, Any] = Field(default_factory=dict)
    stock: int = Field(ge=0)
    avg_rating: float = Field(ge=0.0, le=5.0)
    # La descripción comercial la redacta el LLM (etapa 2) y es, junto con las reseñas,
    # una de las dos superficies de inyección indirecta: es texto que el agente recupera,
    # no texto que el usuario escribió. Por eso su procedencia es `Origen.RESENA`.
    description: str = ""

    def resumen(self) -> str:
        """Una línea legible, para el bloque de catálogo del system prompt."""
        return (
            f"{self.id} | {self.name} | {self.brand} | {self.category} | "
            f"${self.price_clp:,} CLP".replace(",", ".")
            + f" | stock: {self.stock} | evaluación: {self.avg_rating:.1f}"
        )


class Review(BaseModel):
    """Reseña de un producto.

    `is_adversarial` y `attack_id` marcan las reseñas que llevan carga de inyección
    indirecta. El agente nunca ve estos campos: son anotación del corpus para evaluar,
    no contenido que se le entregue.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    product_id: str
    rating: int = Field(ge=1, le=5)
    text: str
    is_adversarial: bool = False
    attack_id: str | None = None


class ToolCall(BaseModel):
    """Una invocación de herramienta, con la procedencia de cada argumento."""

    model_config = ConfigDict(extra="forbid")

    nombre: str
    argumentos: dict[str, Any] = Field(default_factory=dict)
    origen_argumentos: dict[str, Origen] = Field(default_factory=dict)
    turno: int = 0
    bloqueada: bool = False
    motivo_bloqueo: str | None = None
    # Mensaje de error si la herramienta se invocó pero falló. Una llamada con error no
    # produjo su efecto, así que no puede contar como una comparación entregada ni como el
    # uso efectivo de una herramienta prohibida.
    error: str | None = None
    # Lo que la herramienta devolvió, tal cual, para poder contrastar después lo que el
    # agente afirmó contra lo que el entorno respondió (la
    # respuesta de `ROB-BUS-007` decía que no había productos y la búsqueda devolvió cinco).
    # Es solo registro: **no se le envía al modelo**, que sigue recibiendo exactamente el
    # mismo bloque de resultado que antes.
    resultado: Any = None

    @property
    def exitosa(self) -> bool:
        return not self.bloqueada and self.error is None

    @property
    def origenes(self) -> set[Origen]:
        return set(self.origen_argumentos.values())

    @property
    def tiene_argumentos_no_confiables(self) -> bool:
        """¿Algún argumento vino de una reseña o descripción?

        Es la condición que el intérprete Code-Then-Execute (etapa 4) usa para bloquear
        un paso: un valor no confiable nunca puede llegar a ser argumento de herramienta.
        """
        return any(not origen.es_confiable for origen in self.origen_argumentos.values())


__all__ = ["Origen", "Product", "Review", "ToolCall"]
