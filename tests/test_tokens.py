"""Aproximación local de tokens (usada por `--dry-run` y por las estadísticas del corpus)."""

from __future__ import annotations

from prf.infra.tokens import METODO_APROXIMADO, approx_tokens, approx_tokens_messages


def test_texto_vacio_es_cero():
    assert approx_tokens("") == 0


def test_crece_con_la_longitud():
    corto = approx_tokens("Busco un notebook.")
    largo = approx_tokens(
        "Busco un notebook para programar con al menos 16 GB de RAM y buena batería."
    )

    assert 0 < corto < largo


def test_el_metodo_queda_declarado():
    assert "aproximacion_local" in METODO_APROXIMADO


def test_suma_system_y_mensajes():
    mensajes = [{"role": "user", "content": "Hola, busco un televisor."}]
    system = [{"type": "text", "text": "Eres un asistente de pre-venta de TiendaDemo.cl."}]

    con_system = approx_tokens_messages(mensajes, system)
    sin_system = approx_tokens_messages(mensajes)

    assert con_system > sin_system > 0


def test_recorre_contenido_estructurado():
    mensajes = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "una reseña muy larga " * 10},
                {"type": "text", "text": "otro bloque"},
            ],
        }
    ]

    assert approx_tokens_messages(mensajes) > 40
