"""Estado de `cte` derivado del intérprete.

Lo que se prueba aquí es la frontera: quién acredita el estado en `cte`. La
respuesta es el intérprete, y los marcadores que el planificador escriba no cuentan ni a
favor ni en contra; se guardan solo para medir su fidelidad.
"""

from __future__ import annotations

import pytest

from prf.agent.configuraciones import CTE
from prf.agent.cte import Interprete, Plan
from prf.env import Sandbox
from prf.env.estado_cte import (
    comparaciones_entregadas,
    ids_de_producto,
    pasos_referenciados,
    recomendados_en_respuesta,
    tasa_transcripcion,
)


@pytest.fixture
def interprete(catalogo):
    return Interprete(Sandbox(catalogo), herramientas_permitidas=CTE.herramientas)


def plan(*pasos: dict) -> Plan:
    return Plan.model_validate({"pasos": list(pasos)})


# ---------------------------------------------------------------- piezas sueltas


def test_las_referencias_se_leen_tambien_dentro_de_listas():
    assert pasos_referenciados(["$s1.0.id", {"x": "$s2"}]) == {"s1", "s2"}


def test_un_id_que_no_esta_en_el_catalogo_no_es_un_producto():
    # El `id` de una reseña no es una recomendación: contarlo inventaría productos.
    dato = {"id": "R0042", "product_id": "P001"}
    assert ids_de_producto(dato, lambda pid: pid.startswith("P")) == ["P001"]


def test_los_productos_se_cuentan_una_vez_y_en_orden():
    dato = [{"id": "P002"}, {"id": "P001"}, {"id": "P002"}]
    assert recomendados_en_respuesta([dato], lambda pid: True) == ["P002", "P001"]


def test_una_comparacion_que_no_llega_a_respond_no_se_entrego():
    llamadas = [("s3", ["P001", "P002"]), ("s4", ["P002", "P003"])]
    assert comparaciones_entregadas(llamadas, {"s4"}) == [["P002", "P003"]]


# ------------------------------------------------------- el intérprete completo


def test_los_productos_de_una_lista_que_entra_en_respond_son_recomendados(interprete):
    ejecucion = interprete.ejecutar(
        plan(
            {"id": "s1", "op": "search_catalog", "args": {"category": "notebooks"}},
            {"id": "s2", "op": "respond", "vars": {"lista": "$s1"}, "plantilla": "{lista}"},
        )
    )

    assert len(ejecucion.recomendados) >= 1
    assert all(interprete.sandbox.catalog.existe(pid) for pid in ejecucion.recomendados)


def test_un_producto_buscado_pero_no_incluido_en_la_respuesta_no_cuenta(interprete):
    ejecucion = interprete.ejecutar(
        plan(
            {"id": "s1", "op": "search_catalog", "args": {"category": "notebooks"}},
            {"id": "s2", "op": "respond", "vars": {}, "plantilla": "Sin novedades."},
        )
    )

    assert ejecucion.recomendados == []


def test_la_comparacion_se_acredita_cuando_su_resultado_entra_en_la_respuesta(interprete):
    ejecucion = interprete.ejecutar(
        plan(
            {"id": "s1", "op": "compare_products", "args": {"ids": ["P001", "P002"]}},
            {"id": "s2", "op": "respond", "vars": {"c": "$s1"}, "plantilla": "{c}"},
        )
    )

    assert ejecucion.comparaciones == [["P001", "P002"]]


def test_la_comparacion_ejecutada_y_no_entregada_no_se_acredita(interprete):
    ejecucion = interprete.ejecutar(
        plan(
            {"id": "s1", "op": "compare_products", "args": {"ids": ["P001", "P002"]}},
            {"id": "s2", "op": "respond", "vars": {}, "plantilla": "Ya te cuento."},
        )
    )

    assert ejecucion.comparaciones == []


