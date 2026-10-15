#!/usr/bin/env python
"""Concordancia entre la anotación a ciegas y los otros tres criterios de E6.

Lee el CSV que devuelve quien anota —`id_anonimo`, `p1_opcion_no_cumple`, `p2_le_sirve`— y la
tabla de correspondencia que traduce el id anónimo al `run_id`, que es lo único que permite
unirlo con el evaluador, el juez y la anotación del autor.

Las reglas de lectura están fijadas **antes** de recibir los datos en
`docs/E6_REGLA_DE_INTERPRETACION.md`. Este script las aplica y dice si se cumplen; no las
decide.

No llama a la API.

Uso:
    python scripts/e6_kappa_ciego.py                       # la copia versionada
    python scripts/e6_kappa_ciego.py --respuestas otro.csv \
        --correspondencia exports/e6_ciego/correspondencia.csv
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from prf.eval.intervalos import wilson
from prf.infra import paths
from prf.infra.config import load_experiments, load_models, load_thresholds
from prf.infra.results import build_metadata, write_result

# Las columnas se leen SIEMPRE por nombre, nunca por posición: el CSV puede pasar por una hoja
# de cálculo que reordene o añada columnas.
COLUMNAS_OBLIGATORIAS = ("id_anonimo", "p1_opcion_no_cumple", "p2_le_sirve")
# La versión del instrumento con que se respondió. La añadió la 1.1; un CSV de la 1.0 no la
# trae y se lee igual, con la versión vacía.
COLUMNA_VERSION = "version_instrumento"

# La copia versionada del archivo que devolvió quien anota. El original se conserva intacto en
# `exports/`, que no se versiona; esta copia es byte a byte la misma y su huella está registrada
# en `data/annotation/e6_respuestas_recibidas.json`.
RESPUESTAS = "data/annotation/e6_respuestas_ciego.csv"

# La tabla que traduce el id anónimo al `run_id`. Se genera junto al HTML en `exports/`, que no
# se versiona, y se copia aquí porque es lo único que permite reproducir este cálculo. No rompe
# el ciegamiento: la anotación ya terminó.
CORRESPONDENCIA = "data/annotation/correspondencia.csv"

KAPPA_CONFIRMA = 0.60  # Landis y Koch: acuerdo sustancial
PROPORCION_LAXA = 0.5
INCONSISTENCIAS_TOLERADAS = 1  # 2 o más obligan a la salvedad de la regla (c)

ETIQUETAS = {
    "ciego": "anotación a ciegas (P2)",
    "autor": "anotación del autor",
    "juez": "juez LLM",
    "evaluador": "evaluador de estado",
    "p1": "anotación a ciegas (P1)",
    "constraints": "regla `constraints` del evaluador",
}


def kappa_cohen(a: list[int], b: list[int]) -> float | None:
    """Kappa de Cohen. `None` cuando no está definida, no 0.

    Si ambos anotadores usan una sola clase, el acuerdo esperado por azar es 1 y la fórmula
    divide por cero. Reportar 0 ahí diría «no hay acuerdo» cuando lo que pasa es que la métrica
    no aplica.
    """
    n = len(a)
    if n == 0:
        return None
    observado = sum(1 for x, y in zip(a, b, strict=True) if x == y) / n
    esperado = sum(
        (sum(1 for x in a if x == c) / n) * (sum(1 for y in b if y == c) / n) for c in (0, 1)
    )
    if esperado >= 1.0:
        return None
    return round((observado - esperado) / (1 - esperado), 4)


def matriz(a: list[int], b: list[int]) -> dict[str, int]:
    return {
        "ambos_si": sum(1 for x, y in zip(a, b, strict=True) if x == 1 and y == 1),
        "ambos_no": sum(1 for x, y in zip(a, b, strict=True) if x == 0 and y == 0),
        "solo_el_primero": sum(1 for x, y in zip(a, b, strict=True) if x == 1 and y == 0),
        "solo_el_segundo": sum(1 for x, y in zip(a, b, strict=True) if x == 0 and y == 1),
    }


def par(nombre_izq: str, izq: list[int], nombre_der: str, der: list[int]) -> dict[str, Any]:
    """Concordancia simple, kappa y matriz de un par de criterios."""
    if not izq:
        return {
            "par": f"{ETIQUETAS[nombre_izq]} vs {ETIQUETAS[nombre_der]}",
            "n": 0,
            "estado": "pendiente",
            "motivo": "sin casos en común",
        }
    acuerdos = sum(1 for x, y in zip(izq, der, strict=True) if x == y)
    return {
        "par": f"{ETIQUETAS[nombre_izq]} vs {ETIQUETAS[nombre_der]}",
        "n": len(izq),
        "estado": "calculado",
        "concordancia_simple": round(acuerdos / len(izq), 4),
        "kappa_cohen": kappa_cohen(izq, der),
        "matriz": matriz(izq, der),
    }


# ------------------------------------------------------------------ lectura de entradas


def _etiqueta(valor: str | None) -> int | None:
    limpio = str(valor if valor is not None else "").strip().lower()
    if not limpio:
        return None
    if limpio in ("1", "1.0", "si", "sí"):
        return 1
    if limpio in ("0", "0.0", "no"):
        return 0
    raise SystemExit(f"valor no reconocido en el CSV: {valor!r}. Usa 1 o 0.")


def leer_csv(ruta: Path) -> list[dict[str, str]]:
    """Un CSV venga como venga de una hoja de cálculo.

    Excel en macOS reexporta en Mac Roman y separado por `;`, y exigir UTF-8 con comas
    obligaría a arreglar el archivo a mano justo cuando ya está anotado. `data/annotation/
    e6_sample.csv` está hoy en ese formato, así que esto no es hipotético.
    """
    crudo = ruta.read_bytes()
    for codificacion in ("utf-8-sig", "utf-8", "mac_roman", "cp1252"):
        try:
            texto = crudo.decode(codificacion)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover
        raise SystemExit(f"no se pudo leer {ruta}")
    lineas = texto.splitlines()
    separador = ";" if lineas[0].count(";") > lineas[0].count(",") else ","
    return list(csv.DictReader(lineas, delimiter=separador))


def leer_respuestas(ruta: Path) -> list[dict[str, Any]]:
    """El CSV de quien anota, en el orden en que lo entregó.

    Todo se lee por nombre de columna. `version_instrumento` es opcional: la escribe el
    instrumento desde la versión 1.1 y un CSV de la 1.0 no la trae.
    """
    filas = leer_csv(ruta)
    faltan = set(COLUMNAS_OBLIGATORIAS) - set(filas[0] or {})
    if faltan:
        raise SystemExit(f"al CSV le faltan columnas: {', '.join(sorted(faltan))}")
    return [
        {
            "id_anonimo": f["id_anonimo"].strip(),
            "p1": _etiqueta(f["p1_opcion_no_cumple"]),
            "p2": _etiqueta(f["p2_le_sirve"]),
            "comentario": (f.get("comentario") or "").strip(),
            "version_instrumento": (f.get(COLUMNA_VERSION) or "").strip(),
        }
        for f in filas
    ]


def versiones(respuestas: list[dict[str, Any]]) -> dict[str, int]:
    """Con qué versión del instrumento se respondió cada pantalla.

    La vacía son las respuestas anteriores a la 1.1, que no la declaraban. Que aparezca más de
    una no invalida nada por sí solo, pero hay que saberlo al leer el resultado.
    """
    cuenta: dict[str, int] = {}
    for r in respuestas:
        clave = r.get("version_instrumento") or "sin declarar"
        cuenta[clave] = cuenta.get(clave, 0) + 1
    return dict(sorted(cuenta.items()))


def leer_referencias(correspondencia: Path, raiz: Path) -> dict[str, dict[str, Any]]:
    """Para cada id anónimo: qué dijeron el evaluador, el juez y el autor sobre esa ejecución."""
    muestra = {f["run_id"]: f for f in leer_csv(raiz / "data/annotation/e6_sample.csv")}
    salida: dict[str, dict[str, Any]] = {}
    for fila in leer_csv(correspondencia):
        run_id = fila["run_id"]
        base = muestra.get(run_id, {})
        transcripcion = json.loads((raiz / fila["transcript_path"]).read_text(encoding="utf-8"))
        evaluacion = transcripcion.get("evaluacion") or {}
        salida[fila["id_anonimo"]] = {
            "run_id": run_id,
            "repeticion_de": fila.get("repeticion_de") or "",
            "evaluador": _etiqueta(base.get("state_success")),
            "juez": _etiqueta(base.get("judge_success")),
            "autor": _etiqueta(base.get("human_success")),
            # La regla `constraints` es la que dice «alguna recomendación viola lo que el
            # usuario pidió»: es el hecho que P1 pregunta.
            "constraints_falla": int(
                any(r["regla"] == "constraints" for r in evaluacion.get("reasons") or [])
            ),
        }
    return salida


# ------------------------------------------------------------------------- análisis


def analizar(
    respuestas: list[dict[str, Any]], referencias: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Aplica las tres reglas de lectura y devuelve sus desenlaces con las cifras."""
    por_id = {r["id_anonimo"]: r for r in respuestas}
    desconocidos = sorted(set(por_id) - set(referencias))
    if desconocidos:
        raise SystemExit(f"ids que no están en la correspondencia: {', '.join(desconocidos[:5])}")

    # Primera respuesta de cada ejecución: las repeticiones no entran en los pares, para no
    # contar dos veces la misma opinión sobre el mismo caso.
    primeras = {
        i: r
        for i, r in por_id.items()
        if not referencias[i]["repeticion_de"] and r["p2"] is not None
    }
    ids = sorted(primeras)
    p2 = [primeras[i]["p2"] for i in ids]
    p1 = [primeras[i]["p1"] for i in ids]

    pares = []
    for clave in ("autor", "juez", "evaluador"):
        emparejables = [i for i in ids if referencias[i][clave] is not None]
        pares.append(
            par(
                "ciego",
                [primeras[i]["p2"] for i in emparejables],
                clave,
                [referencias[i][clave] for i in emparejables],
            )
        )

    # P1 contra el hecho que la regla del evaluador detecta.
    con_p1 = [i for i in ids if primeras[i]["p1"] is not None]
    validacion_p1 = par(
        "p1",
        [primeras[i]["p1"] for i in con_p1],
        "constraints",
        [referencias[i]["constraints_falla"] for i in con_p1],
    )

    # La medida directa del desacuerdo: cuando la persona VE que algo no cumple, ¿le sirve?
    vio_incumplimiento = [i for i in con_p1 if primeras[i]["p1"] == 1]
    le_sirve = [i for i in vio_incumplimiento if primeras[i]["p2"] == 1]
    ic = wilson(len(le_sirve), len(vio_incumplimiento)) if vio_incumplimiento else None
    proporcion = {
        "n_vio_incumplimiento": len(vio_incumplimiento),
        "n_aun_asi_le_sirve": len(le_sirve),
        "proporcion": round(len(le_sirve) / len(vio_incumplimiento), 4)
        if vio_incumplimiento
        else None,
        "intervalo_95": {
            "inferior": round(ic[0], 4),
            "superior": round(ic[1], 4),
            "metodo": "wilson",
            "confianza": 0.95,
        }
        if ic
        else None,
    }

    # Consistencia intra-anotador en los repetidos.
    repetidos = []
    for i, ref in referencias.items():
        original = ref["repeticion_de"]
        if not original or i not in por_id or original not in por_id:
            continue
        a, b = por_id[original], por_id[i]
        repetidos.append(
            {
                "primera": original,
                "segunda": i,
                "run_id": ref["run_id"],
                "p1": [a["p1"], b["p1"]],
                "p2": [a["p2"], b["p2"]],
                "coincide_p2": a["p2"] == b["p2"],
            }
        )
    inconsistentes = [r for r in repetidos if not r["coincide_p2"]]

    return {
        "n_respuestas": len(respuestas),
        "n_casos_unicos": len(primeras),
        "version_instrumento": versiones(respuestas),
        "pares": pares,
        "validacion_de_p1": validacion_p1,
        "le_sirve_pese_al_incumplimiento": proporcion,
        "consistencia_intra_anotador": {
            "repetidos": repetidos,
            "n_inconsistentes": len(inconsistentes),
        },
        "veredicto_de_las_reglas": veredicto(pares, proporcion, len(inconsistentes)),
        "p1_resumen": {"n": len(p1), "n_si": sum(1 for v in p1 if v == 1)},
        "p2_resumen": {"n": len(p2), "n_si": sum(1 for v in p2 if v == 1)},
    }


