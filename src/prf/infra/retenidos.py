"""Artefactos que no se publican en su forma original, y cómo se leen en su lugar.

El agente, al fabricar canales de contacto que nadie le había dado, escribió un **móvil
chileno con formato válido**. El número es invención del modelo, pero un número inventado
con formato válido puede ser el de una persona real, así que esos archivos no se publican tal
cual: en su lugar va una copia con el sufijo `.redactado.json`, donde los dígitos del número
están reemplazados por un marcador del mismo largo. El original se conserva fuera del
repositorio público y su SHA-256 queda en `docs/MANIFIESTO_ARTEFACTOS.json`, para que la
retención sea auditable y no un recorte silencioso.

Lo que el resto del marco necesita de aquí es poder leer esas transcripciones sin saber cuál
de las dos versiones tiene delante. `publicable()` y `transcripciones()` resuelven eso con una
regla única: **si existe la copia redactada, se usa esa**. El orden importa. Si ganara el
original, el repositorio privado y el público evaluarían archivos distintos y la diferencia no
aparecería hasta que alguien clonara el público.
"""

from __future__ import annotations

import re
from fnmatch import fnmatch
from pathlib import Path

SUFIJO = ".redactado.json"

# Los archivos cuyo original no se publica, con el motivo. Las rutas son relativas a la raíz.
RETENIDOS: dict[str, str] = {
    "results/runs_e4/CUM-025__cte.json": (
        "el agente inventó un móvil chileno con formato válido al fabricar canales de contacto "
        "que nadie le dio; un número inventado puede pertenecer a una persona real"
    ),
    "results/runs_e4_v2.0.0/CUM-025__cte.json": "misma respuesta, corrida del agente 2.0.0",
    "results/e4_compliance_cte_v2.0.0.json": "lleva esa respuesta dentro de su evidencia",
}

# Lo que la redacción dejó escrito. Sirve para comprobar que ningún archivo publicable trae el
# número de vuelta: el marcador sí puede aparecer, los dígitos no.
MARCADOR = "X"
TELEFONO_CHILENO = re.compile(r"\+56[\s-]?9[\s-]?\d{4}[\s-]?\d{4}")


def es_redactado(ruta: Path | str) -> bool:
    return str(ruta).endswith(SUFIJO)


def nombre_original(ruta: Path) -> Path:
    """La ruta que la copia redactada sustituye."""
    return ruta.with_name(ruta.name[: -len(SUFIJO)] + ".json") if es_redactado(ruta) else ruta


def redactada_de(ruta: Path) -> Path:
    return ruta.with_name(ruta.name[: -len(".json")] + SUFIJO)


def publicable(ruta: Path) -> Path:
    """El archivo que hay que leer: la copia redactada si existe, y si no el original.

    La copia gana a propósito. Con el original ganando, este repositorio y el publicado
    puntuarían archivos distintos sin que nadie se enterase.
    """
    copia = redactada_de(ruta)
    return copia if copia.is_file() else ruta


def transcripciones(directorio: Path, patron: str = "*.json") -> list[Path]:
    """Las transcripciones de un directorio, una por ejecución, en orden.

    `patron` se compara contra el nombre **original**, así que `*__cte.json` encuentra también
    la copia redactada de `CUM-025__cte.json`, que es justo lo que hace que la prueba de
    regresión evalúe las mismas 25 ejecuciones en los dos repositorios.
    """
    por_original: dict[str, Path] = {}
    for ruta in sorted(directorio.glob("*.json")):
        original = nombre_original(ruta)
        if not fnmatch(original.name, patron):
            continue
        # La copia redactada gana; si solo está el original, se usa él.
        if es_redactado(ruta) or original.name not in por_original:
            por_original[original.name] = ruta
    return [por_original[n] for n in sorted(por_original)]


__all__ = [
    "MARCADOR",
    "RETENIDOS",
    "SUFIJO",
    "TELEFONO_CHILENO",
    "es_redactado",
    "nombre_original",
    "publicable",
    "redactada_de",
    "transcripciones",
]
