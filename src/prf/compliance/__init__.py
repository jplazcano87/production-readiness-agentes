"""Checklist de cumplimiento ejecutable y sus verificadores (etapa 6).

El checklist traduce la Ley N° 21.719 y la circular SERNAC (2022) a ítems que una función
puede comprobar sobre evidencia concreta: la respuesta del agente, los artefactos que el
marco persiste o la declaración de despliegue. Lo que no es comprobable no está en el
checklist.
"""

from prf.compliance.checklist import (
    Item,
    cargar_checklist,
    cargar_despliegue,
    redactar_pii,
)
from prf.compliance.verifiers import REGISTRO, Contexto, Resultado

__all__ = [
    "Contexto",
    "Item",
    "REGISTRO",
    "Resultado",
    "cargar_checklist",
    "cargar_despliegue",
    "redactar_pii",
]
