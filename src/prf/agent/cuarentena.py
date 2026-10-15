"""Modelo en cuarentena: convierte texto no confiable en un objeto de esquema fijo.

Es la pieza central de `dual_llm` y también la usa `cte`. La idea (Willison, 2023) es que
el modelo privilegiado —el que puede invocar herramientas— nunca vea el texto que escribió
un tercero. Ve solo un objeto con campos declarados, tipos declarados y longitudes acotadas.

Tres capas de defensa, en este orden:

1. **El esquema.** Un `float`, dos listas de a lo más cinco frases de a lo más seis
   palabras y un `bool`. Una instrucción inyectada no cabe en esa forma.
2. **El filtro de marcadores.** Aunque quepa, se descarta cualquier resumen que contenga
   códigos, correos, URLs, RUT o identificadores de producto: son el vehículo típico de la
   exfiltración, y ninguno tiene por qué aparecer en un resumen de opiniones.
3. **El descarte.** Si algo no valida, no se intenta reparar: se devuelve
   `{"error": "resumen no disponible"}`. Reparar una salida sospechosa es exactamente lo
   que un atacante querría que hiciéramos.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from prf.agent.prompts import SISTEMA_CUARENTENA
from prf.env.models import Review
from prf.infra.client import AnthropicClient

MAX_FRASES = 5
MAX_PALABRAS = 6
RESUMEN_NO_DISPONIBLE: dict[str, str] = {"error": "resumen no disponible"}

# Patrones que no tienen ninguna razón de estar en un resumen de opiniones y que sí son el
# vehículo habitual de una exfiltración.
MARCADORES_SOSPECHOSOS = (
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),  # correo
    re.compile(r"https?://|www\."),  # URL
    re.compile(r"\b[A-Z]{2,}[-_][A-Z0-9]{2,}"),  # códigos tipo PRF-XXX
    re.compile(r"\b\d{1,2}\.\d{3}\.\d{3}-[\dkK]\b"),  # RUT
    re.compile(r"\bP\d{4}\b"),  # id de producto
    re.compile(r"<<rec:"),  # marcador de recomendación
)


def contiene_marcador_sospechoso(texto: str) -> bool:
    return any(patron.search(texto) for patron in MARCADORES_SOSPECHOSOS)


class ResumenResenas(BaseModel):
    """Lo único que el modelo privilegiado llega a ver de las reseñas."""

    model_config = ConfigDict(extra="forbid")

    rating_promedio: float = Field(ge=1.0, le=5.0)
    pros: list[str] = Field(default_factory=list, max_length=MAX_FRASES)
    contras: list[str] = Field(default_factory=list, max_length=MAX_FRASES)
    menciona_defectos: bool

    @field_validator("pros", "contras")
    @classmethod
    def _frases_cortas_y_limpias(cls, valor: list[str]) -> list[str]:
        for frase in valor:
            palabras = frase.split()
            if not palabras:
                raise ValueError("frase vacía")
            if len(palabras) > MAX_PALABRAS:
                raise ValueError(
                    f"«{frase}» tiene {len(palabras)} palabras, el máximo es {MAX_PALABRAS}"
                )
            if contiene_marcador_sospechoso(frase):
                raise ValueError(f"«{frase}» contiene un marcador que no corresponde a un resumen")
        return valor

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _extraer_json(texto: str) -> Any:
    limpio = re.sub(r"^```(?:json)?\s*", "", texto.strip())
    limpio = re.sub(r"\s*```$", "", limpio)
    try:
        return json.loads(limpio)
    except json.JSONDecodeError:
        inicio, fin = limpio.find("{"), limpio.rfind("}")
        if inicio != -1 and fin > inicio:
            return json.loads(limpio[inicio : fin + 1])
        raise


def _prompt(resenas: list[Review]) -> str:
    cuerpo = "\n\n".join(f"[reseña {i}] {r.text}" for i, r in enumerate(resenas, start=1))
    return f"Resume estas {len(resenas)} reseñas:\n\n{cuerpo}"


class Cuarentena:
    """Envoltorio del modelo en cuarentena, con su contabilidad."""

    def __init__(self, client: AnthropicClient, *, role: str = "quarantine") -> None:
        self.client = client
        self.role = role
        self.n_llamadas = 0
        self.n_descartes = 0
        self.motivos_descarte: list[str] = []

    def resumir(self, resenas: list[Review]) -> dict[str, Any]:
        """Devuelve el resumen validado, o `{"error": "resumen no disponible"}`.

        No reintenta: una salida que no valida es, en el peor caso, el resultado de una
        inyección que logró desviar al modelo en cuarentena. Volver a pedírsela con el
        mismo texto solo le daría otra oportunidad al atacante.
        """
        if not resenas:
            return ResumenResenas(
                rating_promedio=3.0, pros=[], contras=[], menciona_defectos=False
            ).to_dict()

        self.n_llamadas += 1
        respuesta = self.client.create(
            self.role,
            [{"role": "user", "content": _prompt(resenas)}],
            system=SISTEMA_CUARENTENA,
            max_tokens=400,
        )
        return self.validar(respuesta.text)

    def validar(self, texto: str) -> dict[str, Any]:
        """Valida la salida del modelo en cuarentena. Separado para poder probarlo sin red."""
        try:
            datos = _extraer_json(texto)
            return ResumenResenas.model_validate(datos).to_dict()
        except (json.JSONDecodeError, ValidationError, TypeError, AttributeError) as exc:
            self.n_descartes += 1
            self.motivos_descarte.append(f"{type(exc).__name__}: {str(exc)[:160]}")
            return dict(RESUMEN_NO_DISPONIBLE)

    def resumen_uso(self) -> dict[str, Any]:
        return {
            "n_llamadas": self.n_llamadas,
            "n_descartes": self.n_descartes,
            "motivos_descarte": list(self.motivos_descarte),
        }


def sanear_producto(producto: dict[str, Any]) -> dict[str, Any]:
    """Quita la descripción comercial de la ficha de un producto.

    La descripción es texto que un tercero escribió, igual que una reseña, y por tanto una
    superficie de inyección indirecta. En `dual_llm` y `cte` el modelo privilegiado no la
    ve. Que eso le reste utilidad es precisamente lo que el experimento mide.
    """
    return {clave: valor for clave, valor in producto.items() if clave != "description"}


def sanear_resultado(resultado: Any) -> Any:
    """Aplica `sanear_producto` a un resultado de herramienta, sea lista o dict."""
    if isinstance(resultado, list):
        return [sanear_resultado(elemento) for elemento in resultado]
    if isinstance(resultado, dict):
        if "description" in resultado:
            return sanear_producto(resultado)
        return {clave: sanear_resultado(valor) for clave, valor in resultado.items()}
    return resultado


__all__ = [
    "MARCADORES_SOSPECHOSOS",
    "MAX_FRASES",
    "MAX_PALABRAS",
    "RESUMEN_NO_DISPONIBLE",
    "Cuarentena",
    "ResumenResenas",
    "contiene_marcador_sospechoso",
    "sanear_producto",
    "sanear_resultado",
]
