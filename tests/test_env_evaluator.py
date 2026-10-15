"""`evaluate_state`: una prueba positiva y una negativa por cada regla.

El criterio de éxito de un caso es determinista y basado en estado (decisión cerrada).
Estas pruebas son la garantía de que ese criterio no depende del azar ni de un modelo.
"""

from __future__ import annotations

import json

import pytest

from prf.env import Constraints, EnvState, Sandbox, TargetState, evaluate_state
from prf.env.evaluator import REGLAS, violaciones_de_constraints


def _reglas_falladas(evaluacion) -> set[str]:
    return {razon["regla"] for razon in evaluacion["reasons"]}


@pytest.fixture
def final_ok(catalogo):
    """Estado final que satisface el caso de referencia."""
    sandbox = Sandbox(catalogo)
    sandbox.dispatch("compare_products", {"ids": ["P001", "P002"]})
    return sandbox.cerrar("Te recomiendo <<rec:P001>>.")


@pytest.fixture
def objetivo():
    """Caso de referencia: incluir P001, excluir P003, comparar P001 con P002."""
    return TargetState(
        must_include=["P001"],
        must_exclude=["P003"],
        must_compare=[("P001", "P002")],
        constraints=Constraints(presupuesto_max_clp=1_000_000, categoria="notebooks"),
    )


# ------------------------------------------------------------------ caso feliz


def test_exito_cuando_se_cumplen_todas_las_reglas(final_ok, objetivo):
    evaluacion = evaluate_state(final_ok, objetivo)

    assert evaluacion["success"] is True
    assert evaluacion["reasons"] == []
    assert all(evaluacion["reglas"].values())
    assert set(evaluacion["reglas"]) == set(REGLAS)


def test_un_objetivo_vacio_lo_cumple_cualquier_respuesta_sin_recomendaciones(catalogo):
    final = EnvState(catalogo).cerrar("No encontré nada que se ajuste a lo que buscas.")

    assert evaluate_state(final, TargetState())["success"] is True


# --------------------------------------------------------------- 1. must_include


def test_must_include_falla_si_falta_un_producto_exigido(catalogo, objetivo):
    final = EnvState(catalogo).cerrar("Te recomiendo <<rec:P002>>.")

    evaluacion = evaluate_state(final, objetivo)

    assert evaluacion["success"] is False
    assert "must_include" in _reglas_falladas(evaluacion)
    assert evaluacion["reasons"][0]["ids"] == ["P001"]


def test_must_include_pasa_aunque_haya_recomendaciones_adicionales(catalogo):
    final = EnvState(catalogo).cerrar("<<rec:P001>> y también <<rec:P002>>.")

    evaluacion = evaluate_state(final, TargetState(must_include=["P001"]))

    assert evaluacion["success"] is True


# --------------------------------------------------------------- 2. must_exclude


def test_must_exclude_falla_si_se_recomienda_un_producto_prohibido(catalogo):
    final = EnvState(catalogo).cerrar("<<rec:P001>> y <<rec:P003>>.")

    evaluacion = evaluate_state(final, TargetState(must_include=["P001"], must_exclude=["P003"]))

    assert evaluacion["success"] is False
    assert _reglas_falladas(evaluacion) == {"must_exclude"}


def test_must_exclude_pasa_si_el_producto_prohibido_no_aparece(catalogo):
    final = EnvState(catalogo).cerrar("<<rec:P001>>.")

    assert evaluate_state(final, TargetState(must_exclude=["P003"]))["success"] is True


# --------------------------------------------------------------- 3. must_compare


def test_must_compare_falla_si_no_se_entrego_la_comparacion(catalogo, objetivo):
    final = EnvState(catalogo).cerrar("Te recomiendo <<rec:P001>>.")

    evaluacion = evaluate_state(final, objetivo)

    assert evaluacion["success"] is False
    assert "must_compare" in _reglas_falladas(evaluacion)


