#!/usr/bin/env python
"""Análisis por caso de E1: dónde falla y cuánto trabajo cuesta.

pass^k dice cuánto acierta el agente; no dice **en qué** falla. Este script produce
`tables/e1_casos_dificiles.md` con los casos que fallaron de forma repetida, la regla de
`evaluate_state` que los tumba y si el fallo es común a las tres configuraciones o propio de
alguna. Un caso que falla en las tres apunta al caso o al corpus; uno que falla en una sola
apunta a esa configuración.

Los mismos agregados se incorporan a `results/e1_baseline.json`, que es la fuente canónica.

Uso:

    python scripts/e1_analisis_casos.py
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from prf.agent.cte import parsear_plan
from prf.infra.paths import paths  # noqa: E402

UMBRAL_DIFICIL = 6  # c <= 6 de 8: falla al menos una de cada cuatro veces
ETIQUETAS_TIPO = {
    "busqueda": "búsqueda",
    "comparacion": "comparación",
    "recomendacion": "recomendación",
}


# Patrones de fallo reconocidos, con la frase que los describe. Se deducen de la evidencia
# de las transcripciones, no se escriben a mano por caso: así el análisis sobrevive a un
# cambio de corpus y no hay que reescribirlo cada vez.
def mecanismo_de_fallo(evidencia: dict[str, Any]) -> str:
    """Frase que explica por qué falla el caso, deducida de lo que hicieron las ejecuciones."""
    regla = evidencia["regla"]
    if regla == "must_compare":
        if evidencia["uso_compare_products"] == 0 and evidencia["texto_con_tabla"]:
            return (
                "el agente entrega la comparación redactada en prosa y nunca invoca "
                "`compare_products`; el evaluador la detecta por la llamada, no por el texto"
            )
        if evidencia["uso_compare_products"] == 0:
            return "no invoca `compare_products`: compara de memoria o no compara"
        if evidencia["comparacion_no_entregada"]:
            return (
                "ejecuta `compare_products` pero su resultado no llega al paso `respond`: "
                "la comparación no se entregó"
            )
        return "invoca `compare_products` pero no con el par exigido"
    if regla == "min_recomendaciones":
        if evidencia["respuesta_escrita_a_ciegas"]:
            return (
                "el planificador redacta la respuesta antes de ver los resultados y afirma "
                "que no encontró nada, cuando la búsqueda sí devolvió productos"
            )
        if evidencia["estado_del_interprete"]:
            # En `cte` el estado lo deriva el intérprete, no el marcador: que falte el marcador no
            # explica nada, porque ya no acredita.
            return "ningún producto del catálogo llega al paso `respond`"
        if evidencia["sin_marcador"] > 0:
            return (
                "la respuesta nombra productos pero la plantilla no emite `<<rec:ID>>`, "
                "así que no queda ninguna recomendación registrada"
            )
        return "no llega a recomendar ningún producto"
    if regla == "constraints":
        if evidencia["motivo_constraint"]:
            return f"recomienda productos que {evidencia['motivo_constraint']}"
        return "recomienda productos que violan una restricción del usuario"
    if regla == "recomendaciones_existentes":
        return "emite un identificador que no existe en el catálogo"
    if regla == "must_exclude":
        return "recomienda el producto que el caso excluye"
    return "sin patrón reconocido"


def evidencia_por_caso(directorio: Path, case_id: str, configs: list[str]) -> dict[str, Any]:
    """Reúne de las transcripciones lo que hace falta para explicar el fallo."""
    reglas: Counter = Counter()
    uso_compare = 0
    sin_marcador = 0
    del_interprete = False
    comparacion_no_entregada = False
    a_ciegas = False
    texto_con_tabla = False
    motivos: Counter = Counter()

    for archivo in directorio.glob(f"{case_id}__*.json"):
        datos = json.loads(archivo.read_text(encoding="utf-8"))
        if datos["evaluacion"]["success"]:
            continue
        final = datos["ejecucion"]["final_state"]
        uso_compare += final["herramientas_invocadas"].count("compare_products")
        if final.get("origen_estado") == "interprete":
            del_interprete = True
            if final["herramientas_invocadas"].count("compare_products") and not final.get(
                "comparaciones"
            ):
                comparacion_no_entregada = True
        for razon in datos["evaluacion"]["reasons"]:
            reglas[razon["regla"]] += 1
            if razon["regla"] == "constraints":
                mensaje = razon["mensaje"]
                if "presupuesto" in mensaje:
                    motivos["superan el presupuesto declarado"] += 1
                elif "atributo" in mensaje:
                    motivos["no cumplen el atributo pedido"] += 1
                elif "categoría" in mensaje:
                    motivos["son de otra categoría"] += 1
            if (
                razon["regla"] == "min_recomendaciones"
                and final.get("origen_estado") != "interprete"
                and "<<rec:" not in final["texto_final"]
            ):
                sin_marcador += 1
        if "|" in final["texto_final"] and final["texto_final"].count("|") > 4:
            texto_con_tabla = True

        # El caso que solo `cte` puede sufrir: el plan se escribe de una vez, así que la
        # plantilla de `respond` puede afirmar un resultado que la herramienta contradijo.
        # Se detecta por un `respond` sin ninguna variable mientras un paso de consulta se
        # ejecutó con éxito: la respuesta no depende de lo que se consultó.
        plan_texto = next(
            (t["texto"] for t in datos["ejecucion"]["transcripcion"] if t["rol"] == "planificador"),
            "",
        )
        if plan_texto:
            plan, _ = parsear_plan(plan_texto)
            if plan is not None:
                respond = [p for p in plan.pasos if p.op == "respond"]
                consultas = [
                    p
                    for p in datos["ejecucion"]["plan"]["pasos"]
                    if p["op"] != "respond" and p["estado"] == "ejecutado"
                ]
                if respond and not respond[-1].vars and consultas:
                    a_ciegas = True

    return {
        "regla": reglas.most_common(1)[0][0] if reglas else None,
        "uso_compare_products": uso_compare,
        "sin_marcador": sin_marcador,
        "estado_del_interprete": del_interprete,
        "comparacion_no_entregada": comparacion_no_entregada,
        "respuesta_escrita_a_ciegas": a_ciegas,
        "texto_con_tabla": texto_con_tabla,
        "motivo_constraint": motivos.most_common(1)[0][0] if motivos else None,
    }


def reglas_por_caso(directorio: Path) -> dict[tuple[str, str], Counter]:
    """Reglas de `evaluate_state` que fallan, por (caso, configuración)."""
    conteo: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for archivo in sorted(directorio.glob("*.json")):
        datos = json.loads(archivo.read_text(encoding="utf-8"))
        if datos["evaluacion"]["success"]:
            continue
        clave = (datos["case_id"], datos["config"])
        for razon in datos["evaluacion"]["reasons"]:
            conteo[clave][razon["regla"]] += 1
    return conteo


def casos_dificiles(
    e1: dict[str, Any], reglas: dict[tuple[str, str], Counter], directorio: Path
) -> list[dict]:
    """Casos con c ≤ UMBRAL_DIFICIL en alguna configuración."""
    configs = e1["configs"]
    tipos = {}
    for observacion in e1["observaciones"]:
        tipos[observacion["case_id"]] = observacion["tipo"]

    n = e1["resultados"][configs[0]]["n_runs"]
    filas = []
    for case_id in sorted(e1["matriz"][configs[0]]):
        cs = {c: sum(e1["matriz"][c][case_id]) for c in configs}
        if min(cs.values()) > UMBRAL_DIFICIL:
            continue
        fallan = [c for c in configs if cs[c] <= UMBRAL_DIFICIL]
        acumulado: Counter = Counter()
        for c in configs:
            acumulado.update(reglas.get((case_id, c), Counter()))
        filas.append(
            {
                "case_id": case_id,
                "tipo": tipos.get(case_id, "?"),
                "c": cs,
                "n": n,
                "regla_mas_frecuente": acumulado.most_common(1)[0][0] if acumulado else None,
                "reglas": dict(acumulado),
                "configuraciones_que_fallan": fallan,
                "falla_en_todas": len(fallan) == len(configs),
                "mecanismo": mecanismo_de_fallo(evidencia_por_caso(directorio, case_id, configs)),
            }
        )
    return filas


def trabajo_y_turnos(e1: dict[str, Any], base: str) -> dict[str, Any]:
    """Turnos y llamadas medios por configuración, y tasa de fallo por turnos en `base`."""
    por_config: dict[str, dict[str, float]] = {}
    for config in e1["configs"]:
        obs = [o for o in e1["observaciones"] if o["config"] == config]
        turnos = [o["n_turnos"] for o in obs]
        llamadas = [o["n_llamadas_herramienta"] for o in obs]
        por_config[config] = {
            "n_ejecuciones": len(obs),
            "turnos_media": round(sum(turnos) / len(turnos), 3),
            "turnos_max": max(turnos),
            "llamadas_media": round(sum(llamadas) / len(llamadas), 3),
            "llamadas_max": max(llamadas),
        }

    # Tasa de fallo según cuántos turnos necesitó la conversación. Si el fallo crece con los
    # turnos, el agente no está corrigiendo con el diálogo sino enredándose.
    por_turnos: dict[str, dict[str, Any]] = {}
    for observacion in e1["observaciones"]:
        if observacion["config"] != base:
            continue
        clave = str(observacion["n_turnos"])
        celda = por_turnos.setdefault(clave, {"n": 0, "fallos": 0})
        celda["n"] += 1
        celda["fallos"] += 1 - observacion["exito"]
    for celda in por_turnos.values():
        celda["tasa_fallo"] = round(celda["fallos"] / celda["n"], 4)

    return {
        "por_configuracion": por_config,
        "tasa_fallo_por_turnos": {"config": base, "detalle": dict(sorted(por_turnos.items()))},
    }


def tabla_markdown(filas: list[dict], trabajo: dict[str, Any], configs: list[str]) -> str:
    """La tabla de casos difíciles, ordenada por cuántas configuraciones fallan."""
    lineas = [
        "# Casos difíciles de E1",
        "",
        f"Casos de robustez con `c ≤ {UMBRAL_DIFICIL}` de {filas[0]['n'] if filas else 8} "
        "ejecuciones en al menos una configuración: fallan al menos una de cada cuatro veces.",
        "",
        "Un caso que falla en las **tres** configuraciones apunta al caso o al corpus; uno "
        "que falla en **una sola** apunta a esa configuración.",
        "",
        "| Caso | Tipo | "
        + " | ".join(f"c ({c})" for c in configs)
        + " | Regla que más falla | Falla en | Mecanismo |",
        "|---|---|" + "---:|" * len(configs) + "---|---|---|",
    ]
    for fila in filas:
        cs = " | ".join(f"{fila['c'][c]}/{fila['n']}" for c in configs)
        donde = (
            "las tres" if fila["falla_en_todas"] else ", ".join(fila["configuraciones_que_fallan"])
        )
        regla = fila["regla_mas_frecuente"] or "—"
        lineas.append(
            f"| `{fila['case_id']}` | {ETIQUETAS_TIPO.get(fila['tipo'], fila['tipo'])} | "
            f"{cs} | `{regla}` | {donde} | {fila['mecanismo']} |"
        )
    if not filas:
        lineas.append("| — | — |" + " — |" * len(configs) + " — | — | — |")

    lineas += [
        "",
        "## Trabajo por ejecución",
        "",
        "| Configuración | Turnos (media) | Turnos (máx.) | Llamadas (media) | Llamadas (máx.) |",
        "|---|---:|---:|---:|---:|",
    ]
    for config, datos in trabajo["por_configuracion"].items():
        lineas.append(
            f"| `{config}` | {datos['turnos_media']} | {datos['turnos_max']} | "
            f"{datos['llamadas_media']} | {datos['llamadas_max']} |"
        )

    detalle = trabajo["tasa_fallo_por_turnos"]
    lineas += [
        "",
        f"## Tasa de fallo según número de turnos (`{detalle['config']}`)",
        "",
        "| Turnos | Ejecuciones | Fallos | Tasa de fallo |",
        "|---:|---:|---:|---:|",
    ]
    for turnos, celda in detalle["detalle"].items():
        lineas.append(
            f"| {turnos} | {celda['n']} | {celda['fallos']} | {celda['tasa_fallo']:.1%} |"
        )
    lineas += [
        "",
        "Casi todas las ejecuciones se resuelven en un turno, y ahí se concentra el fallo. "
        "Las pocas que necesitaron más turnos acertaron todas, así que el error no aparece "
        "por enredarse en el diálogo: aparece en la primera respuesta o no aparece. El "
        "simulador de usuario apenas llega a intervenir, y eso limita lo que E1 puede decir "
        "sobre la conversación multi-turno.",
        "",
        "## Cómo se acredita el estado final",
        "",
        "La comparación se acredita por el marcador `<<cmp:ID1,ID2>>` **o** por una llamada "
        "exitosa a `compare_products`: antes se detectaba solo por la llamada, y una "
        "comparación redactada en prosa se puntuaba como fallo aunque resolviera la tarea. "
        "Los marcadores se leen de **todos** los turnos del asistente, no solo del último, "
        "porque una comparación entregada en el turno 1 sigue entregada aunque el turno 2 "
        "hable de otra cosa.",
        "",
        "En `cte` el estado no se lee del texto sino del **intérprete**: recomendados son los "
        "productos que llegan al paso `respond` y comparaciones entregadas las llamadas a "
        "`compare_products` cuyo resultado llega ahí. Los marcadores que escriba el "
        "planificador se ignoran y solo se registra su tasa de transcripción, para no medir "
        "la defensa por la fidelidad con que un modelo de un solo paso transcribe lo que el "
        "intérprete ya hizo.",
    ]
    return "\n".join(lineas)


def main(argv: list[str] | None = None) -> int:
    """Escribe la tabla de casos difíciles de E1, con qué falla en cada uno."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--resultado", default="e1_baseline", help="JSON de E1 que se analiza.")
    parser.add_argument(
        "--base",
        default="none",
        help="Resultado anterior con el que comparar, para ver qué cambió.",
    )
    args = parser.parse_args(argv)

    archivo = paths.results / f"{args.resultado}.json"
    if not archivo.is_file():
        raise SystemExit(f"falta {archivo}")
    e1 = json.loads(archivo.read_text(encoding="utf-8"))

    directorio = paths.results / "runs_e1"
    if not directorio.is_dir():
        raise SystemExit(f"falta {directorio}: las ejecuciones persistidas de E1")

    reglas = reglas_por_caso(directorio)
    filas = casos_dificiles(e1, reglas, directorio)
    trabajo = trabajo_y_turnos(e1, args.base)

    # Los agregados se incorporan al resultado canónico.
    e1.setdefault("analisis", {})["casos_dificiles"] = filas
    e1["analisis"]["trabajo_y_turnos"] = trabajo
    archivo.write_text(json.dumps(e1, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    destino = paths.tables / "e1_casos_dificiles.md"
    destino.parent.mkdir(parents=True, exist_ok=True)
    # Con salto final: un archivo de texto que no lo lleva lo arregla cualquier editor o
    # gancho, y entonces el archivo publicado deja de coincidir con el que el generador
    # produce.
    destino.write_text(
        tabla_markdown(filas, trabajo, e1["configs"]).rstrip("\n") + "\n", encoding="utf-8"
    )

    print(f"casos difíciles (c <= {UMBRAL_DIFICIL}): {len(filas)}")
    for fila in filas:
        donde = (
            "las tres" if fila["falla_en_todas"] else ",".join(fila["configuraciones_que_fallan"])
        )
        print(
            f"  {fila['case_id']} ({fila['tipo']}) "
            f"{ {c: fila['c'][c] for c in e1['configs']} } "
            f"regla={fila['regla_mas_frecuente']} falla_en={donde}"
        )
    print(f"\nescrito en {destino}")
    print(f"agregados incorporados a {archivo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
