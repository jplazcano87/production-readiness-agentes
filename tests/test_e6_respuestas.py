"""El archivo que se analiza es el que llegó, y es analizable.

La copia versionada de las respuestas es lo que produce las cifras del informe. Si alguien la
editara —arreglar una fila, quitar una respuesta rara, reexportarla desde Excel— el análisis
seguiría corriendo y nadie se enteraría. El acta de recepción registra la huella del archivo
recibido y esto comprueba que la copia sigue siendo esa, campo por campo.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

from e6_kappa_ciego import RESPUESTAS, leer_respuestas  # noqa: E402

ACTA = RAIZ / "data" / "annotation" / "e6_respuestas_recibidas.json"
CSV_RESPUESTAS = RAIZ / RESPUESTAS
IDS = [f"C{i:02d}" for i in range(1, 69)]


def acta() -> dict:
    return json.loads(ACTA.read_text(encoding="utf-8"))


def filas() -> list[dict[str, str]]:
    # `utf-8-sig`: el instrumento escribe el BOM para que Excel no destroce las tildes.
    crudo = CSV_RESPUESTAS.read_text(encoding="utf-8-sig")
    return list(csv.DictReader(crudo.splitlines()))


def test_la_copia_es_el_archivo_que_se_recibio():
    huella = hashlib.sha256(CSV_RESPUESTAS.read_bytes()).hexdigest()
    assert huella == acta()["sha256"], "la copia versionada no es la que registra el acta"
    assert acta()["archivo"] == RESPUESTAS


def test_el_archivo_trae_el_bom_y_se_lee_con_utf_8_sig():
    crudo = CSV_RESPUESTAS.read_bytes()
    assert crudo.startswith(b"\xef\xbb\xbf"), "el instrumento escribe el BOM; no se quita"
    # Leído sin `utf-8-sig`, la primera columna se llamaría «﻿id_anonimo» y no habría
    # forma de encontrarla por nombre.
    assert "﻿" not in crudo.decode("utf-8-sig")
    assert leer_respuestas(CSV_RESPUESTAS)[0]["id_anonimo"] == "C01"


def test_son_las_68_pantallas_sin_duplicados():
    ids = [f["id_anonimo"] for f in filas()]
    assert len(ids) == len(IDS) == acta()["n_filas"]
    assert ids == IDS, "faltan, sobran o están repetidos"


def test_las_dos_respuestas_son_binarias_en_todas():
    for fila in filas():
        assert fila["p1_opcion_no_cumple"] in ("0", "1"), fila
        assert fila["p2_le_sirve"] in ("0", "1"), fila


def test_todas_se_respondieron_con_el_instrumento_1_1():
    versiones = {f["version_instrumento"] for f in filas()}
    assert versiones == {acta()["version_instrumento"]} == {"1.1"}


def test_el_archivo_no_trae_datos_personales():
    """Lo único de texto libre es el comentario. Si trajera algo, habría que revisarlo a mano
    antes de versionarlo; aquí está vacío en las 68."""
    assert all(not f["comentario"].strip() for f in filas())
    assert set(filas()[0]) == {
        "id_anonimo",
        "p1_opcion_no_cumple",
        "p2_le_sirve",
        "comentario",
        "timestamp",
        "segundos_en_pantalla",
        "version_instrumento",
    }


def test_el_tiempo_total_del_acta_es_el_del_archivo():
    total = sum(float(f["segundos_en_pantalla"]) for f in filas())
    assert round(total, 1) == acta()["segundos_en_pantalla_total"]


def test_el_documento_del_instrumento_registra_lo_entregado_y_lo_recibido():
    doc = (RAIZ / "docs" / "E6_INSTRUMENTO.md").read_text(encoding="utf-8")
    entregado = RAIZ / "exports" / "e6_ciego" / "anotacion_e6.html"
    assert "versión **1.1**" in doc
    if entregado.is_file():  # pragma: no cover - `exports/` no se versiona
        assert hashlib.sha256(entregado.read_bytes()).hexdigest() in doc
    assert "## Respuestas recibidas" in doc
    assert acta()["sha256"] in doc
    assert acta()["fecha_recepcion"] in doc


# ------------------------------------------------- la tabla dice lo que dice el resultado

RESULTADO = RAIZ / "results" / "e6_blind.json"
TABLA = RAIZ / "tables" / "e6_agreement.md"


def test_las_tres_filas_a_ciegas_salen_del_resultado_y_no_de_la_mano():
    """La tabla se regenera con `e6_agreement.py`, así que las filas tienen que venir del
    JSON. Escritas a mano se perderían en la siguiente regeneración, en silencio."""
    ciego = json.loads(RESULTADO.read_text(encoding="utf-8"))
    tabla = TABLA.read_text(encoding="utf-8")
    assert "## Ronda a ciegas" in tabla
    for par in ciego["pares"]:
        referencia = par["par"].split(" vs ", 1)[1]
        m, k = par["matriz"], par["kappa_cohen"]
        # El par se escribe con la referencia primero, así que las dos celdas de desacuerdo se
        # cruzan respecto del JSON. Equivocarlas invertiría quién es más estricto.
        fila = (
            f"| {referencia} vs anotación a ciegas | {par['n']} | "
            f"{par['concordancia_simple']:.4f} | {k:.4f} | "
            f"{m['solo_el_segundo']} | {m['solo_el_primero']} |"
        )
        assert fila in tabla, fila


def test_el_resultado_a_ciegas_se_calculo_sobre_las_64_primeras_respuestas():
    ciego = json.loads(RESULTADO.read_text(encoding="utf-8"))
    assert ciego["n_respuestas"] == 68
    assert ciego["n_casos_unicos"] == 64  # las 4 repeticiones no cuentan dos veces
    assert ciego["version_instrumento"] == {"1.1": 68}
    assert ciego["metadata"]["api_mode"] == "none"


def test_el_exploratorio_se_declara_exploratorio():
    """Si un día alguien cita estas cifras como si decidieran algo, que al menos el archivo
    diga que no."""
    archivo = RAIZ / "results" / "e6_blind_exploratorio.json"
    datos = json.loads(archivo.read_text(encoding="utf-8"))
    assert datos["aviso"].startswith("EXPLORATORIO")
    assert datos["metadata"]["preinscrito"] is False
    assert datos["metadata"]["api_mode"] == "none"
    # Y no reescribe ningún desenlace: eso vive solo en el resultado preinscrito.
    assert "veredicto_de_las_reglas" not in datos


def test_las_ocho_que_solo_la_persona_aprueba_son_las_de_rob_bus_007_con_cte():
    """La frase del informe dice que son «las ocho ejecuciones de ROB-BUS-007 en que
    Code-Then-Execute niega productos que su búsqueda devolvió». Esto la fija: si una ronda
    futura la contradice, falla aquí y no en la lectura de alguien."""
    datos = json.loads(
        (RAIZ / "results" / "e6_blind_exploratorio.json").read_text(encoding="utf-8")
    )
    bloque = datos["solo_la_persona_aprueba"]
    assert bloque["n"] == 8
    assert bloque["case_id_distintos"] == ["ROB-BUS-007"]
    assert bloque["configuraciones"] == ["cte"]
    assert bloque["todas_con_la_tabla_completa"] is True
    for f in bloque["ejecuciones"]:
        # La búsqueda devolvió productos dentro del presupuesto y la respuesta no ofreció
        # ninguno: eso es lo que «niega productos que su búsqueda devolvió» quiere decir.
        assert len(f["dentro_del_presupuesto"]) == 5, f["id_anonimo"]
        assert f["recomendaciones_finales"] == [], f["id_anonimo"]
        assert f["no_estaban_en_la_tabla"] == [], f["id_anonimo"]
        assert "no encontramos" in f["lo_que_dice_el_agente"], f["id_anonimo"]
