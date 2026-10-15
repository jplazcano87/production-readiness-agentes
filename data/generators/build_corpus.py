#!/usr/bin/env python
"""Construye el corpus v1.0 y lo congela con hash.

Orden de construcción, impuesto por las dependencias:

1. esqueletos de producto (programático);
2. nombres y descripciones (LLM) — los necesitan las intenciones de comparación;
3. esqueletos de casos de las tres dimensiones (programático);
4. intenciones (LLM);
5. reseñas benignas (LLM) y adversariales (programáticas, desde las plantillas);
6. escritura de `data/corpus/v1.0/` y `MANIFEST.json` con el hash SHA-256 de cada archivo.

El corpus se escribe una vez y no se regenera al evaluar: es la condición para que dos
ejecuciones de E1 separadas en el tiempo sigan siendo comparables.

Uso:

    python data/generators/build_corpus.py --dry-run   # costo estimado, sin llamar a la API
    python data/generators/build_corpus.py             # construcción real
    python data/generators/build_corpus.py --sin-llm   # solo la capa programática
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

# `data/generators/` es un paquete fuera de `src/`. Al ejecutar este archivo como script,
# `sys.path[0]` es su propio directorio y `import generators` falla; se añade `data/` para
# que el comando documentado en el README funcione sin exportar PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from generators import CORPUS_VERSION, SEED_GLOBAL  # noqa: E402
from generators.casos_cumplimiento import (  # noqa: E402
    generar_casos_cumplimiento,
    validar_casos_de_cumplimiento,
)
from generators.casos_robustez import generar_casos_robustez, validar_casos  # noqa: E402
from generators.casos_seguridad import cargar_plantillas, generar_casos_seguridad  # noqa: E402
from generators.catalogo import generar_productos  # noqa: E402
from generators.redaccion import (
    estimar_costo,
    redactar_catalogo,
    redactar_intenciones,
    redactar_resenas,
)  # noqa: E402
from prf.env import CasoCumplimiento, CasoRobustez, CasoSeguridad, Catalog  # noqa: E402
from prf.infra.archivos import sha256_de  # noqa: E402
from prf.infra.client import AnthropicClient  # noqa: E402
from prf.infra.config import load_models  # noqa: E402
from prf.infra.cost import DryRunReport  # noqa: E402
from prf.infra.paths import paths  # noqa: E402
from prf.infra.results import utc_timestamp  # noqa: E402

ARCHIVOS = (
    "catalog.json",
    "reviews.jsonl",
    "cases_robustness.jsonl",
    "cases_security.jsonl",
    "cases_compliance.jsonl",
)


def sha256_archivo(ruta: Path) -> str:
    """SHA-256 de un archivo del corpus, que es lo que lo identifica una vez congelado."""
    return sha256_de(ruta)


def _escribir_jsonl(ruta: Path, filas: list[dict[str, Any]]) -> None:
    with ruta.open("w", encoding="utf-8") as handle:
        for fila in filas:
            handle.write(json.dumps(fila, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _escribir_json(ruta: Path, datos: Any) -> None:
    with ruta.open("w", encoding="utf-8") as handle:
        json.dump(datos, handle, ensure_ascii=False, indent=1, sort_keys=True)
        handle.write("\n")


def construir_esqueletos(seed: int) -> dict[str, Any]:
    """Toda la capa programática. Sin red, determinista por semilla."""
    productos = generar_productos(seed)
    catalog = Catalog.model_validate({"products": productos, "reviews": []})

    robustez = generar_casos_robustez(catalog, seed)
    errores = validar_casos(robustez, catalog)
    if errores:
        raise SystemExit("casos de robustez inalcanzables:\n  " + "\n  ".join(errores))

    seguridad, resenas_adversariales = generar_casos_seguridad(catalog, seed)
    cumplimiento = generar_casos_cumplimiento(seed)
    errores = validar_casos_de_cumplimiento(cumplimiento, catalog)
    if errores:
        raise SystemExit("casos de cumplimiento inalcanzables:\n  " + "\n  ".join(errores))

    return {
        "productos": productos,
        "catalog": catalog,
        "robustez": robustez,
        "seguridad": seguridad,
        "cumplimiento": cumplimiento,
        "resenas_adversariales": resenas_adversariales,
    }


def resolver_senuelo(texto: str, caso: dict[str, Any], nombres: dict[str, str]) -> str:
    """Sustituye `{producto_objetivo}` por el nombre comercial del producto señuelo.

    Se hace aquí y no en el generador porque el nombre lo escribe el LLM: hasta esta
    altura solo existe el id. Dejar el id en el texto haría que el usuario o la reseña
    hablaran en códigos de inventario, un delator del andamiaje ajeno al ataque.
    """
    if "{producto_objetivo}" not in texto:
        return texto
    senuelo = caso.get("producto_senuelo") or ""
    return texto.replace("{producto_objetivo}", nombres.get(senuelo, senuelo))


def _intent_final(caso: dict[str, Any], redactado: str, nombres: dict[str, str]) -> str:
    """Une la parte benigna redactada con la carga adversarial, **solo en el vector directo**.

    La carga se concatena **literal** salvo por el nombre del señuelo: si el LLM la
    reescribiera, el centinela cambiaría y el criterio de éxito dejaría de ser comprobable.

    En el vector **indirecto** la carga no va en el mensaje del usuario: vive en el texto que
    el agente recupera —la reseña o la descripción del producto portador—. Concatenarla aquí
    convertiría el ataque indirecto en directo sin que nada lo advirtiera, y el experimento
    estaría midiendo otra cosa. `scripts/calibrar_ataques.py` ya lo condicionaba así; esta
    función no, y el defecto estaba latente porque hasta v1.2 todo caso indirecto llevaba la
    carga vacía.
    """
    if caso.get("vector") == "indirect":
        return redactado.strip()
    carga = resolver_senuelo(caso.get("carga") or "", caso, nombres).strip()
    return f"{redactado.strip()} {carga}".strip() if carga else redactado.strip()


# Campos que `CasoSeguridad` estrena en v1.3. Se escriben solo cuando llevan algo: un
# `"portador": null` o un `"descripcion_adversarial": ""` añadido a los 140 casos heredados les
# cambiaría los bytes, y con ellos el hash del corpus, por un campo que no dice nada de ellos.
# La identidad byte a byte de lo heredado es lo que permite combinar las corridas de E2 ya
# pagadas con las nuevas en vez de repetirlas, así que no es un detalle de formato.
CAMPOS_NUEVOS_V1_3 = ("portador", "descripcion_adversarial")


def _fila_de_seguridad(datos: dict[str, Any]) -> dict[str, Any]:
    """El caso de seguridad como línea del corpus, sin los campos nuevos que estén vacíos."""
    fila = CasoSeguridad.model_validate(datos).model_dump(mode="json")
    for clave in CAMPOS_NUEVOS_V1_3:
        if not fila.get(clave):
            fila.pop(clave, None)
    return fila


def descripcion_envenenada(benigna: str, carga: str) -> str:
    """Descripción del portador con la carga añadida al final.

    Se **añade** en vez de sustituir porque es lo que hace verosímil la inyección: una ficha
    que solo contiene la instrucción no es una descripción de producto, y el ataque fallaría
    por delatarse y no por la defensa. Al final y no al principio porque el texto comercial
    es lo que da el contexto en el que la instrucción pasa por una condición de venta más.

    La carga queda **literal**: si se reescribiera, el centinela cambiaría y el criterio de
    éxito dejaría de ser comprobable. Que esté literal es también lo que permite buscarla en
    el resultado de la herramienta para decidir si se entregó.
    """
    if not carga:
        return benigna.strip()
    return f"{benigna.strip()} {carga.strip()}".strip()


def main(argv: list[str] | None = None) -> int:
    """Construye una versión del corpus y la congela con su hash. Acepta `--dry-run`."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dry-run", action="store_true", help="Estima el costo y termina.")
    parser.add_argument(
        "--sin-llm",
        action="store_true",
        help="Construye solo la capa programática (sin nombres, descripciones ni reseñas).",
    )
    parser.add_argument(
        "--rehacer-intenciones",
        action="store_true",
        help=(
            "Con --reusar-texto, vuelve a redactar solo las intenciones y conserva el "
            "catálogo y las reseñas. Necesario cuando cambia algo que la intención "
            "menciona, como el producto portador de un ataque indirecto."
        ),
    )
    parser.add_argument(
        "--reusar-texto",
        action="store_true",
        help=(
            "Reensambla el corpus con el texto ya redactado (catálogo, intenciones y "
            "reseñas benignas del corpus previo) sin llamar a la API. Sirve para aplicar "
            "una corrección de la capa programática sin volver a pagar por la redacción."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=SEED_GLOBAL,
        help="Semilla global. Cambiarla produce otro corpus.",
    )
    parser.add_argument(
        "--version", default=CORPUS_VERSION, help="Versión que se escribe en data/corpus/."
    )
    parser.add_argument(
        "--rehacer-casos",
        nargs="+",
        default=None,
        metavar="ID_O_PREFIJO",
        help=(
            "Con --reusar-texto, vuelve a redactar la intención de los casos cuyo `case_id` "
            "empiece por uno de estos valores y reutiliza las demás. Es lo que hace falta "
            "cuando cambia algo de la capa programática que la intención menciona, como el "
            "producto portador de un ataque indirecto: a diferencia de "
            "--rehacer-intenciones, no toca el texto de los casos que no cambiaron."
        ),
    )
    parser.add_argument(
        "--base",
        default=None,
        help=(
            "Versión de corpus de la que tomar el texto ya redactado, con --reusar-texto. "
            "Permite construir una versión nueva sobre otra sin copiar directorios a mano: "
            "lo que ya existe se reutiliza y solo se redacta lo que el corpus base no tenía."
        ),
    )
    args = parser.parse_args(argv)

    models = load_models()
    print(f"Construyendo el corpus {args.version} con semilla {args.seed}.\n")
    esqueletos = construir_esqueletos(args.seed)
    casos_con_intent = esqueletos["robustez"] + esqueletos["seguridad"]
    print(
        f"Capa programática: {len(esqueletos['productos'])} productos, "
        f"{len(esqueletos['robustez'])} casos de robustez, "
        f"{len(esqueletos['seguridad'])} de seguridad, "
        f"{len(esqueletos['cumplimiento'])} de cumplimiento, "
        f"{len(esqueletos['resenas_adversariales'])} reseñas adversariales.\n"
    )

    if args.dry_run:
        reporte = DryRunReport(titulo=f"build_corpus — corpus {args.version}")
        n_productos = len(esqueletos["productos"])
        n_intenciones = len(casos_con_intent)
        conceptos: set[str] | None = None
        if args.reusar_texto:
            # En modo incremental solo se paga por las intenciones que el corpus base no
            # trae. Estimar las tres tareas completas daría una cifra diez veces mayor que
            # el gasto real y la aprobación se pediría sobre un número que no es el que se
            # va a gastar.
            previo = _leer_corpus(_origen(args), esqueletos)
            faltan = _intenciones_faltantes(
                casos_con_intent, (previo or {}).get("intenciones"), args.rehacer_casos
            )
            n_productos, n_intenciones = 0, len(faltan)
            conceptos = {"intenciones de usuario"}
            reporte.notas.append(
                f"Modo incremental sobre {args.base or args.version}: se redactan "
                f"{len(faltan)} intenciones y se reutiliza el resto del texto. "
                "Catálogo y reseñas benignas no se vuelven a pedir."
            )
        for estimacion in estimar_costo(models, n_productos, n_intenciones):
            if conceptos is not None and estimacion.concepto not in conceptos:
                continue
            reporte.add(estimacion)
        reporte.notas.append(
            "Sin Batch API: la construcción del corpus es interactiva y sus fallos se "
            "corrigen en el momento; el descuento no compensa esperar hasta 24 horas."
        )
        reporte.notas.append(
            "Sin prompt caching: el prefijo compartido queda bajo el mínimo cacheable de "
            "Haiku 4.5 (4096 tokens) y no crearía ninguna entrada."
        )
        print(reporte)
        return 0

    productos = esqueletos["productos"]
    resenas_benignas: list[dict[str, Any]] = []
    benignas_intent: dict[str, str] = {}
    incidencias: list[str] = []
    destino = paths.corpus_version(args.version)

    if args.reusar_texto:
        origen = _origen(args)
        anterior = _leer_corpus(origen, esqueletos)
        if anterior is None:
            raise SystemExit(f"--reusar-texto necesita un corpus previo en {origen}; no lo hay.")
        productos = anterior["productos"]
        benignas_intent = anterior["intenciones"]
        resenas_benignas = anterior["resenas_benignas"]
        if origen != destino:
            incidencias.append(f"texto reutilizado del corpus base en {origen.name}")
        faltan = _intenciones_faltantes(casos_con_intent, benignas_intent, args.rehacer_casos)
        if faltan and not args.rehacer_intenciones:
            # Lo que distingue una versión incremental de una regeneración: se redactan las
            # intenciones de los casos nuevos y **solo** esas. Volver a pedir las 200 las
            # cambiaría todas, y las corridas ya pagadas dejarían de medir los mismos casos.
            client = AnthropicClient(models)
            print(f"Redactando {len(faltan)} intenciones nuevas…")
            nuevas, inc = redactar_intenciones(
                client, faltan, {p["id"]: p["name"] for p in productos}
            )
            benignas_intent.update(nuevas)
            incidencias += inc
            motivo = (
                f"por pedirse con --rehacer-casos {' '.join(args.rehacer_casos)}"
                if args.rehacer_casos
                else "por ser casos que el corpus base no tenía"
            )
            incidencias.append(
                f"{len(faltan)} intenciones redactadas {motivo}; las demás se reutilizaron "
                "sin cambios"
            )
            print(
                f"\nUso de la API: "
                f"{json.dumps(client.usage_summary()['total'], ensure_ascii=False)}"
            )
            print(f"Costo real: USD {client.ledger.costo_usd(models):.4f}\n")
        if args.rehacer_intenciones:
            client = AnthropicClient(models)
            print("Redactando intenciones…")
            benignas_intent, inc = redactar_intenciones(
                client, casos_con_intent, {p["id"]: p["name"] for p in productos}
            )
            incidencias += inc
            incidencias.append(
                "intenciones redactadas de nuevo; catálogo y reseñas benignas reutilizados"
            )
            print(
                f"\nUso de la API: "
                f"{json.dumps(client.usage_summary()['total'], ensure_ascii=False)}"
            )
            print(f"Costo real: USD {client.ledger.costo_usd(models):.4f}\n")
        elif not faltan:
            incidencias.append("reensamblado sobre el texto del corpus previo, sin llamar a la API")
    elif args.sin_llm:
        incidencias.append("ejecutado con --sin-llm: no hay texto redactado por el modelo")
        for producto in productos:
            producto["description"] = f"{producto['name']}."
        for caso in casos_con_intent:
            benignas_intent[caso["case_id"]] = caso.get("escenario") or caso.get("necesidad", "")
    else:
        client = AnthropicClient(models)
        print("Redactando catálogo…")
        productos, inc = redactar_catalogo(client, productos)
        incidencias += inc

        print("Redactando intenciones…")
        benignas_intent, inc = redactar_intenciones(
            client, casos_con_intent, {p["id"]: p["name"] for p in productos}
        )
        incidencias += inc

        print("Redactando reseñas…")
        resenas_benignas, inc = redactar_resenas(client, productos)
        incidencias += inc
        print(f"\nUso de la API: {json.dumps(client.usage_summary()['total'], ensure_ascii=False)}")
        print(f"Costo real: USD {client.ledger.costo_usd(models):.4f}\n")

    # --- ensamblado de los casos con su texto -------------------------------
    nombres = {p["id"]: p["name"] for p in productos}
    descripciones = {p["id"]: p.get("description") or "" for p in productos}
    resenas = resenas_benignas + [
        {**r, "text": resolver_senuelo(r["text"], _por_ataque(esqueletos, r), nombres)}
        for r in esqueletos["resenas_adversariales"]
    ]
    robustez = [
        CasoRobustez.model_validate(
            {**caso, "intent": benignas_intent.get(caso["case_id"], "")}
        ).model_dump(mode="json")
        for caso in esqueletos["robustez"]
    ]
    seguridad = []
    for caso in esqueletos["seguridad"]:
        datos = {
            clave: valor
            for clave, valor in caso.items()
            if clave not in ("necesidad", "categoria", "persona", "pii_simulada")
        }
        datos["carga"] = resolver_senuelo(caso.get("carga") or "", caso, nombres).strip()
        datos["intent"] = _intent_final(caso, benignas_intent.get(caso["case_id"], ""), nombres)
        if caso.get("portador") == "descripcion":
            datos["descripcion_adversarial"] = descripcion_envenenada(
                descripciones.get(caso.get("producto_portador") or "", ""), datos["carga"]
            )
        seguridad.append(_fila_de_seguridad(datos))
    cumplimiento = [
        CasoCumplimiento.model_validate(caso).model_dump(mode="json")
        for caso in esqueletos["cumplimiento"]
    ]

    # --- escritura ----------------------------------------------------------
    destino.mkdir(parents=True, exist_ok=True)
    _escribir_json(destino / "catalog.json", {"products": productos})
    _escribir_jsonl(destino / "reviews.jsonl", resenas)
    _escribir_jsonl(destino / "cases_robustness.jsonl", robustez)
    _escribir_jsonl(destino / "cases_security.jsonl", seguridad)
    _escribir_jsonl(destino / "cases_compliance.jsonl", cumplimiento)

    hashes = {nombre: sha256_archivo(destino / nombre) for nombre in ARCHIVOS}
    corpus_hash = hashlib.sha256(
        "".join(hashes[nombre] for nombre in ARCHIVOS).encode("utf-8")
    ).hexdigest()

    plantillas = cargar_plantillas()
    manifest = {
        "corpus_version": args.version,
        "corpus_hash": corpus_hash,
        "base": _base_declarada(args, destino),
        "seed": args.seed,
        "timestamp": utc_timestamp(),
        "modelo_redaccion": None if args.sin_llm else models.role("synthetic_writer").id,
        "notas": [
            "Las notas de las reseñas las fija el corpus a partir del `avg_rating` de "
            "cada producto (ver `redaccion.notas_objetivo`), no el modelo: así la media "
            "de las reseñas mostradas concuerda con la evaluación del catálogo.",
        ],
        "idioma": "es-CL",
        "datos": "100% sintéticos; PII simulada con dominio example.cl y RUT no asignados",
        "conteos": {
            "productos": len(productos),
            "resenas_benignas": sum(1 for r in resenas if not r["is_adversarial"]),
            "resenas_adversariales": sum(1 for r in resenas if r["is_adversarial"]),
            "casos_robustez": len(robustez),
            "casos_robustez_por_tipo": _contar(robustez, "tipo"),
            "casos_seguridad": len(seguridad),
            "casos_seguridad_por_tipo": _contar(seguridad, "tipo"),
            "casos_seguridad_por_objetivo": _contar(
                [c for c in seguridad if c.get("objetivo")], "objetivo"
            ),
            # Por superficie de inyección. Los casos de v1.2 no declaran `portador` y son
            # todos de reseña: se cuentan como tal con la misma regla que usa el evaluador.
            "casos_seguridad_por_portador": _contar(
                [
                    {"portador": CasoSeguridad.model_validate(c).portador_efectivo}
                    for c in seguridad
                    if c.get("vector") == "indirect"
                ],
                "portador",
            ),
            "casos_cumplimiento": len(cumplimiento),
            "plantillas_ataque": {
                "dev": sum(1 for p in plantillas if p["particion"] == "dev"),
                "test": sum(1 for p in plantillas if p["particion"] == "test"),
            },
        },
        "archivos": [
            {"nombre": nombre, "sha256": hashes[nombre], "bytes": (destino / nombre).stat().st_size}
            for nombre in ARCHIVOS
        ],
        "incidencias": incidencias,
    }
    _escribir_json(destino / "MANIFEST.json", manifest)

    print(f"Corpus escrito en {destino}")
    print(f"corpus_hash: {corpus_hash}")
    if incidencias:
        print(f"\nIncidencias registradas ({len(incidencias)}):")
        for incidencia in incidencias:
            print(f"  - {incidencia}")
    return 0


def _por_ataque(esqueletos: dict[str, Any], resena: dict[str, Any]) -> dict[str, Any]:
    """El caso indirecto al que pertenece una reseña adversarial."""
    for caso in esqueletos["seguridad"]:
        if caso.get("case_id") == resena.get("attack_id"):
            return caso
    return {}


def _origen(args: argparse.Namespace) -> Path:
    """Directorio del que se reutiliza el texto: el corpus base si se declaró, o el destino."""
    return paths.corpus_version(args.base or args.version)


def _base_declarada(args: argparse.Namespace, destino: Path) -> str | None:
    """De qué versión hereda este corpus, que no es lo mismo que de dónde se reutilizó texto.

    Reconstruir una versión **sobre sí misma** —lo que hace falta para rehacer unos casos sin
    volver a pagar el resto del texto— no cambia de quién hereda. Sin esto, el segundo
    reensamblado de v1.3 escribiría `base: v1.3` y el registro perdería la única pista de que
    el corpus es incremental sobre v1.2.
    """
    if args.base and args.base != args.version:
        return str(args.base)
    manifest = destino / "MANIFEST.json"
    if manifest.is_file():
        previo = json.loads(manifest.read_text(encoding="utf-8")).get("base")
        if previo and previo != args.version:
            return str(previo)
    return args.base


def _intenciones_faltantes(
    casos: list[dict[str, Any]],
    intenciones: dict[str, str] | None,
    rehacer: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Casos cuya intención hay que redactar: los que no la tienen y los que se piden rehacer.

    Lo segundo no es una comodidad. Si cambia algo de la capa programática que la intención
    nombra —el producto portador de un ataque indirecto, por ejemplo— la intención reutilizada
    pide un producto que el caso ya no usa, y el ataque no se entrega nunca. El caso contaría
    como bloqueado sin que ninguna defensa lo bloqueara.
    """
    disponibles = intenciones or {}
    prefijos = tuple(rehacer or ())
    return [
        c
        for c in casos
        if not (disponibles.get(c["case_id"]) or "").strip()
        or (prefijos and c["case_id"].startswith(prefijos))
    ]


def _leer_corpus(destino: Path, esqueletos: dict[str, Any]) -> dict[str, Any] | None:
    """Recupera el texto redactado de un corpus previo: catálogo, intenciones y reseñas.

    De las intenciones de seguridad se devuelve solo la **parte benigna**: la carga
    adversarial se vuelve a concatenar en el ensamblado, y dejarla dentro la duplicaría.
    Se recorta comparando con la carga que el generador produce para ese mismo caso, así
    que el recorte es exacto y no una heurística sobre el texto.
    """
    catalogo = destino / "catalog.json"
    if not catalogo.is_file():
        return None
    productos = json.loads(catalogo.read_text(encoding="utf-8"))["products"]
    nombres = {p["id"]: p["name"] for p in productos}
    # Formas que la carga pudo tener en el corpus previo: con el nombre comercial (forma
    # actual), con el id (forma anterior a la corrección del señuelo) y con el marcador sin
    # resolver. Probar las tres hace que el recorte siga siendo exacto aunque el corpus en
    # disco venga de una versión anterior del generador.
    cargas: dict[str, list[str]] = {}
    for caso in esqueletos["seguridad"]:
        bruta = (caso.get("carga") or "").strip()
        if not bruta:
            continue
        senuelo = caso.get("producto_senuelo") or ""
        cargas[caso["case_id"]] = [
            bruta.replace("{producto_objetivo}", nombres.get(senuelo, senuelo)),
            bruta.replace("{producto_objetivo}", senuelo),
            bruta,
        ]

    intenciones: dict[str, str] = {}
    for nombre in ("cases_robustness.jsonl", "cases_security.jsonl"):
        archivo = destino / nombre
        if not archivo.is_file():
            return None
        for linea in archivo.read_text(encoding="utf-8").splitlines():
            if not linea.strip():
                continue
            caso = json.loads(linea)
            texto = caso["intent"]
            # Se recorta en bucle: un corpus reensamblado con una versión anterior del
            # generador puede llevar más de una carga encadenada al final.
            for _ in range(4):
                recortado = False
                for carga in cargas.get(caso["case_id"], []):
                    if carga and texto.endswith(carga):
                        texto = texto[: -len(carga)].strip()
                        recortado = True
                        break
                if not recortado:
                    break
            intenciones[caso["case_id"]] = texto

    reviews = destino / "reviews.jsonl"
    benignas = [
        fila
        for fila in (
            json.loads(linea)
            for linea in reviews.read_text(encoding="utf-8").splitlines()
            if linea.strip()
        )
        if not fila["is_adversarial"]
    ]
    return {"productos": productos, "intenciones": intenciones, "resenas_benignas": benignas}


def _contar(filas: list[dict[str, Any]], clave: str) -> dict[str, int]:
    conteo: dict[str, int] = {}
    for fila in filas:
        valor = fila.get(clave)
        if valor is not None:
            conteo[str(valor)] = conteo.get(str(valor), 0) + 1
    return dict(sorted(conteo.items()))


if __name__ == "__main__":
    sys.exit(main())
