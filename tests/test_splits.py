"""Particiones dev/test: estratificación, herencia de plantilla y ausencia de fugas."""

from __future__ import annotations

import pytest

from make_splits import (
    DEV,
    FILAS,
    TEST,
    cargar_casos,
    contar,
    particionar,
    tabla_markdown,
    verificar,
)
from prf.infra.config import load_experiments
from prf.infra.paths import paths

VERSION = load_experiments()["corpus_version"]
SEED = 20260906
FRACCION = 0.30

pytestmark = pytest.mark.skipif(
    not (paths.corpus_version(VERSION) / "MANIFEST.json").is_file(),
    reason="el corpus v1.0 aún no está construido",
)


@pytest.fixture(scope="module")
def casos():
    return cargar_casos(VERSION)


@pytest.fixture(scope="module")
def asignacion(casos):
    return particionar(casos, seed=SEED, fraccion_dev=FRACCION)


# ------------------------------------------------------------------ invariantes


# Total del corpus v1.4: 60 de robustez, 170 de seguridad y 26 de cumplimiento.
TOTAL_CASOS = 256
# Casos de cumplimiento, y cuántos quedan en desarrollo. Son 8 de 26 y no 8 de 25 porque v1.4
# añade `CUM-026` y la partición es **aditiva**: el caso nuevo va a prueba y ninguno de los 25
# anteriores cambia de lado. Ver `_particion_previa` en `scripts/make_splits.py`.
CASOS_CUMPLIMIENTO = 26
DEV_CUMPLIMIENTO = 8
# Ataques, es decir casos con plantilla: 40 directos, 60 indirectos de reseña y 30 de
# descripción. Los 40 benignos no llevan plantilla.
TOTAL_ATAQUES = 130


def test_todos_los_casos_reciben_particion(casos, asignacion):
    assert len(asignacion) == len(casos) == TOTAL_CASOS
    assert set(asignacion.values()) == {DEV, TEST}


def test_ningun_case_id_esta_en_ambas_particiones():
    # Criterio de "hecho" de la etapa 3, verificado sobre los archivos escritos.
    destino = paths.splits_version(VERSION)
    if not (destino / "dev.txt").is_file():
        pytest.skip("las particiones aún no se han escrito")

    dev = set((destino / "dev.txt").read_text(encoding="utf-8").split())
    test = set((destino / "test.txt").read_text(encoding="utf-8").split())

    assert dev and test
    assert not (dev & test)


def test_los_archivos_cubren_exactamente_el_corpus(casos):
    destino = paths.splits_version(VERSION)
    if not (destino / "dev.txt").is_file():
        pytest.skip("las particiones aún no se han escrito")

    escritos = set((destino / "dev.txt").read_text(encoding="utf-8").split()) | set(
        (destino / "test.txt").read_text(encoding="utf-8").split()
    )

    assert escritos == {c["case_id"] for c in casos}


def test_la_particion_es_determinista(casos, asignacion):
    otra = particionar(casos, seed=SEED, fraccion_dev=FRACCION)

    assert otra == asignacion


def test_una_semilla_distinta_reparte_distinto(casos, asignacion):
    otra = particionar(casos, seed=SEED + 1, fraccion_dev=FRACCION)

    # Los ataques no se sortean, así que solo cambia el resto.
    assert otra != asignacion


def test_verificar_no_encuentra_problemas(casos, asignacion):
    assert verificar(asignacion, casos) == []


# ----------------------------------------------------- herencia de la plantilla


def test_los_ataques_heredan_la_particion_de_su_plantilla(casos, asignacion):
    # Es la regla que impide que una formulación adversarial vista durante el ajuste
    # reaparezca en la medición del ASR.
    ataques = [c for c in casos if c["particion_plantilla"]]

    assert len(ataques) == TOTAL_ATAQUES
    for caso in ataques:
        assert asignacion[caso["case_id"]] == caso["particion_plantilla"], caso["case_id"]