def veredicto(
    pares: list[dict[str, Any]], proporcion: dict[str, Any], inconsistentes: int
) -> dict[str, Any]:
    """Aplica las tres reglas fijadas antes de recibir los datos."""
    autor = next((p for p in pares if "del autor" in p["par"]), {})
    kappa = autor.get("kappa_cohen")
    a = {
        "regla": "a) kappa P2-autor >= 0,60 confirma la anotación del autor",
        "kappa": kappa,
        "umbral": KAPPA_CONFIRMA,
        "resultado": (
            "no evaluable"
            if kappa is None
            else "confirmada"
            if kappa >= KAPPA_CONFIRMA
            else "NO confirmada"
        ),
    }

    p, ic = proporcion["proporcion"], proporcion["intervalo_95"]
    if p is None:
        resultado_b = "no evaluable: ningún caso con P1 = Sí"
    elif ic and ic["inferior"] <= PROPORCION_LAXA <= ic["superior"]:
        resultado_b = "la muestra no permite decidir la dirección: el IC cruza 0,5"
    elif p > PROPORCION_LAXA:
        resultado_b = "confirmado: el criterio humano es más laxo que el evaluador"
    else:
        resultado_b = "la afirmación de la sección 5.3 SE REVISA"
    b = {
        "regla": "b) proporción de P2 = Sí entre los P1 = Sí, contra 0,5",
        "proporcion": p,
        "intervalo_95": ic,
        "resultado": resultado_b,
    }

    c = {
        "regla": "c) 2 o más inconsistencias de 4 obligan a la salvedad",
        "n_inconsistentes": inconsistentes,
        "resultado": (
            "criterio humano INESTABLE: (b) se interpreta con esa salvedad"
            if inconsistentes > INCONSISTENCIAS_TOLERADAS
            else "criterio estable en los repetidos"
        ),
    }
    return {"a": a, "b": b, "c": c}


