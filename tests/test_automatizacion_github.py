"""La automatización de GitHub, comprobada como cualquier otra cosa del repositorio.

Un workflow mal escrito no falla: pasa, y deja de comprobar lo que alguien creía que
comprobaba. Tres cosas se fijan aquí porque son las que se degradan en silencio: que las
acciones estén ancladas a un commit y no a una etiqueta que su autor puede mover, que los
permisos del token sean de solo lectura, y que el CI corra la misma compuerta que se corre en
local.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[1]
GITHUB = RAIZ / ".github"
CI = GITHUB / "workflows" / "ci.yml"
SHA_COMPLETO = re.compile(r"^[0-9a-f]{40}$")


@pytest.fixture(scope="module")
def ci() -> dict:
    # `on` es la palabra reservada `True` para el cargador de YAML 1.1; se lee como venga.
    return yaml.safe_load(CI.read_text(encoding="utf-8"))


def pasos_con_accion(workflow: dict) -> list[tuple[str, str]]:
    usos = []
    for nombre, trabajo in workflow["jobs"].items():
        for paso in trabajo["steps"]:
            if "uses" in paso:
                usos.append((nombre, paso["uses"]))
    return usos


# ------------------------------------------------------------------ el workflow de CI


def test_las_acciones_estan_fijadas_por_sha_con_su_version_al_lado(ci: dict):
    texto = CI.read_text(encoding="utf-8")
    usos = pasos_con_accion(ci)
    assert usos, "el CI no usa ninguna acción: algo se rompió al leerlo"
    for trabajo, uso in usos:
        accion, _, referencia = uso.partition("@")
        assert SHA_COMPLETO.match(referencia), f"{trabajo}: {uso} no está fijada por SHA"
        # El comentario con la versión es lo que hace revisable una actualización del SHA.
        linea = next(ln for ln in texto.splitlines() if uso in ln)
        assert re.search(r"#\s*v\d+", linea), f"{trabajo}: {uso} sin la versión en el comentario"


def test_el_token_es_de_solo_lectura_y_no_hay_pull_request_target(ci: dict):
    assert ci["permissions"] == {"contents": "read"}
    # Un trabajo puede declarar más que la cabecera, pero solo lecturas y solo el trabajo que
    # lo necesita: el escaneo de secretos lista los commits del pull request.
    permitidos = {"contents": "read", "pull-requests": "read"}
    for nombre, trabajo in ci["jobs"].items():
        permisos = trabajo.get("permissions") or {}
        assert set(permisos) <= set(permitidos), (nombre, permisos)
        assert all(permisos[k] == "read" for k in permisos), (nombre, permisos)
    disparadores = ci.get("on") or ci.get(True)
    assert set(disparadores) == {"push", "pull_request"}
    # Solo `main`: la rama de la preparación de la versión pública salió en la fase 4, y una
    # base de más en el repositorio público sería una puerta que nadie declaró.
    assert disparadores["push"]["branches"] == ["main"]
    assert disparadores["pull_request"]["branches"] == ["main"]
    assert "pull_request_target" not in CI.read_text(encoding="utf-8")


def test_el_ci_corre_las_dos_versiones_de_python_y_la_compuerta_completa(ci: dict):
    pruebas = ci["jobs"]["pruebas"]
    assert pruebas["strategy"]["matrix"]["python"] == ["3.11", "3.12"]

    comandos = "\n".join(
        paso.get("run", "") for trabajo in ci["jobs"].values() for paso in trabajo["steps"]
    )
    for esperado in (
        "ruff check .",
        "ruff format --check .",
        "pytest -q",
        "scripts/verificar_equivalencia.py",
        "scripts/verificar_equivalencia.py --completo",
    ):
        assert esperado in comandos, esperado
    # El bloqueo entra como restricción solo donde la comparación depende de las versiones.
    equivalencia = "\n".join(p.get("run", "") for p in ci["jobs"]["equivalencia"]["steps"])
    assert "-c requirements-lock.txt" in equivalencia
    pruebas_cmd = "\n".join(p.get("run", "") for p in pruebas["steps"])
    assert "requirements-lock.txt" not in pruebas_cmd


def test_el_trabajo_que_compara_figuras_fija_la_imagen_del_runner(ci: dict):
    """`ubuntu-latest` es una etiqueta que GitHub mueve. En el trabajo que compara píxeles, eso
    cambiaría el resultado sin que nadie lo decidiera."""
    assert ci["jobs"]["equivalencia"]["runs-on"] == "ubuntu-24.04"
    # Los demás no comparan imágenes y siguen la etiqueta.
    for nombre in ("pruebas", "secretos"):
        assert ci["jobs"][nombre]["runs-on"] == "ubuntu-latest", nombre


def test_el_ci_escanea_secretos(ci: dict):
    usos = [uso for _, uso in pasos_con_accion(ci)]
    assert any("gitleaks" in uso for uso in usos), usos


# --------------------------------------------------- dependabot, plantillas y revisores


def test_dependabot_cubre_las_acciones_una_vez_al_mes_y_no_el_bloqueo():
    datos = yaml.safe_load((GITHUB / "dependabot.yml").read_text(encoding="utf-8"))
    assert datos["version"] == 2
    ecosistemas = {u["package-ecosystem"]: u for u in datos["updates"]}
    # Sin ecosistema `pip`: `pyproject.toml` declara mínimos y `requirements-lock.txt` es un
    # artefacto congelado, no una lista de dependencias que mantener.
    assert set(ecosistemas) == {"github-actions"}
    for ecosistema, actualizacion in ecosistemas.items():
        assert actualizacion["schedule"]["interval"] == "monthly", ecosistema


def test_las_plantillas_de_issue_existen_y_no_hay_issues_en_blanco():
    plantillas = sorted(p.name for p in (GITHUB / "ISSUE_TEMPLATE").glob("*.yml"))
    assert plantillas == ["config.yml", "discrepancia.yml", "error.yml", "mejora.yml"]

    config = yaml.safe_load((GITHUB / "ISSUE_TEMPLATE" / "config.yml").read_text("utf-8"))
    assert config["blank_issues_enabled"] is False
    enlaces = " ".join(c["url"] for c in config["contact_links"])
    assert "security/advisories/new" in enlaces, "lo de seguridad tiene que ir al canal privado"

    for nombre in ("error.yml", "mejora.yml", "discrepancia.yml"):
        datos = yaml.safe_load((GITHUB / "ISSUE_TEMPLATE" / nombre).read_text("utf-8"))
        assert datos["name"] and datos["description"] and datos["body"], nombre


def test_la_plantilla_de_pull_request_lleva_la_compuerta_y_nada_sobre_ia():
    texto = (GITHUB / "PULL_REQUEST_TEMPLATE.md").read_text(encoding="utf-8")
    for esperado in (
        "pytest -q",
        "ruff check .",
        "verificar_equivalencia.py --completo",
        "Sin secretos",
        "Ningún artefacto congelado modificado",
        "--dry-run",
    ):
        assert esperado in texto, esperado
    # La política de asistentes de IA vive en CONTRIBUTING.md y no pide declarar el uso: la
    # plantilla no puede pedirlo por la puerta de atrás.
    assert not re.search(r"(?i)\bia\b|asistent|copilot|declarar el uso", texto)


def test_codeowners_nombra_a_quien_revisa():
    texto = (GITHUB / "CODEOWNERS").read_text(encoding="utf-8")
    reglas = [ln for ln in texto.splitlines() if ln.strip() and not ln.startswith("#")]
    assert reglas == ["* @jplazcano87"], reglas
