"""El análisis de la anotación a ciegas aplica las reglas fijadas antes de recibir los datos.

Lo que se protege es que el script no invente lectura: los tres umbrales de
`docs/E6_REGLA_DE_INTERPRETACION.md` están escritos antes del CSV y aquí se comprueba que se
aplican tal cual, incluida la salvaguarda de que un intervalo que cruza 0,5 no confirma nada.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

from e6_kappa_ciego import (  # noqa: E402
    COLUMNA_VERSION,
    KAPPA_CONFIRMA,
    analizar,
    kappa_cohen,
    leer_csv,
    leer_respuestas,
    veredicto,
    versiones,
)

DOC = RAIZ / "docs" / "E6_REGLA_DE_INTERPRETACION.md"


def _referencias(n: int, *, constraints: int = 0, repetidos: int = 0) -> dict:
    refs = {}
    for i in range(1, n + 1):
        refs[f"C{i:02d}"] = {
            "run_id": f"R{i}",
            "repeticion_de": "",
            "evaluador": 0 if i <= constraints else 1,
            "juez": 1,
            "autor": 1,
            "constraints_falla": 1 if i <= constraints else 0,
        }
    for j in range(repetidos):
        idr = f"C{n + j + 1:02d}"
        original = f"C{j + 1:02d}"
        refs[idr] = {**refs[original], "repeticion_de": original}
    return refs


def _respuestas(refs: dict, p1: dict, p2: dict) -> list[dict]:
    return [
        {
            "id_anonimo": i,
            "p1": p1.get(i, 0),
            "p2": p2.get(i, 1),
            "comentario": "",
            "version_instrumento": "1.1",
        }
        for i in refs
    ]


# ------------------------------------------------------------------- kappa


def test_kappa_es_none_cuando_no_esta_definida():
    # Ambos usan una sola clase: el acuerdo esperado por azar es 1 y la fórmula divide por cero.
    assert kappa_cohen([1, 1, 1], [1, 1, 1]) is None
    assert kappa_cohen([], []) is None


def test_kappa_perfecta_y_nula():
    assert kappa_cohen([1, 0, 1, 0], [1, 0, 1, 0]) == 1.0
    assert kappa_cohen([1, 0, 1, 0], [0, 1, 0, 1]) == -1.0


# ------------------------------------------------------------------- las tres reglas


def test_la_regla_a_usa_el_umbral_de_landis_y_koch():
    assert KAPPA_CONFIRMA == 0.60
    assert "0,60" in DOC.read_text(encoding="utf-8")
    pares = [{"par": "anotación a ciegas (P2) vs anotación del autor", "kappa_cohen": 0.61}]
    prop = {"proporcion": None, "intervalo_95": None}
    assert veredicto(pares, prop, 0)["a"]["resultado"] == "confirmada"
    pares[0]["kappa_cohen"] = 0.59
    assert veredicto(pares, prop, 0)["a"]["resultado"] == "NO confirmada"


def test_la_regla_b_no_confirma_si_el_intervalo_cruza_la_mitad():
    """Una proporción de 0,69 con un intervalo que incluye 0,5 no sostiene la dirección. Decirlo
    es lo que evita presentar como confirmación lo que es imprecisión de la muestra."""
    pares = [{"par": "… vs anotación del autor", "kappa_cohen": 0.7}]
    cruza = {"proporcion": 0.6923, "intervalo_95": {"inferior": 0.4237, "superior": 0.8732}}
    assert "no permite decidir" in veredicto(pares, cruza, 0)["b"]["resultado"]

    claro = {"proporcion": 0.8, "intervalo_95": {"inferior": 0.6, "superior": 0.92}}
    assert "más laxo" in veredicto(pares, claro, 0)["b"]["resultado"]

    bajo = {"proporcion": 0.2, "intervalo_95": {"inferior": 0.08, "superior": 0.4}}
    assert "SE REVISA" in veredicto(pares, bajo, 0)["b"]["resultado"]


def test_la_regla_c_exige_dos_inconsistencias_para_la_salvedad():
    pares = [{"par": "… vs anotación del autor", "kappa_cohen": 0.7}]
    prop = {"proporcion": 0.8, "intervalo_95": {"inferior": 0.6, "superior": 0.92}}
    assert "estable" in veredicto(pares, prop, 1)["c"]["resultado"]
    assert "INESTABLE" in veredicto(pares, prop, 2)["c"]["resultado"]


# ------------------------------------------------------------------- análisis completo


def test_las_repeticiones_no_cuentan_dos_veces_en_los_pares():
    refs = _referencias(10, repetidos=2)
    resp = _respuestas(refs, {}, {})
    salida = analizar(resp, refs)
    assert salida["n_respuestas"] == 12
    assert salida["n_casos_unicos"] == 10
    for p in salida["pares"]:
        assert p["n"] == 10, p["par"]


def test_la_consistencia_se_mide_sobre_los_repetidos():
    refs = _referencias(10, repetidos=2)
    # La segunda vez contesta distinto en uno de los dos.
    resp = _respuestas(refs, {}, {"C11": 0})
    cons = analizar(resp, refs)["consistencia_intra_anotador"]
    assert len(cons["repetidos"]) == 2
    assert cons["n_inconsistentes"] == 1


def test_la_proporcion_se_calcula_solo_sobre_los_que_vieron_el_incumplimiento():
    refs = _referencias(10, constraints=4)
    # Dice que no cumple en 4 casos; en 3 de ellos igual le sirve.
    resp = _respuestas(
        refs,
        {f"C{i:02d}": 1 for i in range(1, 5)},
        {"C04": 0},
    )
    pr = analizar(resp, refs)["le_sirve_pese_al_incumplimiento"]
    assert pr["n_vio_incumplimiento"] == 4
    assert pr["n_aun_asi_le_sirve"] == 3
    assert pr["proporcion"] == 0.75
    assert pr["intervalo_95"]["metodo"] == "wilson"


def test_p1_se_valida_contra_la_regla_constraints():
    refs = _referencias(10, constraints=3)
    resp = _respuestas(refs, {f"C{i:02d}": 1 for i in range(1, 4)}, {})
    v = analizar(resp, refs)["validacion_de_p1"]
    assert v["concordancia_simple"] == 1.0
    assert v["kappa_cohen"] == 1.0


def test_un_id_desconocido_aborta():
    refs = _referencias(3)
    resp = _respuestas(refs, {}, {}) + [
        {"id_anonimo": "C99", "p1": 0, "p2": 1, "comentario": "", "version_instrumento": "1.1"}
    ]
    with pytest.raises(SystemExit, match="no están en la correspondencia"):
        analizar(resp, refs)


# ------------------------------------------------------------------- entrada


def test_el_csv_se_lee_venga_como_venga_de_la_hoja_de_calculo(tmp_path):
    ruta = tmp_path / "r.csv"
    ruta.write_bytes(
        "id_anonimo;p1_opcion_no_cumple;p2_le_sirve;comentario\n"
        "C01;1;0;no cumplía el presupuesto\n".encode("mac_roman")
    )
    filas = leer_respuestas(ruta)
    assert filas == [
        {
            "id_anonimo": "C01",
            "p1": 1,
            "p2": 0,
            "comentario": "no cumplía el presupuesto",
            # Un CSV de la versión 1.0 no trae la columna: se lee igual y queda vacía.
            "version_instrumento": "",
        }
    ]


def test_la_version_del_instrumento_se_lee_por_nombre_de_columna(tmp_path):
    """La columna va al final en el CSV que produce el instrumento, pero una hoja de cálculo
    puede reordenar columnas. Leer por nombre es lo que hace que eso no importe."""
    ruta = tmp_path / "r.csv"
    ruta.write_text(
        f"{COLUMNA_VERSION},p2_le_sirve,id_anonimo,p1_opcion_no_cumple\n1.1,1,C01,0\n",
        encoding="utf-8",
    )
    filas = leer_respuestas(ruta)
    assert filas[0]["version_instrumento"] == "1.1"
    assert filas[0]["id_anonimo"] == "C01" and filas[0]["p1"] == 0 and filas[0]["p2"] == 1


def test_el_analisis_declara_con_que_version_se_respondio_cada_pantalla():
    """Si una parte se respondió con 1.0 y otra con 1.1, hay que verlo en el resultado."""
    assert versiones([{"version_instrumento": "1.1"}] * 3) == {"1.1": 3}
    assert versiones([{"version_instrumento": ""}, {"version_instrumento": "1.1"}]) == {
        "1.1": 1,
        "sin declarar": 1,
    }
    refs = _referencias(4)
    salida = analizar(_respuestas(refs, {}, {}), refs)
    assert salida["version_instrumento"] == {"1.1": 4}


def test_un_csv_sin_las_columnas_nuevas_aborta(tmp_path):
    ruta = tmp_path / "viejo.csv"
    ruta.write_text("id_anonimo,human_success\nC01,1\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="faltan columnas"):
        leer_respuestas(ruta)


def test_la_muestra_del_autor_se_puede_leer_hoy():
    """`data/annotation/e6_sample.csv` está en Mac Roman con `;` desde que pasó por Excel."""
    filas = leer_csv(RAIZ / "data" / "annotation" / "e6_sample.csv")
    assert len(filas) == 64
    assert {"run_id", "state_success", "judge_success", "human_success"} <= set(filas[0])


def test_la_regla_de_interpretacion_existe_y_precede_a_los_datos():
    texto = DOC.read_text(encoding="utf-8")
    assert "antes de recibir el CSV" in texto
    for clave in ("### a)", "### b)", "### c)"):
        assert clave in texto
    assert "policy-v0.3.0" in texto
