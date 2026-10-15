"""Capa programática: 60 casos de robustez (20 búsqueda, 20 comparación, 20 recomendación).

Cada caso lleva su `target_state` **derivado del catálogo**, no inventado: las
restricciones se construyen a partir de un producto que existe, de modo que
`validate_target_reachable` pase por construcción y no por suerte.

Una decisión que condiciona todo el diseño: en búsqueda y en recomendación por necesidad
`must_include` va **vacío**. Varios productos del catálogo son respuestas legítimas, y
exigir uno concreto convertiría en fallo una recomendación correcta. Lo que se exige es
`min_recomendaciones=1` más el cumplimiento de las restricciones, y un `must_exclude` con
un producto que incumple exactamente una de ellas: así el caso distingue a un agente que
respeta el presupuesto de uno que lo ignora. En comparación sí hay ids concretos, porque
el usuario nombra los dos productos que quiere comparar.
"""

from __future__ import annotations

import random
from typing import Any

from prf.env import Catalog, Constraints, TargetState, validate_target_reachable

N_POR_TIPO = 20

# Necesidades que dan pie a una recomendación, con la categoría y el atributo que las
# hacen verificables. El texto natural lo redacta el LLM a partir de esta estructura.
NECESIDADES: list[dict[str, Any]] = [
    {
        "escenario": "editar video en 4K sin que el equipo se pegue",
        "categoria": "notebooks",
        "atributo": "ram_gb",
        "minimo": 32,
    },
    {
        "escenario": "programar y correr contenedores todo el día",
        "categoria": "notebooks",
        "atributo": "ram_gb",
        "minimo": 16,
    },
    {
        "escenario": "llevar el computador en la mochila a diario",
        "categoria": "notebooks",
        "atributo": "peso_kg",
        "maximo": 1.3,
    },
    {
        "escenario": "guardar muchas fotos y videos del celular",
        "categoria": "celulares",
        "atributo": "almacenamiento_gb",
        "minimo": 256,
    },
    {
        "escenario": "que la batería aguante un turno largo sin cargador",
        "categoria": "celulares",
        "atributo": "bateria_mah",
        "minimo": 5000,
    },
    {
        "escenario": "sacar buenas fotos en los paseos familiares",
        "categoria": "celulares",
        "atributo": "camara_mp",
        "minimo": 50,
    },
    {
        "escenario": "concentrarse en una oficina ruidosa",
        "categoria": "audifonos",
        "atributo": "cancelacion_ruido",
        "valor": True,
    },
    {
        "escenario": "escuchar música en viajes largos sin recargar",
        "categoria": "audifonos",
        "atributo": "autonomia_horas",
        "minimo": 24,
    },
    {
        "escenario": "ver películas en el living con buena imagen",
        "categoria": "televisores",
        "atributo": "resolucion",
        "valor": "4K",
    },
    {
        "escenario": "un televisor grande para el departamento",
        "categoria": "televisores",
        "atributo": "pulgadas",
        "minimo": 55,
    },
    {
        "escenario": "cocinar más sano friendo con poco aceite",
        "categoria": "electrodomesticos_cocina",
        "atributo": "tipo",
        "valor": "freidora de aire",
    },
    {
        "escenario": "preparar café todas las mañanas en la casa",
        "categoria": "electrodomesticos_cocina",
        "atributo": "tipo",
        "valor": "cafetera",
    },
    {
        "escenario": "controlar las luces desde el teléfono",
        "categoria": "hogar_inteligente",
        "atributo": "tipo",
        "valor": "ampolleta",
    },
    {
        "escenario": "vigilar la entrada de la casa cuando no hay nadie",
        "categoria": "hogar_inteligente",
        "atributo": "tipo",
        "valor": "cámara",
    },
    {
        "escenario": "empezar con domótica sin instalar un hub aparte",
        "categoria": "hogar_inteligente",
        "atributo": "requiere_hub",
        "valor": False,
    },
]

PERSONAS = [
    "estudiante universitario con presupuesto ajustado",
    "profesional que trabaja desde la casa",
    "madre que compra un regalo para su hijo",
    "jubilado que quiere algo simple de usar",
    "persona que arrienda departamento y recién se está equipando",
    "trabajador independiente que necesita la herramienta para producir",
]


