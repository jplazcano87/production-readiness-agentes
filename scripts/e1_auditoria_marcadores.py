#!/usr/bin/env python
"""Ejecuciones de E1 donde el evaluador no ve lo que el texto sí dice.

Nace de un hallazgo puntual: `ROB-REC-013__cte__1` figura con cero recomendaciones y su
respuesta lista tres productos del catálogo con sus marcadores. En `cte` el estado lo deriva el
intérprete de lo que llegó al paso `respond` y los marcadores del planificador se ignoran,
así que una respuesta puede nombrar productos sin que el estado los registre.

Esto busca ese desajuste en las corridas **finales** de E1: ejecuciones que el evaluador reprueba
por `min_recomendaciones` o por `must_compare` y cuyo texto visible, en cambio, menciona
productos del catálogo. Reporta cuántas hay y qué pasaría con pass^k si se corrigieran.

**No corrige nada.** Solo mide. No llama a la API.

Uso:
    python scripts/e1_auditoria_marcadores.py
    python scripts/e1_auditoria_marcadores.py --entrada e1_prompt_only
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from prf.env import Catalog
from prf.eval.passk import passk
from prf.infra import paths
from prf.infra.config import load_experiments

# Las dos reglas que afirman una ausencia: «no recomendó» y «no comparó». Son las únicas donde
# un desajuste entre el estado y el texto produce un falso negativo.
REGLAS_DE_AUSENCIA = ("min_recomendaciones", "must_compare")
ID_PRODUCTO = re.compile(r"\bP\d{4}\b")
MARCADOR = re.compile(r"<<(?:rec|cmp):([^>]*)>>")


def productos_en_el_texto(texto: str, catalogo: Catalog) -> dict[str, list[str]]:
    """Qué productos del catálogo nombra el texto, por id y por nombre.

    Los nombres se buscan completos: un nombre de catálogo tiene varias palabras y no aparece
    por casualidad. Buscar por palabras sueltas daría coincidencias con cualquier frase.
    """
    por_id = sorted({p for p in ID_PRODUCTO.findall(texto) if catalogo.existe(p)})
    por_nombre = sorted(
        {p.id for p in catalogo.products if p.name and p.name.lower() in texto.lower()}
    )
    return {"por_id": por_id, "por_nombre": por_nombre}


def cumple_restricciones(pid: str, target: dict[str, Any], catalogo: Catalog) -> bool:
    """Si ese producto satisface lo que el caso exigía."""
    producto = catalogo.get(pid)
    if producto is None:
        return False
    c = target.get("constraints") or {}
    if c.get("categoria") and producto.category != c["categoria"]:
        return False
    if c.get("presupuesto_max_clp") and producto.price_clp > c["presupuesto_max_clp"]:
        return False
    if c.get("presupuesto_min_clp") and producto.price_clp < c["presupuesto_min_clp"]:
        return False
    for atributo, exigido in (c.get("atributos") or {}).items():
        valor = (producto.attributes or {}).get(atributo)
        if valor is None:
            return False
        if isinstance(exigido, dict):
            if "min" in exigido and valor < exigido["min"]:
                return False
            if "max" in exigido and valor > exigido["max"]:
                return False
        elif valor != exigido:
            return False
    return True


def clasificar(
    hallazgo: dict[str, Any], target: dict[str, Any], catalogo: Catalog
) -> dict[str, Any]:
    """Distingue el falso negativo del acierto del evaluador.

    Que el texto nombre productos no basta: en `ROB-BUS-007` el agente dice «no encontré nada»
    y menciona dos que **superan el presupuesto** para sugerir ampliarlo. Ahí el evaluador
    acierta: no recomendó nada válido. El candidato a falso negativo es otro: el texto trae lo
    que la regla exige —una comparación con su marcador, o un producto que sí cumple— y el
    estado no lo registró.
    """
    texto_marcadores = hallazgo["marcadores_en_el_texto"]
    if "must_compare" in hallazgo["reglas_de_ausencia"]:
        exigidas = {frozenset(par) for par in target.get("must_compare") or []}
        en_texto = {frozenset(m.split(",")) for m in texto_marcadores if "," in m}
        faltan = exigidas - en_texto
        return {
            "veredicto": "candidato_a_falso_negativo" if not faltan else "evaluador_acierta",
            "motivo": (
                "el texto trae el marcador de la comparación exigida y el estado no la registró"
                if not faltan
                else "la comparación exigida no está en el texto"
            ),
        }

    validos = [
        p for p in hallazgo["productos_en_el_texto"] if cumple_restricciones(p, target, catalogo)
    ]
    return {
        "veredicto": "candidato_a_falso_negativo" if validos else "evaluador_acierta",
        "productos_que_cumplen": validos,
        "motivo": (
            f"el texto nombra {len(validos)} producto(s) que cumplen y el estado no registró "
            "ninguna recomendación"
            if validos
            else "los productos del texto NO cumplen las restricciones: el agente los menciona "
            "para explicar por qué no sirven"
        ),
    }


def auditar_ejecucion(ruta: Path, catalogo: Catalog) -> dict[str, Any] | None:
    """Devuelve el desajuste si lo hay, o `None`."""
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    evaluacion = datos.get("evaluacion") or {}
    if evaluacion.get("success"):
        return None
    reglas = [r["regla"] for r in evaluacion.get("reasons") or []]
    de_ausencia = [r for r in reglas if r in REGLAS_DE_AUSENCIA]
    if not de_ausencia:
        return None

    ejecucion = datos["ejecucion"]
    final = ejecucion.get("final_state") or {}
    texto = final.get("texto_final") or ""
    mencionados = productos_en_el_texto(texto, catalogo)
    citados = sorted(set(mencionados["por_id"]) | set(mencionados["por_nombre"]))
    if not citados:
        return None

    hallazgo = {
        "run_id": datos["run_id"],
        "case_id": datos["case_id"],
        "config": datos["config"],
        "tipo": datos["tipo"],
        "reglas_que_fallan": reglas,
        "reglas_de_ausencia": de_ausencia,
        "recomendaciones_en_el_estado": final.get("recomendaciones") or [],
        "comparaciones_en_el_estado": final.get("comparaciones") or [],
        "origen_estado": final.get("origen_estado"),
        "productos_en_el_texto": citados,
        "marcadores_en_el_texto": sorted(set(MARCADOR.findall(texto))),
        "motivo_del_evaluador": [
            r["mensaje"] for r in evaluacion.get("reasons") or [] if r["regla"] in de_ausencia
        ],
    }
    hallazgo["clasificacion"] = clasificar(hallazgo, datos.get("target_state") or {}, catalogo)
    return hallazgo


def efecto_en_passk(
    e1: dict[str, Any], desajustes: list[dict[str, Any]], k_values: list[int]
) -> dict[str, Any]:
    """Qué pasaría con pass^k si cada desajuste se contara como éxito.

    Es una **cota superior** del efecto: supone que los tres desajustes son falsos negativos,
    que es justo lo que esta auditoría no decide. Sirve para saber si la pregunta importa.
    """
    salida: dict[str, Any] = {}
    por_config: dict[str, set[str]] = defaultdict(set)
    for d in desajustes:
        if d["clasificacion"]["veredicto"] == "candidato_a_falso_negativo":
            por_config[d["config"]].add(d["run_id"])

    for config, matriz in e1.get("matriz", {}).items():
        afectados = por_config.get(config, set())
        if not afectados:
            continue
        corregida = {}
        casos_tocados = []
        for case_id, runs in matriz.items():
            nuevos = list(runs)
            cambio = False
            for i in range(len(nuevos)):
                if f"{case_id}__{config}__{i}" in afectados and nuevos[i] == 0:
                    nuevos[i] = 1
                    cambio = True
            corregida[case_id] = nuevos
            if cambio:
                casos_tocados.append(
                    {"case_id": case_id, "antes": sum(runs), "despues": sum(nuevos)}
                )
        salida[config] = {
            "casos_afectados": casos_tocados,
            "pass_k": {
                f"pass^{k}": {
                    "actual": round(_pass_k_global(matriz, k), 6),
                    "si_se_corrigiera": round(_pass_k_global(corregida, k), 6),
                }
                for k in k_values
            },
        }
    return salida


def _pass_k_global(matriz: dict[str, list[int]], k: int) -> float:
    valores = [passk(len(runs), sum(runs), k) for runs in matriz.values()]
    return sum(valores) / len(valores) if valores else 0.0


def main(argv: list[str] | None = None) -> int:
    """Audita las ejecuciones donde el estado y el texto visible discrepan, y lo escribe."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--entrada", action="append", default=None, help="JSON de E1 cuyas ejecuciones se auditan."
    )
    parser.add_argument(
        "--transcripciones",
        default="results/runs_e1",
        help="Directorio con las transcripciones por ejecución.",
    )
    args = parser.parse_args(argv)

    entradas = args.entrada or ["e1_baseline", "e1_prompt_only"]
    catalogo = Catalog.from_corpus(load_experiments()["corpus_version"])
    directorio = paths.root / args.transcripciones

    informe: dict[str, Any] = {"corridas": {}, "total_desajustes": 0}
    for nombre in entradas:
        ruta = paths.results / f"{nombre}.json"
        if not ruta.is_file():
            print(f"  {nombre}: no existe todavía, se omite")
            continue
        e1 = json.loads(ruta.read_text(encoding="utf-8"))
        configs = e1.get("configs", [])
        desajustes = []
        revisadas = faltantes = 0
        for observacion in e1.get("observaciones", []):
            archivo = directorio / f"{observacion['run_id']}.json"
            if not archivo.is_file():
                faltantes += 1
                continue
            revisadas += 1
            hallazgo = auditar_ejecucion(archivo, catalogo)
            if hallazgo:
                desajustes.append(hallazgo)
        informe["corridas"][nombre] = {
            "configs": configs,
            "agent_version": e1["metadata"].get("agent_version"),
            "cobertura": {"revisadas": revisadas, "sin_transcripcion": faltantes},
            "desajustes": desajustes,
            "efecto_en_passk": efecto_en_passk(e1, desajustes, e1.get("k_values", [1, 2, 4, 8])),
        }
        informe["total_desajustes"] += len(desajustes)

    imprimir(informe)
    return 0


