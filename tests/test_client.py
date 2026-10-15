"""Pruebas del wrapper del SDK, con la API simulada (ninguna llamada de red)."""

from __future__ import annotations

import pytest

from prf.infra.client import AnthropicClient, BatchOutcome, is_retryable
from tests.conftest import (
    FakeBadRequestError,
    FakeBatchResult,
    FakeBatchResultInner,
    FakeBlock,
    FakeMessage,
    FakeRateLimitError,
    FakeServerError,
    FakeUsage,
)

# ------------------------------------------------------------------ parámetros


def test_build_params_usa_los_valores_del_rol(client):
    params = client.build_params("agent", [{"role": "user", "content": "hola"}])

    assert params["model"] == "claude-sonnet-4-6"
    assert params["max_tokens"] == 2048
    assert params["temperature"] == 1.0
    assert params["messages"] == [{"role": "user", "content": "hola"}]


def test_build_params_permite_sobrescribir_y_agregar_herramientas(client):
    params = client.build_params(
        "quarantine",
        [{"role": "user", "content": "resume"}],
        max_tokens=64,
        temperature=0.0,
        tools=[{"name": "get_reviews", "input_schema": {}}],
        tool_choice={"type": "auto"},
    )

    assert params["model"] == "claude-haiku-4-5-20251001"
    assert params["max_tokens"] == 64
    assert params["tools"][0]["name"] == "get_reviews"
    assert params["tool_choice"] == {"type": "auto"}


def test_rol_desconocido_falla_temprano(client):
    with pytest.raises(KeyError, match="rol de modelo desconocido"):
        client.build_params("inexistente", [{"role": "user", "content": "x"}])


# ---------------------------------------------------------------------- caché


def test_build_system_pone_cache_control_en_prompt_y_catalogo():
    bloques = AnthropicClient.build_system("Eres un asistente.", "CATÁLOGO: ...")

    assert len(bloques) == 2
    assert all(bloque["cache_control"] == {"type": "ephemeral"} for bloque in bloques)
    assert bloques[0]["text"] == "Eres un asistente."


def test_build_system_sin_cache_para_e3():
    # E3 (latencia/TTFT) exige API en tiempo real y SIN prompt caching.
    bloques = AnthropicClient.build_system("Eres un asistente.", "CATÁLOGO: ...", cache=False)

    assert all("cache_control" not in bloque for bloque in bloques)


def test_result_registra_si_la_peticion_llevaba_cache(client):
    con_cache = client.create(
        "agent",
        [{"role": "user", "content": "hola"}],
        system=AnthropicClient.build_system("rol", "catálogo"),
    )
    sin_cache = client.create(
        "agent",
        [{"role": "user", "content": "hola"}],
        system=AnthropicClient.build_system("rol", "catálogo", cache=False),
    )

    assert con_cache.cache_enabled is True
    assert sin_cache.cache_enabled is False


# ------------------------------------------------------- contabilidad de tokens


def test_create_reporta_tokens_y_latencia(client, fake_anthropic):
    fake_anthropic.messages.respuesta = FakeMessage(
        content=[FakeBlock(text="Recomiendo <<rec:P001>>")],
        usage=FakeUsage(
            input_tokens=1500,
            output_tokens=42,
            cache_creation_input_tokens=800,
            cache_read_input_tokens=700,
        ),
    )

    resultado = client.create("agent", [{"role": "user", "content": "hola"}])

    assert resultado.text == "Recomiendo <<rec:P001>>"
    assert resultado.input_tokens == 1500
    assert resultado.output_tokens == 42
    assert resultado.usage.cache_creation_tokens == 800
    assert resultado.cache_read_tokens == 700
    assert resultado.latency_s is not None and resultado.latency_s >= 0
    assert resultado.ttft_s is None  # sin streaming no hay TTFT
    assert resultado.request_id == "req_test_0001"
    assert resultado.streamed is False


def test_campos_de_cache_ausentes_se_normalizan_a_cero(client, fake_anthropic):
    fake_anthropic.messages.respuesta = FakeMessage(usage=FakeUsage(cache_read_input_tokens=None))

    resultado = client.create("agent", [{"role": "user", "content": "hola"}])

    assert resultado.cache_read_tokens == 0
    assert resultado.usage.cache_creation_tokens == 0


def test_tool_uses_expone_los_bloques_de_herramienta(client, fake_anthropic):
    fake_anthropic.messages.respuesta = FakeMessage(
        content=[
            FakeBlock(text="Busco en el catálogo."),
            FakeBlock(
                type="tool_use", id="tu_1", name="search_catalog", input={"query": "notebook"}
            ),
        ]
    )

    resultado = client.create("agent", [{"role": "user", "content": "hola"}])

    assert resultado.text == "Busco en el catálogo."
    assert [uso["name"] for uso in resultado.tool_uses] == ["search_catalog"]


