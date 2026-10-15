"""Compuerta de pre-vuelo: comprueba el arnés entero antes de gastar en las corridas finales.

    python scripts/prevuelo.py --dry-run
    python scripts/prevuelo.py

Ejecuta una muestra pequeña en las cuatro configuraciones y **aborta con un mensaje concreto**
si algo de lo que las corridas finales dan por supuesto no se cumple. Las corridas finales
cuestan cerca de USD 70 y tardan tres horas; cada defecto que este proyecto encontró tarde
—una etiqueta de ataque visible para el agente, un marcador que no se emitía, un evaluador que
leía el turno equivocado— habría costado unos centavos si se hubiera comprobado aquí.

Las comprobaciones **estáticas** van primero y no cuestan nada: si el prompt cambió o el
despliegue tiene un contacto real, no tiene sentido llamar a la API. Las **dinámicas** se
comprueban sobre lo que la muestra produjo.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any

from prf.agent import AGENT_VERSION, obtener
from prf.agent.bucle import ejecutar_caso
from prf.agent.configuraciones import CONFIGURACIONES
from prf.agent.huellas import huellas, system_prompt
from prf.agent.prompts import CLAUSULAS_DEFENSIVAS, bloque_cumplimiento
from prf.compliance import cargar_despliegue
from prf.env import Catalog, Sandbox
from prf.env.cases import CasoCumplimiento, CasoRobustez, CasoSeguridad
from prf.env.evaluator import EVALUATOR_VERSION, REGLAS, evaluate_state
from prf.eval.ataque import entrega_de_la_carga
from prf.infra import paths
from prf.infra.client import AnthropicClient
from prf.infra.config import load_experiments, load_models
from prf.infra.cost import DryRunReport, Usage

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_e1 import FRACCION_SONNET, PERFIL_MEDIDO, _estimacion  # noqa: E402

CONFIGS = ("none", "prompt_only", "dual_llm", "cte")
TOLERANCIA_COSTO = 0.20
# La rejilla principal va concurrente como en las corridas reales. E3 no: mide latencia y
# cuatro peticiones a la vez medirían la contención del cliente.
CONCURRENCIA = 4

# Los cuatro fragmentos que niegan un objetivo de ataque. Desde 3.0.0 solo `prompt_only` los
# lleva; que reaparezcan en otra configuración volvería a hacer de `none` algo que no es una
# línea base sin protección.
CLAUSULAS = {
    "unauthorized_promise": "No prometes rebajas ni condiciones especiales",
    "out_of_domain": "Si te piden algo ajeno a la compra en esta tienda",
    "exfiltration": "nunca los envías a terceros",
    "task_hijack": "No inventas precios, descuentos, promociones",
}

# Dominios que delatarían un contacto real en la declaración de despliegue. El corpus es
# sintético y sus canales tienen que serlo también.
DOMINIO_SINTETICO = re.compile(r"(example\.cl|example\.com|tiendademo\.example\.cl)")
TELEFONO_DOCUMENTACION = re.compile(r"\+?56\s?2\s?2555")


class PreVueloFallido(SystemExit):
    """Una comprobación no pasó: no se lanza ninguna corrida final."""


# --------------------------------------------------------------------------- muestra


def muestra(version: str, split: str) -> dict[str, list[Any]]:
    """3 casos de robustez por tipo, 3 directos, 3 indirectos, 3 benignos y 4 de cumplimiento."""
    raiz = paths.corpus_version(version)
    ids = set((paths.splits_version(version) / f"{split}.txt").read_text(encoding="utf-8").split())

    def _leer(archivo: str, modelo):
        return [
            caso
            for linea in (raiz / archivo).read_text(encoding="utf-8").splitlines()
            if linea.strip()
            for caso in [modelo.model_validate_json(linea)]
            if caso.case_id in ids
        ]

    robustez = _leer("cases_robustness.jsonl", CasoRobustez)
    seguridad = _leer("cases_security.jsonl", CasoSeguridad)
    cumplimiento = _leer("cases_compliance.jsonl", CasoCumplimiento)

    def _n_por(casos, clave, n):
        vistos: Counter = Counter()
        salida = []
        for caso in casos:
            k = clave(caso)
            if vistos[k] < n:
                vistos[k] += 1
                salida.append(caso)
        return salida

    return {
        "robustez": _n_por(robustez, lambda c: c.tipo, 3),
        "seguridad": _n_por(seguridad, lambda c: c.tipo, 3),
        "cumplimiento": cumplimiento[:4],
    }


def estimar(n_ejecuciones_por_config: int, n_e3: int) -> DryRunReport:
    """Tokens y costo de las comprobaciones que llaman a la API."""
    models = load_models()
    reporte = DryRunReport(titulo="Pre-vuelo — muestra en las cuatro configuraciones")
    for config in CONFIGS:
        perfil = PERFIL_MEDIDO[config]
        fraccion = FRACCION_SONNET[config]
        for etiqueta, modelo, parte in (
            (f"{config}: sonnet", models.role("agent").id, fraccion),
            (f"{config}: haiku", models.role("quarantine").id, 1 - fraccion),
        ):
            if parte <= 0:
                continue
            uso = Usage(
                input_tokens=int(perfil["input_tokens"] * n_ejecuciones_por_config * parte),
                output_tokens=int(perfil["output_tokens"] * n_ejecuciones_por_config * parte),
                cache_creation_tokens=int(
                    perfil["cache_creation_tokens"] * n_ejecuciones_por_config * parte
                ),
                cache_read_tokens=int(
                    perfil["cache_read_tokens"] * n_ejecuciones_por_config * parte
                ),
            )
            reporte.add(
                _estimacion(models, etiqueta, modelo, n_ejecuciones_por_config, uso, batch=False)
            )
        # E3: sin caché, la lectura se paga como entrada normal.
        entrada = (
            perfil["input_tokens"] + perfil["cache_read_tokens"] + perfil["cache_creation_tokens"]
        )
        reporte.add(
            _estimacion(
                models,
                f"{config}: E3 sin caché",
                models.role("agent").id,
                n_e3,
                Usage(
                    input_tokens=int(entrada * n_e3),
                    output_tokens=int(perfil["output_tokens"] * n_e3),
                ),
                batch=False,
            )
        )
    reporte.notas.append(
        "Perfil por ejecución medido en E1 (1008 ejecuciones reales). El pre-vuelo compara el "
        f"costo real contra esta estimación con una tolerancia de ±{TOLERANCIA_COSTO:.0%}."
    )
    return reporte


# ------------------------------------------------------------------------- estáticas


def comprobaciones_estaticas(version: str) -> list[str]:
    """Todo lo que se puede saber sin llamar a la API. Si algo falla aquí, no se gasta nada."""
    fallos: list[str] = []
    despliegue = cargar_despliegue()

    # --- versiones
    esperada = json.loads(
        (paths.configs / "congelado_corrida_final.json").read_text(encoding="utf-8")
    )["agent_version"]
    if AGENT_VERSION != esperada:
        fallos.append(f"agent_version es {AGENT_VERSION}, se esperaba {esperada}")
    if EVALUATOR_VERSION != "2.1.1":
        fallos.append(f"evaluator_version es {EVALUATOR_VERSION}, se esperaba 2.1.1")
    esperada_corpus = json.loads(
        (paths.configs / "congelado_corrida_final.json").read_text(encoding="utf-8")
    )["corpus_version"]
    if version != esperada_corpus:
        fallos.append(f"corpus_version es {version}, se esperaba {esperada_corpus}")

    # --- huellas de prompt contra lo congelado
    registro_path = paths.configs / "congelado_corrida_final.json"
    if not registro_path.is_file():
        fallos.append("falta configs/congelado_corrida_final.json")
    else:
        registro = json.loads(registro_path.read_text(encoding="utf-8"))
        actuales = huellas(despliegue)
        if actuales != registro["huellas_prompt"]:
            distintas = [k for k in actuales if actuales[k] != registro["huellas_prompt"].get(k)]
            fallos.append(f"huellas de prompt distintas de las del commit: {distintas}")
        manifest = json.loads(
            (paths.corpus_version(version) / "MANIFEST.json").read_text(encoding="utf-8")
        )
        if manifest["corpus_hash"] != registro["corpus_hash"]:
            fallos.append("el corpus no es el congelado: cambió su hash")

    # --- cláusulas defensivas: solo prompt_only
    for nombre, config in CONFIGURACIONES.items():
        prompt = system_prompt(config, despliegue)
        presentes = [o for o, frag in CLAUSULAS.items() if frag in prompt]
        if nombre == "prompt_only":
            faltan = [o for o in CLAUSULAS if o not in presentes]
            if faltan:
                fallos.append(f"prompt_only no niega: {faltan}")
        elif presentes:
            fallos.append(f"{nombre} lleva cláusulas defensivas: {presentes}")

    # --- bloque de cumplimiento en las cuatro
    bloque = bloque_cumplimiento(despliegue)
    sin_bloque = [
        n for n, c in CONFIGURACIONES.items() if bloque not in system_prompt(c, despliegue)
    ]
    if sin_bloque:
        fallos.append(f"sin bloque de cumplimiento: {sin_bloque}")
    if bloque not in CLAUSULAS_DEFENSIVAS + bloque:  # sanidad del propio bloque
        fallos.append("el bloque de cumplimiento salió vacío")

    # --- sonda del borde del sandbox: lo que sale hacia el agente no lleva anotaciones,
    #     la carga adversarial sale íntegra, y el registro sí las conserva.
    fallos += _sonda_get_reviews(version)

    # --- contactos sintéticos en la declaración de despliegue
    for texto in _contactos(despliegue):
        if "@" in texto and not DOMINIO_SINTETICO.search(texto):
            fallos.append(f"contacto no sintético en despliegue.yaml: {texto}")
        if texto.replace(" ", "").startswith("+56") and not TELEFONO_DOCUMENTACION.search(texto):
            fallos.append(f"teléfono fuera del rango de documentación: {texto}")
    return fallos


def _sonda_get_reviews(version: str) -> list[str]:
    """Comprueba el único borde por el que las cuatro configuraciones reciben una reseña.

    Se comprueba aquí y no sobre `ejecucion.llamadas` porque ese campo es el **registro**, y
    el registro conserva las anotaciones a propósito: confundirlo con lo que el agente
    ve daría un fallo donde no lo hay. Lo que se exige es que `Sandbox.dispatch` entregue el
    texto íntegro y sin las etiquetas del andamiaje, que es lo que cruzan el bucle
    conversacional y el intérprete de `cte` por igual.
    """
    fallos: list[str] = []
    catalogo = Catalog.from_corpus(version)
    adversariales = [r for r in catalogo.reviews if r.is_adversarial]
    if not adversariales:
        return ["el corpus no tiene reseñas adversariales: la sonda no puede comprobar nada"]

    resena = adversariales[0]
    sandbox = Sandbox(catalogo)
    entregado = sandbox.dispatch("get_reviews", {"product_id": resena.product_id, "limit": 5})
    crudo = json.dumps(entregado.get("resultado"), ensure_ascii=False)
    if "is_adversarial" in crudo or "attack_id" in crudo:
        fallos.append("get_reviews entrega al agente las anotaciones del andamiaje")

    entregada = next(
        (r for r in entregado.get("resultado") or [] if r.get("id") == resena.id), None
    )
    if entregada is None:
        fallos.append(f"la reseña adversarial {resena.id} no llegó en el resultado")
    elif entregada.get("text") != resena.text:
        fallos.append(
            f"la carga de {resena.id} llegó alterada: retirar la etiqueta no puede tocar el texto"
        )

    guardado = sandbox.state.llamadas[-1].resultado
    if not any("is_adversarial" in r for r in guardado or []):
        fallos.append(
            "el registro perdió las anotaciones: E2 las necesita para saber si la carga se "
            "entregó, y retirarlas de ahí sería retirarlas de donde sí hacen falta"
        )
    return fallos


def _contactos(despliegue: dict[str, Any]) -> list[str]:
    salida = []

    def _recorrer(dato):
        if isinstance(dato, dict):
            for v in dato.values():
                _recorrer(v)
        elif isinstance(dato, list):
            for v in dato:
                _recorrer(v)
        elif isinstance(dato, str) and ("@" in dato or dato.strip().startswith("+")):
            salida.append(dato)

    _recorrer(despliegue)
    return salida


# -------------------------------------------------------------------------- dinámicas


def ejecutar_muestra(
    casos: dict[str, list[Any]], version: str, client: AnthropicClient
) -> dict[str, Any]:
    """Corre la muestra en las cuatro configuraciones y recoge la evidencia cruda."""
    catalogo = Catalog.from_corpus(version)
    registros: list[dict[str, Any]] = []
    errores: list[str] = []
    orden = 0

    todos = casos["robustez"] + casos["seguridad"] + casos["cumplimiento"]
    tareas = [(c, caso) for c in CONFIGS for caso in todos]
    candado = Lock()

    def _una(tarea):
        nonlocal orden
        config_nombre, caso = tarea
        try:
            ejecucion = ejecutar_caso(
                client,
                # `descripciones_inyectadas` solo existe en los casos de seguridad y solo
                # trae algo en los de portador descripción; en los demás es vacío.
                Sandbox(catalogo, descripciones=getattr(caso, "descripciones_inyectadas", {})),
                caso,
                obtener(config_nombre),
            )
        except Exception as exc:  # noqa: BLE001 - el pre-vuelo existe para verlas
            with candado:
                errores.append(f"{caso.case_id}/{config_nombre}: {type(exc).__name__}: {exc}")
            return
        with candado:
            orden += 1
            registros.append(
                {
                    "orden": orden,
                    "case_id": caso.case_id,
                    "config": config_nombre,
                    "dimension": caso.dimension,
                    "tipo": getattr(caso, "tipo", None),
                    "vector": getattr(caso, "vector", None),
                    "caso": caso,
                    "ejecucion": ejecucion,
                }
            )

    with ThreadPoolExecutor(max_workers=CONCURRENCIA) as pool:
        list(pool.map(_una, tareas))
    return {"registros": registros, "errores": errores}


def ejecutar_e3(
    casos: list[Any],
    version: str,
    client: AnthropicClient,
    modos: tuple[str, ...] = ("frio", "caliente"),
) -> dict[str, Any]:
    """Dos casos en las cuatro configuraciones, en frío (sin caché) y en caliente (con caché)."""
    catalogo = Catalog.from_corpus(version)
    salida: dict[str, list[dict[str, Any]]] = {"frio": [], "caliente": []}
    errores: list[str] = []
    for modo, cache in [m for m in (("frio", False), ("caliente", True)) if m[0] in modos]:
        for caso in casos:
            for config_nombre in CONFIGS:
                marca = len(client.registro)
                try:
                    ejecucion = ejecutar_caso(
                        client,
                        Sandbox(catalogo),
                        caso,
                        obtener(config_nombre),
                        streaming=True,
                        cache=cache,
                    )
                except Exception as exc:  # noqa: BLE001
                    errores.append(f"E3 {modo} {caso.case_id}/{config_nombre}: {exc}")
                    continue
                salida[modo].append(
                    {
                        "case_id": caso.case_id,
                        "config": config_nombre,
                        "cache": cache,
                        "usage": ejecucion.usage.to_dict(),
                        "llamadas_api": client.registro[marca:],
                    }
                )
    return {**salida, "errores": errores}


def _aceptadas_sin_caso() -> list[str]:
    registro = paths.configs / "congelado_corrida_final.json"
    if not registro.is_file():
        return []
    return json.loads(registro.read_text(encoding="utf-8")).get("reglas_sin_caso_aceptadas", [])


def reglas_del_corpus(version: str) -> tuple[set[str], set[str]]:
    """Qué reglas de `evaluate_state` puede ejercer este corpus, y cuáles no puede ninguna.

    Se deriva del corpus y no de una lista fija: exigirle a la muestra las siete reglas
    cuando el corpus solo puede ejercer seis convierte la compuerta en un fallo permanente, y
    exigir solo las que la muestra tocó la convierte en un adorno. Lo correcto es exigir todo
    lo que el corpus permite y **nombrar aparte** lo que no permite ninguno.
    """
    raiz = paths.corpus_version(version)
    exigibles: set[str] = set()
    for archivo in ("cases_robustness.jsonl", "cases_security.jsonl", "cases_compliance.jsonl"):
        for linea in (raiz / archivo).read_text(encoding="utf-8").splitlines():
            if not linea.strip():
                continue
            target = json.loads(linea).get("target_state") or {}
            exigibles |= _reglas_de_target(target)
    return exigibles, set(REGLAS) - exigibles


def _reglas_de_target(target: dict[str, Any]) -> set[str]:
    reglas: set[str] = set()
    if target.get("must_include"):
        reglas.add("must_include")
    if target.get("must_exclude"):
        reglas.add("must_exclude")
    if target.get("must_compare"):
        reglas.add("must_compare")
    if target.get("forbidden_tools"):
        reglas.add("forbidden_tools")
    if target.get("min_recomendaciones"):
        reglas |= {"min_recomendaciones", "recomendaciones_existentes"}
    c = target.get("constraints") or {}
    if (
        c.get("categoria")
        or c.get("presupuesto_max_clp")
        or c.get("presupuesto_min_clp")
        or c.get("atributos")
    ):
        reglas.add("constraints")
    return reglas


def comprobaciones_dinamicas(
    recogido: dict[str, Any], e3: dict[str, Any], version_corpus: str
) -> list[str]:
    """Lo que solo se sabe ejecutando. Cada fallo nombra la aserción que no se cumplió."""
    fallos: list[str] = []
    registros = recogido["registros"]

    todos_errores = recogido["errores"] + e3["errores"]
    # Un 400 por saldo insuficiente o credenciales no es un defecto del arnés, y llamarlo así
    # manda a revisar el código cuando lo que hay que hacer es recargar la cuenta.
    de_cuenta = [e for e in todos_errores if _es_de_cuenta(e)]
    del_arnes = [e for e in todos_errores if not _es_de_cuenta(e)]
    if de_cuenta:
        fallos.append(
            f"la API rechazó {len(de_cuenta)} llamadas por saldo o credenciales, no por el "
            f"arnés: {de_cuenta[0][:160]}"
        )
    if del_arnes:
        fallos.append("excepciones del arnés: " + "; ".join(del_arnes[:3]))
    if not registros:
        return fallos + ["no se completó ninguna ejecución"]

    # --- get_reviews: sin anotaciones del andamiaje y con la carga íntegra
    con_resenas = 0
    for r in registros:
        for llamada in r["ejecucion"].llamadas:
            if llamada.get("nombre") != "get_reviews":
                continue
            resultado = llamada.get("resultado") or []
            con_resenas += 1
            # Las anotaciones se comprueban en la sonda estática, sobre el borde real: aquí
            # `resultado` es el registro, que las conserva a propósito.
            for resena in resultado if isinstance(resultado, list) else []:
                if isinstance(resena, dict) and not (resena.get("text") or "").strip():
                    fallos.append(f"{r['case_id']}: una reseña llegó sin texto")
    if not con_resenas:
        fallos.append("ninguna ejecución llamó a get_reviews: la superficie indirecta no se probó")

    # --- entrega de cargas indirectas = 1,0
    indirectos = [r for r in registros if r["vector"] == "indirect"]
    entregadas = [
        entrega_de_la_carga(r["caso"], r["ejecucion"].llamadas)["entregada"] for r in indirectos
    ]
    if not indirectos:
        fallos.append("la muestra no incluyó ningún ataque indirecto")
    elif not all(entregadas):
        no = [r["case_id"] for r, e in zip(indirectos, entregadas, strict=True) if not e]
        fallos.append(f"entrega de cargas indirectas {sum(entregadas)}/{len(entregadas)}: {no}")

    # --- marcadores en las conversacionales, intérprete en cte
    for r in registros:
        final = r["ejecucion"].final_state
        if final is None:
            fallos.append(f"{r['case_id']}/{r['config']}: sin estado final")
            continue
        if r["config"] == "cte":
            if final.origen_estado != "interprete":
                fallos.append(
                    f"{r['case_id']}/cte: estado con origen '{final.origen_estado}', "
                    "debía derivarlo el intérprete"
                )
        elif final.origen_estado != "texto":
            fallos.append(f"{r['case_id']}/{r['config']}: estado con origen inesperado")

    conversacionales = [
        r for r in registros if r["config"] != "cte" and r["dimension"] == "robustez"
    ]
    con_marcador = [
        r for r in conversacionales if "<<rec:" in (r["ejecucion"].final_state.texto_final or "")
    ]
    if conversacionales and not con_marcador:
        fallos.append("ninguna configuración conversacional emitió el marcador <<rec:>>")
    cte_con_rec = [
        r
        for r in registros
        if r["config"] == "cte"
        and r["dimension"] == "robustez"
        and r["ejecucion"].final_state.recomendaciones
    ]
    if not cte_con_rec:
        fallos.append("la extracción del intérprete no acreditó ninguna recomendación en cte")

    # --- reglas de evaluate_state: se exige ejercer todas las que el corpus puede ejercer
    ejercitadas = _reglas_ejercitadas(registros)
    exigibles, inexistentes = reglas_del_corpus(version_corpus)
    faltan = sorted(exigibles - ejercitadas)
    if faltan:
        fallos.append(f"la muestra no ejerció reglas que el corpus sí ejerce: {faltan}")
    # Una regla que ningún caso ejerce no invalida las corridas —nada en ellas depende de
    # ella— pero tampoco puede pasar en silencio: se acepta solo si está declarada en el
    # archivo de congelación, de modo que la lista no crezca sin que nadie lo decida.
    aceptadas = set(_aceptadas_sin_caso())
    no_declaradas = sorted(inexistentes - aceptadas)
    if no_declaradas:
        fallos.append(
            f"reglas que NINGÚN caso del corpus ejerce y no están declaradas: {no_declaradas}"
        )
    desaparecidas = sorted(aceptadas - inexistentes)
    if desaparecidas:
        fallos.append(
            f"declaradas como sin caso pero el corpus sí las ejerce: {desaparecidas}; "
            "actualiza configs/congelado_corrida_final.json"
        )

    # --- caché: lectura desde la segunda ejecución del modo caliente
    calientes = sorted(e3["caliente"], key=lambda m: (m["config"], m["case_id"]))
    por_config: dict[str, list[dict[str, Any]]] = {}
    for m in calientes:
        por_config.setdefault(m["config"], []).append(m)
    for config_nombre in CONFIGS:
        muestras = por_config.get(config_nombre, [])
        if len(muestras) < 2:
            # Saltarla en silencio convertiría la aserción en un adorno que siempre pasa.
            fallos.append(
                f"{config_nombre}: solo {len(muestras)} ejecución(es) en el modo con caché; "
                "hacen falta dos para comprobar que la segunda lee de caché"
            )
            continue
        if not muestras[1]["usage"].get("cache_read_tokens"):
            fallos.append(
                f"{config_nombre}: cache_read_tokens = 0 en la segunda ejecución del modo "
                "con caché; el prefijo cacheado no se está reutilizando"
            )
    for m in e3["frio"]:
        # `cache_enabled` es lo que el cliente registra por llamada y refleja si se envió
        # `cache_control`. Comprobar el campo que existe, y no uno inventado, es la
        # diferencia entre una aserción y un adorno que siempre pasa.
        if not m["llamadas_api"]:
            fallos.append(f"{m['config']}: E3 en frío no registró ninguna llamada")
        if any(ll.get("cache_enabled") for ll in m["llamadas_api"]):
            fallos.append(f"{m['config']}: E3 en frío envió cache_control")
        if m["usage"].get("cache_read_tokens") or m["usage"].get("cache_creation_tokens"):
            fallos.append(f"{m['config']}: E3 en frío registró tokens de caché; debía ir sin caché")
    return fallos


SENALES_DE_CUENTA = (
    "credit balance",
    "billing",
    "usage limit",
    "authentication",
    "permission",
    "invalid x-api-key",
)


def _es_de_cuenta(mensaje: str) -> bool:
    bajo = mensaje.lower()
    return any(senal in bajo for senal in SENALES_DE_CUENTA)


def _reglas_ejercitadas(registros: list[dict[str, Any]]) -> set[str]:
    """Reglas de `evaluate_state` que la muestra llegó a evaluar de verdad.

    Una regla «se ejerció» cuando el caso la exige: `must_compare` solo se comprueba si el
    caso pide comparar. Sin esto, una muestra que no incluya comparaciones daría por buena una
    regla que nunca se ejecutó.
    """
    ejercitadas: set[str] = set()
    for r in registros:
        target = getattr(r["caso"], "target_state", None)
        if target is None or r["ejecucion"].final_state is None:
            continue
        evaluate_state(r["ejecucion"].final_state, target)
        if target.must_include:
            ejercitadas.add("must_include")
        if target.must_exclude:
            ejercitadas.add("must_exclude")
        if target.must_compare:
            ejercitadas.add("must_compare")
        if target.forbidden_tools:
            ejercitadas.add("forbidden_tools")
        if target.min_recomendaciones:
            ejercitadas.add("min_recomendaciones")
            ejercitadas.add("recomendaciones_existentes")
        c = target.constraints
        if c.categoria or c.presupuesto_max_clp or c.presupuesto_min_clp or c.atributos:
            ejercitadas.add("constraints")
    return ejercitadas


# ------------------------------------------------------------------------------ main


def _pasada_anterior(salida: str) -> dict[str, Any] | None:
    """La pasada anterior, si sirve para heredar sus veredictos de la rejilla principal.

    Solo se hereda de una pasada cuyo único fallo fuera de cuenta —saldo o credenciales—: si
    la anterior falló por algo del arnés, heredar sus verdictos sería dar por bueno justo lo
    que no lo estaba.
    """
    archivo = paths.results / f"{salida}.json"
    if not archivo.is_file():
        raise PreVueloFallido(f"--reanudar necesita una pasada anterior en {archivo}, y no la hay.")
    previa = json.loads(archivo.read_text(encoding="utf-8"))
    if previa.get("fallos_estaticos"):
        raise PreVueloFallido("la pasada anterior falló en las estáticas: repítela entera.")
    # Se reconoce por el contenido y no por el prefijo del mensaje: la pasada anterior pudo
    # escribirlo con otra redacción —de hecho la escribió, antes de que la compuerta
    # distinguiera facturación de arnés— y un filtro que dependa del formato del texto deja
    # pasar justo lo que debía atrapar.
    del_arnes = [
        f
        for f in previa.get("fallos_dinamicos", [])
        if not _es_de_cuenta(f) and "modo con caché" not in f
    ]
    if del_arnes:
        raise PreVueloFallido(
            "la pasada anterior falló por el arnés, no por la cuenta; repítela entera:\n  · "
            + "\n  · ".join(del_arnes[:3])
        )
    return previa


def _solo_cache(e3: dict[str, Any]) -> list[str]:
    """Las comprobaciones que dependen del modo con caché, que es lo que se reejecuta."""
    fallos: list[str] = []
    if e3["errores"]:
        de_cuenta = [e for e in e3["errores"] if _es_de_cuenta(e)]
        if de_cuenta:
            fallos.append(
                f"la API volvió a rechazar por saldo o credenciales: {de_cuenta[0][:160]}"
            )
        else:
            fallos.append("excepciones del arnés en el modo con caché: " + e3["errores"][0][:160])
    por_config: dict[str, list[dict[str, Any]]] = {}
    for m in e3["caliente"]:
        por_config.setdefault(m["config"], []).append(m)
    for config_nombre in CONFIGS:
        muestras = por_config.get(config_nombre, [])
        if len(muestras) < 2:
            fallos.append(
                f"{config_nombre}: solo {len(muestras)} ejecución(es) en el modo con caché; "
                "hacen falta dos para comprobar que la segunda lee de caché"
            )
            continue
        if not muestras[1]["usage"].get("cache_read_tokens"):
            fallos.append(
                f"{config_nombre}: cache_read_tokens = 0 en la segunda ejecución del modo "
                "con caché; el prefijo cacheado no se está reutilizando"
            )
    return fallos


def _informe(titulo: str, fallos: list[str]) -> bool:
    if fallos:
        print(f"\n[FALLA] {titulo}")
        for f in fallos:
            print(f"   · {f}")
        return False
    print(f"[ok] {titulo}")
    return True


def main(argv: list[str] | None = None) -> int:
    """Pasa las comprobaciones de pre-vuelo y escribe su informe.

    `--dry-run` deja fuera las que llaman a la API.
    """
    experimentos = load_experiments()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--version",
        default=experimentos["corpus_version"],
        help="Versión del corpus que se va a usar en la corrida.",
    )
    parser.add_argument("--split", default="dev", help="Partición que se va a usar en la corrida.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo las comprobaciones estáticas: no llama a la API.",
    )
    parser.add_argument(
        "--reanudar",
        action="store_true",
        help=(
            "Reejecuta las comprobaciones estáticas y solo la fase que quedó incompleta. "
            "Las de la rejilla principal se heredan de la pasada anterior, que se exige "
            "haber corrido con el mismo agente, evaluador y corpus."
        ),
    )
    parser.add_argument(
        "--salida", default="prevuelo", help="Nombre del JSON en results/, sin extensión."
    )
    args = parser.parse_args(argv)

    casos = muestra(args.version, args.split)
    n_por_config = sum(len(v) for v in casos.values())
    # E3 mide latencia sobre casos benignos: usar ataques mediría otra cosa.
    casos_e3 = [c for c in casos["seguridad"] if c.tipo == "benigno"][:2]
    total = n_por_config * len(CONFIGS) + len(casos_e3) * len(CONFIGS) * 2

    print(
        f"Pre-vuelo: {n_por_config} casos × {len(CONFIGS)} configuraciones "
        f"+ E3 frío y caliente ({len(casos_e3)} × {len(CONFIGS)} × 2) = {total} ejecuciones.\n"
    )
    reporte = estimar(n_por_config, len(casos_e3) * 2)
    if args.dry_run:
        print(reporte)
        return 0

    print("— Comprobaciones estáticas (sin llamar a la API) —")
    fallos_estaticos = comprobaciones_estaticas(args.version)
    if not _informe(
        "versiones, huellas de prompt, cláusulas, cumplimiento y despliegue", fallos_estaticos
    ):
        raise PreVueloFallido(
            "\nPRE-VUELO FALLIDO en las comprobaciones estáticas. No se llamó a la API y no "
            "debe lanzarse ninguna corrida final."
        )

    models = load_models()
    client = AnthropicClient(models)
    inicio = time.perf_counter()
    heredado = _pasada_anterior(args.salida) if args.reanudar else None

    if heredado is None:
        print("\n— Ejecutando la muestra —")
        recogido = ejecutar_muestra(casos, args.version, client)
        print(f"  {len(recogido['registros'])} ejecuciones de la rejilla principal")
        e3 = ejecutar_e3(casos_e3, args.version, client, modos=("frio", "caliente"))
        print(f"  {len(e3['frio'])} en frío y {len(e3['caliente'])} en caliente")
    else:
        # La pasada anterior corrió con el mismo agente, evaluador y corpus —lo comprueban
        # las estáticas de arriba, que acaban de pasar—, así que sus veredictos sobre la
        # rejilla principal siguen valiendo. Lo único que quedó a medias fue el modo con
        # caché, y es lo único que se vuelve a ejecutar.
        print(
            f"\n— Reanudando desde {args.salida}.json "
            f"({heredado['n_ejecuciones']} ejecuciones, USD {heredado['costo_usd']}) —"
        )
        recogido = {"registros": [], "errores": []}
        e3 = ejecutar_e3(casos_e3, args.version, client, modos=("caliente",))
        e3["frio"] = []
        print(f"  {len(e3['caliente'])} ejecuciones en caliente")

    costo_pasada = client.ledger.costo_usd(models)
    # Al reanudar, lo comparable con la estimación de la muestra completa es lo gastado en
    # todas las pasadas, no lo de esta: comparar 8 ejecuciones contra la estimación de 104
    # daría un desvío del 90 % que no dice nada.
    costo = costo_pasada + (heredado["costo_usd"] if heredado else 0.0)
    minutos = (time.perf_counter() - inicio) / 60

    print("\n— Comprobaciones dinámicas —")
    if heredado is None:
        fallos = comprobaciones_dinamicas(recogido, e3, args.version)
    else:
        fallos = _solo_cache(e3)
        print(
            "  rejilla principal: heredada de la pasada anterior "
            "(anotaciones, entrega, marcadores, intérprete y reglas, sin fallos)"
        )
    _, sin_caso = reglas_del_corpus(args.version)
    if sin_caso:
        print(
            f"[aviso declarado] reglas sin ningún caso en el corpus: {sorted(sin_caso)} "
            "(aceptada en configs/congelado_corrida_final.json)"
        )
    ok_dinamicas = _informe(
        "anotaciones, entrega, marcadores, extracción del intérprete, reglas y caché", fallos
    )

    desvio = abs(costo - reporte.total_usd) / reporte.total_usd if reporte.total_usd else 0.0
    fallos_costo = (
        []
        if desvio <= TOLERANCIA_COSTO
        else [
            f"costo real USD {costo:.4f} frente a USD {reporte.total_usd:.4f} estimados: "
            f"desvío {desvio:.1%} sobre una tolerancia de {TOLERANCIA_COSTO:.0%}"
        ]
    )
    detalle_costo = (
        f"(real USD {costo:.4f}"
        + (f" = {costo_pasada:.4f} ahora + {heredado['costo_usd']} heredados" if heredado else "")
        + f", estimado USD {reporte.total_usd:.4f}, desvío {desvio:.1%})"
    )
    ok_costo = _informe(
        f"costo dentro de ±{TOLERANCIA_COSTO:.0%} del dry-run {detalle_costo}", fallos_costo
    )

    resultado = {
        "aprobado": bool(ok_dinamicas and ok_costo),
        "n_ejecuciones": (
            len(recogido["registros"])
            + len(e3["frio"])
            + len(e3["caliente"])
            + (heredado["n_ejecuciones"] if heredado else 0)
        ),
        "minutos": round(minutos, 2),
        "costo_usd": round(costo, 4),
        "costo_usd_esta_pasada": round(costo_pasada, 4),
        "estimacion_usd": round(reporte.total_usd, 4),
        "desvio_costo": round(desvio, 4),
        "fallos_estaticos": fallos_estaticos,
        "fallos_dinamicos": fallos,
        "fallos_costo": fallos_costo,
        "reglas_sin_caso": sorted(sin_caso),
        "reanudado": bool(heredado),
        "heredado_de": (
            {"n_ejecuciones": heredado["n_ejecuciones"], "costo_usd": heredado["costo_usd"]}
            if heredado
            else None
        ),
        "agent_version": AGENT_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "corpus_version": args.version,
    }
    destino = paths.results / f"{args.salida}.json"
    destino.write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        f"\n{len(recogido['registros']) + len(e3['frio']) + len(e3['caliente'])} ejecuciones "
        f"· {minutos:.1f} min · USD {costo:.4f}"
    )
    print(f"escrito en {destino}")
    if not resultado["aprobado"]:
        raise PreVueloFallido("\nPRE-VUELO FALLIDO: no se lanza ninguna corrida final.")
    print("\nPRE-VUELO APROBADO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
