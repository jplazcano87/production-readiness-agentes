"""Escritura de los JSON canónicos de `results/`.

`results/*.json` es la fuente de verdad del informe. Todo archivo escrito
aquí lleva el bloque `metadata` con los siete campos obligatorios; `write_result` falla
si alguno falta, para que ningún resultado quede sin trazabilidad.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from prf.infra.paths import paths

CAMPOS_METADATA = (
    "seed",
    "corpus_version",
    "corpus_hash",
    "model",
    "config",
    "timestamp",
    "git_commit",
    "api_mode",
    "agent_version",
    "evaluator_version",
    # Obligatorio desde el criterio 1.1.0. Los resultados escritos antes no lo traen, y es
    # justamente por eso: no declaraban con qué criterio se midió el éxito de un ataque, y
    # cuando el criterio cambió hubo que averiguarlo por la fecha del archivo.
    "criterio_ataque_version",
)

# Valor de `criterio_ataque_version` en los experimentos que no juzgan ningún ataque: E1 mide
# robustez, E3 latencia y E4 cumplimiento, y ninguno decide si una carga adversarial prosperó.
# Rellenarlo con la versión instalada diría que ese criterio se usó, y no se usó.
CRITERIOS_NO_APLICABLES = ("no_aplica",)


def _version(valor: Any) -> bool:
    return bool(isinstance(valor, str) and re.fullmatch(r"\d+\.\d+\.\d+", valor))


# Vías por las que se puede haber llamado a la API.
API_MODES = ("batch", "realtime", "realtime_concurrente", "none")


def git_commit() -> str | None:
    """Hash del commit actual, o `None` si no hay repositorio git o no hay commits.

    No falla: el repositorio debe poder ejecutarse antes del primer commit.
    """
    try:
        salida = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=paths.root,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - entorno sin git
        return None
    if salida.returncode != 0:
        return None
    return salida.stdout.strip() or None


def git_dirty() -> bool | None:
    """¿Hay cambios sin confirmar? `None` si no se puede determinar."""
    try:
        salida = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=paths.root,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover
        return None
    if salida.returncode != 0:
        return None
    return bool(salida.stdout.strip())


def corpus_hash(corpus_version: str) -> str | None:
    """Hash del corpus congelado, leído de su `MANIFEST.json`.

    Devuelve `None` mientras el corpus no exista (antes de la etapa 2).
    """
    manifest = paths.corpus_version(corpus_version) / "MANIFEST.json"
    if not manifest.is_file():
        return None
    with manifest.open(encoding="utf-8") as handle:
        datos = json.load(handle)
    valor = datos.get("corpus_hash")
    return str(valor) if valor is not None else None


def utc_timestamp() -> str:
    """Marca de tiempo ISO 8601 en UTC."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def politica_vigente(tag: str = "policy-v0.3.0") -> dict[str, Any]:
    """La política go/no-go con la que se juzgará esta corrida, y el commit que la congela.

    Va en la metadata de todo resultado nuevo. Sin ella, dentro de seis meses no hay forma de
    saber con qué reglas se midió algo —ni, sobre todo, si esas reglas existían ya cuando se
    midió, que es lo que el tag anotado demuestra—.
    """
    from prf.infra.config import load_thresholds

    umbrales = load_thresholds()
    commit = None
    try:
        salida = subprocess.run(
            ["git", "rev-list", "-n", "1", tag],
            capture_output=True,
            text=True,
            cwd=paths.root,
            check=False,
        )
        commit = salida.stdout.strip() or None
    except OSError:  # pragma: no cover - sin git instalado
        pass
    return {
        "thresholds_version": str(umbrales["version"]),
        "tag": tag,
        "commit_del_tag": commit,
    }