def test_ledger_acumula_uso_y_costo(client):
    client.create("agent", [{"role": "user", "content": "a"}])
    client.create("agent", [{"role": "user", "content": "b"}])

    resumen = client.usage_summary()

    assert resumen["n_llamadas"] == 2
    assert resumen["total"]["input_tokens"] == 200
    assert resumen["total"]["output_tokens"] == 40
    # 200 tokens de entrada a 3 USD/Mtok + 40 de salida a 15 USD/Mtok.
    assert resumen["costo_usd_estimado"] == pytest.approx(0.0012, abs=1e-9)


# ------------------------------------------------------------------- streaming


def test_stream_mide_ttft_antes_que_la_latencia_total(client):
    resultado = client.stream("agent", [{"role": "user", "content": "hola"}])

    assert resultado.streamed is True
    assert resultado.ttft_s is not None
    assert resultado.latency_s is not None
    assert 0 <= resultado.ttft_s <= resultado.latency_s


def test_stream_sin_deltas_deja_ttft_en_none(client, fake_anthropic):
    from tests.conftest import FakeEvent

    fake_anthropic.messages.eventos = [FakeEvent("message_start"), FakeEvent("message_stop")]

    resultado = client.stream("agent", [{"role": "user", "content": "hola"}])

    assert resultado.ttft_s is None
    assert resultado.latency_s is not None


# ------------------------------------------------------------------ reintentos


def test_is_retryable_distingue_por_tipo_de_error():
    assert is_retryable(FakeRateLimitError()) is True
    assert is_retryable(FakeServerError()) is True
    assert is_retryable(FakeBadRequestError()) is False
    assert is_retryable(ValueError("otra cosa")) is False


def test_reintenta_con_backoff_exponencial(client, fake_anthropic, sleeps):
    fake_anthropic.messages.errores = [FakeRateLimitError(), FakeServerError()]

    resultado = client.create("agent", [{"role": "user", "content": "hola"}])

    assert resultado.n_intentos == 3
    assert len(sleeps) == 2
    # Equal jitter: cada espera cae en [d/2, d] con d = min(base * 2**intento, tope).
    for intento, espera in enumerate(sleeps):
        d = min(client.backoff_base_s * (2**intento), client.backoff_max_s)
        assert d / 2 <= espera <= d
    assert sleeps[1] > sleeps[0]  # el backoff crece de verdad entre intentos


def test_no_reintenta_errores_de_cliente(client, fake_anthropic, sleeps):
    fake_anthropic.messages.errores = [FakeBadRequestError()]

    with pytest.raises(FakeBadRequestError):
        client.create("agent", [{"role": "user", "content": "hola"}])

    assert sleeps == []


def test_agota_los_reintentos_y_propaga(client, fake_anthropic, sleeps):
    fake_anthropic.messages.errores = [FakeServerError() for _ in range(10)]

    with pytest.raises(FakeServerError):
        client.create("agent", [{"role": "user", "content": "hola"}])

    assert len(sleeps) == client.max_retries


# --------------------------------------------------------------- conteo tokens


def test_count_tokens_solo_envia_los_campos_del_endpoint(client, fake_anthropic):
    total = client.count_tokens(
        "agent",
        [{"role": "user", "content": "hola"}],
        system=AnthropicClient.build_system("rol"),
    )

    enviado = fake_anthropic.messages.llamadas[-1]
    assert total == 1234
    assert set(enviado) == {"model", "messages", "system"}
    assert "max_tokens" not in enviado  # el endpoint de conteo no lo acepta


# ----------------------------------------------------------------------- lotes


def _resultado_lote(custom_id: str, texto: str) -> FakeBatchResult:
    return FakeBatchResult(
        custom_id=custom_id,
        result=FakeBatchResultInner(
            type="succeeded",
            message=FakeMessage(content=[FakeBlock(text=texto)]),
        ),
    )


def test_build_batch_request_incluye_custom_id_y_params(client):
    peticion = client.build_batch_request(
        "caso-001-run-0", "agent", [{"role": "user", "content": "hola"}]
    )

    assert peticion["custom_id"] == "caso-001-run-0"
    assert peticion["params"]["model"] == "claude-sonnet-4-6"


def test_submit_batch_rechaza_custom_id_duplicados(client):
    peticiones = [
        client.build_batch_request("dup", "agent", [{"role": "user", "content": "a"}]),
        client.build_batch_request("dup", "agent", [{"role": "user", "content": "b"}]),
    ]

    with pytest.raises(ValueError, match="únicos"):
        client.submit_batch(peticiones)


def test_submit_batch_rechaza_lote_vacio(client):
    with pytest.raises(ValueError, match="vacío"):
        client.submit_batch([])


