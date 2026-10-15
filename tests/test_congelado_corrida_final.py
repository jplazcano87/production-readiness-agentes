"""Mientras el tag `corrida-final-3.0.0` apunte al HEAD, nada de esto puede cambiar.

Las corridas finales cuestan cerca de USD 70 y solo son comparables entre sí si el agente, el
evaluador y el corpus son los mismos en todas. Esta prueba es la que impide que un cambio
inocente —una palabra del prompt, un umbral del evaluador, una regeneración del corpus— se
cuele entre dos corridas y las vuelva incomparables sin que nadie lo advierta.

**Solo aplica si el tag apunta exactamente al HEAD.** Antes de tagear no hay nada que
congelar, y después de mover el tag a conciencia lo que hay que actualizar es
`configs/congelado_corrida_final.json`, no esta prueba.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from prf.agent import AGENT_VERSION
from prf.agent.huellas import huellas
from prf.compliance import cargar_checklist, cargar_despliegue
from prf.env.evaluator import EVALUATOR_VERSION
from prf.infra import paths
from prf.infra.config import load_experiments

REGISTRO = paths.configs / "congelado_corrida_final.json"


def _git(*args: str) -> str | None:
    try:
        salida = subprocess.run(
            ["git", *args], capture_output=True, text=True, cwd=paths.root, check=False
        )
    except OSError:  # pragma: no cover - sin git instalado
        return None
    return salida.stdout.strip() if salida.returncode == 0 else None


@pytest.fixture(scope="module")
def congelado() -> dict:
    if not REGISTRO.is_file():
        pytest.skip("no hay registro de congelación")
    return json.loads(REGISTRO.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def tag_en_head(congelado) -> bool:
    head = _git("rev-parse", "HEAD")
    tag = _git("rev-list", "-n", "1", congelado["tag"])
    return bool(head) and head == tag


def _exigir(tag_en_head: bool) -> None:
    if not tag_en_head:
        pytest.skip("el tag de corrida final no apunta al HEAD: no hay nada congelado que proteger")


def test_el_registro_describe_el_estado_actual_o_el_tag_no_esta_en_head(congelado, tag_en_head):
    # Sanidad del propio registro: si existe, sus campos tienen que estar completos.
    for clave in (
        "agent_version",
        "evaluator_version",
        "corpus_version",
        "corpus_hash",
        "corpus_version_en_resultados",
        "corpus_hash_en_resultados",
        "checklist_version",
    ):
        assert congelado.get(clave), clave
    assert congelado["huellas_prompt"]


def test_las_versiones_no_cambian(congelado, tag_en_head):
    _exigir(tag_en_head)

    assert AGENT_VERSION == congelado["agent_version"], "cambió el agente"
    assert EVALUATOR_VERSION == congelado["evaluator_version"], "cambió el evaluador"
    assert load_experiments()["corpus_version"] == congelado["corpus_version"]


def test_el_corpus_sigue_siendo_el_mismo(congelado, tag_en_head):
    _exigir(tag_en_head)
    manifest = json.loads(
        (paths.corpus_version(congelado["corpus_version"]) / "MANIFEST.json").read_text(
            encoding="utf-8"
        )
    )

    assert manifest["corpus_hash"] == congelado["corpus_hash"], "el corpus se regeneró"


def test_los_prompts_siguen_siendo_los_mismos(congelado, tag_en_head):
    _exigir(tag_en_head)
    actuales = huellas(cargar_despliegue())

    assert actuales == congelado["huellas_prompt"], (
        "cambió el system prompt de alguna configuración: las corridas finales dejarían de "
        "ser del mismo sistema"
    )


def test_la_declaracion_de_despliegue_no_cambia(congelado, tag_en_head):
    # El bloque de cumplimiento se genera desde ella, así que moverla mueve los cuatro prompts.
    _exigir(tag_en_head)

    assert cargar_despliegue()["version"] == congelado["despliegue_version"]


# ------------------------------------------------------------------- guardia permanente
#
# Las cuatro pruebas de arriba se saltan cuando el tag no apunta al HEAD, y ese es el momento
# en que más falta hacen: E5 consolida resultados que se midieron con un código que ya no es
# el del árbol, y nada lo advertiría. La guardia de abajo **no se salta nunca**. No exige que
# el árbol esté congelado: exige que, si cambió, `configs/congelado_corrida_final.json` lo
# diga, porque ese archivo es lo que el veredicto declara como versión de lo que juzga.


def test_el_registro_de_congelacion_describe_el_arbol_de_ahora(congelado):
    actual = {
        "agent_version": AGENT_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "corpus_version": load_experiments()["corpus_version"],
        "checklist_version": cargar_checklist()[0],
        "huellas_prompt": huellas(cargar_despliegue()),
    }
    registrado = {clave: congelado[clave] for clave in actual}
    assert actual == registrado, (
        "el árbol ya no coincide con el registro de la corrida final. Si el cambio es "
        "deliberado, actualiza configs/congelado_corrida_final.json y repite las corridas que "
        "afecte; si no lo es, revísalo antes de volver a consolidar el veredicto."
    )


@pytest.mark.parametrize("campo", ["corpus_version", "corpus_version_en_resultados"])
def test_el_corpus_del_registro_no_se_regenero(congelado, campo):
    manifest = json.loads(
        (paths.corpus_version(congelado[campo]) / "MANIFEST.json").read_text(encoding="utf-8")
    )
    sufijo = "" if campo == "corpus_version" else "_en_resultados"
    assert manifest["corpus_hash"] == congelado[f"corpus_hash{sufijo}"], campo


def test_el_corpus_del_arbol_hereda_del_corpus_de_los_resultados(congelado):
    """Lo que legitima tener el árbol en una versión y los resultados en otra.

    El registro declara que el corpus del árbol hereda del de los resultados byte a byte, y
    esa declaración es lo único que permite seguir consolidando corridas medidas con la
    versión anterior. Así que no se cree: se comparan los bytes.

    Si alguna vez el corpus nuevo deja de ser incremental —porque se regeneró el catálogo, o
    se reescribieron las reseñas— esta prueba falla y lo que hay que hacer es repetir las
    corridas, no tocar la prueba.
    """
    arbol = paths.corpus_version(congelado["corpus_version"])
    resultados = paths.corpus_version(congelado["corpus_version_en_resultados"])
    if arbol == resultados:
        pytest.skip("el árbol y los resultados están en la misma versión de corpus")

    for nombre in congelado["corpus_hereda_byte_a_byte"]:
        assert (arbol / nombre).read_bytes() == (resultados / nombre).read_bytes(), nombre

    # Los archivos que crecen se heredan **por prefijo**: sus primeras N líneas son las que
    # las corridas de aquella versión midieron, y los casos nuevos van detrás.
    for nombre, heredadas in congelado["corpus_hereda_por_prefijo"].items():
        nuevas = (arbol / nombre).read_text(encoding="utf-8").splitlines()
        viejas = (resultados / nombre).read_text(encoding="utf-8").splitlines()
        assert len(viejas) == heredadas, (
            f"{nombre}: el corpus de los resultados trae {len(viejas)} líneas y el registro "
            f"declara {heredadas}"
        )
        assert nuevas[:heredadas] == viejas, (
            f"{nombre}: los casos heredados cambiaron, así que las corridas ya medidas "
            "dejarían de medir los mismos casos"
        )


def test_los_resultados_declaran_las_versiones_del_registro(congelado):
    """Lo que E5 consolida se midió con lo que el registro congela.

    Es la comprobación que cierra el círculo: no basta con que el árbol coincida con el
    registro si los JSON que el veredicto lee vienen de otra versión.
    """
    esperado = congelado["agent_versions_en_resultados"]
    for nombre, agente in esperado.items():
        ruta = paths.results / f"{nombre}.json"
        if nombre == "e4_compliance":
            ruta = paths.results / "e4_compliance_cte.json"
        if not ruta.is_file():  # pragma: no cover
            pytest.skip(f"falta {nombre}")
        metadata = json.loads(ruta.read_text(encoding="utf-8"))["metadata"]
        # El agente puede diferir entre corridas —E2 con Sonnet va en 3.0.0 y E3 en 3.0.1, y el
        # registro dice por qué— pero el corpus no: si cambiara, dejarían de ser comparables.
        assert metadata["agent_version"] == agente, nombre
        # El corpus del árbol puede ir por delante del de los resultados: las versiones son
        # incrementales. Lo que no puede es ir por otro lado, y de eso se encarga la prueba
        # de herencia de abajo.
        assert metadata["corpus_version"] == congelado["corpus_version_en_resultados"], nombre
        assert metadata["corpus_hash"] == congelado["corpus_hash_en_resultados"], nombre
