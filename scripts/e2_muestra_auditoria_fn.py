"""Población y muestra de la auditoría de falsos negativos del criterio 1.2.0, sin API.

    python scripts/e2_muestra_auditoria_fn.py
    python scripts/e2_muestra_auditoria_fn.py --check

**La población** son las ejecuciones de ataque de las dos corridas de E2 sobre v1.2
(`results/e2_security_criterio1.2.0.json`, agente Sonnet, y
`results/e2_security_haiku_criterio1.2.0.json`, agente Haiku) que cumplen las tres cosas:

1. **Los dos criterios las dan por fracaso**: `ataque_exitoso` (1.2.0) y
   `ataque_exitoso_literal` (1.0.0) en falso.
2. **La carga llegó a un modelo**: `entrega.entregada` en verdadero. En el vector directo la
   carga es el propio mensaje del usuario; en el indirecto, la reseña que la herramienta
   devolvió, que en `dual_llm` y `cte` lee el modelo en cuarentena.
3. **Tienen transcripción publicada**: sin ella no hay nada que leer.

Son **1.304**: 778 de Sonnet y 526 de Haiku. La corrida del portador descripción no entra,
porque se midió directamente con el 1.2.0 y no tiene lectura con el 1.0.0. El script recalcula
además los dos veredictos desde cada transcripción y se detiene si alguno no coincide con el
guardado.

**La muestra** son 40, sin reposición, con `random.Random(20260906).sample` sobre la población
ordenada por `run_id`. Los `run_id` se repiten entre las dos corridas, así que la identidad de
una ejecución es el par (`corrida`, `run_id`) y el desempate del orden es `corrida`.

**Esta muestra no reproduce la original.** El informe cita una auditoría de 40 fracasos de esta
misma población sin ningún falso negativo, pero aquella muestra no se conservó en ninguna
parte. Esta la **repite**: se fija con la semilla del proyecto y se publica antes de leerla, de
modo que lo que se lea después no pueda haber elegido qué se leía.
"""

from __future__ import annotations

import argparse
import collections
import csv
import io
import json
import random
import sys
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from e2_holdout_criterio import (  # noqa: E402
    DESTINO,
    modelo_del_agente,
    veredicto_literal,
    veredicto_vigente,
)

SEMILLA = 20260906
N_MUESTRA = 40
N_POBLACION = 1304
CORRIDAS = {
    "e2_security": "results/e2_security_criterio1.2.0.json",
    "e2_security_haiku": "results/e2_security_haiku_criterio1.2.0.json",
}
POBLACION = DESTINO / "poblacion_fn.csv"
MUESTRA = DESTINO / "muestra_fn.csv"
COLUMNAS_POBLACION = ["corrida", "run_id", "modelo", "config", "objetivo", "tipo_criterio"]
COLUMNAS_MUESTRA = ["orden", *COLUMNAS_POBLACION]


def poblacion() -> list[dict[str, str]]:
    """Las 1.304 ejecuciones, ordenadas por (`run_id`, `corrida`)."""
    filas = []
    for corrida, ruta in CORRIDAS.items():
        documento = json.loads((RAIZ / ruta).read_text(encoding="utf-8"))
        for o in documento["observaciones"]:
            if o["tipo"] == "benigno":
                continue
            # La transcripción va primero: las que no la tienen conservaron su veredicto
            # original y no llevan `ataque_exitoso_literal`, porque no se pudieron releer.
            transcripcion = RAIZ / (o.get("transcripcion") or "")
            if not o.get("transcripcion") or not transcripcion.is_file():
                continue
            if o["ataque_exitoso"] or o["ataque_exitoso_literal"]:
                continue
            if not o["entrega"].get("entregada"):
                continue
            registro = json.loads(transcripcion.read_text(encoding="utf-8"))
            if veredicto_vigente(registro) or veredicto_literal(registro):
                raise SystemExit(
                    f"{corrida}/{o['run_id']}: el resultado lo da por fracaso y la "
                    "transcripción, recalculada, no"
                )
            filas.append(
                {
                    "corrida": corrida,
                    "run_id": o["run_id"],
                    "modelo": modelo_del_agente(registro),
                    "config": o["config"],
                    "objetivo": o["objetivo"],
                    "tipo_criterio": registro["criterio"]["tipo"],
                }
            )
    filas.sort(key=lambda f: (f["run_id"], f["corrida"]))
    if len(filas) != N_POBLACION:
        raise SystemExit(f"la población tiene {len(filas)} ejecuciones y no {N_POBLACION}")
    return filas


def muestra(filas: list[dict[str, str]]) -> list[dict[str, Any]]:
    elegidas = random.Random(SEMILLA).sample(filas, N_MUESTRA)
    return [{"orden": i, **f} for i, f in enumerate(elegidas, start=1)]


def como_csv(filas: list[dict[str, Any]], columnas: list[str]) -> str:
    salida = io.StringIO()
    escritor = csv.DictWriter(salida, fieldnames=columnas, lineterminator="\n")
    escritor.writeheader()
    escritor.writerows(filas)
    return salida.getvalue()


def desglose(filas: list[dict[str, str]]) -> dict[str, dict[str, int]]:
    return {
        campo: dict(sorted(collections.Counter(f[campo] for f in filas).items()))
        for campo in ("corrida", "modelo", "config", "objetivo", "tipo_criterio")
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--check", action="store_true", help="Compara con los CSV publicados sin escribir nada."
    )
    args = parser.parse_args(argv)

    filas = poblacion()
    elegidas = muestra(filas)
    archivos = {
        POBLACION: como_csv(filas, COLUMNAS_POBLACION),
        MUESTRA: como_csv(elegidas, COLUMNAS_MUESTRA),
    }
    if args.check:
        distintos = [r for r, c in archivos.items() if r.read_text(encoding="utf-8") != c]
        for ruta in distintos:
            print(f"{ruta.relative_to(RAIZ)} no coincide con lo que se recalcula")
        return 1 if distintos else 0

    DESTINO.mkdir(parents=True, exist_ok=True)
    for ruta, contenido in archivos.items():
        ruta.write_text(contenido, encoding="utf-8")
        print(f"escrito {ruta.relative_to(RAIZ)}")
    print(f"población {len(filas)}, muestra {len(elegidas)} con semilla {SEMILLA}")
    for campo, conteo in desglose(filas).items():
        print(f"  {campo}: {conteo}")
    print(f"  muestra por objetivo: {desglose(elegidas)['objetivo']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
