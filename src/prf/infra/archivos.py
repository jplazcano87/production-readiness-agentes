"""Lecturas de archivo que varios scripts necesitan igual.

Dos operaciones que estaban escritas tres y cuatro veces, con diferencias que no eran
decisiones sino accidentes: una versión del lector de JSONL descartaba las líneas en blanco y
otra no, y una de las funciones de huella leía el archivo entero en memoria mientras otra lo
hacía por bloques. Tenerlas en un sitio evita que la próxima copia elija al azar.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

BLOQUE = 1 << 20


def sha256_de(ruta: Path | str) -> str:
    """SHA-256 de un archivo, leído por bloques.

    Por bloques y no de una vez porque algunas transcripciones y resultados pesan megabytes y
    no hay razón para cargarlos enteros solo para resumirlos.
    """
    h = hashlib.sha256()
    with Path(ruta).open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(BLOQUE), b""):
            h.update(bloque)
    return h.hexdigest()


def leer_jsonl(ruta: Path | str) -> list[dict[str, Any]]:
    """Las líneas de un `.jsonl` como diccionarios, saltando las vacías.

    Saltar las vacías no es cosmético: un archivo que termina en salto de línea produce una
    última línea vacía, y según quién lo lea eso era un caso de más o un error de análisis.
    """
    texto = Path(ruta).read_text(encoding="utf-8")
    return [json.loads(linea) for linea in texto.splitlines() if linea.strip()]


__all__ = ["leer_jsonl", "sha256_de"]
