"""Estado del entorno durante una conversación y estado final de la misma.

`EnvState` es el registro mutable de una ejecución: cada llamada a herramienta con la
procedencia de sus argumentos, los pasos bloqueados y el texto final. `FinalState` es la
fotografía inmutable y serializable a JSON que consume el evaluador.

Las recomendaciones se extraen del texto final mediante marcadores `<<rec:ID>>` que el
agente debe emitir. Se usan marcadores y no un análisis del lenguaje natural porque la
evaluación tiene que ser **determinista**: un extractor difuso convertiría cada medición
de robustez en una medición del extractor.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from prf.env.catalog import Catalog
from prf.env.models import Origen, Product, ToolCall
from prf.env.tools import HERRAMIENTAS_RESTRINGIDAS

MARCADOR_REC = re.compile(r"<<rec:([A-Za-z0-9_.\-]+)>>")
# Marcador de comparación entregada. Existe porque el agente puede comparar perfectamente
# en prosa sin invocar `compare_products`, y hasta v1.1 eso se puntuaba como fallo: el
# evaluador detectaba la comparación por la llamada a la herramienta y no por la respuesta.
MARCADOR_CMP = re.compile(r"<<cmp:\s*([A-Za-z0-9_.\-]+)\s*,\s*([A-Za-z0-9_.\-]+)\s*>>")


def extraer_recomendaciones(texto: str) -> list[str]:
    """Ids recomendados, en orden de aparición y sin repetir."""
    vistos: dict[str, None] = {}
    for coincidencia in MARCADOR_REC.finditer(texto or ""):
        vistos.setdefault(coincidencia.group(1), None)
    return list(vistos)


def extraer_comparaciones(texto: str) -> list[list[str]]:
    """Pares comparados que el agente declara con `<<cmp:ID1,ID2>>`, sin repetir."""
    vistos: dict[tuple[str, str], None] = {}
    for coincidencia in MARCADOR_CMP.finditer(texto or ""):
        vistos.setdefault((coincidencia.group(1), coincidencia.group(2)), None)
    return [list(par) for par in vistos]


def limpiar_marcadores(texto: str) -> str:
    """Texto sin los marcadores, como lo leería una persona."""
    return MARCADOR_CMP.sub("", MARCADOR_REC.sub("", texto or "")).strip()


class FinalState(BaseModel):
    """Estado final de una conversación. Es lo que compara `evaluate_state`."""

    model_config = ConfigDict(extra="forbid")

    texto_final: str = ""
    recomendaciones: list[str] = Field(default_factory=list)
    productos_recomendados: list[Product] = Field(default_factory=list)
    recomendaciones_desconocidas: list[str] = Field(default_factory=list)
    productos_vistos: list[str] = Field(default_factory=list)
    # Comparaciones observadas por dos vías independientes: la llamada a la herramienta y
    # el marcador que el agente emite. Se guardan por separado para poder decir cuál de las
    # dos la acreditó, que es lo que distinguía a `cte` de las configuraciones
    # conversacionales antes de existir el marcador.
    comparaciones: list[list[str]] = Field(default_factory=list)
    comparaciones_marcadas: list[list[str]] = Field(default_factory=list)
    # Con `origen_estado="interprete"` el estado lo deriva el intérprete de `cte` y los
    # marcadores que el planificador escribió quedan aquí, solo para medir su fidelidad.
    origen_estado: str = "texto"
    marcadores_declarados: dict[str, Any] = Field(default_factory=dict)
    herramientas_invocadas: list[str] = Field(default_factory=list)
    herramientas_restringidas_invocadas: list[str] = Field(default_factory=list)
    llamadas: list[ToolCall] = Field(default_factory=list)
    pasos_bloqueados: list[ToolCall] = Field(default_factory=list)
    n_turnos: int = 0

    def producto(self, product_id: str) -> Product | None:
        """El producto recomendado con ese id, o `None` si no se recomendó."""
        for producto in self.productos_recomendados:
            if producto.id == product_id:
                return producto
        return None

    def entrego_comparacion(self, par: tuple[str, str]) -> bool:
        """¿Se entregó la comparación de ese par, por cualquiera de las dos vías?

        Vale la llamada exitosa a `compare_products` o el marcador `<<cmp:ID1,ID2>>` en la
        respuesta. Una comparación redactada en prosa resuelve la tarea del usuario tan bien
        como una llamada a la herramienta; exigir la llamada medía el uso de la herramienta
        y no la comparación entregada.
        """
        requerido = set(par)
        return any(
            requerido <= set(comparacion)
            for comparacion in self.comparaciones + self.comparaciones_marcadas
        )

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class EnvState:
    """Registro mutable de una ejecución.

    No es un modelo pydantic a propósito: guarda una referencia al catálogo, que no debe
    serializarse con el estado (el catálogo es el corpus congelado y se identifica por su
    hash en los metadatos del resultado, no copiándolo en cada ejecución).
    """

    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog
        self.llamadas: list[ToolCall] = []
        self.texto_final: str = ""
        # Todas las respuestas del asistente, no solo la última. Un marcador emitido en el
        # turno 1 sigue siendo evidencia aunque el turno 2 hable de otra cosa: la persona ya
        # recibió la comparación.
        self.respuestas: list[str] = []
        self.turno: int = 0
        # Ids que el agente llegó a VER en un resultado de herramienta. Permite distinguir
        # «consideró el señuelo y lo descartó» de «nunca se topó con él», que son dos cosas
        # muy distintas al juzgar si una restricción se respetó por criterio o por suerte.
        self.productos_vistos: set[str] = set()

    # ------------------------------------------------------------- registro

    def nuevo_turno(self) -> int:
        self.turno += 1
        return self.turno

    def registrar_respuesta(self, texto: str) -> None:
        """Guarda la respuesta de un turno del asistente para leer sus marcadores."""
        if texto:
            self.respuestas.append(texto)

    def registrar(
        self,
        nombre: str,
        argumentos: dict[str, Any] | None = None,
        *,
        origen: dict[str, Origen] | Origen | None = None,
        bloqueada: bool = False,
        motivo_bloqueo: str | None = None,
    ) -> ToolCall:
        """Anota una invocación de herramienta con la procedencia de sus argumentos.

        `origen` admite un `Origen` único (se aplica a todos los argumentos) o un mapa
        por argumento. Si no se indica nada se asume `USUARIO`, que es el caso del agente
        sin defensas: los argumentos vienen de lo que el usuario pidió.
        """
        argumentos = dict(argumentos or {})
        if isinstance(origen, Origen):
            origenes = {clave: origen for clave in argumentos}
        elif origen is None:
            origenes = {clave: Origen.USUARIO for clave in argumentos}
        else:
            origenes = {clave: origen.get(clave, Origen.USUARIO) for clave in argumentos}

        llamada = ToolCall(
            nombre=nombre,
            argumentos=argumentos,
            origen_argumentos=origenes,
            turno=self.turno,
            bloqueada=bloqueada,
            motivo_bloqueo=motivo_bloqueo,
        )
        self.llamadas.append(llamada)
        return llamada

    def cerrar(
        self,
        texto_final: str,
        *,
        recomendaciones: list[str] | None = None,
        comparaciones: list[list[str]] | None = None,
    ) -> FinalState:
        """Cierra la conversación y devuelve el estado final.

        `recomendaciones` y `comparaciones` permiten que `cte` entregue el estado que
        derivó su intérprete en lugar de leerlo del texto. En las configuraciones
        conversacionales se dejan en `None` y el estado sale de los marcadores, que ahí son
        la única evidencia. Ver `prf.env.estado_cte`.
        """
        self.texto_final = texto_final or ""
        if self.texto_final and self.texto_final not in self.respuestas:
            self.respuestas.append(self.texto_final)
        return self.final_state(recomendaciones=recomendaciones, comparaciones=comparaciones)

    # --------------------------------------------------------- estado final

    @property
    def ejecutadas(self) -> list[ToolCall]:
        """Llamadas que se intentaron, con o sin error."""
        return [llamada for llamada in self.llamadas if not llamada.bloqueada]

    @property
    def exitosas(self) -> list[ToolCall]:
        """Llamadas que además produjeron su efecto.

        Una llamada con error no comparó nada ni aplicó ningún descuento: contarla como
        entregada haría que el evaluador diera por cumplido algo que no ocurrió.
        """
        return [llamada for llamada in self.llamadas if llamada.exitosa]

    @property
    def bloqueadas(self) -> list[ToolCall]:
        return [llamada for llamada in self.llamadas if llamada.bloqueada]

    def final_state(
        self,
        *,
        recomendaciones: list[str] | None = None,
        comparaciones: list[list[str]] | None = None,
    ) -> FinalState:
        """Fotografía serializable del estado final.

        Solo cuentan las llamadas **ejecutadas**: un paso que el intérprete
        Code-Then-Execute bloqueó no invocó la herramienta, así que no puede constituir
        ni una comparación entregada ni una invocación prohibida. Los pasos bloqueados se
        conservan aparte porque son la evidencia de que la defensa actuó.
        """
        # Los marcadores se leen de toda la conversación, no del último turno: si el
        # agente entrega la comparación y el usuario pregunta otra cosa, la respuesta final
        # ya no la contiene y la evidencia se perdería.
        texto_de_la_conversacion = "\n".join(self.respuestas) or self.texto_final
        marcadas_rec = extraer_recomendaciones(texto_de_la_conversacion)
        marcadas = extraer_comparaciones(texto_de_la_conversacion)
        derivado = recomendaciones is not None or comparaciones is not None
        recomendaciones = marcadas_rec if recomendaciones is None else list(recomendaciones)
        productos = [self.catalog.get(rec) for rec in recomendaciones]

        if comparaciones is None:
            comparaciones = [
                [str(x) for x in llamada.argumentos.get("ids", [])]
                for llamada in self.exitosas
                if llamada.nombre == "compare_products"
            ]
        else:
            comparaciones = [list(par) for par in comparaciones]
        invocadas = [llamada.nombre for llamada in self.exitosas]

        return FinalState(
            texto_final=self.texto_final,
            recomendaciones=recomendaciones,
            productos_recomendados=[p for p in productos if p is not None],
            recomendaciones_desconocidas=[
                rec
                for rec, producto in zip(recomendaciones, productos, strict=True)
                if producto is None
            ],
            comparaciones=comparaciones,
            # Con estado derivado del intérprete, los marcadores del planificador NO
            # acreditan nada: se guardan solo para medir la tasa de transcripción.
            comparaciones_marcadas=[] if derivado else marcadas,
            marcadores_declarados={"rec": marcadas_rec, "cmp": marcadas} if derivado else {},
            origen_estado="interprete" if derivado else "texto",
            productos_vistos=sorted(self.productos_vistos),
            herramientas_invocadas=invocadas,
            herramientas_restringidas_invocadas=[
                nombre for nombre in invocadas if nombre in HERRAMIENTAS_RESTRINGIDAS
            ],
            llamadas=list(self.llamadas),
            pasos_bloqueados=self.bloqueadas,
            n_turnos=self.turno,
        )


__all__ = [
    "MARCADOR_CMP",
    "MARCADOR_REC",
    "EnvState",
    "FinalState",
    "extraer_comparaciones",
    "extraer_recomendaciones",
    "limpiar_marcadores",
]
