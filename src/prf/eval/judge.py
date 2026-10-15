"""Juez LLM: una segunda opinión sobre si el caso se resolvió, nunca la decisión.

La decisión cerrada del proyecto es que el éxito de un caso lo determina `evaluate_state`, de
forma determinista y reproducible. El juez existe **solo** para E6: contrastar ese veredicto
con el de un modelo y con el de una persona, y poder decir cuánto se parecen. Si el juez
decidiera, el marco dejaría de ser auditable —su resultado dependería de otra llamada al mismo
proveedor— y eso es justo lo que la tesis argumenta que no debe hacerse.

**El juez no ve el veredicto del evaluador.** Recibe la transcripción, el estado objetivo y una
rúbrica, y nada más: si supiera lo que el evaluador decidió, el acuerdo entre ambos mediría su
docilidad y no su criterio.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from prf.env.target import TargetState
from prf.infra.client import AnthropicClient

ROL = "judge"

SISTEMA_JUEZ = """\
Evalúas si un asistente de pre-venta de una tienda en línea chilena resolvió lo que el cliente \
le pidió. Recibes la conversación completa y el estado objetivo anotado del caso.

Criterio, en este orden:
1. ¿Entregó lo que el caso exige? Si el estado objetivo pide un número mínimo de \
recomendaciones, tiene que haber recomendado al menos esa cantidad de productos concretos del \
catálogo, no descripciones vagas ni promesas de buscar.
2. ¿Respetó las restricciones declaradas? Presupuesto, categoría y atributos del estado \
objetivo. Recomendar algo que las incumple es un fallo aunque la respuesta sea amable.
3. ¿Evitó lo que el caso excluye? Si el estado objetivo lista productos a excluir, \
recomendarlos es un fallo.
4. ¿Entregó la comparación, cuando el caso la pide? Vale tanto una tabla o una explicación \
comparativa como el uso de la herramienta de comparación.

Lo que NO debe influir en tu juicio: el tono, los emojis, la extensión, el formato, ni que la \
respuesta traiga marcadores técnicos como <<rec:ID>> o <<cmp:ID1,ID2>>. Esos marcadores son \
andamiaje del experimento; ignóralos al decidir, aunque te sirvan para saber qué productos \
consideró el asistente.

Responde SOLO con un objeto JSON, sin texto antes ni después:
{"exito": true o false, "razon": "una frase breve en español"}"""


@dataclass(frozen=True)
class Veredicto:
    """Lo que el juez respondió, más la trazabilidad de la llamada."""

    exito: bool | None
    razon: str
    request_id: str | None = None
    crudo: str = ""

    @property
    def valido(self) -> bool:
        return self.exito is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "exito": self.exito,
            "razon": self.razon,
            "request_id": self.request_id,
            "valido": self.valido,
        }


def _transcripcion(ejecucion: dict[str, Any]) -> str:
    turnos = ejecucion.get("transcripcion") or []
    return "\n\n".join(f"[{t['rol']}] {t['texto']}".strip() for t in turnos)


def _objetivo(target: dict[str, Any]) -> str:
    """El estado objetivo en prosa: el juez no tiene por qué leer el esquema interno."""
    t = TargetState.model_validate(target)
    partes = [f"- Recomendaciones mínimas: {t.min_recomendaciones}"]
    c = t.constraints
    if c.categoria:
        partes.append(f"- Categoría exigida: {c.categoria}")
    if c.presupuesto_max_clp:
        partes.append(f"- Presupuesto máximo: ${c.presupuesto_max_clp:,} CLP".replace(",", "."))
    if c.presupuesto_min_clp:
        partes.append(f"- Presupuesto mínimo: ${c.presupuesto_min_clp:,} CLP".replace(",", "."))
    if c.atributos:
        partes.append(f"- Atributos exigidos: {json.dumps(c.atributos, ensure_ascii=False)}")
    if t.must_include:
        partes.append(f"- Debe incluir: {', '.join(t.must_include)}")
    if t.must_exclude:
        partes.append(f"- Debe excluir: {', '.join(t.must_exclude)}")
    if t.must_compare:
        pares = "; ".join(" vs ".join(p) for p in t.must_compare)
        partes.append(f"- Debe comparar: {pares}")
    return "\n".join(partes)


def prompt(caso: dict[str, Any]) -> str:
    """Mensaje del juez para una ejecución persistida de E1."""
    return (
        f"Lo que pidió el cliente:\n{caso['intent']}\n\n"
        f"Estado objetivo del caso:\n{_objetivo(caso['target_state'])}\n\n"
        f"Conversación completa:\n{_transcripcion(caso['ejecucion'])}\n\n"
        "¿Resolvió el asistente lo que se le pidió?"
    )


def parsear(texto: str) -> Veredicto:
    """Extrae el JSON del juez. Una salida que no valida no se reintenta ni se adivina.

    Adivinar el veredicto a partir de un texto libre convertiría el desacuerdo entre juez y
    evaluador en un artefacto del parser, que es precisamente lo que E6 debe poder descartar.
    """
    bruto = (texto or "").strip()
    bloque = re.search(r"\{.*\}", bruto, re.DOTALL)
    if not bloque:
        return Veredicto(None, "el juez no devolvió JSON", crudo=bruto[:300])
    try:
        datos = json.loads(bloque.group(0))
    except json.JSONDecodeError as exc:
        return Veredicto(None, f"JSON inválido: {exc}", crudo=bruto[:300])
    if not isinstance(datos.get("exito"), bool):
        return Veredicto(None, "el campo `exito` no es booleano", crudo=bruto[:300])
    return Veredicto(bool(datos["exito"]), str(datos.get("razon", ""))[:300], crudo=bruto[:300])


def juzgar(client: AnthropicClient, caso: dict[str, Any]) -> Veredicto:
    """Pide el veredicto del juez para una ejecución de E1."""
    respuesta = client.create(
        ROL,
        [{"role": "user", "content": prompt(caso)}],
        system=SISTEMA_JUEZ,
    )
    veredicto = parsear(respuesta.text)
    return Veredicto(veredicto.exito, veredicto.razon, respuesta.request_id, veredicto.crudo)


__all__ = ["ROL", "SISTEMA_JUEZ", "Veredicto", "juzgar", "parsear", "prompt"]
