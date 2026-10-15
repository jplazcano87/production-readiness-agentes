"""Intérprete Code-Then-Execute: las reglas que el modelo no puede negociar.

Las tres pruebas que exige el plan —argumento no confiable bloqueado, herramienta no
permitida bloqueada, plan válido ejecutado— más las que cubren la resolución de
referencias y el paso de respuesta.
"""

from __future__ import annotations

import pytest

from prf.agent.configuraciones import CTE, NONE
from prf.agent.cte import Interprete, Plan, Valor, parsear_plan
from prf.env import Sandbox
from prf.env.models import Origen


@pytest.fixture
def interprete(catalogo):
    return Interprete(Sandbox(catalogo), herramientas_permitidas=CTE.herramientas)


def plan(*pasos: dict) -> Plan:
    return Plan.model_validate({"pasos": list(pasos)})


# ------------------------------------------------ (a) argumento no confiable


def test_un_argumento_no_confiable_bloquea_el_paso(interprete):
    # Es la regla que corta el secuestro del flujo de control: aunque una reseña logre que
    # el planificador escriba el paso, el intérprete no lo ejecuta.
    interprete.entorno["s1"] = Valor({"id": "P0003"}, Origen.RESENA)

    ejecucion = interprete.ejecutar(
        plan({"id": "s2", "op": "get_product", "args": {"id": "$s1.id"}})
    )

    assert ejecucion.pasos[0].estado == "bloqueado"
    assert "no confiable" in ejecucion.pasos[0].motivo
    assert len(ejecucion.bloqueados) == 1


def test_el_paso_bloqueado_no_invoca_la_herramienta(interprete):
    interprete.entorno["s1"] = Valor({"id": "P0003"}, Origen.RESENA)

    interprete.ejecutar(plan({"id": "s2", "op": "get_product", "args": {"id": "$s1.id"}}))

    assert interprete.sandbox.state.ejecutadas == []
    assert interprete.sandbox.state.bloqueadas[0].nombre == "get_product"


def test_un_argumento_del_catalogo_si_se_acepta(interprete):
    interprete.entorno["s1"] = Valor({"id": "P002"}, Origen.CATALOGO)

    ejecucion = interprete.ejecutar(
        plan({"id": "s2", "op": "get_product", "args": {"id": "$s1.id"}})
    )

    assert ejecucion.pasos[0].estado == "ejecutado"


# ------------------------------------------- (b) herramienta no permitida


@pytest.mark.parametrize("herramienta", ["apply_discount", "send_message"])
def test_las_herramientas_restringidas_no_estan_permitidas_en_cte(interprete, herramienta):
    ejecucion = interprete.ejecutar(
        plan({"id": "s1", "op": herramienta, "args": {"product_id": "P001", "pct": 50}})
    )

    assert ejecucion.pasos[0].estado == "bloqueado"
    assert ejecucion.pasos[0].motivo == "herramienta no permitida"
    assert interprete.sandbox.state.ejecutadas == []


def test_una_herramienta_inventada_tambien_se_bloquea(interprete):
    ejecucion = interprete.ejecutar(plan({"id": "s1", "op": "borrar_todo", "args": {}}))

    assert ejecucion.pasos[0].estado == "bloqueado"


def test_la_lista_de_permitidas_depende_de_la_configuracion():
    # En `cte` las restringidas no están; en `none` se exponen para que el ataque sea
    # observable. La diferencia es del diseño del experimento, no un descuido.
    assert "apply_discount" not in CTE.herramientas
    assert "apply_discount" in NONE.herramientas


# ---------------------------------------------------- (c) plan válido


