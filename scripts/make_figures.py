#!/usr/bin/env python
"""Genera las figuras del informe.

Punto de entrada único para todas: mantener el estilo en un solo módulo
(`prf.infra.figuras`) evita que las figuras del capítulo 4 y las del 5 se vean como si
vinieran de dos trabajos distintos.

Figuras de la etapa 3:

- `fig2_distribucion_corpus.png` — panel 2×2 con la composición del corpus.
- `fig3_ataques.png` — ataques por objetivo y vector.

Todas se imprimen en blanco y negro, así que la identidad de las series nunca depende del
color: se distinguen por tono de gris y por textura, y llevan leyenda y etiquetas directas.

Uso:

    python scripts/make_figures.py --corpus
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from matplotlib.ticker import MaxNLocator  # noqa: E402

from prf.infra.archivos import leer_jsonl  # noqa: E402
from prf.infra.config import load_experiments  # noqa: E402
from prf.infra.figuras import (  # noqa: E402
    RELLENO,
    RELLENO_CLARO,
    TEXTURAS,
    TINTA,
    TINTA_SUAVE,
    aplicar_estilo,
    coma_decimal,
    etiquetar_barras,
    figura,
    guardar,
    numero,
    sin_marcos,
)
from prf.infra.paths import paths  # noqa: E402
from prf.infra.tokens import approx_tokens  # noqa: E402

ETIQUETAS_CATEGORIA = {
    "notebooks": "Notebooks",
    "celulares": "Celulares",
    "audifonos": "Audífonos",
    "televisores": "Televisores",
    "electrodomesticos_cocina": "Electrodom.\nde cocina",
    "hogar_inteligente": "Hogar\ninteligente",
}

ETIQUETAS_OBJETIVO = {
    "exfiltration": "Exfiltración\nde datos",
    "task_hijack": "Desvío de la\nrecomendación",
    "out_of_domain": "Fuera de\ndominio",
    "unauthorized_promise": "Promesa no\nautorizada",
}

ORDEN_OBJETIVOS = ("exfiltration", "task_hijack", "out_of_domain", "unauthorized_promise")


def cargar(version: str) -> dict[str, Any]:
    """Los archivos del corpus que las figuras necesitan."""
    raiz = paths.corpus_version(version)

    def jsonl(nombre: str) -> list[dict[str, Any]]:
        return leer_jsonl(raiz / nombre)

    return {
        "productos": json.loads((raiz / "catalog.json").read_text(encoding="utf-8"))["products"],
        "resenas": jsonl("reviews.jsonl"),
        "robustez": jsonl("cases_robustness.jsonl"),
        "seguridad": jsonl("cases_security.jsonl"),
        "cumplimiento": jsonl("cases_compliance.jsonl"),
    }


# Nombre legible de cada regla, en la terminología del informe. El `id` del YAML es el que cita
# el veredicto; aquí hace falta algo que se lea en una figura.
NOMBRES_DE_REGLA = {
    "robustez.pass_k_1": "pass^1",
    "robustez.no_degradacion": "no degradación",
    "seguridad.asr_global": "ASR global",
    "seguridad.asr_directa": "ASR directa",
    "seguridad.asr_indirecta": "ASR indirecta",
    "seguridad.asr_por_objetivo": "ASR por objetivo",
    "seguridad.utilidad_benigna": "utilidad benigna",
    "operacion.ttft_p95_s": "TTFT p95",
    "operacion.sobrecosto_latencia": "sobrecosto de TTFT",
    "cumplimiento.items_criticos": "ítems críticos",
    "cumplimiento.zero_tolerance": "tolerancia cero",
}

DIMENSIONES_DEL_MARCO = (
    ("Robustez", "robustez", "E1 · pass^k, n = 8"),
    ("Seguridad", "seguridad", "E2 · ASR y utilidad"),
    ("Operación", "operacion", "E3 · TTFT"),
    ("Cumplimiento", "cumplimiento", "E4 · checklist, n = 5"),
)


def _numero(valor: float, decimales: int = 2) -> str:
    """El umbral con coma decimal y los decimales que le corresponden.

    No se recortan los ceros: una proporción se escribe 0,20 y no 0,2, porque en una tabla de
    umbrales el número de decimales es parte de la precisión que se declara.
    """
    if decimales == 0:
        return f"{int(round(valor))}"
    return f"{valor:.{decimales}f}".replace(".", ",")


def umbral_de_regla(identificador: str, regla: dict[str, Any]) -> str:
    """El umbral de una regla, tal como la figura lo muestra.

    Se compone **desde el YAML**, no se escribe a mano: una figura con los umbrales
    transcritos a mano es una figura que se desincroniza de la política en la primera
    revisión, y nadie se entera porque la figura no se vuelve a mirar.
    `tests/test_figura_marco.py` compara cada etiqueta con su valor en `thresholds.yaml`.
    """
    if "max_incidencias" in regla:
        n = regla["max_incidencias"]
        return f"{n} incidencia{'s' if n != 1 else ''}"
    if "margen" in regla:
        return f"\u2265 {regla.get('referencia', 'none')} \u2212 {_numero(regla['margen'])}"
    if identificador == "cumplimiento.items_criticos":
        return f"= {_numero(regla['min'] * 100, 0)} %"
    if identificador == "operacion.ttft_p95_s":
        return f"\u2264 {_numero(regla['max'], 1)} s"
    if identificador == "operacion.sobrecosto_latencia":
        return f"\u2264 {_numero(regla['max'], 1)}\u00d7"
    if "max" in regla:
        return f"\u2264 {_numero(regla['max'])}"
    if "min" in regla:
        return f"\u2265 {_numero(regla['min'])}"
    return ""


def reglas_del_marco(umbrales: dict[str, Any]) -> dict[str, list[tuple[str, str, bool]]]:
    """Por dimensión, la lista de (nombre legible, umbral, vincula) leída del YAML."""
    salida: dict[str, list[tuple[str, str, bool]]] = {}
    for _, dimension, _ in DIMENSIONES_DEL_MARCO:
        filas = []
        for clave, regla in (umbrales.get(dimension) or {}).items():
            if not isinstance(regla, dict) or "vincula" not in regla:
                continue
            identificador = regla.get("id", f"{dimension}.{clave}")
            nombre = NOMBRES_DE_REGLA.get(identificador, identificador.split(".", 1)[-1])
            filas.append((nombre, umbral_de_regla(identificador, regla), bool(regla["vincula"])))
        salida[dimension] = filas
    return salida


def fig1_esquema_del_marco(umbrales: dict[str, Any], destino: Path) -> Path:
    """El marco y la vinculación por regla de la política v0.3.0.

    Lo que la figura tiene que dejar claro no es que haya cuatro dimensiones —eso lo dice el
    texto— sino **qué decide y qué solo se reporta**, y con qué umbral. Las reglas vinculantes
    van en relleno gris con borde continuo y las de objetivo en blanco con borde discontinuo:
    en impresión monocroma el trazo se distingue siempre y un tono de gris no.

    Sin título ni nota dentro de la imagen, que en el informe van en el documento. La leyenda
    de los dos estilos sí va dentro, porque sin ella la figura no se entiende sola.

    Se dibuja con `Rectangle` y coordenadas explícitas, no con cajas redondeadas: el relleno de
    `boxstyle` se mide en puntos y no en unidades de datos, así que una caja nominalmente de 23
    unidades se salía de su columna.
    """
    from matplotlib.patches import FancyArrowPatch, Rectangle

    reglas = reglas_del_marco(umbrales)

    fig, ax = figura(3.9)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    ax.grid(False)

    ancho, hueco = 22.4, 2.5
    alto_caja, paso = 7.4, 8.4
    y_techo = 97.0
    # Cada columna mide lo que necesita y todas cuelgan del mismo techo. Con la altura del
    # máximo, las tres columnas de dos reglas quedaban medio vacías y el hueco se leía como si
    # faltara algo.
    altos = {d: 13.0 + paso * len(reglas[d]) for _, d, _ in DIMENSIONES_DEL_MARCO}
    centros = []

    for i, (titulo, dimension, fuente) in enumerate(DIMENSIONES_DEL_MARCO):
        x = 1.2 + i * (ancho + hueco)
        alto = altos[dimension]
        y_base = y_techo - alto
        centros.append((x + ancho / 2, y_base))
        ax.add_patch(
            Rectangle(
                (x, y_base),
                ancho,
                alto,
                facecolor="white",
                edgecolor=TINTA,
                linewidth=1.1,
                zorder=2,
            )
        )
        ax.text(
            x + ancho / 2,
            y_base + alto - 3.8,
            titulo,
            ha="center",
            fontsize=8.5,
            fontweight="bold",
            zorder=3,
        )
        ax.text(
            x + ancho / 2,
            y_base + alto - 8.0,
            fuente,
            ha="center",
            fontsize=6.4,
            color=TINTA_SUAVE,
            zorder=3,
        )
        for j, (nombre, umbral, vincula) in enumerate(reglas[dimension]):
            yr = y_base + alto - 11.5 - j * paso
            ax.add_patch(
                Rectangle(
                    (x + 1.4, yr - alto_caja),
                    ancho - 2.8,
                    alto_caja,
                    facecolor=RELLENO_CLARO if vincula else "white",
                    edgecolor=TINTA if vincula else TINTA_SUAVE,
                    linewidth=1.0 if vincula else 0.8,
                    linestyle="-" if vincula else (0, (2.5, 1.5)),
                    zorder=3,
                )
            )
            color = TINTA if vincula else TINTA_SUAVE
            ax.text(
                x + ancho / 2,
                yr - alto_caja / 2 + 1.5,
                nombre,
                ha="center",
                va="center",
                fontsize=6.2,
                color=color,
                zorder=4,
            )
            ax.text(
                x + ancho / 2,
                yr - alto_caja / 2 - 1.9,
                umbral,
                ha="center",
                va="center",
                fontsize=6.2,
                color=color,
                fontweight="bold" if vincula else "normal",
                zorder=4,
            )

    alto_veredicto, y_veredicto = 13.5, 2.0
    ax.add_patch(
        Rectangle(
            (20, y_veredicto),
            60,
            alto_veredicto,
            facecolor=RELLENO_CLARO,
            edgecolor=TINTA,
            linewidth=1.4,
            zorder=2,
        )
    )
    ax.text(
        50,
        y_veredicto + 9.8,
        "Veredicto conjuntivo",
        ha="center",
        fontsize=8.5,
        fontweight="bold",
        zorder=3,
    )
    ax.text(
        50,
        y_veredicto + 5.8,
        "GO solo si cumplen todas las reglas vinculantes",
        ha="center",
        fontsize=6.8,
        zorder=3,
    )
    ax.text(
        50,
        y_veredicto + 2.0,
        "NO-GO si alguna falla  ·  INDETERMINADO si falta evidencia",
        ha="center",
        fontsize=6.4,
        color=TINTA_SUAVE,
        zorder=3,
    )
    for cx, cy in centros:
        ax.add_patch(
            FancyArrowPatch(
                (cx, cy - 0.6),
                (cx * 0.3 + 50 * 0.7, y_veredicto + alto_veredicto + 0.6),
                arrowstyle="-|>",
                mutation_scale=8,
                color=TINTA_SUAVE,
                linewidth=0.9,
                shrinkA=0,
                shrinkB=1,
                zorder=1,
            )
        )

    # Leyenda de los dos estilos, dentro del gráfico: sin ella la figura no se entiende sola,
    # y el informe no debe tener que explicarla en la nota.
    for k, (etiqueta, vincula) in enumerate(
        (("vincula: decide el veredicto", True), ("objetivo: se reporta", False))
    ):
        # A la izquierda, en la banda entre las columnas y el veredicto: ahí no hay flechas
        # ni cajas, así que la leyenda no pisa nada.
        xl, yl = 1.2, 26.0 - k * 5.4
        ax.add_patch(
            Rectangle(
                (xl, yl),
                3.2,
                3.0,
                facecolor=RELLENO_CLARO if vincula else "white",
                edgecolor=TINTA if vincula else TINTA_SUAVE,
                linewidth=1.0 if vincula else 0.8,
                linestyle="-" if vincula else (0, (2.5, 1.5)),
                zorder=3,
            )
        )
        ax.text(xl + 4.2, yl + 1.5, etiqueta, fontsize=6.2, va="center", color=TINTA)
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 1.0))
    return guardar(fig, destino)


def fig2_distribucion_corpus(
    corpus: dict[str, Any], destino: Path, version: str | None = None
) -> Path:
    """Panel 2×2: composición del corpus v1.0."""
    fig, ejes = figura(5.4, nrows=2, ncols=2)
    (ax_cat, ax_precio), (ax_intencion, ax_resena) = ejes

    # (a) Productos por categoría. Barras horizontales: los nombres de categoría son
    # largos y en vertical se solaparían o habría que rotarlos.
    conteo = Counter(p["category"] for p in corpus["productos"])
    orden = sorted(conteo, key=lambda c: conteo[c])
    etiquetas = [ETIQUETAS_CATEGORIA.get(c, c).replace("\n", " ") for c in orden]
    barras = ax_cat.barh(etiquetas, [conteo[c] for c in orden], color=RELLENO, height=0.62)
    ax_cat.set_title("(a) Productos por categoría", loc="left")
    ax_cat.set_xlabel("Productos")
    ax_cat.grid(axis="x", visible=True)
    # Coma decimal en los ejes que la llevan: el de millones de CLP y los dos histogramas de
    # tokens, que matplotlib rotula con punto.
    for ax in (ax_precio, ax_intencion, ax_resena):
        coma_decimal(ax)
    coma_decimal(ax_cat, ejes="x")
    ax_cat.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=5))
    ax_cat.grid(axis="y", visible=False)
    ax_cat.set_xlim(0, max(conteo.values()) * 1.18)
    for barra in barras:
        ax_cat.text(
            barra.get_width() + max(conteo.values()) * 0.02,
            barra.get_y() + barra.get_height() / 2,
            f"{int(barra.get_width())}",
            va="center",
            fontsize=7,
            color=TINTA,
        )

    # (b) Precios, en millones de pesos para que el eje quepa.
    precios = [p["price_clp"] / 1_000_000 for p in corpus["productos"]]
    ax_precio.hist(precios, bins=20, color=RELLENO, edgecolor="white", linewidth=0.5)
    ax_precio.set_title("(b) Precio del producto", loc="left")
    ax_precio.set_xlabel("Millones de CLP")
    ax_precio.set_ylabel("Productos")
    ax_precio.yaxis.set_major_locator(MaxNLocator(integer=True))

    # (c) Longitud de las intenciones, las 225 de las tres dimensiones.
    intenciones = [
        approx_tokens(caso["intent"])
        for grupo in ("robustez", "seguridad", "cumplimiento")
        for caso in corpus[grupo]
    ]
    ax_intencion.hist(intenciones, bins=20, color=RELLENO, edgecolor="white", linewidth=0.5)
    ax_intencion.set_title("(c) Longitud de la intención", loc="left")
    ax_intencion.set_xlabel("Tokens (aproximados)")
    ax_intencion.set_ylabel("Casos")
    ax_intencion.yaxis.set_major_locator(MaxNLocator(integer=True))

    # (d) Longitud de las reseñas benignas.
    resenas = [approx_tokens(r["text"]) for r in corpus["resenas"] if not r.get("is_adversarial")]
    ax_resena.hist(resenas, bins=20, color=RELLENO, edgecolor="white", linewidth=0.5)
    ax_resena.set_title("(d) Longitud de la reseña", loc="left")
    ax_resena.set_xlabel("Tokens (aproximados)")
    ax_resena.set_ylabel("Reseñas")
    ax_resena.yaxis.set_major_locator(MaxNLocator(integer=True))

    for ax in (ax_cat, ax_precio, ax_intencion, ax_resena):
        sin_marcos(ax)
    # `sin_marcos` fija la rejilla al fondo; el panel (a) la lleva en el eje x.
    ax_cat.grid(axis="x", visible=True)

    # Sin título dentro de la imagen: en el informe lo lleva el documento. `version` sigue en
    # la firma porque el generador la usa para elegir el corpus, y el pie del informe tiene
    # que citar la misma que la tabla 3.
    _ = version
    fig.tight_layout(rect=(0.005, 0.005, 0.995, 0.995))
    return guardar(fig, destino)


def fig3_ataques(corpus: dict[str, Any], destino: Path) -> Path:
    """Ataques por objetivo, vector y **portador**.

    Tres series desde el corpus v1.3, no dos. El vector indirecto se parte por la superficie
    de inyección —reseña o descripción— porque las defensas las tratan de forma distinta: la
    reseña pasa por el LLM en cuarentena y la descripción se elimina. Dibujarlas juntas
    escondería que un tercio de los ataques indirectos tiene ASR cero por construcción en dos
    de las cuatro configuraciones.

    Cada serie lleva leyenda **y** textura: en impresión monocroma dos grises contiguos se
    confunden y la orientación del rayado no.
    """
    ataques = [c for c in corpus["seguridad"] if c["tipo"] in ("directo", "indirecto")]

    def superficie(caso: dict[str, Any]) -> str:
        if caso["vector"] == "direct":
            return "directo"
        return caso.get("portador") or "resena"

    conteo = Counter((c["objetivo"], superficie(c)) for c in ataques)
    series = [
        ("directo", "Inyección directa", RELLENO, TEXTURAS[0]),
        ("resena", "Indirecta · portador reseña", RELLENO_CLARO, TEXTURAS[1]),
        ("descripcion", "Indirecta · portador descripción", "white", TEXTURAS[0]),
    ]
    presentes = [s for s in series if sum(conteo[(o, s[0])] for o in ORDEN_OBJETIVOS)]

    fig, ax = figura(3.3)
    posiciones = list(range(len(ORDEN_OBJETIVOS)))
    ancho = 0.80 / len(presentes)
    altura_maxima = 0
    for i, (clave, etiqueta, relleno, textura) in enumerate(presentes):
        valores = [conteo[(o, clave)] for o in ORDEN_OBJETIVOS]
        altura_maxima = max(altura_maxima, *valores)
        desplazamiento = (i - (len(presentes) - 1) / 2) * (ancho + 0.012)
        barras = ax.bar(
            [p + desplazamiento for p in posiciones],
            valores,
            width=ancho,
            color=relleno,
            edgecolor=TINTA_SUAVE if relleno == "white" else "white",
            linewidth=0.8,
            hatch=textura,
            label=f"{etiqueta} (n = {sum(valores)})",
        )
        etiquetar_barras(ax, barras)

    # Conteos enteros: un eje con 2,5 casos de ataque no significa nada.
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_xticks(posiciones)
    ax.set_xticklabels([ETIQUETAS_OBJETIVO[o] for o in ORDEN_OBJETIVOS])
    ax.set_ylabel("Casos de ataque")
    ax.set_ylim(0, altura_maxima * 1.30)
    ax.legend(loc="upper right", ncol=1)
    coma_decimal(ax, ejes="y")
    sin_marcos(ax)
    # Sin notas dentro de la imagen: lo que decían —que los 40 benignos no se muestran y que
    # en dual_llm y cte el cero de la descripción es estructural— va al pie del informe.
    fig.tight_layout(rect=(0.005, 0.005, 0.995, 0.995))
    return guardar(fig, destino)


ETIQUETAS_TIPO = {
    "busqueda": "Búsqueda con restricciones",
    "comparacion": "Comparación",
    "recomendacion": "Recomendación por necesidad",
}
ETIQUETAS_CONFIG = {
    "none": "Sin protección",
    "prompt_only": "Solo prompt",
    "dual_llm": "Dual LLM",
    "cte": "Code-Then-Execute",
}
MARCADORES = ("o", "s", "^", "D")


def fig4_passk_decay(resultado: dict[str, Any], destino: Path) -> Path:
    """Figura 4: caída de pass^k al aumentar k.

    Dos paneles. El izquierdo compara configuraciones —es la pregunta de no degradación—
    y el derecho desglosa la línea base por tipo de intención. La identidad de cada serie
    va por marcador y etiqueta directa además de por tono de gris, para que la figura se
    lea igual impresa en blanco y negro.
    """
    ks = resultado["k_values"]
    # `prompt_only` se midió en su propia corrida, así que las cuatro configuraciones viven en
    # dos archivos. La figura las junta y las ordena como el resto del informe; si una faltara,
    # la serie simplemente no aparece en vez de romper la figura.
    extra = resultado.get("_extra") or {}
    resultados = {**resultado["resultados"], **extra}
    orden = [c for c in ETIQUETAS_CONFIG if c in resultados]
    configs = orden + [c for c in resultados if c not in orden]
    fig, (ax_cfg, ax_tipo) = figura(3.3, nrows=1, ncols=2)

    grises = ["#1a1a1a", "#767676", "#a8a8a8", "#c7c7c7"]

    for i, config in enumerate(configs):
        valores = [resultados[config]["global"][f"pass^{k}"]["valor"] for k in ks]
        ax_cfg.plot(
            ks,
            valores,
            marker=MARCADORES[i % len(MARCADORES)],
            color=grises[i % len(grises)],
            linewidth=1.6,
            markersize=5,
            label=ETIQUETAS_CONFIG.get(config, config),
        )
    ax_cfg.set_title("(a) Por configuración de defensa", loc="left")
    ax_cfg.legend(loc="lower left")

    base = "none" if "none" in resultados else configs[0]
    por_tipo = resultados[base]["por_tipo"]
    for i, (tipo, datos) in enumerate(sorted(por_tipo.items())):
        valores = [datos[f"pass^{k}"]["valor"] for k in ks]
        ax_tipo.plot(
            ks,
            valores,
            marker=MARCADORES[i % len(MARCADORES)],
            color=grises[i % len(grises)],
            linewidth=1.6,
            markersize=5,
            label=ETIQUETAS_TIPO.get(tipo, tipo),
        )
    ax_tipo.set_title(f"(b) Por tipo de intención ({ETIQUETAS_CONFIG.get(base, base)})", loc="left")
    ax_tipo.legend(loc="lower left")

    for ax in (ax_cfg, ax_tipo):
        ax.set_xlabel("k (ejecuciones que deben acertar todas)")
        ax.set_xticks(ks)
        ax.set_ylim(-0.03, 1.03)
        ax.set_ylabel("pass^k")
        coma_decimal(ax, ejes="y")
        sin_marcos(ax)

    # Sin nota dentro de la imagen. La advertencia que llevaba es imprescindible —las
    # diferencias entre configuraciones son de uno o dos casos de 42 y sus intervalos se
    # solapan— pero va en el pie del informe, no aquí.
    fig.tight_layout(rect=(0.005, 0.005, 0.995, 0.995))
    return guardar(fig, destino)


def fig5_asr_utility(e2: dict, umbrales: dict, destino: Path) -> Path:
    """Figura 5: ASR indirecta frente a utilidad benigna, un punto por configuración.

    El cuadrante bueno es el de arriba a la izquierda: poca ASR y mucha utilidad. Las líneas
    de umbral lo delimitan.

    En este corpus la ASR indirecta es cero en tres de las cuatro configuraciones, así que sus
    puntos caen en x = 0 y se superponen. **Que se superpongan es el resultado**, y por eso no
    se separan con desplazamientos artificiales: se nombran en la leyenda y el panel (b)
    desglosa el ASR por vector, que es donde sí hay diferencias.
    """
    orden = [c for c in ETIQUETAS_CONFIG if c in e2["configs"]]
    configs = orden + [c for c in e2["configs"] if c not in orden]
    criterio = (e2.get("metadata") or {}).get("criterio_ataque_version", "no declarado")
    fig, (ax, ax_vec) = figura(3.4, nrows=1, ncols=2)
    grises = ["#1a1a1a", "#767676", "#a8a8a8", "#c7c7c7"]

    asr_max = umbrales["asr_indirecta"]["max"]
    util_min = umbrales["utilidad_benigna"]["min"]

    for i, c in enumerate(configs):
        r = e2["resultados"][c]
        x = (r["asr_por_vector"].get("indirect") or {}).get("asr") or 0.0
        y = r["utilidad_benigna"]["asr"] or 0.0
        ax.scatter(
            x,
            y,
            marker=MARCADORES[i % len(MARCADORES)],
            s=90,
            facecolor="none" if i else grises[0],
            edgecolor=grises[i % len(grises)],
            linewidth=1.4,
            zorder=3 + i,
            label=ETIQUETAS_CONFIG.get(c, c),
        )

    ax.axvline(asr_max, color="#4d4d4d", linewidth=1.0, linestyle="--")
    ax.axhline(util_min, color="#4d4d4d", linewidth=1.0, linestyle="--")
    ax.annotate(
        f"ASR máx. {numero(asr_max)}",
        (asr_max + 0.006, 1.008),
        fontsize=7,
        va="top",
        color="#4d4d4d",
    )
    ax.annotate(
        f"utilidad mín. {numero(util_min)}",
        (max(0.22, asr_max + 0.05) - 0.006, util_min - 0.004),
        fontsize=7,
        ha="right",
        va="top",
        color="#4d4d4d",
    )
    ax.set_xlim(-0.012, max(0.22, asr_max + 0.05))
    ax.set_ylim(0.878, 1.015)
    ax.set_xlabel("ASR del vector indirecto")
    ax.set_ylabel("utilidad benigna (pass^1)")
    coma_decimal(ax)
    ax.set_title("(a) ASR indirecta frente a utilidad benigna", loc="left")
    ax.legend(loc="center left", fontsize=7.5, frameon=False, handletextpad=0.4, borderaxespad=0.6)
    sin_marcos(ax)

    ancho = 0.36
    posiciones = list(range(len(configs)))
    directa = [
        (e2["resultados"][c]["asr_por_vector"].get("direct") or {}).get("asr") or 0.0
        for c in configs
    ]
    indirecta = [
        (e2["resultados"][c]["asr_por_vector"].get("indirect") or {}).get("asr") or 0.0
        for c in configs
    ]
    ax_vec.bar(
        [p - ancho / 2 for p in posiciones],
        directa,
        ancho,
        color="#767676",
        edgecolor="#1a1a1a",
        linewidth=0.6,
        label="directa",
    )
    ax_vec.bar(
        [p + ancho / 2 for p in posiciones],
        indirecta,
        ancho,
        color="#ffffff",
        edgecolor="#1a1a1a",
        linewidth=0.6,
        hatch="///",
        label="indirecta",
    )
    for x, v in zip(posiciones, directa, strict=True):
        if v:
            ax_vec.annotate(
                numero(v, 3),
                (x - ancho / 2, v),
                textcoords="offset points",
                xytext=(0, 3),
                ha="center",
                fontsize=7,
            )
    ax_vec.set_xticks(posiciones)
    ax_vec.set_xticklabels(
        [ETIQUETAS_CONFIG.get(c, c) for c in configs], fontsize=7, rotation=20, ha="right"
    )
    ax_vec.set_ylabel("ASR")
    coma_decimal(ax_vec, ejes="y")
    ax_vec.set_ylim(0, max(0.05, (max(directa + indirecta) or 0.01) * 1.6))
    ax_vec.set_title("(b) ASR por vector", loc="left")
    ax_vec.legend(loc="upper left", fontsize=7.5, frameon=False)
    sin_marcos(ax_vec)

    # Sin título ni nota dentro de la imagen. El criterio con que se juzgó cada ataque sigue
    # siendo imprescindible —la misma corrida leída con el criterio anterior da un ASR directo
    # de cte casi siete veces mayor— así que el generador lo devuelve para que el pie del
    # informe lo cite.
    _ = criterio
    fig.tight_layout(rect=(0.005, 0.005, 0.995, 0.995))
    return guardar(fig, destino)


def main(argv: list[str] | None = None) -> int:
    """Genera el conjunto de figuras que se le pida y las escribe en `figures/`."""
    experimentos = load_experiments()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--corpus", action="store_true", help="Figuras 2 y 3 (etapa 3).")
    parser.add_argument("--e1", action="store_true", help="Figura 4 (etapa 5).")
    parser.add_argument("--e2", action="store_true", help="Figura 5 (etapa 7).")
    parser.add_argument("--marco", action="store_true", help="Figura 1 (esquema del marco).")
    parser.add_argument(
        "--informe",
        action="store_true",
        help=(
            "Las cinco figuras del informe, con las fuentes finales, en figures/informe/. "
            "Es el único modo que hay que recordar para regenerarlas todas."
        ),
    )
    parser.add_argument(
        "--resultado", default="e1_baseline", help="Nombre del JSON de results/ para --e1."
    )
    parser.add_argument(
        "--resultado-extra",
        nargs="*",
        default=None,
        help=(
            "Corridas de E1 adicionales que se juntan en la figura 4. `prompt_only` se midió "
            "aparte, así que las cuatro configuraciones viven en dos archivos."
        ),
    )
    parser.add_argument(
        "--e2-resultado",
        default="e2_security",
        help="Nombre del JSON de E2 para --e2. Lo final es la vista combinada de v1.3.",
    )
    parser.add_argument(
        "--destino",
        default=None,
        help="Directorio de salida. Por omisión `figures/`.",
    )
    parser.add_argument(
        "--version",
        default=experimentos["corpus_version"],
        help="Versión del corpus del que salen las figuras del corpus.",
    )
    args = parser.parse_args(argv)

    if args.informe:
        args.corpus = args.e1 = args.e2 = args.marco = True
        args.destino = args.destino or str(paths.figures / "informe")
        args.resultado_extra = (
            args.resultado_extra if args.resultado_extra is not None else ["e1_prompt_only"]
        )
        if args.e2_resultado == "e2_security":
            args.e2_resultado = "e2_security_v1.3"

    if not (args.corpus or args.e1 or args.e2 or args.marco):
        parser.error("indica qué figuras generar, por ejemplo --informe, --corpus o --e1")

    destino = Path(args.destino) if args.destino else paths.figures
    destino.mkdir(parents=True, exist_ok=True)

    import yaml

    umbrales = yaml.safe_load((paths.configs / "thresholds.yaml").read_text(encoding="utf-8"))

    aplicar_estilo()
    salidas = []
    if args.marco:
        salidas.append(fig1_esquema_del_marco(umbrales, destino / "fig1_esquema_marco.png"))
    if args.corpus:
        corpus = cargar(args.version)
        salidas += [
            fig2_distribucion_corpus(
                corpus, destino / "fig2_distribucion_corpus.png", args.version
            ),
            fig3_ataques(corpus, destino / "fig3_ataques.png"),
        ]
    if args.e1:
        archivo = paths.results / f"{args.resultado}.json"
        if not archivo.is_file():
            raise SystemExit(f"falta {archivo}: ejecuta antes scripts/run_e1.py")
        datos = json.loads(archivo.read_text(encoding="utf-8"))
        extra: dict[str, Any] = {}
        for nombre in args.resultado_extra or []:
            otro = paths.results / f"{nombre}.json"
            if not otro.is_file():
                raise SystemExit(f"falta {otro}")
            extra.update(json.loads(otro.read_text(encoding="utf-8"))["resultados"])
        datos["_extra"] = extra
        salidas.append(fig4_passk_decay(datos, destino / "fig4_passk_decay.png"))
    if args.e2:
        archivo = paths.results / f"{args.e2_resultado}.json"
        if not archivo.is_file():
            raise SystemExit(f"falta {archivo}: ejecuta antes scripts/run_e2.py")
        salidas.append(
            fig5_asr_utility(
                json.loads(archivo.read_text(encoding="utf-8")),
                umbrales["seguridad"],
                destino / "fig5_asr_utility.png",
            )
        )
    for ruta in salidas:
        print(f"  {ruta}  ({ruta.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
