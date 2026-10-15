#!/usr/bin/env python
"""E1 — línea base de robustez y no degradación bajo defensa.

Ejecuta los casos de robustez de la partición de prueba `n` veces con cada configuración y
reporta pass^k para k ∈ {1,2,4,8}, global y por tipo de intención, con IC 95 % por bootstrap
sobre casos.

`none` da la línea base; `dual_llm` y `cte` dicen **si la defensa degrada la robustez**, que
es lo que la tabla 5 debe responder y no se puede leer del ASR.

Uso:

    python scripts/run_e1.py --dry-run              # costo estimado por configuración
    python scripts/run_e1.py --piloto 2             # 2 casos por configuración, para validar
    python scripts/run_e1.py                        # E1 completo

Estrategia de ejecución (documentada porque condiciona el costo y el calendario):

- `realtime_concurrente` ejecuta conversaciones completas en paralelo, con un semáforo de
  `api.concurrencia_max`. Cada ejecución sigue siendo secuencial por dentro, que es lo que
  exige un bucle agente–usuario con uso de herramientas.
- `batch` requiere invertir el control del bucle: una conversación con herramientas no es
  una petición sino una cadena de peticiones que dependen unas de otras, así que agruparlas
  obliga a avanzar todas las conversaciones en bloque, una ronda por lote. Ver la nota de
  `--dry-run`, que compara ahorro contra riesgo de calendario.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from prf.agent.bucle import ejecutar_caso  # noqa: E402
from prf.agent.configuraciones import obtener  # noqa: E402
from prf.env import Catalog, Sandbox, caso_desde_dict, evaluate_state  # noqa: E402
from prf.eval.bootstrap import bootstrap_ic  # noqa: E402
from prf.eval.passk import curva_passk, passk_agregado  # noqa: E402
from prf.infra.client import AnthropicClient  # noqa: E402
from prf.infra.config import load_experiments, load_models  # noqa: E402
from prf.infra.corrida import (
    EstadoCorrida,
    TopeDeGasto,
    resumen_piloto,
    verificar_piloto,
)
from prf.infra.cost import DryRunReport, Usage, estimate_cost_usd  # noqa: E402
from prf.infra.paths import paths  # noqa: E402
from prf.infra.results import build_metadata, politica_vigente, write_result  # noqa: E402
from prf.infra.tracking import Tracker  # noqa: E402

# Errores que NO son fallos del agente: no hay crédito, no hay credencial, no hay permiso.
# Registrarlos como `exito = 0` produciría un pass^k de cero que parece un resultado y es
# una avería de infraestructura. Cuando aparece uno, la corrida se aborta sin escribir nada.
SENALES_FATALES = (
    "usage limit",
    "credit balance",
    "authentication",
    "permission",
    "invalid x-api-key",
)


def es_fatal(exc: BaseException) -> bool:
    """¿La causa impide que CUALQUIER ejecución tenga sentido?"""
    mensaje = str(exc).lower()
    return any(senal in mensaje for senal in SENALES_FATALES)


TIPOS = ("busqueda", "comparacion", "recomendacion")

# Uso medido por ejecución. Procede del PILOTO de E1 (48 ejecuciones reales, 2 casos × 8
# × 3 configuraciones), no de supuestos. Se usa el mismo perfil para las cuatro porque el
# piloto mide el promedio de la rejilla y no distingue por configuración: la estimación
# previa, que sí las distinguía a partir de ejecuciones sueltas de la etapa 4, se quedó un
# 56 % por debajo del costo real, sobre todo por ignorar `cache_creation` —la entrada de
# caché expira a los 5 minutos y se reescribe varias veces en una corrida larga— y por
# subestimar los tokens de salida.
PERFIL_MEDIDO: dict[str, dict[str, int]] = {
    "none": {
        "input_tokens": 2273,
        "cache_read_tokens": 10975,
        "cache_creation_tokens": 707,
        "output_tokens": 851,
    },
    "prompt_only": {
        "input_tokens": 2273,
        "cache_read_tokens": 10975,
        "cache_creation_tokens": 707,
        "output_tokens": 851,
    },
    "dual_llm": {
        "input_tokens": 2273,
        "cache_read_tokens": 10975,
        "cache_creation_tokens": 707,
        "output_tokens": 851,
    },
    "cte": {
        "input_tokens": 2273,
        "cache_read_tokens": 10975,
        "cache_creation_tokens": 707,
        "output_tokens": 851,
    },
}
# Segundos por ejecución, medidos en las mismas corridas. Sirven para estimar el calendario.
# Segundos por ejecución, medidos en el piloto: 48 ejecuciones en 4,2 min con concurrencia
# 4 dan 21 s por ejecución de reloj de pared.
LATENCIA_MEDIDA_S: dict[str, float] = {
    "none": 21.0,
    "prompt_only": 21.0,
    "dual_llm": 21.0,
    "cte": 21.0,
}
# Reparto del uso entre el modelo caro y el barato, por configuración. En `cte` el
# planificador es sonnet y la cuarentena haiku; en `dual_llm` el agente es sonnet y la
# cuarentena haiku; en `none` todo el peso es del agente más el simulador de usuario.
FRACCION_SONNET: dict[str, float] = {
    "none": 0.85,
    "prompt_only": 0.85,
    "dual_llm": 0.80,
    "cte": 0.55,
}


def cargar_casos(version: str, split: str) -> list[Any]:
    """Casos de robustez de la partición indicada."""
    ids = set((paths.splits_version(version) / f"{split}.txt").read_text(encoding="utf-8").split())
    archivo = paths.corpus_version(version) / "cases_robustness.jsonl"
    casos = []
    for linea in archivo.read_text(encoding="utf-8").splitlines():
        if not linea.strip():
            continue
        datos = json.loads(linea)
        if datos["case_id"] in ids:
            casos.append(caso_desde_dict(datos))
    return sorted(casos, key=lambda c: c.case_id)


def muestra_estratificada(casos: list[Any], por_tipo: int) -> list[Any]:
    """`por_tipo` casos de cada tipo de intención.

    Un piloto que toma los primeros casos por id solo cubre `busqueda` y no diría nada
    sobre `comparacion`, que exige además que el agente entregue una comparación concreta.
    """
    elegidos: list[Any] = []
    for tipo in TIPOS:
        elegidos.extend([c for c in casos if c.tipo == tipo][:por_tipo])
    return sorted(elegidos, key=lambda c: c.case_id)


# --------------------------------------------------------------------- costo


def uso_estimado(config: str, ejecuciones: int, parte: float) -> Usage:
    """Uso estimado de una porción de la rejilla. **Única fuente de verdad del costo.**

    Incluye `cache_creation`: la entrada de caché expira a los cinco minutos, así que en
    una corrida larga se reescribe varias veces y no es un costo que se amortice entre
    todas las ejecuciones. Ignorarlo fue una de las dos causas de que la estimación previa
    al piloto se quedara un 56 % por debajo del costo real.
    """
    perfil = PERFIL_MEDIDO[config]
    return Usage(
        input_tokens=int(perfil["input_tokens"] * ejecuciones * parte),
        cache_read_tokens=int(perfil["cache_read_tokens"] * ejecuciones * parte),
        cache_creation_tokens=int(perfil.get("cache_creation_tokens", 0) * ejecuciones * parte),
        output_tokens=int(perfil["output_tokens"] * ejecuciones * parte),
    )


def estimar(configs: list[str], n_casos: int, n_runs: int, concurrencia: int) -> DryRunReport:
    """Costo estimado por configuración, en los dos modos de API."""
    models = load_models()
    reporte = DryRunReport(
        titulo=f"E1 — {n_casos} casos × {n_runs} ejecuciones × {len(configs)} configuraciones"
    )
    sonnet = models.role("agent").id
    haiku = models.role("quarantine").id

    for config in configs:
        ejecuciones = n_casos * n_runs
        fraccion = FRACCION_SONNET[config]
        for etiqueta, modelo, parte in (
            (f"{config}: sonnet", sonnet, fraccion),
            (f"{config}: haiku", haiku, 1 - fraccion),
        ):
            if parte <= 0:
                continue
            uso = uso_estimado(config, ejecuciones, parte)
            reporte.add(_estimacion(models, etiqueta, modelo, ejecuciones, uso, batch=False))
    reporte.notas.append(
        "Uso por ejecución medido en el piloto de E1 (48 ejecuciones reales), no supuesto."
    )
    reporte.notas.append(
        "Incluye cache_creation: la entrada de caché expira a los 5 minutos y se reescribe "
        "varias veces en una corrida larga, así que no es un costo amortizable."
    )
    return reporte


def _estimacion(models, concepto, modelo, n_llamadas, uso, *, batch):
    from prf.infra.cost import CostEstimate

    return CostEstimate(
        concepto=concepto,
        model=modelo,
        n_llamadas=n_llamadas,
        usage=uso,
        batch=batch,
        usd=estimate_cost_usd(models, modelo, uso, batch=batch),
    )


def resumen_por_modo(configs: list[str], n_casos: int, n_runs: int, concurrencia: int) -> str:
    """Compara los dos modos de API en costo y en calendario."""
    models = load_models()
    sonnet, haiku = models.role("agent").id, models.role("quarantine").id
    lineas = [
        "",
        "Costo por configuración y modo de API",
        "",
        f"{'configuración':<14} {'ejecuciones':>12} {'tiempo real':>12} {'batch (−50 %)':>14} "
        f"{'horas (conc. ' + str(concurrencia) + ')':>18}",
        "-" * 74,
    ]
    total_rt = total_batch = total_horas = 0.0
    for config in configs:
        ejecuciones = n_casos * n_runs
        fraccion = FRACCION_SONNET[config]
        usd_rt = usd_batch = 0.0
        for modelo, parte in ((sonnet, fraccion), (haiku, 1 - fraccion)):
            uso = uso_estimado(config, ejecuciones, parte)
            usd_rt += estimate_cost_usd(models, modelo, uso, batch=False)
            usd_batch += estimate_cost_usd(models, modelo, uso, batch=True)
        horas = ejecuciones * LATENCIA_MEDIDA_S[config] / concurrencia / 3600
        total_rt += usd_rt
        total_batch += usd_batch
        total_horas += horas
        lineas.append(
            f"{config:<14} {ejecuciones:>12} {usd_rt:>11.2f}$ {usd_batch:>13.2f}$ {horas:>17.1f}"
        )
    lineas.append("-" * 74)
    lineas.append(
        f"{'TOTAL':<14} {n_casos * n_runs * len(configs):>12} {total_rt:>11.2f}$ "
        f"{total_batch:>13.2f}$ {total_horas:>17.1f}"
    )
    lineas.extend(
        [
            "",
            f"Ahorro de Batch API: {total_rt - total_batch:.2f} USD "
            f"({(1 - total_batch / total_rt):.0%}).",
            "",
            "Calendario. En tiempo real con concurrencia el trabajo termina en las horas de la",
            "última columna, de forma predecible. Batch cuesta la mitad, pero una conversación",
            "con herramientas no es una petición sino una cadena de peticiones dependientes:",
            "agruparlas obliga a avanzar todas las conversaciones en bloque, una ronda por lote,",
            "y cada lote puede tardar hasta 24 horas. Con 3-4 rondas por ejecución, E1 podría",
            "ocupar varios días y una tanda fallida obliga a repetir la espera completa.",
        ]
    )
    return "\n".join(lineas)


# ----------------------------------------------------------------- ejecución


def _recuperar(
    archivo: Path,
    matriz: dict[str, dict[str, list[int]]],
    observaciones: list[dict[str, Any]],
    transcripciones: dict[str, dict[str, str]],
) -> None:
    """Reconstruye desde disco lo que una ejecución ya persistida aportaba en memoria.

    La reanudación no vuelve a llamar a la API, pero el análisis necesita la matriz y las
    observaciones igual: se leen del archivo de la ejecución, que es la evidencia de que
    ocurrió. El uso de tokens **no** se recupera —ya se pagó en la corrida anterior— y por eso
    el costo que reporta una corrida reanudada es solo el de lo que ejecutó ahora.
    """
    datos = json.loads(archivo.read_text(encoding="utf-8"))
    config, caso_id, indice = datos["config"], datos["case_id"], datos["run"]
    matriz[config][caso_id][indice] = 1 if datos["evaluacion"]["success"] else 0
    ejecucion = datos["ejecucion"]
    observaciones.append(
        {
            "run_id": datos["run_id"],
            "case_id": caso_id,
            "config": config,
            "tipo": datos["tipo"],
            "exito": matriz[config][caso_id][indice],
            "n_turnos": ejecucion.get("n_turnos", 0),
            "n_llamadas_herramienta": len(ejecucion.get("llamadas") or []),
            "trato_senuelo": datos.get("trato_senuelo") or [],
            "reanudada": True,
        }
    )
    transcripciones[config][datos["run_id"]] = str(archivo.relative_to(paths.root))


def ejecutar(
    casos: list[Any],
    configs: list[str],
    n_runs: int,
    version: str,
    concurrencia: int,
    max_turnos: int,
    directorio_runs: Path,
    estado: EstadoCorrida | None = None,
    reanudar: bool = False,
) -> tuple[
    dict[str, dict[str, list[int]]],
    list[dict[str, Any]],
    AnthropicClient,
    dict[str, Usage],
    dict[str, dict[str, str]],
    list[dict[str, Any]],
]:
    """Ejecuta la rejilla completa.

    Devuelve (matriz, incidencias, cliente, uso por configuración, rutas de transcripción).

    Cada ejecución se persiste entera —transcripción, llamadas con procedencia, pasos
    bloqueados y estado final— porque la etapa 8 muestrea 80 ejecuciones reales de E1 para
    compararlas con el juez LLM y con un anotador humano, y necesita el `transcript_path`
    de cada una. Sin esto, E1 habría que repetirlo entero para poder hacer E6.
    """
    models = load_models()
    client = AnthropicClient(models)
    catalogo = Catalog.from_corpus(version)

    matriz: dict[str, dict[str, list[int]]] = {
        c: {caso.case_id: [0] * n_runs for caso in casos} for c in configs
    }
    incidencias: list[dict[str, Any]] = []
    fatal: list[str] = []
    uso_por_config: dict[str, Usage] = {c: Usage() for c in configs}
    observaciones: list[dict[str, Any]] = []
    transcripciones: dict[str, dict[str, str]] = {c: {} for c in configs}
    directorio_runs.mkdir(parents=True, exist_ok=True)
    candado = Lock()
    tareas = [
        (config, caso, indice) for config in configs for caso in casos for indice in range(n_runs)
    ]
    reanudadas = 0
    if estado is not None and reanudar:
        ids = [f"{c.case_id}__{cfg}__{i}" for cfg, c, i in tareas]
        reanudadas = estado.cargar(directorio_runs, ids)
        if reanudadas:
            print(f"  reanudando: {reanudadas} ejecuciones ya persistidas se saltan.\n")
    total = len(tareas)
    hechas = 0
    inicio = time.perf_counter()

    def _una(tarea):
        nonlocal hechas
        config_nombre, caso, indice = tarea
        if fatal:
            return []
        run_id_previo = f"{caso.case_id}__{config_nombre}__{indice}"
        if reanudar and estado is not None and not estado.pendiente(run_id_previo):
            with candado:
                _recuperar(
                    directorio_runs / f"{run_id_previo}.json",
                    matriz,
                    observaciones,
                    transcripciones,
                )
            return []
        # Un sandbox por ejecución: compartirlo mezclaría el registro de herramientas de
        # conversaciones distintas y el estado final dejaría de ser el de este caso.
        sandbox = Sandbox(catalogo)
        try:
            ejecucion = ejecutar_caso(
                client, sandbox, caso, obtener(config_nombre), max_turnos=max_turnos
            )
            evaluacion = evaluate_state(ejecucion.final_state, caso.target_state)
            exito = 1 if evaluacion["success"] else 0
            razones = [r["regla"] for r in evaluacion["reasons"]]

            # Cómo trató el agente el señuelo de `must_exclude`: no es lo mismo haberlo
            # visto y descartado que no habérselo topado nunca. Lo primero es criterio; lo
            # segundo puede ser suerte del orden en que la herramienta devolvió resultados.
            senuelos = caso.target_state.must_exclude
            vistos = set(ejecucion.final_state.productos_vistos)
            recomendados = set(ejecucion.final_state.recomendaciones)
            trato_senuelo = [
                {
                    "producto": pid,
                    "visto": pid in vistos,
                    "recomendado": pid in recomendados,
                    "trato": (
                        "recomendado"
                        if pid in recomendados
                        else ("considerado_y_excluido" if pid in vistos else "nunca_aparecio")
                    ),
                }
                for pid in senuelos
            ]

            run_id = f"{caso.case_id}__{config_nombre}__{indice}"
            archivo = directorio_runs / f"{run_id}.json"
            archivo.write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "case_id": caso.case_id,
                        "config": config_nombre,
                        "run": indice,
                        "tipo": caso.tipo,
                        "intent": caso.intent,
                        "target_state": caso.target_state.model_dump(mode="json"),
                        "ejecucion": ejecucion.to_dict(),
                        "evaluacion": evaluacion,
                        "trato_senuelo": trato_senuelo,
                    },
                    ensure_ascii=False,
                    indent=1,
                ),
                encoding="utf-8",
            )
            with candado:
                observaciones.append(
                    {
                        "run_id": run_id,
                        "case_id": caso.case_id,
                        "config": config_nombre,
                        "tipo": caso.tipo,
                        "exito": exito,
                        "n_turnos": ejecucion.n_turnos,
                        "n_llamadas_herramienta": len(ejecucion.llamadas),
                        "trato_senuelo": trato_senuelo,
                    }
                )
                uso_por_config[config_nombre] = uso_por_config[config_nombre] + ejecucion.usage
                transcripciones[config_nombre][run_id] = str(archivo.relative_to(paths.root))
        except Exception as exc:  # noqa: BLE001 - una ejecución rota no debe tumbar E1
            if es_fatal(exc):
                with candado:
                    if not fatal:
                        fatal.append(f"{type(exc).__name__}: {str(exc)[:300]}")
                        print(f"\nABORTANDO: {fatal[0]}", flush=True)
                return []
            exito, razones = 0, [f"excepcion:{type(exc).__name__}"]
            with candado:
                incidencias.append(
                    {
                        "case_id": caso.case_id,
                        "config": config_nombre,
                        "run": indice,
                        "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                    }
                )
        with candado:
            matriz[config_nombre][caso.case_id][indice] = exito
            hechas += 1
            if estado is not None and hechas % 10 == 0:
                try:
                    estado.comprobar_gasto(client.ledger.costo_usd(models))
                except TopeDeGasto as exc:
                    if not fatal:
                        fatal.append(str(exc))
                        print(f"\nDETENIDA POR TOPE DE GASTO: {exc}", flush=True)
                    return []
            if hechas % 10 == 0 or hechas == total:
                transcurrido = time.perf_counter() - inicio
                restante = transcurrido / hechas * (total - hechas)
                print(
                    f"  {hechas}/{total} ejecuciones · {transcurrido / 60:.1f} min · "
                    f"quedan ~{restante / 60:.0f} min",
                    flush=True,
                )
        return razones

    with ThreadPoolExecutor(max_workers=concurrencia) as pool:
        list(pool.map(_una, tareas))
    if fatal:
        raise SystemExit(
            f"\nE1 abortado sin escribir resultados: {fatal[0]}\n"
            "No es un fallo del agente. Se completaron "
            f"{hechas} de {total} ejecuciones; las hechas quedan en results/runs_e1/."
        )
    return matriz, incidencias, client, uso_por_config, transcripciones, observaciones


# ------------------------------------------------------------------ análisis


def analizar(
    matriz: dict[str, list[int]],
    casos: list[Any],
    n_runs: int,
    ks: list[int],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """pass^k global y por tipo, con IC por bootstrap sobre casos."""
    por_tipo: dict[str, list[int]] = defaultdict(list)
    exitos_global: list[int] = []
    for caso in casos:
        aciertos = sum(matriz[caso.case_id])
        exitos_global.append(aciertos)
        por_tipo[caso.tipo].append(aciertos)

    def _con_ic(exitos: list[int]) -> dict[str, Any]:
        salida: dict[str, Any] = {}
        for k in ks:
            ic = bootstrap_ic(
                exitos,
                lambda muestra, k=k: passk_agregado(muestra, n=n_runs, k=k),
                n_remuestreos=bootstrap["n_resamples"],
                confianza=bootstrap["confidence"],
                seed=bootstrap["seed"],
            )
            salida[f"pass^{k}"] = ic.to_dict()
        return salida

    return {
        "n_casos": len(casos),
        "n_runs": n_runs,
        "global": _con_ic(exitos_global),
        "por_tipo": {
            tipo: {"n_casos": len(por_tipo[tipo]), **_con_ic(por_tipo[tipo])}
            for tipo in TIPOS
            if por_tipo.get(tipo)
        },
        "curva": {str(k): v for k, v in curva_passk(exitos_global, n=n_runs, ks=ks).items()},
        "exitos_por_caso": {c.case_id: sum(matriz[c.case_id]) for c in casos},
    }


def _costo_config(models, config: str, uso: Usage) -> float:
    """Costo de una configuración repartiendo su uso entre el modelo caro y el barato.

    Es una atribución, no una factura: el cliente contabiliza por modelo y una ejecución
    mezcla los dos. Se usa la misma fracción con la que se estima el costo por adelantado,
    de modo que la estimación y lo realmente gastado sean comparables.
    """
    fraccion = FRACCION_SONNET.get(config, 0.85)
    sonnet, haiku = models.role("agent").id, models.role("quarantine").id
    total = 0.0
    for modelo, parte in ((sonnet, fraccion), (haiku, 1 - fraccion)):
        porcion = Usage(
            input_tokens=int(uso.input_tokens * parte),
            output_tokens=int(uso.output_tokens * parte),
            cache_creation_tokens=int(uso.cache_creation_tokens * parte),
            cache_read_tokens=int(uso.cache_read_tokens * parte),
        )
        total += estimate_cost_usd(models, modelo, porcion)
    return total


def analisis_extra(
    observaciones: list[dict[str, Any]],
    matriz: dict[str, dict[str, list[int]]],
    casos: list[Any],
    n_runs: int,
) -> dict[str, Any]:
    """Lo que pass^k no dice: dónde falla, cómo trata el señuelo y cuánto trabajo cuesta."""
    tipos = {c.case_id: c.tipo for c in casos}

    inconsistentes: dict[str, Any] = {}
    distribucion: dict[str, dict[str, int]] = {}
    for config, por_caso in matriz.items():
        # Casos que NO acertaron las 8 veces: son los que hacen caer pass^8 y los que
        # conviene mirar uno a uno, porque un caso 7/8 es un problema distinto de un 0/8.
        fallos = [
            {"case_id": cid, "tipo": tipos[cid], "c": sum(filas), "n": n_runs}
            for cid, filas in sorted(por_caso.items())
            if sum(filas) < n_runs
        ]
        inconsistentes[config] = {
            "n_casos_con_c_menor_que_n": len(fallos),
            "por_tipo": {tipo: sum(1 for f in fallos if f["tipo"] == tipo) for tipo in TIPOS},
            "casos": fallos,
        }
        cuentas = [sum(filas) for filas in por_caso.values()]
        distribucion[config] = {
            f"{n_runs}/{n_runs}": sum(1 for c in cuentas if c == n_runs),
            f"{n_runs - 1}/{n_runs}": sum(1 for c in cuentas if c == n_runs - 1),
            f"<={n_runs - 2}/{n_runs}": sum(1 for c in cuentas if c <= n_runs - 2),
        }

    senuelo: dict[str, dict[str, int]] = {}
    trabajo: dict[str, dict[str, float]] = {}
    for config in matriz:
        obs = [o for o in observaciones if o["config"] == config]
        tratos = [t["trato"] for o in obs for t in o["trato_senuelo"]]
        senuelo[config] = {
            "considerado_y_excluido": tratos.count("considerado_y_excluido"),
            "nunca_aparecio": tratos.count("nunca_aparecio"),
            "recomendado": tratos.count("recomendado"),
            "ejecuciones_con_senuelo": len(tratos),
        }
        turnos = [o["n_turnos"] for o in obs] or [0]
        llamadas = [o["n_llamadas_herramienta"] for o in obs] or [0]
        trabajo[config] = {
            "turnos_media": round(sum(turnos) / len(turnos), 2),
            "turnos_max": max(turnos),
            "llamadas_media": round(sum(llamadas) / len(llamadas), 2),
            "llamadas_max": max(llamadas),
        }

    return {
        "casos_inconsistentes": inconsistentes,
        "distribucion_de_c": distribucion,
        "trato_del_senuelo": senuelo,
        "trabajo_por_ejecucion": trabajo,
    }


def main(argv: list[str] | None = None) -> int:
    """Corre E1 y escribe su JSON canónico. Acepta `--dry-run`, que no llama a la API."""
    experimentos = load_experiments()
    e1 = experimentos["experiments"]["e1_robustez"]

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--configs",
        nargs="+",
        default=e1["configs"],
        help="Configuraciones de defensa a medir, separadas por espacio.",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=e1["n_runs_por_caso"],
        help="Ejecuciones por caso. pass^k necesita n >= k.",
    )
    parser.add_argument(
        "--split", default=e1["split"], help="Partición del corpus: dev, test o todos."
    )
    parser.add_argument(
        "--tipo",
        choices=TIPOS,
        default=None,
        help="Restringe a un tipo de intención. Para validar en desarrollo antes de medir.",
    )
    parser.add_argument(
        "--version",
        default=experimentos["corpus_version"],
        help="Versión del corpus congelado sobre la que se mide.",
    )
    parser.add_argument(
        "--max-turnos",
        type=int,
        default=e1.get("max_turnos", 6),
        help="Tope de turnos de conversación por ejecución.",
    )
    parser.add_argument(
        "--concurrencia",
        type=int,
        default=experimentos["api"]["concurrencia_max"],
        help="Peticiones simultáneas a la API, dentro del límite de tasa.",
    )
    parser.add_argument(
        "--piloto",
        type=int,
        default=0,
        metavar="N",
        help=(
            "Ejecuta N casos por TIPO de intención, no los N primeros: tomar los primeros "
            "por id deja fuera comparación y recomendación, que son los tipos con "
            "requisitos distintos."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Imprime tokens y costo estimado en USD y no llama a la API.",
    )
    parser.add_argument(
        "--reanudar",
        action="store_true",
        help="Salta las ejecuciones que ya tienen su archivo en results/runs_e1/.",
    )
    parser.add_argument(
        "--sin-piloto",
        action="store_true",
        help="Omite el piloto previo de 3 casos por tipo.",
    )
    parser.add_argument(
        "--mlflow",
        action="store_true",
        help="Registra la corrida en MLflow, además del JSON canónico.",
    )
    parser.add_argument(
        "--salida", default="e1_baseline", help="Nombre del JSON en results/, sin extensión."
    )
    args = parser.parse_args(argv)

    casos = cargar_casos(args.version, args.split)
    if args.tipo:
        casos = [c for c in casos if c.tipo == args.tipo]
    if args.piloto:
        casos = muestra_estratificada(casos, args.piloto)
    if not casos:
        raise SystemExit("no hay casos de robustez en esa partición")

    if args.dry_run:
        print(estimar(args.configs, len(casos), args.n, args.concurrencia))
        print(resumen_por_modo(args.configs, len(casos), args.n, args.concurrencia))
        return 0

    print(
        f"E1: {len(casos)} casos × {args.n} ejecuciones × {len(args.configs)} "
        f"configuraciones = {len(casos) * args.n * len(args.configs)} ejecuciones, "
        f"concurrencia {args.concurrencia}.\n"
    )
    directorio_runs = paths.results / "runs_e1"

    if not args.sin_piloto:
        # El piloto usa `--n 1` y 3 casos por tipo: detecta un fallo sistemático del arnés por
        # unos centavos, en vez de al final de una corrida de una hora.
        casos_piloto = muestra_estratificada(casos, 3)
        print(f"Piloto: {len(casos_piloto)} casos × 1 × {len(args.configs)} configuraciones.")
        _, inc_p, cli_p, _, _, obs_p = ejecutar(
            casos_piloto,
            args.configs,
            1,
            args.version,
            args.concurrencia,
            args.max_turnos,
            directorio_runs,
        )
        metricas = {"utilidad_benigna": None, "entrega": None, "errores": len(inc_p)}
        fallos = verificar_piloto(metricas)
        print(f"  {resumen_piloto(metricas)}")
        if fallos:
            raise SystemExit("Piloto fallido: " + "; ".join(fallos))
        print(
            f"  piloto en verde (USD {cli_p.ledger.costo_usd(load_models()):.4f}); "
            "sigue la corrida completa.\n"
        )

    estimacion = estimar(args.configs, len(casos), args.n, args.concurrencia)
    estado = EstadoCorrida(
        salida=args.salida, directorio=paths.results, estimacion_usd=estimacion.total_usd
    )
    matriz, incidencias, client, uso_por_config, transcripciones, observaciones = ejecutar(
        casos,
        args.configs,
        args.n,
        args.version,
        args.concurrencia,
        args.max_turnos,
        directorio_runs,
        estado,
        args.reanudar,
    )

    models = load_models()
    # pass^k no está definido para k > n. Con `--n` reducido (un piloto) los k mayores se
    # descartan en vez de reventar el análisis después de haber gastado las ejecuciones.
    ks = [k for k in e1["k_values"] if k <= args.n]
    descartados = [k for k in e1["k_values"] if k > args.n]
    if descartados:
        print(f"  k descartados por superar n={args.n}: {descartados}")
    if not ks:
        raise SystemExit(f"ningún k de {e1['k_values']} es válido con n={args.n}")
    resultados = {
        config: analizar(matriz[config], casos, args.n, ks, experimentos["bootstrap"])
        for config in args.configs
    }

    # No degradación: cuánto pierde cada defensa respecto de la línea base.
    linea_base = resultados.get("none", {}).get("global", {}).get("pass^1", {}).get("valor")
    for datos in resultados.values():
        valor = datos["global"]["pass^1"]["valor"]
        datos["delta_pass1_vs_none"] = None if linea_base is None else round(valor - linea_base, 6)

    payload = {
        "configs": args.configs,
        "k_values": ks,
        "resultados": resultados,
        # Coste y uso atribuidos a cada defensa: sin esto solo se conoce el total y no se
        # puede decir cuánto cuesta proteger, que es parte de lo que la tabla 5 compara.
        "uso_por_config": {
            config: {
                **uso.to_dict(),
                "costo_usd": round(_costo_config(models, config, uso), 4),
            }
            for config, uso in uso_por_config.items()
        },
        # Rutas de las ejecuciones persistidas: la etapa 8 muestrea 80 de aquí.
        "transcripciones": transcripciones,
        "matriz": {
            config: {cid: list(filas) for cid, filas in matriz[config].items()}
            for config in args.configs
        },
        "analisis": analisis_extra(observaciones, matriz, casos, args.n),
        "observaciones": observaciones,
        "incidencias": incidencias,
        "uso_acumulado": client.usage_summary(),
    }
    metadata = build_metadata(
        seed=args.n and experimentos["seed_global"],
        model={
            "agent": models.role("agent").id,
            "quarantine": models.role("quarantine").id,
            "user_simulator": models.role("user_simulator").id,
        },
        config=",".join(args.configs),
        corpus_version=args.version,
        criterio_ataque_version="no_aplica",
        api_mode="realtime_concurrente",
        extra={
            "split": args.split,
            "n_runs_por_caso": args.n,
            "n_casos": len(casos),
            "concurrencia": args.concurrencia,
            "piloto": bool(args.piloto),
            "prompt_caching": True,
            "costo_usd_real": round(client.ledger.costo_usd(models), 4),
            # La política con la que se juzgará esta corrida, congelada antes de medirla.
            "politica": politica_vigente(),
        },
    )
    archivo = write_result(args.salida, payload, metadata)

    tracker = Tracker(args.mlflow, experiment="e1_robustez")
    with tracker.run(f"e1-{','.join(args.configs)}") as activo:
        activo.log_params({"n": args.n, "casos": len(casos), "configs": args.configs})
        activo.log_metrics(
            {f"{c}_pass1": resultados[c]["global"]["pass^1"]["valor"] for c in args.configs}
        )

    print("\npass^k global por configuración")
    print(f"  {'config':<12} " + "".join(f"{'pass^' + str(k):>22}" for k in ks))
    for config in args.configs:
        fila = "".join(
            f"{resultados[config]['global']['pass^' + str(k)]['valor']:>10.3f} "
            f"[{resultados[config]['global']['pass^' + str(k)]['ic_inferior']:.2f},"
            f"{resultados[config]['global']['pass^' + str(k)]['ic_superior']:.2f}]"
            for k in ks
        )
        print(f"  {config:<12} {fila}")
    if incidencias:
        print(f"\nIncidencias: {len(incidencias)}")
    print(f"\ncosto real: USD {client.ledger.costo_usd(models):.4f}")
    print(f"escrito en {archivo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