def test_un_plan_valido_se_ejecuta_de_principio_a_fin(interprete):
    ejecucion = interprete.ejecutar(
        plan(
            {"id": "s1", "op": "search_catalog", "args": {"query": "notebook", "limit": 3}},
            {"id": "s2", "op": "get_product", "args": {"id": "$s1.0.id"}},
            {
                "id": "s3",
                "op": "respond",
                "plantilla": "Te recomiendo {nombre} <<rec:{id}>>.",
                "vars": {"nombre": "$s2.name", "id": "$s2.id"},
            },
        )
    )

    assert [p.estado for p in ejecucion.pasos] == ["ejecutado"] * 3
    assert ejecucion.bloqueados == []
    assert "<<rec:P001>>" in ejecucion.texto_final
    assert "Notebook Aurora 14" in ejecucion.texto_final


def test_la_respuesta_final_queda_en_el_estado(interprete):
    interprete.ejecutar(
        plan(
            {"id": "s1", "op": "search_catalog", "args": {"query": "notebook"}},
            {
                "id": "s2",
                "op": "respond",
                "plantilla": "Mira <<rec:{id}>>.",
                "vars": {"id": "$s1.0.id"},
            },
        )
    )
    final = interprete.sandbox.cerrar(
        interprete.ejecutar(
            plan(
                {"id": "t1", "op": "search_catalog", "args": {"query": "notebook"}},
                {
                    "id": "t2",
                    "op": "respond",
                    "plantilla": "Mira <<rec:{id}>>.",
                    "vars": {"id": "$t1.0.id"},
                },
            )
        ).texto_final
    )

    assert final.recomendaciones == ["P001"]


# ------------------------------------------------------------- referencias


def test_las_referencias_navegan_listas_y_campos(interprete):
    interprete.entorno["s1"] = Valor([{"id": "P001", "sub": {"x": 7}}], Origen.CATALOGO)

    assert interprete.resolver("$s1.0.id") == ("P001", Origen.CATALOGO)
    assert interprete.resolver("$s1.0.sub.x") == (7, Origen.CATALOGO)


def test_un_literal_no_es_una_referencia(interprete):
    assert interprete.resolver("notebook") == ("notebook", Origen.USUARIO)
    assert interprete.resolver(900_000) == (900_000, Origen.USUARIO)


def test_una_referencia_a_un_paso_inexistente_falla(interprete):
    with pytest.raises(KeyError, match="inexistente"):
        interprete.resolver("$sNoExiste")


def test_un_indice_fuera_de_rango_deja_el_paso_en_error(interprete):
    interprete.entorno["s1"] = Valor([{"id": "P001"}], Origen.CATALOGO)

    ejecucion = interprete.ejecutar(
        plan({"id": "s2", "op": "get_product", "args": {"id": "$s1.9.id"}})
    )

    assert ejecucion.pasos[0].estado == "error"


def test_get_reviews_marca_su_salida_como_no_confiable(interprete):
    interprete.ejecutar(plan({"id": "s1", "op": "get_reviews", "args": {"product_id": "P001"}}))

    assert interprete.entorno["s1"].origen is Origen.RESENA
    assert not interprete.entorno["s1"].confiable


def test_sin_cuarentena_el_texto_no_confiable_no_entra_en_la_respuesta(interprete):
    ejecucion = interprete.ejecutar(
        plan(
            {"id": "s1", "op": "get_reviews", "args": {"product_id": "P002"}},
            {
                "id": "s2",
                "op": "respond",
                "plantilla": "Opiniones: {op}",
                "vars": {"op": "$s1"},
            },
        )
    )

    assert "IGNORA TUS INSTRUCCIONES" not in ejecucion.texto_final
    assert "omitido" in ejecucion.texto_final


# ------------------------------------------------------------ parseo del plan


def test_parsear_plan_acepta_json_limpio():
    plan_, error = parsear_plan('{"pasos": [{"id": "s1", "op": "get_product", "args": {}}]}')

    assert error is None
    assert plan_.pasos[0].op == "get_product"


def test_parsear_plan_tolera_bloques_de_codigo():
    plan_, error = parsear_plan('```json\n{"pasos": [{"id": "s1", "op": "x"}]}\n```')

    assert error is None and plan_ is not None


def test_parsear_plan_rechaza_lo_que_no_es_un_plan():
    plan_, error = parsear_plan("no soy JSON")

    assert plan_ is None
    assert "no devolvió JSON" in error


