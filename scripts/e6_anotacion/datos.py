"""Lo que la interfaz de anotación necesita de cada ejecución, y nada más.

Este módulo es el que **ciega** la muestra. Todo lo que pueda anclar a la persona que anota
—configuración de defensa, tipo de caso, `run_id`, `case_id`, el veredicto del evaluador y el
del juez— se queda aquí y no llega al HTML. La ronda anterior de E6 falló justamente por lo
contrario: el formulario mostraba `judge_success` y `judge_reason` en la misma fila que la celda
por rellenar, y el acuerdo resultante no es verificable.

Lo que sí viaja es lo que hace falta para juzgar: el mensaje del cliente, la conversación y los
productos que el asistente consultó, para poder comprobar las restricciones.
"""

from __future__ import annotations

import csv
import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Marcadores internos con los que el agente acredita su estado final. Son instrumentación del
# marco, no algo que un cliente vería, así que se quitan del texto visible.
MARCADORES = re.compile(r"<<(?:rec|cmp):[^>]*>>")

# Campos del catálogo que sirven para comprobar una restricción. `description` queda fuera: es
# prosa de marketing, alarga la tabla y no se usa para verificar nada.
ATRIBUTOS_UTILES = (
    "ram_gb",
    "ssd_gb",
    "pantalla_pulgadas",
    "peso_kg",
    "procesador",
    "bateria_mah",
    "camara_mp",
    "almacenamiento_gb",
    "autonomia_horas",
    "cancelacion_ruido",
    "resistencia_agua",
    "pulgadas",
    "resolucion",
    "tecnologia",
    "capacidad_litros",
    "potencia_watts",
)

# El id de catálogo con que el agente nombra un producto («el P0031», «Más barato: P0126»).
# Cuando la respuesta solo usa el código, la tabla es el único lugar donde quien anota puede
# saber de qué producto habla, así que el código tiene que estar ahí.
CODIGO_PRODUCTO = re.compile(r"\bP\d{4}\b")

PREFIJO_ANONIMO = "C"

# Los únicos roles que una persona vería en una conversación real. `planificador` es el turno
# interno de `cte` y lleva el plan en JSON: mostrarlo delataría la configuración —rompiendo el
# ciegamiento— y además es jerga que la persona no tiene por qué leer.
ROLES_VISIBLES = ("usuario", "asistente")


@dataclass
class Caso:
    """Una ejecución lista para mostrarse, ya ciega."""

    id_anonimo: str
    pedido: str
    turnos: list[dict[str, str]] = field(default_factory=list)
    productos: list[dict[str, Any]] = field(default_factory=list)
    explicacion: str = ""  # solo en los casos de práctica

    def to_dict(self) -> dict[str, Any]:
        """El caso tal como viaja al HTML. Nada que no esté aquí llega a quien anota."""
        d = {
            "id": self.id_anonimo,
            "pedido": self.pedido,
            "turnos": self.turnos,
            "productos": self.productos,
        }
        if self.explicacion:
            d["explicacion"] = self.explicacion
        return d


def limpiar(texto: str) -> str:
    """Quita los marcadores internos y los espacios que dejan."""
    return re.sub(r"[ \t]{2,}", " ", MARCADORES.sub("", texto)).strip()


def _precio(valor: Any) -> str:
    try:
        return "$" + f"{int(valor):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "—"


def _atributos(producto: dict[str, Any]) -> dict[str, Any]:
    attrs = producto.get("attributes") or {}
    return {k: attrs[k] for k in ATRIBUTOS_UTILES if k in attrs}


