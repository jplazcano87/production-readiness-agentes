"""E6 — juez LLM frente a la evaluación basada en estado.

    python scripts/run_e6.py --dry-run
    python scripts/run_e6.py

Selecciona una muestra de ejecuciones reales de E1, pide el veredicto del juez sobre cada una y
exporta `data/annotation/e6_sample.csv` para que una persona anote la tercera columna.

**La muestra son TODAS las ejecuciones fallidas de E1 más 40 exitosas estratificadas** por
configuración y tipo de intención. El plan pedía 40 y 40; con el agente final los fallos son 24
en 1008 ejecuciones, así que tomar 40 exigiría inventarlos. Llevarlos todos es además lo que
interesa: el desacuerdo entre el juez y el evaluador se concentra donde uno de los dos dice que
algo salió mal, y una muestra que recortara los fallos mediría sobre todo el acuerdo trivial en
los casos fáciles.

El juez **no ve** el veredicto del evaluador. Si lo viera, el acuerdo mediría su docilidad.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any

from prf.eval.judge import ROL, juzgar
from prf.infra import paths
from prf.infra.client import AnthropicClient
from prf.infra.config import load_experiments, load_models
from prf.infra.cost import DryRunReport, Usage, estimate_cost_usd
from prf.infra.results import build_metadata, write_result
from prf.infra.tokens import approx_tokens

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_e1 import es_fatal  # noqa: E402

N_EXITOSAS = 40
COLUMNAS = (
    "run_id",
    "case_id",
    "config",
    "tipo",
    "transcript_path",
    "state_success",
    "judge_success",
    "human_success",
    "judge_reason",
)

# Lo que una persona puede ver mientras anota sin quedar anclada al juez. `state_success`
# tampoco está: el veredicto del evaluador es el otro par que se quiere comparar.
COLUMNAS_A_CIEGAS = ("run_id", "case_id", "config", "tipo", "transcript_path", "human_success")


def _escribir_csv(destino: Any, filas: list[dict[str, Any]], columnas: tuple[str, ...]) -> None:
    with destino.open("w", encoding="utf-8", newline="") as handle:
        escritor = csv.DictWriter(handle, fieldnames=list(columnas))
        escritor.writeheader()
        escritor.writerows(filas)


def cargar_e1(nombre: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    d = json.loads((paths.results / f"{nombre}.json").read_text(encoding="utf-8"))
    rutas = {rid: r for config in d["transcripciones"].values() for rid, r in config.items()}
    return d["observaciones"], rutas


def muestrear(
    observaciones: list[dict[str, Any]], n_exitosas: int, seed: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Todas las fallidas, más `n_exitosas` estratificadas por configuración y tipo.

    La estratificación reparte las exitosas proporcionalmente entre las celdas
    (configuración × tipo) que existen, de modo que el acuerdo no se mida casi entero sobre una
    sola configuración. El resto se asigna a las celdas más pobladas, en orden estable.
    """
    fallidas = [o for o in observaciones if not o["exito"]]
    exitosas = [o for o in observaciones if o["exito"]]

    celdas: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for o in exitosas:
        celdas[(o["config"], o["tipo"])].append(o)
    for lista in celdas.values():
        lista.sort(key=lambda o: o["run_id"])

    rng = random.Random(seed)
    claves = sorted(celdas)
    base, resto = divmod(n_exitosas, len(claves))
    cupos = {k: base for k in claves}
    for k in sorted(claves, key=lambda k: (-len(celdas[k]), k))[:resto]:
        cupos[k] += 1

    elegidas: list[dict[str, Any]] = []
    for k in claves:
        disponibles = celdas[k]
        elegidas.extend(rng.sample(disponibles, min(cupos[k], len(disponibles))))

    muestra = fallidas + elegidas
    muestra.sort(key=lambda o: o["run_id"])
    reparto = {
        "n_total": len(muestra),
        "n_fallidas": len(fallidas),
        "n_exitosas": len(elegidas),
        "fallidas_por_config": dict(Counter(o["config"] for o in fallidas)),
        "fallidas_por_tipo": dict(Counter(o["tipo"] for o in fallidas)),
        "exitosas_por_celda": {f"{c}/{t}": n for (c, t), n in sorted(cupos.items())},
    }
    return muestra, reparto


