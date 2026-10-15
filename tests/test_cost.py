"""Estimación de costo: tarifas, caché y descuento de Batch API."""

from __future__ import annotations

import pytest

from prf.infra.cost import DryRunReport, Usage, estimate_cost_usd, make_estimate


def test_usage_suma_y_totaliza():
    total = Usage(input_tokens=10, output_tokens=5) + Usage(input_tokens=1, cache_read_tokens=100)

    assert total.input_tokens == 11
    assert total.output_tokens == 5
    assert total.cache_read_tokens == 100
    assert total.total_tokens == 116


def test_costo_basico_entrada_y_salida(models_config):
    usd = estimate_cost_usd(
        models_config,
        "claude-sonnet-4-6",
        Usage(input_tokens=1_000_000, output_tokens=1_000_000),
    )

    assert usd == pytest.approx(18.0)  # 3 + 15


def test_la_cache_se_cobra_sobre_la_tarifa_de_entrada(models_config):
    escritura = estimate_cost_usd(
        models_config, "claude-sonnet-4-6", Usage(cache_creation_tokens=1_000_000)
    )
    lectura = estimate_cost_usd(
        models_config, "claude-sonnet-4-6", Usage(cache_read_tokens=1_000_000)
    )

    assert escritura == pytest.approx(3.0 * 1.25)
    assert lectura == pytest.approx(3.0 * 0.10)


def test_batch_aplica_el_descuento_del_50_por_ciento(models_config):
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)

    normal = estimate_cost_usd(models_config, "claude-sonnet-4-6", usage)
    lote = estimate_cost_usd(models_config, "claude-sonnet-4-6", usage, batch=True)

    assert lote == pytest.approx(normal * 0.5)


def test_haiku_es_mas_barato_que_sonnet(models_config):
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)

    haiku = estimate_cost_usd(models_config, "claude-haiku-4-5-20251001", usage)
    sonnet = estimate_cost_usd(models_config, "claude-sonnet-4-6", usage)

    assert haiku < sonnet


def test_modelo_sin_precio_falla_con_mensaje_claro(models_config):
    with pytest.raises(KeyError, match="no hay precio declarado"):
        estimate_cost_usd(models_config, "modelo-inventado", Usage(input_tokens=1))


def test_make_estimate_escala_por_numero_de_llamadas(models_config):
    estimacion = make_estimate(
        models_config,
        concepto="E1: agente",
        model_id="claude-sonnet-4-6",
        n_llamadas=100,
        usage_por_llamada=Usage(input_tokens=1000, output_tokens=200),
        batch=True,
    )

    assert estimacion.usage.input_tokens == 100_000
    assert estimacion.usage.output_tokens == 20_000
    assert estimacion.usd == pytest.approx((100_000 * 3 + 20_000 * 15) / 1e6 * 0.5)


def test_reporte_de_dry_run_imprime_totales_y_costo(models_config):
    reporte = DryRunReport(titulo="E1 (línea base de robustez)")
    reporte.add(
        make_estimate(
            models_config,
            concepto="agente",
            model_id="claude-sonnet-4-6",
            n_llamadas=10,
            usage_por_llamada=Usage(input_tokens=1000, output_tokens=100),
            batch=True,
        )
    )
    reporte.add(
        make_estimate(
            models_config,
            concepto="simulador de usuario",
            model_id="claude-haiku-4-5-20251001",
            n_llamadas=10,
            usage_por_llamada=Usage(input_tokens=500, output_tokens=50),
            batch=True,
        )
    )

    texto = str(reporte)

    assert "[--dry-run]" in texto
    assert "E1 (línea base de robustez)" in texto
    assert "batch" in texto
    assert "Costo estimado: USD" in texto
    assert reporte.total_usd == pytest.approx(sum(item.usd for item in reporte.items))
    assert reporte.to_dict()["total_tokens"]["input_tokens"] == 15_000
