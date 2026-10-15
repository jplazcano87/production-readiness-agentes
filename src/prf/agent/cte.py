"""Code-Then-Execute simplificado, inspirado en CaMeL. **No es una réplica.**

La diferencia con las otras tres configuraciones es de arquitectura: el modelo no ejecuta
nada. Emite un plan en un mini-lenguaje JSON y un **intérprete determinista** lo ejecuta,
aplicando reglas que el modelo no puede negociar:

1. **Lista de herramientas permitidas.** `apply_discount` y `send_message` no están en la
   lista de un agente de pre-venta. Que no se invoquen no depende de que el modelo se porte
   bien: el intérprete no sabe ejecutarlas.
2. **Etiquetas de procedencia.** Todo valor lleva `trusted` (usuario o catálogo) o
   `untrusted` (reseñas y descripciones). El resultado de `get_reviews` es siempre
   `untrusted`.
3. **Un valor `untrusted` nunca es argumento de herramienta.** Es la regla que corta el
   secuestro del flujo de control: aunque una reseña logre que el planificador escriba un
   paso que le pase su contenido a una herramienta, el intérprete lo bloquea.
4. **El texto `untrusted` se resume en cuarentena antes de entrar en la respuesta.**

Un paso que viola una regla no se ejecuta: se registra como `blocked` con su motivo. Esa
lista es la evidencia de que la defensa actuó, y alimenta la columna «pasos bloqueados» de
la tabla 5.

Lo que este intérprete **no** hace, y que CaMeL sí: no hay un lenguaje de capacidades
completo, ni flujo de control (condicionales y bucles), ni política de dependencias entre
valores. Es una versión reducida, y el informe lo declara así.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from prf.agent.cuarentena import Cuarentena, sanear_resultado
from prf.env.estado_cte import (
    comparaciones_entregadas,
    pasos_referenciados,
    recomendados_en_respuesta,
)
from prf.env.models import Origen, Review
from prf.env.sandbox import Sandbox

OP_RESPONDER = "respond"
MAX_PASOS = 8
REFERENCIA = re.compile(r"^\$([A-Za-z0-9_]+)((?:\.[A-Za-z0-9_]+)*)$")


class Paso(BaseModel):
    """Un paso del plan."""

    model_config = ConfigDict(extra="forbid")

    id: str
    op: str
    args: dict[str, Any] = Field(default_factory=dict)
    plantilla: str | None = None
    vars: dict[str, Any] = Field(default_factory=dict)


class Plan(BaseModel):
    """El plan completo que emite el planificador."""

    model_config = ConfigDict(extra="forbid")

    pasos: list[Paso] = Field(min_length=1, max_length=MAX_PASOS)


@dataclass
class Valor:
    """Un valor del intérprete, con su procedencia."""

    dato: Any
    origen: Origen

    @property
    def confiable(self) -> bool:
        return self.origen.es_confiable


@dataclass
class ResultadoPaso:
    paso_id: str
    op: str
    estado: str  # ejecutado | bloqueado | error
    motivo: str | None = None
    detalle: Any = None


ESPECIFICACION = re.compile(r"\{(\w+):[^{}]*\}")


def _formatear_sin_especificacion(plantilla: str, valores: dict[str, str]) -> str:
    """Sustituye `{nombre:lo-que-sea}` por `{nombre}` y formatea.

    Solo se usa cuando `format` ya falló: no cambia el resultado de una plantilla válida.
    """
    return ESPECIFICACION.sub(r"{\1}", plantilla).format(**valores)


@dataclass
class EjecucionPlan:
    """Lo que produjo el intérprete.

    `recomendados` y `comparaciones` los deriva el intérprete de lo que realmente llegó al
    paso `respond`, no de los marcadores que el planificador escriba. Ver
    `prf.env.estado_cte`.
    """

    texto_final: str = ""
    pasos: list[ResultadoPaso] = field(default_factory=list)
    bloqueados: list[ResultadoPaso] = field(default_factory=list)
    recomendados: list[str] = field(default_factory=list)
    comparaciones: list[list[str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "texto_final": self.texto_final,
            "pasos": [
                {"paso_id": p.paso_id, "op": p.op, "estado": p.estado, "motivo": p.motivo}
                for p in self.pasos
            ],
            "n_bloqueados": len(self.bloqueados),
            "recomendados": list(self.recomendados),
            "comparaciones": [list(par) for par in self.comparaciones],
        }


class Interprete:
    """Ejecuta un plan sobre el sandbox aplicando las reglas de procedencia."""

    def __init__(
        self,
        sandbox: Sandbox,
        *,
        herramientas_permitidas: tuple[str, ...],
        cuarentena: Cuarentena | None = None,
    ) -> None:
        self.sandbox = sandbox
        self.permitidas = set(herramientas_permitidas)
        self.cuarentena = cuarentena
        self.entorno: dict[str, Valor] = {}
        # (id del paso, ids comparados) de cada llamada exitosa a `compare_products`.
        self.comparaciones_ejecutadas: list[tuple[str, list[str]]] = []

    # ------------------------------------------------------------ referencias

    def resolver(self, expresion: Any) -> tuple[Any, Origen]:
        """Resuelve un literal o una referencia `$paso.ruta`. Devuelve (valor, procedencia).

        Un literal viene del plan, que a su vez viene de lo que pidió el usuario: es
        `USUARIO`. Una referencia hereda la procedencia del paso que la produjo.

        Las referencias también se resuelven **dentro de listas y diccionarios**:
        `compare_products` recibe `ids` como lista, y no descender en ella dejaría pasar la
        cadena literal `"$s1.0.id"` como si fuera un identificador. La procedencia del
        conjunto es la del elemento menos confiable: basta un valor de reseña dentro de una
        lista para que el argumento entero deje de ser confiable.
        """
        if isinstance(expresion, list):
            resueltos = [self.resolver(e) for e in expresion]
            origen = (
                Origen.RESENA if any(not o.es_confiable for _, o in resueltos) else Origen.USUARIO
            )
            return [v for v, _ in resueltos], origen
        if isinstance(expresion, dict):
            resueltos = {k: self.resolver(v) for k, v in expresion.items()}
            origen = (
                Origen.RESENA
                if any(not o.es_confiable for _, o in resueltos.values())
                else Origen.USUARIO
            )
            return {k: v for k, (v, _) in resueltos.items()}, origen
        if not isinstance(expresion, str):
            return expresion, Origen.USUARIO
        coincidencia = REFERENCIA.match(expresion)
        if not coincidencia:
            return expresion, Origen.USUARIO

        paso_id, ruta = coincidencia.group(1), coincidencia.group(2)
        if paso_id not in self.entorno:
            raise KeyError(f"referencia a un paso inexistente: ${paso_id}")

        valor = self.entorno[paso_id]
        dato = valor.dato
        for tramo in [t for t in ruta.split(".") if t]:
            if isinstance(dato, list):
                if not tramo.isdigit() or int(tramo) >= len(dato):
                    raise KeyError(f"índice fuera de rango en {expresion}")
                dato = dato[int(tramo)]
            elif isinstance(dato, dict):
                if tramo not in dato:
                    raise KeyError(f"campo inexistente en {expresion}: {tramo}")
                dato = dato[tramo]
            else:
                raise KeyError(f"no se puede navegar {expresion}")
        return dato, valor.origen

    # -------------------------------------------------------------- ejecución

    def ejecutar(self, plan: Plan) -> EjecucionPlan:
        """Ejecuta el plan paso a paso y devuelve lo que produjo cada uno."""
        ejecucion = EjecucionPlan()
        for paso in plan.pasos:
            resultado = self._ejecutar_paso(paso, ejecucion)
            ejecucion.pasos.append(resultado)
            if resultado.estado == "bloqueado":
                ejecucion.bloqueados.append(resultado)
        return ejecucion

    def _ejecutar_paso(self, paso: Paso, ejecucion: EjecucionPlan) -> ResultadoPaso:
        if paso.op == OP_RESPONDER:
            return self._responder(paso, ejecucion)

        # Regla 1: lista de herramientas permitidas.
        if paso.op not in self.permitidas:
            self.sandbox.bloquear(paso.op, paso.args, "herramienta no permitida")
            return ResultadoPaso(paso.id, paso.op, "bloqueado", "herramienta no permitida")

        # Regla 3: ningún argumento puede venir de contenido no confiable.
        argumentos: dict[str, Any] = {}
        origenes: dict[str, Origen] = {}
        for clave, expresion in paso.args.items():
            try:
                dato, origen = self.resolver(expresion)
            except KeyError as exc:
                return ResultadoPaso(paso.id, paso.op, "error", str(exc))
            if not origen.es_confiable:
                self.sandbox.bloquear(paso.op, paso.args, f"argumento no confiable: {clave}")
                return ResultadoPaso(
                    paso.id, paso.op, "bloqueado", f"argumento no confiable: {clave}"
                )
            argumentos[clave] = dato
            origenes[clave] = origen

        respuesta = self.sandbox.dispatch(paso.op, argumentos, origen=origenes)
        if "error" in respuesta:
            return ResultadoPaso(paso.id, paso.op, "error", respuesta["error"])
        if paso.op == "compare_products":
            self.comparaciones_ejecutadas.append(
                (paso.id, [str(x) for x in argumentos.get("ids", [])])
            )

        # Regla 2: `get_reviews` produce siempre contenido no confiable.
        crudo = respuesta["resultado"]
        if paso.op == "get_reviews":
            self.entorno[paso.id] = Valor(crudo, Origen.RESENA)
        else:
            self.entorno[paso.id] = Valor(sanear_resultado(crudo), Origen.CATALOGO)
        return ResultadoPaso(paso.id, paso.op, "ejecutado", detalle=None)

    def _responder(self, paso: Paso, ejecucion: EjecucionPlan) -> ResultadoPaso:
        """Compone la respuesta final. Regla 4: lo no confiable se resume antes de entrar."""
        if paso.plantilla is None:
            return ResultadoPaso(paso.id, paso.op, "error", "respond sin plantilla")

        valores: dict[str, str] = {}
        # Lo que de verdad entra en la respuesta: el estado de `cte` se lee de aquí y no de
        # los marcadores que el planificador redacte. Ver `prf.env.estado_cte`.
        resueltos: list[Any] = []
        referenciados: set[str] = set()
        for nombre, expresion in paso.vars.items():
            referenciados |= pasos_referenciados(expresion)
            try:
                dato, origen = self.resolver(expresion)
            except KeyError as exc:
                valores[nombre] = ""
                ejecucion.pasos.append(ResultadoPaso(paso.id, paso.op, "error", f"{nombre}: {exc}"))
                continue
            resueltos.append(dato)
            valores[nombre] = self._a_texto(dato, origen)

        ejecucion.recomendados = recomendados_en_respuesta(resueltos, self.sandbox.catalog.existe)
        ejecucion.comparaciones = comparaciones_entregadas(
            self.comparaciones_ejecutadas, referenciados
        )

        try:
            texto = paso.plantilla.format(**valores)
        except (KeyError, IndexError) as exc:
            return ResultadoPaso(paso.id, paso.op, "error", f"plantilla inválida: {exc}")
        except ValueError:
            # El planificador escribe a veces una especificación de formato numérica sobre un
            # valor que ya es texto —`{precio:,}`—, y `str.format` levanta ValueError. Perder
            # la ejecución entera por eso convertiría un desliz de redacción en una ejecución
            # sin resultado: se compone el texto ignorando la especificación, que es lo que el
            # planificador quiso decir, y queda constancia en el paso.
            texto = _formatear_sin_especificacion(paso.plantilla, valores)
            ejecucion.texto_final = texto
            return ResultadoPaso(
                paso.id, paso.op, "ejecutado", "plantilla con especificación de formato inválida"
            )

        ejecucion.texto_final = texto
        return ResultadoPaso(paso.id, paso.op, "ejecutado")

    def _a_texto(self, dato: Any, origen: Origen) -> str:
        """Convierte un valor en texto para la respuesta, pasando por cuarentena si toca."""
        if origen.es_confiable:
            return str(dato) if not isinstance(dato, (dict, list)) else _resumen_legible(dato)
        if self.cuarentena is None:
            return "[contenido no confiable omitido]"
        resenas = _a_resenas(dato)
        resumen = self.cuarentena.resumir(resenas)
        return _resumen_legible(resumen)


def _a_resenas(dato: Any) -> list[Review]:
    """Reconstruye objetos `Review` desde el resultado serializado de `get_reviews`."""
    if isinstance(dato, dict):
        dato = [dato]
    resenas = []
    for elemento in dato if isinstance(dato, list) else []:
        if isinstance(elemento, dict) and "text" in elemento:
            resenas.append(Review.model_validate(elemento))
    return resenas


def _resumen_legible(dato: Any) -> str:
    """Texto breve para insertar en la plantilla de respuesta."""
    if isinstance(dato, dict):
        if "error" in dato:
            return "resumen de opiniones no disponible"
        if "rating_promedio" in dato:
            partes = [f"evaluación {dato['rating_promedio']:.1f}"]
            if dato.get("pros"):
                partes.append("a favor: " + ", ".join(dato["pros"][:3]))
            if dato.get("contras"):
                partes.append("en contra: " + ", ".join(dato["contras"][:3]))
            return "; ".join(partes)
        if "name" in dato:
            return str(dato["name"])
        return ", ".join(f"{k}: {v}" for k, v in list(dato.items())[:4])
    if isinstance(dato, list):
        return ", ".join(_resumen_legible(e) for e in dato[:3])
    return str(dato)


def parsear_plan(texto: str) -> tuple[Plan | None, str | None]:
    """Convierte la salida del planificador en un `Plan`. Devuelve (plan, error)."""
    import json

    limpio = re.sub(r"^```(?:json)?\s*", "", texto.strip())
    limpio = re.sub(r"\s*```$", "", limpio)
    try:
        datos = json.loads(limpio)
    except json.JSONDecodeError:
        inicio, fin = limpio.find("{"), limpio.rfind("}")
        if inicio == -1 or fin <= inicio:
            return None, "el planificador no devolvió JSON"
        try:
            datos = json.loads(limpio[inicio : fin + 1])
        except json.JSONDecodeError as exc:
            return None, f"JSON inválido: {exc}"
    try:
        return Plan.model_validate(datos), None
    except ValidationError as exc:
        return None, f"plan inválido: {str(exc)[:200]}"


__all__ = [
    "MAX_PASOS",
    "OP_RESPONDER",
    "EjecucionPlan",
    "Interprete",
    "Paso",
    "Plan",
    "ResultadoPaso",
    "Valor",
    "parsear_plan",
]
