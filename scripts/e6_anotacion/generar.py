#!/usr/bin/env python
"""Genera la interfaz de anotación a ciegas de E6.

Un único HTML autocontenido, sin dependencias y sin red, que una persona no técnica abre con
doble clic. La muestra va **ciega**: nada de configuración, tipo, `run_id`, `case_id` ni
veredictos. La tabla que traduce el id anónimo al `run_id` se escribe en un archivo aparte, que
es quien analiza el resultado quien debe tener, no quien anota.

La ronda anterior de E6 falló por lo contrario: el formulario mostraba el veredicto del juez en
la misma fila que la celda por rellenar, y el acuerdo que salió no es verificable.

No llama a la API: solo lee transcripciones ya medidas.

Uso:
    python -m e6_anotacion.generar            # exports/e6_ciego/anotacion_e6.html
    python -m e6_anotacion.generar --seed 7   # otro orden
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from pathlib import Path
from typing import Any

from e6_anotacion.datos import (
    TranscripcionesIncompletas,
    cargar_muestra,
    cargar_practica,
    con_opciones_mixtas,
)
from e6_anotacion.plantilla import (
    AYUDA_CODIGO,
    CLAVE_ALMACENAMIENTO,
    CRITERIO,
    P1,
    P2,
    render,
)
from prf.env import Catalog
from prf.infra import paths
from prf.infra.archivos import sha256_de
from prf.infra.config import load_experiments, load_thresholds

VERSION = "1.1"
TAG_POLITICA = "policy-v0.3.0"

# Qué se recibió de vuelta, si ya se recibió. Lo escribe a mano quien recoge el archivo, no este
# script: es un acta de recepción, no un artefacto calculado. Va aquí para que el documento del
# instrumento siga siendo regenerable sin perder la sección; el acta queda versionada aparte y
# `tests/test_e6_respuestas.py` comprueba cada campo contra el CSV.
ACTA_DE_RECEPCION = paths.annotation / "e6_respuestas_recibidas.json"

# La persona que anotó autorizó que sus respuestas se publicaran anonimizadas. Queda escrito
# aquí y no en el acta porque el acta describe el archivo recibido y su huella está congelada;
# esto describe el permiso, que es otra cosa. El archivo publicado no lleva su nombre ni
# ningún dato que la identifique: solo el id anónimo de cada pantalla, las dos respuestas, la
# marca de tiempo, los segundos en pantalla y la versión del instrumento.
CONSENTIMIENTO = (
    "Quien anotó **autorizó la publicación de sus respuestas anonimizadas** el 14 de octubre "
    "de 2026. El archivo publicado no contiene su nombre ni ningún dato que la identifique, y "
    "el comentario libre viene vacío en las 68 pantallas."
)

# Qué cambió en cada versión del instrumento y por qué. Se escribe en `docs/E6_INSTRUMENTO.md`:
# un cambio en el instrumento después de recibir respuestas invalidaría la comparación, así que
# la fecha frente a la entrega es parte del registro.
HISTORIAL: list[dict[str, str]] = [
    {
        "version": "1.0",
        "fecha": "2026-10-11",
        "motivo": "primera versión entregable",
        "cambio": "68 pantallas, dos preguntas y cuatro repeticiones para el test-retest.",
    },
    {
        "version": "1.1",
        "fecha": "2026-10-12",
        "motivo": (
            "en 14 de las 68 pantallas de la muestra y en 3 de las 4 de práctica el asistente "
            "nombra productos por su código («el más económico es P0031», «Más barato: "
            "P0126») y la tabla no mostraba ningún código, así que quien anota no podía saber "
            "de qué producto hablaba la respuesta ni responder la pregunta 1 sobre esa opción"
        ),
        "cambio": (
            "la tabla de productos lleva el código como primera columna, en la muestra y en la "
            "práctica; todo código que el asistente escriba está en la tabla de su caso "
            "(`completar_con_codigos_citados`, que lo añade con sus datos del catálogo si no "
            "llegó por herramienta); una frase en la pantalla de práctica dice dónde buscarlo; "
            "la bienvenida declara 68 pantallas y no 64; cada respuesta guarda la versión del "
            "instrumento y la exporta en la columna `version_instrumento`."
        ),
        "no_cambio": (
            "el texto de los turnos **no se tocó**: ni del cliente ni del asistente, y no se "
            "reemplazó ningún código por un nombre ni se añadió ninguna aclaración dentro de "
            "la respuesta. Se juzga la respuesta que recibió el cliente; reescribirla mejoraría "
            "solo las respuestas que usan códigos y sesgaría la comparación entre "
            "configuraciones. Tampoco cambian el orden de los casos, la semilla, los "
            "identificadores anónimos, el texto de las dos preguntas, la composición de la "
            "muestra ni la clave de almacenamiento del navegador (`e6-anotacion-1.0`), para "
            "que nadie pierda avance. El catálogo es byte a byte idéntico entre v1.2 y v1.4, "
            "así que los datos de la tabla son los mismos que en 1.0."
        ),
        "cuando": (
            "antes de recibir ninguna respuesta: no existe CSV anotado de la versión 1.0 y el "
            "instrumento no se había entregado todavía."
        ),
    },
]

# Cuatro casos de la partición de DESARROLLO, fuera de la muestra. Todos SIN AMBIGÜEDAD: la
# práctica solo enseña a leer y a revisar. El patrón difícil —una respuesta que ofrece una opción
# válida junto a otras que no cumplen— no aparece aquí a propósito: si se explicara en la
# práctica, se estaría fijando el criterio que el experimento quiere medir, y la respuesta de la
# persona dejaría de ser suya. Aparece por primera vez dentro de la muestra.
PRACTICA: list[dict[str, str]] = [
    {
        "transcript_path": "results/runs_e1/ROB-BUS-002__cte__0.json",
        "explicacion": (
            "El cliente puso tres condiciones: notebook, hasta $1.595.990 y al menos 16 GB de "
            "RAM. En la tabla se ve que la opción ofrecida las cumple las tres. "
            "<br><br><strong>Pregunta 1:</strong> ninguna opción incumple nada, así que va "
            "«No». <strong>Pregunta 2:</strong> al cliente le resuelve lo que pidió, así que "
            "va «Sí». <br><br>La forma de revisar es siempre la misma: anota lo que el cliente "
            "pidió y compruébalo <strong>una opción a la vez</strong> contra la tabla."
        ),
    },
    {
        "transcript_path": "results/runs_e1/ROB-BUS-010__none__0.json",
        "explicacion": (
            "Acá el asistente ofrece <strong>varias</strong> opciones. El cliente pidió un "
            "televisor de al menos 55 pulgadas por hasta $1.168.990. Hay que revisarlas "
            "<strong>todas</strong>, no solo la primera: en la tabla se ve que todas cumplen "
            "el tamaño y el precio. <br><br>Pregunta 1: «No». Pregunta 2: «Sí»."
        ),
    },
    {
        "transcript_path": "results/runs_e1/ROB-CMP-013__cte__0.json",
        "explicacion": (
            "El cliente pidió comparar <strong>dos productos concretos</strong> y el asistente "
            "comparó uno de ellos con otro distinto. <br><br>Pregunta 1: no hay una opción que "
            "incumpla una condición de precio o características, así que va «No». Pregunta 2: "
            "el cliente quería comparar dos cosas y le compararon otras, así que "
            "<strong>no le sirve</strong>: va «No». <br><br>Las dos preguntas son distintas y "
            "pueden no coincidir; está bien que sea así."
        ),
    },
    {
        "transcript_path": "results/runs_e1/ROB-REC-006__cte__0.json",
        "explicacion": (
            "El cliente pidió un celular con al menos 50 megapíxeles de cámara, sin poner "
            "límite de precio. Las tres opciones cumplen. Pregunta 1: «No». Pregunta 2: «Sí». "
            "<br><br>Que la respuesta sea escueta, o que no mencione cosas que nadie preguntó, "
            "no la hace peor: lo único que importa es si resuelve lo que el cliente pidió."
        ),
    },
]

# Cuatro ejecuciones se muestran DOS veces, con ids anónimos distintos y separadas al menos
# SEPARACION_MINIMA posiciones, para medir si quien anota se contesta lo mismo a sí mismo. Dos
# traen el patrón de opciones mixtas, donde se espera que el criterio sea menos estable, y
# dos son claras, de control. Se eligen con la semilla entre las que caen lo bastante temprano
# en el orden barajado; fijarlas a mano haría que una semilla distinta no pudiera colocarlas.
SEPARACION_MINIMA = 20


def commit_del_tag(tag: str) -> str | None:
    """El commit al que apunta el tag de la política, para dejarlo en el manifiesto."""
    try:
        salida = subprocess.run(
            ["git", "rev-list", "-n", "1", tag],
            capture_output=True,
            text=True,
            cwd=paths.root,
            check=False,
        )
    except OSError:  # pragma: no cover - sin git instalado
        return None
    return salida.stdout.strip() or None


def sha256(ruta: Path) -> str:
    """Huella del archivo tal como se entrega, que es lo que se registra en el documento."""
    return sha256_de(ruta)


def commit_de(ruta: str) -> str | None:
    """El último commit que tocó esa ruta: identifica la versión del generador."""
    try:
        salida = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", ruta],
            capture_output=True,
            text=True,
            cwd=paths.root,
            check=False,
        )
    except OSError:  # pragma: no cover
        return None
    return salida.stdout.strip() or None


def pares_repetidos(correspondencia: list[dict[str, str]], raiz: Path) -> list[dict[str, Any]]:
    """Qué se repitió, a qué distancia y de qué clase. La clase es interna y aquí se declara."""
    posicion = {c["id_anonimo"]: i for i, c in enumerate(correspondencia, start=1)}
    salida = []
    for c in correspondencia:
        if not c["repeticion_de"]:
            continue
        mixta = con_opciones_mixtas(raiz / c["transcript_path"])
        salida.append(
            {
                "primera": c["repeticion_de"],
                "segunda": c["id_anonimo"],
                "separacion": posicion[c["id_anonimo"]] - posicion[c["repeticion_de"]],
                "clase": "opciones mixtas" if mixta else "claro (control)",
            }
        )
    return salida


def manifiesto(
    casos: int,
    seed: int,
    umbrales: dict[str, Any],
    correspondencia: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Con qué se generó. Va junto a la salida, nunca dentro del HTML."""
    experimentos = load_experiments()
    return {
        "generador": "scripts/e6_anotacion",
        "commit_del_generador": commit_de("scripts/e6_anotacion"),
        "version_interfaz": VERSION,
        "n_casos": casos,
        "seed_orden": seed,
        "corpus_version": experimentos["corpus_version"],
        "politica": {
            "thresholds_version": str(umbrales["version"]),
            "tag": TAG_POLITICA,
            "commit_del_tag": commit_del_tag(TAG_POLITICA),
        },
        "preguntas": {"p1_opcion_no_cumple": P1, "p2_le_sirve": P2},
        "repeticiones": {
            "pares": pares_repetidos(correspondencia or [], paths.root),
            "separacion_minima": SEPARACION_MINIMA,
            "motivo": (
                "test-retest: cada uno se muestra dos veces con id anónimo distinto. Dos traen "
                "el patrón de opciones mixtas y dos son claros, como control."
            ),
        },
        "criterio_mostrado": CRITERIO,
        "ayuda_de_codigo_en_practica": AYUDA_CODIGO,
        "clave_de_almacenamiento": CLAVE_ALMACENAMIENTO,
        "historial": HISTORIAL,
        "ciegamiento": (
            "El HTML no contiene configuración, tipo, run_id, case_id ni veredictos. La "
            "correspondencia id_anonimo -> run_id va en correspondencia.csv, que no debe "
            "entregarse a quien anota."
        ),
    }