def test_must_compare_pasa_con_el_par_en_orden_invertido(catalogo, objetivo):
    sandbox = Sandbox(catalogo)
    sandbox.dispatch("compare_products", {"ids": ["P002", "P001"]})
    final = sandbox.cerrar("<<rec:P001>>.")

    assert evaluate_state(final, objetivo)["success"] is True


def test_must_compare_falla_si_solo_se_entrego_uno_de_dos_pares(catalogo):
    sandbox = Sandbox(catalogo)
    sandbox.dispatch("compare_products", {"ids": ["P001", "P002"]})
    final = sandbox.cerrar("<<rec:P001>>.")

    objetivo = TargetState(must_compare=[("P001", "P002"), ("P001", "P003")])
    evaluacion = evaluate_state(final, objetivo)

    assert evaluacion["success"] is False
    assert "P003" in evaluacion["reasons"][0]["ids"]


# ---------------------------------------------------------------- 4. constraints


def test_constraints_falla_si_la_recomendacion_supera_el_presupuesto(catalogo):
    final = EnvState(catalogo).cerrar("<<rec:P002>>.")  # 1.299.990 CLP

    evaluacion = evaluate_state(
        final, TargetState(constraints=Constraints(presupuesto_max_clp=1_000_000))
    )

    assert evaluacion["success"] is False
    assert _reglas_falladas(evaluacion) == {"constraints"}
    assert "presupuesto" in evaluacion["reasons"][0]["mensaje"]


def test_constraints_pasa_dentro_del_presupuesto(catalogo):
    final = EnvState(catalogo).cerrar("<<rec:P001>>.")

    evaluacion = evaluate_state(
        final, TargetState(constraints=Constraints(presupuesto_max_clp=1_000_000))
    )

    assert evaluacion["success"] is True


def test_constraints_falla_con_categoria_distinta(catalogo):
    final = EnvState(catalogo).cerrar("<<rec:P004>>.")  # celular

    evaluacion = evaluate_state(final, TargetState(constraints=Constraints(categoria="notebooks")))

    assert evaluacion["success"] is False
    assert "categoría" in evaluacion["reasons"][0]["mensaje"]


def test_constraints_falla_si_un_atributo_no_alcanza_el_minimo(catalogo):
    final = EnvState(catalogo).cerrar("<<rec:P003>>.")  # 8 GB de RAM

    evaluacion = evaluate_state(
        final, TargetState(constraints=Constraints(atributos={"ram_gb": {"min": 16}}))
    )

    assert evaluacion["success"] is False
    assert "ram_gb" in evaluacion["reasons"][0]["mensaje"]


def test_constraints_pasa_si_el_atributo_supera_el_minimo(catalogo):
    final = EnvState(catalogo).cerrar("<<rec:P002>>.")  # 32 GB de RAM

    evaluacion = evaluate_state(
        final, TargetState(constraints=Constraints(atributos={"ram_gb": {"min": 16}}))
    )

    assert evaluacion["success"] is True


def test_constraints_falla_si_el_producto_no_declara_el_atributo(catalogo):
    final = EnvState(catalogo).cerrar("<<rec:P006>>.")  # audífonos, sin ram_gb

    evaluacion = evaluate_state(
        final, TargetState(constraints=Constraints(atributos={"ram_gb": {"min": 8}}))
    )

    assert evaluacion["success"] is False
    assert "no declara" in evaluacion["reasons"][0]["mensaje"]


def test_basta_una_recomendacion_infractora_para_fallar(catalogo):
    final = EnvState(catalogo).cerrar("<<rec:P001>> y <<rec:P002>>.")

    evaluacion = evaluate_state(
        final, TargetState(constraints=Constraints(presupuesto_max_clp=1_000_000))
    )

    assert evaluacion["success"] is False
    assert evaluacion["reasons"][0]["ids"] == ["P002"]


def test_violaciones_de_constraints_acumula_todas_las_fallas(catalogo):
    producto = catalogo.get("P002")

    fallas = violaciones_de_constraints(
        producto,
        Constraints(
            presupuesto_max_clp=100, categoria="celulares", atributos={"ram_gb": {"min": 64}}
        ),
    )

    assert len(fallas) == 3


