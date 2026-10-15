"""Intervalos para proporciones: el bootstrap no puede informar en cero."""

from __future__ import annotations

import pytest

from prf.eval.bootstrap import bootstrap_ic
from prf.eval.intervalos import clopper_pearson, ic_proporcion, wilson


def test_el_bootstrap_degenera_con_una_muestra_de_ceros():
    # Es el motivo del cambio: no es una certeza, es que remuestrear ceros da ceros.
    ic = bootstrap_ic([0] * 210, lambda m: sum(m) / len(m), n_remuestreos=200, seed=1)

    assert ic.inferior == 0.0 and ic.superior == 0.0


def test_con_cero_exitos_el_intervalo_no_es_cero():
    ic = ic_proporcion(0, 210)

    assert ic.valor == 0.0
    assert ic.ic_inferior == 0.0
    assert 0.01 < ic.ic_superior < 0.02
    assert ic.metodo == "clopper_pearson"


def test_menos_ejecuciones_dejan_mas_incertidumbre():
    # 0 de 60 no dice lo mismo que 0 de 210, y el intervalo tiene que notarlo.
    assert ic_proporcion(0, 60).ic_superior > ic_proporcion(0, 210).ic_superior


def test_con_exitos_usa_wilson():
    ic = ic_proporcion(3, 840)

    assert ic.metodo == "wilson"
    assert ic.ic_inferior > 0
    assert ic.ic_superior > ic.valor


def test_el_extremo_superior_tambien_es_exacto():
    ic = ic_proporcion(60, 60)

    assert ic.metodo == "clopper_pearson"
    assert ic.ic_superior == 1.0
    assert ic.ic_inferior < 1.0


@pytest.mark.parametrize(("exitos", "n"), [(0, 30), (1, 30), (15, 30), (29, 30), (30, 30)])
def test_el_intervalo_siempre_contiene_la_proporcion_y_cabe_en_cero_uno(exitos, n):
    ic = ic_proporcion(exitos, n)

    assert 0.0 <= ic.ic_inferior <= ic.valor <= ic.ic_superior <= 1.0


def test_sin_datos_el_intervalo_es_todo_el_rango():
    ic = ic_proporcion(0, 0)

    assert (ic.ic_inferior, ic.ic_superior) == (0.0, 1.0)
    assert ic.metodo == "sin_datos"


def test_wilson_y_clopper_pearson_coinciden_en_orden_de_magnitud():
    # Wilson es más estrecho pero no debe estar en otro mundo: si lo estuviera, elegir uno u
    # otro cambiaría la conclusión y no solo la precisión.
    w = wilson(10, 100)
    cp = clopper_pearson(10, 100)

    assert cp[0] <= w[0] and w[1] <= cp[1]
