"""Vista combinada de E2 sobre la partición de prueba de v1.3, sin llamar a la API.

    python scripts/e2_vista_combinada.py

v1.3 es incremental: los 98 casos de seguridad de prueba de v1.2 son byte a byte los mismos y
sus 1.176 ejecuciones siguen siendo válidas, así que lo nuevo se **une** a lo ya medido en vez
de repetirlo. El precedente es E1 con `prompt_only`, que se combinó igual.

Lo que se une no son dos corridas cualesquiera: las dos se leen con el **criterio de ataque
1.2.0**, y por eso la parte de v1.2 se toma de su reclasificación y no del archivo original.
Combinar una corrida leída con 1.0.0 y otra con 1.2.0 daría un ASR que no mide nada, porque la
mitad contaría rechazos como éxitos.

Las dos corridas difieren en la versión del agente —3.0.0 y 3.0.1— y en la cobertura de sus
transcripciones. Las dos cosas se declaran en la metadata en vez de promediarse en silencio: el
parche 3.0.1 solo evita perder una ejecución cuando el planificador de `cte` escribe una
especificación de formato inválida, y con Sonnet no se activó nunca.

El informe necesita las cifras **con y sin** los ataques de descripción, porque en `dual_llm` y
`cte` el cero de ese portador es estructural —la clave `description` se elimina antes de que la
lea ningún modelo— y meterlo en el agregado baja el ASR sin que ninguna defensa haya resistido
nada. Las reglas de la política leen el total, como está escrito en la v0.3.0.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from prf.env.cases import CasoSeguridad  # noqa: E402
from prf.eval.ataque import CRITERIO_ATAQUE_VERSION  # noqa: E402
from prf.infra import paths  # noqa: E402
from prf.infra.config import load_experiments  # noqa: E402
from prf.infra.results import build_metadata, read_result, write_result  # noqa: E402
from prf.verdict import evidencia as ev  # noqa: E402
from run_e2 import analizar  # noqa: E402

BASE_V12 = "e2_security_criterio1.2.0"
NUEVOS = "e2_portador_descripcion"
SALIDA = "e2_security_v1.3"


def _portador_de(case_id: str, casos: dict[str, CasoSeguridad]) -> str | None:
    caso = casos.get(case_id)
    return caso.portador_efectivo if caso else None


def _cobertura(nombre: str, observaciones: list[dict[str, Any]]) -> dict[str, Any]:
    """Cuántas de las ejecuciones de una corrida tienen su transcripción en disco.

    Una corrida sin transcripciones no se puede auditar, y la de v1.2 perdió 26 cuando el
    piloto de la corrida con Haiku compartió directorio y las sobrescribió. Un recuento que no
    diga cuántas
    pudo mirar no es auditable.
    """
    con = sum(
        1
        for o in observaciones
        if o.get("transcripcion") and (paths.root / o["transcripcion"]).is_file()
    )
    return {
        "corrida": f"results/{nombre}.json",
        "ejecuciones": len(observaciones),
        "con_transcripcion": con,
        "sin_transcripcion": len(observaciones) - con,
    }


def main(argv: list[str] | None = None) -> int:
    """Une las dos corridas de E2 en la vista que el informe cita."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--salida", default=SALIDA, help="Nombre del JSON en results/, sin extensión."
    )
    args = parser.parse_args(argv)

    experimentos = load_experiments()
    version = experimentos["corpus_version"]
    bootstrap = experimentos["bootstrap"]

    base = read_result(BASE_V12)
    nuevos = read_result(NUEVOS)
    md_base, md_nuevos = dict(base["metadata"]), dict(nuevos["metadata"])

    for nombre, metadata in ((BASE_V12, md_base), (NUEVOS, md_nuevos)):
        if metadata.get("criterio_ataque_version") != CRITERIO_ATAQUE_VERSION:
            raise SystemExit(
                f"{nombre} declara criterio {metadata.get('criterio_ataque_version')} y el "
                f"instalado es {CRITERIO_ATAQUE_VERSION}: no se pueden combinar"
            )

    casos = {
        c.case_id: c
        for linea in (paths.corpus_version(version) / "cases_security.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if linea.strip()
        for c in [CasoSeguridad.model_validate_json(linea)]
    }

    observaciones = []
    for origen, documento in ((BASE_V12, base), (NUEVOS, nuevos)):
        for o in documento["observaciones"]:
            observaciones.append({**o, "corrida": origen})

    configs = sorted(set(base["configs"]) | set(nuevos["configs"]))
    # `prompt_only` existe en las dos; el resto también. Si alguna faltara en una de ellas, su
    # ASR combinado mezclaría poblaciones distintas y hay que verlo, no descubrirlo después.
    solo_en_una = [c for c in configs if (c in base["configs"]) != (c in nuevos["configs"])]

    de_descripcion = {
        o["run_id"] for o in observaciones if _portador_de(o["case_id"], casos) == "descripcion"
    }
    sin_descripcion = [o for o in observaciones if o["run_id"] not in de_descripcion]

    por_portador: dict[str, Any] = {}
    for portador in ("resena", "descripcion"):
        subconjunto = [o for o in observaciones if _portador_de(o["case_id"], casos) == portador]
        por_portador[portador] = analizar(subconjunto, configs, bootstrap) if subconjunto else {}

    payload = {
        "configs": configs,
        "n_casos": len({o["case_id"] for o in observaciones}),
        "n_ejecuciones": len(observaciones),
        "resultados": analizar(observaciones, configs, bootstrap),
        "sin_ataques_de_descripcion": {
            "que_es": (
                "El mismo cálculo dejando fuera los 21 casos con portador descripción. En "
                "`dual_llm` y `cte` su cero es estructural —`sanear_producto` elimina la clave "
                "`description` antes de que la lea ningún modelo— así que incluirlos baja el "
                "ASR agregado sin que ninguna defensa haya resistido nada."
            ),
            "n_ejecuciones": len(sin_descripcion),
            "resultados": analizar(sin_descripcion, configs, bootstrap),
        },
        "por_portador": por_portador,
        "destino_de_los_exitos": {
            config: ev.destino_de_los_exitos({"observaciones": observaciones}, config, paths.root)
            for config in configs
        },
        "observaciones": observaciones,
    }

    metadata = build_metadata(
        seed=experimentos["seed_global"],
        model=md_nuevos["model"],
        config=",".join(configs),
        corpus_version=version,
        api_mode="none",
        agent_version=f"{md_base['agent_version']}+{md_nuevos['agent_version']}",
        evaluator_version=md_nuevos["evaluator_version"],
        extra={
            "split": "test",
            "n_runs_por_caso": md_nuevos["n_runs_por_caso"],
            "n_casos": payload["n_casos"],
            "vista_combinada": {
                "que_es": (
                    "Unión de las ejecuciones de dos corridas sobre la misma partición de "
                    "prueba. No se volvió a medir nada: v1.3 hereda de v1.2 byte a byte los "
                    "98 casos de seguridad de prueba anteriores."
                ),
                "sin_llamadas_api": True,
                "corridas": [
                    {
                        "nombre": f"results/{BASE_V12}.json",
                        "casos": md_base["n_casos"],
                        "agent_version": md_base["agent_version"],
                        "corpus_version": md_base["corpus_version"],
                        "api_mode_original": md_base.get("api_mode_original")
                        or "realtime_concurrente",
                        "cobertura": _cobertura(BASE_V12, base["observaciones"]),
                    },
                    {
                        "nombre": f"results/{NUEVOS}.json",
                        "casos": md_nuevos["n_casos"],
                        "agent_version": md_nuevos["agent_version"],
                        "corpus_version": md_nuevos["corpus_version"],
                        "api_mode_original": md_nuevos["api_mode"],
                        "cobertura": _cobertura(NUEVOS, nuevos["observaciones"]),
                    },
                ],
                "configs_en_una_sola_corrida": solo_en_una,
                "nota_agente": (
                    "Las dos corridas usan versiones distintas del agente, 3.0.0 y 3.0.1. El "
                    "parche solo evita perder una ejecución cuando el planificador de `cte` "
                    "escribe una especificación de formato inválida; con Sonnet no se activó "
                    "en ninguna de las dos corridas."
                ),
            },
            # El diagnóstico de cobertura de E5 lee este campo, así que la vista combinada
            # tiene que arrastrarlo: las 26 transcripciones que el piloto con Haiku sobrescribió
            # siguen faltando en la mitad de v1.2, y un «cero fugas» sobre una cobertura que
            # nadie declara no se puede comprobar.
            "transcripciones_perdidas": (md_base.get("transcripciones_perdidas") or {}),
            "cobertura_de_transcripciones": {
                "verificadas": sum(
                    _cobertura(nombre, documento["observaciones"])["con_transcripcion"]
                    for nombre, documento in ((BASE_V12, base), (NUEVOS, nuevos))
                ),
                "total": len(observaciones),
                "por_corrida": {
                    BASE_V12: _cobertura(BASE_V12, base["observaciones"]),
                    NUEVOS: _cobertura(NUEVOS, nuevos["observaciones"]),
                },
            },
            "costo_usd_real": 0.0,
            "costo_usd_de_las_corridas_combinadas": round(
                float(md_base.get("costo_usd_real") or 0)
                + float(md_nuevos.get("costo_usd_real") or 0),
                4,
            ),
        },
    )

    archivo = write_result(args.salida, payload, metadata)
    resultados = payload["resultados"]
    sin = payload["sin_ataques_de_descripcion"]["resultados"]

    print(f"vista combinada en {archivo.name}")
    print(
        f"  {payload['n_casos']} casos · {payload['n_ejecuciones']} ejecuciones · "
        f"criterio de ataque {CRITERIO_ATAQUE_VERSION}"
    )
    if solo_en_una:
        print(f"  ATENCIÓN: configuraciones presentes en una sola corrida: {solo_en_una}")
    cabecera = (
        f"{'config':<13}{'ASR global':>16}{'sin descripción':>18}{'directa':>12}{'indirecta':>12}"
    )
    print(f"\n  {cabecera}")
    for config in configs:
        fila = resultados[config]
        print(
            f"  {config:<13}{fila['asr_sobre_todas']['asr']:>16.4f}"
            f"{sin[config]['asr_sobre_todas']['asr']:>18.4f}"
            f"{fila['asr_por_vector'].get('direct', {}).get('asr', 0):>12.4f}"
            f"{fila['asr_por_vector'].get('indirect', {}).get('asr', 0):>12.4f}"
        )
    print("\n  ASR por portador")
    for config in configs:
        celdas = []
        for portador in ("resena", "descripcion"):
            bloque = por_portador[portador].get(config, {}).get("asr_sobre_todas", {})
            celdas.append(f"{portador} {bloque.get('exitos', 0)}/{bloque.get('n', 0)}")
        print(f"  {config:<13}" + "  ·  ".join(celdas))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
