"""Estimadores pass^k y pass@k.

Se comprueban contra valores calculados a mano y contra propiedades que el estimador debe
cumplir por construcción, no contra una implementación de referencia: una prueba que
compare el código consigo mismo no detecta un error en la fórmula.
"""

from __future__ import annotations

import math
from fractions import Fraction

import pytest

from prf.eval.passk import (
    curva_passk,
    exitos_desde_matriz,
    pass_at_k,
    passk,
    passk_agregado,
    passk_por_caso,
)

# ------------------------------------------- valores conocidos que fija el plan


def test_todas_las_ejecuciones_aciertan():
    assert passk(8, 8, 1) == 1.0
    assert passk(8, 8, 8) == 1.0


def test_con_la_mitad_de_aciertos_no_se_puede_acertar_ocho_de_ocho():
    assert passk(8, 4, 8) == 0.0


def test_seis_aciertos_de_ocho_eligiendo_dos():
    # C(6,2)/C(8,2) = 15/28
    assert passk(8, 6, 2) == pytest.approx(float(Fraction(15, 28)))


# ------------------------------------------------------ fórmula, caso por caso


@pytest.mark.parametrize(
    ("n", "c", "k"),
    [(8, c, k) for c in range(9) for k in range(1, 9)],
)
def test_passk_coincide_con_la_definicion_combinatoria(n, c, k):
    esperado = 0.0 if c < k else math.comb(c, k) / math.comb(n, k)

    assert passk(n, c, k) == pytest.approx(esperado)


@pytest.mark.parametrize(
    ("n", "c", "k"),
    [(8, c, k) for c in range(9) for k in range(1, 9)],
)
def test_pass_at_k_coincide_con_la_definicion_combinatoria(n, c, k):
    esperado = 1.0 if n - c < k else 1.0 - math.comb(n - c, k) / math.comb(n, k)

    assert pass_at_k(n, c, k) == pytest.approx(esperado)


# --------------------------------------------------------------- propiedades


def test_con_k_igual_a_uno_ambas_metricas_son_la_tasa_de_exito():
    for c in range(9):
        assert passk(8, c, 1) == pytest.approx(c / 8)
        assert pass_at_k(8, c, 1) == pytest.approx(c / 8)


def test_passk_no_crece_al_aumentar_k():
    # Exigir que k ejecuciones acierten todas es más difícil cuanto mayor es k.
    valores = [passk(8, 6, k) for k in range(1, 9)]

    assert valores == sorted(valores, reverse=True)


def test_pass_at_k_no_decrece_al_aumentar_k():
    valores = [pass_at_k(8, 2, k) for k in range(1, 9)]

    assert valores == sorted(valores)


def test_passk_no_decrece_al_aumentar_los_aciertos():
    valores = [passk(8, c, 4) for c in range(9)]

    assert valores == sorted(valores)


def test_las_dos_metricas_se_separan_cuando_el_agente_es_inconsistente():
    # Es el argumento de por qué la fiabilidad no se mide con pass@k: con 4 de 8 aciertos,
    # «al menos una de cuatro acierta» es casi seguro y «las cuatro aciertan» es casi nulo.
    assert pass_at_k(8, 4, 4) > 0.95
    assert passk(8, 4, 4) < 0.02


def test_un_agente_determinista_da_lo_mismo_en_ambas():
    for k in range(1, 9):
        assert passk(8, 8, k) == pass_at_k(8, 8, k) == 1.0
        assert passk(8, 0, k) == pass_at_k(8, 0, k) == 0.0


# ------------------------------------------------------------- validaciones


@pytest.mark.parametrize(("n", "c", "k"), [(0, 0, 1), (8, 9, 1), (8, -1, 1), (8, 4, 0), (8, 4, 9)])
def test_los_argumentos_fuera_de_rango_se_rechazan(n, c, k):
    with pytest.raises(ValueError):
        passk(n, c, k)


# --------------------------------------------------------------- agregados


def test_el_agregado_es_la_media_de_los_pass_k_por_caso():
    # Y no el pass^k de los éxitos agrupados: agrupar trataría casos fáciles y difíciles
    # como una sola población.
    exitos = [8, 4, 0]

    por_caso = passk_por_caso(exitos, n=8, k=2)
    assert por_caso == [1.0, pytest.approx(float(Fraction(6, 28))), 0.0]
    assert passk_agregado(exitos, n=8, k=2) == pytest.approx(sum(por_caso) / 3)


def test_el_agregado_difiere_de_agrupar_los_exitos():
    exitos = [8, 0]  # un caso siempre acierta, el otro nunca

    agregado = passk_agregado(exitos, n=8, k=4)
    agrupado = passk(16, 8, 4)  # como si fuera un solo caso con 16 ejecuciones

    assert agregado == pytest.approx(0.5)
    assert agrupado != pytest.approx(agregado)


def test_la_curva_cubre_todos_los_k_pedidos():
    curva = curva_passk([8, 6, 4], n=8, ks=[1, 2, 4, 8])

    assert list(curva) == [1, 2, 4, 8]
    assert curva[1] > curva[8]


def test_la_curva_decrece_con_k():
    curva = curva_passk([7, 6, 5, 8], n=8, ks=[1, 2, 4, 8])
    valores = [curva[k] for k in (1, 2, 4, 8)]

    assert valores == sorted(valores, reverse=True)


def test_sin_casos_no_hay_agregado():
    with pytest.raises(ValueError, match="no hay casos"):
        passk_agregado([], n=8, k=1)


def test_la_matriz_se_convierte_en_exitos_por_caso():
    matriz = [[1, 0, 1, 1], [0, 0, 0, 0], [True, True, False, True]]

    assert exitos_desde_matriz(matriz) == [3, 0, 3]


def test_una_matriz_completa_da_pass_k_igual_a_uno():
    matriz = [[1] * 8 for _ in range(5)]

    assert passk_agregado(exitos_desde_matriz(matriz), n=8, k=8) == 1.0


def test_un_k_mayor_que_n_no_esta_definido():
    # Un piloto con n reducido no puede reportar pass^8: el análisis debe descartar esos k
    # antes de gastar las ejecuciones, no reventar después.
    with pytest.raises(ValueError, match="k debe estar entre"):
        passk(2, 2, 4)


# ------------------ una avería de infraestructura no es un fallo del agente


@pytest.mark.parametrize(
    "mensaje",
    [
        "You have reached your specified API usage limits",
        "Your credit balance is too low",
        "authentication_error: invalid x-api-key",
        "permission denied for this workspace",
    ],
)
def test_los_errores_de_infraestructura_se_reconocen_como_fatales(mensaje):
    # Registrarlos como `exito = 0` produciría un pass^k de cero que parece un resultado y
    # es una avería de facturación. Ocurrió: 860 de 1.008 ejecuciones fallaron por límite de
    # gasto y el JSON quedó con dual_llm y cte en 0,000.
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from run_e1 import es_fatal

    assert es_fatal(RuntimeError(mensaje))


def test_un_fallo_del_agente_no_es_fatal():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from run_e1 import es_fatal

    assert not es_fatal(ValueError("el plan no era JSON válido"))
    assert not es_fatal(TimeoutError("la petición tardó demasiado"))
