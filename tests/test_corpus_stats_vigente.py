"""`tables/corpus_stats.md` tiene que ser del corpus que el repo declara vigente.

La tabla 3 del informe se genera una vez y se queda en el repositorio, así que se desincroniza
en silencio: estuvo generada sobre **v1.1** mientras el corpus vigente ya era v1.2, y nada lo
advertía. Una tabla que dice en el pie de qué corpus es, pero cuyos números son de otro, es peor
que no tenerla: parece verificada.

Se comprueban las dos mitades, porque fallan por separado:

1. **El pie declara el corpus vigente**, con su hash completo tal como está en el MANIFEST.
2. **Los números son de ese corpus**. El pie se puede editar a mano; los N, no. Se recalculan
   desde el corpus y se comparan con los de la tabla.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

from corpus_stats import cargar_corpus, series  # noqa: E402
from prf.infra.config import load_experiments  # noqa: E402
from prf.infra.tokens import approx_tokens  # noqa: E402

TABLA = RAIZ / "tables" / "corpus_stats.md"


@pytest.fixture(scope="module")
def texto() -> str:
    if not TABLA.is_file():
        pytest.skip("no hay tables/corpus_stats.md: genérala con scripts/corpus_stats.py")
    return TABLA.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def vigente() -> str:
    return load_experiments()["corpus_version"]


def _filas(texto: str) -> dict[str, int]:
    """{nombre de la variable: N} tal como la tabla los declara."""
    salida: dict[str, int] = {}
    for linea in texto.splitlines():
        if not linea.startswith("|") or linea.startswith("|---") or "Variable |" in linea:
            continue
        celdas = [c.strip() for c in linea.strip("|").split("|")]
        if len(celdas) >= 2 and celdas[1].isdigit():
            salida[celdas[0]] = int(celdas[1])
    return salida


def test_el_pie_declara_el_corpus_vigente(texto: str, vigente: str):
    assert f"Corpus `{vigente}`" in texto, (
        f"la tabla no dice ser del corpus vigente ({vigente}); regenérala con "
        "`python scripts/corpus_stats.py`"
    )


def test_el_pie_declara_el_hash_del_corpus_vigente(texto: str, vigente: str):
    manifest = json.loads(
        (RAIZ / "data" / "corpus" / vigente / "MANIFEST.json").read_text(encoding="utf-8")
    )
    esperado = manifest["corpus_hash"]
    declarados = re.findall(r"hash `([0-9a-f]{16,64})", texto)

    assert declarados, "la tabla no declara ningún hash de corpus en su pie"
    assert esperado.startswith(declarados[0]), (
        f"la tabla declara el hash {declarados[0]}… y el de {vigente} es {esperado[:16]}…"
    )
    assert declarados[0] == esperado, (
        "el hash del pie va completo, no truncado: truncarlo deja de identificar el corpus "
        "de forma única en el informe"
    )


def test_los_numeros_son_los_del_corpus_vigente(texto: str, vigente: str):
    """El pie se edita a mano; los N no. Esta es la mitad que de verdad ata la tabla."""
    corpus = cargar_corpus(vigente)
    esperadas = {nombre.strip(): len(valores) for nombre, valores in series(corpus, approx_tokens)}
    declaradas = _filas(texto)

    assert declaradas, "no se pudo leer ninguna fila de la tabla"
    faltan = sorted(set(esperadas) - set(declaradas))
    sobran = sorted(set(declaradas) - set(esperadas))
    assert not faltan, f"la tabla no trae estas filas del corpus vigente: {faltan}"
    assert not sobran, f"la tabla trae filas que el corpus vigente no produce: {sobran}"

    distintas = {
        nombre: (declaradas[nombre], esperadas[nombre])
        for nombre in esperadas
        if declaradas[nombre] != esperadas[nombre]
    }
    assert not distintas, (
        "la tabla está generada sobre otro corpus; (declarado, esperado) por fila: "
        f"{distintas}. Regenérala con `python scripts/corpus_stats.py`"
    )


def test_la_carga_adversarial_esta_separada_por_portador(texto: str, vigente: str):
    """Desde v1.3 hay dos superficies y promediarlas no describe a ninguna.

    La fila de descripción arrastra la ficha comercial legítima, que el ataque no escribió
    pero el agente sí lee, así que su longitud no es comparable con la de una reseña.
    """
    corpus = cargar_corpus(vigente)
    hay_descripcion = any(c.get("portador") == "descripcion" for c in corpus["seguridad"])
    if not hay_descripcion:
        pytest.skip(f"{vigente} no tiene ataques con portador descripción")

    declaradas = _filas(texto)
    for fila in ("vector directo", "portador reseña", "portador descripción"):
        assert fila in declaradas, f"falta la fila «{fila}» en la tabla"

    agregada = declaradas["Longitud de carga adversarial (tokens)"]
    superficies = ("vector directo", "portador reseña", "portador descripción")
    partes = sum(declaradas[f] for f in superficies)
    assert agregada == partes, (
        f"la fila agregada declara N={agregada} y las tres superficies suman {partes}"
    )