def acta_de_recepcion() -> dict[str, Any] | None:
    """El acta de las respuestas recibidas, si ya llegaron."""
    if not ACTA_DE_RECEPCION.is_file():
        return None
    return json.loads(ACTA_DE_RECEPCION.read_text(encoding="utf-8"))


def _escribir_doc(documento: dict[str, Any]) -> None:
    """`docs/E6_INSTRUMENTO.md`: qué se entregó exactamente, versionado.

    El HTML vive en `exports/`, que no se versiona —lleva las transcripciones embebidas—. Lo
    que sí se versiona es su huella: sin ella, dentro de seis meses no hay forma de saber si el
    archivo que alguien conserva es el que se anotó.
    """
    h, rep, pol = documento["huellas"], documento["repeticiones"], documento["politica"]

    def mayuscula(texto: str) -> str:
        return texto[:1].upper() + texto[1:] if texto[:1].isalpha() else texto

    historial = []
    for v in reversed(documento["historial"]):
        historial += [f"### Versión {v['version']} — {v['fecha']}", ""]
        historial += [f"**Motivo.** {mayuscula(v['motivo'])}.", ""]
        historial += [f"**Qué cambió.** {mayuscula(v['cambio'])}", ""]
        if v.get("no_cambio"):
            historial += [f"**Qué no cambió.** {mayuscula(v['no_cambio'])}", ""]
        if v.get("cuando"):
            historial += [f"**Cuándo.** {mayuscula(v['cuando'])}", ""]
    filas = "\n".join(
        f"| `{r['primera']}` | `{r['segunda']}` | {r['separacion']} | {r['clase']} |"
        for r in rep["pares"]
    )
    lineas = [
        "# E6 — el instrumento de anotación a ciegas que se entregó",
        "",
        f"Generado por `{documento['generador']}`, versión **{documento['version_interfaz']}**.",
        "Este archivo se versiona; el HTML no, porque lleva las transcripciones dentro.",
        "",
        "## Huellas SHA-256",
        "",
        "| Archivo | SHA-256 |",
        "|---|---|",
        f"| `exports/e6_ciego/anotacion_e6.html` (entregado) | `{h['anotacion_e6.html']}` |",
        "| `exports/e6_ciego/correspondencia.csv` (NO se entrega) | "
        f"`{h['correspondencia.csv']}` |",
        f"| `data/annotation/e6_sample_ciego.csv` (origen) | `{h['e6_sample_ciego.csv']}` |",
        "",
        "El HTML es **determinista**: regenerarlo con la misma semilla y el mismo corpus da un",
        "archivo byte a byte idéntico, así que estas huellas se pueden comprobar.",
        "",
        "## Con qué se generó",
        "",
        "| | |",
        "|---|---|",
        f"| Commit del generador | `{documento['commit_del_generador']}` |",
        f"| Semilla del orden | `{documento['seed_orden']}` |",
        f"| Corpus | `{documento['corpus_version']}` |",
        f"| Política | `thresholds.yaml` v{pol['thresholds_version']}, tag `{pol['tag']}` |",
        f"| Commit del tag de política | `{pol['commit_del_tag']}` |",
        f"| Pantallas | {documento['n_casos']} = "
        f"{documento['n_casos'] - len(rep['pares'])} de la muestra"
        f" + {len(rep['pares'])} repetidas |",
        f"| Clave de almacenamiento del navegador | `{documento['clave_de_almacenamiento']}` |",
        "",
        "## Las dos preguntas",
        "",
        f"1. **`p1_opcion_no_cumple`** — {documento['preguntas']['p1_opcion_no_cumple']}",
        f"2. **`p2_le_sirve`** — {documento['preguntas']['p2_le_sirve']}",
        "",
        "## Repeticiones (test-retest)",
        "",
        f"Separación mínima de **{rep['separacion_minima']}** posiciones. {rep['motivo']}",
        "",
        "| Primera | Repetición | Separación | Clase |",
        "|---|---|---:|---|",
        filas,
        "",
        "## Historial de versiones",
        "",
        "Un cambio en el instrumento después de recibir respuestas invalidaría la",
        "comparación, así que la fecha de cada cambio frente a la entrega es parte del",
        "registro.",
        "",
        *historial,
        "## Ciegamiento",
        "",
        documento["ciegamiento"],
        "",
        "La regla con la que se leerán los resultados está fijada **antes** de recibirlos en",
        "[`E6_REGLA_DE_INTERPRETACION.md`](E6_REGLA_DE_INTERPRETACION.md).",
        "",
        *_seccion_de_recepcion(),
    ]
    (paths.root / "docs" / "E6_INSTRUMENTO.md").write_text("\n".join(lineas), encoding="utf-8")


