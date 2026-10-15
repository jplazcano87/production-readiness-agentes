"""Conteo de tokens.

Dos modos, y el que se use queda declarado en cada resultado:

- `count_tokens_api`: conteo exacto con `client.messages.count_tokens` del SDK. Requiere red.
- `approx_tokens`: aproximación local, sin red, para `--dry-run` y para las estadísticas
  del corpus (tabla 3 del informe). Heurística declarada: `ceil(len(texto) / 3.6)`
  caracteres por token, calibrada para español; se documenta como aproximación en el
  informe y nunca se presenta como conteo exacto.
"""

from __future__ import annotations

import math
from typing import Any

CHARS_POR_TOKEN_ES = 3.6
METODO_APROXIMADO = f"aproximacion_local_{CHARS_POR_TOKEN_ES}_chars_por_token"


def approx_tokens(texto: str) -> int:
    """Aproxima el número de tokens de un texto en español, sin llamar a la API."""
    if not texto:
        return 0
    return max(1, math.ceil(len(texto) / CHARS_POR_TOKEN_ES))


def approx_tokens_messages(messages: list[dict[str, Any]], system: Any = None) -> int:
    """Aproxima los tokens de entrada de una petición completa (system + mensajes)."""
    total = 0
    for bloque in _iter_textos(system):
        total += approx_tokens(bloque)
    for mensaje in messages:
        for bloque in _iter_textos(mensaje.get("content")):
            total += approx_tokens(bloque)
        total += 4  # sobrecarga aproximada por turno
    return total


def _iter_textos(contenido: Any):
    """Recorre texto plano dentro de la estructura de contenido de la API."""
    if contenido is None:
        return
    if isinstance(contenido, str):
        yield contenido
    elif isinstance(contenido, dict):
        if isinstance(contenido.get("text"), str):
            yield contenido["text"]
        elif isinstance(contenido.get("content"), (list, str, dict)):
            yield from _iter_textos(contenido["content"])
    elif isinstance(contenido, list):
        for elemento in contenido:
            yield from _iter_textos(elemento)


__all__ = ["CHARS_POR_TOKEN_ES", "METODO_APROXIMADO", "approx_tokens", "approx_tokens_messages"]
