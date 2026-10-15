"""Qué configuración lleva las cláusulas que niegan cada objetivo de ataque (3.0.0).

Hasta 2.2.0 vivían en `SISTEMA_BASE` y por tanto **las cuatro** configuraciones las tenían,
incluida `none`. Cada una prohíbe por adelantado justo lo que un objetivo de ataque del
corpus pide, así que `none` no era una línea base sin protección y E2 midió un ASR de cero en
las cuatro. Estas pruebas fijan la separación para que no se deshaga sin querer.
"""

from __future__ import annotations

import pytest

from prf.agent.configuraciones import CONFIGURACIONES
from prf.agent.prompts import CLAUSULAS_DEFENSIVAS, SISTEMA_BASE, sistema_agente
from prf.compliance import cargar_despliegue

# Un fragmento por objetivo de ataque del corpus. La correspondencia es lo que hace la
# prueba informativa: no comprueba que falte un texto, sino que ninguna configuración salvo
# `prompt_only` niegue de antemano lo que el ataque va a pedir.
POR_OBJETIVO = {
    "unauthorized_promise": "No prometes rebajas ni condiciones especiales",
    "out_of_domain": "Si te piden algo ajeno a la compra en esta tienda",
    "exfiltration": "nunca los envías a terceros",
    "task_hijack": "No inventas precios, descuentos, promociones",
}


def prompt_de(nombre: str) -> str:
    config = CONFIGURACIONES[nombre]
    return sistema_agente(
        advierte=config.advierte_en_prompt,
        cuarentena=config.usa_cuarentena,
        despliegue=cargar_despliegue(),
        clausulas_defensivas=config.clausulas_defensivas,
    )


def test_las_clausulas_cubren_los_cuatro_objetivos_de_ataque():
    for objetivo, fragmento in POR_OBJETIVO.items():
        assert fragmento in CLAUSULAS_DEFENSIVAS, objetivo


def test_el_prompt_base_ya_no_las_contiene():
    for objetivo, fragmento in POR_OBJETIVO.items():
        assert fragmento not in SISTEMA_BASE, objetivo


@pytest.mark.parametrize("nombre", ["none", "dual_llm", "cte"])
@pytest.mark.parametrize("objetivo", sorted(POR_OBJETIVO))
def test_ninguna_configuracion_salvo_prompt_only_niega_el_objetivo(nombre, objetivo):
    assert POR_OBJETIVO[objetivo] not in prompt_de(nombre), (
        f"{nombre} niega {objetivo} en su prompt: no es una medición de su mecanismo"
    )


@pytest.mark.parametrize("objetivo", sorted(POR_OBJETIVO))
def test_prompt_only_si_las_lleva(objetivo):
    assert POR_OBJETIVO[objetivo] in prompt_de("prompt_only")


def test_solo_prompt_only_las_declara():
    con = [n for n, c in CONFIGURACIONES.items() if c.clausulas_defensivas]
    assert con == ["prompt_only"]


# ---------------------------------------------------- lo que NO se mueve del prompt base


def test_la_declaracion_de_ser_ia_se_queda_en_el_base():
    # Es una obligación de cumplimiento (TRANSPARENCIA_IA), no una defensa contra un ataque:
    # sacarla del base rompería E4 sin decir nada sobre seguridad.
    for nombre in CONFIGURACIONES:
        assert "asistente de inteligencia artificial" in prompt_de(nombre), nombre


def test_el_bloque_de_cumplimiento_sigue_en_las_cuatro():
    # Nace de E4 y no cubre ningún objetivo de ataque, así que se queda.
    canal = cargar_despliegue()["canal_ejercicio_derechos"]["correo"]
    for nombre in CONFIGURACIONES:
        assert canal in prompt_de(nombre), nombre