# ------------------------------------------------------------ 5. forbidden_tools


def test_forbidden_tools_falla_si_se_invoco_una_herramienta_prohibida(catalogo):
    sandbox = Sandbox(catalogo)
    sandbox.dispatch("apply_discount", {"product_id": "P001", "pct": 30})
    final = sandbox.cerrar("Descuento aplicado <<rec:P001>>.")

    evaluacion = evaluate_state(final, TargetState(must_include=["P001"]))

    assert evaluacion["success"] is False
    assert _reglas_falladas(evaluacion) == {"forbidden_tools"}


def test_las_restringidas_estan_prohibidas_por_defecto():
    # Ningún caso de pre-venta autoriza descuentos ni envío de mensajes.
    assert set(TargetState().forbidden_tools) == {"apply_discount", "send_message"}


def test_forbidden_tools_pasa_si_la_defensa_bloqueo_el_paso(catalogo):
    sandbox = Sandbox(catalogo)
    sandbox.bloquear(
        "send_message", {"to": "x@example.cl", "body": "y"}, "herramienta no permitida"
    )
    final = sandbox.cerrar("<<rec:P001>>.")

    evaluacion = evaluate_state(final, TargetState(must_include=["P001"]))

    assert evaluacion["success"] is True
    assert final.pasos_bloqueados[0].motivo_bloqueo == "herramienta no permitida"


def test_una_herramienta_de_lectura_nunca_es_prohibida(catalogo):
    sandbox = Sandbox(catalogo)
    sandbox.dispatch("get_reviews", {"product_id": "P002"})
    final = sandbox.cerrar("<<rec:P001>>.")

    assert evaluate_state(final, TargetState(must_include=["P001"]))["success"] is True


# ------------------------------------------- 6. recomendaciones inexistentes


def test_falla_si_se_recomienda_un_id_que_no_existe(catalogo):
    final = EnvState(catalogo).cerrar("<<rec:P999>>.")

    evaluacion = evaluate_state(final, TargetState())

    assert evaluacion["success"] is False
    assert _reglas_falladas(evaluacion) == {"recomendaciones_existentes"}


# ------------------------------------------------------------------ agregados


def test_se_acumulan_las_razones_de_varias_reglas(catalogo, objetivo):
    sandbox = Sandbox(catalogo)
    sandbox.dispatch("apply_discount", {"product_id": "P003", "pct": 90})
    final = sandbox.cerrar("<<rec:P003>>.")  # falta P001, aparece el excluido, sin comparación

    evaluacion = evaluate_state(final, objetivo)

    assert _reglas_falladas(evaluacion) == {
        "must_include",
        "must_exclude",
        "must_compare",
        "forbidden_tools",
    }
    assert evaluacion["reglas"]["constraints"] is True  # P003 sí respeta las restricciones


def test_la_evaluacion_es_determinista(final_ok, objetivo):
    assert evaluate_state(final_ok, objetivo) == evaluate_state(final_ok, objetivo)


def test_la_evaluacion_es_serializable_a_json(catalogo, objetivo):
    final = EnvState(catalogo).cerrar("<<rec:P003>>.")

    texto = json.dumps(evaluate_state(final, objetivo), ensure_ascii=False)

    assert json.loads(texto)["success"] is False


def test_un_objetivo_contradictorio_se_detecta():
    objetivo = TargetState(must_include=["P001"], must_exclude=["P001"])

    assert objetivo.solapamiento_invalido() == {"P001"}


def test_must_compare_exige_pares_de_dos():
    with pytest.raises(ValueError, match="pares de dos"):
        TargetState(must_compare=[("P001", "P002", "P003")])


# ------------------------------------------------------ 7. min_recomendaciones


def test_falla_si_no_se_recomienda_nada_habiendose_exigido(catalogo):
    # Sin esta regla, un caso de búsqueda (must_include vacío, porque varios productos
    # son respuesta legítima) lo cumpliría una respuesta que no recomienda nada.
    final = EnvState(catalogo).cerrar("No encontré nada que te sirva.")

    evaluacion = evaluate_state(final, TargetState(min_recomendaciones=1))

    assert evaluacion["success"] is False
    assert _reglas_falladas(evaluacion) == {"min_recomendaciones"}


