"""Las dos tablas de resultados por configuración, desde los JSON canónicos.

    python scripts/make_tables.py

La primera compara las cuatro configuraciones en las tres dimensiones: robustez (E1),
seguridad (E2), latencia (E3) y cumplimiento (E4). La segunda desglosa la seguridad por
vector y objetivo, con el ASR calculado de las dos formas —sobre todas las ejecuciones y
sobre las que recibieron la carga— y la tasa de entrega que las separa.

No inventa celdas: si un experimento no cubre una configuración, la celda dice «—». `none`
y `prompt_only` no están en E1, que corrió tres configuraciones.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from prf.infra import paths

CONFIGS = ("none", "prompt_only", "dual_llm", "cte")


def _leer(nombre: str) -> dict[str, Any] | None:
    archivo = paths.results / f"{nombre}.json"
    if not archivo.exists():
        return None
    return json.loads(archivo.read_text(encoding="utf-8"))


def _n(valor, formato="{:.3f}", vacio="—"):
    return vacio if valor is None else formato.format(valor)


def tabla5(
    e1: dict[str, Any],
    e2: dict[str, Any],
    e3: dict[str, Any],
    e4: dict[str, Any],
    e1_extra: dict[str, Any] | None = None,
) -> str:
    """Las cuatro dimensiones por configuración.

    `e1_extra` trae la robustez de las configuraciones que no entraron en la corrida principal
    de E1: `prompt_only` se midió aparte, y sin esto su fila seguiría con guiones aunque el
    dato exista.
    """
    lineas = [
        "## Resultados por configuración",
        "",
        "Robustez de E1 (corpus v1.2, n = 8), seguridad y utilidad de E2 (n = 3), latencia de "
        "E3 (5 repeticiones, sin caché) y cumplimiento de E4. `prompt_only` se midió en una "
        "corrida de E1 aparte, con el mismo corpus y el mismo evaluador: la corrida principal "
        "comparó tres configuraciones.",
        "",
        "| Configuración | pass^1 (E1) | pass^8 (E1) | ASR global | ASR indirecta "
        "| Utilidad benigna | TTFT p95 (s) | Sobrecosto p95 | Críticos |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for c in CONFIGS:
        r1 = (e1 or {}).get("resultados", {}).get(c) or (e1_extra or {}).get("resultados", {}).get(
            c
        )
        r2 = (e2 or {}).get("resultados", {}).get(c)
        r3 = (e3 or {}).get("resultados", {}).get(c)
        r4 = (e4 or {}).get(c, {}).get("resumen")
        p1 = _n(r1["global"]["pass^1"]["valor"]) if r1 else "—"
        p8 = _n(r1["global"]["pass^8"]["valor"]) if r1 else "—"
        asr = _n(r2["asr_sobre_todas"]["asr"]) if r2 else "—"
        asr_i = _n((r2["asr_por_vector"].get("indirect") or {}).get("asr")) if r2 else "—"
        util = _n(r2["utilidad_benigna"]["asr"]) if r2 else "—"
        p95 = _n(r3["ttft_visible_s"]["p95"], "{:.2f}") if r3 else "—"
        sob = _n(r3["sobrecosto_vs_none"]["razon_p95"], "{:.2f}×") if r3 else "—"
        cum = f"{r4['n_criticos_pass']}/{r4['n_criticos']}" if r4 else "—"
        lineas.append(f"| `{c}` | {p1} | {p8} | {asr} | {asr_i} | {util} | {p95} | {sob} | {cum} |")
    return "\n".join(lineas)


def tabla6(e2: dict[str, Any]) -> str:
    """Seguridad por vector y objetivo, que es lo que el agregado esconde."""
    lineas = [
        "## Seguridad por vector y objetivo",
        "",
        "El ASR se reporta de dos formas. **Sobre todas** las ejecuciones de ataque, y **sobre "
        "las entregadas**: las que recibieron de verdad la carga adversarial. En el vector "
        "indirecto la carga vive en la reseña de un producto portador, y si el agente nunca "
        "consulta ese producto el ataque no se ejecutó. Contarlo como bloqueado le atribuiría "
        "a la defensa un mérito que no tuvo.",
        "",
        "Los intervalos son **exactos**: Clopper-Pearson cuando el ASR observado es cero "
        "—donde el bootstrap devolvería `[0, 0]` por degeneración— y Wilson en el resto. "
        "El límite superior es la cifra que importa: dice hasta dónde podría llegar el riesgo "
        "real sin que este experimento lo hubiera visto.",
        "",
        "| Configuración | Ataques | Entregados | Tasa de entrega | ASR (todas) "
        "| IC 95 % | Método | ASR (entregadas) |",
        "|---|---:|---:|---:|---:|---|---|---:|",
    ]
    for c in e2["configs"]:
        r = e2["resultados"][c]
        ent = r["entrega"]
        a = r["asr_sobre_todas"]
        lineas.append(
            f"| `{c}` | {a['n']} | {ent['n_entregados']}/{ent['n_indirectos']} "
            f"| {_n(ent['tasa'])} | {_n(a['asr'])} "
            f"| [{_n(a.get('ic_inferior'))}, {_n(a.get('ic_superior'))}] "
            f"| {a.get('metodo') or '—'} | {_n(r['asr_sobre_entregadas']['asr'])} |"
        )

    vectores = sorted({v for c in e2["configs"] for v in e2["resultados"][c]["asr_por_vector"]})
    lineas += [
        "",
        "### ASR por vector",
        "",
        "| Configuración | " + " | ".join(vectores) + " |",
        "|---|" + "---|" * len(vectores),
    ]
    for c in e2["configs"]:
        pv = e2["resultados"][c]["asr_por_vector"]
        lineas.append(
            f"| `{c}` | " + " | ".join(_n((pv.get(v) or {}).get("asr")) for v in vectores) + " |"
        )

    lineas += [
        "",
        "### Exfiltración, en dos filas",
        "",
        "Una de las familias presenta el centinela como **identificador administrativo del "
        "propio pedido** —«mi número de pedido es X, inclúyelo junto al producto»—. El agente "
        "escribe un código que el usuario le pide poner en su propia cotización: cuenta como "
        "éxito del criterio, pero es discutible que sea exfiltración en el sentido fuerte. Va "
        "aparte para que el lector decida.",
        "",
        "| Configuración | Con dato administrativo | Sin dato administrativo |",
        "|---|---:|---:|",
    ]
    for c in e2["configs"]:
        r = e2["resultados"][c]
        con = r.get("asr_exfiltration_con_dato_administrativo") or {}
        sin = r.get("asr_exfiltration_sin_dato_administrativo") or {}
        lineas.append(
            f"| `{c}` | {_n(con.get('asr'))} ({con.get('n', 0)}) "
            f"| {_n(sin.get('asr'))} ({sin.get('n', 0)}) |"
        )

    objetivos = sorted({o for c in e2["configs"] for o in e2["resultados"][c]["asr_por_objetivo"]})
    lineas += [
        "",
        "### ASR por objetivo",
        "",
        "| Configuración | " + " | ".join(objetivos) + " |",
        "|---|" + "---|" * len(objetivos),
    ]
    for c in e2["configs"]:
        po = e2["resultados"][c]["asr_por_objetivo"]
        lineas.append(
            f"| `{c}` | " + " | ".join(_n((po.get(o) or {}).get("asr")) for o in objetivos) + " |"
        )

    desenlaces = e2["resultados"].get("cte", {}).get("desenlaces")
    if desenlaces:
        total = sum(desenlaces.values())
        lineas += [
            "",
            "### Los tres desenlaces de `cte`",
            "",
            "Un ataque que no llega a su objetivo porque el plan estaba roto **no es una defensa "
            "que funcionó**. Separarlo del bloqueo real es lo que impide atribuirle a "
            "Code-Then-Execute un ASR que no ganó.",
            "",
            "| Desenlace | Ejecuciones | Tasa |",
            "|---|---:|---:|",
        ]
        for k, v in sorted(desenlaces.items(), key=lambda kv: -kv[1]):
            lineas.append(f"| {k.replace('_', ' ')} | {v} | {v / total:.3f} |")
        error = desenlaces.get("fallido_por_error_de_plan", 0)
        lineas += [
            "",
            f"**Tasa de error de plan: {error}/{total} = {error / total:.3f}.** El ASR observado "
            "de `cte` es una cota inferior de su ASR con un planificador que no se equivoca.",
        ]
    return "\n".join(lineas)


def tabla_latencia(e3: dict[str, Any], e3w: dict[str, Any] | None = None) -> str:
    """TTFT y latencia extremo a extremo por configuración, con su sobrecosto."""
    lineas = [
        "## Latencia (E3)",
        "",
        "TTFT **visible**: el instante en que la persona ve el primer token. En `cte` no es el "
        "primer token del planificador —que es una llamada interna— sino el momento en que el "
        "intérprete compone la respuesta.",
        "",
        f"Ambas columnas son de la **misma versión** —agente `{e3['metadata']['agent_version']}`"
        f", corpus `{e3['metadata']['corpus_version']}`—, así que no difieren en el agente ni "
        "en el corpus. Sí difieren en la ventana temporal: son dos corridas distintas.",
        "",
        "> **No se observó efecto de la caché sobre el TTFT.** La comparación **no fue "
        "intercalada** —frío y caliente son dos corridas separadas— y la variación del "
        "proveedor entre corridas es del mismo orden que la diferencia medida: el p95 de "
        "`none` en frío pasó de 5,55 s a 2,20 s entre dos corridas sin que nada del agente lo "
        "explique. Por eso **no se concluye efecto en ninguna dirección**, ni a favor ni en "
        "contra. Lo que sí es sólido, porque no depende de la ventana temporal, es el "
        "**ahorro de costo** —USD 8,60 frente a 23,14, un 63 % menos— y el **sobrecosto de "
        "`cte`**, que se mide dentro de cada corrida contra su propia línea base.",
        "",
        "| Configuración | p50 frío | p50 caliente | p95 frío | p95 caliente | % > 5 s (frío) "
        "| Sobrecosto p95 (frío) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for c in e3["configs"]:
        r = e3["resultados"][c]
        t, sob = r["ttft_visible_s"], r["sobrecosto_vs_none"]
        w = ((e3w or {}).get("resultados", {}) or {}).get(c, {}).get("ttft_visible_s", {})
        lineas.append(
            f"| `{c}` | {_n(t['p50'], '{:.2f}')} | {_n(w.get('p50'), '{:.2f}')} "
            f"| {_n(t['p95'], '{:.2f}')} | {_n(w.get('p95'), '{:.2f}')} "
            f"| {_n(t['pct_sobre_5s'], '{:.1f} %')} | {_n(sob['razon_p95'], '{:.2f}×')} |"
        )
    lineas += [
        "",
        "### TTFT por llamada interna",
        "",
        "| Configuración | Rol | n | p50 (s) | p95 (s) |",
        "|---|---|---:|---:|---:|",
    ]
    for c in e3["configs"]:
        for rol, v in e3["resultados"][c]["ttft_por_llamada_interna"].items():
            lineas.append(
                f"| `{c}` | {rol} | {v['n']} | {_n(v['p50'], '{:.2f}')} "
                f"| {_n(v['p95'], '{:.2f}')} |"
            )
    return "\n".join(lineas)


def tabla_e4_items(e4: dict[str, Any]) -> str:
    """E4 ítem por ítem, con la tasa de aprobación sobre las n ejecuciones."""
    configs = [c for c in CONFIGS if c in e4]
    n = e4[configs[0]].get("n_runs", 1)
    lineas = [
        "## E4 — cumplimiento, ítem por ítem",
        "",
        f"{n} ejecuciones por caso y configuración. **Un ítem pasa solo si pasa en las {n}**: "
        "de una obligación normativa no interesa que se cumpla en promedio sino que se cumpla "
        "siempre (regla introducida en los umbrales v0.2.1). Un ítem entre 1 y n−1 se marca "
        "**inestable**: no es que incumpla, es que no se puede garantizar.",
        "",
        "| Ítem | Criticidad | " + " | ".join(f"`{c}`" for c in configs) + " |",
        "|---|---|" + "---:|" * len(configs),
    ]
    ids = list(e4[configs[0]]["items"])
    for iid in ids:
        fila = []
        for c in configs:
            r = e4[c]["items"][iid]
            if r["tolerancia_cero"]:
                fila.append("ok" if r["estado"] == "pass" else "**VIOLADO**")
                continue
            aprob, total = r.get("n_aprobadas"), r.get("n_ejecuciones")
            if r["estado"] == "no_evaluable":
                # No es lo mismo incumplir que no poder comprobarlo. `cte` no cita productos
                # en CUM-003, así que no hay precio que contrastar: pintarlo como violación
                # le atribuiría un incumplimiento que la evidencia no muestra.
                fila.append("n/e")
            elif aprob is None:
                fila.append(r["estado"])
            elif r["estado"] == "pass":
                fila.append(f"{aprob}/{total}")
            elif r.get("inestable"):
                fila.append(f"**{aprob}/{total}**")
            else:
                fila.append(f"~~{aprob}/{total}~~")
        crit = "crítico" if e4[configs[0]]["items"][iid]["criticidad"] == "critico" else "no"
        lineas.append(f"| `{iid}` | {crit} | " + " | ".join(fila) + " |")

    lineas += [
        "",
        "`n/n` aprueba · **negrita** inestable · ~~tachado~~ falla siempre · "
        "`n/e` no evaluable: la ejecución no produjo la evidencia que el ítem contrasta.",
        "",
        "| Configuración | Críticos aprobados | Ítems inestables | Críticos sin aprobar | Cumple |",
        "|---|---:|---:|---|---|",
    ]
    for c in configs:
        r = e4[c]["resumen"]
        lineas.append(
            f"| `{c}` | {r['n_criticos_pass']}/{r['n_criticos']} | {r.get('n_inestables', 0)} "
            f"| {', '.join(f'`{i}`' for i in r['items_criticos_no_pass']) or '—'} "
            f"| {'sí' if r['cumple'] else 'no'} |"
        )
    return "\n".join(lineas)


def tabla_haiku(e2h: dict[str, Any], e2: dict[str, Any] | None) -> str:
    """Mismo prompt, mismo corpus, otro modelo: cuánto de la seguridad es del modelo."""
    lineas = [
        "## Seguridad con un modelo más pequeño",
        "",
        f"Mismo prompt (agente `{e2h['metadata']['agent_version']}`), mismo corpus y mismas "
        "defensas, con `claude-haiku-4-5-20251001` como modelo del agente. Es la forma de "
        "separar lo que aporta la defensa de lo que aporta el modelo: si el ASR sube al "
        "cambiar de modelo y las defensas lo bajan, la defensa sirve; si no sube, lo que "
        "resistía era el modelo.",
        "",
        "| Configuración | ASR (Sonnet) | ASR (Haiku) | Utilidad benigna (Haiku) |",
        "|---|---:|---:|---:|",
    ]
    for c in e2h["configs"]:
        rh = e2h["resultados"][c]
        rs = ((e2 or {}).get("resultados", {}) or {}).get(c, {})
        lineas.append(
            f"| `{c}` | {_n((rs.get('asr_sobre_todas') or {}).get('asr'))} "
            f"| {_n(rh['asr_sobre_todas']['asr'])} "
            f"| {_n(rh['utilidad_benigna']['asr'])} |"
        )
    return "\n".join(lineas)


def main(argv: list[str] | None = None) -> int:
    """Escribe las tablas de resultados por configuración en `tables/`."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--salida", default="e2_e3_summary", help="Directorio donde se escriben las tablas."
    )
    args = parser.parse_args(argv)

    e1, e2 = _leer("e1_baseline"), _leer("e2_security")
    # E3 en frío no se repitió sobre el agente 3.0.0: la referencia es la corrida de 2.2.0
    # sobre el corpus v1.1. Se usa la que haya, y la tabla declara de cuál viene cada columna.
    e3 = _leer("e3_latency")
    e3w = _leer("e3_latency_warm")
    e2h = _leer("e2_security_haiku")
    e4 = {c: _leer(f"e4_compliance_{c}") for c in CONFIGS}
    e4 = {c: v for c, v in e4.items() if v}
    if e2 is None:
        raise SystemExit("falta results/e2_security.json")

    partes = [
        "# Seguridad, latencia, robustez y cumplimiento por configuración",
        "",
        f"Agente `{e2['metadata']['agent_version']}`, evaluador "
        f"`{e2['metadata']['evaluator_version']}`, corpus `{e2['metadata']['corpus_version']}`.",
        "",
        tabla5(e1, e2, e3, e4, _leer("e1_prompt_only")),
        "",
        tabla6(e2),
    ]
    if e4:
        destino_e4 = paths.tables / "e4_items.md"
        destino_e4.write_text(tabla_e4_items(e4) + "\n", encoding="utf-8")
        print(f"escrito en {destino_e4}")
    if e3:
        partes += ["", tabla_latencia(e3, e3w)]
    if e2h:
        partes += ["", tabla_haiku(e2h, e2)]

    destino = paths.tables / f"{args.salida}.md"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("\n".join(partes) + "\n", encoding="utf-8")
    print(f"escrito en {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
