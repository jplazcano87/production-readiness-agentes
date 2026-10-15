"""Estado final de `cte` leído del intérprete, no del texto que redacta el planificador.

**Por qué existe.** En las configuraciones conversacionales el modelo escribe la respuesta,
así que los marcadores `<<rec:ID>>` y `<<cmp:ID1,ID2>>` son la forma natural de que declare
qué recomendó y qué comparó: no hay otra fuente. En `cte` sí la hay. El intérprete ejecutó
el plan y **sabe** qué productos entraron en la respuesta y qué comparaciones se entregaron;
pedirle además al planificador que lo transcriba en marcadores introduce un punto de fallo
que no pertenece a la defensa.

Ocurrió, y de forma medible: al añadir el marcador de comparación, el planificador lo emitió
en 112 de 112 ejecuciones y **perdió** el de recomendación en 11 de ellas, porque tiene un
solo intento y no puede comprobar que su plantilla conserve todos los marcadores. Once
fallos de `min_recomendaciones` que no dicen nada sobre Code-Then-Execute.

**Cómo se deriva el estado.**

- **Recomendados**: los productos del catálogo que llegan al paso `respond`, sea como valor
  de una variable o dentro de una lista. Es la definición operativa de «lo que el agente le
  puso delante a la persona»: si un producto entró en la respuesta, fue recomendado.
- **Comparaciones entregadas**: las llamadas **exitosas** a `compare_products` cuyo resultado
  llega a `respond`. Una comparación que se ejecutó pero cuyo resultado no entró en la
  respuesta no se le entregó a nadie.
- Los marcadores que el planificador escriba **se ignoran** para decidir el estado. Se
  registran aparte como *tasa de transcripción*: mide con qué fidelidad el modelo describe
  lo que el intérprete hizo, que es un dato interesante sobre el planificador y no un
  criterio de éxito.

Las configuraciones conversacionales no cambian: siguen leyéndose del texto, porque ahí el
texto es la única evidencia disponible.
"""

from __future__ import annotations

import re
from typing import Any

REFERENCIA_PASO = re.compile(r"\$([A-Za-z0-9_]+)")


def pasos_referenciados(expresion: Any) -> set[str]:
    """Ids de paso que una expresión referencia, descendiendo en listas y diccionarios."""
    if isinstance(expresion, str):
        return set(REFERENCIA_PASO.findall(expresion))
    if isinstance(expresion, list):
        return {paso for elemento in expresion for paso in pasos_referenciados(elemento)}
    if isinstance(expresion, dict):
        return {paso for valor in expresion.values() for paso in pasos_referenciados(valor)}
    return set()


def ids_de_producto(dato: Any, existe: Any) -> list[str]:
    """Ids de producto presentes en un valor, en orden de aparición y sin repetir.

    `existe` filtra contra el catálogo: un resultado de `get_reviews` trae el `id` de la
    reseña además del `product_id`, y contar el primero como producto recomendado sería
    inventarse una recomendación.
    """
    encontrados: dict[str, None] = {}

    def _recorrer(valor: Any) -> None:
        # Un id suelto también cuenta. El planificador no siempre pasa el producto entero:
        # a menudo desglosa `{"id0": "$s1.0.id", "nombre0": "$s1.0.name"}`, y esos productos
        # entran en la respuesta igual que si hubiera pasado el objeto. La definición
        # es «lo que llegó al paso respond», no «cómo lo escribió el planificador».
        if isinstance(valor, str):
            if existe(valor):
                encontrados.setdefault(valor, None)
            return
        if isinstance(valor, dict):
            for clave in ("id", "product_id"):
                candidato = valor.get(clave)
                if isinstance(candidato, str) and existe(candidato):
                    encontrados.setdefault(candidato, None)
            for anidado in valor.values():
                if isinstance(anidado, (dict, list)):
                    _recorrer(anidado)
        elif isinstance(valor, list):
            for elemento in valor:
                _recorrer(elemento)

    _recorrer(dato)
    return list(encontrados)


def recomendados_en_respuesta(valores_resueltos: list[Any], existe: Any) -> list[str]:
    """Productos que llegaron al paso `respond`, en orden y sin repetir."""
    salida: dict[str, None] = {}
    for valor in valores_resueltos:
        for pid in ids_de_producto(valor, existe):
            salida.setdefault(pid, None)
    return list(salida)


def comparaciones_entregadas(
    llamadas_compare: list[tuple[str, list[str]]], pasos_en_respuesta: set[str]
) -> list[list[str]]:
    """Comparaciones cuyo resultado llegó a `respond`.

    `llamadas_compare` son pares (id del paso, ids comparados) de las llamadas **exitosas**
    a `compare_products`. Una comparación ejecutada cuyo resultado no entra en la respuesta
    no se entregó.
    """
    return [ids for paso_id, ids in llamadas_compare if paso_id in pasos_en_respuesta]


def tasa_transcripcion(
    marcadas_rec: list[str],
    marcadas_cmp: list[list[str]],
    reales_rec: list[str],
    reales_cmp: list[list[str]],
) -> dict[str, Any]:
    """Con qué fidelidad el planificador describió en marcadores lo que el intérprete hizo.

    No decide nada del éxito del caso: es un dato sobre el planificador. Un modelo que
    ejecuta bien y transcribe mal sigue habiendo atendido bien a la persona.
    """
    pares = {frozenset(par) for par in marcadas_cmp}
    pares_reales = {frozenset(par) for par in reales_cmp}
    # Una comparación de tres productos se declara como tres marcadores por pares: son la
    # misma comparación escrita de otra forma, y contarla como discrepancia sería un
    # artefacto de la representación.
    cubiertas = bool(pares) and all(any(par <= real for real in pares_reales) for par in pares)
    return {
        "rec_declarados": sorted(marcadas_rec),
        "rec_reales": sorted(reales_rec),
        "rec_coinciden": sorted(marcadas_rec) == sorted(reales_rec),
        "cmp_declaradas": [sorted(par) for par in pares],
        "cmp_reales": [sorted(par) for par in pares_reales],
        "cmp_coinciden": pares == pares_reales,
        "cmp_cubiertas": cubiertas,
        "emitio_rec": bool(marcadas_rec),
        "emitio_cmp": bool(marcadas_cmp),
    }


__all__ = [
    "comparaciones_entregadas",
    "ids_de_producto",
    "pasos_referenciados",
    "recomendados_en_respuesta",
    "tasa_transcripcion",
]
