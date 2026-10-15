"""Las versiones del corpus solo añaden: cada una contiene a la anterior byte a byte.

Es la propiedad de la que depende todo el diseño incremental del trabajo. Si se cumple, una
corrida medida sobre v1.2 sigue midiendo exactamente los mismos casos en v1.3 y en v1.4, y sus
resultados se pueden **combinar** con los nuevos en vez de repetirse. Si se rompe, lo que hay
que repetir son las corridas, no esta prueba.

Dos comprobaciones, y las dos sobre los archivos, no sobre lo que el MANIFEST afirma:

1. **Contención byte a byte.** Los archivos que no crecen son idénticos; los `.jsonl` que
   crecen tienen las líneas de la versión base como **prefijo exacto**, en el mismo orden. Un
   caso insertado en medio correría los siguientes y, como el `case_id` de varios se deriva del
   orden, las transcripciones ya medidas dejarían de corresponder a los casos que dicen medir.
2. **Estabilidad de la partición.** Ningún `case_id` que ya tenía partición cambia de lado. Sin
   esto, añadir un caso rebaraja su estrato y mueve casos ya medidos: pasó al construir v1.4,
   donde `CUM-026` empujaba a `CUM-025` de desarrollo a prueba, y por eso `particionar` recibe
   ahora la asignación de la versión anterior.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prf.infra.config import load_experiments

RAIZ = Path(__file__).resolve().parents[1]
CORPUS = RAIZ / "data" / "corpus"
SPLITS = RAIZ / "data" / "splits"

ARCHIVOS = (
    "catalog.json",
    "reviews.jsonl",
    "cases_robustness.jsonl",
    "cases_security.jsonl",
    "cases_compliance.jsonl",
)

# Cadena de versiones incrementales, de la más nueva a la más vieja. v1.1 no está porque
# corrigió cinco intenciones en sitio en vez de añadir casos: no es incremental y no lo
# pretende.
CADENA = (("v1.4", "v1.3"), ("v1.3", "v1.2"))


def _lineas(ruta: Path) -> list[str]:
    return ruta.read_text(encoding="utf-8").splitlines()


def _presente(version: str) -> bool:
    return (CORPUS / version / "MANIFEST.json").is_file()


@pytest.mark.parametrize(("version", "base"), CADENA)
def test_el_corpus_contiene_byte_a_byte_a_su_base(version: str, base: str):
    if not (_presente(version) and _presente(base)):
        pytest.skip(f"{version} o {base} no están en disco")

    for nombre in ARCHIVOS:
        nuevo, viejo = CORPUS / version / nombre, CORPUS / base / nombre
        assert viejo.is_file(), f"{base}/{nombre} no existe"
        if nombre.endswith(".jsonl"):
            lineas_nuevas, lineas_viejas = _lineas(nuevo), _lineas(viejo)
            assert lineas_nuevas[: len(lineas_viejas)] == lineas_viejas, (
                f"{nombre}: las líneas de {base} no son un prefijo exacto de {version}"
            )
            assert len(lineas_nuevas) >= len(lineas_viejas)
        else:
            assert nuevo.read_bytes() == viejo.read_bytes(), (
                f"{nombre}: {version} no lo hereda idéntico de {base}"
            )


@pytest.mark.parametrize(("version", "base"), CADENA)
def test_el_manifiesto_declara_de_quien_hereda(version: str, base: str):
    if not (_presente(version) and _presente(base)):
        pytest.skip(f"{version} o {base} no están en disco")
    manifest = json.loads((CORPUS / version / "MANIFEST.json").read_text(encoding="utf-8"))

    assert manifest["base"] == base, (
        f"{version} hereda de {base} en los archivos y declara {manifest['base']!r}"
    )


@pytest.mark.parametrize(("version", "base"), CADENA)
def test_ningun_caso_heredado_cambia_de_particion(version: str, base: str):
    if not ((SPLITS / version).is_dir() and (SPLITS / base).is_dir()):
        pytest.skip(f"faltan las particiones de {version} o de {base}")

    def asignacion(cual: str) -> dict[str, str]:
        salida = {}
        for particion in ("dev", "test"):
            archivo = SPLITS / cual / f"{particion}.txt"
            for case_id in archivo.read_text(encoding="utf-8").split():
                salida[case_id] = particion
        return salida

    nueva, vieja = asignacion(version), asignacion(base)
    movidos = {
        case_id: (lado, nueva.get(case_id))
        for case_id, lado in vieja.items()
        if nueva.get(case_id) != lado
    }

    assert not movidos, f"casos que cambiaron de partición entre {base} y {version}: {movidos}"
    assert set(vieja) <= set(nueva), "la versión nueva perdió casos de la anterior"


def test_la_version_vigente_encabeza_la_cadena():
    """La cadena tiene que hablar de la versión que el repo usa.

    Sin esto, declarar una versión nueva en `experiments.yaml` y olvidarse de añadirla a
    `CADENA` dejaría las tres pruebas de arriba comprobando una herencia vieja mientras la
    nueva no se comprueba: seguirían verdes sin medir lo que importa.
    """
    vigente = load_experiments()["corpus_version"]

    assert CADENA[0][0] == vigente, (
        f"el corpus vigente es {vigente} y la cadena empieza en {CADENA[0][0]}"
    )


def test_la_cadena_esta_encadenada():
    """Cada eslabón hereda del siguiente: la contención es transitiva o no sirve de nada."""
    for (version, base), (siguiente, _) in zip(CADENA, CADENA[1:], strict=False):
        assert base == siguiente, f"{version} hereda de {base}, que no es el eslabón siguiente"
