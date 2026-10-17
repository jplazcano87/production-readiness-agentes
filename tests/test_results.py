"""Metadatos obligatorios y escritura de los JSON canónicos de `results/`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prf.agent import AGENT_VERSION
from prf.env.evaluator import EVALUATOR_VERSION
from prf.infra.results import CAMPOS_METADATA, build_metadata, read_result, write_result


def test_metadata_incluye_los_siete_campos_obligatorios():
    metadata = build_metadata(
        seed=20260906,
        model="claude-sonnet-4-6",
        config="none",
        corpus_version="v1.0",
        api_mode="batch",
        batch_ids=["msgbatch_1"],
    )

    assert set(CAMPOS_METADATA) <= set(metadata)


def test_metadata_admite_varios_modelos_y_campos_extra():
    metadata = build_metadata(
        seed=1,
        model={"agent": "claude-sonnet-4-6", "quarantine": "claude-haiku-4-5-20251001"},
        config="dual_llm",
        corpus_version="v1.0",
        api_mode="realtime",
        extra={"n_runs": 8, "prompt_caching": True},
    )

    assert metadata["model"]["quarantine"] == "claude-haiku-4-5-20251001"
    assert metadata["n_runs"] == 8


def test_corpus_hash_es_none_mientras_no_exista_el_manifest():
    # El corpus se congela en la etapa 2; antes de eso el hash no existe todavía.
    metadata = build_metadata(
        seed=1, model="m", config="none", corpus_version="v0.0-inexistente", api_mode="none"
    )

    assert metadata["corpus_hash"] is None


def test_timestamp_es_utc():
    metadata = build_metadata(
        seed=1, model="m", config="none", corpus_version="v1.0", api_mode="realtime"
    )

    assert metadata["timestamp"].endswith("+00:00")


def test_write_result_escribe_json_utf8_con_metadata(tmp_path):
    metadata = build_metadata(
        seed=20260906,
        model="claude-sonnet-4-6",
        config="none",
        corpus_version="v1.0",
        api_mode="batch",
        batch_ids=["msgbatch_abc"],
    )

    archivo = write_result(
        "e1_baseline",
        {"pass_k": {"1": 0.87}, "nota": "acentuación en español"},
        metadata,
        directorio=tmp_path,
    )

    assert archivo.name == "e1_baseline.json"
    contenido = json.loads(archivo.read_text(encoding="utf-8"))
    assert contenido["metadata"]["seed"] == 20260906
    assert contenido["pass_k"]["1"] == 0.87
    assert "acentuación" in archivo.read_text(encoding="utf-8")  # sin escapes \u


def test_write_result_rechaza_metadata_incompleta(tmp_path):
    with pytest.raises(ValueError, match="corpus_hash"):
        write_result("x", {}, {"seed": 1}, directorio=tmp_path)


def test_read_result_recupera_lo_escrito(tmp_path):
    metadata = build_metadata(
        seed=7, model="m", config="cte", corpus_version="v1.0", api_mode="realtime_concurrente"
    )
    write_result("e5_verdict_cte", {"veredicto": "NO-GO"}, metadata, directorio=tmp_path)

    datos = read_result("e5_verdict_cte", directorio=tmp_path)

    assert datos["veredicto"] == "NO-GO"
    assert datos["metadata"]["config"] == "cte"


# ----------------------------------------------------------------- api_mode


def test_api_mode_es_obligatorio():
    # La vía por la que se llamó a la API cambia el costo y la latencia: un resultado que
    # no la declara no es comparable con otro.
    with pytest.raises(TypeError):
        build_metadata(seed=1, model="m", config="none", corpus_version="v1.0")


def test_api_mode_desconocido_se_rechaza():
    with pytest.raises(ValueError, match="api_mode desconocido"):
        build_metadata(
            seed=1, model="m", config="none", corpus_version="v1.0", api_mode="telepatia"
        )


def test_el_modo_batch_registra_los_batch_id():
    metadata = build_metadata(
        seed=1,
        model="m",
        config="none",
        corpus_version="v1.0",
        api_mode="batch",
        batch_ids=["msgbatch_1", "msgbatch_2"],
    )

    assert metadata["batch_ids"] == ["msgbatch_1", "msgbatch_2"]


def test_un_modo_que_no_es_batch_no_puede_declarar_batch_id():
    with pytest.raises(ValueError, match="batch"):
        build_metadata(
            seed=1,
            model="m",
            config="none",
            corpus_version="v1.0",
            api_mode="realtime",
            batch_ids=["msgbatch_1"],
        )


def test_write_result_exige_api_mode(tmp_path):
    incompleta = {
        "seed": 1,
        "corpus_version": "v1.0",
        "corpus_hash": None,
        "model": "m",
        "config": "none",
        "timestamp": "2026-09-07T00:00:00+00:00",
        "git_commit": None,
    }

    with pytest.raises(ValueError, match="api_mode"):
        write_result("x", {}, incompleta, directorio=tmp_path)


# ------------------------------------------------------------- agent_version


def test_la_version_del_agente_queda_en_los_metadatos():
    # Entre las cuatro corridas de E1 cambió el agente sin que el JSON lo dijera.
    metadata = build_metadata(
        seed=1, model="m", config="none", corpus_version="v1.0", api_mode="none"
    )

    assert metadata["agent_version"] == AGENT_VERSION


def test_la_version_del_evaluador_va_aparte_de_la_del_agente(tmp_path):
    # Entre las corridas 3 y 4 de E1 cambió el evaluador sin cambiar el agente
    # conversacional: declarar solo una de las dos no basta para comparar resultados.
    metadata = build_metadata(
        seed=1, model="m", config="none", corpus_version="v1.0", api_mode="none"
    )

    assert metadata["evaluator_version"] == EVALUATOR_VERSION

    del metadata["evaluator_version"]
    with pytest.raises(ValueError, match="evaluator_version"):
        write_result("x", {"a": 1}, metadata=metadata, directorio=tmp_path)


def test_un_resultado_sin_version_de_agente_no_se_escribe(tmp_path):
    metadata = build_metadata(
        seed=1, model="m", config="none", corpus_version="v1.0", api_mode="none"
    )
    del metadata["agent_version"]

    with pytest.raises(ValueError, match="agent_version"):
        write_result("x", {"a": 1}, metadata=metadata, directorio=tmp_path)


# --------------------------------------- la calibración de los ataques, solo en desarrollo


def test_las_rondas_de_calibracion_no_tocan_la_particion_de_prueba():
    """La afirmación que estos tres archivos sostienen: la fuerza de los ataques se ajustó sin
    ejecutar nunca la partición de prueba. Si una ronda trae un caso de prueba, la afirmación
    es falsa y hay que decirlo, no corregir el archivo."""
    raiz = Path(__file__).resolve().parents[1]
    prueba = set(
        (raiz / "data" / "splits" / "v1.4" / "test.txt").read_text(encoding="utf-8").split()
    )
    desarrollo = set(
        (raiz / "data" / "splits" / "v1.4" / "dev.txt").read_text(encoding="utf-8").split()
    )

    for ronda in (1, 2, 3):
        datos = json.loads((raiz / "results" / f"e2_cal_r{ronda}.json").read_text(encoding="utf-8"))
        casos = {o["case_id"] for o in datos["observaciones"]}
        assert casos <= desarrollo, (ronda, sorted(casos - desarrollo))
        assert not casos & prueba, (ronda, sorted(casos & prueba))
        assert datos["n_casos"] == len(casos) == 30, (ronda, len(casos))
        assert set(datos["configs"]) == {"none"}, (ronda, datos["configs"])
        # El corpus con que corrieron era de trabajo, y por eso no se publica.
        assert datos["metadata"]["corpus_version"] == "v1.2-dev", ronda


def test_las_rondas_de_calibracion_estan_publicadas_y_con_huella():
    raiz = Path(__file__).resolve().parents[1]
    manifiesto = json.loads(
        (raiz / "docs" / "MANIFIESTO_ARTEFACTOS.json").read_text(encoding="utf-8")
    )
    for ronda in (1, 2, 3):
        rel = f"results/e2_cal_r{ronda}.json"
        assert (raiz / rel).is_file(), rel
        assert rel in manifiesto["artefactos"], rel


def _tokens_de(transcripcion: Path) -> dict:
    ejecucion = json.loads(transcripcion.read_text(encoding="utf-8"))["ejecucion"]
    return {
        k: ejecucion[k]
        for k in ("input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens")
    }


def test_las_rutas_que_declaran_las_rondas_llevan_a_la_compuerta_y_no_a_ellas():
    """El aviso de `docs/PROCEDENCIA.md`, convertido en prueba.

    Las tres rondas y la compuerta del modelo pequeño declaran las **mismas** 60 rutas, porque
    el arnés de entonces no usaba un directorio por corrida. Lo que hay en ellas es la
    compuerta. Los resultados están congelados, así que esto no se arregla: se fija, para que
    nadie lea esas transcripciones como si fueran de la calibración.
    """
    raiz = Path(__file__).resolve().parents[1]
    compuerta = json.loads((raiz / "results" / "e2_compuerta_haiku.json").read_text("utf-8"))
    observaciones = {o["run_id"]: o for o in compuerta["observaciones"]}
    declaradas = {o["transcripcion"] for o in compuerta["observaciones"]}
    assert len(declaradas) == 60

    for ronda in (1, 2, 3):
        datos = json.loads((raiz / "results" / f"e2_cal_r{ronda}.json").read_text("utf-8"))
        assert {o["transcripcion"] for o in datos["observaciones"]} == declaradas, ronda

    coincide_con_la_compuerta = 0
    for ruta in declaradas:
        archivo = raiz / ruta
        assert archivo.is_file(), ruta
        datos = json.loads(archivo.read_text(encoding="utf-8"))
        observacion = observaciones[datos["run_id"]]
        assert _tokens_de(archivo) == observacion["tokens"], ruta
        assert datos["ataque"]["exitoso"] == observacion["ataque_exitoso"], ruta
        coincide_con_la_compuerta += 1
    assert coincide_con_la_compuerta == 60

    # Y no son de ninguna ronda: los éxitos no cuadran con ninguna de las tres.
    exitos_en_disco = sum(
        json.loads((raiz / ruta).read_text(encoding="utf-8"))["ataque"]["exitoso"]
        for ruta in declaradas
    )
    assert exitos_en_disco == 12
    for ronda in (1, 2, 3):
        datos = json.loads((raiz / "results" / f"e2_cal_r{ronda}.json").read_text("utf-8"))
        exitos = sum(o["ataque_exitoso"] for o in datos["observaciones"])
        assert exitos != exitos_en_disco, (ronda, exitos)


def test_la_ejecucion_de_e2_que_sobrevivio_al_piloto_esta_publicada():
    """`SEG-BEN-040__cte__2` es la única de las 26 sin ruta declarada cuyo archivo sigue siendo
    el de la corrida con Sonnet: el piloto escribía solo el sufijo `__0`."""
    raiz = Path(__file__).resolve().parents[1]
    e2 = json.loads((raiz / "results" / "e2_security.json").read_text(encoding="utf-8"))
    sin_ruta = [o for o in e2["observaciones"] if not o.get("transcripcion")]
    assert len(sin_ruta) == 26
    assert len(e2["observaciones"]) == 1176

    archivo = raiz / "results" / "runs_e2" / "SEG-BEN-040__cte__2.json"
    assert archivo.is_file()
    observacion = next(o for o in sin_ruta if o["run_id"] == "SEG-BEN-040__cte__2")
    datos = json.loads(archivo.read_text(encoding="utf-8"))
    assert _tokens_de(archivo) == observacion["tokens"]
    assert datos["config"] == observacion["config"] == "cte"
    assert datos["tipo"] == observacion["tipo"] == "benigno"
    assert datos["ataque"]["exitoso"] == observacion["ataque_exitoso"] is None
    assert datos["evaluacion"]["success"] is observacion["utilidad_benigna"] is True
    assert len(datos["ejecucion"]["llamadas"]) == observacion["n_llamadas"]


# El cambio que corrigió los dos defectos que el piloto destapó, en UTC. Se escribe aquí porque
# el repositorio público no lleva el historial donde está ese commit: lo que separa al piloto de
# la medición es el instante, y así se puede comprobar sin git.
CORRECCION_DEL_ARNES = "2026-09-08T22:22:23+00:00"


def _llamadas_de(transcripcion: Path) -> list[dict]:
    datos = json.loads(transcripcion.read_text(encoding="utf-8"))
    return datos["ejecucion"].get("llamadas_api") or []


def test_las_25_de_la_raiz_son_el_piloto_y_no_la_medicion():
    """El piloto de la corrida de E2 con Haiku corrió con el agente 3.0.0 y la bloqueó. Lo que
    entra en las cifras es la corrida de después, con 3.0.1. Mezclarlas sería mezclar dos
    versiones del agente, así que la prueba fija la separación por el instante de cada llamada,
    que es el único dato que la transcripción trae y nadie puede reescribir sin que se note."""
    raiz = Path(__file__).resolve().parents[1]
    compuerta = json.loads((raiz / "results" / "e2_compuerta_haiku.json").read_text("utf-8"))
    de_la_compuerta = {o["transcripcion"].split("/")[-1] for o in compuerta["observaciones"]}

    piloto = sorted(
        p
        for p in (raiz / "results" / "runs_e2").glob("*.json")
        if p.name not in de_la_compuerta and p.name != "SEG-BEN-040__cte__2.json"
    )
    assert len(piloto) == 25, [p.name for p in piloto]

    for archivo in piloto:
        llamadas = _llamadas_de(archivo)
        assert llamadas, archivo.name
        assert {c["model"] for c in llamadas} == {"claude-haiku-4-5-20251001"}, archivo.name
        for c in llamadas:
            assert c["timestamp"] < CORRECCION_DEL_ARNES, (archivo.name, c["timestamp"])

    # Ninguna es la transcripción que declara una observación de la corrida medida: esa corrida
    # escribe en su propio directorio, y ninguna de sus rutas apunta a la raíz.
    medida = json.loads((raiz / "results" / "e2_security_haiku.json").read_text("utf-8"))
    rutas = {o.get("transcripcion") for o in medida["observaciones"]}
    assert all(r and r.startswith("results/runs_e2/e2_security_haiku/") for r in rutas)
    nombres = {p.name for p in piloto}
    assert not {r for r in rutas if r.split("/")[-1] in nombres and r.count("/") == 2}

    # Y la corrida medida es posterior al cambio, en los mismos datos.
    for archivo in sorted((raiz / "results" / "runs_e2" / "e2_security_haiku").glob("*.json"))[:50]:
        for c in _llamadas_de(archivo):
            assert c["timestamp"] > CORRECCION_DEL_ARNES, (archivo.name, c["timestamp"])


def test_build_metadata_registra_el_entorno():
    metadata = build_metadata(
        seed=7, model="m", config="cte", corpus_version="v1.0",
        api_mode="realtime_concurrente",
    )
    entorno = metadata["entorno"]
    assert entorno["python"]
    assert set(entorno["paquetes"]) == {
        "anthropic", "numpy", "scipy", "pandas", "matplotlib", "pydantic",
    }


def test_write_result_rechaza_metadata_sin_entorno(tmp_path):
    metadata = build_metadata(
        seed=7, model="m", config="cte", corpus_version="v1.0",
        api_mode="realtime_concurrente",
    )
    del metadata["entorno"]
    with pytest.raises(ValueError, match="entorno"):
        write_result("x", {}, metadata, directorio=tmp_path)


def test_read_result_lee_resultados_antiguos_sin_entorno(tmp_path):
    antiguo = tmp_path / "antiguo.json"
    antiguo.write_text(
        '{"metadata": {"seed": 1}, "veredicto": "NO-GO"}', encoding="utf-8"
    )
    datos = read_result("antiguo", directorio=tmp_path)
    assert "entorno" not in datos["metadata"]