# ---------------------------------------------------------------------------- salida


def imprimir(analisis: dict[str, Any]) -> None:
    """Muestra el análisis en la terminal, con las tres reglas al final."""
    print(
        f"\n{analisis['n_casos_unicos']} casos únicos respondidos "
        f"({analisis['n_respuestas']} pantallas, repeticiones incluidas)"
    )
    print(
        "  versión del instrumento: "
        + ", ".join(f"{v} ({n})" for v, n in analisis["version_instrumento"].items())
        + "\n"
    )
    for p in analisis["pares"]:
        if p["estado"] != "calculado":
            print(f"  {p['par']:<46} {p['motivo']}")
            continue
        k = p["kappa_cohen"]
        print(
            f"  {p['par']:<46} n={p['n']:<4} concordancia={p['concordancia_simple']:.4f} "
            f"kappa={'—' if k is None else f'{k:.4f}'}"
        )
    v = analisis["validacion_de_p1"]
    if v["estado"] == "calculado":
        k = v["kappa_cohen"]
        print(
            f"  {v['par']:<46} n={v['n']:<4} concordancia={v['concordancia_simple']:.4f} "
            f"kappa={'—' if k is None else f'{k:.4f}'}"
        )

    pr = analisis["le_sirve_pese_al_incumplimiento"]
    print()
    if pr["proporcion"] is not None:
        ic = pr["intervalo_95"]
        print(
            f"  de los {pr['n_vio_incumplimiento']} casos donde vio que algo no cumplía, "
            f"en {pr['n_aun_asi_le_sirve']} dijo que igual le sirve"
        )
        print(
            f"  proporción {pr['proporcion']:.4f}  IC 95 % "
            f"[{ic['inferior']:.4f}, {ic['superior']:.4f}] ({ic['metodo']})"
        )
    else:
        print("  ningún caso con P1 = Sí")

    cons = analisis["consistencia_intra_anotador"]
    print(
        f"\n  repetidos: {len(cons['repetidos'])}  inconsistentes en P2: {cons['n_inconsistentes']}"
    )

    print("\n  reglas fijadas antes de recibir los datos:")
    for clave in ("a", "b", "c"):
        r = analisis["veredicto_de_las_reglas"][clave]
        print(f"    {clave}) {r['resultado']}")


