"""Tabla 3 del informe y las figuras 2 y 3.

Las figuras se comprueban por sus propiedades verificables —que existan, que tengan la
resolución y el ancho pedidos, que ninguna serie dependa del color— no por su apariencia,
que se revisa a ojo.
"""

from __future__ import annotations

import statistics

import pytest

from corpus_stats import cargar_corpus, cargas_adversariales, fila_markdown, series, tabla_markdown
from make_figures import ORDEN_OBJETIVOS, cargar, fig2_distribucion_corpus, fig3_ataques
from prf.infra.config import load_experiments
from prf.infra.figuras import ANCHO_PULGADAS, DPI, TEXTURAS, aplicar_estilo
from prf.infra.paths import paths
from prf.infra.tokens import approx_tokens

# El corpus **vigente**, no uno fijo. Estaba clavado en `v1.0` con un `skipif`, así que el día
# que ese corpus dejara de estar en disco el módulo entero se habría saltado en silencio y la
# cobertura de la tabla 3 y de las figuras 2 y 3 se habría perdido sin que nada lo dijera.
VERSION = load_experiments()["corpus_version"]

pytestmark = pytest.mark.skipif(
    not (paths.corpus_version(VERSION) / "MANIFEST.json").is_file(),
    reason=f"el corpus {VERSION} no está construido",
)

# Las cuatro primeras filas son fijas; las de carga adversarial dependen de qué superficies
# tenga el corpus, así que se derivan de él en lugar de escribirse aquí.
FILAS_FIJAS = [
    "Precio del producto (CLP)",
    "Longitud de intención (tokens)",
    "Longitud de reseña (tokens)",
    "Reseñas por producto",
    "Longitud de carga adversarial (tokens)",
]
FILAS_POR_SUPERFICIE = {
    "directo": "    vector directo",
    "resena": "    portador reseña",
    "descripcion": "    portador descripción",
}


@pytest.fixture(scope="module")
def corpus():
    return cargar_corpus(VERSION)


# ------------------------------------------------------------------- tabla 3


def _filas_esperadas(corpus) -> list[str]:
    cargas = cargas_adversariales(corpus)
    return FILAS_FIJAS + [
        etiqueta for clave, etiqueta in FILAS_POR_SUPERFICIE.items() if cargas[clave]
    ]


def test_las_filas_son_exactamente_las_del_informe(corpus):
    nombres = [nombre for nombre, _ in series(corpus, approx_tokens)]

    assert nombres == _filas_esperadas(corpus)


def test_cada_fila_tiene_los_datos_que_declara(corpus):
    """Los N salen del corpus, no de constantes: así siguen valiendo cuando el corpus crece."""
    valores = dict(series(corpus, approx_tokens))
    n_ataques = sum(1 for c in corpus["seguridad"] if c["tipo"] in ("directo", "indirecto"))
    n_casos = sum(len(corpus[g]) for g in ("robustez", "seguridad", "cumplimiento"))
    n_benignas = sum(1 for r in corpus["resenas"] if not r.get("is_adversarial"))

    assert len(valores["Precio del producto (CLP)"]) == len(corpus["productos"])
    assert len(valores["Longitud de intención (tokens)"]) == n_casos
    assert len(valores["Longitud de reseña (tokens)"]) == n_benignas
    assert len(valores["Reseñas por producto"]) == len(corpus["productos"])
    assert len(valores["Longitud de carga adversarial (tokens)"]) == n_ataques


def test_las_cargas_adversariales_cubren_todos_los_ataques(corpus):
    """Ninguna superficie se queda fuera del recuento.

    `cargas_adversariales` solo miraba reseñas, así que al añadir el portador descripción los
    30 casos nuevos desaparecían del N de la tabla sin que nada fallara.
    """
    cargas = cargas_adversariales(corpus)
    n_ataques = sum(1 for c in corpus["seguridad"] if c["tipo"] in ("directo", "indirecto"))

    assert set(cargas) == set(FILAS_POR_SUPERFICIE)
    assert sum(len(v) for v in cargas.values()) == n_ataques
    assert all(texto.strip() for textos in cargas.values() for texto in textos)


