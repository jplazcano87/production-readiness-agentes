"""Carga del checklist y redacción de datos personales en lo que se persiste."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from prf.compliance.verifiers import REGISTRO
from prf.infra import paths

RUTA_CHECKLIST = Path(__file__).with_name("checklist.yaml")
EVIDENCIAS = ("respuesta", "log", "configuracion")
CRITICIDADES = ("critico", "no_critico")


@dataclass(frozen=True)
class Item:
    """Un ítem del checklist."""

    id: str
    fuente: str
    criterio: str
    evidencia: str
    criticidad: str
    tolerancia_cero: bool
    verificador: str
    casos: tuple[str, ...]

    @property
    def implementado(self) -> bool:
        return self.verificador in REGISTRO

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "fuente": self.fuente,
            "criterio": " ".join(self.criterio.split()),
            "evidencia": self.evidencia,
            "criticidad": self.criticidad,
            "tolerancia_cero": self.tolerancia_cero,
            "verificador": self.verificador,
            "verificador_implementado": self.implementado,
            "casos": list(self.casos),
        }


def cargar_checklist(ruta: Path | None = None) -> tuple[str, list[Item]]:
    """Lee el checklist y valida que cada ítem sea ejecutable.

    Falla si un ítem declara un verificador que no existe: un checklist con ítems que nadie
    puede comprobar produce la apariencia de cumplimiento, que es peor que no tenerlo.
    """
    datos = yaml.safe_load((ruta or RUTA_CHECKLIST).read_text(encoding="utf-8"))
    items: list[Item] = []
    vistos: set[str] = set()
    for bruto in datos["items"]:
        item = Item(
            id=bruto["id"],
            fuente=bruto["fuente"],
            criterio=bruto["criterio"],
            evidencia=bruto["evidencia"],
            criticidad=bruto["criticidad"],
            tolerancia_cero=bool(bruto["tolerancia_cero"]),
            verificador=bruto["verificador"],
            casos=tuple(bruto.get("casos") or ()),
        )
        if item.id in vistos:
            raise ValueError(f"id de ítem repetido: {item.id}")
        if item.evidencia not in EVIDENCIAS:
            raise ValueError(f"{item.id}: evidencia desconocida {item.evidencia!r}")
        if item.criticidad not in CRITICIDADES:
            raise ValueError(f"{item.id}: criticidad desconocida {item.criticidad!r}")
        if not item.implementado:
            raise ValueError(f"{item.id}: verificador no implementado ({item.verificador})")
        vistos.add(item.id)
        items.append(item)
    return datos["version"], items


def cargar_despliegue(ruta: Path | None = None) -> dict[str, Any]:
    """Declaración de despliegue: la evidencia de tipo `configuracion`."""
    destino = ruta or paths.configs / "despliegue.yaml"
    return yaml.safe_load(destino.read_text(encoding="utf-8"))


# ------------------------------------------------------------ redacción de datos

ETIQUETAS = {
    "rut": "[RUT_REDACTADO]",
    "correo": "[CORREO_REDACTADO]",
    "telefono": "[TELEFONO_REDACTADO]",
    "nombre": "[NOMBRE_REDACTADO]",
}


def formas_de(valor: str, clave: str = "") -> list[str]:
    """El mismo dato escrito como suele aparecer.

    Un RUT se escribe con puntos o sin ellos; un nombre completo se abrevia al de pila en
    cuanto el agente saluda («Hola Valentina»). Buscar solo la cadena completa dejaba pasar
    esa forma, que es un dato personal igual, y la dejaba en claro en los artefactos.
    """
    formas = {valor, valor.replace(".", ""), valor.replace(".", "").replace("-", "")}
    if clave == "nombre":
        formas |= {parte for parte in valor.split() if len(parte) >= 4}
    return sorted((f for f in formas if len(f) >= 4), key=len, reverse=True)


def redactar_pii(dato: Any, pii: dict[str, str]) -> Any:
    """Sustituye los datos personales del caso por su etiqueta, recorriendo la estructura.

    Se aplica **antes** de escribir cualquier artefacto. El ítem `PII_NO_PERSISTE_EN_CLARO`
    comprueba luego el archivo escrito: es este control el que se está poniendo a prueba, y
    por eso la comprobación se hace sobre el resultado y no sobre la intención.

    Cada valor se busca en todas sus formas (`formas_de`), incluido el nombre de pila.
    """
    if not pii:
        return dato
    if isinstance(dato, str):
        salida = dato
        for clave, valor in pii.items():
            if not valor:
                continue
            etiqueta = ETIQUETAS.get(clave, f"[{clave.upper()}_REDACTADO]")
            for forma in formas_de(valor, clave):
                salida = re.sub(re.escape(forma), etiqueta, salida, flags=re.IGNORECASE)
        return salida
    if isinstance(dato, dict):
        return {k: redactar_pii(v, pii) for k, v in dato.items()}
    if isinstance(dato, list):
        return [redactar_pii(v, pii) for v in dato]
    return dato


__all__ = [
    "CRITICIDADES",
    "EVIDENCIAS",
    "Item",
    "RUTA_CHECKLIST",
    "cargar_checklist",
    "cargar_despliegue",
    "formas_de",
    "redactar_pii",
]
