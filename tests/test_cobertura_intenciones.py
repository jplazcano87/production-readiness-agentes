"""Cada restricción evaluable debe estar comunicada en el texto de la intención.

`evaluate_state` juzga una recomendación contra `target_state.constraints`. Si el texto no
menciona una de esas restricciones, el caso exige información que nunca entregó: el fallo
es del corpus y no del agente. En v1.0 esto dejó `ROB-BUS-014` fallando 0/8 en las tres
configuraciones.
"""

from __future__ import annotations

import json

import pytest

from prf.env import Constraints, faltas, menciona_categoria, menciona_cifra
from prf.env.cobertura import cifras_del_texto
from prf.infra.config import load_experiments
from prf.infra.paths import paths

VERSION = load_experiments()["corpus_version"]

pytestmark = pytest.mark.skipif(
    not (paths.corpus_version(VERSION) / "MANIFEST.json").is_file(),
    reason="el corpus aún no está construido",
)


def _nombres_citados(caso: dict, catalogo) -> tuple[str, ...]:
    """Nombres de los productos que el caso exige comparar."""
    pares = caso["target_state"].get("must_compare") or []
    return tuple(
        catalogo.get(pid).name for par in pares for pid in par if catalogo.get(pid) is not None
    )


def _casos_evaluados() -> list[dict]:
    """Casos cuyo éxito decide `evaluate_state`: robustez y benignos de seguridad."""
    raiz = paths.corpus_version(VERSION)
    casos = []
    for linea in (raiz / "cases_robustness.jsonl").read_text(encoding="utf-8").splitlines():
        if linea.strip():
            casos.append(json.loads(linea))
    for linea in (raiz / "cases_security.jsonl").read_text(encoding="utf-8").splitlines():
        if linea.strip():
            datos = json.loads(linea)
            if datos["tipo"] == "benigno":
                casos.append(datos)
    return casos


# ----------------------------------------------------- el detector, por unidad


@pytest.mark.parametrize(
    ("texto", "objetivo"),
    [
        ("tengo hasta 704.990 pesos", 704_990),
        ("mi tope son 704990 pesos", 704_990),
        ("puedo gastar 705 mil", 704_990),
        ("hasta 1 millón 564 mil pesos", 1_564_990),
        ("un presupuesto de 1,77 millones", 1_766_990),
    ],
)
def test_reconoce_las_formas_en_que_se_escribe_un_precio(texto, objetivo):
    assert menciona_cifra(texto, objetivo)


def test_no_confunde_una_cifra_cualquiera_con_el_presupuesto():
    assert not menciona_cifra("busco algo con 32 gb de ram", 1_766_990)


def test_una_intencion_vaga_no_comunica_el_presupuesto():
    # El caso real que falló 0/8 en v1.0.
    assert not menciona_cifra("tengo presupuesto para invertir bien", 1_766_990)


def test_las_cifras_se_extraen_con_separadores_de_miles():
    assert 1_766_990 in cifras_del_texto("cuesta $1.766.990 con despacho")


@pytest.mark.parametrize(
    ("texto", "categoria"),
    [
        ("busco un notebook liviano", "notebooks"),
        ("quiero un computador para la U", "notebooks"),
        ("unos audífonos para viajar", "audifonos"),
        ("una freidora de aire", "electrodomesticos_cocina"),
        ("una ampolleta que se controle del celular", "hogar_inteligente"),
    ],
)
def test_reconoce_la_categoria_por_su_nombre_o_sinonimo(texto, categoria):
    assert menciona_categoria(texto, categoria)


def test_detecta_un_atributo_numerico_ausente():
    problemas = faltas(
        "busco un notebook con harta memoria", Constraints(atributos={"ram_gb": {"min": 32}})
    )

    assert [p.tipo for p in problemas] == ["atributo"]


def test_un_atributo_numerico_presente_no_es_falta():
    assert faltas("con al menos 32 GB de RAM", Constraints(atributos={"ram_gb": {"min": 32}})) == []


def test_los_atributos_booleanos_no_se_comprueban():
    # «cancelacion_ruido: true» se expresa de demasiadas formas; exigir una cadena concreta
    # daría falsos positivos que ensuciarían la verificación de lo que sí es comprobable.
    assert (
        faltas("audífonos para concentrarme", Constraints(atributos={"cancelacion_ruido": True}))
        == []
    )


# ------------------------------------------------------- el corpus completo


def test_toda_restriccion_evaluable_esta_comunicada_en_la_intencion():
    from prf.env import Catalog

    catalogo = Catalog.from_corpus(VERSION)
    problemas = []
    for caso in _casos_evaluados():
        constraints = Constraints.model_validate(caso["target_state"]["constraints"])
        for falta in faltas(caso["intent"], constraints, _nombres_citados(caso, catalogo)):
            problemas.append(f"{caso['case_id']}: {falta}")

    assert not problemas, "casos que exigen lo que no comunican:\n  " + "\n  ".join(problemas)


def test_todos_los_casos_de_robustez_y_benignos_se_revisan():
    casos = _casos_evaluados()

    assert len(casos) == 100  # 60 de robustez + 40 benignos de seguridad
