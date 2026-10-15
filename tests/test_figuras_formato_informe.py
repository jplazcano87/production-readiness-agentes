"""Las cinco figuras cumplen el formato del informe (APA).

Las reglas no son de gusto: cada una resuelve un problema concreto al maquetar.

- **Sin título ni nota dentro de la imagen.** En APA el título y la nota van en el documento,
  no en el PNG. Con el título incrustado aparece dos veces, y la nota dentro de la imagen no se
  puede corregir sin regenerar la figura.
- **Coma decimal.** El documento escribe 0,05 y matplotlib escribe 0.05. Mezclarlas obliga al
  lector a decidir en cada cifra cuál está leyendo.
- **Sin rayas ni backticks.** La raya larga y el acento grave son convenciones de este
  repositorio, no del informe.
- **Terminología del informe**: «Desvío de la recomendación», no «Secuestro de la tarea».

Se comprueba sobre los objetos de matplotlib y no sobre el PNG: lo que importa es el texto que
la figura dibuja, y leerlo del objeto lo hace verificable sin OCR.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")

import make_figures as mf  # noqa: E402
from prf.infra.config import load_experiments  # noqa: E402
from prf.infra.figuras import ANCHO_PULGADAS, DPI, aplicar_estilo  # noqa: E402

RAYA = "—"


def _leer(nombre: str) -> dict | None:
    ruta = RAIZ / "results" / f"{nombre}.json"
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.is_file() else None


@pytest.fixture(scope="module")
def figuras(tmp_path_factory) -> dict:
    """Las cinco, dibujadas de verdad, capturadas antes de que `guardar` las cierre."""
    version = load_experiments()["corpus_version"]
    if not (RAIZ / "data" / "corpus" / version / "MANIFEST.json").is_file():
        pytest.skip(f"el corpus {version} no está construido")
    e1 = _leer("e1_baseline")
    e2 = _leer("e2_security_v1.3") or _leer("e2_security")
    if not (e1 and e2):
        pytest.skip("faltan los resultados de E1 o E2")

    capturadas: dict = {}
    original = mf.guardar

    def espia(fig, destino):
        capturadas[Path(destino).stem] = fig
        return original(fig, destino)

    mf.guardar = espia
    try:
        aplicar_estilo()
        umbrales = yaml.safe_load(
            (RAIZ / "configs" / "thresholds.yaml").read_text(encoding="utf-8")
        )
        corpus = mf.cargar(version)
        extra = _leer("e1_prompt_only")
        e1 = {**e1, "_extra": (extra or {}).get("resultados", {})}
        destino = tmp_path_factory.mktemp("figuras")
        mf.fig1_esquema_del_marco(umbrales, destino / "fig1.png")
        mf.fig2_distribucion_corpus(corpus, destino / "fig2.png", version)
        mf.fig3_ataques(corpus, destino / "fig3.png")
        mf.fig4_passk_decay(e1, destino / "fig4.png")
        mf.fig5_asr_utility(e2, umbrales["seguridad"], destino / "fig5.png")
    finally:
        mf.guardar = original
    return capturadas


def _textos(fig) -> list[str]:
    """Todo el texto que la figura dibuja, rótulos de eje incluidos."""
    fig.canvas.draw()
    salida: list[str] = []
    for ax in fig.get_axes():
        salida += [ax.get_title(), ax.get_xlabel(), ax.get_ylabel()]
        salida += [t.get_text() for t in ax.texts]
        salida += [e.get_text() for e in list(ax.get_xticklabels()) + list(ax.get_yticklabels())]
        leyenda = ax.get_legend()
        if leyenda:
            salida += [t.get_text() for t in leyenda.get_texts()]
    salida += [t.get_text() for t in fig.texts]
    if fig._suptitle is not None:
        salida.append(fig._suptitle.get_text())
    return [s for s in salida if s and s.strip()]


NOMBRES = ("fig1", "fig2", "fig3", "fig4", "fig5")


def test_se_dibujan_las_cinco(figuras: dict):
    assert sorted(figuras) == list(NOMBRES)


@pytest.mark.parametrize("nombre", NOMBRES)
def test_sin_titulo_incrustado(figuras: dict, nombre: str):
    """El título va en el documento. Dentro de la imagen aparecería dos veces."""
    titulos = [t for t in _textos(figuras[nombre]) if re.match(r"\s*Figura\s*\d", t)]

    assert not titulos, f"{nombre} lleva el título dentro de la imagen: {titulos}"


@pytest.mark.parametrize("nombre", NOMBRES)
def test_sin_notas_al_pie_dentro_de_la_imagen(figuras: dict, nombre: str):
    """`fig.text` es como se escribían las notas; la nota va en el documento.

    La leyenda y los rótulos viven en los ejes, no en la figura, así que esto no los toca.
    """
    notas = [t.get_text() for t in figuras[nombre].texts if t.get_text().strip()]

    assert not notas, f"{nombre} lleva notas dentro de la imagen: {notas}"


@pytest.mark.parametrize("nombre", NOMBRES)
def test_coma_decimal_en_todo_el_texto(figuras: dict, nombre: str):
    con_punto = [t for t in _textos(figuras[nombre]) if re.search(r"\d\.\d", t)]

    assert not con_punto, f"{nombre} usa punto decimal en: {con_punto}"


@pytest.mark.parametrize("nombre", NOMBRES)
def test_sin_rayas_ni_backticks(figuras: dict, nombre: str):
    textos = _textos(figuras[nombre])
    con_raya = [t for t in textos if RAYA in t]
    con_backtick = [t for t in textos if "`" in t]

    assert not con_raya, f"{nombre} usa raya larga en: {con_raya}"
    assert not con_backtick, f"{nombre} usa backticks en: {con_backtick}"


def test_la_terminologia_es_la_del_informe(figuras: dict):
    """«Desvío de la recomendación», no «Secuestro de la tarea»."""
    assert "Desvío de la\nrecomendación" in mf.ETIQUETAS_OBJETIVO.values()
    for nombre in NOMBRES:
        viejos = [t for t in _textos(figuras[nombre]) if "ecuestro" in t]
        assert not viejos, f"{nombre} usa la terminología anterior: {viejos}"


@pytest.mark.parametrize("nombre", NOMBRES)
def test_el_ancho_y_la_resolucion_son_los_del_informe(figuras: dict, nombre: str):
    fig = figuras[nombre]

    assert fig.get_figwidth() == pytest.approx(ANCHO_PULGADAS)
    assert fig.dpi == pytest.approx(DPI)
    assert round(fig.get_figwidth() * DPI) == 1300


def test_los_cinco_png_del_informe_existen_con_el_ancho_pedido():
    """Los archivos que el informe cita, no solo los que el test dibuja."""
    pytest.importorskip("PIL")
    from PIL import Image

    directorio = RAIZ / "figures" / "informe"
    esperados = {
        "fig1_esquema_marco.png",
        "fig2_distribucion_corpus.png",
        "fig3_ataques.png",
        "fig4_passk_decay.png",
        "fig5_asr_utility.png",
    }
    presentes = {p.name for p in directorio.glob("*.png")} if directorio.is_dir() else set()
    faltan = sorted(esperados - presentes)
    if faltan:
        pytest.skip(f"faltan por generar: {faltan} (python scripts/make_figures.py --informe)")

    for nombre in sorted(esperados):
        with Image.open(directorio / nombre) as imagen:
            assert imagen.size[0] == 1300, f"{nombre} mide {imagen.size[0]} px de ancho"
            assert round(imagen.info["dpi"][0]) == DPI, f"{nombre} no está a {DPI} dpi"