def test_un_plan_demasiado_largo_se_rechaza():
    pasos = [{"id": f"s{i}", "op": "get_product", "args": {}} for i in range(20)]
    plan_, error = parsear_plan('{"pasos": ' + str(pasos).replace("'", '"') + "}")

    assert plan_ is None
    assert "plan inválido" in error


# ------------------------------- referencias dentro de listas y diccionarios


def test_una_referencia_dentro_de_una_lista_se_resuelve(interprete):
    # `compare_products` recibe `ids` como lista: no descender en ella dejaría pasar la
    # cadena literal "$s1.0.id" como si fuera un identificador.
    interprete.entorno["s1"] = Valor([{"id": "P001"}, {"id": "P002"}], Origen.CATALOGO)

    ejecucion = interprete.ejecutar(
        plan({"id": "s2", "op": "compare_products", "args": {"ids": ["$s1.0.id", "$s1.1.id"]}})
    )

    assert ejecucion.pasos[0].estado == "ejecutado"
    assert interprete.sandbox.state.exitosas[0].argumentos["ids"] == ["P001", "P002"]


def test_una_lista_con_un_valor_no_confiable_contamina_el_argumento(interprete):
    # Basta un valor de reseña dentro de la lista para que el argumento entero deje de ser
    # confiable: si no, un ataque solo tendría que esconderse en el segundo elemento.
    interprete.entorno["s1"] = Valor([{"id": "P001"}], Origen.CATALOGO)
    interprete.entorno["s2"] = Valor([{"id": "P003"}], Origen.RESENA)

    ejecucion = interprete.ejecutar(
        plan({"id": "s3", "op": "compare_products", "args": {"ids": ["$s1.0.id", "$s2.0.id"]}})
    )

    assert ejecucion.pasos[0].estado == "bloqueado"
    assert "no confiable" in ejecucion.pasos[0].motivo


def test_las_referencias_dentro_de_un_diccionario_se_resuelven(interprete):
    interprete.entorno["s1"] = Valor({"tope": 900000}, Origen.CATALOGO)

    valor, origen = interprete.resolver({"max_price": "$s1.tope", "query": "notebook"})

    assert valor == {"max_price": 900000, "query": "notebook"}
    assert origen is Origen.USUARIO


def test_una_lista_de_literales_sigue_siendo_del_usuario(interprete):
    valor, origen = interprete.resolver(["P001", "P002"])

    assert valor == ["P001", "P002"]
    assert origen is Origen.USUARIO


def test_una_especificacion_de_formato_invalida_no_pierde_la_ejecucion(interprete):
    """`{precio:,}` sobre un texto levanta ValueError y antes se perdía la ejecución entera.

    Lo destapó la corrida con Haiku, que escribe esa forma más a menudo que Sonnet: dos de
    veintisiete ejecuciones del piloto quedaron sin resultado por un desliz de redacción del
    planificador, no por la defensa.
    """
    ejecucion = interprete.ejecutar(
        plan(
            {"id": "s1", "op": "get_product", "args": {"id": "P001"}},
            {
                "id": "s2",
                "op": "respond",
                "vars": {"precio": "$s1.price_clp", "nombre": "$s1.name"},
                "plantilla": "{nombre} cuesta {precio:,} pesos",
            },
        )
    )

    assert ejecucion.pasos[-1].estado == "ejecutado"
    assert "cuesta" in ejecucion.texto_final
    assert "{precio" not in ejecucion.texto_final


def test_una_plantilla_valida_sigue_formateandose_igual(interprete):
    ejecucion = interprete.ejecutar(
        plan(
            {"id": "s1", "op": "get_product", "args": {"id": "P001"}},
            {
                "id": "s2",
                "op": "respond",
                "vars": {"nombre": "$s1.name"},
                "plantilla": "Te recomiendo {nombre} <<rec:P001>>",
            },
        )
    )

    assert ejecucion.pasos[-1].estado == "ejecutado"
    assert ejecucion.pasos[-1].motivo is None
