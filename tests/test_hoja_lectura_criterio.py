"""La hoja de lectura del criterio 1.2.0 no filtra nada que ancle a quien lee.

Mismo propósito que `tests/test_e6_anotacion.py` para el instrumento de E6: se comprueba sobre
el HTML generado, no sobre la intención del generador. Lo que viene de las ejecuciones y del
corpus va marcado con la clase `ej`; fuera de eso, la hoja no puede nombrar configuración,
modelo, fuente ni veredicto. Y dentro tampoco pueden aparecer el turno del planificador de
Code-Then-Execute ni el objeto de la cuarentena.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

from e2_hoja_lectura_criterio import (  # noqa: E402
    SEMILLA_BARAJADO,
    _corpus,
    a_leer,
    barajar,
    ficha,
    generar,
)
from prf.env import Catalog  # noqa: E402


@pytest.fixture(scope="module")
def generado():
    return generar()


@pytest.fixture(scope="module")
def hoja(generado):
    return generado[0]


@pytest.fixture(scope="module")
def correspondencia(generado):
    return list(csv.DictReader(io.StringIO(generado[2])))


@pytest.fixture(scope="module")
def fichas_y_configs():
    casos, resenas = _corpus()
    catalogo = Catalog.from_corpus("v1.2")
    salida = []
    for item in barajar(a_leer()):
        registro = json.loads((RAIZ / item["ruta"]).read_text(encoding="utf-8"))
        salida.append((ficha(item, casos, resenas, catalogo), registro))
    return salida


def esqueleto(hoja: str) -> str:
    """La hoja sin el texto que viene de las ejecuciones y del corpus."""
    return re.sub(r'<(\w+) class="ej[^"]*">.*?</\1>', "", hoja, flags=re.DOTALL)


# ------------------------------------------------------------------- el conjunto


def test_son_76_con_id_anonimo_y_en_orden_reproducible(correspondencia):
    assert [f["id"] for f in correspondencia] == [f"A{i:02d}" for i in range(1, 77)]
    fuentes = [f["fuente"] for f in correspondencia]
    assert fuentes.count("auditoria_fn") == 40 and fuentes.count("holdout") == 36
    assert barajar(a_leer()) == barajar(a_leer())
    assert SEMILLA_BARAJADO == 20261018


def test_la_hoja_es_determinista(generado):
    assert generar() == generado


def test_las_anotaciones_salen_vacias(generado):
    filas = list(csv.DictReader(io.StringIO(generado[1])))
    assert list(filas[0]) == ["id", "logro", "canal", "nota"]
    assert len(filas) == 76
    assert all(f["logro"] == f["canal"] == f["nota"] == "" for f in filas)


# ------------------------------------------------------------------- ciegamiento


def test_ningun_run_id_ni_case_id_en_la_hoja(hoja, correspondencia):
    for fila in correspondencia:
        assert fila["run_id"] not in hoja, fila["id"]
        assert fila["run_id"].split("__")[0] not in hoja, fila["id"]


def test_el_esqueleto_no_nombra_configuracion_modelo_fuente_ni_veredicto(hoja):
    resto = esqueleto(hoja).lower()
    for palabra in (
        "none",
        "prompt_only",
        "dual_llm",
        "cte",
        "code-then-execute",
        "sonnet",
        "haiku",
        "claude",
        "holdout",
        "hold-out",
        "auditor",
        "compuerta",
        "piloto",
        "veredicto",
        "criterio",
        "éxito",
        "exito",
        "fracaso",
        "planificador",
        "cuarentena",
        "corrida",
    ):
        assert not re.search(rf"\b{re.escape(palabra)}", resto), palabra


def test_el_centinela_no_delata_la_particion(hoja):
    assert not re.search(r"PRF-(?:DEV|TEST)", hoja)


def test_la_correspondencia_va_fuera_de_la_hoja(hoja):
    assert "auditoria_fn" not in hoja and "e2_security" not in hoja


# ------------------------------------------- Code-Then-Execute y la cuarentena


def test_no_aparece_el_turno_del_planificador(hoja, fichas_y_configs):
    con_plan = 0
    for _, registro in fichas_y_configs:
        for turno in registro["ejecucion"]["transcripcion"]:
            if turno["rol"] == "planificador":
                con_plan += 1
                # El plan es JSON con los pasos; su primera línea larga no puede estar.
                linea = max(turno["texto"].splitlines(), key=len).strip()
                assert linea and linea not in hoja
    assert con_plan, "la hoja debe traer ejecuciones de Code-Then-Execute"
    roles = set(re.findall(r'<span class="rol">([^<]*):</span>', hoja))
    assert roles == {"Cliente", "Agente"}


def test_no_aparece_el_objeto_de_la_cuarentena_ni_ningun_resultado(hoja):
    for clave in ("rating_promedio", "menciona_defectos", '"pros"', '"contras"', "&quot;pros"):
        assert clave not in hoja, clave
    # Ni el resultado de una búsqueda: ningún campo de producto del catálogo.
    for clave in ("price_clp", "avg_rating", "&quot;stock&quot;"):
        assert clave not in hoja, clave


def test_las_acciones_tienen_el_mismo_formato_en_las_cuatro(fichas_y_configs):
    por_config: dict[str, set[tuple[str, ...]]] = {}
    for f, registro in fichas_y_configs:
        for accion in f.acciones:
            por_config.setdefault(registro["config"], set()).add(tuple(sorted(accion)))
            assert accion["estado"] in ("se completó", "no se completó")
    assert "cte" in por_config, "alguna ejecución de Code-Then-Execute debe traer acciones"
    formatos = set().union(*por_config.values())
    assert formatos == {("argumentos", "estado", "herramienta")}


def test_las_acciones_de_cte_son_los_pasos_que_ejecuto_el_interprete(fichas_y_configs):
    for f, registro in fichas_y_configs:
        if registro["config"] != "cte":
            continue
        assert [a["herramienta"] for a in f.acciones] == [
            ll["nombre"] for ll in registro["ejecucion"]["llamadas"]
        ]


def test_lo_que_la_carga_pedia_esta_en_cada_ficha(fichas_y_configs):
    for f, _ in fichas_y_configs:
        assert f.carga.strip(), f.id
        assert f.turnos and f.turnos[0][0] == "Cliente", f.id
