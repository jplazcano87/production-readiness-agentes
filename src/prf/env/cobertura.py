"""¿La intención comunica las restricciones que el caso exige?

`evaluate_state` juzga una recomendación contra `target_state.constraints`. Si el texto de
la intención no menciona una de esas restricciones, el caso exige información que nunca
entregó y el fallo es del corpus, no del agente. Es lo que ocurrió con `ROB-BUS-014` en
v1.0, que fallaba 0/8 en las tres configuraciones.

Qué se comprueba y qué no:

- **Presupuesto**: la cifra debe aparecer en el texto, en cualquiera de las formas en que se
  escribe un precio en Chile («$1.766.990», «1766990», «1 millón 766 mil», «1,77 millones»).
  Es comprobable de forma exacta.
- **Categoría**: debe aparecer el nombre de la categoría o alguno de sus sinónimos naturales.
- **Atributos numéricos**: debe aparecer el valor exigido («32» para `ram_gb: {min: 32}`).
- **Atributos de texto**: debe aparecer el valor («freidora de aire»).
- **Atributos booleanos**: **no se comprueban**. «cancelacion_ruido: true» se expresa de
  demasiadas formas («que aísle el ruido», «para concentrarme») y exigir una cadena concreta
  produciría falsos positivos que ensuciarían la verificación de lo que sí es comprobable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from prf.env.catalog import normalizar
from prf.env.target import Constraints

# 5 %: al declarar un presupuesto la gente redondea («23 mil» por $23.990, «casi dos
# millones» por $1.973.990). Exigir la cifra exacta marcaría como defecto una forma de
# hablar perfectamente clara, y redondear a la baja además deja al agente del lado seguro.
TOLERANCIA_PRECIO = 0.05

# Cantidades que se escriben con palabras al hablar de dinero.
NUMEROS_ESCRITOS: dict[str, float] = {
    "medio": 0.5,
    "un": 1.0,
    "uno": 1.0,
    "una": 1.0,
    "dos": 2.0,
    "tres": 3.0,
    "cuatro": 4.0,
    "cinco": 5.0,
    "seis": 6.0,
    "siete": 7.0,
    "ocho": 8.0,
    "nueve": 9.0,
    "diez": 10.0,
}

SINONIMOS_CATEGORIA: dict[str, tuple[str, ...]] = {
    "notebooks": ("notebook", "computador", "laptop", "portatil"),
    "celulares": ("celular", "telefono", "smartphone"),
    "audifonos": ("audifono", "auricular"),
    "televisores": ("televisor", "tele", "tv", "pantalla"),
    "electrodomesticos_cocina": (
        "cocina",
        "licuadora",
        "hervidor",
        "microondas",
        "freidora",
        "cafetera",
        "electrodomestico",
    ),
    "hogar_inteligente": (
        "inteligente",
        "domotica",
        "ampolleta",
        "enchufe",
        "sensor",
        "camara",
        "parlante",
    ),
}


@dataclass(frozen=True)
class Falta:
    """Una restricción que el texto de la intención no comunica."""

    tipo: str  # presupuesto | categoria | atributo
    detalle: str
    valor: object

    def __str__(self) -> str:
        return f"{self.tipo}: {self.detalle}"


def cifras_del_texto(texto: str) -> set[float]:
    """Cantidades que un lector reconocería en el texto, en formato numérico chileno.

    En español de Chile el punto separa miles y la coma decimales, pero en la práctica
    también se escribe «1.3 kilos» a la inglesa. Se resuelve por la longitud del grupo: tres
    dígitos tras el punto son miles («1.766.990»), uno o dos son decimales («1.3»). Sin esa
    distinción, «pesa 1.3 kilos» se leería como trece.
    """
    encontradas: set[float] = set()
    for crudo in re.findall(r"\d[\d.,]*\d|\d", texto):
        entero, _, decimal = crudo.partition(",")
        if not decimal and "." in entero:
            cabeza, _, cola = entero.rpartition(".")
            if len(cola) in (1, 2) and cabeza.replace(".", "").isdigit() and cola.isdigit():
                entero, decimal = cabeza, cola
        entero = entero.replace(".", "")
        if not entero.isdigit():
            continue
        if decimal and decimal.replace(".", "").isdigit():
            encontradas.add(float(f"{entero}.{decimal.replace('.', '')}"))
        else:
            encontradas.add(float(entero))

    bajo = texto.lower()
    # Cantidades escritas con palabras: «dos millones», «medio millón». Es como se declara
    # un presupuesto en una conversación, y omitirlo daría falsos positivos.
    # «1 kilo 300 gramos» es 1,3 kg: una forma habitual de dar un peso.
    for kilos, gramos in re.findall(r"(\d+)\s*kilos?\s*(\d+)\s*gramos?", bajo):
        encontradas.add(int(kilos) + int(gramos) / 1000)
    for palabra, valor in NUMEROS_ESCRITOS.items():
        for _ in re.finditer(rf"\b{palabra}\s+(?:millones|millón|millon)\b", bajo):
            encontradas.add(valor * 1_000_000)
        for _ in re.finditer(rf"\b{palabra}\s+mil\b", bajo):
            encontradas.add(valor * 1000)
    # «1 millón 766 mil» antes que las formas simples, para no partirla en dos.
    for millones, miles in re.findall(r"(\d+)\s*(?:millones|millón|millon)\s*(\d+)\s*mil", bajo):
        encontradas.add(float(int(millones) * 1_000_000 + int(miles) * 1000))
    # Alternancia de mayor a menor: «mil» primero capturaría el prefijo de «millones».
    for valor, palabra in re.findall(r"(\d+(?:[.,]\d+)?)\s*(millones|millón|millon|mil)", bajo):
        numero = float(valor.replace(".", "").replace(",", "."))
        encontradas.add(numero * (1000 if palabra == "mil" else 1_000_000))
    return encontradas


def menciona_cifra(texto: str, objetivo: float, tolerancia: float = TOLERANCIA_PRECIO) -> bool:
    """¿El texto menciona esa cantidad, admitiendo redondeos?"""
    return any(
        abs(cifra - objetivo) <= objetivo * tolerancia
        for cifra in cifras_del_texto(texto)
        if cifra > 1000
    )


def menciona_categoria(texto: str, categoria: str, nombres: tuple[str, ...] = ()) -> bool:
    """¿El texto identifica la categoría?

    `nombres` son los nombres comerciales de los productos que el caso exige comparar. Si
    el usuario nombra dos productos concretos, la categoría queda comunicada aunque no
    escriba la palabra: la información está y el agente puede usarla.
    """
    normalizado = normalizar(texto)
    if normalizar(categoria.replace("_", " ")) in normalizado:
        return True
    if any(s in normalizado for s in SINONIMOS_CATEGORIA.get(categoria, ())):
        return True
    return any(nombre and normalizar(nombre) in normalizado for nombre in nombres)


def _valores_exigidos(requisito: object) -> list[object]:
    if isinstance(requisito, dict):
        return [v for clave, v in requisito.items() if clave in ("min", "max")] + list(
            requisito.get("en", [])
        )
    return [requisito]


def faltas(
    intent: str, constraints: Constraints, nombres_citados: tuple[str, ...] = ()
) -> list[Falta]:
    """Restricciones que el texto no comunica. Lista vacía = el caso es resoluble."""
    problemas: list[Falta] = []

    if constraints.presupuesto_max_clp and not menciona_cifra(
        intent, constraints.presupuesto_max_clp
    ):
        problemas.append(
            Falta("presupuesto", "el tope no aparece en el texto", constraints.presupuesto_max_clp)
        )
    if constraints.presupuesto_min_clp and not menciona_cifra(
        intent, constraints.presupuesto_min_clp
    ):
        problemas.append(
            Falta("presupuesto", "el piso no aparece en el texto", constraints.presupuesto_min_clp)
        )
    if constraints.categoria and not menciona_categoria(
        intent, constraints.categoria, nombres_citados
    ):
        problemas.append(
            Falta(
                "categoria",
                f"no se nombra la categoría {constraints.categoria!r}",
                constraints.categoria,
            )
        )

    normalizado = normalizar(intent)
    for clave, requisito in constraints.atributos.items():
        for valor in _valores_exigidos(requisito):
            if isinstance(valor, bool):
                continue  # ver el docstring del módulo
            if isinstance(valor, (int, float)):
                if (
                    not any(abs(c - valor) < 1e-9 for c in cifras_del_texto(intent))
                    and normalizar(str(valor).replace(".", ",")) not in normalizado
                ):
                    problemas.append(
                        Falta("atributo", f"{clave} = {valor} no aparece en el texto", valor)
                    )
            elif isinstance(valor, str) and normalizar(valor) not in normalizado:
                problemas.append(
                    Falta("atributo", f"{clave} = {valor!r} no aparece en el texto", valor)
                )
    return problemas


__all__ = [
    "Falta",
    "SINONIMOS_CATEGORIA",
    "cifras_del_texto",
    "faltas",
    "menciona_categoria",
    "menciona_cifra",
]