def imprimir(informe: dict[str, Any]) -> None:
    """Muestra la auditoría en la terminal, con la cobertura declarada."""
    for nombre, corrida in informe["corridas"].items():
        cob = corrida["cobertura"]
        print(f"\n=== {nombre} (agente {corrida['agent_version']}) ===")
        print(
            f"  ejecuciones revisadas: {cob['revisadas']}"
            + (
                f"  sin transcripción: {cob['sin_transcripcion']}"
                if cob["sin_transcripcion"]
                else ""
            )
        )
        desajustes = corrida["desajustes"]
        if not desajustes:
            print("  sin desajustes: ninguna ejecución reprobada por ausencia menciona productos")
            continue
        por_config: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for d in desajustes:
            por_config[d["config"]].append(d)
        print(f"  DESAJUSTES: {len(desajustes)}")
        for config, lista in sorted(por_config.items()):
            casos = sorted({d["case_id"] for d in lista})
            print(
                f"    {config:<12} {len(lista):>3} ejecuciones · {len(casos)} casos: "
                + ", ".join(casos[:6])
                + ("…" if len(casos) > 6 else "")
            )
        candidatos = [
            d for d in desajustes if d["clasificacion"]["veredicto"] == "candidato_a_falso_negativo"
        ]
        aciertos = [d for d in desajustes if d not in candidatos]
        print(
            f"    candidatos a FALSO NEGATIVO: {len(candidatos)}"
            f"  ·  el evaluador acierta en: {len(aciertos)}"
        )
        print("\n  detalle:")
        for d in desajustes[:14]:
            marca = "FALSO NEG?" if d in candidatos else "ok evaluador"
            print(
                f"    {d['run_id']:<28} {','.join(d['reglas_de_ausencia']):<21} {marca:<13}"
                f" {d['clasificacion']['motivo'][:62]}"
            )
        if len(desajustes) > 14:
            print(f"    … y {len(desajustes) - 14} más")

        efecto = corrida["efecto_en_passk"]
        if efecto:
            print("\n  efecto en pass^k si los desajustes fueran falsos negativos (cota superior):")
            for config, datos in sorted(efecto.items()):
                for k, v in datos["pass_k"].items():
                    if v["actual"] != v["si_se_corrigiera"]:
                        print(
                            f"    {config:<12} {k:<8} {v['actual']:.4f} -> "
                            f"{v['si_se_corrigiera']:.4f}"
                        )
                for c in datos["casos_afectados"]:
                    print(f"      caso {c['case_id']}: {c['antes']}/8 -> {c['despues']}/8 aciertos")
    print(f"\ntotal de desajustes: {informe['total_desajustes']}")


if __name__ == "__main__":
    raise SystemExit(main())