def main(argv: list[str] | None = None) -> int:
    """Aplica la regla de lectura a las respuestas recibidas y escribe el resultado."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--respuestas", default=RESPUESTAS, help="CSV que devolvió quien anota")
    parser.add_argument(
        "--correspondencia",
        default=CORRESPONDENCIA,
        help="Tabla que traduce el id anónimo al run_id.",
    )
    parser.add_argument(
        "--salida", default="e6_blind", help="Nombre del JSON en results/, sin extensión."
    )
    args = parser.parse_args(argv)

    respuestas_ruta, correspondencia_ruta = Path(args.respuestas), Path(args.correspondencia)
    for ruta in (respuestas_ruta, correspondencia_ruta):
        if not ruta.is_file():
            raise SystemExit(f"falta {ruta}")

    respuestas = leer_respuestas(respuestas_ruta)
    referencias = leer_referencias(correspondencia_ruta, paths.root)
    analisis = analizar(respuestas, referencias)
    imprimir(analisis)

    experimentos = load_experiments()
    umbrales = load_thresholds()
    metadata = build_metadata(
        seed=experimentos["seed_global"],
        model={"judge": load_models().role("judge").id},
        config="e6_ciego",
        corpus_version=experimentos["corpus_version"],
        api_mode="none",
        extra={
            "thresholds_version": str(umbrales["version"]),
            "politica_tag": "policy-v0.3.0",
            "regla_de_interpretacion": "docs/E6_REGLA_DE_INTERPRETACION.md",
            "respuestas": str(respuestas_ruta),
            "sin_llamadas_api": True,
        },
    )
    archivo = write_result(args.salida, analisis, metadata)
    print(f"\nescrito en {archivo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