# Holguras de presupuesto (percentil del precio entre los candidatos) para los casos de
# búsqueda, y modificadores de restricción para los de recomendación.
PERCENTILES_PRESUPUESTO = (0.45, 0.60, 0.80)
VARIANTES_RECOMENDACION = ("sin_presupuesto", "con_tope", "con_piso")


def _combinaciones(necesidades: list[dict[str, Any]], variantes: tuple[Any, ...]):
    """Producto cartesiano en orden estable: (necesidad, variante)."""
    for variante in variantes:
        for necesidad in necesidades:
            yield necesidad, variante


def _aplicar_variante(catalog: Catalog, base: Constraints, variante: str) -> Constraints | None:
    """Añade a la restricción base el modificador de presupuesto de la variante."""
    if variante == "sin_presupuesto":
        return base
    if variante == "con_tope":
        tope = _percentil_precio(catalog, base, 0.65)
        if tope is None:
            return None
        return base.model_copy(update={"presupuesto_max_clp": tope})
    piso = _percentil_precio(catalog, base, 0.30)
    if piso is None:
        return None
    return base.model_copy(update={"presupuesto_min_clp": piso})


def requisito(necesidad: dict[str, Any]) -> dict[str, Any]:
    """Traduce una necesidad al formato de restricción por atributo."""
    if "minimo" in necesidad:
        return {necesidad["atributo"]: {"min": necesidad["minimo"]}}
    if "maximo" in necesidad:
        return {necesidad["atributo"]: {"max": necesidad["maximo"]}}
    return {necesidad["atributo"]: necesidad["valor"]}


def _percentil_precio(catalog: Catalog, restricciones: Constraints, percentil: float) -> int | None:
    """Precio en el percentil dado entre los candidatos que cumplen las restricciones.

    Un tope de presupuesto debe dejar pasar a parte de los candidatos pero no a todos: si
    los descarta a todos el caso es imposible, y si los acepta a todos no distingue a un
    agente que respeta el presupuesto de uno que lo ignora. El percentil además varía por
    caso, para que dos casos con la misma necesidad no acaben siendo el mismo caso.
    """
    candidatos = catalog.buscar(
        "",
        category=restricciones.categoria,
        attributes=restricciones.atributos or None,
    )
    if len(candidatos) < 3:
        return None
    precios = sorted(p.price_clp for p in candidatos)
    return precios[min(len(precios) - 1, int(len(precios) * percentil))]


def _excluido_que_incumple(
    catalog: Catalog, restricciones: Constraints, evitar: set[str]
) -> str | None:
    """Un producto de la misma categoría que incumple alguna restricción.

    Es el señuelo del caso: si el agente lo recomienda, es que ignoró lo que el usuario
    pidió. Sin él, la regla `must_exclude` no tendría nada que atrapar.
    """
    for producto in catalog.buscar("", category=restricciones.categoria):
        if producto.id in evitar:
            continue
        supera_precio = (
            restricciones.presupuesto_max_clp is not None
            and producto.price_clp > restricciones.presupuesto_max_clp
        )
        if supera_precio:
            return producto.id
    return None


def generar_casos_robustez(catalog: Catalog, seed: int) -> list[dict[str, Any]]:
    """60 esqueletos de caso de robustez, sin el texto de la intención."""
    rng = random.Random(seed)
    casos: list[dict[str, Any]] = []
    casos.extend(_casos_busqueda(catalog, rng))
    casos.extend(_casos_comparacion(catalog, rng))
    casos.extend(_casos_recomendacion(catalog, rng))
    return casos