def productos_consultados(ejecucion: dict[str, Any]) -> list[dict[str, Any]]:
    """Los productos que las herramientas devolvieron, sin repetir y en orden de aparición.

    Se muestran para que la persona pueda comprobar una restricción —presupuesto, memoria,
    batería— contra el catálogo, en vez de creerle al asistente. Sin esto, «respeta sus
    restricciones» no es verificable.
    """
    vistos: dict[str, dict[str, Any]] = {}
    for llamada in ejecucion.get("llamadas") or []:
        for producto in _productos_de(llamada.get("resultado")):
            pid = producto.get("id")
            if not pid or pid in vistos:
                continue
            vistos[pid] = {
                "codigo": pid,
                "nombre": producto.get("name", "—"),
                "precio": _precio(producto.get("price_clp")),
                "precio_num": producto.get("price_clp"),
                "stock": producto.get("stock"),
                "valoracion": producto.get("avg_rating"),
                "atributos": _atributos(producto),
            }
    return list(vistos.values())


def _productos_de(resultado: Any) -> list[dict[str, Any]]:
    """Los productos que hay dentro de un resultado de herramienta, a cualquier profundidad."""
    if isinstance(resultado, dict):
        if "price_clp" in resultado:
            return [resultado]
        return [p for v in resultado.values() for p in _productos_de(v)]
    if isinstance(resultado, list):
        return [p for v in resultado for p in _productos_de(v)]
    return []


def desde_catalogo(ejecucion: dict[str, Any], catalogo: Any) -> list[dict[str, Any]]:
    """Los productos vistos, reconstruidos desde el catálogo congelado.

    Respaldo para las corridas que no persistieron el resultado de cada herramienta: las de
    desarrollo son anteriores al arreglo que lo registra. `final_state.productos_vistos` sí
    guarda qué productos pasaron por las herramientas, y el catálogo —congelado y con hash— da
    sus datos. Es la misma información, tomada de la fuente de verdad en vez del registro.
    """
    salida = []
    for pid in (ejecucion.get("final_state") or {}).get("productos_vistos") or []:
        fila = _fila_de_catalogo(pid, catalogo)
        if fila is not None:
            salida.append(fila)
    return salida


def _fila_de_catalogo(pid: str, catalogo: Any) -> dict[str, Any] | None:
    """La fila de la tabla para un producto, tomada del catálogo congelado."""
    producto = catalogo.get(pid) if catalogo is not None else None
    if producto is None:
        return None
    return {
        "codigo": pid,
        "nombre": producto.name,
        "precio": _precio(producto.price_clp),
        "precio_num": producto.price_clp,
        "stock": producto.stock,
        "valoracion": producto.avg_rating,
        "atributos": _atributos({"attributes": dict(producto.attributes or {})}),
    }


def codigos_citados(turnos: list[dict[str, str]]) -> list[str]:
    """Los códigos de producto que el asistente escribió, en orden y sin repetir.

    Solo los turnos del asistente: un código que la persona lea en la respuesta es el que
    necesita poder buscar en la tabla. Se lee del texto **ya limpio**, que es el que se ve;
    los códigos de los marcadores internos (`<<rec:…>>`) ya no están ahí.
    """
    salida: list[str] = []
    for turno in turnos:
        if turno.get("rol") != "asistente":
            continue
        for codigo in CODIGO_PRODUCTO.findall(turno.get("texto", "")):
            if codigo not in salida:
                salida.append(codigo)
    return salida


def completar_con_codigos_citados(
    productos: list[dict[str, Any]], turnos: list[dict[str, str]], catalogo: Any
) -> list[dict[str, Any]]:
    """Añade a la tabla los productos que el asistente nombró por código y no están en ella.

    El asistente puede nombrar un producto que no pasó por ninguna herramienta: el índice del
    catálogo va en el system prompt, así que puede citarlo de memoria. Cuando eso pasa y la
    respuesta solo da el código, quien anota no tiene dónde mirar el precio ni los atributos y
    la pregunta 1 queda sin respuesta posible. Se añaden al final, con sus datos del catálogo:
    el orden de los que ya estaban no cambia.
    """
    if catalogo is None:
        return productos
    presentes = {p.get("codigo") for p in productos}
    completos = list(productos)
    for codigo in codigos_citados(turnos):
        if codigo in presentes:
            continue
        fila = _fila_de_catalogo(codigo, catalogo)
        if fila is None:
            continue
        completos.append(fila)
        presentes.add(codigo)
    return completos


