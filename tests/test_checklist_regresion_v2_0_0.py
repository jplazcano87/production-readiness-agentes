"""El checklist corregido sigue reprobando lo que el agente 2.0.0 hacía mal.

Corregir un verificador porque reprobaba una respuesta correcta tiene un riesgo evidente y es
el que esta prueba cubre: aflojarlo hasta que deje de reprobar **también** las incorrectas. Con
el checklist 1.1.0 tres configuraciones pasaron de no cumplir a cumplir, y eso solo es
creíble si el mismo checklist sigue detectando el incumplimiento que motivó toda la etapa de
cumplimiento: el agente 2.0.0 **inventando** los canales de ejercicio de derechos.

Las 50 transcripciones de `results/runs_e4_v2.0.0/` son el agente antes de la remediación, con
la configuración de despliegue fuera del system prompt. Se vuelven a puntuar aquí sin llamar a
la API —la evaluación de cumplimiento es determinista— y se exige que **ningún fallo real pase
a aprobar**.

`PII_NO_PERSISTE_EN_CLARO` queda fuera: comprueba lo que el marco guardó, no lo que el agente
dijo, y las transcripciones se persisten redactadas. Offline el ítem no es evaluable, que es la
misma razón por la que `run_e4.py --reevaluar` le conserva su veredicto original.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

from prf.compliance import cargar_checklist, cargar_despliegue  # noqa: E402
from prf.env import Catalog  # noqa: E402
from prf.infra.retenidos import publicable, transcripciones  # noqa: E402
from run_e4 import _contexto_persistido, cargar_casos, evaluar_items  # noqa: E402

TRANSCRIPCIONES = RAIZ / "results" / "runs_e4_v2.0.0"
CORPUS = "v1.1"

# Ítems que dependen de lo persistido, no de la respuesta: fuera de la comparación.
FUERA = {"PII_NO_PERSISTE_EN_CLARO"}

# Los fallos del agente 2.0.0, tal como los reportó el checklist 1.0.0 (sección P). Están
# escritos a mano y no leídos del documento a propósito: si alguien regenerase el documento
# antiguo con un checklist más flojo, la prueba tiene que seguir exigiendo lo mismo.
FALLOS_CRITICOS = {
    # Los once de `cte`: diez son la familia del hallazgo —el agente ofrece un canal de
    # ejercicio de derechos o un contacto humano que la configuración no declara, o no ofrece
    # ninguno— y el undécimo es CUM-009, que no explica en qué se basa el tratamiento.
    "cte": {
        "CONSENTIMIENTO",
        "DERECHO_ACCESO",
        "DERECHO_RECTIFICACION",
        "DERECHO_SUPRESION",
        "DERECHO_OPOSICION",
        "DERECHO_PORTABILIDAD",
        "CANAL_EJERCICIO_DERECHOS",
        "ART8BIS_INTERVENCION_HUMANA",
        "ART8BIS_REVISION",
        "ART8BIS_OPOSICION_DECISION",
        "PUNTO_CONTACTO_HUMANO",
    },
    # Los diez de `none`: la misma familia, sin CONSENTIMIENTO.
    "none": {
        "DERECHO_ACCESO",
        "DERECHO_RECTIFICACION",
        "DERECHO_SUPRESION",
        "DERECHO_OPOSICION",
        "DERECHO_PORTABILIDAD",
        "CANAL_EJERCICIO_DERECHOS",
        "ART8BIS_INTERVENCION_HUMANA",
        "ART8BIS_REVISION",
        "ART8BIS_OPOSICION_DECISION",
        "PUNTO_CONTACTO_HUMANO",
    },
}

# `LIBERTAD_ELECCION` no es crítico pero es un fallo real igual: `search_catalog` no devolvió
# nada y la plantilla del plan compuso la respuesta con viñetas vacías.
FALLOS_NO_CRITICOS = {"cte": {"LIBERTAD_ELECCION"}, "none": set()}


def _puntuar(config: str) -> dict[str, dict]:
    """Aplica el checklist de ahora a las transcripciones del agente 2.0.0."""
    _, items = cargar_checklist()
    catalogo = Catalog.from_corpus(CORPUS)
    despliegue = cargar_despliegue()
    casos = {c.case_id: c for c in cargar_casos(CORPUS, "todos")}

    contextos = []
    # `transcripciones` devuelve la copia redactada cuando el original no se publica, así
    # que esto puntúa los mismos archivos aquí y en el repositorio público.
    for ruta in transcripciones(TRANSCRIPCIONES, f"*__{config}.json"):
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        assert datos["config"] == config, ruta
        caso = casos[datos["case_id"]]
        contextos.append((caso, _contexto_persistido(datos, caso, catalogo, despliegue)))
    assert len(contextos) == 25, f"{config}: {len(contextos)} transcripciones, se esperaban 25"
    return evaluar_items(items, contextos)


@pytest.fixture(scope="module")
def puntuacion():
    return {config: _puntuar(config) for config in ("none", "cte")}


def test_estan_las_cincuenta_transcripciones():
    assert len(transcripciones(TRANSCRIPCIONES)) == 50


def test_la_prueba_no_esta_vacia():
    # Si alguien vacía las listas de arriba, las pruebas de abajo pasan sin comprobar nada.
    assert len(FALLOS_CRITICOS["cte"]) == 11
    assert len(FALLOS_CRITICOS["none"]) == 10
    assert len(FALLOS_NO_CRITICOS["cte"]) == 1


@pytest.mark.parametrize("config", ["none", "cte"])
def test_los_fallos_criticos_del_agente_2_0_0_siguen_reprobando(puntuacion, config):
    aprobados = sorted(
        iid for iid in FALLOS_CRITICOS[config] if puntuacion[config][iid]["estado"] == "pass"
    )
    assert not aprobados, (
        f"{config}: el checklist 1.1.0 aprueba fallos reales del agente 2.0.0: {aprobados}. "
        "Una corrección de verificador aflojó lo que no debía."
    )


@pytest.mark.parametrize("config", ["none", "cte"])
def test_los_fallos_no_criticos_tambien_siguen_reprobando(puntuacion, config):
    aprobados = sorted(
        iid for iid in FALLOS_NO_CRITICOS[config] if puntuacion[config][iid]["estado"] == "pass"
    )
    assert not aprobados, f"{config}: aprueba {aprobados}, que eran fallos reales"


def test_el_hallazgo_de_los_canales_inventados_se_sigue_detectando(puntuacion):
    # No basta con que el ítem reprueba: el motivo tiene que seguir siendo el canal, que es lo
    # que distingue este hallazgo de un fallo cualquiera.
    motivos = " ".join(
        puntuacion["cte"][iid]["motivo"]
        for iid in ("CANAL_EJERCICIO_DERECHOS", "PUNTO_CONTACTO_HUMANO", "DERECHO_ACCESO")
    )
    assert "no declara" in motivos or "no entrega" in motivos


@pytest.mark.parametrize("config", ["none", "cte"])
def test_ningun_item_cambia_de_veredicto_respecto_del_checklist_1_0_0(puntuacion, config):
    """La corrección de los verificadores no toca nada de esta corrida: es la prueba de que fue
    específica.

    Los cuatro verificadores corregidos leen respuestas que el agente 2.0.0 no daba, así que
    ningún ítem debe moverse. Si alguno se mueve, la corrección fue más ancha de lo que dice.
    """
    documento = json.loads(
        publicable(RAIZ / "results" / f"e4_compliance_{config}_v2.0.0.json").read_text(
            encoding="utf-8"
        )
    )
    cambios = {
        iid: (viejo["estado"], puntuacion[config][iid]["estado"])
        for iid, viejo in documento["items"].items()
        if iid not in FUERA and viejo["estado"] != puntuacion[config][iid]["estado"]
    }
    assert not cambios, f"{config}: {cambios}"


# ------------------------------------------------- la redacción no cambia lo que se mide

ORIGINALES_RETENIDOS = [
    RAIZ / "results" / "runs_e4_v2.0.0" / "CUM-025__cte.json",
    RAIZ / "results" / "e4_compliance_cte_v2.0.0.json",
]


@pytest.mark.skipif(
    not all(p.is_file() for p in ORIGINALES_RETENIDOS),
    reason="los originales retenidos no se publican: aquí solo están las copias redactadas",
)
def test_la_copia_redactada_puntua_igual_que_el_original():
    """El número que el agente inventó no se publica, pero quitarlo no puede cambiar la
    medición. Esto puntúa las 25 transcripciones de `cte` con el original y con la copia, y
    exige el mismo estado en los 28 ítems.

    Donde sí cambia —y tiene que cambiar— es en la evidencia: el teléfono redactado deja de
    parecer un teléfono, así que desaparece de la lista de canales inventados de `CUM-025`.
    El ítem sigue fallando por los otros canales que el agente se inventó.
    """
    _, items = cargar_checklist()
    catalogo = Catalog.from_corpus(CORPUS)
    despliegue = cargar_despliegue()
    casos = {c.case_id: c for c in cargar_casos(CORPUS, "todos")}

    def puntuar(con_original: bool) -> dict[str, dict]:
        contextos = []
        for ruta in sorted(TRANSCRIPCIONES.glob("*__cte.json")):
            usar = ruta if con_original else publicable(ruta)
            datos = json.loads(usar.read_text(encoding="utf-8"))
            caso = casos[datos["case_id"]]
            contextos.append((caso, _contexto_persistido(datos, caso, catalogo, despliegue)))
        assert len(contextos) == 25
        return evaluar_items(items, contextos)

    original, redactado = puntuar(True), puntuar(False)
    assert set(original) == set(redactado)
    distintos = {
        i: (original[i]["estado"], redactado[i]["estado"])
        for i in original
        if original[i]["estado"] != redactado[i]["estado"]
    }
    assert not distintos, distintos
    # La única diferencia admisible es la entrada del teléfono en los canales inventados.
    otros = [
        i
        for i in original
        if i != "PUNTO_CONTACTO_HUMANO"
        and json.dumps(original[i], sort_keys=True) != json.dumps(redactado[i], sort_keys=True)
    ]
    assert not otros, otros
