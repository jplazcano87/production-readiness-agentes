#!/usr/bin/env python
"""Prueba de humo contra la API real: valida ids de modelo y prompt caching.

Qué comprueba, por cada rol de `configs/models.yaml`:

1. que el id de modelo declarado sea **aceptado** por la API (se imprime el id que la
   respuesta trae de vuelta, que es la confirmación de que existe);
2. que `usage` llegue completo, con los campos de caché;
3. que `cache_control` en el system prompt produzca de verdad escritura y luego lectura
   de caché (`cache_read_tokens > 0`).

Tres llamadas de `max_tokens=5` por rol:

| variante      | `cache_control` | transporte      | qué se espera                          |
|---------------|-----------------|-----------------|----------------------------------------|
| `sin_cache`   | no              | streaming       | `cache_*_tokens == 0`; además mide TTFT |
| `cache_write` | sí              | sin streaming   | `cache_creation_tokens > 0`            |
| `cache_read`  | sí              | sin streaming   | `cache_read_tokens > 0`                |

El bloque de catálogo se dimensiona por encima del **mínimo de prefijo cacheable**, que
depende del modelo (1024 tokens en Sonnet 4.6, 4096 en Haiku 4.5). Por debajo de ese
mínimo la caché no se crea y la API no devuelve ningún error: `cache_creation_input_tokens`
llega en 0 y no hay forma de distinguirlo de un fallo de configuración.

Los roles que comparten modelo comparten también la entrada de caché, porque el acierto es
por prefijo y no por rol: el segundo rol con el mismo id puede leer la caché que escribió
el primero. Es el comportamiento correcto y así se reporta.

Uso:

    python scripts/smoke_api.py --dry-run      # estimación, sin llamar a la API
    python scripts/smoke_api.py                # ejecución real
    python scripts/smoke_api.py --role agent   # un solo rol
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

import anthropic
from dotenv import load_dotenv

from prf.infra.cli import add_common_args
from prf.infra.client import AnthropicClient
from prf.infra.config import ModelsConfig, load_models
from prf.infra.cost import DryRunReport, Usage, make_estimate
from prf.infra.results import build_metadata, write_result
from prf.infra.tokens import approx_tokens

MAX_TOKENS = 5
PREGUNTA = "Responde únicamente con la palabra: listo."
SYSTEM_ROL = (
    "Eres un asistente de pre-venta de la tienda ficticia TiendaDemo.cl. "
    "Respondes en español de Chile, de forma breve y sin inventar precios ni descuentos."
)
# Holgura sobre el mínimo mayor (4096 tokens de Haiku 4.5): la aproximación local de
# tokens puede subestimar, y quedarse corto haría que la caché no se cree en silencio.
OBJETIVO_TOKENS_CATALOGO = 6000

VARIANTES = ("sin_cache", "cache_write", "cache_read")

_CATEGORIAS = {
    "notebooks": ["Aurora", "Cordillera", "Elqui", "Patagonia"],
    "celulares": ["Loa", "Maipo", "Biobío", "Aysén"],
    "audifonos": ["Chinchorro", "Tongoy", "Rapa", "Chiloé"],
    "televisores": ["Atacama", "Valdivia", "Osorno", "Pucón"],
    "electrodomesticos_cocina": ["Curicó", "Limarí", "Choapa", "Itata"],
    "hogar_inteligente": ["Lauca", "Futaleufú", "Baker", "Loa Norte"],
}
_ATRIBUTOS = [
    "pantalla de 15,6 pulgadas",
    "batería de 12 horas de autonomía declarada",
    "garantía de 12 meses en tienda",
    "conectividad inalámbrica de doble banda",
    "cancelación activa de ruido",
    "eficiencia energética clase A",
    "carcasa de aluminio reciclado",
    "compatibilidad con asistentes de voz",
]


def construir_catalogo(objetivo_tokens: int = OBJETIVO_TOKENS_CATALOGO) -> str:
    """Bloque de catálogo ficticio, determinista y estable byte a byte.

    La estabilidad es obligatoria: la caché es un acierto por prefijo, así que cualquier
    variación entre llamadas (una fecha, un identificador aleatorio) la invalidaría y
    `cache_read_tokens` saldría 0 sin motivo aparente.
    """
    lineas = ["CATÁLOGO DE REFERENCIA (sintético, TiendaDemo.cl):"]
    indice = 0
    while approx_tokens("\n".join(lineas)) < objetivo_tokens:
        for categoria, marcas in _CATEGORIAS.items():
            marca = marcas[indice % len(marcas)]
            atributo = _ATRIBUTOS[indice % len(_ATRIBUTOS)]
            precio = 89_990 + (indice % 40) * 10_000
            lineas.append(
                f"- P{indice:04d} | {marca} {categoria.replace('_', ' ')} serie {indice % 9} | "
                f"categoría: {categoria} | precio: ${precio:,} CLP | stock: {3 + indice % 17} "
                f"unidades | atributo destacado: {atributo} | evaluación promedio: "
                f"{3.4 + (indice % 16) / 10:.1f} de 5."
            )
            indice += 1
    return "\n".join(lineas)


def _roles_a_probar(models: ModelsConfig, filtro: str | None) -> list[str]:
    if filtro is None:
        return list(models.roles)
    if filtro not in models.roles:
        raise SystemExit(f"rol desconocido: {filtro!r}. Disponibles: {', '.join(models.roles)}")
    return [filtro]


def _dry_run(models: ModelsConfig, roles: list[str], catalogo: str) -> int:
    tokens_entrada = approx_tokens(SYSTEM_ROL) + approx_tokens(catalogo) + approx_tokens(PREGUNTA)
    titulo = (
        f"smoke_api — {len(roles)} rol(es) × {len(VARIANTES)} llamadas de max_tokens={MAX_TOKENS}"
    )
    reporte = DryRunReport(titulo=titulo)
    for rol in roles:
        reporte.add(
            make_estimate(
                models,
                concepto=f"{rol} ({len(VARIANTES)} variantes)",
                model_id=models.role(rol).id,
                n_llamadas=len(VARIANTES),
                usage_por_llamada=Usage(input_tokens=tokens_entrada, output_tokens=MAX_TOKENS),
                batch=False,
            )
        )
    reporte.notas.append(
        "Cota superior: se cobra todo como entrada sin caché. Las lecturas de caché reales "
        "cuestan 0,10× y el descuento se verá en la ejecución."
    )
    reporte.notas.append(
        f"Bloque de catálogo: ~{approx_tokens(catalogo)} tokens aproximados, por encima del "
        "mínimo cacheable de 4096 de Haiku 4.5."
    )
    print(reporte)
    return 0


def _fila(resultado: Any, rol: str, variante: str, id_solicitado: str) -> dict[str, Any]:
    return {
        "rol": rol,
        "variante": variante,
        "model_solicitado": id_solicitado,
        "model_aceptado": resultado.model,
        "cache_control": variante != "sin_cache",
        "usage": resultado.usage.to_dict(),
        "cache_read_tokens": resultado.cache_read_tokens,
        "stop_reason": resultado.stop_reason,
        "ttft_s": round(resultado.ttft_s, 3) if resultado.ttft_s is not None else None,
        "latency_s": round(resultado.latency_s, 3) if resultado.latency_s is not None else None,
        "texto": resultado.text.strip(),
        "request_id": resultado.request_id,
    }


def _imprimir_fila(fila: dict[str, Any]) -> None:
    usage = fila["usage"]
    print(f"  [{fila['variante']:<12}] id aceptado: {fila['model_aceptado']}")
    print(
        f"      usage: entrada={usage['input_tokens']} salida={usage['output_tokens']} "
        f"cache_write={usage['cache_creation_tokens']} cache_read={usage['cache_read_tokens']}"
    )
    print(
        f"      cache_read_tokens={fila['cache_read_tokens']}  ttft_s={fila['ttft_s']}  "
        f"latency_s={fila['latency_s']}  stop_reason={fila['stop_reason']}"
    )
    print(f"      respuesta: {fila['texto']!r}")


def main(argv: list[str] | None = None) -> int:
    """Hace la prueba de humo contra la API y escribe lo que costó."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    add_common_args(parser)
    parser.add_argument("--role", default=None, help="Prueba un solo rol de configs/models.yaml.")
    args = parser.parse_args(argv)

    load_dotenv()
    models = load_models()
    roles = _roles_a_probar(models, args.role)
    catalogo = construir_catalogo()

    if args.dry_run:
        return _dry_run(models, roles, catalogo)

    system_sin_cache = AnthropicClient.build_system(SYSTEM_ROL, catalogo, cache=False)
    system_con_cache = AnthropicClient.build_system(SYSTEM_ROL, catalogo, cache=True)
    mensajes = [{"role": "user", "content": PREGUNTA}]

    client = AnthropicClient(models)
    filas: list[dict[str, Any]] = []
    print(
        f"smoke_api: {len(roles)} rol(es), {len(VARIANTES)} llamadas cada uno, "
        f"max_tokens={MAX_TOKENS}, catálogo ~{approx_tokens(catalogo)} tokens aproximados.\n"
    )

    for rol in roles:
        id_solicitado = models.role(rol).id
        print(f"rol {rol} -> id solicitado: {id_solicitado}")
        for variante in VARIANTES:
            usa_cache = variante != "sin_cache"
            system = system_con_cache if usa_cache else system_sin_cache
            try:
                if variante == "sin_cache":
                    # Streaming solo en esta variante: mide TTFT sin añadir ninguna llamada.
                    resultado = client.stream(rol, mensajes, system=system, max_tokens=MAX_TOKENS)
                else:
                    resultado = client.create(rol, mensajes, system=system, max_tokens=MAX_TOKENS)
            except (anthropic.NotFoundError, anthropic.BadRequestError) as exc:
                print(
                    f"\nID DE MODELO RECHAZADO en el rol {rol!r}: {id_solicitado}", file=sys.stderr
                )
                print(f"  error de la API: {exc}", file=sys.stderr)
                print(
                    "  Se detiene aquí. Corrige el campo `id` de ese rol en configs/models.yaml "
                    "y anótalo en configs/models.yaml antes de reintentar.",
                    file=sys.stderr,
                )
                return 2
            except anthropic.AuthenticationError as exc:
                print(f"\nCredenciales inválidas o ausentes: {exc}", file=sys.stderr)
                print("  Completa ANTHROPIC_API_KEY en .env (ver .env.example).", file=sys.stderr)
                return 3

            fila = _fila(resultado, rol, variante, id_solicitado)
            filas.append(fila)
            _imprimir_fila(fila)
        print()

    ids_por_rol = {rol: models.role(rol).id for rol in roles}
    resumen = {
        "ids_aceptados": sorted({fila["model_aceptado"] for fila in filas}),
        "ids_solicitados": sorted(set(ids_por_rol.values())),
        "cache_write_observada": any(f["usage"]["cache_creation_tokens"] > 0 for f in filas),
        "cache_read_observada": any(f["cache_read_tokens"] > 0 for f in filas),
        "ttft_medido": any(f["ttft_s"] is not None for f in filas),
    }
    print("Resumen")
    print(f"  ids solicitados: {', '.join(resumen['ids_solicitados'])}")
    print(f"  ids aceptados:   {', '.join(resumen['ids_aceptados'])}")
    print(f"  escritura de caché observada: {resumen['cache_write_observada']}")
    print(f"  lectura de caché observada:   {resumen['cache_read_observada']}")
    print(f"  TTFT medido:                  {resumen['ttft_medido']}")
    print(f"  costo real de esta prueba: USD {client.ledger.costo_usd(models):.4f}")

    archivo = write_result(
        "smoke_api",
        {"resumen": resumen, "llamadas": filas, "uso_acumulado": client.usage_summary()},
        build_metadata(
            seed=args.seed if args.seed is not None else 0,
            model=ids_por_rol,
            config="smoke",
            corpus_version="v1.0",
            api_mode="realtime",
            extra={
                "max_tokens": MAX_TOKENS,
                "catalogo_tokens_aprox": approx_tokens(catalogo),
                "minimo_cacheable_sonnet_4_6": 1024,
                "minimo_cacheable_haiku_4_5": 4096,
            },
        ),
    )
    print(f"  resultado escrito en {archivo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