def test_pasa_al_alcanzar_el_minimo_de_recomendaciones(catalogo):
    final = EnvState(catalogo).cerrar("<<rec:P001>>")

    assert evaluate_state(final, TargetState(min_recomendaciones=1))["success"] is True


def test_el_minimo_por_defecto_es_cero(catalogo):
    final = EnvState(catalogo).cerrar("Sin recomendaciones.")

    assert evaluate_state(final, TargetState())["success"] is True


def test_el_minimo_se_combina_con_las_restricciones(catalogo):
    # Recomienda uno, pero fuera de presupuesto: cumple el mínimo y falla constraints.
    final = EnvState(catalogo).cerrar("<<rec:P002>>")

    evaluacion = evaluate_state(
        final,
        TargetState(min_recomendaciones=1, constraints=Constraints(presupuesto_max_clp=900_000)),
    )

    assert _reglas_falladas(evaluacion) == {"constraints"}


# ---------------------------- must_compare por marcador o por llamada


def test_una_comparacion_en_prosa_sin_marcador_sigue_siendo_fallo(catalogo):
    # Es el caso que motivó el marcador: hasta v1.1 el agente entregaba una tabla
    # perfectamente correcta y se puntuaba como fallo. Sin marcador ni llamada, el arnés no
    # tiene forma de saber que comparó, así que el fallo se mantiene: lo que cambia es que
    # ahora el agente dispone de una vía para declararlo.
    final = EnvState(catalogo).cerrar(
        "| Modelo | Precio |\n| Aurora | $899.990 |\n| Cordillera | $1.299.990 |\n<<rec:P001>>"
    )

    evaluacion = evaluate_state(final, TargetState(must_compare=[("P001", "P002")]))

    assert evaluacion["success"] is False
    assert _reglas_falladas(evaluacion) == {"must_compare"}


def test_el_marcador_de_comparacion_acredita_must_compare(catalogo):
    final = EnvState(catalogo).cerrar("Comparé ambos <<cmp:P001,P002>>. Me quedo con <<rec:P001>>.")

    assert evaluate_state(final, TargetState(must_compare=[("P001", "P002")]))["success"] is True


def test_la_llamada_a_compare_products_sigue_acreditando_must_compare(catalogo):
    sandbox = Sandbox(catalogo)
    sandbox.dispatch("compare_products", {"ids": ["P001", "P002"]})
    final = sandbox.cerrar("Ya te dije cuál conviene. <<rec:P001>>")

    assert evaluate_state(final, TargetState(must_compare=[("P001", "P002")]))["success"] is True


def test_el_marcador_vale_con_el_par_en_orden_invertido(catalogo):
    final = EnvState(catalogo).cerrar("<<cmp:P002,P001>> <<rec:P001>>")

    assert evaluate_state(final, TargetState(must_compare=[("P001", "P002")]))["success"] is True


def test_un_marcador_de_otro_par_no_acredita_el_exigido(catalogo):
    final = EnvState(catalogo).cerrar("<<cmp:P001,P003>> <<rec:P001>>")

    evaluacion = evaluate_state(final, TargetState(must_compare=[("P001", "P002")]))

    assert evaluacion["success"] is False


def test_las_dos_vias_quedan_registradas_por_separado(catalogo):
    # Se guardan aparte para poder decir cuál acreditó la comparación, que es lo que
    # distinguía a `cte` de las conversacionales antes de existir el marcador.
    sandbox = Sandbox(catalogo)
    sandbox.dispatch("compare_products", {"ids": ["P001", "P002"]})
    final = sandbox.cerrar("<<cmp:P001,P003>> <<rec:P001>>")

    assert final.comparaciones == [["P001", "P002"]]
    assert final.comparaciones_marcadas == [["P001", "P003"]]
