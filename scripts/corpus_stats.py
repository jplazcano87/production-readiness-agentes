#!/usr/bin/env python
"""Estadísticas descriptivas del corpus (tabla 3 del informe).

Escribe `tables/corpus_stats.md` con cinco filas y las columnas N, Media, Mediana,
Desviación estándar y Mínimo–Máximo.

**Conteo de tokens.** Por omisión usa una aproximación local declarada
(`prf.infra.tokens`: un token cada 3,6 caracteres, calibrada para español), que no
requiere red y hace la tabla reproducible sin gastar cuota. Con `--tokenizador sdk` se usa
el conteo exacto de `messages.count_tokens`, y con `--calibrar N` se comparan ambos sobre
una muestra para poder declarar el error de la aproximación en el informe en vez de
afirmarlo sin evidencia.

Uso:

    python scripts/corpus_stats.py                  # aproximación local
    python scripts/corpus_stats.py --calibrar 40    # además mide su error contra el SDK
    python scripts/corpus_stats.py --tokenizador sdk
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from prf.infra.archivos import leer_jsonl  # noqa: E402
from prf.infra.config import load_experiments, load_models  # noqa: E402
from prf.infra.paths import paths  # noqa: E402
from prf.infra.tokens import CHARS_POR_TOKEN_ES, approx_tokens  # noqa: E402

Contador = Callable[[str], int]


def cargar_corpus(version: str) -> dict[str, Any]:
    """Productos, reseñas y los tres archivos de casos."""
    raiz = paths.corpus_version(version)

    def jsonl(nombre: str) -> list[dict[str, Any]]:
        """Un archivo del corpus, con un mensaje útil si todavía no se ha construido."""
        ruta = raiz / nombre
        if not ruta.is_file():
            raise SystemExit(
                f"falta {ruta}: construye el corpus antes de calcular sus estadísticas"
            )
        return leer_jsonl(ruta)

    catalogo = raiz / "catalog.json"
    if not catalogo.is_file():
        raise SystemExit(f"falta {catalogo}")

    return {
        "productos": json.loads(catalogo.read_text(encoding="utf-8"))["products"],
        "resenas": jsonl("reviews.jsonl"),
        "robustez": jsonl("cases_robustness.jsonl"),
        "seguridad": jsonl("cases_security.jsonl"),
        "cumplimiento": jsonl("cases_compliance.jsonl"),
        "manifest": json.loads((raiz / "MANIFEST.json").read_text(encoding="utf-8")),
    }


def cargas_adversariales(corpus: dict[str, Any]) -> dict[str, list[str]]:
    """El texto inyectado de cada ataque, por superficie.

    Lo que se mide es **lo que entra en el contexto del agente**, no solo la instrucción:

    - vector **directo**: la carga que se añade al mensaje del usuario;
    - portador **reseña**: la reseña completa que la transporta;
    - portador **descripción**: la ficha completa del producto con la carga ya incrustada.

    Las tres se cuentan por separado porque no son comparables entre sí: una ficha de producto
    envenenada arrastra la descripción comercial legítima, que el ataque no escribió pero el
    agente sí lee. Promediarlas daría una cifra que no describe a ninguna.
    """
    por_ataque = {r["attack_id"]: r["text"] for r in corpus["resenas"] if r.get("is_adversarial")}
    textos: dict[str, list[str]] = {"directo": [], "resena": [], "descripcion": []}
    for caso in corpus["seguridad"]:
        if caso["tipo"] == "directo" and caso.get("carga"):
            textos["directo"].append(caso["carga"])
        elif caso["tipo"] == "indirecto":
            if caso.get("portador") == "descripcion":
                ficha = caso.get("descripcion_adversarial")
                if ficha:
                    textos["descripcion"].append(ficha)
            else:
                texto = por_ataque.get(caso["case_id"])
                if texto:
                    textos["resena"].append(texto)
    return textos


def series(corpus: dict[str, Any], contar: Contador) -> list[tuple[str, list[float]]]:
    """Las filas de la tabla 3, en su orden exacto.

    La carga adversarial va en una fila agregada —la que existía y permite comparar con las
    versiones anteriores del corpus— seguida de una por superficie. Desde v1.3 el agregado
    mezcla tres cosas distintas, así que solo vale para la serie histórica.
    """
    intenciones = [
        caso["intent"]
        for grupo in ("robustez", "seguridad", "cumplimiento")
        for caso in corpus[grupo]
    ]
    benignas = [r for r in corpus["resenas"] if not r.get("is_adversarial")]
    por_producto: dict[str, int] = {p["id"]: 0 for p in corpus["productos"]}
    for resena in corpus["resenas"]:
        if resena["product_id"] in por_producto:
            por_producto[resena["product_id"]] += 1

    cargas = cargas_adversariales(corpus)
    filas: list[tuple[str, list[float]]] = [
        ("Precio del producto (CLP)", [float(p["price_clp"]) for p in corpus["productos"]]),
        ("Longitud de intención (tokens)", [float(contar(t)) for t in intenciones]),
        ("Longitud de reseña (tokens)", [float(contar(r["text"])) for r in benignas]),
        ("Reseñas por producto", [float(v) for v in por_producto.values()]),
        (
            "Longitud de carga adversarial (tokens)",
            [float(contar(t)) for todas in cargas.values() for t in todas],
        ),
    ]
    etiquetas = {
        "directo": "    vector directo",
        "resena": "    portador reseña",
        "descripcion": "    portador descripción",
    }
    for clave, etiqueta in etiquetas.items():
        if cargas[clave]:
            filas.append((etiqueta, [float(contar(t)) for t in cargas[clave]]))
    return filas


def _formatear(valor: float, *, miles: bool) -> str:
    if miles:
        return f"{valor:,.0f}".replace(",", ".")
    return f"{valor:.1f}"


def fila_markdown(nombre: str, valores: list[float]) -> str:
    """Una fila de la tabla, con media, mediana, desviación y rango."""
    miles = "CLP" in nombre
    n = len(valores)
    media = statistics.mean(valores)
    mediana = statistics.median(valores)
    desviacion = statistics.stdev(valores) if n > 1 else 0.0
    minimo, maximo = min(valores), max(valores)
    return (
        f"| {nombre} | {n} | {_formatear(media, miles=miles)} | "
        f"{_formatear(mediana, miles=miles)} | {_formatear(desviacion, miles=miles)} | "
        f"{_formatear(minimo, miles=miles)}–{_formatear(maximo, miles=miles)} |"
    )


def tabla_markdown(filas: list[tuple[str, list[float]]], *, nota: str) -> str:
    """La tabla completa de estadísticas descriptivas."""
    lineas = [
        "| Variable | N | Media | Mediana | Desv. est. | Mín.–Máx. |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    lineas.extend(fila_markdown(nombre, valores) for nombre, valores in filas)
    lineas.extend(["", nota])
    return "\n".join(lineas)


def calibrar(textos: list[str], client: Any, muestra: int) -> dict[str, float]:
    """Compara la aproximación local con el conteo exacto del SDK sobre una muestra.

    Permite declarar el error de la aproximación en el informe con una medición, en vez de
    afirmar que «es razonable».
    """
    import random

    rng = random.Random(load_experiments()["seed_global"])
    elegidos = rng.sample(textos, min(muestra, len(textos)))
    errores, ratios = [], []
    for texto in elegidos:
        exacto = client.count_tokens("synthetic_writer", [{"role": "user", "content": texto}])
        aproximado = approx_tokens(texto)
        errores.append(abs(aproximado - exacto) / exacto)
        ratios.append(len(texto) / exacto)
    return {
        "n": len(elegidos),
        "error_relativo_medio": statistics.mean(errores),
        "error_relativo_max": max(errores),
        "chars_por_token_observado": statistics.mean(ratios),
    }


def main(argv: list[str] | None = None) -> int:
    """Escribe las estadísticas descriptivas del corpus vigente en `tables/`."""
    experimentos = load_experiments()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--version",
        default=experimentos["corpus_version"],
        help="Versión del corpus que se describe. Por omisión, la vigente.",
    )
    parser.add_argument(
        "--tokenizador",
        choices=("aproximado", "sdk"),
        default="aproximado",
        help="`sdk` usa messages.count_tokens y requiere red.",
    )
    parser.add_argument(
        "--calibrar",
        type=int,
        default=0,
        metavar="N",
        help="Mide el error de la aproximación contra el SDK sobre N textos.",
    )
    parser.add_argument("--salida", default=None, help="Archivo Markdown de destino.")
    args = parser.parse_args(argv)

    corpus = cargar_corpus(args.version)
    client = None
    if args.tokenizador == "sdk" or args.calibrar:
        from prf.infra.client import AnthropicClient

        client = AnthropicClient(load_models())

    if args.tokenizador == "sdk":

        def contar(texto: str) -> int:
            return client.count_tokens("synthetic_writer", [{"role": "user", "content": texto}])

        metodo = "conteo exacto con `messages.count_tokens` del SDK de Anthropic"
    else:
        contar = approx_tokens
        metodo = (
            f"aproximación local declarada: un token cada {CHARS_POR_TOKEN_ES} caracteres "
            "(`prf.infra.tokens.approx_tokens`), sin llamadas a la API"
        )

    filas = series(corpus, contar)

    n_resenas_adv = sum(1 for r in corpus["resenas"] if r.get("is_adversarial"))
    n_descripcion = sum(1 for c in corpus["seguridad"] if c.get("portador") == "descripcion")
    nota = (
        f"Corpus `{args.version}`, hash `{corpus['manifest']['corpus_hash']}`. "
        f"Conteo de tokens: {metodo}. «Reseñas por producto» cuenta también la reseña "
        f"adversarial de los {n_resenas_adv} productos portadores de una inyección por "
        "reseña, una por ataque, que por eso llegan a cuatro."
    )
    if n_descripcion:
        nota += (
            f" Los {n_descripcion} portadores de una inyección por descripción no añaden "
            "ninguna reseña: su carga va en la ficha del producto."
        )
    nota += (
        " Las tres filas de carga adversarial miden lo que entra en el contexto del agente: "
        "la carga sola en el vector directo, y el texto completo que la transporta —la reseña "
        "o la ficha del producto— en el indirecto. La fila agregada mezcla las tres y solo "
        "sirve para comparar con las versiones anteriores del corpus."
    )

    if args.calibrar:
        textos = [c["intent"] for c in corpus["robustez"]] + [
            r["text"] for r in corpus["resenas"] if not r.get("is_adversarial")
        ]
        medicion = calibrar(textos, client, args.calibrar)
        nota += (
            f" Error de la aproximación medido sobre {medicion['n']} textos: "
            f"{medicion['error_relativo_medio']:.1%} en promedio y "
            f"{medicion['error_relativo_max']:.1%} en el peor caso "
            f"({medicion['chars_por_token_observado']:.2f} caracteres por token observados)."
        )
        print(json.dumps(medicion, ensure_ascii=False, indent=1))

    tabla = tabla_markdown(filas, nota=nota)
    destino = Path(args.salida) if args.salida else paths.tables / "corpus_stats.md"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(tabla + "\n", encoding="utf-8")

    print(tabla)
    print(f"\n  escrito en {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