def leer_ejecucion(ruta: Path) -> dict[str, Any]:
    return json.loads(ruta.read_text(encoding="utf-8"))


def caso_desde(ruta: Path, id_anonimo: str, *, explicacion: str = "", catalogo: Any = None) -> Caso:
    """Construye el caso visible. Nada de lo que no esté aquí llega al HTML."""
    datos = leer_ejecucion(ruta)
    ejecucion = datos["ejecucion"]
    turnos = [
        {"rol": t["rol"], "texto": limpiar(t["texto"])}
        for t in ejecucion["transcripcion"]
        if t["rol"] in ROLES_VISIBLES and limpiar(t["texto"])
    ]
    pedido = next((t["texto"] for t in turnos if t["rol"] == "usuario"), "")
    productos = productos_consultados(ejecucion)
    if not productos and catalogo is not None:
        productos = desde_catalogo(ejecucion, catalogo)
    productos = completar_con_codigos_citados(productos, turnos, catalogo)
    return Caso(
        id_anonimo=id_anonimo,
        pedido=pedido,
        turnos=turnos,
        productos=productos,
        explicacion=explicacion,
    )


class TranscripcionesIncompletas(RuntimeError):
    """Falta alguna transcripción de la muestra: no se genera nada.

    Generar la interfaz con 63 de 64 casos produciría una anotación que no se puede comparar
    con el evaluador ni con el juez sobre la misma muestra, y el hueco se descubriría al final.
    """


def con_opciones_mixtas(ruta: Path) -> bool:
    """Si la ejecución trae el patrón difícil: varias opciones y alguna incumple una condición.

    Es donde el criterio del evaluador y el del juez se separan —13 de los 16 desacuerdos— y
    por tanto donde se espera que el criterio humano sea menos estable. La clasificación es
    **interna**: sirve para elegir qué repetir y nunca llega al HTML.
    """
    datos = leer_ejecucion(ruta)
    evaluacion = datos.get("evaluacion") or {}
    if evaluacion.get("success"):
        return False
    reglas = {r["regla"] for r in evaluacion.get("reasons") or []}
    recomendaciones = (datos["ejecucion"].get("final_state") or {}).get("recomendaciones") or []
    return "constraints" in reglas and len(recomendaciones) > 1


def elegir_repeticiones(
    orden: list[dict[str, str]], raiz: Path, separacion: int, seed: int, por_clase: int = 2
) -> list[str]:
    """Qué ejecuciones repetir: `por_clase` con el patrón de opciones mixtas y otras tantas claras.

    Solo se consideran las que caen lo bastante temprano en el orden barajado como para que su
    repetición quepa `separacion` posiciones después. Las claras funcionan de control: si quien
    anota también se contradice ahí, lo que es inestable es la atención y no el criterio.
    """
    tope = len(orden) - separacion
    elegibles = list(enumerate(orden))[:tope]
    mixtas = [f["run_id"] for _, f in elegibles if con_opciones_mixtas(raiz / f["transcript_path"])]
    claras = [
        f["run_id"] for _, f in elegibles if not con_opciones_mixtas(raiz / f["transcript_path"])
    ]
    azar = random.Random(seed + 2)
    if len(mixtas) < por_clase or len(claras) < por_clase:
        raise ValueError(
            f"no hay suficientes candidatos en las primeras {tope} posiciones: "
            f"{len(mixtas)} con opciones mixtas y {len(claras)} claras"
        )
    return azar.sample(mixtas, por_clase) + azar.sample(claras, por_clase)


