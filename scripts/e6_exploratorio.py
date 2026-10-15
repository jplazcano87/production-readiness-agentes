#!/usr/bin/env python
"""Lecturas EXPLORATORIAS de la anotación a ciegas de E6. No deciden nada.

La regla fijada antes de recibir los datos está en `docs/E6_REGLA_DE_INTERPRETACION.md` y la
aplica `scripts/e6_kappa_ciego.py`. Lo de aquí se le ocurrió a alguien **después** de ver los
números, así que no puede confirmar ni refutar nada: va en un archivo aparte, rotulado, para
que no se confunda con lo preinscrito. Sirve para describir dónde cayeron los desacuerdos y
para abrir preguntas a la siguiente ronda, no para cerrarlas.

Dos lecturas:

1. Las 16 ejecuciones donde el evaluador de estado reprueba y el juez aprueba —el desacuerdo
   que motivó toda la ronda— con lo que la persona contestó en cada una.
2. La tasa de `p2_le_sirve` en los casos donde el asistente nombra productos por su código,
   frente al resto. El instrumento 1.1 añadió el código a la tabla justo para que esos casos
   fueran legibles; esto mira si se comportan distinto. Con 14 casos de un lado no distingue
   el efecto del contenido de esas respuestas del efecto de la legibilidad.
3. Las ejecuciones que el autor y el juez reprueban y la persona aprueba: el otro lado del
   desacuerdo. Para cada una, qué devolvió la búsqueda dentro del presupuesto y si la tabla
   del instrumento lo mostraba, que es lo que dice si la persona tenía con qué verlo.

No llama a la API.

Uso:
    python scripts/e6_exploratorio.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from e6_anotacion.datos import (  # noqa: E402
    cargar_muestra,
    codigos_citados,
    leer_ejecucion,
    limpiar,
)
from e6_anotacion.generar import SEPARACION_MINIMA  # noqa: E402
from e6_kappa_ciego import CORRESPONDENCIA, RESPUESTAS, leer_csv, leer_respuestas  # noqa: E402
from prf.env import Catalog  # noqa: E402
from prf.eval.intervalos import wilson  # noqa: E402
from prf.infra import paths  # noqa: E402
from prf.infra.config import load_experiments, load_models  # noqa: E402
from prf.infra.results import build_metadata, write_result  # noqa: E402

ROLES_VISIBLES = ("usuario", "asistente")


def _turnos(ruta: Path) -> list[dict[str, str]]:
    """Los turnos tal como los vio quien anota."""
    ejecucion = leer_ejecucion(ruta)["ejecucion"]
    return [
        {"rol": t["rol"], "texto": limpiar(t["texto"])}
        for t in ejecucion["transcripcion"]
        if t["rol"] in ROLES_VISIBLES and limpiar(t["texto"])
    ]


def _primeras(respuestas: list[dict[str, Any]], correspondencia: list[dict[str, str]]):
    """La primera respuesta de cada ejecución, indexada por `run_id`.

    Las repeticiones se dejan fuera igual que en la regla: contarlas dos veces pesaría doble la
    misma opinión sobre el mismo caso.
    """
    por_id = {r["id_anonimo"]: r for r in respuestas}
    salida = {}
    for fila in correspondencia:
        if fila["repeticion_de"] or fila["id_anonimo"] not in por_id:
            continue
        salida[fila["run_id"]] = {**por_id[fila["id_anonimo"]], "fila": fila}
    return salida


def desacuerdos_evaluador_juez(primeras: dict[str, Any], raiz: Path) -> dict[str, Any]:
    """Qué contestó la persona en las 16 donde el evaluador reprueba y el juez aprueba."""
    muestra = leer_csv(raiz / "data/annotation/e6_sample.csv")
    filas = []
    for f in muestra:
        if not (f["state_success"] in ("0", "0.0") and f["judge_success"] in ("1", "1.0")):
            continue
        evaluacion = leer_ejecucion(raiz / f["transcript_path"]).get("evaluacion") or {}
        reglas = sorted({r["regla"] for r in evaluacion.get("reasons") or []})
        r = primeras.get(f["run_id"])
        filas.append(
            {
                "id_anonimo": r["fila"]["id_anonimo"] if r else None,
                "run_id": f["run_id"],
                "case_id": f["case_id"],
                "config": f["config"],
                "tipo": f["tipo"],
                "regla_que_falla": reglas,
                "clase": "restricciones" if reglas == ["constraints"] else "lectura del estado",
                "autor": int(f["human_success"]) if f["human_success"] else None,
                "p1_opcion_no_cumple": r["p1"] if r else None,
                "p2_le_sirve": r["p2"] if r else None,
            }
        )
    filas.sort(key=lambda x: (x["clase"], x["id_anonimo"] or ""))
    con_p2 = [f for f in filas if f["p2_le_sirve"] is not None]
    le_sirve = [f for f in con_p2 if f["p2_le_sirve"] == 1]
    vio = [f for f in con_p2 if f["p1_opcion_no_cumple"] == 1]
    return {
        "n": len(filas),
        "por_clase": {
            "restricciones": sum(1 for f in filas if f["clase"] == "restricciones"),
            "lectura del estado": sum(1 for f in filas if f["clase"] == "lectura del estado"),
        },
        "n_le_sirve": len(le_sirve),
        "n_vio_incumplimiento": len(vio),
        "ejecuciones": filas,
    }


def por_codigo_en_el_texto(primeras: dict[str, Any], raiz: Path) -> dict[str, Any]:
    """Tasa de `p2_le_sirve` según si el asistente nombra productos por su código."""
    grupos: dict[str, list[int]] = {"con_codigo": [], "sin_codigo": []}
    detalle = []
    for r in primeras.values():
        turnos = _turnos(raiz / r["fila"]["transcript_path"])
        codigos = codigos_citados(turnos)
        clave = "con_codigo" if codigos else "sin_codigo"
        if r["p2"] is not None:
            grupos[clave].append(r["p2"])
        detalle.append(
            {
                "id_anonimo": r["fila"]["id_anonimo"],
                "codigos": codigos,
                "p1_opcion_no_cumple": r["p1"],
                "p2_le_sirve": r["p2"],
            }
        )
    salida = {}
    for clave, valores in grupos.items():
        ic = wilson(sum(valores), len(valores)) if valores else None
        salida[clave] = {
            "n": len(valores),
            "n_le_sirve": sum(valores),
            "tasa": round(sum(valores) / len(valores), 4) if valores else None,
            "intervalo_95": (
                {
                    "inferior": round(ic[0], 4),
                    "superior": round(ic[1], 4),
                    "metodo": "wilson",
                    "confianza": 0.95,
                }
                if ic
                else None
            ),
        }
    salida["casos"] = sorted(detalle, key=lambda x: x["id_anonimo"])
    return salida


def _primera_frase(texto: str, tope: int = 330) -> str:
    """Una línea de lo que dijo el agente, para poder leer la tabla sin abrir ocho archivos.

    Corta en la **última** frase que quepa, no en la primera: en varias de estas respuestas la
    primera frase es el saludo y lo que importa —que no encontró nada— viene en la siguiente.
    """
    limpio = " ".join(texto.split())
    if len(limpio) <= tope:
        return limpio
    corte = limpio.rfind(". ", 0, tope)
    frase = limpio[: corte + 1] if corte > 0 else limpio[:tope]
    return frase.rstrip() + " […]"


def _busqueda_y_tabla(ruta: Path, productos_de_la_tabla: list[dict[str, Any]]) -> dict[str, Any]:
    """Qué devolvió la búsqueda dentro del presupuesto y si la tabla lo mostraba.

    El tope se lee de los argumentos con que el agente llamó a la herramienta, no del caso: lo
    que interesa es si la respuesta contradice **su propia** búsqueda.
    """
    ejecucion = leer_ejecucion(ruta)["ejecucion"]
    tope: int | None = None
    devueltos: list[dict[str, Any]] = []
    for llamada in ejecucion.get("llamadas") or []:
        argumentos = llamada.get("argumentos") or {}
        if argumentos.get("max_price") is not None:
            tope = argumentos["max_price"]
        resultado = llamada.get("resultado")
        if isinstance(resultado, list):
            devueltos += [p for p in resultado if isinstance(p, dict) and "price_clp" in p]
    dentro = [p for p in devueltos if tope is None or p["price_clp"] <= tope]
    en_la_tabla = {p["codigo"] for p in productos_de_la_tabla}
    faltan = [p["id"] for p in dentro if p["id"] not in en_la_tabla]
    return {
        "presupuesto_de_la_busqueda_clp": tope,
        "devueltos_por_la_busqueda": len(devueltos),
        "dentro_del_presupuesto": [
            {"codigo": p["id"], "nombre": p["name"], "precio_clp": p["price_clp"]} for p in dentro
        ],
        "la_tabla_los_mostraba": not faltan if dentro else None,
        "no_estaban_en_la_tabla": faltan,
        "recomendaciones_finales": (ejecucion.get("final_state") or {}).get("recomendaciones")
        or [],
    }


def solo_la_persona_aprueba(primeras: dict[str, Any], raiz: Path, catalogo: Any) -> dict[str, Any]:
    """Las ejecuciones que el autor y el juez reprueban y la persona da por útiles.

    Es la celda que hace negativa la kappa del par con el autor: 8 de 8 de los «no» del autor
    caen aquí. Mirar qué tienen en común es descriptivo y nada más.
    """
    muestra = {f["run_id"]: f for f in leer_csv(raiz / "data/annotation/e6_sample.csv")}
    casos, _ = cargar_muestra(
        raiz / "data/annotation/e6_sample_ciego.csv",
        raiz,
        load_experiments()["seed_global"],
        catalogo,
        separacion=SEPARACION_MINIMA,
    )
    por_id = {c.id_anonimo: c for c in casos}

    filas = []
    for run_id, r in primeras.items():
        f = muestra[run_id]
        if not (f["human_success"] == "0" and f["judge_success"] == "0" and r["p2"] == 1):
            continue
        ruta = raiz / r["fila"]["transcript_path"]
        datos = leer_ejecucion(ruta)
        evaluacion = datos.get("evaluacion") or {}
        respuestas = [
            limpiar(t["texto"])
            for t in datos["ejecucion"]["transcripcion"]
            if t["rol"] == "asistente"
        ]
        caso = por_id[r["fila"]["id_anonimo"]]
        filas.append(
            {
                "id_anonimo": caso.id_anonimo,
                "run_id": run_id,
                "case_id": f["case_id"],
                "config": f["config"],
                "tipo": f["tipo"],
                "regla_que_falla": sorted({x["regla"] for x in evaluacion.get("reasons") or []}),
                "p1_opcion_no_cumple": r["p1"],
                "p2_le_sirve": r["p2"],
                "lo_que_dice_el_agente": _primera_frase(respuestas[0] if respuestas else ""),
                **_busqueda_y_tabla(ruta, caso.productos),
            }
        )
    filas.sort(key=lambda x: x["id_anonimo"])
    casos_distintos = sorted({f["case_id"] for f in filas})
    configs = sorted({f["config"] for f in filas})
    return {
        "n": len(filas),
        "case_id_distintos": casos_distintos,
        "configuraciones": configs,
        "todas_con_la_tabla_completa": all(f["la_tabla_los_mostraba"] is True for f in filas),
        "ejecuciones": filas,
    }


def imprimir(salida: dict[str, Any]) -> None:
    """Muestra las lecturas exploratorias, con el aviso de que no deciden nada."""
    d = salida["desacuerdo_evaluador_juez"]
    print("\nEXPLORATORIO — no decide nada. La regla preinscrita se aplica en e6_blind.json\n")
    print(
        f"  las {d['n']} donde el evaluador reprueba y el juez aprueba "
        f"({d['por_clase']['restricciones']} por restricciones, "
        f"{d['por_clase']['lectura del estado']} por lectura del estado)"
    )
    print(f"  {'id':<5} {'regla':<20} {'config':<12} {'P1':<4} {'P2':<4} autor")
    for f in d["ejecuciones"]:
        print(
            f"  {f['id_anonimo'] or '—':<5} {','.join(f['regla_que_falla']):<20} "
            f"{f['config']:<12} {str(f['p1_opcion_no_cumple']):<4} "
            f"{str(f['p2_le_sirve']):<4} {f['autor']}"
        )
    print(
        f"\n  de las {d['n']}: en {d['n_le_sirve']} dijo que le sirve, "
        f"en {d['n_vio_incumplimiento']} vio un incumplimiento"
    )

    o = salida["solo_la_persona_aprueba"]
    print(
        f"\n  las {o['n']} que el autor y el juez reprueban y la persona aprueba: "
        f"case_id {', '.join(o['case_id_distintos'])} · config {', '.join(o['configuraciones'])}"
    )
    print(f"  {'id':<5} {'run_id':<28} {'regla':<22} {'P1':<4} {'P2':<4} tabla completa")
    for f in o["ejecuciones"]:
        print(
            f"  {f['id_anonimo']:<5} {f['run_id']:<28} {','.join(f['regla_que_falla']):<22} "
            f"{f['p1_opcion_no_cumple']:<4} {f['p2_le_sirve']:<4} "
            f"{'sí' if f['la_tabla_los_mostraba'] else 'no'} "
            f"({len(f['dentro_del_presupuesto'])} dentro del presupuesto)"
        )

    c = salida["codigo_en_el_texto"]
    print("\n  tasa de «le sirve» según si el asistente nombra productos por su código")
    for clave in ("con_codigo", "sin_codigo"):
        g = c[clave]
        ic = g["intervalo_95"]
        print(
            f"    {clave:<12} n={g['n']:<3} le sirve={g['n_le_sirve']:<3} "
            f"tasa={g['tasa']:.4f}  IC 95 % [{ic['inferior']:.4f}, {ic['superior']:.4f}]"
        )


def main(argv: list[str] | None = None) -> int:
    """Escribe las lecturas exploratorias, en un archivo aparte del resultado preinscrito."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--respuestas", default=RESPUESTAS, help="CSV que devolvió quien anota.")
    parser.add_argument(
        "--correspondencia",
        default=CORRESPONDENCIA,
        help="Tabla que traduce el id anónimo al run_id.",
    )
    parser.add_argument(
        "--salida",
        default="e6_blind_exploratorio",
        help="Nombre del JSON en results/, sin extensión.",
    )
    args = parser.parse_args(argv)

    raiz = paths.root
    respuestas = leer_respuestas(Path(args.respuestas))
    correspondencia = leer_csv(Path(args.correspondencia))
    primeras = _primeras(respuestas, correspondencia)

    salida = {
        "aviso": (
            "EXPLORATORIO. Estas lecturas se decidieron después de ver los datos y no forman "
            "parte de docs/E6_REGLA_DE_INTERPRETACION.md. No confirman ni refutan ninguna "
            "afirmación del informe. El resultado que decide está en results/e6_blind.json."
        ),
        "desacuerdo_evaluador_juez": desacuerdos_evaluador_juez(primeras, raiz),
        "solo_la_persona_aprueba": solo_la_persona_aprueba(
            primeras, raiz, Catalog.from_corpus(load_experiments()["corpus_version"])
        ),
        "codigo_en_el_texto": por_codigo_en_el_texto(primeras, raiz),
    }
    imprimir(salida)

    experimentos = load_experiments()
    metadata = build_metadata(
        seed=experimentos["seed_global"],
        model={"judge": load_models().role("judge").id},
        config="e6_ciego_exploratorio",
        corpus_version=experimentos["corpus_version"],
        api_mode="none",
        extra={
            "preinscrito": False,
            "respuestas": args.respuestas,
            "sin_llamadas_api": True,
            "regla_preinscrita": "docs/E6_REGLA_DE_INTERPRETACION.md (se aplica en e6_blind)",
        },
    )
    archivo = write_result(args.salida, salida, metadata)
    print(f"\nescrito en {archivo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