def build_metadata(
    *,
    seed: int,
    model: str | dict[str, str],
    config: str,
    corpus_version: str,
    api_mode: str,
    agent_version: str | None = None,
    evaluator_version: str | None = None,
    criterio_ataque_version: str | None = None,
    batch_ids: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bloque `metadata` obligatorio de todo resultado.

    `api_mode` no tiene valor por omisión a propósito: la vía por la que se llamó a la API
    cambia el costo y la latencia de un experimento, y un resultado que no la declara no es
    comparable con otro. Cuando es `batch`, se registran además los `batch_id`, que son lo
    único que permite volver a la ejecución original en la consola de Anthropic.

    `agent_version` identifica la versión del agente que produjo el resultado —prompts,
    defensas y forma de acreditar el estado final—. Sin ella, dos corridas del mismo
    experimento pueden diferir sin que el JSON diga por qué; ocurrió entre las cuatro
    corridas de E1. Por omisión toma la versión del
    código instalado.

    `evaluator_version` identifica de dónde sale el estado que se juzga y con qué reglas.
    Va aparte de `agent_version` porque las dos cambian por su cuenta: entre las corridas 3
    y 4 de E1 cambió el evaluador sin que cambiara el agente conversacional, y un resultado
    que solo declarara una de las dos no sería comparable con otro.
    """
    if agent_version is None:
        from prf.agent.configuraciones import AGENT_VERSION

        agent_version = AGENT_VERSION
    if evaluator_version is None:
        from prf.env.evaluator import EVALUATOR_VERSION

        evaluator_version = EVALUATOR_VERSION
    if criterio_ataque_version is None:
        from prf.eval.ataque import CRITERIO_ATAQUE_VERSION

        criterio_ataque_version = CRITERIO_ATAQUE_VERSION
    if criterio_ataque_version not in CRITERIOS_NO_APLICABLES and not _version(
        criterio_ataque_version
    ):
        raise ValueError(
            f"criterio_ataque_version inválido: {criterio_ataque_version!r}. Una versión "
            f"x.y.z, o {' / '.join(CRITERIOS_NO_APLICABLES)} en un experimento que no juzga "
            "ataques."
        )
    if api_mode not in API_MODES:
        raise ValueError(f"api_mode desconocido: {api_mode!r}. Válidos: {', '.join(API_MODES)}")
    metadata: dict[str, Any] = {
        "seed": seed,
        "corpus_version": corpus_version,
        "corpus_hash": corpus_hash(corpus_version),
        "model": model,
        "config": config,
        "timestamp": utc_timestamp(),
        "git_commit": git_commit(),
        "git_dirty": git_dirty(),
        "api_mode": api_mode,
        "agent_version": agent_version,
        "evaluator_version": evaluator_version,
        # Con qué criterio se decidió si un ataque prosperó. Va aparte de
        # `evaluator_version`, que es el evaluador de estado: el criterio de ataque cambió en
        # 1.1.0 sin que el evaluador de estado se moviera, y un resultado que declarara solo
        # una de las dos no sería comparable con otro.
        "criterio_ataque_version": criterio_ataque_version,
    }
    if api_mode == "batch":
        metadata["batch_ids"] = list(batch_ids or [])
    elif batch_ids:
        raise ValueError("solo un resultado con api_mode='batch' declara batch_ids")
    if extra:
        metadata.update(extra)
    return metadata


def write_result(
    nombre: str,
    payload: dict[str, Any],
    metadata: dict[str, Any],
    *,
    directorio: Path | None = None,
) -> Path:
    """Escribe `results/<nombre>.json` con su bloque `metadata` validado."""
    faltantes = [campo for campo in CAMPOS_METADATA if campo not in metadata]
    if faltantes:
        raise ValueError("metadata incompleta, faltan campos obligatorios: " + ", ".join(faltantes))
    destino = directorio or paths.results
    destino.mkdir(parents=True, exist_ok=True)
    archivo = destino / (nombre if nombre.endswith(".json") else f"{nombre}.json")
    documento = {"metadata": metadata, **payload}
    with archivo.open("w", encoding="utf-8") as handle:
        json.dump(documento, handle, ensure_ascii=False, indent=2, sort_keys=False)
        handle.write("\n")
    return archivo


def read_result(nombre: str, *, directorio: Path | None = None) -> dict[str, Any]:
    """Lee un resultado canónico."""
    destino = directorio or paths.results
    archivo = destino / (nombre if nombre.endswith(".json") else f"{nombre}.json")
    with archivo.open(encoding="utf-8") as handle:
        return json.load(handle)


__all__ = [
    "API_MODES",
    "CAMPOS_METADATA",
    "build_metadata",
    "politica_vigente",
    "corpus_hash",
    "git_commit",
    "git_dirty",
    "read_result",
    "utc_timestamp",
    "write_result",
]
