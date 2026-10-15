"""Sandbox sintético de ecommerce: catálogo, herramientas, estado y evaluador.

Ninguna pieza de este paquete llama a la API ni usa azar: dado el mismo catálogo, los
mismos argumentos producen el mismo resultado, y dado el mismo estado final, el mismo
veredicto. Es la condición para que pass^k (etapa 5) mida el no determinismo del agente
y no el del entorno.
"""

from prf.env.cases import (
    Caso,
    CasoCumplimiento,
    CasoRobustez,
    CasoSeguridad,
    CriterioAtaque,
    caso_desde_dict,
    productos_alcanzables,
    validate_target_reachable,
)
from prf.env.catalog import Catalog, cumple_atributo, normalizar
from prf.env.cobertura import Falta, faltas, menciona_categoria, menciona_cifra
from prf.env.evaluator import (
    EVALUATOR_VERSION,
    Evaluacion,
    evaluate_state,
    violaciones_de_constraints,
)
from prf.env.models import Origen, Product, Review, ToolCall
from prf.env.sandbox import Sandbox, ToolError
from prf.env.state import EnvState, FinalState, extraer_recomendaciones, limpiar_marcadores
from prf.env.target import Constraints, TargetState
from prf.env.tools import (
    HERRAMIENTAS,
    HERRAMIENTAS_LECTURA,
    HERRAMIENTAS_RESTRINGIDAS,
    tool_schemas,
)

__all__ = [
    "EVALUATOR_VERSION",
    "HERRAMIENTAS",
    "HERRAMIENTAS_LECTURA",
    "HERRAMIENTAS_RESTRINGIDAS",
    "Caso",
    "CasoCumplimiento",
    "CasoRobustez",
    "CasoSeguridad",
    "Catalog",
    "Constraints",
    "CriterioAtaque",
    "EnvState",
    "Falta",
    "Evaluacion",
    "FinalState",
    "Origen",
    "Product",
    "Review",
    "Sandbox",
    "TargetState",
    "ToolCall",
    "ToolError",
    "caso_desde_dict",
    "cumple_atributo",
    "evaluate_state",
    "faltas",
    "extraer_recomendaciones",
    "limpiar_marcadores",
    "menciona_categoria",
    "menciona_cifra",
    "normalizar",
    "productos_alcanzables",
    "tool_schemas",
    "validate_target_reachable",
    "violaciones_de_constraints",
]
