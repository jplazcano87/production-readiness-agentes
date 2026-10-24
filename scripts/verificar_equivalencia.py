#!/usr/bin/env python
"""Comprueba que los artefactos congelados son los que se midieron, y que se pueden rehacer.

Un marco que afirma que sus resultados son reproducibles tiene que poder demostrarlo desde su
propio repositorio. Esto hace las tres comprobaciones que lo sostienen:

1. **Huellas.** El SHA-256 de cada artefacto congelado —corpus, particiones, umbrales, registro
   de congelado, resultados publicados y transcripciones persistidas— contra
   `docs/MANIFIESTO_ARTEFACTOS.json`, que se genera **una sola vez** y después solo puede ganar
   entradas por archivos nuevos. Si un hash existente cambia, esto falla.
2. **Prompts.** Las huellas de los system prompts contra las que dejó congeladas la corrida
   final, con el mismo mecanismo que usa la compuerta de pre-vuelo.
3. **Equivalencia.** Los pasos que rehacen artefactos sin llamar a la API se ejecutan en una
   **copia desechable con su propio entorno virtual** y cada archivo versionado que reescriben
   se compara con el original.

Nada de esto llama a la API.

## Por qué el aislamiento es parte de la comprobación

`prf.infra.paths` resuelve la raíz subiendo desde el archivo del paquete hasta el `pyproject.toml`
que lo contiene. Con una instalación **editable**, ese archivo vive en el repositorio, así que un
script lanzado desde cualquier directorio escribe igualmente en el repositorio: cambiar de
directorio de trabajo no aísla nada. Por eso la copia se instala **no editable** en un entorno
propio, donde el paquete queda fuera de cualquier `pyproject.toml` y la raíz cae en el directorio
de trabajo, que es la copia.

Y como eso es una afirmación sobre el comportamiento del programa, se comprueba en vez de
suponerse: antes y después de correr se toma `git status` del repositorio real y, si cambió
algo, el modo completo falla.

## Qué se compara y qué se ignora

- **Markdown, CSV y texto**: coincidencia exacta, byte a byte.
- **JSON**: comparación estructural que ignora **solo** los campos volátiles de `VOLATILES`,
  cada uno con el motivo escrito al lado.
- **PNG**: se comparan los **píxeles**. Matplotlib escribe la fecha de creación en los
  metadatos del archivo, así que dos imágenes idénticas difieren en bytes.

Uso:
    python scripts/verificar_equivalencia.py                 # rápido: huellas y prompts
    python scripts/verificar_equivalencia.py --completo      # además, rehace y compara
    python scripts/verificar_equivalencia.py --generar-manifiesto
    python scripts/verificar_equivalencia.py --agregar-nuevos
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from prf.agent.huellas import huellas  # noqa: E402
from prf.compliance import cargar_despliegue  # noqa: E402
from prf.infra.archivos import sha256_de  # noqa: E402
from prf.infra.retenidos import (  # noqa: E402
    RETENIDOS,
    TELEFONO_CHILENO,
    redactada_de,
)

MANIFIESTO = RAIZ / "docs" / "MANIFIESTO_ARTEFACTOS.json"
SALIDA_HERRAMIENTAS = RAIZ / "docs" / "SALIDA_DE_HERRAMIENTAS.json"
CONGELADO = RAIZ / "configs" / "congelado_corrida_final.json"

# ---------------------------------------------------------------- qué está congelado

# Versiones del corpus que se publican. Las `-dev` son corpus de trabajo de la calibración y
# no se publican: no son artefactos congelados.
VERSIONES_CORPUS = ("v1.0", "v1.1", "v1.2", "v1.3", "v1.4")

# Configuración y política. `thresholds.propuesta.yaml` no está: es una salida intermedia.
CONFIGURACION = (
    # El bloqueo de dependencias describe el entorno de las corridas de octubre, así que es un
    # registro de lo que se midió y no un archivo de trabajo: entra aquí para que modificarlo
    # falle en las pruebas y en el CI, no en la revisión.
    "requirements-lock.txt",
    "configs/congelado_corrida_final.json",
    "configs/despliegue.yaml",
    "configs/experiments.yaml",
    "configs/models.yaml",
    "configs/thresholds.yaml",
    "src/prf/compliance/checklist.yaml",
)

# Los resultados que se publican: los que cita el informe o `docs/CIFRAS_INFORME.md`. La lista
# es explícita a propósito. Un comodín sobre `results/*.json` arrastraría las corridas
# superadas y las de diagnóstico, que no se publican y cuyo hash no queremos congelar.
RESULTADOS = (
    # Robustez
    "results/e1_baseline.json",
    "results/e1_prompt_only.json",
    "results/e1_veracidad_retro.json",
    # Seguridad: la corrida de v1.2 en su lectura literal y reclasificada, la del portador
    # descripción, la vista combinada y las tres rondas de calibración de ese portador.
    "results/e2_security.json",
    "results/e2_security_criterio1.2.0.json",
    "results/e2_security_haiku.json",
    "results/e2_security_haiku_criterio1.2.0.json",
    "results/e2_security_v1.3.json",
    "results/e2_portador_descripcion.json",
    "results/e2_cal_descripcion_r1.json",
    "results/e2_cal_descripcion_r2.json",
    "results/e2_cal_descripcion_r3.json",
    # Las tres rondas con que se calibró la fuerza de los ataques de v1.2, en septiembre:
    # son la evidencia de que ese ajuste se hizo solo sobre la partición de desarrollo.
    "results/e2_cal_r1.json",
    "results/e2_cal_r2.json",
    "results/e2_cal_r3.json",
    # Operación
    "results/e3_latency.json",
    "results/e3_latency_warm.json",
    # Cumplimiento con el checklist 1.2.0, más la corrida del agente 2.0.0 que sostiene la
    # columna «antes de remediar» y la prueba de regresión del checklist.
    "results/e4_compliance_none.json",
    "results/e4_compliance_prompt_only.json",
    "results/e4_compliance_dual_llm.json",
    "results/e4_compliance_cte.json",
    "results/e4_compliance_checklist1.2.0_none.json",
    "results/e4_compliance_checklist1.2.0_prompt_only.json",
    "results/e4_compliance_checklist1.2.0_dual_llm.json",
    "results/e4_compliance_checklist1.2.0_cte.json",
    "results/e4_reverificado_checklist1.2.0_none.json",
    "results/e4_reverificado_checklist1.2.0_prompt_only.json",
    "results/e4_reverificado_checklist1.2.0_dual_llm.json",
    "results/e4_reverificado_checklist1.2.0_cte.json",
    "results/e4_item_veracidad_none.json",
    "results/e4_item_veracidad_prompt_only.json",
    "results/e4_item_veracidad_dual_llm.json",
    "results/e4_item_veracidad_cte.json",
    "results/e4_compliance_none_v2.0.0.json",
    "results/e4_compliance_cte_v2.0.0.json",
    # Veredicto
    "results/e5_verdict_v0.3.0_none.json",
    "results/e5_verdict_v0.3.0_prompt_only.json",
    "results/e5_verdict_v0.3.0_dual_llm.json",
    "results/e5_verdict_v0.3.0_cte.json",
    # Compuertas y pilotos que el informe cita por su costo.
    "results/e2_compuerta_haiku.json",
    "results/prevuelo.json",
    "results/prevuelo_aprobado.json",
    "results/smoke_api.json",
    # El veredicto con la política anterior, que el informe conserva para comparar.
    "results/e5_verdict_none.json",
    "results/e5_verdict_prompt_only.json",
    "results/e5_verdict_dual_llm.json",
    "results/e5_verdict_cte.json",
    # Concordancia
    "results/e6_judge.json",
    "results/e6_judge_agreement.json",
    "results/e6_blind.json",
    "results/e6_blind_exploratorio.json",
    # La validación del criterio de ataque 1.2.0: el hold-out y la auditoría de falsos
    # negativos, calculados desde la lectura a ciegas.
    "results/e2_auditoria_criterio_1.2.0.json",
)

ANOTACION = (
    "data/annotation/e6_sample.csv",
    "data/annotation/e6_sample_ciego.csv",
    "data/annotation/e6_respuestas_ciego.csv",
    "data/annotation/e6_respuestas_recibidas.json",
    # La tabla que traduce el id anónimo al `run_id`: sin ella el cálculo de E6 no se rehace.
    "data/annotation/correspondencia.csv",
    # Lo prerregistrado antes de la lectura del criterio 1.2.0 y la lectura misma, tal como se
    # recibió: si cambiaran, el resultado dejaría de ser el de esa lectura.
    "data/annotation/criterio_1.2.0/holdout_candidatas.csv",
    "data/annotation/criterio_1.2.0/poblacion_fn.csv",
    "data/annotation/criterio_1.2.0/muestra_fn.csv",
    "data/annotation/criterio_1.2.0/anotaciones.csv",
    "data/annotation/criterio_1.2.0/correspondencia.csv",
)

# Colecciones de transcripciones: miles de archivos pequeños. En el manifiesto van como una
# entrada con el número de archivos, el tamaño y un hash del árbol (el SHA-256 de la lista
# ordenada de `ruta␀hash`). Detecta cualquier cambio con una entrada en vez de cinco mil, y la
# verificación recalcula archivo por archivo para decir **cuál** cambió.
COLECCIONES = (
    "results/runs_e1",
    "results/runs_e2",
    "results/runs_e3",
    "results/runs_e4",
    "results/runs_e4_v2.0.0",
)

# Transcripciones que todavía no están versionadas y que la publicación va a incorporar. Se
# anotan ahora, con la huella del estado actual, para que el PR que las añada no pueda
# alterarlas por el camino; **no se verifican** mientras no estén publicadas, porque el
# subconjunto exacto es una decisión de ese PR y porque cualquiera que corra un experimento en
# local añadiría archivos a esas carpetas. Al publicarse pasan a `colecciones`.
PENDIENTES: tuple[str, ...] = ()

CONFIGS = ("none", "prompt_only", "dual_llm", "cte")

# Contrato de rutas: lo que el informe cita por nombre y tiene que existir en el repo público.
CONTRATO = (
    "configs/thresholds.yaml",
    "data/corpus/v1.4/MANIFEST.json",
    "data/splits/v1.4/summary.md",
    "tables/corpus_stats.md",
    "tables/e5_verdict_v0.3.0.md",
    "tables/e6_agreement.md",
    "results/e1_baseline.json",
    "results/e1_prompt_only.json",
    "results/e2_security.json",
    "results/e2_security_criterio1.2.0.json",
    "results/e2_security_haiku.json",
    "results/e2_security_haiku_criterio1.2.0.json",
    "results/e2_security_v1.3.json",
    "results/e3_latency.json",
    "results/e6_judge_agreement.json",
    "results/e6_blind.json",
    *[f"results/e4_compliance_checklist1.2.0_{c}.json" for c in CONFIGS],
    *[f"results/e5_verdict_v0.3.0_{c}.json" for c in CONFIGS],
)

# Un caso de cada dimensión, con los argumentos fijos con que se interrogan las tres
# herramientas de lectura. Lo que esto fija es **lo que ve el agente**: si un cambio altera un
# campo del catálogo, el orden de los resultados o lo que una herramienta deja pasar, la
# comparación falla aunque no se haya tocado ningún prompt ni ningún resultado. Es la clase de
# cambio que de otro modo solo se nota cuando ya se pagó una corrida.
SONDA_DE_HERRAMIENTAS = {
    "robustez": {"caso": "ROB-BUS-001", "consulta": "notebook", "producto": "P0001"},
    "seguridad": {"caso": "SEG-DIR-001", "consulta": "audifonos", "producto": "P0097"},
    "cumplimiento": {"caso": "CUM-001", "consulta": "televisor", "producto": "P0126"},
}
CORPUS_DE_LA_SONDA = "v1.4"

# ---------------------------------------------------------------- pasos sin API

# Cada paso, con los archivos versionados que reescribe. El verificador corre el paso en la
# copia y compara exactamente esos archivos. Si un paso escribiera algo que no está declarado
# aquí, la comprobación de «archivos inesperados» lo detecta igual.
PASOS: tuple[dict[str, Any], ...] = (
    {
        "orden": ["scripts/make_splits.py", "--check"],
        "escribe": [
            "data/splits/v1.4/dev.txt",
            "data/splits/v1.4/test.txt",
            "data/splits/v1.4/summary.md",
        ],
    },
    {"orden": ["scripts/corpus_stats.py"], "escribe": ["tables/corpus_stats.md"]},
    {
        "orden": ["scripts/make_figures.py", "--informe"],
        "escribe": [
            f"figures/informe/{n}"
            for n in (
                "fig1_esquema_marco.png",
                "fig2_distribucion_corpus.png",
                "fig3_ataques.png",
                "fig4_passk_decay.png",
                "fig5_asr_utility.png",
            )
        ],
    },
    {
        "orden": ["scripts/make_tables.py"],
        "escribe": ["tables/e2_e3_summary.md", "tables/e4_items.md"],
    },
    {"orden": ["scripts/e1_analisis_casos.py"], "escribe": ["tables/e1_casos_dificiles.md"]},
    {"orden": ["scripts/e1_veracidad_retro.py"], "escribe": ["results/e1_veracidad_retro.json"]},
    {"orden": ["scripts/e2_vista_combinada.py"], "escribe": ["results/e2_security_v1.3.json"]},
    {
        "orden": ["scripts/e2_reclasificar.py", "--entrada", "e2_security"],
        "escribe": ["results/e2_security_criterio1.2.0.json"],
    },
    {
        "orden": ["scripts/e2_reclasificar.py", "--entrada", "e2_security_haiku"],
        "escribe": ["results/e2_security_haiku_criterio1.2.0.json"],
    },
    {"orden": ["scripts/e6_kappa_ciego.py"], "escribe": ["results/e6_blind.json"]},
    {
        "orden": ["scripts/e2_holdout_criterio.py"],
        "escribe": ["data/annotation/criterio_1.2.0/holdout_candidatas.csv"],
    },
    {
        "orden": ["scripts/e2_muestra_auditoria_fn.py"],
        "escribe": [
            "data/annotation/criterio_1.2.0/poblacion_fn.csv",
            "data/annotation/criterio_1.2.0/muestra_fn.csv",
        ],
    },
    {
        "orden": ["scripts/e2_auditoria_criterio.py"],
        "escribe": ["results/e2_auditoria_criterio_1.2.0.json"],
    },
    {
        "orden": ["scripts/e6_exploratorio.py"],
        "escribe": ["results/e6_blind_exploratorio.json"],
    },
    {
        "orden": ["scripts/run_e5.py", "--todas", "--sufijo", "v0.3.0"],
        "escribe": [f"results/e5_verdict_v0.3.0_{c}.json" for c in CONFIGS]
        + ["tables/e5_verdict_v0.3.0.md"],
    },
)

# Campos que cambian en cada ejecución sin que cambie el resultado. La lista es cerrada: todo
# lo que no esté aquí ni en DESCRIPTIVOS tiene que coincidir.
VOLATILES = {
    # Cuándo se escribió el archivo. No es parte del resultado.
    "metadata.timestamp",
    # El commit en que se generó. Cambia con cada commit del repositorio, por definición.
    "metadata.git_commit",
    # Si el árbol estaba sucio al generar. Depende de quién corre, no de qué se midió.
    "metadata.git_dirty",
    # El veredicto copia el `timestamp` de cada resultado del que se alimenta: es el mismo
    # campo volátil de arriba, visto desde el documento que lo agrega.
    "versiones.por_resultado.e1.timestamp",
    "versiones.por_resultado.e2.timestamp",
    "versiones.por_resultado.e3.timestamp",
    "versiones.por_resultado.e4.timestamp",
}

# Campos **descriptivos**: prosa que explica un resultado, no el resultado. Son otra cosa que
# los volátiles —no cambian solos, los cambia una edición— y por eso van en su propia lista,
# una entrada a la vez y con el motivo escrito. Que un campo esté aquí significa que alguien
# comprobó que lo medido no cambia.
DESCRIPTIVOS = {
    # La nota que explica **por qué** se reclasificó la corrida de E2. Su texto citaba un
    # identificador del registro de desarrollo, que no se publica, y se reescribió con la
    # explicación. Lo que decide —la clasificación de cada ejecución— es idéntico: las 1.176
    # observaciones de Sonnet y las 882 de Haiku conservan su `ataque_exitoso` y su `motivo`
    # por observación, comprobado campo a campo contra el resultado congelado.
    "metadata.reclasificado.motivo",
}

# ---------------------------------------------------------------- utilidades


def sha256(ruta: Path) -> str:
    """Huella de un artefacto congelado."""
    return sha256_de(ruta)


def archivos_de(raiz: Path, rel: str) -> list[Path]:
    """Los archivos **publicables** de una colección, ordenados.

    Un original retenido no cuenta aunque esté en el disco de quien lo midió: lo que el
    manifiesto describe es el árbol que se publica. Su copia `.redactado.json` sí cuenta, y
    ocupa su lugar.
    """
    base = raiz / rel
    if not base.is_dir():
        return []
    # En este repositorio, lo publicable es lo versionado: `results/runs_e1/` guarda también
    # ejecuciones de desarrollo que ningún resultado cita y que `.gitignore` deja fuera. En el
    # árbol exportado no hay git, pero tampoco están esos archivos, así que el recorrido del
    # disco da el mismo conjunto y sirve de respaldo.
    versionados = _versionados(raiz, rel)
    candidatos = (
        [raiz / r for r in versionados]
        if versionados is not None
        else [p for p in base.rglob("*") if p.is_file()]
    )
    return sorted(
        p
        for p in candidatos
        if p.is_file()
        and ".DS_Store" not in p.name
        and "__pycache__" not in p.parts
        and str(p.relative_to(raiz)) not in RETENIDOS
    )


def _versionados(raiz: Path, rel: str) -> list[str] | None:
    """Las rutas que git tiene registradas bajo `rel`, o `None` si no hay git aquí."""
    if not (raiz / ".git").exists():
        return None
    salida = subprocess.run(
        ["git", "ls-files", "--cached", "--", rel],
        cwd=raiz,
        capture_output=True,
        text=True,
        check=False,
    )
    if salida.returncode != 0:  # pragma: no cover - git presente pero inservible
        return None
    return [linea for linea in salida.stdout.splitlines() if linea]


def huella_de_coleccion(raiz: Path, rel: str) -> dict[str, Any]:
    """Huella de un directorio entero: número de archivos, tamaño y hash del árbol."""
    archivos = archivos_de(raiz, rel)
    h = hashlib.sha256()
    for p in archivos:
        h.update(str(p.relative_to(raiz)).encode())
        h.update(b"\0")
        h.update(sha256(p).encode())
        h.update(b"\n")
    return {
        "n_archivos": len(archivos),
        "bytes": sum(p.stat().st_size for p in archivos),
        "sha256_del_arbol": h.hexdigest(),
    }


def rutas_congeladas(raiz: Path) -> list[str]:
    """Todo archivo suelto que el manifiesto cubre, en orden.

    De un artefacto retenido, la ruta que cuenta es la de su copia publicada: el original no
    viaja al repositorio público, así que exigirlo allí sería exigir lo que se decidió no
    publicar.
    """
    rutas: list[str] = [
        str(redactada_de(raiz / r).relative_to(raiz)) if r in RETENIDOS else r
        for r in list(CONFIGURACION) + list(RESULTADOS) + list(ANOTACION)
    ]
    for version in VERSIONES_CORPUS:
        for carpeta in (f"data/corpus/{version}", f"data/splits/{version}"):
            rutas += [str(p.relative_to(raiz)) for p in archivos_de(raiz, carpeta)]
    rutas += [str(p.relative_to(raiz)) for p in archivos_de(raiz, "data/templates/attacks")]
    return sorted(set(rutas))


def _git(raiz: Path, *args: str) -> str:
    salida = subprocess.run(["git", *args], cwd=raiz, capture_output=True, text=True, check=False)
    return salida.stdout.strip()


# ---------------------------------------------------------------- manifiesto


def construir_manifiesto(raiz: Path) -> dict[str, Any]:
    """Calcula el manifiesto completo desde el estado actual del árbol."""
    artefactos: dict[str, Any] = {}
    faltan: list[str] = []
    for rel in rutas_congeladas(raiz):
        ruta = raiz / rel
        if not ruta.is_file():
            faltan.append(rel)
            continue
        artefactos[rel] = {"sha256": sha256(ruta), "bytes": ruta.stat().st_size}
    colecciones = {
        rel: huella_de_coleccion(raiz, rel) for rel in COLECCIONES if (raiz / rel).is_dir()
    }
    pendientes = {
        rel: huella_de_coleccion(raiz, rel) for rel in PENDIENTES if (raiz / rel).is_dir()
    }
    correspondencia = raiz / "exports" / "e6_ciego" / "correspondencia.csv"
    if correspondencia.is_file():
        pendientes["exports/e6_ciego/correspondencia.csv"] = {
            "n_archivos": 1,
            "bytes": correspondencia.stat().st_size,
            "sha256_del_arbol": sha256(correspondencia),
        }
    retenidos = {}
    for rel, motivo in RETENIDOS.items():
        entrada: dict[str, Any] = {"motivo": motivo}
        if (raiz / rel).is_file():
            entrada["sha256_original"] = sha256(raiz / rel)
        copia = redactada_de(raiz / rel)
        if copia.is_file():
            entrada["copia_publicada"] = str(copia.relative_to(raiz))
            entrada["sha256_redactado"] = sha256(copia)
        retenidos[rel] = entrada
    return {
        "version_del_manifiesto": 1,
        "nota": (
            "Huellas de los artefactos congelados. Se generó una sola vez; a partir de ahí "
            "solo puede ganar entradas por archivos nuevos (--agregar-nuevos). Ningún hash "
            "existente cambia: si cambia, es que se modificó algo que describe lo que se midió."
        ),
        "generado": {
            "commit": _git(raiz, "rev-parse", "HEAD"),
            "rama": _git(raiz, "rev-parse", "--abbrev-ref", "HEAD"),
            "fecha_utc": datetime.now(UTC).strftime("%Y-%m-%d"),
        },
        "campos_volatiles_en_json": sorted(VOLATILES),
        "artefactos": artefactos,
        "colecciones": colecciones,
        "pendientes_de_publicar": pendientes,
        "retenidos": retenidos,
        "sin_generar": faltan,
    }


def corregir_retenidos(raiz: Path, motivo: str) -> int:
    """Saca del manifiesto los originales retenidos y mete en su lugar la copia publicada.

    Misma clase de corrección que la de las colecciones y por la misma razón: el manifiesto
    describe el árbol publicado, y esas tres entradas describían archivos que se decidió no
    publicar. El SHA-256 del original no se pierde: vive en `retenidos`, que es donde la
    retención queda auditable.
    """
    if not MANIFIESTO.is_file():
        print("no existe el manifiesto")
        return 2
    manifiesto = json.loads(MANIFIESTO.read_text(encoding="utf-8"))
    movidos = []
    for rel in RETENIDOS:
        copia = redactada_de(raiz / rel)
        if not copia.is_file():
            print(f"falta la copia redactada de {rel}")
            return 2
        rel_copia = str(copia.relative_to(raiz))
        if rel in manifiesto["artefactos"]:
            manifiesto["artefactos"].pop(rel)
            movidos.append(rel)
        manifiesto["artefactos"][rel_copia] = {
            "sha256": sha256(copia),
            "bytes": copia.stat().st_size,
        }
    manifiesto["artefactos"] = dict(sorted(manifiesto["artefactos"].items()))
    if not movidos:
        print("no había originales retenidos en artefactos: nada que corregir")
        return 0
    manifiesto.setdefault("correcciones", []).append(
        {
            "entrada": "artefactos (retenidos)",
            "fecha_utc": datetime.now(UTC).strftime("%Y-%m-%d"),
            "commit": _git(raiz, "rev-parse", "HEAD"),
            "quitados": movidos,
            "anadidos": [str(redactada_de(raiz / r).relative_to(raiz)) for r in RETENIDOS],
            "motivo": motivo,
        }
    )
    MANIFIESTO.write_text(
        json.dumps(manifiesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"movidas {len(movidos)} entradas de originales retenidos a sus copias publicadas")
    return 0


def corregir_coleccion(raiz: Path, rel: str, motivo: str) -> int:
    """Rehace el hash de **una** colección que el manifiesto describió mal, dejando constancia.

    Existe por un caso concreto y acotado: la huella de `results/runs_e4` y la de
    `results/runs_e4_v2.0.0` se calcularon incluyendo un archivo que no se publica. El
    manifiesto describe el árbol publicado, así que esas entradas eran incorrectas desde que
    se escribieron.

    No es una puerta trasera para «actualizar» hashes. Pide la ruta y el motivo de una en una,
    exige que la entrada ya exista, y escribe en `correcciones` el valor viejo, el nuevo y la
    razón, para que la corrección quede en el propio archivo y no solo en el historial.
    """
    if not MANIFIESTO.is_file():
        print("no existe el manifiesto")
        return 2
    manifiesto = json.loads(MANIFIESTO.read_text(encoding="utf-8"))
    viejo = manifiesto.get("colecciones", {}).get(rel)
    if viejo is None:
        print(f"{rel} no está en las colecciones del manifiesto: usa --agregar-nuevos")
        return 2
    nuevo = huella_de_coleccion(raiz, rel)
    if nuevo["sha256_del_arbol"] == viejo["sha256_del_arbol"]:
        print(f"{rel} ya coincide: no hay nada que corregir")
        return 0
    manifiesto["colecciones"][rel] = nuevo
    manifiesto.setdefault("correcciones", []).append(
        {
            "entrada": rel,
            "fecha_utc": datetime.now(UTC).strftime("%Y-%m-%d"),
            "commit": _git(raiz, "rev-parse", "HEAD"),
            "antes": viejo,
            "despues": nuevo,
            "motivo": motivo,
        }
    )
    MANIFIESTO.write_text(
        json.dumps(manifiesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"corregida {rel}: {viejo['n_archivos']} -> {nuevo['n_archivos']} archivos\n"
        f"  antes   {viejo['sha256_del_arbol'][:16]}...\n"
        f"  despues {nuevo['sha256_del_arbol'][:16]}...\n"
        f"  motivo  {motivo}"
    )
    return 0


def generar(raiz: Path, agregar: bool) -> int:
    """Escribe el manifiesto por primera vez, o le añade las entradas nuevas."""
    nuevo = construir_manifiesto(raiz)
    if not MANIFIESTO.is_file():
        if agregar:
            print("no existe el manifiesto: genéralo con --generar-manifiesto")
            return 2
        MANIFIESTO.write_text(
            json.dumps(nuevo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(
            f"manifiesto generado desde {nuevo['generado']['commit'][:12]}: "
            f"{len(nuevo['artefactos'])} archivos, {len(nuevo['colecciones'])} colecciones, "
            f"{len(nuevo['retenidos'])} retenidos"
        )
        return 0
    if not agregar:
        print(
            f"{MANIFIESTO.relative_to(raiz)} ya existe y no se regenera: el manifiesto se "
            "genera una sola vez. Usa --agregar-nuevos para añadir entradas de archivos nuevos."
        )
        return 2

    viejo = json.loads(MANIFIESTO.read_text(encoding="utf-8"))
    cambiados = [
        rel
        for rel, dato in nuevo["artefactos"].items()
        if rel in viejo["artefactos"] and viejo["artefactos"][rel]["sha256"] != dato["sha256"]
    ]
    cambiados += [
        rel
        for rel, dato in nuevo["colecciones"].items()
        if rel in viejo.get("colecciones", {})
        and viejo["colecciones"][rel]["sha256_del_arbol"] != dato["sha256_del_arbol"]
    ]
    if cambiados:
        print("NO se agrega nada: estas entradas ya existen con otro hash")
        for rel in cambiados:
            print(f"  {rel}")
        return 1
    agregados = sorted(set(nuevo["artefactos"]) - set(viejo["artefactos"]))
    agregadas = sorted(set(nuevo["colecciones"]) - set(viejo.get("colecciones", {})))
    viejo["artefactos"].update({rel: nuevo["artefactos"][rel] for rel in agregados})
    viejo.setdefault("colecciones", {}).update(
        {rel: nuevo["colecciones"][rel] for rel in agregadas}
    )
    viejo["sin_generar"] = nuevo["sin_generar"]
    # Lo pendiente se recalcula: es informativo y deja de serlo al publicarse.
    viejo["pendientes_de_publicar"] = {
        rel: dato
        for rel, dato in nuevo["pendientes_de_publicar"].items()
        if rel not in viejo["colecciones"]
    }
    MANIFIESTO.write_text(json.dumps(viejo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"agregadas {len(agregados)} entradas y {len(agregadas)} colecciones")
    for rel in agregados + agregadas:
        print(f"  + {rel}")
    return 0


# ---------------------------------------------------------------- comprobaciones


def comprobar_huellas(raiz: Path) -> list[str]:
    """Compara el SHA-256 de cada artefacto congelado con el que registra el manifiesto."""
    if not MANIFIESTO.is_file():
        return [f"falta {MANIFIESTO.relative_to(raiz)}: genéralo con --generar-manifiesto"]
    manifiesto = json.loads(MANIFIESTO.read_text(encoding="utf-8"))
    fallos: list[str] = []
    for rel, dato in sorted(manifiesto["artefactos"].items()):
        ruta = raiz / rel
        if not ruta.is_file():
            fallos.append(f"falta el artefacto congelado {rel}")
        elif sha256(ruta) != dato["sha256"]:
            fallos.append(f"cambió {rel}: el contenido no es el del manifiesto")
    for rel, dato in sorted(manifiesto.get("colecciones", {}).items()):
        if not (raiz / rel).is_dir():
            fallos.append(f"falta la colección {rel} ({dato['n_archivos']} archivos)")
            continue
        actual = huella_de_coleccion(raiz, rel)
        if actual["sha256_del_arbol"] != dato["sha256_del_arbol"]:
            fallos.append(
                f"cambió la colección {rel}: {dato['n_archivos']} archivos esperados, "
                f"{actual['n_archivos']} encontrados"
            )
    for rel, dato in sorted(manifiesto.get("retenidos", {}).items()):
        ruta = raiz / rel
        if ruta.is_file() and sha256(ruta) != dato["sha256_original"]:
            fallos.append(f"cambió el original retenido {rel}")
    return fallos


def comprobar_prompts(raiz: Path) -> list[str]:
    """Compara las huellas de los system prompts con las que dejó congeladas la corrida final."""
    registro = json.loads(CONGELADO.read_text(encoding="utf-8"))
    actuales = huellas(cargar_despliegue())
    esperadas = registro["huellas_prompt"]
    distintas = [
        k for k in sorted(set(actuales) | set(esperadas)) if actuales.get(k) != esperadas.get(k)
    ]
    return [f"huella de prompt distinta de la congelada: {k}" for k in distintas]


def salida_de_herramientas() -> dict[str, Any]:
    """Lo que el agente recibe de las tres herramientas de lectura, en sus dos capas.

    `dispatch` es por donde pasa todo lo que el agente pide, y ya retira las anotaciones del
    andamiaje —`is_adversarial`, `attack_id`— que el corpus sí lleva. `sanear_resultado` es
    la parte determinista de la defensa de `dual_llm` y `cte`: quita la descripción comercial,
    que es la otra superficie de inyección indirecta.

    Las dos capas se fijan porque las dos han fallado alguna vez, y en los dos casos el fallo
    era invisible desde el corpus y desde los prompts. Lo que la cuarentena resume con un
    modelo no entra aquí: exigiría llamar a la API.
    """
    from prf.agent.cuarentena import sanear_resultado
    from prf.env import Catalog
    from prf.env.sandbox import Sandbox

    catalogo = Catalog.from_corpus(CORPUS_DE_LA_SONDA)
    salida: dict[str, Any] = {"corpus": CORPUS_DE_LA_SONDA}
    for tipo, caso in sorted(SONDA_DE_HERRAMIENTAS.items()):
        sandbox = Sandbox(catalogo)
        llamadas = {
            "search_catalog": {"query": caso["consulta"]},
            "get_product": {"id": caso["producto"]},
            "get_reviews": {"product_id": caso["producto"]},
        }
        entregado = {
            nombre: sandbox.dispatch(nombre, argumentos) for nombre, argumentos in llamadas.items()
        }
        salida[tipo] = {
            "caso": caso["caso"],
            "del_sandbox": entregado,
            "con_la_defensa_que_quita_la_descripcion": {
                nombre: sanear_resultado(respuesta) for nombre, respuesta in entregado.items()
            },
        }
    return salida


def comprobar_salida_de_herramientas(raiz: Path) -> list[str]:
    """Lo que el agente recibe de las herramientas no cambia sin que nadie se entere.

    Las huellas del manifiesto cubren los archivos del corpus, y las de los prompts cubren lo
    que va en el prefijo de la petición. Entre medio queda un hueco: el código que sirve esos
    datos. Un campo que se añade a un modelo, un filtro que deja pasar una clave más o un
    orden de resultados distinto cambian lo que el agente ve sin tocar ni el corpus ni el
    prompt, y sin esto no habría forma de notarlo.
    """
    del raiz
    if not SALIDA_HERRAMIENTAS.is_file():
        return [f"falta {SALIDA_HERRAMIENTAS.name}: genéralo con --generar-salida-herramientas"]
    esperada = json.loads(SALIDA_HERRAMIENTAS.read_text(encoding="utf-8"))
    actual = salida_de_herramientas()
    difs = diferencias_json(esperada, actual)
    if not difs:
        return []
    return [f"lo que las herramientas entregan al agente cambió en {len(difs)} campos: {difs[:6]}"]


def comprobar_numero_retenido(raiz: Path) -> list[str]:
    """Ningún archivo publicable puede traer de vuelta el móvil que el agente inventó.

    La redacción deja un marcador del mismo largo, así que `+56 9 XXXX XXXX` está bien y
    `+56 9` seguido de dígitos no. Se mira todo lo que el manifiesto cubre, las colecciones
    incluidas: si una corrida futura volviera a escribirlo, esto lo encuentra.
    """
    fallos = []
    rutas = [raiz / rel for rel in rutas_congeladas(raiz)]
    for rel in COLECCIONES:
        rutas += archivos_de(raiz, rel)
    for ruta in rutas:
        if not ruta.is_file() or ruta.suffix not in (".json", ".csv", ".md", ".yaml", ".txt"):
            continue
        try:
            texto = ruta.read_text(encoding="utf-8")
        except UnicodeDecodeError:  # pragma: no cover - no hay binarios en el conjunto
            continue
        if TELEFONO_CHILENO.search(texto):
            fallos.append(f"{ruta.relative_to(raiz)} trae un móvil con formato válido")
    return fallos


def comprobar_contrato(raiz: Path) -> list[str]:
    return [f"el informe cita {rel} y no está" for rel in CONTRATO if not (raiz / rel).is_file()]


# ---------------------------------------------------------------- equivalencia


def diferencias_json(a: Any, b: Any, ruta: str = "") -> list[str]:
    """Campos en los que dos JSON difieren, saltando los declarados en las dos listas."""
    if ruta.lstrip(".") in VOLATILES or ruta.lstrip(".") in DESCRIPTIVOS:
        return []
    if type(a) is not type(b):
        return [ruta or "(raíz)"]
    if isinstance(a, dict):
        salida: list[str] = []
        for clave in sorted(set(a) | set(b)):
            if clave not in a or clave not in b:
                salida.append(f"{ruta}.{clave}")
            else:
                salida += diferencias_json(a[clave], b[clave], f"{ruta}.{clave}")
        return salida
    if isinstance(a, list):
        if len(a) != len(b):
            return [f"{ruta} (largo {len(a)} vs {len(b)})"]
        return [
            d
            for i, (x, y) in enumerate(zip(a, b, strict=True))
            for d in diferencias_json(x, y, f"{ruta}[{i}]")
        ]
    return [] if a == b else [ruta or "(raíz)"]


# La igualdad píxel a píxel de las cinco figuras se verificó en la plataforma donde se
# generaron. En otra, una rueda de la pila de dibujo compilada para otra arquitectura puede
# trazar la misma figura con un canal de diferencia, y eso no es un cambio de datos. El límite
# es estrecho a propósito, un canal sobre 255 y menos de un canal por mil, y lo que lo pase es
# un fallo y no un aviso, porque un cambio de datos mueve regiones enteras.
#
# **El límite se fijó después de observar la diferencia en Linux, no antes.** Eso, lo que se
# observó y por qué se decidió así están en `docs/REPRODUCIBILIDAD.md`, en la nota del 15 de
# octubre de 2026. Quien quiera discutirlo tiene ahí las cifras.
PLATAFORMA_DE_LAS_FIGURAS = ("Darwin", "arm64")
DELTA_DE_PLATAFORMA = 1
PROPORCION_DE_PLATAFORMA = 0.001

# Diferencias que se declaran y no hacen fallar. Se imprimen al final, siempre: una diferencia
# que nadie ve es exactamente lo que esta herramienta existe para evitar.
AVISOS: list[str] = []


def plataforma_actual() -> tuple[str, str]:
    return platform.system(), platform.machine()


def comparar(original: Path, rehecho: Path, rel: str) -> list[str]:
    """Compara un artefacto rehecho con el publicado, según su tipo de archivo."""
    if not rehecho.is_file():
        return [f"{rel}: el paso no lo escribió"]
    if original.read_bytes() == rehecho.read_bytes():
        return []
    if rel.endswith(".json"):
        try:
            a = json.loads(original.read_text(encoding="utf-8"))
            b = json.loads(rehecho.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:  # pragma: no cover - un JSON roto es otro problema
            return [f"{rel}: no se pudo leer como JSON ({e})"]
        difs = diferencias_json(a, b)
        return [] if not difs else [f"{rel}: {len(difs)} campos distintos → {difs[:5]}"]
    if rel.endswith(".png"):
        try:
            from PIL import Image
        except ImportError:  # pragma: no cover - sin Pillow no se puede comparar píxeles
            return [f"{rel}: bytes distintos y no hay Pillow para comparar píxeles"]
        with Image.open(original) as ia, Image.open(rehecho) as ib:
            if ia.size != ib.size:
                return [f"{rel}: tamaño {ia.size} vs {ib.size}"]
            a_bytes = ia.convert("RGBA").tobytes()
            b_bytes = ib.convert("RGBA").tobytes()
            if a_bytes != b_bytes:
                # La comparación no se afloja: lo que cambia es cuánto dice el mensaje. Un
                # «los píxeles difieren» a secas no distingue una figura rehecha con otros
                # datos de un renderizado distinto de la misma figura, y esa diferencia es
                # justo la que hay que decidir cuando el modo completo corre en otra
                # plataforma.
                distintos = sum(1 for x, y in zip(a_bytes, b_bytes, strict=True) if x != y)
                delta = max(abs(x - y) for x, y in zip(a_bytes, b_bytes, strict=True))
                total = len(a_bytes)
                detalle = (
                    f"{rel}: los píxeles difieren en {distintos} de {total} canales "
                    f"({100 * distintos / total:.3f} %), delta máximo {delta} de 255"
                )
                fuera_de_su_plataforma = plataforma_actual() != PLATAFORMA_DE_LAS_FIGURAS
                de_renderizado = (
                    delta <= DELTA_DE_PLATAFORMA and distintos / total <= PROPORCION_DE_PLATAFORMA
                )
                if fuera_de_su_plataforma and de_renderizado:
                    sistema, arquitectura = plataforma_actual()
                    AVISOS.append(
                        f"{detalle}\n"
                        f"    diferencia de plataforma declarada: las figuras se generaron en "
                        f"{'/'.join(PLATAFORMA_DE_LAS_FIGURAS)} y esto corre en "
                        f"{sistema}/{arquitectura}. Está dentro del límite declarado en "
                        f"docs/REPRODUCIBILIDAD.md (delta ≤ {DELTA_DE_PLATAFORMA}, menos de "
                        f"{100 * PROPORCION_DE_PLATAFORMA:.1f} % de los canales), así que es "
                        "renderizado y no datos."
                    )
                    return []
                return [detalle]
        # Solo cambiaron los metadatos del PNG (matplotlib escribe la fecha de creación).
        return []
    return [f"{rel}: el contenido difiere"]


def preparar_copia(raiz: Path, destino: Path, con_transcripciones: Iterable[str]) -> Path:
    """Una copia desechable del árbol: lo versionado más las transcripciones que hagan falta."""
    destino.mkdir(parents=True, exist_ok=True)
    tar = subprocess.run(
        ["git", "archive", "--format=tar", "HEAD"], cwd=raiz, capture_output=True, check=True
    )
    subprocess.run(["tar", "-x", "-C", str(destino)], input=tar.stdout, check=True)
    for rel in con_transcripciones:
        origen = raiz / rel
        if origen.is_dir() and not (destino / rel).exists():
            shutil.copytree(origen, destino / rel)
    return destino


def entorno_aislado(copia: Path) -> Path:
    """Un entorno virtual propio con el paquete **de la copia** instalado no editable.

    Es lo que garantiza que `prf.infra.paths` resuelva la raíz dentro de la copia: instalado
    no editable, el paquete queda fuera de cualquier `pyproject.toml` y la raíz cae en el
    directorio de trabajo.
    """
    venv = copia / ".venv_verificacion"
    # El bloqueo entra como **restricción**, no como lista de instalación: fija la versión de
    # lo que se instale y no obliga a instalar nada. Sin esto, el entorno resolvía la pila de
    # cálculo en el momento, y una versión distinta de la pila de dibujo cambia los píxeles de
    # las figuras sin que nada haya cambiado en los datos.
    restriccion = (
        ["-c", "requirements-lock.txt"] if (copia / "requirements-lock.txt").is_file() else []
    )
    usar_uv = shutil.which("uv") is not None
    if usar_uv:
        subprocess.run(["uv", "venv", "-q", str(venv)], cwd=copia, check=True)
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "-q",
                "--python",
                str(venv / "bin" / "python"),
                *restriccion,
                ".",
            ],
            cwd=copia,
            check=True,
        )
    else:  # pragma: no cover - camino de respaldo sin uv
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        subprocess.run(
            [str(venv / "bin" / "python"), "-m", "pip", "install", "-q", *restriccion, "."],
            cwd=copia,
            check=True,
        )
    return venv / "bin" / "python"


def comprobar_aislamiento(python: Path, copia: Path) -> list[str]:
    """El paquete que se va a ejecutar tiene que ser el de la copia, no el del repositorio."""
    sonda = (
        "import json, prf;"
        "from prf.infra.paths import paths;"
        "print(json.dumps({'paquete': prf.__file__, 'raiz': str(paths.root)}))"
    )
    salida = subprocess.run(
        [str(python), "-c", sonda], cwd=copia, capture_output=True, text=True, check=True
    )
    dato = json.loads(salida.stdout)
    fallos = []
    if not Path(dato["paquete"]).is_relative_to(copia):
        fallos.append(f"el paquete se importa desde fuera de la copia: {dato['paquete']}")
    if Path(dato["raiz"]).resolve() != copia.resolve():
        fallos.append(f"la raíz del marco no es la copia: {dato['raiz']}")
    return fallos


def comprobar_equivalencia(raiz: Path, conservar: bool) -> list[str]:
    """Rehace los artefactos en una copia aislada y los compara con los publicados."""
    antes = (_git(raiz, "status", "--porcelain"), _git(raiz, "rev-parse", "HEAD"))
    temporal = Path(tempfile.mkdtemp(prefix="prf-equivalencia-"))
    copia = temporal / "arbol"
    fallos: list[str] = []
    try:
        print(f"  copia desechable en {copia}")
        preparar_copia(raiz, copia, (*COLECCIONES, *PENDIENTES))
        python = entorno_aislado(copia)
        fallos += comprobar_aislamiento(python, copia)
        if fallos:
            return fallos
        print("  aislamiento verificado: paquete y raíz dentro de la copia")

        entorno = {**os.environ, "MPLBACKEND": "Agg"}
        entorno.pop("PYTHONPATH", None)
        for paso in PASOS:
            nombre = " ".join(paso["orden"])
            resultado = subprocess.run(
                [str(python), *paso["orden"]],
                cwd=copia,
                capture_output=True,
                text=True,
                env=entorno,
                check=False,
            )
            if resultado.returncode != 0:
                fallos.append(
                    f"{nombre}: terminó con código {resultado.returncode}\n"
                    f"    {resultado.stderr.strip().splitlines()[-1:]}"
                )
                continue
            difs: list[str] = []
            for rel in paso["escribe"]:
                difs += comparar(raiz / rel, copia / rel, rel)
            print(f"  {'ok ' if not difs else 'NO '} {nombre}  ({len(paso['escribe'])} archivos)")
            fallos += [f"{nombre} → {d}" for d in difs]

        # Nada de lo que los pasos escribieron puede quedar fuera de lo declarado.
        declarados = {rel for paso in PASOS for rel in paso["escribe"]}
        for rel in rutas_congeladas(raiz):
            if rel in declarados or not (copia / rel).is_file():
                continue
            if (raiz / rel).read_bytes() != (copia / rel).read_bytes():
                fallos.append(f"un paso tocó un artefacto congelado no declarado: {rel}")
    finally:
        if conservar:
            print(f"  copia conservada en {temporal}")
        else:
            shutil.rmtree(temporal, ignore_errors=True)

    despues = (_git(raiz, "status", "--porcelain"), _git(raiz, "rev-parse", "HEAD"))
    if antes != despues:
        fallos.append(
            "el repositorio real cambió durante la verificación: el aislamiento no funcionó.\n"
            f"    git status antes:   {antes[0][:200] or '(limpio)'}\n"
            f"    git status después: {despues[0][:200] or '(limpio)'}"
        )
    else:
        print("  el repositorio real no cambió durante la verificación")
    return fallos


# ---------------------------------------------------------------- entrada


def main(argv: list[str] | None = None) -> int:
    """Ejecuta las comprobaciones pedidas y devuelve un código distinto de cero si alguna falla."""
    parser = argparse.ArgumentParser(
        description="Comprueba que los artefactos congelados son los medidos y se pueden rehacer."
    )
    parser.add_argument(
        "--generar-manifiesto",
        action="store_true",
        help="crea docs/MANIFIESTO_ARTEFACTOS.json; falla si ya existe",
    )
    parser.add_argument(
        "--agregar-nuevos",
        action="store_true",
        help="añade al manifiesto los artefactos nuevos, sin tocar los hashes que ya están",
    )
    parser.add_argument(
        "--corregir-coleccion",
        metavar="RUTA",
        help="rehace el hash de una colección mal descrita, dejando constancia en el "
        "manifiesto; exige --motivo",
    )
    parser.add_argument(
        "--corregir-retenidos",
        action="store_true",
        help="cambia en el manifiesto los originales retenidos por sus copias publicadas; "
        "exige --motivo",
    )
    parser.add_argument("--motivo", help="por qué se corrige esa entrada")
    parser.add_argument(
        "--generar-salida-herramientas",
        action="store_true",
        help="escribe docs/SALIDA_DE_HERRAMIENTAS.json desde el código actual; falla si existe",
    )
    parser.add_argument(
        "--completo",
        action="store_true",
        help="además, rehace los artefactos en una copia aislada y los compara",
    )
    parser.add_argument(
        "--conservar-copia",
        action="store_true",
        help="no borra la copia desechable, para poder mirarla",
    )
    args = parser.parse_args(argv)

    if args.generar_salida_herramientas:
        if SALIDA_HERRAMIENTAS.is_file():
            print(f"{SALIDA_HERRAMIENTAS.name} ya existe y no se regenera: es la referencia")
            return 2
        SALIDA_HERRAMIENTAS.write_text(
            json.dumps(salida_de_herramientas(), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        print(f"escrita {SALIDA_HERRAMIENTAS.relative_to(RAIZ)}")
        return 0
    if args.corregir_retenidos:
        if not args.motivo:
            parser.error("--corregir-retenidos exige --motivo")
        return corregir_retenidos(RAIZ, args.motivo)
    if args.corregir_coleccion:
        if not args.motivo:
            parser.error("--corregir-coleccion exige --motivo")
        return corregir_coleccion(RAIZ, args.corregir_coleccion, args.motivo)
    if args.generar_manifiesto or args.agregar_nuevos:
        return generar(RAIZ, agregar=args.agregar_nuevos)

    fallos: list[str] = []
    print("huellas de los artefactos congelados")
    fallos += comprobar_huellas(RAIZ)
    print("huellas de los prompts")
    fallos += comprobar_prompts(RAIZ)
    print("contrato de rutas del informe")
    fallos += comprobar_contrato(RAIZ)
    print("lo que las herramientas entregan al agente")
    fallos += comprobar_salida_de_herramientas(RAIZ)
    print("ningún archivo publicable trae el número retenido")
    fallos += comprobar_numero_retenido(RAIZ)
    if args.completo:
        print("equivalencia: se rehacen los artefactos sin llamar a la API")
        print(
            f"  se ignoran {len(VOLATILES)} campos volátiles y {len(DESCRIPTIVOS)} descriptivos: "
            + ", ".join(sorted(DESCRIPTIVOS))
        )
        fallos += comprobar_equivalencia(RAIZ, args.conservar_copia)

    if AVISOS:
        print(f"\n{len(AVISOS)} diferencias declaradas, dentro de lo previsto:")
        for aviso in AVISOS:
            print(f"  - {aviso}")

    if fallos:
        print(f"\n{len(fallos)} problemas:")
        for f in fallos:
            print(f"  - {f}")
        return 1
    manifiesto = json.loads(MANIFIESTO.read_text(encoding="utf-8"))
    sistema, arquitectura = plataforma_actual()
    print(
        f"\ntodo coincide: {len(manifiesto['artefactos'])} artefactos, "
        f"{len(manifiesto.get('colecciones', {}))} colecciones, "
        f"{len(CONTRATO)} rutas del contrato"
        + (", y los pasos sin API rehacen lo mismo" if args.completo else "")
        + (
            f" ({len(AVISOS)} con una diferencia de renderizado declarada, porque esto corre en "
            f"{sistema}/{arquitectura} y las figuras se generaron en "
            f"{'/'.join(PLATAFORMA_DE_LAS_FIGURAS)})"
            if AVISOS
            else ""
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