def test_la_tabla_trae_las_cinco_columnas(corpus):
    tabla = tabla_markdown(series(corpus, approx_tokens), nota="nota de prueba")

    assert "| Variable | N | Media | Mediana | Desv. est. | Mín.–Máx. |" in tabla
    for nombre in _filas_esperadas(corpus):
        assert f"| {nombre} |" in tabla
    assert "nota de prueba" in tabla


def test_los_estadisticos_de_una_fila_son_correctos():
    fila = fila_markdown("Prueba", [1.0, 2.0, 3.0, 4.0])

    assert "| 4 |" in fila  # N
    assert "2.5" in fila  # media y mediana
    assert f"{statistics.stdev([1.0, 2.0, 3.0, 4.0]):.1f}" in fila
    assert "1.0–4.0" in fila


def test_el_precio_se_formatea_con_separador_de_miles():
    fila = fila_markdown("Precio del producto (CLP)", [100_000.0, 2_000_000.0])

    assert "1.050.000" in fila  # media, con punto como separador


def test_la_tabla_escrita_existe_y_declara_el_metodo_de_conteo(corpus):
    archivo = paths.tables / "corpus_stats.md"
    if not archivo.is_file():
        pytest.skip("la tabla aún no se ha generado")

    texto = archivo.read_text(encoding="utf-8")

    assert "| Variable | N | Media | Mediana | Desv. est. | Mín.–Máx. |" in texto
    # El plan exige declarar el método de conteo, no solo usarlo.
    assert "Conteo de tokens:" in texto
    for nombre in _filas_esperadas(corpus):
        assert nombre.strip() in texto


# -------------------------------------------------------------------- figuras


def test_las_dos_figuras_se_generan(tmp_path):
    aplicar_estilo()
    datos = cargar(VERSION)

    fig2 = fig2_distribucion_corpus(datos, tmp_path / "fig2.png")
    fig3 = fig3_ataques(datos, tmp_path / "fig3.png")

    assert fig2.is_file() and fig2.stat().st_size > 10_000
    assert fig3.is_file() and fig3.stat().st_size > 10_000


def test_las_figuras_tienen_la_resolucion_y_el_ancho_del_informe(tmp_path):
    from PIL import Image

    aplicar_estilo()
    ruta = fig2_distribucion_corpus(cargar(VERSION), tmp_path / "fig2.png")

    with Image.open(ruta) as imagen:
        ancho_px, _ = imagen.size
        dpi = imagen.info.get("dpi", (DPI, DPI))[0]

    assert round(dpi) == DPI
    # Ancho exacto, no aproximado: dos figuras del informe con anchos distintos se ven
    # como si vinieran de trabajos distintos.
    assert ancho_px == round(ANCHO_PULGADAS * DPI)


def test_las_figuras_del_informe_estan_escritas():
    """Las del informe viven en `figures/informe/` y se versionan.

    Antes esto miraba `figures/fig2_*.png` y `fig3_*.png`, que eran las de una etapa anterior
    y ya no coincidían con lo que el código dibuja: se trazaron sobre el corpus v1.2 y difieren
    en píxeles de lo que `make_figures.py` produce hoy. Se dejaron de publicar, así que la
    comprobación apunta a las que sí son el entregable y deja de saltarse en silencio.
    """
    for nombre in ("fig2_distribucion_corpus.png", "fig3_ataques.png"):
        archivo = paths.figures / "informe" / nombre
        assert archivo.is_file(), nombre
        assert archivo.stat().st_size > 10_000


def test_la_figura_3_cubre_los_cuatro_objetivos():
    assert len(ORDEN_OBJETIVOS) == 4
    assert set(ORDEN_OBJETIVOS) == {
        "exfiltration",
        "task_hijack",
        "out_of_domain",
        "unauthorized_promise",
    }


def test_las_texturas_son_espejo_y_de_igual_densidad():
    # En una impresión en blanco y negro, la identidad de la serie la lleva la textura:
    # dos rayados con la misma inclinación serían indistinguibles, y con densidades
    # distintas una serie pesaría más que la otra sin ninguna razón de diseño.
    a, b = TEXTURAS

    assert set(a) != set(b)
    assert len(a) == len(b)
    assert "-" not in a + b and "|" not in a + b  # nunca horizontal ni vertical
