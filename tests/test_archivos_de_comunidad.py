"""Los archivos de comunidad dicen lo mismo que el resto del repositorio.

Son los que alguien lee antes de contribuir, así que una contradicción aquí cuesta más que en
cualquier otro sitio: la cita que no coincide con `CITATION.cff`, la versión que quedó atrás, el
canal de reporte con el correo equivocado o una política que exige algo que ya no se exige.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections import Counter
from pathlib import Path

import pytest
import yaml

from tests.conftest import versionados

RAIZ = Path(__file__).resolve().parents[1]
CORREO_PUBLICO = "jlazcanoc@estudiante.uc.cl"
URL_PUBLICA = "https://github.com/jplazcano87/production-readiness-agentes"


def leer(nombre: str) -> str:
    return (RAIZ / nombre).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def cff() -> dict:
    return yaml.safe_load(leer("CITATION.cff"))


@pytest.fixture(scope="module")
def version_del_paquete() -> str:
    return tomllib.loads(leer("pyproject.toml"))["project"]["version"]


# --------------------------------------------------------------------------- la cita


def test_la_cita_es_valida_y_coincide_con_el_paquete(cff: dict, version_del_paquete: str):
    assert cff["cff-version"] == "1.2.0"
    assert cff["version"] == version_del_paquete
    assert cff["repository-code"] == URL_PUBLICA
    assert cff["license"] == "MIT"
    autor = cff["authors"][0]
    assert (autor["family-names"], autor["given-names"]) == ("Lazcano Candia", "Juan Pablo")
    assert autor["email"] == CORREO_PUBLICO
    # La fecha de publicación la puso la fase 4, y es la misma que `PROCEDENCIA.md` declara
    # como fecha de la exportación: son el mismo acto.
    fecha = str(cff["date-released"])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", fecha), fecha
    assert f"| Fecha de la exportación | {fecha} |" in leer("docs/PROCEDENCIA.md")


def sin_cita_partida(nombre: str) -> str:
    """El README parte la cita en varias líneas de bloque; esto la deja en una sola, sin las
    marcas de la cita."""
    return " ".join(leer(nombre).replace("\n>", "").split())


def test_el_readme_cita_exactamente_lo_que_dice_citation_cff(cff: dict):
    preferida = cff["preferred-citation"]
    seguido = sin_cita_partida("README.md")

    autor = preferida["authors"][0]
    inicial = autor["given-names"].split()
    esperado = (
        f"{autor['family-names']}, {inicial[0][0]}. {inicial[1][0]}. ({preferida['year']}). "
        f"*{preferida['title']}*. {preferida['thesis-type']}, "
        f"{preferida['institution']['name']}."
    )
    assert " ".join(esperado.split()) in seguido, esperado


def test_la_cita_en_ingles_mantiene_autor_y_institucion(cff: dict):
    preferida = cff["preferred-citation"]
    seguido = sin_cita_partida("README.en.md")
    assert f"{preferida['authors'][0]['family-names']}, J. P. ({preferida['year']})" in seguido
    assert preferida["institution"]["name"] in seguido


# ------------------------------------------------- la política de contribuciones con IA


def test_la_politica_de_ia_vive_completa_en_contributing():
    contributing = leer("CONTRIBUTING.md")
    assert "## Contribuciones con asistentes de IA" in contributing
    assert "responde por cada línea que envía" in contributing
    assert "No se exige declarar el uso" in contributing
    assert "tampoco se prohíben los trailers" in contributing
    assert "van leídos por una persona" in contributing


def test_agents_remite_a_la_politica_y_no_la_repite():
    """La condición que se retiró: `AGENTS.md` exigía declarar el uso en el pull request, y la
    política decidida no lo exige."""
    agents = leer("AGENTS.md")
    assert "declara el uso" not in agents
    assert "[`CONTRIBUTING.md`](CONTRIBUTING.md)" in agents
    # Lo que sí se queda son las instrucciones operativas.
    assert "No toca los artefactos congelados" in agents
    assert "No ejecuta nada que gaste API" in agents
    for condicion in ("No se exige declarar", "trailers"):
        assert condicion not in agents


# ------------------------------------------------------- conducta, seguridad y cambios


def test_el_codigo_de_conducta_es_el_convenio_30_con_su_canal_de_reporte():
    coc = leer("CODE_OF_CONDUCT.md")
    assert "Contributor Covenant 3.0" in coc
    assert "contributor-covenant.org/version/3/0/" in coc
    assert "CC BY-SA 4.0" in coc
    assert CORREO_PUBLICO in coc
    # Los dos marcadores que el convenio deja para que cada proyecto los complete.
    assert "[NOTA" not in coc and "[NOTE" not in coc


def test_security_declara_canal_privado_y_version_vigente(version_del_paquete: str):
    security = leer("SECURITY.md")
    assert "reporte privado de vulnerabilidades de GitHub" in security
    assert "No abras un issue público" in security
    assert CORREO_PUBLICO in security
    assert version_del_paquete in security


def test_el_changelog_tiene_la_entrada_de_la_version(version_del_paquete: str, cff: dict):
    changelog = leer("CHANGELOG.md")
    # La fecha de la versión es la de publicación de `CITATION.cff` y la de la exportación de
    # `PROCEDENCIA.md`: los tres hablan del mismo día y así no se pueden separar.
    assert f"## [{version_del_paquete}] - {cff['date-released']}" in changelog
    assert "Keep a Changelog" in changelog
    for seccion in ("### Añadido", "### Cambiado", "### Corregido", "### Quitado"):
        assert seccion in changelog


def test_el_changelog_no_se_come_el_registro_de_defectos():
    """Son dos documentos distintos: el registro es de la investigación y sigue en 32."""
    registro = leer("docs/REGISTRO_DE_DEFECTOS.md")
    numerados = re.findall(r"^\| (\d+) \|", registro, flags=re.MULTILINE)
    assert [int(n) for n in numerados] == list(range(1, 33)), numerados
    assert "REGISTRO_DE_DEFECTOS.md" in leer("CHANGELOG.md")


# ------------------------------------------------------------ ningún correo de más


def test_los_correos_publicables_son_el_de_contacto_o_de_dominio_de_ejemplo():
    """Un correo personal en un archivo publicable no se nota hasta que alguien lo recibe."""
    patron = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    extensiones = {".md", ".py", ".toml", ".cff", ".txt", ".yaml", ".yml", ".cfg", ".sh"}
    fuera = ("data/", "results/", "tables/", "figures/")
    ajenos = []
    for ruta in versionados(RAIZ):
        if Path(ruta).suffix not in extensiones or ruta.startswith(fuera):
            continue
        try:
            contenido = (RAIZ / ruta).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for correo in set(patron.findall(contenido)):
            if correo == CORREO_PUBLICO or correo.endswith((".example.cl", "@example.cl")):
                continue
            if correo.endswith(("@example.com", "@example.org", "@example.net")):
                continue
            ajenos.append(f"{ruta}: {correo}")
    assert not ajenos, ajenos


# ------------------------------------------- los conteos del registro de cambios


def con_punto(n: int) -> str:
    """El separador de miles del documento: `4.199`, no `4,199`."""
    return f"{n:,}".replace(",", ".")


def test_el_changelog_cuenta_bien_las_transcripciones():
    """Los conteos se leen del árbol, no de la memoria.

    La última vez que se publicaron transcripciones, dos cifras del registro de cambios
    quedaron viejas y nadie lo vio hasta que alguien las sumó a mano. Esta prueba las suma
    sola: si una colección gana o pierde archivos, el documento tiene que decirlo.
    """
    publicadas = [r for r in versionados(RAIZ) if r.startswith("results/runs_")]
    por_coleccion = Counter(r.split("/")[1] for r in publicadas)
    changelog = " ".join(leer("CHANGELOG.md").split())

    for coleccion, cuantas in sorted(por_coleccion.items()):
        assert f"`{coleccion}` ({con_punto(cuantas)}" in changelog, (coleccion, cuantas)

    # Las tres que este repositorio publicó por primera vez; las dos de E4 ya estaban.
    nuevas = sum(n for c, n in por_coleccion.items() if c in ("runs_e1", "runs_e2", "runs_e3"))
    assert f"{con_punto(nuevas)} archivos nuevos" in changelog, nuevas


def test_el_changelog_cuenta_bien_los_artefactos_congelados():
    manifiesto = json.loads(
        (RAIZ / "docs" / "MANIFIESTO_ARTEFACTOS.json").read_text(encoding="utf-8")
    )
    changelog = " ".join(leer("CHANGELOG.md").split())
    artefactos = con_punto(len(manifiesto["artefactos"]))
    colecciones = len(manifiesto["colecciones"])
    assert f"de los {artefactos} artefactos congelados y las {colecciones} colecciones" in changelog
