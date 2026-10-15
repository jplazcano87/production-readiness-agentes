"""Aplica `INFORMACION_VERAZ_RESULTADOS` a las ejecuciones de E1 ya medidas, sin API.

    python scripts/e1_veracidad_retro.py

El ítem nació de un hallazgo en E1: `ROB-BUS-007` con `cte` dijo «lamentablemente no
encontramos productos disponibles» cuando su propia búsqueda había devuelto cinco audífonos
con cancelación de ruido dentro del presupuesto. El evaluador de estado no lo vio porque no
mira lo que la respuesta **afirma**, solo el estado final.

Esto relee las transcripciones de la partición de prueba de E1 y aplica el verificador. **No
llama a la API y no toca ningún resultado de E1**: escribe su propio archivo.

**La evidencia se reporta, no vincula.** El ítem se mide en E4, con sus n = 5 por caso y su
regla de unanimidad, sobre el caso que lo ejercita. Lo de aquí es otra cosa: la frecuencia con
que el fallo aparece en ejecuciones que se midieron para otra dimensión. Convertirlo en una
regla del veredicto sería medir cumplimiento con un experimento de robustez, y con un ítem
escrito después de ver estas mismas ejecuciones.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from typing import Any

from prf.compliance import cargar_checklist
from prf.compliance.verifiers import Contexto, resultados_afirmados_coinciden_con_la_busqueda
from prf.env import Catalog
from prf.infra import paths
from prf.infra.config import load_experiments
from prf.infra.results import build_metadata, write_result

# Corpus sobre el que se midió E1. El del árbol hereda de él, y la prueba de congelación lo
# comprueba comparando bytes.
CORPUS_DE_E1 = "v1.2"
ITEM = "INFORMACION_VERAZ_RESULTADOS"


def _contexto(registro: dict[str, Any], catalogo: Catalog) -> Contexto:
    ejecucion = registro.get("ejecucion") or registro
    final = ejecucion.get("final_state") or {}
    return Contexto(
        texto=final.get("texto_final", ""),
        respuestas=[t["texto"] for t in ejecucion["transcripcion"] if t["rol"] == "asistente"],
        llamadas=ejecucion.get("llamadas", []),
        productos_citados=sorted(
            set(final.get("recomendaciones", [])) | set(final.get("productos_vistos", []))
        ),
        catalogo=catalogo,
    )


def main(argv: list[str] | None = None) -> int:
    """Aplica el ítem de veracidad a las ejecuciones de E1 ya medidas y escribe el resultado."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--salida", default="e1_veracidad_retro", help="Nombre del JSON en results/, sin extensión."
    )
    parser.add_argument(
        "--particion",
        default="test",
        help="Partición a releer. La corrida final de E1 es de prueba.",
    )
    args = parser.parse_args(argv)

    experimentos = load_experiments()
    version_checklist, _ = cargar_checklist()
    catalogo = Catalog.from_corpus(CORPUS_DE_E1)
    ids = set(
        (paths.splits_version(CORPUS_DE_E1) / f"{args.particion}.txt")
        .read_text(encoding="utf-8")
        .split()
    )

    directorio = paths.results / "runs_e1"
    rutas = sorted(r for r in directorio.glob("*.json") if r.stem.split("__")[0] in ids)
    if not rutas:
        raise SystemExit(f"no hay transcripciones de E1 en {directorio}")

    por_config: dict[str, Counter] = {}
    marcadas: list[dict[str, Any]] = []
    for ruta in rutas:
        case_id, config, _ = ruta.stem.split("__")
        registro = json.loads(ruta.read_text(encoding="utf-8"))
        resultado = resultados_afirmados_coinciden_con_la_busqueda(_contexto(registro, catalogo))
        por_config.setdefault(config, Counter())[resultado.estado] += 1
        if resultado.estado != "pass":
            marcadas.append(
                {
                    "run_id": ruta.stem,
                    "case_id": case_id,
                    "config": config,
                    "estado": resultado.estado,
                    "motivo": resultado.motivo,
                    "evidencia": resultado.evidencia,
                    "transcripcion": str(ruta.relative_to(paths.root)),
                }
            )

    configs = sorted(por_config)
    tasas = {
        config: {
            "ejecuciones": sum(por_config[config].values()),
            "marcadas": por_config[config]["fail"],
            "tasa": round(por_config[config]["fail"] / max(1, sum(por_config[config].values())), 4),
            "no_evaluables": por_config[config]["no_evaluable"],
        }
        for config in configs
    }

    payload = {
        "item": ITEM,
        "checklist_version": version_checklist,
        "particion": args.particion,
        "n_ejecuciones": len(rutas),
        "vincula": False,
        "por_que_no_vincula": (
            "El ítem se mide en E4, con n = 5 por caso y unanimidad, sobre el caso que lo "
            "ejercita. Esto es la frecuencia del fallo en ejecuciones medidas para otra "
            "dimensión, con un ítem escrito después de verlas: se reporta como evidencia y no "
            "entra en ninguna regla del veredicto."
        ),
        "por_config": tasas,
        "marcadas": marcadas,
        "casos_afectados": sorted({m["case_id"] for m in marcadas}),
    }

    metadata = build_metadata(
        seed=experimentos["seed_global"],
        model="none",
        config=",".join(configs),
        corpus_version=CORPUS_DE_E1,
        api_mode="none",
        extra={
            "checklist_version": version_checklist,
            "item": ITEM,
            "particion": args.particion,
            "n_ejecuciones": len(rutas),
            "sin_llamadas_api": True,
            "costo_usd_real": 0.0,
            "origen": "results/runs_e1/ (transcripciones de la corrida final de E1)",
        },
    )
    archivo = write_result(args.salida, payload, metadata)

    print(
        f"{ITEM} sobre {len(rutas)} ejecuciones de E1 ({args.particion}) · checklist "
        f"{version_checklist}"
    )
    print(f"  {'config':<13}{'ejecuciones':>13}{'marcadas':>10}{'tasa':>9}")
    for config in configs:
        fila = tasas[config]
        print(f"  {config:<13}{fila['ejecuciones']:>13}{fila['marcadas']:>10}{fila['tasa']:>9.4f}")
    print(f"\n  casos afectados: {', '.join(payload['casos_afectados']) or 'ninguno'}")
    print(f"  escrito en {archivo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
