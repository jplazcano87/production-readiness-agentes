"""Concordancia entre el evaluador de estado, el juez LLM y la anotación humana (tabla 7).

    python scripts/e6_agreement.py --solo-estado-juez   # sin esperar la anotación
    python scripts/e6_agreement.py                      # con la columna human_success completa

Lee `data/annotation/e6_sample.csv` y calcula, para cada par, la **concordancia simple** y la
**kappa de Cohen**. Las dos juntas y no una sola: con clases muy desbalanceadas —y aquí lo
están, porque casi todas las ejecuciones de E1 tienen éxito— la concordancia simple se acerca al
90 % por el solo hecho de que ambos digan «éxito» casi siempre. Kappa descuenta el acuerdo que
se habría producido por azar, y es la que dice si el acuerdo significa algo.

Mientras `human_success` esté vacía, solo el par estado–juez es calculable y los otros dos se
declaran pendientes en vez de rellenarse con nada.
"""

from __future__ import annotations

import argparse
import csv
import json
from itertools import combinations
from pathlib import Path
from typing import Any

from prf.infra import paths
from prf.infra.config import load_experiments, load_models
from prf.infra.results import build_metadata, write_result

ETIQUETAS = {
    "state_success": "evaluador de estado",
    "judge_success": "juez LLM",
    "human_success": "anotación humana",
}

# La ronda a ciegas vive en su propio resultado, con su propia regla de lectura fijada de
# antemano. Sus filas se añaden a esta tabla cuando ese archivo existe, en vez de escribirse a
# mano: regenerar la tabla no puede borrarlas.
RESULTADO_CIEGO = "e6_blind.json"
# En `e6_blind.json` el primero del par es siempre la anotación a ciegas. En la tabla el par se
# escribe al revés —referencia primero— para que se lea igual que las filas de arriba, así que
# las dos celdas de desacuerdo se intercambian con él.

# El CSV lo exporta `run_e6.py` en UTF-8 con comas, pero lo anota una persona, y una persona lo
# abre con una hoja de cálculo. Excel en macOS lo devuelve en Mac Roman y separado por `;`;
# Excel en Windows, en cp1252. Rechazar eso obligaría a arreglar el archivo a mano justo cuando
# ya está anotado, así que el lector se adapta en vez de exigir.
CODIFICACIONES = ("utf-8-sig", "mac_roman", "cp1252")
SEPARADORES = (",", ";", "\t")
ETIQUETAS_VALIDAS = {"0": 0, "1": 1, "0.0": 0, "1.0": 1, "no": 0, "si": 1, "sí": 1}

# Columnas que identifican al archivo. `judge_success` no está: la exportación a ciegas, que es
# la que se debe anotar, no la lleva.
COLUMNAS_MINIMAS = {"run_id", "human_success"}

# Letras no ASCII que el español de Chile usa de verdad. Sirve para desambiguar entre dos
# codificaciones de byte único, que nunca fallan al decodificar: `mac_roman` acepta los 256
# bytes, así que «la primera que no lance excepción» elige mal en silencio.
LETRAS_ESPANOLAS = set("áéíóúüñÁÉÍÓÚÜÑ")


def _rarezas(texto: str) -> int:
    """Cuántos caracteres caen donde el español no los pondría.

    Un byte alto que sigue a una minúscula está dentro de una palabra, y dentro de una palabra
    en español solo caben minúsculas acentuadas. Si al decodificar «recomendó» sale
    `recomendÛ` o `recomend—`, la codificación es la equivocada.

    Es una heurística y puede empatar; por eso la codificación elegida se declara en el JSON y
    se imprime al ejecutar, en vez de darse por supuesta.
    """
    return sum(
        1
        for anterior, c in zip(texto, texto[1:], strict=False)
        if not c.isascii() and anterior.islower() and not (c.islower() and c in LETRAS_ESPANOLAS)
    )


def _decodificar(ruta: Path) -> tuple[str, str]:
    """El texto del CSV y la codificación con la que se leyó.

    UTF-8 primero y estricto: es lo que exporta `run_e6.py`, y si valida no hay nada que
    adivinar. Solo cuando falla se elige entre las de byte único, y ahí no vale quedarse con la
    primera que no reviente, porque ninguna revienta.
    """
    crudo = ruta.read_bytes()
    try:
        return crudo.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        pass
    candidatas = [
        (_rarezas(crudo.decode(c, errors="replace")), i, c)
        for i, c in enumerate(CODIFICACIONES[1:])
    ]
    _, _, elegida = min(candidatas)
    return crudo.decode(elegida), elegida


