#!/usr/bin/env python
"""Ejecuta un caso del corpus con una configuración de defensa.

    python -m prf.agent.run --case ROB-BUS-001 --config cte
    python -m prf.agent.run --case SEG-IND-001 --config dual_llm --dry-run

Escribe `results/runs/<case_id>__<config>__<n>.json` con la transcripción completa, las
llamadas a herramienta con su procedencia, los pasos bloqueados, los tokens (incluida la
caché), TTFT, latencia, el `final_state` y su evaluación determinista.

Es el motor que E1, E2 y E3 invocarán; aquí se expone como comando para poder inspeccionar
un caso concreto sin lanzar un experimento entero.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from prf.agent.bucle import MAX_TURNOS, ejecutar_caso
from prf.agent.configuraciones import CONFIGURACIONES, obtener
from prf.env import Catalog, Sandbox, caso_desde_dict, evaluate_state
from prf.env.cases import CasoCumplimiento, CasoRobustez, CasoSeguridad
from prf.infra.client import AnthropicClient
from prf.infra.config import load_experiments, load_models
from prf.infra.cost import DryRunReport, Usage, make_estimate
from prf.infra.paths import paths
from prf.infra.results import build_metadata, write_result
from prf.infra.tokens import approx_tokens

Caso = CasoRobustez | CasoSeguridad | CasoCumplimiento

ARCHIVOS_CASOS = (
    "cases_robustness.jsonl",
    "cases_security.jsonl",
    "cases_compliance.jsonl",
)


def cargar_caso(case_id: str, version: str) -> Caso:
    """Busca un caso por su id en los tres archivos del corpus."""
    raiz = paths.corpus_version(version)
    for nombre in ARCHIVOS_CASOS:
        archivo = raiz / nombre
        if not archivo.is_file():
            continue
        for linea in archivo.read_text(encoding="utf-8").splitlines():
            if not linea.strip():
                continue
            datos = json.loads(linea)
            if datos["case_id"] == case_id:
                return caso_desde_dict(datos)
    raise SystemExit(f"no existe el caso {case_id!r} en el corpus {version}")


def estimar(caso: Caso, config_nombre: str, catalogo_tokens: int) -> DryRunReport:
    """Costo estimado de una ejecución, sin llamar a la API."""
    models = load_models()
    config = obtener(config_nombre)
    reporte = DryRunReport(titulo=f"prf.agent.run — {caso.case_id} con `{config_nombre}`")

    # El bloque de catálogo se reenvía en cada llamada del turno; con caché se cobra al
    # 10 %, pero la estimación es una cota superior y lo cuenta como entrada.
    entrada_por_llamada = catalogo_tokens + 700 + approx_tokens(caso.intent)

    if config.usa_planificador:
        reporte.add(
            make_estimate(
                models,
                concepto="planificador (sonnet)",
                model_id=models.role("cte_planner").id,
                n_llamadas=1,
                usage_por_llamada=Usage(input_tokens=entrada_por_llamada, output_tokens=1500),
            )
        )
    else:
        # Un turno son varias llamadas: la inicial y una por ronda de herramienta.
        llamadas_agente = MAX_TURNOS * 3
        reporte.add(
            make_estimate(
                models,
                concepto="agente (sonnet)",
                model_id=models.role("agent").id,
                n_llamadas=llamadas_agente,
                usage_por_llamada=Usage(input_tokens=entrada_por_llamada, output_tokens=600),
            )
        )
        reporte.add(
            make_estimate(
                models,
                concepto="simulador de usuario (haiku)",
                model_id=models.role("user_simulator").id,
                n_llamadas=MAX_TURNOS,
                usage_por_llamada=Usage(input_tokens=800, output_tokens=120),
            )
        )
    if config.usa_cuarentena:
        reporte.add(
            make_estimate(
                models,
                concepto="modelo en cuarentena (haiku)",
                model_id=models.role("quarantine").id,
                n_llamadas=MAX_TURNOS,
                usage_por_llamada=Usage(input_tokens=900, output_tokens=250),
            )
        )
    reporte.notas.append(
        "Cota superior: supone que el agente agota los turnos y que no hay aciertos de caché."
    )
    return reporte


def main(argv: list[str] | None = None) -> int:
    """Ejecuta un caso suelto con una configuración, para mirar una conversación completa."""
    experimentos = load_experiments()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--case", required=True, help="Identificador del caso, p. ej. ROB-BUS-001.")
    parser.add_argument(
        "--config",
        required=True,
        choices=sorted(CONFIGURACIONES),
        help="Configuración de defensa con la que se ejecuta el caso.",
    )
    parser.add_argument(
        "--version",
        default=experimentos["corpus_version"],
        help="Versión del corpus de la que se toma el caso.",
    )
    parser.add_argument("--run", type=int, default=0, help="Índice de repetición del caso.")
    parser.add_argument(
        "--max-turnos", type=int, default=MAX_TURNOS, help="Tope de turnos de conversación."
    )
    parser.add_argument(
        "--streaming",
        action="store_true",
        help="Mide el TTFT con streaming. Es lo que usa E3.",
    )
    parser.add_argument(
        "--sin-cache",
        action="store_true",
        help="Desactiva `cache_control`. E3 lo exige y lo registra en su JSON.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Estima el costo y termina, sin llamar a la API."
    )
    parser.add_argument("--salida", default=None, help="Directorio donde escribir el JSON.")
    args = parser.parse_args(argv)

    caso = cargar_caso(args.case, args.version)
    catalogo = Catalog.from_corpus(args.version)

    if args.dry_run:
        print(estimar(caso, args.config, approx_tokens(catalogo.bloque_indice())))
        return 0

    config = obtener(args.config)
    models = load_models()
    client = AnthropicClient(models)
    sandbox = Sandbox(catalogo)

    ejecucion = ejecutar_caso(
        client,
        sandbox,
        caso,
        config,
        max_turnos=args.max_turnos,
        streaming=args.streaming,
        cache=not args.sin_cache,
    )
    evaluacion = evaluate_state(ejecucion.final_state, caso.target_state)

    payload: dict[str, Any] = {
        "ejecucion": ejecucion.to_dict(),
        "evaluacion": evaluacion,
        "uso_acumulado": client.usage_summary(),
        "caso": {
            "case_id": caso.case_id,
            "dimension": caso.dimension,
            "tipo": getattr(caso, "tipo", None),
            "intent": caso.intent,
            "target_state": caso.target_state.model_dump(mode="json"),
        },
    }
    metadata = build_metadata(
        seed=experimentos["seed_global"],
        model={
            "agent": models.role("agent").id,
            "quarantine": models.role("quarantine").id,
            "user_simulator": models.role("user_simulator").id,
        },
        config=config.nombre,
        corpus_version=args.version,
        api_mode="realtime",
        extra={
            "case_id": caso.case_id,
            "run": args.run,
            "max_turnos": args.max_turnos,
            "streaming": args.streaming,
            "prompt_caching": not args.sin_cache,
        },
    )
    destino = Path(args.salida) if args.salida else paths.results / "runs"
    archivo = write_result(
        f"{caso.case_id}__{config.nombre}__{args.run}", payload, metadata, directorio=destino
    )

    print(f"caso {caso.case_id} · configuración {config.nombre}")
    print(f"  turnos: {ejecucion.n_turnos} · llamadas a herramienta: {len(ejecucion.llamadas)}")
    print(f"  pasos bloqueados: {len(ejecucion.pasos_bloqueados)}")
    print(f"  recomendaciones: {ejecucion.final_state.recomendaciones}")
    print(f"  éxito (estado): {evaluacion['success']}")
    if not evaluacion["success"]:
        for razon in evaluacion["reasons"]:
            print(f"    - {razon['regla']}: {razon['mensaje']}")
    print(f"  ttft_s: {ejecucion.ttft_s} · latency_s: {ejecucion.latency_s:.2f}")
    print(f"  tokens: {ejecucion.usage.to_dict()}")
    print(f"  costo real: USD {client.ledger.costo_usd(models):.4f}")
    print(f"  escrito en {archivo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
