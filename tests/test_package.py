"""El paquete importa y la estructura del repositorio está donde el informe la espera."""

from __future__ import annotations

import pytest

import prf
from prf.infra.paths import paths


def test_el_paquete_importa_y_tiene_version():
    """La del paquete avanza con las publicaciones.

    Las versiones del agente, del evaluador, del criterio de ataque, del checklist y de la
    política **no** se mueven con ella: describen con qué se midió, y cada resultado las
    declara en su metadata. Confundirlas sería dar por nuevo lo que no se ha vuelto a medir.
    """
    assert prf.__version__ == "1.1.1"
    # Y `pyproject.toml` declara la misma: dos sitios con la versión es un sitio de más donde
    # se puede quedar atrás.
    declarada = [
        linea
        for linea in (paths.root / "pyproject.toml").read_text(encoding="utf-8").splitlines()
        if linea.startswith("version = ")
    ]
    assert declarada == [f'version = "{prf.__version__}"'], declarada


@pytest.mark.parametrize(
    "modulo",
    ["prf.env", "prf.agent", "prf.eval", "prf.compliance", "prf.verdict", "prf.infra"],
)
def test_los_subpaquetes_importan(modulo):
    __import__(modulo)


@pytest.mark.parametrize(
    "carpeta",
    ["configs", "data", "results", "figures", "tables"],
)
def test_las_carpetas_de_salida_existen(carpeta):
    assert (paths.root / carpeta).is_dir()


def test_no_hay_claves_versionadas():
    # Regla de trabajo 2: nunca una clave en el repositorio.
    assert not (paths.root / ".env").exists() or ".env" in (paths.root / ".gitignore").read_text()
    ejemplo = (paths.root / ".env.example").read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY=" in ejemplo
    assert ejemplo.strip().endswith("=") or "ANTHROPIC_API_KEY=\n" in ejemplo


# ------------------------------------------------- herramientas de desarrollo


def test_el_lock_fija_las_dependencias_declaradas():
    """El archivo de bloqueo tiene que cubrir lo que `pyproject.toml` exige.

    Un lock al que le falta una dependencia del paquete no reproduce nada: instalarlo deja
    que el resolutor elija esa versión, que es justo lo que el lock existe para evitar.
    """
    lock = (paths.root / "requirements-lock.txt").read_text(encoding="utf-8")
    fijadas = {
        linea.split("==")[0].lower()
        for linea in lock.splitlines()
        if "==" in linea and not linea.startswith("#")
    }
    pyproject = (paths.root / "pyproject.toml").read_text(encoding="utf-8")
    dependencias = pyproject.split("dependencies = [", 1)[1].split("]", 1)[0]
    declaradas = {
        linea.strip().strip('",').split(">=")[0].split("==")[0].lower()
        for linea in dependencias.splitlines()
        if linea.strip().startswith('"')
    }
    assert declaradas <= fijadas, sorted(declaradas - fijadas)


def test_el_lock_declara_que_no_se_leyo_de_los_resultados():
    """Los resultados congelados no registran la versión de sus dependencias, así que el lock
    es el entorno de hoy y no una lectura de los de entonces. Decirlo es parte del archivo."""
    lock = (paths.root / "requirements-lock.txt").read_text(encoding="utf-8")
    assert "docs/REPRODUCIBILIDAD.md" in lock
    assert "anthropic==" in lock


def test_los_ganchos_de_pre_commit_tienen_la_version_fijada():
    """`pre-commit autoupdate` mueve las revisiones, y moverlas sin querer cambiaría el
    formato de archivos que este repositorio compara byte a byte."""
    config = (paths.root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    revisiones = [
        linea.split("rev:", 1)[1].strip()
        for linea in config.splitlines()
        if linea.strip().startswith("rev:")
    ]
    assert len(revisiones) == 3, revisiones
    assert all(r.startswith("v") and r[1].isdigit() for r in revisiones), revisiones
    # Los artefactos congelados no pasan por los ganchos que reescriben archivos.
    for carpeta in ("data/corpus/", "data/splits/", "results/"):
        assert carpeta in config, carpeta