def _separador(cabecera: str) -> str:
    """El separador con el que la cabecera trae las columnas que identifican al archivo."""
    for separador in SEPARADORES:
        if COLUMNAS_MINIMAS <= set(cabecera.strip().split(separador)):
            return separador
    raise SystemExit(
        "la cabecera del CSV no trae las columnas esperadas con ninguno de los separadores "
        f"{SEPARADORES}: {cabecera.strip()[:120]}"
    )


def leer_csv(ruta: Path) -> tuple[list[dict[str, str]], dict[str, str]]:
    """Las filas anotadas, venga el archivo como venga de la hoja de cálculo.

    Devuelve también cómo se leyó, para que el JSON lo declare: si la anotación llegó en otra
    codificación, eso es parte de la procedencia del dato y no un detalle de implementación.
    """
    texto, codificacion = _decodificar(ruta)
    lineas = texto.splitlines()
    if not lineas:
        raise SystemExit(f"{ruta} está vacío")
    separador = _separador(lineas[0])
    filas = list(csv.DictReader(lineas, delimiter=separador))
    columnas_del_juez = sorted(c for c in (filas[0] if filas else {}) if c.startswith("judge"))
    return filas, {
        "codificacion": codificacion,
        "separador": separador,
        # Si el archivo que se anotó traía el veredicto del juez, la anotación no es
        # independiente de él, y el par juez–humano deja de medir lo que dice medir.
        "columnas_del_juez_visibles": columnas_del_juez,
        "anotacion_a_ciegas": not columnas_del_juez,
    }


def etiqueta(valor: str | None) -> int | None:
    """La anotación como 0/1, o `None` si la celda está vacía.

    Una celda con algo que no es una etiqueta **no** se trata como vacía: contarla como «sin
    anotar» escondería un error de tecleo dentro de un `n` más chico, y la concordancia saldría
    calculada sobre una muestra distinta de la que se cree.
    """
    limpio = str(valor if valor is not None else "").strip().lower()
    if not limpio:
        return None
    if limpio not in ETIQUETAS_VALIDAS:
        raise SystemExit(
            f"valor de anotación no reconocido: {valor!r}. Usa 1 (éxito) o 0 (fallo), "
            "o deja la celda vacía si aún no la anotaste."
        )
    return ETIQUETAS_VALIDAS[limpio]