def test_run_batch_espera_y_empareja_por_custom_id(client, fake_anthropic, sleeps):
    fake_anthropic.messages.estados_lote = ["in_progress", "in_progress", "ended"]
    fake_anthropic.messages.resultados_lote = [
        _resultado_lote("caso-b", "segundo"),
        _resultado_lote("caso-a", "primero"),  # la Batch API devuelve en cualquier orden
    ]
    peticiones = [
        client.build_batch_request("caso-a", "agent", [{"role": "user", "content": "a"}]),
        client.build_batch_request("caso-b", "agent", [{"role": "user", "content": "b"}]),
    ]

    resultados = client.run_batch(peticiones, poll_interval_s=0.0)

    assert set(resultados) == {"caso-a", "caso-b"}
    assert resultados["caso-a"].result.text == "primero"
    assert resultados["caso-b"].result.text == "segundo"
    assert all(salida.ok for salida in resultados.values())
    assert len(sleeps) == 2  # dos sondeos antes de `ended`


def test_collect_batch_conserva_los_errores(client, fake_anthropic):
    fake_anthropic.messages.estados_lote = ["ended"]
    fake_anthropic.messages.resultados_lote = [
        _resultado_lote("ok", "bien"),
        FakeBatchResult(
            custom_id="malo",
            result=FakeBatchResultInner(type="errored", error={"type": "invalid_request"}),
        ),
        FakeBatchResult(custom_id="vencido", result=FakeBatchResultInner(type="expired")),
    ]

    resultados = client.collect_batch("msgbatch_test")

    assert resultados["ok"].ok is True
    assert resultados["malo"].status == "errored"
    assert resultados["malo"].error == {"type": "invalid_request"}
    assert resultados["vencido"].status == "expired"
    assert resultados["vencido"].result is None


def test_resultado_de_lote_se_marca_como_batch(client, fake_anthropic):
    fake_anthropic.messages.estados_lote = ["ended"]
    fake_anthropic.messages.resultados_lote = [_resultado_lote("caso-a", "texto")]

    resultados = client.collect_batch("msgbatch_test", roles={"caso-a": "agent"})
    salida: BatchOutcome = resultados["caso-a"]

    assert salida.result.batch is True
    assert salida.result.role == "agent"
    assert salida.result.custom_id == "caso-a"
    assert salida.result.latency_s is None  # la latencia no es interpretable en lote


def test_wait_for_batch_respeta_el_timeout(client, fake_anthropic):
    fake_anthropic.messages.estados_lote = ["in_progress"]

    with pytest.raises(TimeoutError, match="msgbatch_test"):
        client.wait_for_batch("msgbatch_test", poll_interval_s=0.0, timeout_s=0.0)


# ------------------------------------------------------------- serialización


def test_call_result_es_serializable_a_json(client):
    import json

    resultado = client.create("agent", [{"role": "user", "content": "hola"}])
    datos = json.loads(json.dumps(resultado.to_dict(), ensure_ascii=False))

    for campo in ("ttft_s", "latency_s", "input_tokens", "output_tokens", "cache_read_tokens"):
        assert campo in datos


# ------------------------------------------- muestreo (temperature) y firma del SDK


def test_temperature_viaja_por_extra_body_en_tiempo_real(client, fake_anthropic):
    # El SDK 1.4.0 no acepta `temperature` como argumento con nombre; la API sí lo acepta
    # en el cuerpo JSON. `extra_body` es el puente, y conserva la temperatura por rol.
    client.create("agent", [{"role": "user", "content": "hola"}])

    enviado = fake_anthropic.messages.llamadas[-1]
    assert "temperature" not in enviado
    assert enviado["extra_body"] == {"temperature": 1.0}


def test_temperature_viaja_por_extra_body_en_streaming(client, fake_anthropic):
    client.stream("quarantine", [{"role": "user", "content": "resume"}])

    enviado = fake_anthropic.messages.llamadas[-1]
    assert "temperature" not in enviado
    assert enviado["extra_body"] == {"temperature": 0.0}


def test_dividir_extra_body_conserva_lo_que_ya_hubiera(client):
    from prf.infra.client import dividir_extra_body

    resultado = dividir_extra_body(
        {"model": "m", "temperature": 0.5, "extra_body": {"otro_campo": 1}}
    )

    assert resultado == {"model": "m", "extra_body": {"otro_campo": 1, "temperature": 0.5}}


def test_la_peticion_de_lote_lleva_temperature_en_linea(client):
    # En la Batch API los parámetros SON el cuerpo JSON: `temperature` va como un campo
    # más, sin `extra_body`.
    peticion = client.build_batch_request(
        "caso-001", "quarantine", [{"role": "user", "content": "hola"}]
    )

    assert "extra_body" not in peticion["params"]
    assert peticion["params"]["temperature"] == 0.0


