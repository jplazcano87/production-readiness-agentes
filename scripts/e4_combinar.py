"""Combina la reverificación de E4 con la corrida del ítem nuevo, sin llamar a la API.

    python scripts/e4_combinar.py --config none

El checklist 1.2.0 añade un ítem y no toca ninguno de los anteriores, así que E4 no se repite:
las 125 transcripciones de cada configuración se **reverifican** —misma evidencia, verificadores
de ahora— y solo el caso del ítem nuevo se ejecuta. Este script une las dos mitades.

La unión no es un `dict.update`. Hay dos cosas que tienen que venir de la corrida completa y no
de la del ítem nuevo:

- **Los ítems de tolerancia cero**, que se evalúan sobre *todas* las ejecuciones. Con una
  corrida de un solo caso saldrían violados por falta de evidencia, no por incumplimiento.
- **Los dos ítems de datos personales**, que la reverificación conserva del original porque las
  transcripciones se persisten redactadas.

Del documento del ítem nuevo se toma **solo ese ítem**. Todo lo demás se descarta, y el `resumen`
se recalcula sobre el resultado de la unión.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from prf.compliance import cargar_checklist
from prf.infra.results import read_result, write_result
from run_e4 import resumen

ITEM_NUEVO = "INFORMACION_VERAZ_RESULTADOS"


def main(argv: list[str] | None = None) -> int:
    """Combina los documentos de cumplimiento de una configuración en uno solo."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--config", required=True, help="Configuración cuyos documentos se combinan."
    )
    parser.add_argument(
        "--item", default=ITEM_NUEVO, help="Identificador del ítem que aporta el documento nuevo."
    )
    args = parser.parse_args(argv)

    reverificado = read_result(f"e4_reverificado_checklist1.2.0_{args.config}")
    del_item = read_result(f"e4_item_veracidad_{args.config}")
    version_checklist, _ = cargar_checklist()

    estado_anterior = reverificado["items"][args.item]["estado"]
    nuevo = del_item["items"][args.item]
    if nuevo["estado"] == "no_evaluable":
        raise SystemExit(
            f"{args.config}: el ítem {args.item} sigue sin evaluar en la corrida de su caso. "
            "No se combina nada."
        )

    metadata = dict(reverificado.pop("metadata"))
    metadata_item = del_item["metadata"]

    reverificado["items"][args.item] = nuevo
    reverificado["evidencia_por_caso"].update(del_item["evidencia_por_caso"])
    reverificado["resumen"] = resumen(reverificado["items"])
    reverificado["checklist_version"] = version_checklist

    metadata["n_casos"] = len(reverificado["evidencia_por_caso"])
    metadata["combinado"] = {
        "que_es": (
            "Los ítems anteriores vienen de reverificar sin API las transcripciones de la "
            "corrida de E4 con el checklist 1.1.0, que dieron exactamente el mismo resultado; "
            f"el ítem {args.item} viene de la corrida de su propio caso."
        ),
        "sin_llamadas_api": True,
        "reverificacion": {
            "origen": metadata["repuntuado"]["origen"],
            "checklist_antes": metadata["repuntuado"]["checklist_antes"],
            "items_cambiados": metadata["repuntuado"]["items_cambiados"],
        },
        "item_nuevo": {
            "id": args.item,
            "origen": f"results/e4_item_veracidad_{args.config}.json",
            "estado_antes": estado_anterior,
            "estado": nuevo["estado"],
            "casos": metadata_item.get("case_ids"),
            "n_runs_por_caso": metadata_item.get("n_runs_por_caso"),
            "agent_version": metadata_item.get("agent_version"),
            "corpus_version": metadata_item.get("corpus_version"),
            # La corrida que produjo estas transcripciones **abortó por el tope de gasto**
            # —la estimación de E4 está calibrada para los 26 casos y subestima una corrida de
            # uno solo, donde la caché no se amortiza— así que ningún archivo registró su
            # costo. El resultado se ensambló después con `--reanudar`, a coste cero, sobre
            # las transcripciones que sí quedaron en disco. Lo que se declara es la última
            # lectura del ledger antes de cada aborto, que es una **cota inferior**.
            "costo_usd_real": metadata_item.get("costo_usd_real"),
            "costo_usd_de_las_ejecuciones": {
                "cota_inferior_usd": 0.59,
                "por_que_no_es_exacto": (
                    "las cuatro corridas abortaron por el tope de gasto antes de escribir su "
                    "resultado, y la cifra es la suma de la última lectura del ledger de cada "
                    "una (0,16 + 0,16 + 0,15 + 0,12), tomada cuando faltaban una o dos "
                    "ejecuciones por registrar"
                ),
                "estimacion_usd": 0.1149,
            },
        },
        "tomados_de_la_corrida_completa": [
            "los ítems de tolerancia cero, que se evalúan sobre todas las ejecuciones",
            "los dos ítems de datos personales, que la reverificación conserva del original",
        ],
    }
    archivo = write_result(f"e4_compliance_checklist1.2.0_{args.config}", reverificado, metadata)

    conteo = reverificado["resumen"]
    print(f"{args.config}: {args.item} {estado_anterior} -> {nuevo['estado']}")
    print(
        f"  críticos {conteo['n_criticos_pass']}/{conteo['n_criticos']} · "
        f"inestables {conteo['n_inestables']} · cumple {conteo['cumple']}"
    )
    if conteo["items_criticos_no_pass"]:
        print(f"  críticos no aprobados: {', '.join(conteo['items_criticos_no_pass'])}")
    print(f"  escrito en {archivo.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
