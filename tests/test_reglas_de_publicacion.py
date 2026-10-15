"""Dos reglas del árbol que se publica, comprobadas por ubicación.

Son reglas sobre **dónde** puede aparecer un texto, no sobre cuántas veces aparece. Un conteo
se cuadra bajando el número hasta que pase; una ubicación, no: o el archivo está en la lista de
los que pueden contenerlo, o la prueba falla y hay que decidir.

- **Identificadores del registro interno de desarrollo** (`(D20)`, `(L9)`). El registro no se
  publica. Los identificadores sobreviven dentro de artefactos congelados, donde cambiarlos
  rompería el hash que demuestra que son los que se midieron, y en la tabla de `PROCEDENCIA.md`
  que los traduce. En ningún otro sitio.
- **Atribución a asistentes de IA y declaración de uso del autor.** El repositorio no declara
  cómo lo construyó el autor. Las menciones metodológicas a modelos de lenguaje (el corpus
  redactado con Haiku, el agente, el juez, el modelo en cuarentena) son parte del método y no
  las toca esta prueba: lo que se prohíbe es la atribución y la declaración de uso.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.conftest import versionados as _versionados_de

RAIZ = Path(__file__).resolve().parents[1]
# Esta prueba se excluye de sus propios barridos: lleva los patrones escritos, así que se
# denunciaría a sí misma. Es el único archivo exento, y el de arriba es el motivo.
ESTA_PRUEBA = "tests/test_reglas_de_publicacion.py"
MANIFIESTO = json.loads((RAIZ / "docs" / "MANIFIESTO_ARTEFACTOS.json").read_text(encoding="utf-8"))

# --------------------------------------------------------------- el árbol que se publica


def versionados() -> list[str]:
    """Lo publicado, según git. En un árbol sin `.git` la prueba que llama aquí se salta con
    su motivo; el ayudante está en `tests/conftest.py` y explica por qué no se recorre el
    disco en su lugar."""
    return _versionados_de(RAIZ)


def texto_de(ruta: str) -> str | None:
    try:
        return (RAIZ / ruta).read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def congelado(ruta: str) -> bool:
    """Un artefacto cuyo hash está en el manifiesto, suelto o dentro de una colección."""
    if ruta in MANIFIESTO["artefactos"] or ruta in MANIFIESTO["retenidos"]:
        return True
    return any(ruta.startswith(f"{coleccion}/") for coleccion in MANIFIESTO["colecciones"])


# ------------------------------------------------- regla 5: identificadores del registro

TOKEN = re.compile(r"(?<![A-Za-z0-9])(?:D\d{1,2}|L\d{1,2})(?![A-Za-z0-9])")

TRADUCCION = "docs/PROCEDENCIA.md"
SECCION_DE_TRADUCCION = "## Identificadores internos en artefactos congelados"


def test_los_identificadores_internos_solo_viven_donde_se_aceptan():
    fuera = []
    for ruta in versionados():
        if ruta in (TRADUCCION, ESTA_PRUEBA) or congelado(ruta):
            continue
        contenido = texto_de(ruta)
        if contenido is None:
            continue
        for numero, linea in enumerate(contenido.splitlines(), 1):
            if TOKEN.search(linea):
                fuera.append(f"{ruta}:{numero}")
    assert not fuera, f"identificadores del registro interno fuera de su ubicación: {fuera}"


def test_en_procedencia_los_identificadores_estan_en_su_seccion():
    """Se aceptan por sección, no por conteo: la tabla puede crecer, el resto del documento no
    puede empezar a citarlos."""
    contenido = texto_de(TRADUCCION)
    assert contenido is not None
    inicio = contenido.index(SECCION_DE_TRADUCCION)
    fin = contenido.index("\n## ", inicio + 1)
    resto = contenido[:inicio] + contenido[fin:]

    assert TOKEN.search(contenido[inicio:fin]), "la tabla de traducción se quedó sin tokens"
    sueltos = [
        f"{TRADUCCION}: {linea.strip()[:70]}" for linea in resto.splitlines() if TOKEN.search(linea)
    ]
    assert not sueltos, sueltos


def test_cada_token_de_la_tabla_dice_donde_aparece():
    """La tabla traduce: si cita un archivo, el token tiene que estar de verdad ahí."""
    contenido = texto_de(TRADUCCION)
    inicio = contenido.index(SECCION_DE_TRADUCCION)
    fin = contenido.index("\n## ", inicio + 1)
    filas = [
        línea
        for línea in contenido[inicio:fin].splitlines()
        if línea.startswith("| `") and "`" in línea
    ]
    assert len(filas) >= 9, filas

    for fila in filas:
        celdas = [c.strip() for c in fila.strip("|").split("|")]
        token = celdas[0].strip("`")
        lugares = [c.strip("`") for c in celdas[1].split(", ")]
        for lugar in lugares:
            if "<config>" in lugar or "v1.*" in lugar:  # la fila cita un patrón
                continue
            contenido_citado = texto_de(lugar)
            assert contenido_citado is not None, (token, lugar)
            assert token in contenido_citado, (token, lugar)


# ------------------------------------------ regla 9: atribución y declaración de uso de IA

# Los archivos que escribe el autor. Se dejan fuera el corpus, las transcripciones y los
# resultados: lo que ahí dice «asistente de IA» lo escribió el modelo evaluado respondiendo, y
# es evidencia, no una declaración del repositorio.
EXTENSIONES = {".md", ".py", ".toml", ".cff", ".txt", ".yaml", ".yml", ".cfg", ".sh", ".json"}
FUERA_DE_ALCANCE = ("data/", "results/", "tables/", "figures/")

# La política para contribuidores sí habla de asistentes de IA: es la única ubicación donde se
# acepta, y lo hace en segunda persona, dirigida a quien contribuye. `AGENTS.md` y `CLAUDE.md`
# la nombran para remitir a ella, y las dos pruebas de `tests/` la citan para comprobar que
# sigue ahí y que la plantilla de pull request no pide declarar el uso.
POLITICA_DE_CONTRIBUCION = {
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    ".github/CONTRIBUTING.md",
    "tests/test_archivos_de_comunidad.py",
    "tests/test_automatizacion_github.py",
}

ATRIBUCION = re.compile(
    r"(?i)co-authored-by\s*:|assisted-by\s*:|generated with \[?claude code|🤖 generated with"
)
MENCION = re.compile(
    r"(?i)asistent\w+ de (programación|ia)|asistid\w+ por (ia|un modelo)"
    r"|ai (coding )?assistant|claude code|copilot|chatgpt"
)
DECLARACION_DEL_AUTOR = re.compile(
    r"(?i)con (la )?ayuda de (un |unos |)asistent"
    r"|\b(usé|utilicé|escribí|redacté|desarrollé|construí)\b[^.]{0,60}\basistent"
    r"|(uso|empleo) de asistentes de ia"
    r"|(use|help) of (ai|programming) assistants"
    r"|written with the help of"
)


def en_alcance(ruta: str) -> bool:
    if ruta == ESTA_PRUEBA:
        return False
    return Path(ruta).suffix in EXTENSIONES and not ruta.startswith(FUERA_DE_ALCANCE)


@pytest.mark.parametrize(
    ("nombre", "patron"),
    [("atribución", ATRIBUCION), ("declaración de uso del autor", DECLARACION_DEL_AUTOR)],
)
def test_no_hay_atribucion_ni_declaracion_de_uso_de_ia(nombre: str, patron: re.Pattern):
    """Ni en la política para contribuidores: ahí se explica lo que se le pide a quien
    contribuye, no cómo construyó el autor este repositorio."""
    hallazgos = []
    for ruta in versionados():
        if not en_alcance(ruta):
            continue
        contenido = texto_de(ruta)
        if contenido is None:
            continue
        for numero, linea in enumerate(contenido.splitlines(), 1):
            if patron.search(linea):
                hallazgos.append(f"{ruta}:{numero}")
    assert not hallazgos, f"{nombre} en archivos publicables: {hallazgos}"


def test_los_asistentes_de_ia_solo_se_mencionan_en_la_politica_de_contribucion():
    fuera = []
    for ruta in versionados():
        if not en_alcance(ruta) or ruta in POLITICA_DE_CONTRIBUCION:
            continue
        contenido = texto_de(ruta)
        if contenido is None:
            continue
        for numero, linea in enumerate(contenido.splitlines(), 1):
            if MENCION.search(linea):
                fuera.append(f"{ruta}:{numero}")
    assert not fuera, f"asistentes de IA mencionados fuera de la política: {fuera}"


def test_la_mencion_metodologica_a_los_modelos_sigue_intacta():
    """La regla no puede convertirse en un filtro que borre el método: el corpus se redactó con
    un modelo y el juez es un modelo, y las dos cosas se declaran."""
    datasheet = texto_de("docs/DATASHEET.md")
    assert "claude-haiku-4-5-20251001" in datasheet
    assert "modelo de lenguaje" in datasheet