def test_el_mock_rechaza_argumentos_que_el_sdk_no_acepta(fake_anthropic):
    # Guarda de la guarda: si el mock volviera a aceptar cualquier cosa, esta clase de
    # fallo solo aparecería gastando una llamada real.
    with pytest.raises(TypeError, match="temperature"):
        fake_anthropic.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=5,
            messages=[{"role": "user", "content": "hola"}],
            temperature=1.0,
        )


# ------------------------------------------- reenvío del turno del asistente


def test_el_reenvio_deja_solo_los_campos_que_la_api_acepta():
    # El objeto acumulado por el stream trae campos que solo tienen sentido de bajada;
    # devolverlos provoca un 400 «Extra inputs are not permitted». El fallo únicamente
    # aparece con streaming, que es la ruta de E3.
    from prf.infra.client import bloques_para_reenvio

    limpios = bloques_para_reenvio(
        [
            {"type": "text", "text": "hola", "citations": None, "parsed_output": {"x": 1}},
            {"type": "tool_use", "id": "t1", "name": "f", "input": {}, "caller": None},
        ]
    )

    assert limpios == [
        {"type": "text", "text": "hola"},
        {"type": "tool_use", "id": "t1", "name": "f", "input": {}},
    ]


def test_un_bloque_de_tipo_desconocido_se_reenvia_intacto():
    from prf.infra.client import bloques_para_reenvio

    bloque = {"type": "algo_nuevo", "campo": 1}

    assert bloques_para_reenvio([bloque]) == [bloque]


def test_call_result_expone_el_contenido_listo_para_reenviar(client, fake_anthropic):
    from tests.conftest import FakeBlock, FakeMessage

    fake_anthropic.messages.respuesta = FakeMessage(
        content=[FakeBlock(type="tool_use", id="t1", name="search_catalog", input={"q": "x"})]
    )

    resultado = client.create("agent", [{"role": "user", "content": "hola"}])

    assert resultado.contenido_para_reenvio == [
        {"type": "tool_use", "id": "t1", "name": "search_catalog", "input": {"q": "x"}}
    ]


# --------------------------------------- registro por llamada y TTFT de texto


def test_cada_llamada_deja_una_fila_en_el_registro(client, fake_anthropic):
    client.create("agent", [{"role": "user", "content": "a"}])
    client.stream("agent", [{"role": "user", "content": "b"}])

    assert len(client.registro) == 2
    assert client.registro[0]["role"] == "agent"
    assert client.registro[0]["api_mode"] == "realtime"
    assert client.registro[0]["request_id"] == "req_test_0001"
    assert client.registro[0]["timestamp"].endswith("+00:00")


def test_el_ttft_de_texto_se_mide_aparte_del_ttft_general(client, fake_anthropic):
    # `ttft_s` marca el primer token de cualquier bloque, incluido el JSON de una llamada
    # a herramienta que el usuario no ve; `ttft_texto_s` marca el primero que sí lee.
    from tests.conftest import FakeDelta, FakeEvent

    fake_anthropic.messages.eventos = [
        FakeEvent("message_start"),
        FakeEvent("content_block_delta", FakeDelta("input_json_delta")),
        FakeEvent("content_block_delta", FakeDelta("text_delta")),
        FakeEvent("message_stop"),
    ]

    resultado = client.stream("agent", [{"role": "user", "content": "hola"}])

    assert resultado.ttft_s is not None
    assert resultado.ttft_texto_s is not None
    assert resultado.ttft_texto_s >= resultado.ttft_s


def test_sin_bloques_de_texto_el_ttft_de_texto_queda_en_none(client, fake_anthropic):
    from tests.conftest import FakeDelta, FakeEvent

    fake_anthropic.messages.eventos = [
        FakeEvent("message_start"),
        FakeEvent("content_block_delta", FakeDelta("input_json_delta")),
    ]

    resultado = client.stream("agent", [{"role": "user", "content": "hola"}])

    assert resultado.ttft_s is not None
    assert resultado.ttft_texto_s is None


def test_el_resumen_de_llamada_no_arrastra_el_contenido(client):
    resultado = client.create("agent", [{"role": "user", "content": "hola"}])

    resumen = resultado.resumen_llamada()

    assert "content" not in resumen and "text" not in resumen
    assert resumen["input_tokens"] == resultado.usage.input_tokens


def test_el_request_id_de_una_llamada_con_streaming_se_registra(client, fake_anthropic):
    # El mensaje acumulado del stream no trae `_request_id`: el id vive en el objeto del
    # stream. E3 solo usa streaming, así que sin esto registraría `null` en todas sus
    # peticiones y no habría forma de volver a ninguna.
    resultado = client.stream("agent", [{"role": "user", "content": "hola"}])

    assert resultado.request_id == "req_test_stream_01"
    assert client.registro[-1]["request_id"] == "req_test_stream_01"
