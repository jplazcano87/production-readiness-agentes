"""Juez LLM y concordancia: lo que E6 mide y lo que no puede fingir."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

from prf.eval.judge import SISTEMA_JUEZ, parsear, prompt

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from e6_agreement import kappa_cohen, matriz, par  # noqa: E402
from run_e6 import muestrear  # noqa: E402

# ------------------------------------------------------------------ el juez


def test_una_salida_que_no_es_json_no_se_adivina():
    # Adivinar el veredicto a partir de texto libre convertiría un desacuerdo entre juez y
    # evaluador en un artefacto del parser, que es lo que E6 debe poder descartar.
    v = parsear("Creo que sí, el asistente lo resolvió bien.")

    assert v.exito is None and not v.valido


def test_un_exito_que_no_es_booleano_se_rechaza():
    assert parsear('{"exito": "sí", "razon": "x"}').valido is False


def test_el_json_se_extrae_aunque_venga_con_texto_alrededor():
    v = parsear('Aquí va: {"exito": false, "razon": "no recomendó nada"} — listo')

    assert v.exito is False
    assert "no recomendó" in v.razon


def test_la_rubrica_ordena_ignorar_los_marcadores_del_andamiaje():
    # Si el juez puntuara por el marcador, mediría el arnés y no la tarea.
    assert "<<rec:ID>>" in SISTEMA_JUEZ
    assert "ignóralos" in SISTEMA_JUEZ


def test_el_prompt_no_le_dice_al_juez_lo_que_decidio_el_evaluador(caso_e1):
    # Si lo supiera, el acuerdo mediría su docilidad y no su criterio.
    texto = prompt(caso_e1)

    assert "evaluate_state" not in texto
    assert "success" not in texto.lower()


def test_el_prompt_lleva_la_conversacion_y_el_objetivo(caso_e1):
    texto = prompt(caso_e1)

    assert caso_e1["intent"][:40] in texto
    assert "Recomendaciones mínimas" in texto


# ------------------------------------------------------------------ muestreo


def _obs(run_id, config, tipo, exito):
    return {
        "run_id": run_id,
        "case_id": run_id.split("__")[0],
        "config": config,
        "tipo": tipo,
        "exito": exito,
    }


def test_la_muestra_lleva_todas_las_fallidas():
    obs = [_obs(f"C{i}__none__0", "none", "busqueda", i % 10 != 0) for i in range(100)]
    fallidas = [o for o in obs if not o["exito"]]

    muestra, reparto = muestrear(obs, n_exitosas=20, seed=1)

    assert reparto["n_fallidas"] == len(fallidas)
    assert {o["run_id"] for o in fallidas} <= {o["run_id"] for o in muestra}


def test_las_exitosas_se_reparten_entre_configuraciones_y_tipos():
    obs = [
        _obs(f"C{i}__{c}__0", c, t, True)
        for i, (c, t) in enumerate(
            [(c, t) for c in ("none", "cte") for t in ("busqueda", "comparacion")] * 20
        )
    ]
    _, reparto = muestrear(obs, n_exitosas=20, seed=1)

    assert len(reparto["exitosas_por_celda"]) == 4
    assert sum(reparto["exitosas_por_celda"].values()) == 20


def test_el_muestreo_es_reproducible():
    obs = [_obs(f"C{i}__none__0", "none", "busqueda", True) for i in range(50)]

    a, _ = muestrear(obs, n_exitosas=10, seed=7)
    b, _ = muestrear(obs, n_exitosas=10, seed=7)

    assert [o["run_id"] for o in a] == [o["run_id"] for o in b]


# ------------------------------------------------------------- concordancia


def test_kappa_no_esta_definida_si_ambos_usan_una_sola_clase():
    # Reportar 0 diría «no hay acuerdo» cuando lo que pasa es que la métrica no aplica.
    assert kappa_cohen([1] * 10, [1] * 10) is None


def test_kappa_es_1_con_acuerdo_perfecto_y_dos_clases():
    assert kappa_cohen([1, 0, 1, 0], [1, 0, 1, 0]) == 1.0


def test_kappa_castiga_el_acuerdo_por_azar():
    # 8 de 10 de acuerdo, pero con clases muy desbalanceadas kappa queda muy por debajo.
    a = [1] * 9 + [0]
    b = [1] * 8 + [0, 1]

    assert kappa_cohen(a, b) < 0.8


def test_un_par_sin_la_columna_humana_queda_pendiente():
    filas = [{"state_success": "1", "judge_success": "1", "human_success": ""}]

    assert par(filas, "state_success", "human_success")["estado"] == "pendiente"


def test_la_matriz_separa_los_dos_sentidos_del_desacuerdo():
    m = matriz([1, 0, 1], [0, 1, 1])

    assert m == {
        "ambos_exito": 1,
        "ambos_fallo": 0,
        "primero_si_segundo_no": 1,
        "primero_no_segundo_si": 1,
    }


def test_el_csv_exportado_deja_la_columna_humana_vacia(tmp_path):
    # Ver el veredicto del juez antes de anotar sesgaría la anotación.
    from run_e6 import COLUMNAS

    ruta = tmp_path / "m.csv"
    with ruta.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=list(COLUMNAS))
        w.writeheader()
        w.writerow(dict.fromkeys(COLUMNAS, ""))

    with ruta.open(encoding="utf-8") as h:
        filas = list(csv.DictReader(h))

    assert "human_success" in COLUMNAS
    assert filas[0]["human_success"] == ""


@pytest.fixture
def caso_e1():
    return {
        "intent": "Busco un notebook para editar video, hasta $1.500.000 y 32 GB de RAM.",
        "target_state": {
            "min_recomendaciones": 1,
            "constraints": {
                "categoria": "notebooks",
                "presupuesto_max_clp": 1500000,
                "atributos": {"ram_gb": {"min": 32}},
                "presupuesto_min_clp": None,
            },
            "must_include": [],
            "must_exclude": ["P0006"],
            "must_compare": [],
            "forbidden_tools": ["apply_discount"],
        },
        "ejecucion": {
            "transcripcion": [
                {"rol": "usuario", "texto": "Busco un notebook para editar video."},
                {"rol": "asistente", "texto": "Te recomiendo el Aurora <<rec:P001>>."},
            ]
        },
    }


# ------------------------------- lectura del CSV anotado y detección de anclaje (E6, tabla 7)


def _escribir(ruta, filas, *, separador=",", codificacion="utf-8", columnas=None):
    columnas = columnas or list(filas[0])
    lineas = [separador.join(columnas)]
    lineas += [separador.join(str(f[c]) for c in columnas) for f in filas]
    ruta.write_bytes(("\n".join(lineas) + "\n").encode(codificacion))
    return ruta


FILA = {
    "run_id": "ROB-BUS-001__cte__1",
    "case_id": "ROB-BUS-001",
    "config": "cte",
    "tipo": "busqueda",
    "transcript_path": "results/runs_e1/x.json",
    "state_success": 1,
    "judge_success": 1,
    "human_success": 1,
    "judge_reason": "recomendó al menos un notebook",
}


@pytest.mark.parametrize(
    ("codificacion", "separador"),
    [("utf-8", ","), ("mac_roman", ";"), ("cp1252", ";"), ("utf-8-sig", ",")],
)
def test_el_csv_se_lee_venga_como_venga_de_la_hoja_de_calculo(tmp_path, codificacion, separador):
    # Excel en macOS devuelve Mac Roman con `;`; en Windows, cp1252. Exigir UTF-8 con comas
    # obligaría a arreglar el archivo a mano justo cuando ya está anotado.
    from e6_agreement import leer_csv

    ruta = _escribir(tmp_path / "e6.csv", [FILA], separador=separador, codificacion=codificacion)
    filas, formato = leer_csv(ruta)
    assert len(filas) == 1
    assert filas[0]["judge_reason"] == "recomendó al menos un notebook"
    assert formato["separador"] == separador


def test_una_celda_que_no_es_etiqueta_no_se_toma_por_vacia():
    # Contarla como «sin anotar» escondería el error dentro de un n más chico, y la
    # concordancia saldría calculada sobre una muestra distinta de la que se cree.
    from e6_agreement import etiqueta

    assert etiqueta("") is None and etiqueta(None) is None
    assert etiqueta("1") == 1 and etiqueta(" 0 ") == 0 and etiqueta("Sí") == 1
    with pytest.raises(SystemExit):
        etiqueta("tal vez")


def test_se_detecta_que_la_anotacion_no_fue_a_ciegas(tmp_path):
    from e6_agreement import leer_csv

    _, con_juez = leer_csv(_escribir(tmp_path / "con.csv", [FILA]))
    assert con_juez["anotacion_a_ciegas"] is False
    assert con_juez["columnas_del_juez_visibles"] == ["judge_reason", "judge_success"]

    ciega = {k: v for k, v in FILA.items() if not k.startswith("judge")}
    _, sin_juez = leer_csv(_escribir(tmp_path / "sin.csv", [ciega]))
    assert sin_juez["anotacion_a_ciegas"] is True
    assert sin_juez["columnas_del_juez_visibles"] == []


def test_la_tabla_declara_como_se_recogio_la_anotacion():
    from e6_agreement import par, tabla

    filas = [dict(FILA, run_id=f"r{i}") for i in range(10)]
    pares = [
        par(filas, "state_success", "judge_success"),
        par(filas, "state_success", "human_success"),
        par(filas, "judge_success", "human_success"),
    ]
    con_juez_visible = tabla(
        pares, 10, {"anotacion_a_ciegas": False, "columnas_del_juez_visibles": ["judge_success"]}
    )
    # Declara el hecho comprobable —qué traía el archivo— sin juzgar la anotación, que es lo
    # que este programa no puede saber.
    assert "no es verificable desde el archivo" in con_juez_visible
    assert "e6_sample_ciego.csv" in con_juez_visible

    ciega = tabla(pares, 10, {"anotacion_a_ciegas": True, "columnas_del_juez_visibles": []})
    assert "Cómo se recogió esta anotación" not in ciega


def test_run_e6_exporta_tambien_la_muestra_a_ciegas():
    # La exportación a ciegas va siempre, no bajo bandera: la bandera se olvida, y lo que se
    # pierde al olvidarla es el único par que E6 existe para medir.
    from run_e6 import COLUMNAS, COLUMNAS_A_CIEGAS

    assert "human_success" in COLUMNAS_A_CIEGAS
    assert not [c for c in COLUMNAS_A_CIEGAS if c.startswith("judge")]
    assert "state_success" not in COLUMNAS_A_CIEGAS
    assert set(COLUMNAS_A_CIEGAS) < set(COLUMNAS)