def kappa_cohen(a: list[int], b: list[int]) -> float | None:
    """Kappa de Cohen para dos anotadores binarios.

    Devuelve `None` cuando no está definida: si ambos anotadores usaron una sola clase, el
    acuerdo esperado por azar es 1 y la fórmula divide por cero. Reportar 0 en ese caso diría
    «no hay acuerdo» cuando lo que pasa es que la métrica no aplica.
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
    """Los cuatro conteos, que son lo que permite leer un desacuerdo por su lado."""
    return {
        "ambos_exito": sum(1 for x, y in zip(a, b, strict=True) if x == 1 and y == 1),
        "ambos_fallo": sum(1 for x, y in zip(a, b, strict=True) if x == 0 and y == 0),
        "primero_si_segundo_no": sum(1 for x, y in zip(a, b, strict=True) if x == 1 and y == 0),
        "primero_no_segundo_si": sum(1 for x, y in zip(a, b, strict=True) if x == 0 and y == 1),
    }


def par(filas: list[dict[str, str]], izq: str, der: str) -> dict[str, Any]:
    """Concordancia de un par sobre las filas donde ambas columnas están completas."""
    pares = [
        (etiqueta(f.get(izq)), etiqueta(f.get(der)))
        for f in filas
        if etiqueta(f.get(izq)) is not None and etiqueta(f.get(der)) is not None
    ]
    if not pares:
        return {
            "par": f"{ETIQUETAS[izq]} vs {ETIQUETAS[der]}",
            "n": 0,
            "estado": "pendiente",
            "motivo": "falta completar alguna de las dos columnas",
        }
    a = [x for x, _ in pares]
    b = [y for _, y in pares]
    acuerdos = sum(1 for x, y in zip(a, b, strict=True) if x == y)
    return {
        "par": f"{ETIQUETAS[izq]} vs {ETIQUETAS[der]}",
        "n": len(pares),
        "estado": "calculado",
        "concordancia_simple": round(acuerdos / len(pares), 4),
        "kappa_cohen": kappa_cohen(a, b),
        "matriz": matriz(a, b),
    }


def _nota_de_procedencia(resultados: list[dict[str, Any]], formato: dict[str, Any]) -> list[str]:
    """Cómo se recogió la anotación humana, cuando eso condiciona cómo se lee la tabla.

    Reporta un hecho comprobable —qué columnas traía el archivo que se anotó— y no un juicio
    sobre la anotación, que este programa no puede emitir: si quien anotó revisó cada
    transcripción o se dejó llevar por la columna de al lado no está en el archivo. Lo que sí
    está es que la independencia entre anotador y juez no se puede **verificar** desde aquí, y
    esa es la salvedad que la tabla debe llevar junto a la cifra.
    """
    juez_humano = next(
        (r for r in resultados if r["par"].startswith(f"{ETIQUETAS['judge_success']} vs")), None
    )
    if not juez_humano or juez_humano["estado"] != "calculado":
        return []
    if formato.get("anotacion_a_ciegas", True):
        return []
    visibles = ", ".join(f"`{c}`" for c in formato["columnas_del_juez_visibles"])
    return [
        "",
        "> ### Cómo se recogió esta anotación",
        ">",
        f"> El archivo que se anotó traía {visibles} además de la columna por rellenar, así "
        "que el veredicto del juez estaba a la vista mientras se anotaba. **La independencia "
        "entre anotador y juez no es verificable desde el archivo**, con independencia de "
        "cómo se anotara en realidad.",
        ">",
        "> `run_e6.py` exporta también `data/annotation/e6_sample_ciego.csv`, sin las columnas "
        "del juez ni la del evaluador de estado. Una ronda sobre ese archivo produciría un "
        "acuerdo verificable sin depender del testimonio de quien anota.",
    ]


def tabla(
    resultados: list[dict[str, Any]], n_muestra: int, formato: dict[str, Any] | None = None
) -> str:
    """La tabla de concordancia entre los tres criterios, con sus matrices."""
    lineas = [
        "# Concordancia entre el evaluador de estado, el juez LLM y la anotación humana",
        "",
        f"Muestra de **{n_muestra} ejecuciones** de E1: todas las fallidas más 40 exitosas "
        "estratificadas por configuración y tipo.",
        "",
        "La **kappa de Cohen** es la columna que importa. La concordancia simple sube sola "
        "cuando una clase domina —aquí el éxito— porque premia el acuerdo que se obtendría "
        "contestando siempre lo mismo; kappa descuenta ese acuerdo por azar, y por eso queda "
        "bastante por debajo. Cuando sale `—`, ambos anotadores usaron una sola clase y la "
        "métrica no está definida: reportar 0 diría «no hay acuerdo» cuando lo que pasa es que "
        "no aplica.",
        "",
        "| Par | N | Concordancia simple | Kappa de Cohen |",
        "|---|---:|---:|---:|",
    ]
    for r in resultados:
        if r["estado"] != "calculado":
            lineas.append(f"| {r['par']} | — | pendiente | pendiente |")
            continue
        k = r["kappa_cohen"]
        lineas.append(
            f"| {r['par']} | {r['n']} | {r['concordancia_simple']:.4f} | "
            f"{'—' if k is None else f'{k:.4f}'} |"
        )

    calculados = [r for r in resultados if r["estado"] == "calculado"]
    if calculados:
        lineas += [
            "",
            "## Dónde discrepan",
            "",
            "| Par | Ambos éxito | Ambos fallo | Solo el primero | Solo el segundo |",
            "|---|---:|---:|---:|---:|",
        ]
        for r in calculados:
            m = r["matriz"]
            lineas.append(
                f"| {r['par']} | {m['ambos_exito']} | {m['ambos_fallo']} "
                f"| {m['primero_si_segundo_no']} | {m['primero_no_segundo_si']} |"
            )
    pendientes = [r for r in resultados if r["estado"] != "calculado"]
    if pendientes:
        lineas += [
            "",
            f"**{len(pendientes)} de 3 pares están pendientes** de que se complete la columna "
            "`human_success` en `data/annotation/e6_sample.csv`. El CSV se exporta con esa "
            "columna vacía a propósito: ver el veredicto del juez antes de anotar sesgaría la "
            "anotación.",
        ]
    lineas += _nota_de_procedencia(resultados, formato or {})
    # Después de la nota a propósito: la nota termina diciendo que haría falta una ronda a
    # ciegas, y esta sección es esa ronda.
    lineas += _seccion_ciega()
    return "\n".join(lineas) + "\n"


def _seccion_ciega() -> list[str]:
    """Las tres filas de la ronda a ciegas, si ya se analizó.

    Es la ronda que esta tabla pedía al final: un acuerdo verificable, con una persona ajena
    que no vio el veredicto de nadie. Se lee de `results/e6_blind.json`, que es donde se
    aplicó la regla fijada antes de recibir los datos.
    """
    archivo = paths.results / RESULTADO_CIEGO
    if not archivo.is_file():
        return []
    ciego = json.loads(archivo.read_text(encoding="utf-8"))
    lineas = [
        "",
        "## Ronda a ciegas: una persona ajena, sin ver ningún veredicto",
        "",
        f"La misma muestra, anotada por una persona que no vio configuración, tipo, `run_id`, "
        f"`case_id` ni veredicto alguno ({ciego['n_casos_unicos']} ejecuciones; "
        f"{ciego['n_respuestas']} pantallas con las 4 repeticiones del test-retest, de las que "
        "se usa la primera respuesta). La columna comparada es `p2_le_sirve`: si la respuesta "
        "le sirve al cliente. La regla de lectura está fijada en "
        "[`E6_REGLA_DE_INTERPRETACION.md`](../docs/E6_REGLA_DE_INTERPRETACION.md), escrita "
        "**antes** de recibir el archivo, y el resultado completo en "
        "[`results/e6_blind.json`](../results/e6_blind.json).",
        "",
        "| Par | N | Concordancia simple | Kappa de Cohen | Solo el primero aprueba | "
        "Solo el segundo aprueba |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for par in ciego["pares"]:
        if par["estado"] != "calculado":
            continue
        referencia = par["par"].split(" vs ", 1)[1]
        m, k = par["matriz"], par["kappa_cohen"]
        lineas.append(
            f"| {referencia} vs anotación a ciegas | {par['n']} | "
            f"{par['concordancia_simple']:.4f} | {'—' if k is None else f'{k:.4f}'} | "
            # El par se escribe con la referencia primero, así que las dos celdas se cruzan.
            f"{m['solo_el_segundo']} | {m['solo_el_primero']} |"
        )
    return lineas


def main(argv: list[str] | None = None) -> int:
    """Calcula la concordancia entre los tres criterios y escribe el JSON y la tabla."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv", default=None, help="Archivo anotado del que se leen las columnas de acuerdo."
    )
    parser.add_argument(
        "--solo-estado-juez",
        action="store_true",
        help="No exige la anotación humana: calcula el único par disponible sin ella.",
    )
    parser.add_argument(
        "--salida", default="e6_judge_agreement", help="Nombre del JSON en results/, sin extensión."
    )
    args = parser.parse_args(argv)

    ruta = Path(args.csv).resolve() if args.csv else paths.annotation / "e6_sample.csv"
    if not ruta.is_file():
        raise SystemExit(f"falta {ruta}: ejecuta antes scripts/run_e6.py")
    filas, formato = leer_csv(ruta)
    if (formato["codificacion"], formato["separador"]) != ("utf-8", ","):
        print(
            f"Aviso: el CSV venía en {formato['codificacion']} separado por "
            f"{formato['separador']!r} —seguramente de una hoja de cálculo—. Se lee igual y "
            "queda declarado en el JSON."
        )

    pares = [
        par(filas, izq, der)
        for izq, der in combinations(("state_success", "judge_success", "human_success"), 2)
    ]
    pendientes = [p for p in pares if p["estado"] != "calculado"]
    if pendientes and not args.solo_estado_juez:
        print(
            f"Aviso: {len(pendientes)} de 3 pares pendientes por falta de `human_success`. "
            "Se escriben igual, marcados como pendientes."
        )

    payload = {
        "n_muestra": len(filas),
        "pares": pares,
        "completo": not pendientes,
        # `--csv` admite una ruta de fuera del repo: entonces se declara tal cual.
        "csv": str(ruta.relative_to(paths.root) if ruta.is_relative_to(paths.root) else ruta),
        "formato_del_csv": formato,
    }
    experimentos = load_experiments()
    models = load_models()
    metadata = build_metadata(
        seed=experimentos["seed_global"],
        model={"judge": models.role("judge").id},
        config="e6",
        corpus_version=experimentos["corpus_version"],
        api_mode="none",
        extra={
            "n_muestra": len(filas),
            "pares_pendientes": [p["par"] for p in pendientes],
            "formato_del_csv": formato,
        },
    )
    archivo = write_result(args.salida, payload, metadata)

    destino = paths.tables / "e6_agreement.md"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(tabla(pares, len(filas), formato), encoding="utf-8")

    if not formato["anotacion_a_ciegas"]:
        print(
            "Aviso: el archivo anotado traía "
            + ", ".join(formato["columnas_del_juez_visibles"])
            + " a la vista. Los pares con anotación humana NO son independientes del juez; "
            "la tabla lo declara."
        )

    for p in pares:
        if p["estado"] == "calculado":
            k = p["kappa_cohen"]
            print(
                f"  {p['par']:<45} n={p['n']:<4} concordancia={p['concordancia_simple']:.4f} "
                f"kappa={'—' if k is None else f'{k:.4f}'}"
            )
        else:
            print(f"  {p['par']:<45} pendiente")
    print(f"\nescrito en {archivo} y {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
