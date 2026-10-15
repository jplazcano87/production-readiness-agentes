"""E4 — cumplimiento: ejecuta el checklist sobre los casos de cumplimiento del corpus.

    python scripts/run_e4.py --config cte --dry-run
    python scripts/run_e4.py --config cte
    python scripts/run_e4.py --tabla-checklist       # no llama a la API

Cada ítem del checklist se evalúa con un verificador determinista sobre la evidencia de la
ejecución. Los dos ítems de tolerancia cero no tienen caso propio: se comprueban sobre
**todas** las ejecuciones, porque son propiedades que deben cumplirse siempre y basta una
violación para forzar NO-GO.

Un ítem queda en `no_evaluable` cuando falta la evidencia para decidir. No se cuenta como
aprobado: un checklist que convierte la falta de evidencia en cumplimiento no sirve para
decidir si algo puede salir a producción.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any

from prf.agent import obtener
from prf.agent.bucle import ejecutar_caso
from prf.compliance import Contexto, cargar_checklist, cargar_despliegue, redactar_pii
from prf.compliance.verifiers import REGISTRO
from prf.env import Catalog, Sandbox
from prf.env.cases import CasoCumplimiento
from prf.env.evaluator import EVALUATOR_VERSION
from prf.infra import paths
from prf.infra.client import AnthropicClient
from prf.infra.config import load_experiments, load_models
from prf.infra.corrida import (
    EstadoCorrida,
    TopeDeGasto,
    resumen_piloto,
    verificar_piloto,
)
from prf.infra.cost import DryRunReport, Usage, estimate_cost_usd
from prf.infra.results import build_metadata, read_result, write_result
from prf.infra.tracking import Tracker

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_e1 import FRACCION_SONNET, PERFIL_MEDIDO, es_fatal  # noqa: E402


def cargar_casos(version: str, split: str) -> list[CasoCumplimiento]:
    """Casos de cumplimiento. `split: todos` los toma todos, que es lo que fija E4."""
    archivo = paths.corpus_version(version) / "cases_compliance.jsonl"
    casos = [
        CasoCumplimiento.model_validate_json(linea)
        for linea in archivo.read_text(encoding="utf-8").splitlines()
        if linea.strip()
    ]
    if split != "todos":
        ids = set(
            (paths.splits_version(version) / f"{split}.txt").read_text(encoding="utf-8").split()
        )
        casos = [c for c in casos if c.case_id in ids]
    return casos


# --------------------------------------------------------------------- estimación


def uso_estimado(config: str, ejecuciones: int, parte: float) -> Usage:
    """Mismo perfil medido que E1: los casos de cumplimiento son conversaciones de una vuelta."""
    perfil = PERFIL_MEDIDO[config]
    return Usage(
        input_tokens=int(perfil["input_tokens"] * ejecuciones * parte),
        output_tokens=int(perfil["output_tokens"] * ejecuciones * parte),
        cache_creation_tokens=int(perfil["cache_creation_tokens"] * ejecuciones * parte),
        cache_read_tokens=int(perfil["cache_read_tokens"] * ejecuciones * parte),
    )


def estimar(config: str, n_casos: int) -> DryRunReport:
    """Tokens y costo que tendría la corrida, para `--dry-run`."""
    models = load_models()
    reporte = DryRunReport(titulo=f"E4 — {n_casos} casos de cumplimiento × 1 ejecución ({config})")
    fraccion = FRACCION_SONNET[config]
    for etiqueta, modelo, parte in (
        (f"{config}: sonnet", models.role("agent").id, fraccion),
        (f"{config}: haiku", models.role("quarantine").id, 1 - fraccion),
    ):
        if parte <= 0:
            continue
        uso = uso_estimado(config, n_casos, parte)
        reporte.add(
            _estimacion(models, etiqueta, modelo, n_casos, uso),
        )
    reporte.notas.append(
        "Uso por ejecución medido en E1 (1008 ejecuciones reales), no supuesto. E4 no repite "
        "casos: un ítem de cumplimiento no se aprueba por mayoría."
    )
    return reporte


def _estimacion(models, concepto, modelo, n_llamadas, uso):
    from prf.infra.cost import CostEstimate

    return CostEstimate(
        concepto=concepto,
        model=modelo,
        n_llamadas=n_llamadas,
        usage=uso,
        batch=False,
        usd=estimate_cost_usd(models, modelo, uso, batch=False),
    )


def _costo_config(models, config: str, uso: Usage) -> float:
    fraccion = FRACCION_SONNET.get(config, 0.85)
    total = 0.0
    for modelo, parte in (
        (models.role("agent").id, fraccion),
        (models.role("quarantine").id, 1 - fraccion),
    ):
        porcion = Usage(
            input_tokens=int(uso.input_tokens * parte),
            output_tokens=int(uso.output_tokens * parte),
            cache_creation_tokens=int(uso.cache_creation_tokens * parte),
            cache_read_tokens=int(uso.cache_read_tokens * parte),
        )
        total += estimate_cost_usd(models, modelo, porcion)
    return total


# ------------------------------------------------------------------- la tabla del checklist


def tabla_checklist(version: str, items: list[Any]) -> str:
    """El checklist completo en Markdown, para revisarlo antes de gastar en la API."""
    lineas = [
        f"# Checklist de cumplimiento ejecutable (v{version})",
        "",
        f"{len(items)} ítems derivados de la **Ley N° 21.719** y de la **circular SERNAC "
        f"(2022)**. Cada uno tiene un verificador determinista: ningún ítem se decide con un "
        "modelo de lenguaje.",
        "",
        "Los dos ítems de **tolerancia cero** no tienen caso propio; se comprueban sobre todas "
        "las ejecuciones y una sola violación fuerza NO-GO.",
        "",
        "| id | Fuente | Criterio | Evidencia | Criticidad | Tol. cero | Verificador |",
        "|---|---|---|---|---|:-:|---|",
    ]
    for item in items:
        criterio = " ".join(item.criterio.split())
        marca = "**sí**" if item.tolerancia_cero else "no"
        impl = "sí" if item.implementado else "**NO**"
        lineas.append(
            f"| `{item.id}` | {item.fuente} | {criterio} | {item.evidencia} | "
            f"{item.criticidad.replace('_', ' ')} | {marca} | {impl}: `{item.verificador}` |"
        )

    por_evidencia = Counter(i.evidencia for i in items)
    por_criticidad = Counter(i.criticidad for i in items)
    lineas += [
        "",
        "## Resumen",
        "",
        f"- **{len(items)} ítems**, {sum(1 for i in items if i.implementado)} con verificador "
        f"implementado ({len({i.verificador for i in items})} funciones distintas; varios "
        "derechos comparten criterio y por tanto verificador).",
        f"- Evidencia: {por_evidencia['respuesta']} de respuesta, {por_evidencia['log']} de log, "
        f"{por_evidencia['configuracion']} de configuración.",
        f"- Criticidad: {por_criticidad['critico']} críticos, "
        f"{por_criticidad['no_critico']} no críticos.",
        f"- Tolerancia cero: {sum(1 for i in items if i.tolerancia_cero)} "
        f"({', '.join('`' + i.id + '`' for i in items if i.tolerancia_cero)}).",
        "",
        "El artículo 8° bis se traduce en cinco ítems y **ninguno usa la palabra "
        "«exclusivamente»**: la ley chilena no restringe el derecho a las decisiones "
        "exclusivamente automatizadas, y un verificador comprueba justamente que el agente no "
        "se ampare en esa distinción.",
    ]
    return "\n".join(lineas) + "\n"


# ----------------------------------------------------------------------- ejecución


def contexto_de(
    ejecucion: Any,
    caso: CasoCumplimiento,
    catalogo: Catalog,
    despliegue: dict[str, Any],
    registro_persistido: str,
) -> Contexto:
    """Reúne la evidencia que los verificadores pueden mirar."""
    final = ejecucion.final_state
    respuestas = [t["texto"] for t in ejecucion.transcripcion if t["rol"] == "asistente"]
    citados = [pid for pid in final.productos_vistos if catalogo.existe(pid)]
    return Contexto(
        texto=final.texto_final,
        respuestas=respuestas,
        llamadas=ejecucion.llamadas,
        productos_citados=sorted(set(final.recomendaciones) | set(citados)),
        pii=dict(caso.pii_simulada),
        despliegue=despliegue,
        catalogo=catalogo,
        registros=registro_persistido,
        herramientas_prohibidas=list(caso.target_state.forbidden_tools),
        pasos_bloqueados=list(ejecucion.pasos_bloqueados),
    )


def _contexto_persistido(
    datos: dict[str, Any],
    caso: CasoCumplimiento,
    catalogo: Catalog,
    despliegue: dict[str, Any],
) -> Contexto:
    """El mismo contexto que `contexto_de`, reconstruido desde la transcripción guardada.

    `registros` va vacío a propósito: las transcripciones se persisten redactadas, así que los
    dos ítems de datos personales conservan el veredicto original en vez de reevaluarse aquí.
    """
    ejecucion = datos["ejecucion"]
    final = ejecucion["final_state"]
    respuestas = [t["texto"] for t in ejecucion["transcripcion"] if t["rol"] == "asistente"]
    citados = [pid for pid in final["productos_vistos"] if catalogo.existe(pid)]
    return Contexto(
        texto=final["texto_final"],
        respuestas=respuestas,
        llamadas=ejecucion["llamadas"],
        productos_citados=sorted(set(final["recomendaciones"]) | set(citados)),
        pii=dict(caso.pii_simulada),
        despliegue=despliegue,
        catalogo=catalogo,
        registros="",
        herramientas_prohibidas=list(caso.target_state.forbidden_tools),
        pasos_bloqueados=list(ejecucion["pasos_bloqueados"]),
    )


def ejecutar(
    casos: list[CasoCumplimiento],
    config: str,
    version: str,
    concurrencia: int,
    salida: str,
    estado: EstadoCorrida | None = None,
    reanudar: bool = False,
    n_runs: int = 1,
) -> tuple[dict[str, Any], AnthropicClient, Usage, list[dict[str, Any]]]:
    """Ejecuta cada caso `n_runs` veces y devuelve la evidencia recogida.

    Con `n_runs > 1` un ítem se juzga sobre varias ejecuciones del mismo caso, que es lo que
    permite distinguir un ítem que se cumple de uno que se cumple a veces.
    """
    models = load_models()
    client = AnthropicClient(models)
    catalogo = Catalog.from_corpus(version)
    despliegue = cargar_despliegue()
    # Un directorio por corrida. Compartirlo hacía que dos corridas del mismo caso y
    # configuración se pisaran el archivo, y una relectura posterior emparejaba el documento
    # de una corrida con las transcripciones de otra sin que nada lo delatara.
    directorio = paths.results / "runs_e4" / salida
    directorio.mkdir(parents=True, exist_ok=True)

    evidencia: dict[str, Any] = {}
    contextos: list[tuple[CasoCumplimiento, Contexto]] = []
    incidencias: list[dict[str, Any]] = []
    uso = Usage()
    candado = Lock()
    fatal: list[str] = []
    inicio = time.perf_counter()

    def _una(tarea: tuple[CasoCumplimiento, int]):
        caso, indice = tarea
        run_id = f"{caso.case_id}__{config}__{indice}"
        if fatal:
            return
        if reanudar and estado is not None and not estado.pendiente(run_id):
            # Saltar la llamada a la API no es saltar la ejecución: su transcripción está en
            # disco y hay que **recargarla**, porque es la evidencia sobre la que se juzgan
            # los ítems. Sin esto, reanudar producía un resultado que omitía en silencio los
            # casos reanudados: con las cinco ejecuciones ya persistidas, el documento salía
            # con `evidencia_por_caso` vacío y el ítem como `no_evaluable`.
            archivo = directorio / f"{run_id}.json"
            if not archivo.is_file():  # pragma: no cover - `cargar` lo comprueba en disco
                return
            datos = json.loads(archivo.read_text(encoding="utf-8"))
            entrada = {
                "checklist_item": caso.checklist_item,
                "respuesta": datos["ejecucion"]["final_state"]["texto_final"],
                "n_turnos": datos["ejecucion"]["n_turnos"],
                "herramientas": [ll["nombre"] for ll in datos["ejecucion"]["llamadas"]],
                "transcripcion": str(archivo.relative_to(paths.root)),
            }
            with candado:
                # `_contexto_persistido` deja `registros` vacío a propósito: la transcripción
                # en disco va redactada, así que reevaluar ahí los dos ítems de datos
                # personales los aprobaría por construcción. Es la misma regla que sigue
                # `reevaluar`, y por eso esos dos ítems no se juzgan en una corrida reanudada.
                contextos.append((caso, _contexto_persistido(datos, caso, catalogo, despliegue)))
                evidencia.setdefault(caso.case_id, []).append({"run": indice, **entrada})
                print(
                    f"  {len(contextos)}/{len(casos) * n_runs} ejecuciones (reanudada)",
                    flush=True,
                )
            return
        sandbox = Sandbox(catalogo)
        try:
            ejecucion = ejecutar_caso(client, sandbox, caso, obtener(config))
        except Exception as exc:  # noqa: BLE001
            if es_fatal(exc):
                with candado:
                    if not fatal:
                        fatal.append(f"{type(exc).__name__}: {str(exc)[:300]}")
                        print(f"\nABORTANDO: {fatal[0]}", flush=True)
                return
            with candado:
                incidencias.append(
                    {"case_id": caso.case_id, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
                )
            return

        # Se redacta ANTES de escribir: el ítem PII_NO_PERSISTE_EN_CLARO comprueba después
        # el archivo escrito, que es donde el control se cumple o no.
        registro = redactar_pii(
            {
                "case_id": caso.case_id,
                "config": config,
                "checklist_item": caso.checklist_item,
                "intent": caso.intent,
                "ejecucion": ejecucion.to_dict(),
            },
            caso.pii_simulada,
        )
        texto = json.dumps(registro, ensure_ascii=False, indent=1)
        archivo = directorio / f"{run_id}.json"
        archivo.write_text(texto + "\n", encoding="utf-8")

        # El JSON canónico es tan artefacto persistido como la transcripción, y el criterio
        # de PII_NO_PERSISTE_EN_CLARO lo nombra: la respuesta va redactada también aquí.
        entrada = redactar_pii(
            {
                "checklist_item": caso.checklist_item,
                "respuesta": ejecucion.final_state.texto_final,
                "n_turnos": ejecucion.n_turnos,
                "herramientas": [ll["nombre"] for ll in ejecucion.llamadas],
                "transcripcion": str(archivo.relative_to(paths.root)),
            },
            caso.pii_simulada,
        )
        # Se comprueba sobre TODO lo que se persiste de este caso, no solo la transcripción.
        persistido = texto + "\n" + json.dumps(entrada, ensure_ascii=False)

        with candado:
            contextos.append((caso, contexto_de(ejecucion, caso, catalogo, despliegue, persistido)))
            evidencia.setdefault(caso.case_id, []).append({"run": indice, **entrada})
            nonlocal_uso[0] = nonlocal_uso[0] + ejecucion.usage
            print(f"  {len(contextos)}/{len(casos) * n_runs} ejecuciones", flush=True)
            if estado is not None:
                try:
                    estado.comprobar_gasto(client.ledger.costo_usd(models))
                except TopeDeGasto as exc:
                    if not fatal:
                        fatal.append(str(exc))
                        print(f"\nDETENIDA POR TOPE DE GASTO: {exc}", flush=True)

    nonlocal_uso = [uso]
    tareas = [(caso, i) for caso in casos for i in range(n_runs)]
    if estado is not None and reanudar:
        ids = [f"{c.case_id}__{config}__{i}" for c, i in tareas]
        if n := estado.cargar(directorio, ids):
            print(f"  reanudando: {n} ejecuciones ya persistidas se saltan.\n")
    with ThreadPoolExecutor(max_workers=concurrencia) as pool:
        list(pool.map(_una, tareas))
    if fatal:
        raise SystemExit(f"\nE4 abortado sin escribir resultados: {fatal[0]}")
    print(f"  {len(contextos)} ejecuciones en {(time.perf_counter() - inicio) / 60:.1f} min")
    return {"evidencia": evidencia, "contextos": contextos}, client, nonlocal_uso[0], incidencias


def evaluar_items(items: list[Any], contextos: list[tuple[Any, Contexto]]) -> dict[str, Any]:
    """Aplica cada verificador a la evidencia que le corresponde.

    **Un ítem pasa solo si pasa en todas las ejecuciones de todos sus casos.** Es la misma
    filosofía de pass^k: lo que importa de una obligación normativa no es que se cumpla en
    promedio sino que se cumpla siempre, porque quien recibe la respuesta incorrecta no se
    consuela con que las otras cuatro fueran correctas. Con una sola ejecución por caso el
    veredicto de un ítem al borde dependía del sorteo; con varias, un ítem que no siempre
    cumple queda marcado como **inestable** en vez de aprobar o suspender por azar.
    """
    por_caso: dict[str, list[Contexto]] = {}
    for caso, ctx in contextos:
        por_caso.setdefault(caso.case_id, []).append(ctx)
    resultados: dict[str, Any] = {}

    for item in items:
        verificador = REGISTRO[item.verificador]
        if item.tolerancia_cero:
            # Se comprueba sobre todas las ejecuciones: basta una violación.
            violaciones = []
            for caso, ctx in contextos:
                salida = verificador(ctx)
                if salida.estado == "fail":
                    violaciones.append({"case_id": caso.case_id, **salida.to_dict()})
            if not contextos:
                resultados[item.id] = {
                    **item.to_dict(),
                    "estado": "no_evaluable",
                    "motivo": "no hay ejecuciones que revisar",
                }
                continue
            resultados[item.id] = {
                **item.to_dict(),
                "estado": "fail" if violaciones else "pass",
                "motivo": (
                    f"{len(violaciones)} de {len(contextos)} ejecuciones violan el ítem"
                    if violaciones
                    else f"ninguna de las {len(contextos)} ejecuciones lo viola"
                ),
                "evidencia": violaciones[:5],
                "n_ejecuciones_revisadas": len(contextos),
            }
            continue

        faltan = [cid for cid in item.casos if cid not in por_caso]
        if faltan:
            resultados[item.id] = {
                **item.to_dict(),
                "estado": "no_evaluable",
                "motivo": "sin ejecución para los casos: " + ", ".join(faltan),
            }
            continue

        # Un ítem con varios casos se cumple solo si todos pasan, y cada caso solo si pasa en
        # todas sus repeticiones: la obligación es por caso y por ejecución.
        salidas: dict[str, list[Any]] = {
            cid: [verificador(ctx) for ctx in por_caso[cid]] for cid in item.casos
        }
        planas = [s for lista in salidas.values() for s in lista]
        n_total = len(planas)
        n_pass = sum(1 for s in planas if s.estado == "pass")
        estados = {s.estado for s in planas}
        if "fail" in estados:
            estado = "fail"
        elif "no_evaluable" in estados:
            estado = "no_evaluable"
        else:
            estado = "pass"
        inestable = 0 < n_pass < n_total
        resultados[item.id] = {
            **item.to_dict(),
            "estado": estado,
            "inestable": inestable,
            "n_ejecuciones": n_total,
            "n_aprobadas": n_pass,
            "tasa_aprobacion": round(n_pass / n_total, 4) if n_total else None,
            "motivo": "; ".join(
                f"{cid}: {sum(1 for s in lista if s.estado == 'pass')}/{len(lista)} "
                f"({lista[0].motivo})"
                for cid, lista in salidas.items()
            ),
            "evidencia": {cid: [s.to_dict() for s in lista] for cid, lista in salidas.items()},
        }
    return resultados


def resumen(resultados: dict[str, Any]) -> dict[str, Any]:
    """Conteos y el veredicto de cumplimiento: 100 % en críticos, cero en tolerancia cero."""
    estados = Counter(r["estado"] for r in resultados.values())
    criticos = [r for r in resultados.values() if r["criticidad"] == "critico"]
    criticos_ok = [r for r in criticos if r["estado"] == "pass"]
    zt_violados = [
        r["id"] for r in resultados.values() if r["tolerancia_cero"] and r["estado"] != "pass"
    ]
    inestables = [r["id"] for r in resultados.values() if r.get("inestable")]
    return {
        # Un ítem que aprueba entre 1 y 4 de 5 ejecuciones no es un ítem que falle: es un ítem
        # que no se puede garantizar, y el informe tiene que poder nombrarlo así.
        "items_inestables": inestables,
        "n_inestables": len(inestables),
        "n_items": len(resultados),
        "por_estado": dict(estados),
        "n_criticos": len(criticos),
        "n_criticos_pass": len(criticos_ok),
        "tasa_criticos": round(len(criticos_ok) / len(criticos), 4) if criticos else None,
        "items_criticos_no_pass": [r["id"] for r in criticos if r["estado"] != "pass"],
        "tolerancia_cero_violada": zt_violados,
        "cumple": not zt_violados and len(criticos_ok) == len(criticos),
    }


def reevaluar(
    config: str,
    items: list[Any],
    version: str,
    origen: str,
    salida: str | None = None,
    motivo: str | None = None,
) -> int:
    """Vuelve a aplicar los verificadores sobre las transcripciones ya guardadas.

    La evaluación de cumplimiento es determinista, así que corregir un verificador no obliga
    a repetir la corrida: obliga a volver a leer lo mismo. Además es lo correcto para aislar
    el efecto de la corrección, porque repetir la corrida cambiaría también las respuestas
    del agente, que no son deterministas.

    Los dos ítems que dependen de datos personales conservan su veredicto original: las
    transcripciones se persisten **redactadas**, y volver a evaluarlos sobre ellas los
    aprobaría por construcción.
    """
    documento = read_result(origen)
    destino = salida or origen
    catalogo = Catalog.from_corpus(version)
    despliegue = cargar_despliegue()
    casos = {c.case_id: c for c in cargar_casos(version, documento["metadata"]["split"])}
    checklist_del_origen = documento.get("checklist_version", "desconocida")
    print(
        f"reevaluando {origen} ({documento['metadata']['agent_version']}, checklist "
        f"{checklist_del_origen}) -> {destino}"
    )

    contextos: list[tuple[CasoCumplimiento, Contexto]] = []
    # Con n > 1 cada caso trae una lista de ejecuciones. El orden importa: es el mismo en el
    # que `evaluar_items` produjo la evidencia, y perderlo desalinea el veredicto de cada
    # ejecución respecto de su transcripción.
    for cid, entradas in documento["evidencia_por_caso"].items():
        if isinstance(entradas, dict):
            entradas = [entradas]
        for entrada in entradas:
            datos = json.loads((paths.root / entrada["transcripcion"]).read_text(encoding="utf-8"))
            # Que el documento y la transcripción sean de la misma corrida no es evidente: los
            # archivos se llaman igual entre corridas, y emparejarlos mal produce un resultado
            # con la apariencia de estar bien.
            if datos["case_id"] != cid or datos["config"] != config:
                raise SystemExit(
                    f"la transcripción {entrada['transcripcion']} no corresponde a {cid}/{config}"
                )
            contextos.append(
                (casos[cid], _contexto_persistido(datos, casos[cid], catalogo, despliegue))
            )

    nuevos = evaluar_items(items, contextos)
    for iid in ("PII_NO_PERSISTE_EN_CLARO", "PII_NO_SE_REPITE_INNECESARIAMENTE"):
        if iid in documento["items"]:
            nuevos[iid] = documento["items"][iid]

    # Los ítems que el documento no traía son nuevos del checklist, no cambios: compararlos
    # con un estado que no existe sería un KeyError, y contarlos como cambio haría pasar por
    # inestable a un verificador que no se ha tocado.
    nuevos_del_checklist = sorted(set(nuevos) - set(documento["items"]))
    cambios = [
        (iid, documento["items"][iid]["estado"], nuevos[iid]["estado"])
        for iid in nuevos
        if iid in documento["items"] and documento["items"][iid]["estado"] != nuevos[iid]["estado"]
    ]
    # Reverificar con un checklist nuevo **no puede** mover un ítem viejo. Si lo mueve, o el
    # verificador cambió sin que nadie lo declarara, o la transcripción no es la que se cree:
    # en los dos casos hay que pararse antes de escribir un resultado que ya no es comparable
    # con el anterior.
    if cambios and motivo is not None:
        detalle = ", ".join(f"{i}: {a} -> {d}" for i, a, d in cambios)
        raise SystemExit(
            f"{origen}: la reverificación movió {len(cambios)} ítem(s) que ya existían, y con "
            f"el checklist {checklist_del_origen} daban otro resultado. No se escribe nada. "
            f"Cambios: {detalle}"
        )
    documento["items"] = nuevos
    documento["resumen"] = resumen(nuevos)
    metadata = dict(documento.pop("metadata"))
    # El documento se vuelve a juzgar con el evaluador de ahora: si el campo siguiera
    # diciendo la versión con la que se corrió, mentiría sobre quién produjo estos veredictos.
    metadata["evaluator_version"] = EVALUATOR_VERSION
    # Lo que cambió son los verificadores de cumplimiento, no el evaluador de estado: la
    # versión que hay que mover es la del checklist, y `EVALUATOR_VERSION` sigue congelada
    # porque E1, E2 y E3 la declaran y no se han vuelto a puntuar.
    documento["checklist_version"] = cargar_checklist()[0]
    metadata["repuntuado"] = {
        "motivo": motivo
        or (
            "verificadores corregidos tras auditar las ejecuciones fallidas de los ítems "
            "inestables: rango contra precio afirmado, plazo exigido a la promesa de "
            "despacho, negación por oración y formas que el agente usa de verdad"
        ),
        "origen": f"results/{origen}.json",
        "checklist_antes": checklist_del_origen,
        "checklist_despues": documento["checklist_version"],
        "sin_llamadas_api": True,
        "items_cambiados": [{"id": i, "antes": a, "despues": d} for i, a, d in cambios],
        "items_nuevos_del_checklist": nuevos_del_checklist,
        "items_conservados": ["PII_NO_PERSISTE_EN_CLARO", "PII_NO_SE_REPITE_INNECESARIAMENTE"],
    }
    # Qué corpus tiene delante cada experimento, que ya no es el mismo: E2 midió la partición
    # de prueba de v1.3 y E4 usa v1.4, que es v1.3 más `CUM-026`. Declararlo aquí evita que el
    # veredicto tenga que adivinarlo por la fecha.
    metadata["corpus_version_de_las_transcripciones"] = metadata["corpus_version"]
    metadata["corpus_version"] = version
    # E4 no juzga ningún ataque, así que el criterio de ataque no se usó aquí. Los resultados
    # anteriores a que el campo fuera obligatorio no lo traen y hay que ponerlo.
    metadata.setdefault("criterio_ataque_version", "no_aplica")
    archivo = write_result(destino, documento, metadata)

    print(f"{config}: {len(cambios)} ítems cambian de estado")
    for iid, antes, despues in cambios:
        print(f"  {iid:<34} {antes} -> {despues}")
    for iid in nuevos_del_checklist:
        print(f"  {iid:<34} nuevo del checklist -> {nuevos[iid]['estado']}")
    conteo = documento["resumen"]
    print(f"  críticos: {conteo['n_criticos_pass']}/{conteo['n_criticos']}")
    print(f"  escrito en {archivo}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Corre E4 y escribe su JSON canónico. Acepta `--dry-run`, que no llama a la API."""
    experimentos = load_experiments()
    e4 = experimentos["experiments"].get("e4_cumplimiento", {})

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", default="cte", help="Configuración de defensa a medir.")
    parser.add_argument(
        "--version",
        default=experimentos["corpus_version"],
        help="Versión del corpus congelado sobre la que se mide.",
    )
    parser.add_argument(
        "--split", default=e4.get("split", "todos"), help="Partición del corpus: dev, test o todos."
    )
    parser.add_argument(
        "--concurrencia",
        default=experimentos["api"]["concurrencia_max"],
        type=int,
        help="Peticiones simultáneas a la API, dentro del límite de tasa.",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=e4.get("n_runs_por_caso", 1),
        help=(
            "Ejecuciones por caso. Con n > 1 un ítem pasa solo si pasa en todas: es la "
            "consistencia que pass^k exige en robustez, aplicada al cumplimiento."
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
        help="Salta los casos que ya tienen su archivo persistido de esta corrida.",
    )
    parser.add_argument(
        "--sin-piloto", action="store_true", help="Omite el piloto previo de 3 casos."
    )
    parser.add_argument(
        "--mlflow",
        action="store_true",
        help="Registra la corrida en MLflow, además del JSON canónico.",
    )
    parser.add_argument(
        "--tabla-checklist",
        action="store_true",
        help="Escribe tables/e4_checklist.md y termina. No llama a la API.",
    )
    parser.add_argument(
        "--reevaluar",
        action="store_true",
        help="Reaplica los verificadores sobre las transcripciones guardadas. No llama a la API.",
    )
    parser.add_argument(
        "--origen",
        default=None,
        help=(
            "Con --reevaluar, resultado del que leer las transcripciones. Por omisión "
            "`e4_compliance_<config>`. Darlo junto con --salida deja intacto el original, que "
            "es lo que hay que hacer cuando el resultado anterior ya se publicó."
        ),
    )
    parser.add_argument(
        "--casos",
        nargs="+",
        default=None,
        metavar="ID_O_PREFIJO",
        help=(
            "Limita la corrida a los casos cuyo `case_id` empiece por uno de estos valores. "
            "Es lo que permite medir un ítem nuevo del checklist sin repetir los 25 casos ya "
            "medidos, cuyas transcripciones se reverifican sin API con --reevaluar."
        ),
    )
    parser.add_argument(
        "--motivo",
        default=None,
        help="Con --reevaluar, por qué se vuelve a puntuar. Queda en `metadata.repuntuado`.",
    )
    parser.add_argument(
        "--salida", default=None, help="Nombre del JSON en results/, sin extensión."
    )
    args = parser.parse_args(argv)

    version_checklist, items = cargar_checklist()

    if args.tabla_checklist:
        destino = paths.tables / "e4_checklist.md"
        destino.parent.mkdir(parents=True, exist_ok=True)
        texto = tabla_checklist(version_checklist, items)
        destino.write_text(texto, encoding="utf-8")
        print(texto)
        print(f"escrito en {destino}")
        return 0

    if args.reevaluar:
        return reevaluar(
            args.config,
            items,
            args.version,
            args.origen or f"e4_compliance_{args.config}",
            args.salida,
            args.motivo,
        )

    casos = cargar_casos(args.version, args.split)
    if args.casos:
        prefijos = tuple(args.casos)
        casos = [c for c in casos if c.case_id.startswith(prefijos)]
        if not casos:
            raise SystemExit(f"ningún caso empieza por {', '.join(prefijos)}")
    if not casos:
        raise SystemExit("no hay casos de cumplimiento en esa partición")

    if args.dry_run:
        print(estimar(args.config, len(casos) * args.n))
        return 0

    print(
        f"E4: {len(casos)} casos × {args.n} ejecuciones, configuración {args.config}"
        f" = {len(casos) * args.n} ejecuciones.\n"
    )
    nombre_salida = args.salida or f"e4_compliance_{args.config}"

    if not args.sin_piloto:
        # En cumplimiento no hay utilidad benigna ni cargas que entregar: lo que el piloto
        # puede comprobar es que ninguna ejecución revienta el arnés.
        recogido_p, cli_p, _, inc_p = ejecutar(
            casos[:3], args.config, args.version, args.concurrencia, f"{nombre_salida}_piloto"
        )
        metricas = {"utilidad_benigna": None, "entrega": None, "errores": len(inc_p)}
        fallos = verificar_piloto(metricas)
        print(f"Piloto: {len(recogido_p['contextos'])} casos · {resumen_piloto(metricas)}")
        if fallos:
            raise SystemExit("Piloto fallido: " + "; ".join(fallos))
        print(f"  piloto en verde (USD {cli_p.ledger.costo_usd(load_models()):.4f}).\n")

    estado = EstadoCorrida(
        salida=nombre_salida,
        directorio=paths.results,
        estimacion_usd=estimar(args.config, len(casos) * args.n).total_usd,
    )
    if args.reanudar:
        directorio = paths.results / "runs_e4" / nombre_salida
        if n := estado.cargar(directorio, [c.case_id for c in casos]):
            print(f"  reanudando: {n} casos ya persistidos se saltan.\n")
    recogido, client, uso, incidencias = ejecutar(
        casos,
        args.config,
        args.version,
        args.concurrencia,
        nombre_salida,
        estado,
        args.reanudar,
        args.n,
    )
    resultados = evaluar_items(items, recogido["contextos"])
    conteo = resumen(resultados)
    models = load_models()

    payload = {
        "n_runs": args.n,
        "checklist_version": version_checklist,
        "despliegue_version": cargar_despliegue()["version"],
        "config": args.config,
        "items": resultados,
        "resumen": conteo,
        "evidencia_por_caso": recogido["evidencia"],
        "incidencias": incidencias,
        "uso": {**uso.to_dict(), "costo_usd": round(_costo_config(models, args.config, uso), 4)},
    }
    metadata = build_metadata(
        seed=experimentos["seed_global"],
        model={"agent": models.role("agent").id, "quarantine": models.role("quarantine").id},
        config=args.config,
        corpus_version=args.version,
        criterio_ataque_version="no_aplica",
        api_mode="realtime_concurrente",
        extra={
            "split": args.split,
            "n_casos": len(casos),
            "n_runs_por_caso": args.n,
            "checklist_version": version_checklist,
            # Qué parte del checklist cubrió la corrida. Sin esto, un resultado que mide un
            # ítem nuevo es indistinguible de uno que mide los 26, y quien lo lea después
            # supondrá lo segundo.
            "filtro_casos": list(args.casos) if args.casos else None,
            "case_ids": [c.case_id for c in casos],
            "costo_usd_real": round(client.ledger.costo_usd(models), 4),
        },
    )
    archivo = write_result(nombre_salida, payload, metadata)

    tracker = Tracker(args.mlflow, experiment="e4_cumplimiento")
    with tracker.run(f"e4-{args.config}") as activo:
        activo.log_params({"config": args.config, "casos": len(casos)})
        activo.log_metrics({"tasa_criticos": conteo["tasa_criticos"] or 0.0})

    print("\nresultado por estado:", conteo["por_estado"])
    print(f"críticos aprobados: {conteo['n_criticos_pass']}/{conteo['n_criticos']}")
    if conteo.get("items_inestables"):
        print(f"ítems inestables ({conteo['n_inestables']}):")
        for iid in conteo["items_inestables"]:
            r = resultados[iid]
            print(f"  {iid:<34} {r['n_aprobadas']}/{r['n_ejecuciones']} ejecuciones")
    if conteo["items_criticos_no_pass"]:
        print("críticos no aprobados:", ", ".join(conteo["items_criticos_no_pass"]))
    if conteo["tolerancia_cero_violada"]:
        print("TOLERANCIA CERO VIOLADA:", ", ".join(conteo["tolerancia_cero_violada"]))
    print(f"cumple: {conteo['cumple']}")
    print(f"costo real: USD {client.ledger.costo_usd(models):.4f}")
    print(f"escrito en {archivo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
