"""El bloque de catálogo de la prueba de humo debe poder cachearse.

Dos condiciones, y ninguna produce error de API si falla: la caché simplemente no se crea
y `cache_read_tokens` queda en 0.
"""

from __future__ import annotations

from prf.infra.tokens import approx_tokens
from smoke_api import MAX_TOKENS, VARIANTES, construir_catalogo

MINIMO_CACHEABLE_HAIKU_4_5 = 4096


def test_el_catalogo_es_estable_byte_a_byte():
    # La caché es un acierto por prefijo: cualquier variación entre llamadas la invalida.
    assert construir_catalogo() == construir_catalogo()


def test_el_catalogo_supera_el_minimo_cacheable_mayor():
    tokens = approx_tokens(construir_catalogo())

    assert tokens > MINIMO_CACHEABLE_HAIKU_4_5


def test_la_prueba_es_barata_por_diseno():
    assert MAX_TOKENS == 5
    assert VARIANTES == ("sin_cache", "cache_write", "cache_read")
