"""Agente de pre-venta y las cuatro configuraciones de defensa.

Las cuatro comparten el mismo arnés (`bucle.py`): `none`, `prompt_only` y `dual_llm` usan
el bucle de tool use, y `cte` lo sustituye por planificador más intérprete determinista. Que
compartan código es lo que permite atribuir una diferencia de ASR a la defensa y no a la
implementación.
"""

from prf.agent.bucle import Ejecucion, ejecutar_caso
from prf.agent.configuraciones import AGENT_VERSION, CONFIGURACIONES, Configuracion, obtener
from prf.agent.cte import Interprete, Plan, parsear_plan
from prf.agent.cuarentena import Cuarentena, ResumenResenas
from prf.agent.prompts import sistema_agente

__all__ = [
    "AGENT_VERSION",
    "CONFIGURACIONES",
    "Configuracion",
    "Cuarentena",
    "Ejecucion",
    "Interprete",
    "Plan",
    "ResumenResenas",
    "ejecutar_caso",
    "obtener",
    "parsear_plan",
    "sistema_agente",
]