def _casos_busqueda(catalog: Catalog, rng: random.Random) -> list[dict[str, Any]]:
    """Búsqueda con restricciones: categoría, presupuesto y un atributo técnico."""
    casos: list[dict[str, Any]] = []
    n = 0
    # Cada necesidad se combina con tres holguras de presupuesto distintas: 45 casos
    # candidatos para elegir 20, todos con un `target_state` diferente.
    for necesidad, percentil in _combinaciones(NECESIDADES, PERCENTILES_PRESUPUESTO):
        if n >= N_POR_TIPO:
            break
        base = Constraints(categoria=necesidad["categoria"], atributos=requisito(necesidad))
        tope = _percentil_precio(catalog, base, percentil)
        if tope is None:
            continue
        restricciones = Constraints(
            categoria=necesidad["categoria"],
            atributos=requisito(necesidad),
            presupuesto_max_clp=tope,
        )
        alcanzables = catalog.buscar(
            "",
            category=restricciones.categoria,
            max_price=tope,
            attributes=restricciones.atributos,
        )
        if len(alcanzables) < 2:
            continue
        excluido = _excluido_que_incumple(catalog, restricciones, {p.id for p in alcanzables})
        if excluido is None:
            continue

        n += 1
        casos.append(
            {
                "case_id": f"ROB-BUS-{n:03d}",
                "tipo": "busqueda",
                "escenario": necesidad["escenario"],
                "persona": rng.choice(PERSONAS),
                "target_state": TargetState(
                    must_exclude=[excluido],
                    constraints=restricciones,
                    min_recomendaciones=1,
                ).model_dump(mode="json"),
                "productos_alcanzables": [p.id for p in alcanzables],
            }
        )
    return casos


def _casos_comparacion(catalog: Catalog, rng: random.Random) -> list[dict[str, Any]]:
    """Comparación: el usuario nombra dos productos concretos de la misma categoría."""
    casos: list[dict[str, Any]] = []
    categorias = catalog.categorias
    for n in range(1, N_POR_TIPO + 1):
        categoria = categorias[n % len(categorias)]
        candidatos = catalog.buscar("", category=categoria)
        # Dos productos separados en la lista: comparar dos casi idénticos no distingue
        # a un agente que compara de uno que responde cualquier cosa.
        a = candidatos[(n * 3) % len(candidatos)]
        b = candidatos[(n * 3 + len(candidatos) // 2) % len(candidatos)]
        if a.id == b.id:
            b = candidatos[(n * 3 + 1) % len(candidatos)]
        casos.append(
            {
                "case_id": f"ROB-CMP-{n:03d}",
                "tipo": "comparacion",
                "escenario": f"decidir entre {a.id} y {b.id} en {categoria}",
                "persona": rng.choice(PERSONAS),
                "target_state": TargetState(
                    must_compare=[(a.id, b.id)],
                    constraints=Constraints(categoria=categoria),
                    min_recomendaciones=1,
                ).model_dump(mode="json"),
                "productos_alcanzables": [a.id, b.id],
            }
        )
    return casos


def _casos_recomendacion(catalog: Catalog, rng: random.Random) -> list[dict[str, Any]]:
    """Recomendación por necesidad: el usuario describe para qué lo quiere, no qué quiere."""
    casos: list[dict[str, Any]] = []
    n = 0
    for necesidad, variante in _combinaciones(NECESIDADES, VARIANTES_RECOMENDACION):
        if n >= N_POR_TIPO:
            break
        base = Constraints(categoria=necesidad["categoria"], atributos=requisito(necesidad))
        restricciones = _aplicar_variante(catalog, base, variante)
        if restricciones is None:
            continue
        alcanzables = catalog.buscar(
            "",
            category=restricciones.categoria,
            max_price=restricciones.presupuesto_max_clp,
            min_price=restricciones.presupuesto_min_clp,
            attributes=restricciones.atributos,
        )
        if len(alcanzables) < 3:
            continue
        n += 1
        casos.append(
            {
                "case_id": f"ROB-REC-{n:03d}",
                "tipo": "recomendacion",
                "escenario": necesidad["escenario"],
                "persona": rng.choice(PERSONAS),
                "target_state": TargetState(
                    constraints=restricciones, min_recomendaciones=1
                ).model_dump(mode="json"),
                "productos_alcanzables": [p.id for p in alcanzables],
            }
        )
    return casos


def validar_casos(casos: list[dict[str, Any]], catalog: Catalog) -> list[str]:
    """Errores de alcanzabilidad. Lista vacía = el 100 % de los casos es alcanzable."""
    errores: list[str] = []
    for caso in casos:
        target = TargetState.model_validate(caso["target_state"])
        alcanzable, motivos = validate_target_reachable(target, catalog)
        if not alcanzable:
            errores.append(f"{caso['case_id']}: {'; '.join(motivos)}")
    return errores


__all__ = [
    "NECESIDADES",
    "PERCENTILES_PRESUPUESTO",
    "PERSONAS",
    "VARIANTES_RECOMENDACION",
    "generar_casos_robustez",
    "validar_casos",
]
