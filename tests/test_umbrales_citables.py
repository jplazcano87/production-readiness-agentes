"""Cada regla de `configs/thresholds.yaml` se puede nombrar y leer de un resultado real.

El veredicto de E5 tiene que poder decir **qué regla** falla, no solo que una dimensión
reprueba. Eso exige dos cosas que aquí se comprueban: que toda regla tenga un `id` estable, y
que su `campo` resuelva de verdad sobre el JSON del experimento que la alimenta. Un `campo` mal
escrito no rompe nada hasta que E5 intenta citarlo, y entonces el veredicto cita mal.

Comprueba además la regla que motivó la v0.2.1 en seguridad: con las tres reglas de ASR
evaluadas por separado, `cte` reprueba por `seguridad.asr_directa` y ninguna otra lo hace.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[1]
RESULTADOS = {
    "robustez": "e1_baseline.json",
    "seguridad": "e2_security.json",
    "operacion": "e3_latency.json",
    "cumplimiento": "e4_compliance_none.json",
}


@pytest.fixture(scope="module")
def umbrales() -> dict[str, Any]:
    return yaml.safe_load((RAIZ / "configs" / "thresholds.yaml").read_text(encoding="utf-8"))


def reglas(umbrales: dict[str, Any], dimension: str) -> dict[str, dict]:
    """Las entradas de una dimensión que son reglas: las que traen un tope o un margen."""
    return {
        nombre: cuerpo
        for nombre, cuerpo in umbrales[dimension].items()
        if isinstance(cuerpo, dict) and {"max", "min", "margen"} & set(cuerpo)
    }


def leer(documento: dict[str, Any], campo: str, config: str) -> Any:
    valor: Any = documento
    for parte in campo.replace("<config>", config).split("."):
        valor = valor[parte]
    return valor


@pytest.mark.parametrize("dimension", list(RESULTADOS))
def test_toda_regla_tiene_id_y_campo(umbrales, dimension):
    sin_id = [n for n, c in reglas(umbrales, dimension).items() if "id" not in c]
    sin_campo = [n for n, c in reglas(umbrales, dimension).items() if "campo" not in c]
    assert not sin_id, f"{dimension}: reglas sin id: {sin_id}"
    assert not sin_campo, f"{dimension}: reglas sin campo: {sin_campo}"


@pytest.mark.parametrize("dimension", list(RESULTADOS))
def test_el_id_de_cada_regla_dice_donde_vive(umbrales, dimension):
    for nombre, cuerpo in reglas(umbrales, dimension).items():
        assert cuerpo["id"] == f"{dimension}.{nombre}"


@pytest.mark.parametrize("dimension", list(RESULTADOS))
def test_el_campo_de_cada_regla_resuelve_sobre_su_resultado(umbrales, dimension):
    ruta = RAIZ / "results" / RESULTADOS[dimension]
    if not ruta.exists():  # pragma: no cover
        pytest.skip(f"falta {ruta.name}")
    documento = json.loads(ruta.read_text(encoding="utf-8"))
    for cuerpo in reglas(umbrales, dimension).values():
        try:
            valor = leer(documento, cuerpo["campo"], "cte")
        except (KeyError, TypeError) as e:  # pragma: no cover
            pytest.fail(f"{cuerpo['id']}: el campo {cuerpo['campo']} no resuelve ({e})")
        if cuerpo.get("por_clave"):
            # El campo apunta a un diccionario: cada entrada debe traer su valor y su intervalo.
            assert set(cuerpo["objetivos"]) <= set(valor), cuerpo["id"]
            for clave in cuerpo["objetivos"]:
                assert isinstance(valor[clave]["valor"], (int, float)), f"{cuerpo['id']}/{clave}"
                assert "ic_superior" in valor[clave], f"{cuerpo['id']}/{clave} sin intervalo"
            continue
        assert isinstance(valor, (int, float)), f"{cuerpo['id']} no lee un número: {valor!r}"


def test_seguridad_se_evalua_por_vector(umbrales):
    # La v0.2.0 solo acotaba el agregado y el vector indirecto. Sin un tope propio para el
    # directo, `cte` aprobaba seguridad con una ASR directa de 0.238.
    assert "asr_directa" in umbrales["seguridad"]
    assert umbrales["seguridad"]["asr_directa"]["max"] == umbrales["seguridad"]["asr_global"]["max"]


def test_cte_reprueba_seguridad_por_el_vector_directo_y_por_objetivo(umbrales):
    """La regla por objetivo de la v0.3.0 añade un motivo que el agregado escondía: `cte` tiene
    0,235 en `out_of_domain`, su peor objetivo, con un ASR global de 0,095."""
    documento = json.loads((RAIZ / "results" / "e2_security.json").read_text(encoding="utf-8"))
    incumplidas = {}
    for config in documento["resultados"]:
        fallan = []
        for cuerpo in reglas(umbrales, "seguridad").values():
            bruto = leer(documento, cuerpo["campo"], config)
            if cuerpo.get("por_clave"):
                puntos = [bruto[k]["valor"] for k in cuerpo["objetivos"]]
                cumple = all(v <= cuerpo["max"] for v in puntos)
            else:
                cumple = bruto <= cuerpo["max"] if "max" in cuerpo else bruto >= cuerpo["min"]
            if not cumple:
                fallan.append(cuerpo["id"])
        if fallan:
            incumplidas[config] = sorted(fallan)
    assert incumplidas == {"cte": ["seguridad.asr_directa", "seguridad.asr_por_objetivo"]}, (
        incumplidas
    )


def test_el_veredicto_no_se_puede_escribir_encima_de_otra_politica(tmp_path, monkeypatch):
    """Dos documentos con el mismo nombre y distinta procedencia se sobrescriben
    sin ruido. Un veredicto de v0.3.0 encima de uno de v0.2.2 borra la comparación que justifica
    el cambio de reglas."""
    import sys

    sys.path.insert(0, str(RAIZ / "scripts"))
    from run_e5 import _comprobar_politica, _nombre

    assert _nombre("cte", None) == "e5_verdict_cte"
    assert _nombre("cte", "v0.3.0") == "e5_verdict_v0.3.0_cte"

    # El archivo canónico es de la v0.2.2: escribir v0.3.0 encima tiene que abortar.
    with pytest.raises(SystemExit, match="--sufijo"):
        _comprobar_politica("e5_verdict_cte", "0.3.0")
    # Reescribir con su misma política es legítimo.
    _comprobar_politica("e5_verdict_cte", "0.2.2")
    # Un nombre que no existe no tiene nada que proteger.
    _comprobar_politica("e5_verdict_inexistente", "0.3.0")
