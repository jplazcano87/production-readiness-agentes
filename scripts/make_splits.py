#!/usr/bin/env python
"""Particiona el corpus en desarrollo y prueba.

Tres reglas, en este orden de precedencia:

1. **Los ataques siguen a su plantilla.** Un caso construido con una plantilla de
   `attacks/dev/` va a desarrollo y uno de `attacks/test/` va a prueba. No se sortea. Si se
   sorteara, una formulación adversarial vista durante el ajuste podría reaparecer en la
   medición, y el ASR de la tabla 5 dejaría de ser una estimación sobre material no visto.
   El plan lo exige para los ataques indirectos; aquí se aplica **también a los directos**,
   porque el riesgo de fuga es idéntico y las plantillas ya están separadas por partición.
2. **Todo lo demás se estratifica.** Robustez por tipo de intención, controles benignos y
   cumplimiento por su dimensión, con la semilla global y una proporción de 30/70.
3. **Un `case_id` vive en una sola partición.** Se verifica al escribir y hay una prueba
   automática que lo comprueba sobre los archivos.

Salidas: `data/splits/<version>/dev.txt`, `test.txt` y `summary.md` (tabla 4 del informe).

Uso:

    python scripts/make_splits.py            # escribe las particiones
    python scripts/make_splits.py --check    # solo verifica las ya escritas
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from prf.infra.config import load_experiments  # noqa: E402
from prf.infra.paths import paths  # noqa: E402

DEV = "dev"
TEST = "test"

# Filas de la tabla 4 del informe, en su orden exacto: (etiqueta, dimensión, tipo).
FILAS: tuple[tuple[str, str, str | None], ...] = (
    ("Robustez: búsqueda", "robustez", "busqueda"),
    ("Robustez: comparación", "robustez", "comparacion"),
    ("Robustez: recomendación", "robustez", "recomendacion"),
    ("Seguridad: inyección directa", "seguridad", "directo"),
    ("Seguridad: inyección indirecta", "seguridad", "indirecto"),
    ("Seguridad: benignos", "seguridad", "benigno"),
    ("Cumplimiento", "cumplimiento", None),
)


def cargar_casos(version: str) -> list[dict[str, Any]]:
    """Todos los casos del corpus, con su dimensión y tipo normalizados."""
    raiz = paths.corpus_version(version)
    casos: list[dict[str, Any]] = []
    for archivo, dimension in (
        ("cases_robustness.jsonl", "robustez"),
        ("cases_security.jsonl", "seguridad"),
        ("cases_compliance.jsonl", "cumplimiento"),
    ):
        ruta = raiz / archivo
        if not ruta.is_file():
            raise SystemExit(f"falta {ruta}: construye el corpus antes de particionar")
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            if not linea.strip():
                continue
            fila = json.loads(linea)
            casos.append(
                {
                    "case_id": fila["case_id"],
                    "dimension": dimension,
                    "tipo": fila.get("tipo"),
                    "particion_plantilla": fila.get("particion_plantilla"),
                }
            )
    return casos


def _particion_previa(version: str) -> dict[str, str]:
    """La asignación de la versión de la que este corpus hereda, si la hay.

    Se lee del `base` que el MANIFEST declara, no de un nombre adivinado: es el mismo campo
    con el que el corpus dice de quién hereda su texto.
    """
    manifest = paths.corpus_version(version) / "MANIFEST.json"
    if not manifest.is_file():
        return {}
    base = json.loads(manifest.read_text(encoding="utf-8")).get("base")
    if not base or base == version:
        return {}
    destino = paths.splits_version(base)
    previa: dict[str, str] = {}
    for particion in (DEV, TEST):
        archivo = destino / f"{particion}.txt"
        if archivo.is_file():
            for case_id in archivo.read_text(encoding="utf-8").split():
                previa[case_id] = particion
    return previa


def particionar(
    casos: list[dict[str, Any]],
    *,
    seed: int,
    fraccion_dev: float,
    previa: dict[str, str] | None = None,
) -> dict[str, str]:
    """Asigna cada `case_id` a `dev` o `test`. Devuelve {case_id: partición}.

    `previa` es la asignación de la versión anterior del corpus, y con ella la partición es
    **estable frente a añadir casos**: un caso que ya tenía lado lo conserva, y los nuevos se
    reparten para acercar cada estrato a su fracción objetivo.

    Sin eso, añadir un caso rebaraja el estrato entero y mueve de partición casos que ya se
    midieron. Pasó al construir v1.4: el caso de cumplimiento nuevo empujó a `CUM-025` de
    desarrollo a prueba, y una corrida anterior habría quedado describiendo una partición que
    ya no existe.
    """
    asignacion: dict[str, str] = {}
    estratos: dict[tuple[str, str | None], list[str]] = {}
    heredada = previa or {}

    for caso in casos:
        # Regla 1: los ataques heredan la partición de su plantilla.
        if caso["particion_plantilla"] in (DEV, TEST):
            asignacion[caso["case_id"]] = caso["particion_plantilla"]
            continue
        estratos.setdefault((caso["dimension"], caso["tipo"]), []).append(caso["case_id"])

    # Regla 2: el resto, estratificado. Se ordena antes de barajar para que la asignación
    # no dependa del orden de lectura de los archivos.
    for clave in sorted(estratos, key=lambda c: (c[0], c[1] or "")):
        ids = sorted(estratos[clave])
        rng = random.Random(f"{seed}:{clave[0]}:{clave[1]}")
        rng.shuffle(ids)
        n_dev = round(len(ids) * fraccion_dev)

        # Regla 3: lo que ya tenía partición la conserva.
        nuevos = [i for i in ids if i not in heredada]
        for case_id in (i for i in ids if i in heredada):
            asignacion[case_id] = heredada[case_id]
        faltan_dev = n_dev - sum(1 for i in ids if asignacion.get(i) == DEV)
        for i, case_id in enumerate(nuevos):
            asignacion[case_id] = DEV if i < faltan_dev else TEST
    return asignacion


def contar(casos: list[dict[str, Any]], asignacion: dict[str, str]) -> list[dict[str, Any]]:
    """Conteos por fila de la tabla 4."""
    filas = []
    for etiqueta, dimension, tipo in FILAS:
        del_grupo = [
            c for c in casos if c["dimension"] == dimension and (tipo is None or c["tipo"] == tipo)
        ]
        dev = sum(1 for c in del_grupo if asignacion[c["case_id"]] == DEV)
        filas.append(
            {
                "etiqueta": etiqueta,
                "dev": dev,
                "test": len(del_grupo) - dev,
                "total": len(del_grupo),
            }
        )
    return filas


def tabla_markdown(filas: list[dict[str, Any]]) -> str:
    """Resumen de la partición: filas fijas y columnas Desarrollo / Prueba / Total."""
    lineas = [
        "| Dimensión y tipo | Desarrollo | Prueba | Total |",
        "|---|---:|---:|---:|",
    ]
    lineas.extend(f"| {f['etiqueta']} | {f['dev']} | {f['test']} | {f['total']} |" for f in filas)
    total = {
        "dev": sum(f["dev"] for f in filas),
        "test": sum(f["test"] for f in filas),
        "total": sum(f["total"] for f in filas),
    }
    lineas.append(
        f"| **Total** | **{total['dev']}** | **{total['test']}** | **{total['total']}** |"
    )
    return "\n".join(lineas)


def verificar(asignacion: dict[str, str], casos: list[dict[str, Any]]) -> list[str]:
    """Comprobaciones que deben pasar antes de escribir nada."""
    problemas: list[str] = []
    ids = [c["case_id"] for c in casos]
    if len(set(ids)) != len(ids):
        problemas.append("hay case_id repetidos en el corpus")
    sin_asignar = [i for i in ids if i not in asignacion]
    if sin_asignar:
        problemas.append(f"casos sin partición: {', '.join(sin_asignar[:5])}")
    for caso in casos:
        esperado = caso["particion_plantilla"]
        if esperado and asignacion.get(caso["case_id"]) != esperado:
            problemas.append(
                f"{caso['case_id']} usa plantilla de {esperado} pero quedó en "
                f"{asignacion.get(caso['case_id'])}"
            )
    return problemas


def escribir(
    asignacion: dict[str, str], filas: list[dict[str, Any]], version: str, seed: int
) -> dict[str, Path]:
    """Escribe dev.txt, test.txt y summary.md."""
    destino = paths.splits_version(version)
    destino.mkdir(parents=True, exist_ok=True)

    salidas = {}
    for particion in (DEV, TEST):
        ids = sorted(i for i, p in asignacion.items() if p == particion)
        archivo = destino / f"{particion}.txt"
        archivo.write_text("\n".join(ids) + "\n", encoding="utf-8")
        salidas[particion] = archivo

    total_dev = sum(f["dev"] for f in filas)
    total = sum(f["total"] for f in filas)
    resumen = destino / "summary.md"
    resumen.write_text(
        "\n".join(
            [
                f"# Particiones del corpus {version}",
                "",
                f"Semilla `{seed}`. Partición por `case_id`, estratificada por dimensión y "
                "tipo, con una proporción objetivo de 30 % desarrollo y 70 % prueba.",
                "",
                "Los casos de seguridad con carga adversarial **no se sortean**: heredan la "
                "partición de la plantilla con que fueron construidos "
                "(`data/templates/attacks/dev/` o `.../test/`). Es lo que impide que una "
                "formulación de ataque vista durante el ajuste reaparezca en la medición.",
                "",
                tabla_markdown(filas),
                "",
                f"Proporción efectiva de desarrollo: {total_dev / total:.1%} "
                f"({total_dev} de {total} casos).",
                "",
            ]
        ),
        encoding="utf-8",
    )
    salidas["summary"] = resumen
    return salidas


def main(argv: list[str] | None = None) -> int:
    """Particiona el corpus, o comprueba con `--check` que la partición no tiene fugas."""
    experimentos = load_experiments()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--version",
        default=experimentos["corpus_version"],
        help="Versión del corpus que se particiona.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=experimentos["splits"]["seed"],
        help="Semilla de la partición. Cambiarla mueve casos ya medidos.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verifica las particiones ya escritas y no las sobrescribe.",
    )
    args = parser.parse_args(argv)

    casos = cargar_casos(args.version)
    fraccion = experimentos["splits"]["dev_fraction"]

    if args.check:
        destino = paths.splits_version(args.version)
        leidos: dict[str, str] = {}
        for particion in (DEV, TEST):
            archivo = destino / f"{particion}.txt"
            if not archivo.is_file():
                raise SystemExit(f"falta {archivo}")
            for case_id in archivo.read_text(encoding="utf-8").split():
                if case_id in leidos:
                    raise SystemExit(f"{case_id} aparece en ambas particiones")
                leidos[case_id] = particion
        problemas = verificar(leidos, casos)
        if problemas:
            print("Problemas:\n  " + "\n  ".join(problemas))
            return 1
        print(f"Particiones correctas: {len(leidos)} casos, ninguno repetido.")
        return 0

    asignacion = particionar(
        casos, seed=args.seed, fraccion_dev=fraccion, previa=_particion_previa(args.version)
    )
    problemas = verificar(asignacion, casos)
    if problemas:
        print("No se escribió nada. Problemas:\n  " + "\n  ".join(problemas))
        return 1

    filas = contar(casos, asignacion)
    salidas = escribir(asignacion, filas, args.version, args.seed)

    print(tabla_markdown(filas))
    print()
    for nombre, ruta in salidas.items():
        print(f"  {nombre}: {ruta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
