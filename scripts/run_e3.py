"""E3 — latencia: TTFT y latencia extremo a extremo, con las 4 configuraciones intercaladas.

    python scripts/run_e3.py --dry-run
    python scripts/run_e3.py

API en tiempo real, streaming y **sin** prompt caching: es una decisión cerrada del proyecto.
Medir latencia con la caché caliente mediría el estado de la caché y no la defensa, y un lote
no tiene TTFT que medir.

**Las cuatro configuraciones se ejecutan intercaladas** —none, prompt_only, dual_llm, cte,
none, …— y de forma **secuencial**, no concurrente. Dos razones: la variación del servicio se
reparte por igual entre las cuatro, y cuatro peticiones simultáneas se estorban entre sí, con
lo que se mediría la contención del cliente en vez de la latencia del sistema.

Se registra por llamada el `request_id`, el momento y el modo de API, y se reporta por
configuración p50, p95, el porcentaje de muestras por encima de 5 s y el sobrecosto frente a
`none` como razón de p95 **y** de p50. En `cte` y `dual_llm` se desglosa además el TTFT por
llamada interna, porque su TTFT visible no es el primer token del modelo sino el instante en
que el usuario ve algo.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from prf.agent import obtener
from prf.agent.bucle import ejecutar_caso
from prf.env import Catalog, Sandbox
from prf.env.cases import CasoSeguridad
from prf.infra import paths
from prf.infra.client import AnthropicClient
from prf.infra.config import load_experiments, load_models
from prf.infra.corrida import (
    EstadoCorrida,
    TopeDeGasto,
    resumen_piloto,
    verificar_piloto,
)
from prf.infra.cost import DryRunReport, Usage
from prf.infra.results import build_metadata, write_result
from prf.infra.tracking import Tracker

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_e1 import FRACCION_SONNET, PERFIL_MEDIDO, es_fatal  # noqa: E402
from run_e2 import _estimacion  # noqa: E402

UMBRAL_LENTO_S = 5.0


def cargar_casos(version: str, split: str, n_casos: int) -> list[CasoSeguridad]:
    """Los primeros `n_casos` benignos de la partición, por id: la selección es reproducible."""
    ids = set((paths.splits_version(version) / f"{split}.txt").read_text(encoding="utf-8").split())
    archivo = paths.corpus_version(version) / "cases_security.jsonl"
    casos = [
        caso
        for linea in archivo.read_text(encoding="utf-8").splitlines()
        if linea.strip()
        for caso in [CasoSeguridad.model_validate_json(linea)]
        if caso.case_id in ids and caso.tipo == "benigno"
    ]
    return sorted(casos, key=lambda c: c.case_id)[:n_casos]


def estimar(configs: list[str], n_casos: int, n_reps: int, con_cache: bool = False) -> DryRunReport:
    """Sin caché cada llamada paga el prefijo entero, que es lo que encarece E3.

    Con caché —E3b— el prefijo se lee en vez de enviarse, así que el costo cae a algo
    parecido al de E1. Estimarlo con el perfil frío daría una cifra muy por encima y podría
    hacer descartar la corrida por un costo que no es el suyo.
    """
    models = load_models()
    reporte = DryRunReport(
        titulo=(
            f"E3{'b' if con_cache else ''} — {n_casos} casos benignos × {n_reps} "
            f"repeticiones × {len(configs)} configuraciones "
            f"({'con' if con_cache else 'sin'} caché)"
        )
    )
    for config in configs:
        ejecuciones = n_casos * n_reps
        fraccion = FRACCION_SONNET[config]
        perfil = PERFIL_MEDIDO[config]
        # Sin caché, lo que se leía de caché se paga como entrada normal.
        entrada = (
            perfil["input_tokens"]
            if con_cache
            else perfil["input_tokens"]
            + perfil["cache_read_tokens"]
            + perfil["cache_creation_tokens"]
        )
        for etiqueta, modelo, parte in (
            (f"{config}: sonnet", models.role("agent").id, fraccion),
            (f"{config}: haiku", models.role("quarantine").id, 1 - fraccion),
        ):
            if parte <= 0:
                continue
            uso = Usage(
                input_tokens=int(entrada * ejecuciones * parte),
                output_tokens=int(perfil["output_tokens"] * ejecuciones * parte),
                cache_read_tokens=(
                    int(perfil["cache_read_tokens"] * ejecuciones * parte) if con_cache else 0
                ),
                cache_creation_tokens=(
                    int(perfil["cache_creation_tokens"] * ejecuciones * parte) if con_cache else 0
                ),
            )
            reporte.add(_estimacion(models, etiqueta, modelo, ejecuciones, uso, batch=False))
    reporte.notas.append(
        "Sin prompt caching: lo que en E1 y E2 se leía de caché aquí se paga como entrada "
        "normal, así que E3 cuesta más por ejecución aunque tenga muchas menos."
        if not con_cache
        else "Con prompt caching (E3b): el prefijo se lee en vez de enviarse, así que cuesta "
        "menos de la mitad que la corrida en frío."
    )
    reporte.notas.append(
        "Secuencial y no concurrente: cuatro peticiones a la vez se estorban y se mediría la "
        "contención del cliente, no la latencia del sistema. Cuenta con ~1 h de reloj."
    )
    return reporte


def _percentil(valores: list[float], q: float) -> float | None:
    if not valores:
        return None
    orden = sorted(valores)
    if len(orden) == 1:
        return orden[0]
    return float(statistics.quantiles(orden, n=100, method="inclusive")[int(q * 100) - 1])


def resumir(muestras: list[dict[str, Any]], configs: list[str]) -> dict[str, Any]:
    """Agrega las repeticiones de cada configuración en los percentiles que el informe cita."""
    por_config = defaultdict(list)
    for m in muestras:
        por_config[m["config"]].append(m)

    salida: dict[str, Any] = {}
    for config in configs:
        ms = por_config.get(config, [])
        ttft = [m["ttft_visible_s"] for m in ms if m["ttft_visible_s"] is not None]
        total = [m["latency_s"] for m in ms if m["latency_s"] is not None]
        por_rol: dict[str, list[float]] = defaultdict(list)
        for m in ms:
            for rol, valores in (m.get("ttft_por_rol") or {}).items():
                por_rol[rol].extend(valores)
        salida[config] = {
            "n": len(ms),
            "ttft_visible_s": {
                "p50": _percentil(ttft, 0.50),
                "p95": _percentil(ttft, 0.95),
                "media": round(statistics.fmean(ttft), 4) if ttft else None,
                "pct_sobre_5s": (
                    round(100 * sum(t > UMBRAL_LENTO_S for t in ttft) / len(ttft), 2)
                    if ttft
                    else None
                ),
            },
            "latencia_total_s": {
                "p50": _percentil(total, 0.50),
                "p95": _percentil(total, 0.95),
                "pct_sobre_5s": (
                    round(100 * sum(t > UMBRAL_LENTO_S for t in total) / len(total), 2)
                    if total
                    else None
                ),
            },
            # El TTFT visible de `cte` es el instante en que el intérprete compone la
            # respuesta, no el primer token del planificador: sin este desglose no se sabe
            # dónde se va el tiempo.
            "ttft_por_llamada_interna": {
                rol: {"n": len(v), "p50": _percentil(v, 0.50), "p95": _percentil(v, 0.95)}
                for rol, v in sorted(por_rol.items())
            },
        }

    base = salida.get("none", {}).get("ttft_visible_s", {})
    for config in configs:
        t = salida[config]["ttft_visible_s"]
        salida[config]["sobrecosto_vs_none"] = {
            "razon_p95": (
                round(t["p95"] / base["p95"], 3) if t["p95"] and base.get("p95") else None
            ),
            "razon_p50": (
                round(t["p50"] / base["p50"], 3) if t["p50"] and base.get("p50") else None
            ),
        }
    return salida


def main(argv: list[str] | None = None) -> int:
    """Corre E3 y escribe su JSON canónico. Acepta `--dry-run`, que no llama a la API."""
    experimentos = load_experiments()
    e3 = experimentos["experiments"]["e3_latencia"]

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--configs",
        nargs="+",
        default=list(e3["configs"]),
        help="Configuraciones de defensa a medir, separadas por espacio.",
    )
    parser.add_argument(
        "--n-casos",
        type=int,
        default=e3["n_casos"],
        help="Casos benignos distintos sobre los que se mide la latencia.",
    )
    parser.add_argument(
        "--reps",
        type=int,
        default=e3["n_repeticiones"],
        help="Repeticiones por caso: el TTFT varía mucho entre ejecuciones idénticas.",
    )
    parser.add_argument(
        "--split", default=e3["split"], help="Partición del corpus: dev, test o todos."
    )
    parser.add_argument(
        "--version",
        default=experimentos["corpus_version"],
        help="Versión del corpus congelado sobre la que se mide.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Imprime tokens y costo estimado en USD y no llama a la API.",
    )
    parser.add_argument(
        "--reanudar",
        action="store_true",
        help="Salta las repeticiones que ya tienen su archivo en results/runs_e3/.",
    )
    parser.add_argument(
        "--sin-piloto", action="store_true", help="Omite el piloto previo de 3 casos."
    )
    parser.add_argument(
        "--con-cache",
        action="store_true",
        help=(
            "E3b: mismo protocolo con prompt caching. La decisión cerrada es que E3 va sin "
            "caché; esta variante mide qué parte de la latencia la ahorra la caché."
        ),
    )
    parser.add_argument(
        "--mlflow",
        action="store_true",
        help="Registra la corrida en MLflow, además del JSON canónico.",
    )
    parser.add_argument(
        "--salida",
        default=None,
        help="Nombre del JSON en results/, sin extensión. Por omisión, e3_latency.",
    )
    args = parser.parse_args(argv)
    if args.salida is None:
        args.salida = "e3_latency_warm" if args.con_cache else "e3_latency"

    casos = cargar_casos(args.version, args.split, args.n_casos)
    if not casos:
        raise SystemExit("no hay casos benignos en esa partición")

    if args.dry_run:
        print(estimar(args.configs, len(casos), args.reps, args.con_cache))
        return 0

    models = load_models()
    client = AnthropicClient(models)
    catalogo = Catalog.from_corpus(args.version)
    directorio = paths.results / "runs_e3"
    directorio.mkdir(parents=True, exist_ok=True)

    muestras: list[dict[str, Any]] = []
    incidencias: list[dict[str, Any]] = []
    estado = EstadoCorrida(
        salida=args.salida,
        directorio=paths.results,
        estimacion_usd=estimar(args.configs, len(casos), args.reps, args.con_cache).total_usd,
    )
    if args.reanudar:
        ids = [
            f"{caso.case_id}__{c}__{rep}"
            for rep in range(args.reps)
            for caso in casos
            for c in args.configs
        ]
        if n := estado.cargar(directorio, ids):
            print(f"  reanudando: {n} repeticiones ya persistidas se saltan.\n")
    if not args.sin_piloto:
        # En E3 todos los casos son benignos: lo que el piloto puede comprobar es que el
        # arnés no lanza excepciones. Decirlo así evita fingir métricas que no existen aquí.
        piloto_casos = casos[:3]
        print(f"Piloto: {len(piloto_casos)} casos × 1 × {len(args.configs)} configuraciones.")
        errores_piloto = 0
        for caso in piloto_casos:
            for config_nombre in args.configs:
                try:
                    ejecutar_caso(
                        client,
                        Sandbox(catalogo),
                        caso,
                        obtener(config_nombre),
                        streaming=True,
                        cache=args.con_cache,
                    )
                except Exception:  # noqa: BLE001
                    errores_piloto += 1
        metricas = {"utilidad_benigna": None, "entrega": None, "errores": errores_piloto}
        fallos = verificar_piloto(metricas)
        print(f"  {resumen_piloto(metricas)}")
        if fallos:
            raise SystemExit("Piloto fallido: " + "; ".join(fallos))
        print(f"  piloto en verde (USD {client.ledger.costo_usd(models):.4f}).\n")
    total = len(casos) * args.reps * len(args.configs)
    inicio = time.perf_counter()
    hechas = 0

    print(
        f"E3: {len(casos)} casos × {args.reps} repeticiones × {len(args.configs)} configuraciones"
    )
    print("     intercaladas y secuenciales, streaming, sin caché.\n")

    for rep in range(args.reps):
        for caso in casos:
            for config_nombre in args.configs:  # intercalado: las 4 en la misma ventana
                run_id = f"{caso.case_id}__{config_nombre}__{rep}"
                if args.reanudar and not estado.pendiente(run_id):
                    continue
                try:
                    estado.comprobar_gasto(client.ledger.costo_usd(models))
                except TopeDeGasto as exc:
                    print(f"\nDETENIDA POR TOPE DE GASTO: {exc}", flush=True)
                    raise SystemExit(str(exc)) from exc
                marca = len(client.registro)
                try:
                    ejecucion = ejecutar_caso(
                        client,
                        Sandbox(catalogo),
                        caso,
                        obtener(config_nombre),
                        streaming=True,
                        cache=args.con_cache,
                    )
                except Exception as exc:  # noqa: BLE001
                    if es_fatal(exc):
                        raise SystemExit(
                            f"\nE3 abortado: {type(exc).__name__}: {str(exc)[:300]}"
                        ) from exc
                    incidencias.append({"run_id": run_id, "error": str(exc)[:200]})
                    continue

                llamadas = [
                    {
                        "rol": r.get("rol"),
                        "request_id": r.get("request_id"),
                        "timestamp": r.get("timestamp"),
                        "api_mode": "realtime",
                        "streaming": True,
                        "cache": args.con_cache,
                        "ttft_s": r.get("ttft_s"),
                        "ttft_texto_s": r.get("ttft_texto_s"),
                    }
                    for r in client.registro[marca:]
                ]
                muestras.append(
                    {
                        "run_id": run_id,
                        "case_id": caso.case_id,
                        "config": config_nombre,
                        "repeticion": rep,
                        "ttft_visible_s": ejecucion.ttft_visible_s,
                        "ttft_s": ejecucion.ttft_s,
                        "latency_s": ejecucion.latency_s,
                        "n_turnos": ejecucion.n_turnos,
                        "ttft_por_rol": ejecucion.ttft_por_rol(),
                        "llamadas": llamadas,
                    }
                )
                (directorio / f"{run_id}.json").write_text(
                    json.dumps(
                        {"run_id": run_id, "ejecucion": ejecucion.to_dict()},
                        ensure_ascii=False,
                        indent=1,
                    ),
                    encoding="utf-8",
                )
                hechas += 1
                if hechas % 10 == 0 or hechas == total:
                    t = time.perf_counter() - inicio
                    print(
                        f"  {hechas}/{total} · {t / 60:.1f} min · "
                        f"quedan ~{t / hechas * (total - hechas) / 60:.0f} min",
                        flush=True,
                    )

    resultados = resumir(muestras, args.configs)
    payload = {
        "configs": args.configs,
        "n_casos": len(casos),
        "n_repeticiones": args.reps,
        "umbral_lento_s": UMBRAL_LENTO_S,
        "resultados": resultados,
        "muestras": muestras,
        "incidencias": incidencias,
        "uso_acumulado": client.usage_summary(),
    }
    metadata = build_metadata(
        seed=experimentos["seed_global"],
        model={"agent": models.role("agent").id, "quarantine": models.role("quarantine").id},
        config=",".join(args.configs),
        corpus_version=args.version,
        criterio_ataque_version="no_aplica",
        api_mode="realtime",
        extra={
            "split": args.split,
            "streaming": True,
            # El criterio de "hecho" de la etapa lo exige explícitamente.
            "prompt_caching": args.con_cache,
            "cache_control": args.con_cache,
            "orden": "intercalado",
            "concurrencia": 1,
            "costo_usd_real": round(client.ledger.costo_usd(models), 4),
        },
    )
    archivo = write_result(args.salida, payload, metadata)

    tracker = Tracker(args.mlflow, experiment="e3_latencia")
    with tracker.run(f"e3-{','.join(args.configs)}") as activo:
        activo.log_params({"casos": len(casos), "reps": args.reps})
        activo.log_metrics(
            {f"{c}_ttft_p95": resultados[c]["ttft_visible_s"]["p95"] or 0.0 for c in args.configs}
        )

    print(f"\n  {'config':<13}{'TTFT p50':>10}{'TTFT p95':>10}{'>5s':>8}{'×p95':>8}{'×p50':>8}")
    for c in args.configs:
        r = resultados[c]
        t, s = r["ttft_visible_s"], r["sobrecosto_vs_none"]
        print(
            f"  {c:<13}{(t['p50'] or 0):>10.2f}{(t['p95'] or 0):>10.2f}"
            f"{(t['pct_sobre_5s'] or 0):>7.1f}%{(s['razon_p95'] or 0):>8.2f}"
            f"{(s['razon_p50'] or 0):>8.2f}"
        )
    print(f"\ncosto real: USD {client.ledger.costo_usd(models):.4f}")
    print(f"escrito en {archivo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
