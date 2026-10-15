"""Intervalos de confianza por bootstrap."""

from __future__ import annotations

import statistics

import pytest

from prf.eval.bootstrap import bootstrap_ic
from prf.eval.passk import passk_agregado

media = statistics.fmean


def test_el_intervalo_contiene_la_estimacion_puntual():
    ic = bootstrap_ic([0.2, 0.5, 0.8, 0.6, 0.4], media, n_remuestreos=500)

    assert ic.inferior <= ic.valor <= ic.superior


def test_es_reproducible_con_la_misma_semilla():
    # Un IC que cambia entre ejecuciones del mismo análisis no es citable en el informe.
    datos = [0.1, 0.9, 0.5, 0.3, 0.7, 0.2]

    primero = bootstrap_ic(datos, media, seed=7)
    segundo = bootstrap_ic(datos, media, seed=7)

    assert primero == segundo


def test_una_semilla_distinta_da_un_intervalo_distinto():
    datos = [0.1, 0.9, 0.5, 0.3, 0.7, 0.2]

    assert bootstrap_ic(datos, media, seed=1) != bootstrap_ic(datos, media, seed=2)


def test_sin_variabilidad_el_intervalo_es_degenerado():
    ic = bootstrap_ic([0.5] * 10, media, n_remuestreos=200)

    assert ic.inferior == ic.superior == ic.valor == 0.5


def test_mas_casos_estrechan_el_intervalo():
    pocos = bootstrap_ic([0.0, 1.0] * 3, media, n_remuestreos=800)
    muchos = bootstrap_ic([0.0, 1.0] * 60, media, n_remuestreos=800)

    assert (muchos.superior - muchos.inferior) < (pocos.superior - pocos.inferior)


def test_los_limites_no_se_salen_del_rango_de_pass_k():
    # pass^k está acotado en [0,1]: un intervalo normal daría límites fuera de rango.
    ic = bootstrap_ic([1.0] * 20 + [0.9], media, n_remuestreos=500)

    assert 0.0 <= ic.inferior <= ic.superior <= 1.0


def test_una_sola_observacion_no_produce_intervalo():
    ic = bootstrap_ic([0.7], media)

    assert ic.inferior == ic.superior == 0.7
    assert ic.n_remuestreos == 0


def test_sin_observaciones_falla():
    with pytest.raises(ValueError, match="no hay observaciones"):
        bootstrap_ic([], media)


def test_una_confianza_invalida_se_rechaza():
    with pytest.raises(ValueError, match="confianza"):
        bootstrap_ic([0.5, 0.6], media, confianza=1.5)


def test_se_remuestrea_sobre_casos_y_no_sobre_ejecuciones():
    # Las 8 ejecuciones de un caso están correlacionadas: tratarlas como observaciones
    # independientes estrecharía el intervalo de forma artificial.
    exitos_por_caso = [8, 0, 8, 0, 8, 0]

    por_casos = bootstrap_ic(
        exitos_por_caso, lambda m: passk_agregado(m, n=8, k=1), n_remuestreos=800
    )
    por_ejecuciones = bootstrap_ic(
        [1] * 24 + [0] * 24, lambda m: sum(m) / len(m), n_remuestreos=800
    )

    assert (por_casos.superior - por_casos.inferior) > (
        por_ejecuciones.superior - por_ejecuciones.inferior
    )


def test_el_intervalo_se_serializa_con_sus_metadatos():
    datos = bootstrap_ic([0.4, 0.6, 0.5], media, n_remuestreos=300).to_dict()

    assert set(datos) == {
        "valor",
        "ic_inferior",
        "ic_superior",
        "confianza",
        "n_remuestreos",
        "n_casos",
    }
    assert datos["n_casos"] == 3