def _intercalar_repeticiones(
    orden: list[dict[str, str]], repetir: list[str], separacion: int, seed: int
) -> list[tuple[dict[str, str], bool]]:
    """Inserta cada caso a repetir una segunda vez, al menos `separacion` posiciones después.

    El test-retest mide si quien anota se contesta lo mismo a sí mismo. Para que mida eso y no
    la memoria a corto plazo, la repetición tiene que caer lo bastante lejos del original: dos
    pantallas seguidas con el mismo caso se reconocen, y entonces el acuerdo es un recuerdo.
    """
    salida: list[tuple[dict[str, str], bool]] = [(f, False) for f in orden]
    azar = random.Random(seed + 1)
    for run_id in repetir:
        origen = next(i for i, (f, rep) in enumerate(salida) if f["run_id"] == run_id and not rep)
        minimo = origen + separacion + 1
        if minimo > len(salida):
            raise ValueError(
                f"no cabe la repetición de {run_id}: está en la posición {origen + 1} y la "
                f"separación mínima es {separacion}"
            )
        destino = azar.randint(minimo, len(salida))
        salida.insert(destino, (dict(salida[origen][0]), True))
    return salida


def cargar_muestra(
    csv_ciego: Path,
    raiz: Path,
    seed: int,
    catalogo: Any = None,
    repetir: list[str] | None = None,
    separacion: int = 20,
) -> tuple[list[Caso], list[dict[str, str]]]:
    """Las ejecuciones de la muestra, barajadas con semilla fija y con id anónimo.

    `repetir` son los `run_id` que se muestran **dos veces**, con ids anónimos distintos, para
    medir la consistencia de quien anota consigo mismo. La correspondencia marca cuál es la
    repetición; dentro del HTML no hay nada que las relacione.

    La tabla de correspondencia se escribe **aparte**: si viajara dentro del HTML, bastaría
    abrir el archivo para romper el ciegamiento.
    """
    filas = list(csv.DictReader(csv_ciego.open(encoding="utf-8")))
    faltan = [f["transcript_path"] for f in filas if not (raiz / f["transcript_path"]).is_file()]
    if faltan:
        raise TranscripcionesIncompletas(
            f"faltan {len(faltan)} de {len(filas)} transcripciones de la muestra: "
            + ", ".join(faltan[:5])
            + ("…" if len(faltan) > 5 else "")
        )

    orden = list(filas)
    random.Random(seed).shuffle(orden)
    if repetir is None:
        repetir = elegir_repeticiones(orden, raiz, separacion, seed)
    secuencia = _intercalar_repeticiones(orden, repetir, separacion, seed)

    casos, correspondencia = [], []
    primera_vez: dict[str, str] = {}
    for i, (fila, es_repeticion) in enumerate(secuencia, start=1):
        id_anonimo = f"{PREFIJO_ANONIMO}{i:02d}"
        casos.append(caso_desde(raiz / fila["transcript_path"], id_anonimo, catalogo=catalogo))
        correspondencia.append(
            {
                "id_anonimo": id_anonimo,
                "run_id": fila["run_id"],
                "transcript_path": fila["transcript_path"],
                "repeticion_de": primera_vez.get(fila["run_id"], "") if es_repeticion else "",
            }
        )
        primera_vez.setdefault(fila["run_id"], id_anonimo)
    return casos, correspondencia


def cargar_practica(practica: list[dict[str, str]], raiz: Path, catalogo: Any = None) -> list[Caso]:
    """Los casos de ensayo, que vienen de la partición de desarrollo y no se exportan."""
    casos = []
    for i, p in enumerate(practica, start=1):
        ruta = raiz / p["transcript_path"]
        if not ruta.is_file():
            raise TranscripcionesIncompletas(f"falta el caso de práctica {p['transcript_path']}")
        casos.append(caso_desde(ruta, f"P{i}", explicacion=p["explicacion"], catalogo=catalogo))
    return casos


__all__ = [
    "ATRIBUTOS_UTILES",
    "CODIGO_PRODUCTO",
    "ROLES_VISIBLES",
    "Caso",
    "MARCADORES",
    "TranscripcionesIncompletas",
    "codigos_citados",
    "completar_con_codigos_citados",
    "cargar_muestra",
    "con_opciones_mixtas",
    "desde_catalogo",
    "elegir_repeticiones",
    "cargar_practica",
    "caso_desde",
    "limpiar",
    "productos_consultados",
]