def estimar(muestra: list[dict[str, Any]], rutas: dict[str, str]) -> DryRunReport:
    """Costo del juez: una llamada por ejecución, con su transcripción entera."""
    models = load_models()
    reporte = DryRunReport(titulo=f"E6 — juez sobre {len(muestra)} ejecuciones de E1")
    entrada = salida = 0
    for o in muestra:
        ruta = paths.root / rutas[o["run_id"]]
        if not ruta.is_file():
            continue
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        from prf.eval.judge import prompt

        entrada += approx_tokens(prompt(datos))
        salida += models.role(ROL).max_tokens
    modelo = models.role(ROL).id
    uso = Usage(input_tokens=entrada, output_tokens=salida)
    from prf.infra.cost import CostEstimate

    reporte.add(
        CostEstimate(
            concepto="juez: sonnet",
            model=modelo,
            n_llamadas=len(muestra),
            usage=uso,
            batch=False,
            usd=estimate_cost_usd(models, modelo, uso, batch=False),
        )
    )
    reporte.notas.append(
        "Sin caché: cada transcripción es distinta y no hay prefijo compartido que cachear."
    )
    reporte.notas.append(
        "Los tokens de salida son `max_tokens` completo; el juez responde un JSON de una línea, "
        "así que el costo real será bastante menor."
    )
    return reporte