def test_el_estado_final_de_cte_viene_del_interprete_y_no_de_los_marcadores(interprete):
    # La plantilla no escribe ningún marcador y aun así el estado queda acreditado: es
    # justo el punto.
    interprete.ejecutar(
        plan(
            {"id": "s1", "op": "compare_products", "args": {"ids": ["P001", "P002"]}},
            {"id": "s2", "op": "respond", "vars": {"c": "$s1"}, "plantilla": "{c}"},
        )
    )
    ejecucion = interprete.ejecutar(
        plan({"id": "s9", "op": "respond", "vars": {}, "plantilla": "listo"})
    )
    assert ejecucion.comparaciones == []


def test_los_marcadores_del_planificador_no_acreditan_estado_en_cte(catalogo):
    sandbox = Sandbox(catalogo)
    final = sandbox.cerrar(
        "Te recomiendo <<rec:P001>> y comparé <<cmp:P001,P002>>",
        recomendaciones=[],
        comparaciones=[],
    )

    assert final.origen_estado == "interprete"
    assert final.recomendaciones == []
    assert final.comparaciones == []
    assert final.comparaciones_marcadas == []
    # Pero quedan guardados, porque miden la fidelidad del planificador.
    assert final.marcadores_declarados["rec"] == ["P001"]


def test_sin_estado_explicito_el_texto_sigue_mandando(catalogo):
    # Las configuraciones conversacionales no cambian por esto.
    sandbox = Sandbox(catalogo)
    final = sandbox.cerrar("Te recomiendo <<rec:P001>>")

    assert final.origen_estado == "texto"
    assert final.recomendaciones == ["P001"]


# ------------------------------------------------------- tasa de transcripción


def test_la_transcripcion_detecta_el_marcador_que_el_planificador_olvido():
    tasa = tasa_transcripcion([], [["P001", "P002"]], ["P001", "P002"], [["P001", "P002"]])

    assert tasa["emitio_rec"] is False
    assert tasa["rec_coinciden"] is False
    assert tasa["cmp_coinciden"] is True


def test_el_orden_de_una_comparacion_no_es_una_discrepancia():
    tasa = tasa_transcripcion([], [["P002", "P001"]], [], [["P001", "P002"]])

    assert tasa["cmp_coinciden"] is True


def test_una_comparacion_de_tres_declarada_por_pares_no_es_una_discrepancia():
    # El intérprete registra una llamada con tres ids; el planificador escribe los tres
    # pares. Es la misma comparación en otra representación.
    tasa = tasa_transcripcion(
        [],
        [["P001", "P002"], ["P002", "P003"], ["P001", "P003"]],
        [],
        [["P001", "P002", "P003"]],
    )

    assert tasa["cmp_coinciden"] is False
    assert tasa["cmp_cubiertas"] is True


def test_un_id_suelto_que_llega_a_respond_es_una_recomendacion(interprete):
    # El planificador suele desglosar los campos en vez de pasar el producto entero:
    # {"id0": "$s1.0.id", "nombre0": "$s1.0.name"}. Ese producto entró en la respuesta
    # igual, y la definición es «lo que llegó a respond».
    ejecucion = interprete.ejecutar(
        plan(
            {"id": "s1", "op": "search_catalog", "args": {"category": "notebooks"}},
            {
                "id": "s2",
                "op": "respond",
                "vars": {"id0": "$s1.0.id", "nombre0": "$s1.0.name"},
                "plantilla": "{nombre0} <<rec:{id0}>>",
            },
        )
    )

    assert len(ejecucion.recomendados) == 1
    assert interprete.sandbox.catalog.existe(ejecucion.recomendados[0])


def test_una_cadena_que_no_es_un_id_del_catalogo_no_cuenta(interprete):
    ejecucion = interprete.ejecutar(
        plan(
            {
                "id": "s1",
                "op": "respond",
                "vars": {"saludo": "Hola, no encontré nada"},
                "plantilla": "{saludo}",
            }
        )
    )

    assert ejecucion.recomendados == []
