"""Las reglas de `configs/thresholds.yaml`, como objetos que se pueden evaluar y citar.

Una regla no es solo un número: es un `id` estable, una ruta al valor dentro del JSON del
experimento que la alimenta (`campo`), un comparador y un límite. El veredicto tiene que poder
decir **cuál** falla, con qué valor y contra qué límite, y no solo que una dimensión reprueba
con su valor observado, el comparador y el límite.

Ninguna regla se escribe aquí. Todas se leen del YAML, que es la política versionada; este
módulo solo sabe cómo aplicarlas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from prf.infra.config import load_thresholds

# Dimensiones cuyo incumplimiento es «no conformidad crítica» y cortocircuita el veredicto.
CRITICAS = ("seguridad", "cumplimiento")


@dataclass(frozen=True)
class Regla:
    """Una condición de la política, con todo lo necesario para citarla.

    `vincula` lo declara el YAML regla a regla desde los umbrales v0.3.0. Antes vinculaba o no
    una dimensión entera, y eso obligaba a dejar fuera del veredicto el sobrecosto de latencia
    solo porque el TTFT absoluto no podía vincular: dos cosas que no miden lo mismo decididas
    por un solo interruptor.

    `por_clave` marca la regla que se aplica a cada entrada de un diccionario —el ASR de cada
    objetivo— en vez de a un escalar. Todas las entradas deben cumplir el tope, y la que falla
    se nombra.
    """

    id: str
    dimension: str
    nombre: str
    comparator: str
    limite: float
    campo: str
    vincula: bool = True
    por_clave: bool = False
    descripcion: str = ""
    fuente: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def cumple(self, valor: float) -> bool:
        return valor <= self.limite if self.comparator == "<=" else valor >= self.limite

    def enunciado(self) -> str:
        return f"{self.campo} {self.comparator} {self.limite}"


@dataclass
class Evaluacion:
    """El resultado de aplicar una regla a una configuración."""

    regla: Regla
    valor: float | None
    estado: str  # cumple | incumple | no_evaluable
    motivo: str
    ic: dict[str, float] | None = None
    evidencia: list[Any] = field(default_factory=list)
    # Solo en reglas `por_clave`: el detalle de cada entrada, para que el veredicto no reduzca
    # cuatro objetivos a un único número.
    por_clave: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.regla.id,
            "dimension": self.regla.dimension,
            "vincula": self.regla.vincula,
            "descripcion": self.regla.descripcion,
            "campo": self.regla.campo,
            "regla": self.regla.enunciado(),
            "umbral": self.regla.limite,
            "comparador": self.regla.comparator,
            "valor": self.valor,
            "intervalo_95": self.ic,
            "estado": self.estado,
            "motivo": self.motivo,
            "evidencia": self.evidencia,
            **({"por_clave": self.por_clave} if self.por_clave else {}),
        }


def _es_regla(cuerpo: Any) -> bool:
    return isinstance(cuerpo, dict) and bool({"max", "min", "margen"} & set(cuerpo))


class PoliticaIncompleta(ValueError):
    """La política no declara algo que el veredicto necesita para decidir.

    Se levanta en vez de resolverlo por omisión: una regla sin `vincula` decide, o deja de
    decidir, según lo que el motor suponga, y entonces el veredicto lo escribió el código y no
    la política.
    """


def cargar_reglas(umbrales: dict[str, Any] | None = None) -> list[Regla]:
    """Todas las reglas del YAML, en el orden en que están escritas."""
    umbrales = umbrales or load_thresholds()
    salida: list[Regla] = []
    for dimension, bloque in umbrales.items():
        if not isinstance(bloque, dict):
            continue
        for nombre, cuerpo in bloque.items():
            if not _es_regla(cuerpo):
                continue
            if "margen" in cuerpo:
                # `no_degradacion` no tiene un límite absoluto: el límite es el valor de la
                # configuración de referencia menos el margen, y se resuelve al evaluar.
                limite, comparator = float(cuerpo["margen"]), ">="
            else:
                limite = float(cuerpo.get("max", cuerpo.get("min")))
                comparator = cuerpo.get("comparator", "<=" if "max" in cuerpo else ">=")
            if "vincula" not in cuerpo:
                raise PoliticaIncompleta(
                    f"la regla {dimension}.{nombre} no declara `vincula`. Decláralo en "
                    "configs/thresholds.yaml: si una regla no dice si vincula, el veredicto lo "
                    "decide el motor en vez de la política."
                )
            salida.append(
                Regla(
                    id=cuerpo.get("id", f"{dimension}.{nombre}"),
                    dimension=dimension,
                    nombre=nombre,
                    comparator=comparator,
                    limite=limite,
                    campo=cuerpo.get("campo", ""),
                    vincula=cuerpo["vincula"],
                    por_clave=bool(cuerpo.get("por_clave")),
                    descripcion=cuerpo.get("descripcion", ""),
                    fuente=cuerpo.get("fuente", ""),
                    extra={
                        k: v
                        for k, v in cuerpo.items()
                        if k
                        not in {"id", "campo", "descripcion", "fuente", "max", "min", "comparator"}
                    },
                )
            )
    return salida


def leer_campo(documento: dict[str, Any], campo: str, config: str) -> Any:
    """El valor que una regla mira, siguiendo su `campo` dentro del JSON del experimento."""
    valor: Any = documento
    for parte in campo.replace("<config>", config).split("."):
        valor = valor[parte]
    return valor


__all__ = [
    "CRITICAS",
    "Evaluacion",
    "PoliticaIncompleta",
    "Regla",
    "cargar_reglas",
    "leer_campo",
]