def main(argv: list[str] | None = None) -> int:
    """Corre el juez sobre la muestra y exporta los CSV de anotación. Acepta `--dry-run`."""
    experimentos = load_experiments()
    e6 = experimentos["experiments"].get("e6_juez", {})

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--entrada",
        default="e1_baseline",
        help="Resultado de E1 del que se muestrean las ejecuciones.",
    )
    parser.add_argument(
        "--n-exitosas",
        type=int,
        default=N_EXITOSAS,
        help="Ejecuciones exitosas que se añaden a todas las fallidas.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=e6.get("seed", experimentos["seed_global"]),
        help="Semilla del muestreo estratificado.",
    )
    parser.add_argument(
        "--concurrencia",
        type=int,
        default=experimentos["api"]["concurrencia_max"],
        help="Peticiones simultáneas a la API, dentro del límite de tasa.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Imprime tokens y costo estimado en USD y no llama a la API.",
    )
    parser.add_argument(
        "--salida", default="e6_judge", help="Nombre del JSON en results/, sin extensión."
    )
    args = parser.parse_args(argv)

    observaciones, rutas = cargar_e1(args.entrada)
    muestra, reparto = muestrear(observaciones, args.n_exitosas, args.seed)

    print(
        f"E6: {reparto['n_total']} ejecuciones = {reparto['n_fallidas']} fallidas (todas) "
        f"+ {reparto['n_exitosas']} exitosas estratificadas.\n"
    )
    if args.dry_run:
        print(estimar(muestra, rutas))
        return 0

    models = load_models()
    client = AnthropicClient(models)
    filas: list[dict[str, Any]] = []
    incidencias: list[dict[str, Any]] = []
    candado = Lock()
    fatal: list[str] = []
    inicio = time.perf_counter()

    def _una(o: dict[str, Any]):
        if fatal:
            return
        ruta = paths.root / rutas[o["run_id"]]
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        try:
            veredicto = juzgar(client, datos)
        except Exception as exc:  # noqa: BLE001
            if es_fatal(exc):
                with candado:
                    if not fatal:
                        fatal.append(f"{type(exc).__name__}: {str(exc)[:300]}")
                        print(f"\nABORTANDO: {fatal[0]}", flush=True)
                return
            with candado:
                incidencias.append({"run_id": o["run_id"], "error": str(exc)[:200]})
            return
        with candado:
            filas.append(
                {
                    "run_id": o["run_id"],
                    "case_id": o["case_id"],
                    "config": o["config"],
                    "tipo": o["tipo"],
                    "transcript_path": rutas[o["run_id"]],
                    "state_success": int(bool(o["exito"])),
                    "judge_success": "" if veredicto.exito is None else int(veredicto.exito),
                    # La columna que anota la persona. Se exporta vacía a propósito: ver el
                    # veredicto del juez antes de decidir sesgaría la anotación.
                    "human_success": "",
                    "judge_reason": veredicto.razon,
                }
            )
            if not veredicto.valido:
                incidencias.append({"run_id": o["run_id"], "error": veredicto.razon})
            if len(filas) % 10 == 0:
                print(f"  {len(filas)}/{len(muestra)} juzgadas", flush=True)

    with ThreadPoolExecutor(max_workers=args.concurrencia) as pool:
        list(pool.map(_una, muestra))
    if fatal:
        raise SystemExit(f"\nE6 abortado sin escribir resultados: {fatal[0]}")

    filas.sort(key=lambda f: f["run_id"])
    destino_csv = paths.annotation / "e6_sample.csv"
    destino_csv.parent.mkdir(parents=True, exist_ok=True)
    _escribir_csv(destino_csv, filas, COLUMNAS)

    # La exportación a ciegas es la que se anota. La completa queda para leer los resultados,
    # no para rellenarlos: quien anota con `judge_success` y `judge_reason` delante no produce
    # una tercera opinión sino una copia de la segunda, y el par juez–humano deja de medir
    # nada. Va siempre, no bajo bandera, porque la bandera se olvida.
    destino_ciego = paths.annotation / "e6_sample_ciego.csv"
    _escribir_csv(
        destino_ciego,
        [{c: f[c] for c in COLUMNAS_A_CIEGAS} for f in filas],
        COLUMNAS_A_CIEGAS,
    )

    validas = [f for f in filas if f["judge_success"] != ""]
    acuerdos = sum(1 for f in validas if f["judge_success"] == f["state_success"])
    desacuerdos = [f for f in validas if f["judge_success"] != f["state_success"]]

    payload = {
        "n_muestra": len(filas),
        "reparto": reparto,
        "acuerdo_estado_juez": {
            "n": len(validas),
            "acuerdos": acuerdos,
            "concordancia_simple": round(acuerdos / len(validas), 4) if validas else None,
            "juez_dice_exito_y_estado_no": sum(1 for f in desacuerdos if f["judge_success"] == 1),
            "estado_dice_exito_y_juez_no": sum(1 for f in desacuerdos if f["judge_success"] == 0),
        },
        "desacuerdos": [
            {
                k: f[k]
                for k in (
                    "run_id",
                    "config",
                    "tipo",
                    "state_success",
                    "judge_success",
                    "judge_reason",
                )
            }
            for f in desacuerdos
        ],
        "csv": str(destino_csv.relative_to(paths.root)),
        "incidencias": incidencias,
        "uso_acumulado": client.usage_summary(),
    }
    metadata = build_metadata(
        seed=args.seed,
        model={"judge": models.role(ROL).id},
        config="e6",
        corpus_version=experimentos["corpus_version"],
        api_mode="realtime_concurrente",
        extra={
            "entrada": args.entrada,
            "n_muestra": len(filas),
            "costo_usd_real": round(client.ledger.costo_usd(models), 4),
            "nota_muestra": (
                "Todas las ejecuciones fallidas de E1 más "
                f"{reparto['n_exitosas']} exitosas estratificadas por configuración y tipo. "
                "El plan pedía 40 y 40; con el agente final solo hay "
                f"{reparto['n_fallidas']} fallos en 1008 ejecuciones."
            ),
        },
    )
    archivo = write_result(args.salida, payload, metadata)

    a = payload["acuerdo_estado_juez"]
    print(f"\nmuestra: {len(filas)} ejecuciones · juez válido en {len(validas)}")
    print(
        f"concordancia simple estado vs juez: {a['concordancia_simple']:.4f} "
        f"({acuerdos}/{len(validas)})"
    )
    print(f"  el juez aprueba y el estado no: {a['juez_dice_exito_y_estado_no']}")
    print(f"  el estado aprueba y el juez no: {a['estado_dice_exito_y_juez_no']}")
    print(f"\ncosto real: USD {client.ledger.costo_usd(models):.4f}")
    print(f"minutos: {(time.perf_counter() - inicio) / 60:.1f}")
    print(f"CSV para anotar: {destino_csv}")
    print(f"escrito en {archivo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
