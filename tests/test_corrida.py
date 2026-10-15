"""Reanudación, tope de gasto y piloto: lo que evita repetir o desbordar una corrida cara."""

from __future__ import annotations

import json

import pytest

from prf.infra.corrida import (
    EstadoCorrida,
    TopeDeGasto,
    resumen_piloto,
    verificar_piloto,
)


@pytest.fixture
def estado(tmp_path):
    return EstadoCorrida(salida="e_test", directorio=tmp_path, estimacion_usd=10.0)


# ------------------------------------------------------------------- tope de gasto


def test_el_tope_es_1_3_veces_la_estimacion(estado):
    assert estado.tope_usd == pytest.approx(13.0)


def test_por_debajo_del_tope_no_se_detiene(estado):
    estado.comprobar_gasto(12.99)  # no levanta


def test_al_superar_el_tope_se_detiene_y_guarda_el_estado(estado):
    with pytest.raises(TopeDeGasto, match="tope"):
        estado.comprobar_gasto(13.01)

    guardado = json.loads(estado.archivo.read_text(encoding="utf-8"))
    assert guardado["detenida_por"]
    assert guardado["costo_usd"] == pytest.approx(13.01)


# --------------------------------------------------------------------- reanudación


def test_se_saltan_solo_las_ejecuciones_con_archivo(estado, tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "A__none__0.json").write_text("{}", encoding="utf-8")

    n = estado.cargar(runs, ["A__none__0", "A__none__1", "B__none__0"])

    assert n == 1
    assert not estado.pendiente("A__none__0")
    assert estado.pendiente("A__none__1")


def test_sin_archivos_previos_todo_queda_pendiente(estado, tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()

    assert estado.cargar(runs, ["A__none__0"]) == 0
    assert estado.pendiente("A__none__0")


# --------------------------------------------------------------------------- piloto


def test_el_piloto_pasa_cuando_todo_cumple():
    assert verificar_piloto({"utilidad_benigna": 0.95, "entrega": 1.0, "errores": 0}) == []


def test_utilidad_baja_detiene_el_piloto():
    fallos = verificar_piloto({"utilidad_benigna": 0.5, "entrega": 1.0, "errores": 0})

    assert len(fallos) == 1 and "utilidad" in fallos[0]


def test_entrega_baja_detiene_el_piloto():
    fallos = verificar_piloto({"utilidad_benigna": 1.0, "entrega": 0.4, "errores": 0})

    assert len(fallos) == 1 and "entrega" in fallos[0]


def test_un_solo_error_del_arnes_detiene_el_piloto():
    fallos = verificar_piloto({"utilidad_benigna": 1.0, "entrega": 1.0, "errores": 1})

    assert len(fallos) == 1 and "error" in fallos[0]


def test_una_metrica_que_no_aplica_no_se_inventa():
    # E1 no tiene utilidad benigna ni entrega de cargas: no comprobarlas es correcto;
    # fingir un valor sería peor.
    assert verificar_piloto({"utilidad_benigna": None, "entrega": None, "errores": 0}) == []
    assert "no aplica" in resumen_piloto({"utilidad_benigna": None, "entrega": None})