def test_la_regla_se_aplica_tambien_a_los_ataques_directos(casos, asignacion):
    # El plan solo la exige para los indirectos; el riesgo de fuga es el mismo.
    directos = [c for c in casos if c["tipo"] == "directo"]

    assert {asignacion[c["case_id"]] for c in directos} == {DEV, TEST}
    for caso in directos:
        assert asignacion[caso["case_id"]] == caso["particion_plantilla"]


def test_verificar_detecta_una_fuga_de_plantilla(casos, asignacion):
    corrompida = dict(asignacion)
    ataque = next(c for c in casos if c["particion_plantilla"] == DEV)
    corrompida[ataque["case_id"]] = TEST

    problemas = verificar(corrompida, casos)

    assert any(ataque["case_id"] in p for p in problemas)


# ------------------------------------------------------------- estratificación


@pytest.mark.parametrize("tipo", ["busqueda", "comparacion", "recomendacion"])
def test_cada_tipo_de_robustez_se_reparte_30_70(casos, asignacion, tipo):
    ids = [c["case_id"] for c in casos if c["tipo"] == tipo]
    dev = sum(1 for i in ids if asignacion[i] == DEV)

    assert len(ids) == 20
    assert dev == 6  # round(20 * 0.30)


def test_los_benignos_y_el_cumplimiento_se_estratifican(casos, asignacion):
    for tipo, total, esperado_dev in (
        ("benigno", 40, 12),
        (None, CASOS_CUMPLIMIENTO, DEV_CUMPLIMIENTO),
    ):
        ids = [
            c["case_id"]
            for c in casos
            if (c["tipo"] == tipo if tipo else c["dimension"] == "cumplimiento")
        ]
        dev = sum(1 for i in ids if asignacion[i] == DEV)
        assert len(ids) == total
        assert dev == esperado_dev


def test_la_proporcion_global_se_acerca_al_30_por_ciento(asignacion):
    dev = sum(1 for p in asignacion.values() if p == DEV)

    assert 0.28 <= dev / len(asignacion) <= 0.32


def test_e1_dispone_de_los_42_casos_de_robustez_que_presupuesta_el_plan(casos, asignacion):
    robustez_test = [
        c for c in casos if c["dimension"] == "robustez" and asignacion[c["case_id"]] == TEST
    ]

    assert len(robustez_test) == 42


# ---------------------------------------------------------------- tabla 4


def test_la_tabla_tiene_las_filas_exactas_del_informe(casos, asignacion):
    filas = contar(casos, asignacion)

    assert [f["etiqueta"] for f in filas] == [f[0] for f in FILAS]
    assert [f["etiqueta"] for f in filas][:3] == [
        "Robustez: búsqueda",
        "Robustez: comparación",
        "Robustez: recomendación",
    ]


def test_las_filas_suman_el_total_del_corpus(casos, asignacion):
    filas = contar(casos, asignacion)

    assert sum(f["total"] for f in filas) == TOTAL_CASOS
    for fila in filas:
        assert fila["dev"] + fila["test"] == fila["total"]


def test_la_tabla_markdown_tiene_las_columnas_pedidas(casos, asignacion):
    tabla = tabla_markdown(contar(casos, asignacion))

    assert "| Dimensión y tipo | Desarrollo | Prueba | Total |" in tabla
    assert "**Total**" in tabla
    assert tabla.count("\n") == len(FILAS) + 2  # cabecera, separador y fila de total


def test_el_summary_existe_y_trae_la_tabla():
    resumen = paths.splits_version(VERSION) / "summary.md"
    if not resumen.is_file():
        pytest.skip("las particiones aún no se han escrito")

    texto = resumen.read_text(encoding="utf-8")

    assert "| Dimensión y tipo | Desarrollo | Prueba | Total |" in texto
    assert "Robustez: búsqueda" in texto
    assert "Cumplimiento" in texto


def test_la_fraccion_configurada_es_la_del_plan():
    splits = load_experiments()["splits"]

    assert splits["dev_fraction"] == 0.30
    assert splits["test_fraction"] == 0.70
    assert splits["indirect_attacks_follow_template_folder"] is True