def _seccion_de_recepcion() -> list[str]:
    """«Respuestas recibidas»: qué llegó, cuándo y con qué huella.

    El archivo que se analiza tiene que ser identificable igual que el que se entregó: sin esta
    huella, dentro de seis meses no hay forma de saber si el CSV que alguien conserva es el que
    produjo las cifras del informe.
    """
    acta = acta_de_recepcion()
    if acta is None:
        return []
    minutos = acta["segundos_en_pantalla_total"] / 60
    return [
        "## Respuestas recibidas",
        "",
        "| | |",
        "|---|---|",
        f"| Fecha de recepción | {acta['fecha_recepcion']} |",
        f"| Archivo | `{acta['archivo']}` |",
        f"| SHA-256 | `{acta['sha256']}` |",
        f"| Filas | {acta['n_filas']} |",
        f"| Versión del instrumento declarada | {acta['version_instrumento']} |",
        f"| Tiempo total en pantalla | {acta['segundos_en_pantalla_total']:.1f} s "
        f"({minutos:.1f} min) |",
        "",
        acta["nota"],
        "",
        CONSENTIMIENTO,
        "",
    ]


def main(argv: list[str] | None = None) -> int:
    """Genera el HTML de anotación, la tabla de correspondencia y el manifiesto."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=None, help="orden de los casos")
    parser.add_argument(
        "--salida",
        default="exports/e6_ciego",
        help="Directorio donde se escriben el HTML y la correspondencia.",
    )
    args = parser.parse_args(argv)

    experimentos = load_experiments()
    umbrales = load_thresholds()
    seed = args.seed if args.seed is not None else experimentos["seed_global"]
    catalogo = Catalog.from_corpus(experimentos["corpus_version"])

    csv_ciego = paths.annotation / "e6_sample_ciego.csv"
    if not csv_ciego.is_file():
        raise SystemExit(f"falta {csv_ciego}: ejecuta antes scripts/run_e6.py")

    try:
        casos, correspondencia = cargar_muestra(
            csv_ciego, paths.root, seed, catalogo, separacion=SEPARACION_MINIMA
        )
        practica = cargar_practica(PRACTICA, paths.root, catalogo)
    except TranscripcionesIncompletas as e:
        raise SystemExit(f"NO SE GENERA NADA: {e}") from e

    destino = Path(args.salida)
    destino.mkdir(parents=True, exist_ok=True)

    html = render(
        casos=[c.to_dict() for c in casos],
        practica=[c.to_dict() for c in practica],
        version=VERSION,
        clave_almacenamiento=CLAVE_ALMACENAMIENTO,
    )
    archivo = destino / "anotacion_e6.html"
    archivo.write_text(html, encoding="utf-8")

    # La correspondencia y el manifiesto van APARTE: si viajaran en el HTML, bastaría abrir el
    # archivo para saber qué configuración produjo cada respuesta.
    tabla = destino / "correspondencia.csv"
    with tabla.open("w", encoding="utf-8", newline="") as handle:
        escritor = csv.DictWriter(
            handle, fieldnames=["id_anonimo", "run_id", "transcript_path", "repeticion_de"]
        )
        escritor.writeheader()
        escritor.writerows(correspondencia)

    # Las huellas se calculan sobre los archivos ya escritos: identifican exactamente lo que
    # se entregó, que es lo que un tercero necesita para comprobar que revisó lo mismo.
    documento = manifiesto(len(casos), seed, umbrales, correspondencia)
    documento["huellas"] = {
        "anotacion_e6.html": sha256(archivo),
        "correspondencia.csv": sha256(tabla),
        "e6_sample_ciego.csv": sha256(csv_ciego),
    }
    manifiesto_ruta = destino / "manifiesto.json"
    manifiesto_ruta.write_text(
        json.dumps(documento, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _escribir_doc(documento)

    repetidos = [c for c in correspondencia if c["repeticion_de"]]
    print(f"casos ciegos:      {len(casos)}  (orden con semilla {seed})")
    print(
        f"  de ellos repetidos: {len(repetidos)}  "
        + ", ".join(f"{c['repeticion_de']}→{c['id_anonimo']}" for c in repetidos)
    )
    print(f"casos de práctica: {len(practica)}  (partición de desarrollo, no se exportan)")
    print(f"tamaño del HTML:   {archivo.stat().st_size / 1024:.0f} KB")
    print()
    print(f"  PARA QUIEN ANOTA -> {archivo}")
    print(f"  NO ENTREGAR      -> {tabla}")
    print(f"  procedencia      -> {manifiesto_ruta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
