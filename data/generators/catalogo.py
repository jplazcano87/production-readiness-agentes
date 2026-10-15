"""Capa programática: 200 productos en 6 categorías.

Determinista por semilla. Los precios están en pesos chilenos y en rangos plausibles por
categoría; los atributos son coherentes con su categoría (un televisor no lleva memoria
RAM) porque las restricciones de los casos de robustez se derivan de esos atributos: un
catálogo incoherente produciría casos imposibles o triviales.

Las marcas son topónimos chilenos usados como nombres de fantasía. No corresponden a
ninguna organización real, en línea con la decisión de datos 100 % sintéticos.
"""

from __future__ import annotations

import random
from typing import Any

N_PRODUCTOS = 200

# Factor de dispersión del precio en torno al centro de cada rango.
ESTIRAMIENTO = 2.1

# Reparto por categoría. Suma exactamente N_PRODUCTOS.
REPARTO: dict[str, int] = {
    "notebooks": 40,
    "celulares": 40,
    "audifonos": 30,
    "televisores": 30,
    "electrodomesticos_cocina": 30,
    "hogar_inteligente": 30,
}

MARCAS: dict[str, list[str]] = {
    "notebooks": ["Aurora", "Cordillera", "Elqui", "Patagonia", "Nahuel"],
    "celulares": ["Loa", "Maipo", "Biobío", "Aysén", "Copiapó"],
    "audifonos": ["Chinchorro", "Tongoy", "Rapa", "Chiloé"],
    "televisores": ["Atacama", "Valdivia", "Osorno", "Pucón"],
    "electrodomesticos_cocina": ["Curicó", "Limarí", "Choapa", "Itata"],
    "hogar_inteligente": ["Lauca", "Futaleufú", "Baker", "Petorca"],
}

# Rango de precio en CLP por categoría (mínimo, máximo).
PRECIOS: dict[str, tuple[int, int]] = {
    "notebooks": (349_990, 2_499_990),
    "celulares": (119_990, 1_399_990),
    "audifonos": (14_990, 449_990),
    "televisores": (179_990, 2_199_990),
    "electrodomesticos_cocina": (24_990, 799_990),
    "hogar_inteligente": (12_990, 349_990),
}

# Atributos por categoría: cada uno con su dominio de valores posibles.
ATRIBUTOS: dict[str, dict[str, list[Any]]] = {
    "notebooks": {
        "ram_gb": [8, 16, 32, 64],
        "ssd_gb": [256, 512, 1024, 2048],
        "pantalla_pulgadas": [13.3, 14.0, 15.6, 16.0],
        "procesador": ["Serie 3", "Serie 5", "Serie 7", "Serie 9"],
        "peso_kg": [1.1, 1.3, 1.6, 2.1],
    },
    "celulares": {
        "almacenamiento_gb": [64, 128, 256, 512],
        "ram_gb": [4, 6, 8, 12],
        "pantalla_pulgadas": [6.1, 6.4, 6.7, 6.9],
        "camara_mp": [12, 48, 50, 108],
        "bateria_mah": [3800, 4500, 5000, 6000],
    },
    "audifonos": {
        "tipo": ["in-ear", "over-ear", "true wireless"],
        "cancelacion_ruido": [True, False],
        "autonomia_horas": [6, 12, 24, 40],
        "inalambrico": [True, False],
        "resistencia_agua": ["ninguna", "IPX4", "IPX7"],
    },
    "televisores": {
        "pulgadas": [32, 43, 50, 55, 65, 75],
        "resolucion": ["HD", "Full HD", "4K", "8K"],
        "tecnologia": ["LED", "QLED", "OLED"],
        "smart_tv": [True, False],
        "hdr": [True, False],
    },
    "electrodomesticos_cocina": {
        "tipo": ["licuadora", "hervidor", "microondas", "freidora de aire", "cafetera"],
        "potencia_w": [600, 900, 1200, 1800],
        "capacidad_litros": [0.5, 1.2, 2.5, 5.0],
        "material": ["acero inoxidable", "plástico reforzado", "vidrio templado"],
    },
    "hogar_inteligente": {
        "tipo": ["ampolleta", "enchufe", "sensor de movimiento", "cámara", "parlante"],
        "protocolo": ["wifi", "zigbee", "matter"],
        "requiere_hub": [True, False],
        "alimentacion": ["red eléctrica", "batería recargable", "pilas"],
    },
}

# Coherencia interna: combinaciones que el generador nunca debe producir.
_INCOHERENCIAS = (
    # Unos audífonos con cancelación activa de ruido no son pasivos ni con cable barato.
    lambda cat, attrs: (
        cat == "audifonos" and attrs["cancelacion_ruido"] and not attrs["inalambrico"]
    ),
    # Un televisor 8K por debajo de 50 pulgadas no existe en el mercado.
    lambda cat, attrs: (
        cat == "televisores" and attrs["resolucion"] == "8K" and attrs["pulgadas"] < 50
    ),
    # Un hervidor no tiene 5 litros de capacidad ni una ampolleta necesita hub y pilas.
    lambda cat, attrs: (
        cat == "electrodomesticos_cocina"
        and attrs["tipo"] == "hervidor"
        and attrs["capacidad_litros"] > 2.5
    ),
    lambda cat, attrs: (
        cat == "hogar_inteligente"
        and attrs["tipo"] == "ampolleta"
        and attrs["alimentacion"] != "red eléctrica"
    ),
)


def _atributos_coherentes(rng: random.Random, categoria: str) -> dict[str, Any]:
    """Sortea atributos hasta que la combinación sea coherente para la categoría."""
    dominio = ATRIBUTOS[categoria]
    for _ in range(50):
        candidato = {clave: rng.choice(valores) for clave, valores in dominio.items()}
        if not any(regla(categoria, candidato) for regla in _INCOHERENCIAS):
            return candidato
    return candidato  # pragma: no cover - 50 intentos no fallan con estos dominios


def _precio_redondeado(bruto: float) -> int:
    """Redondea a la baja al millar y deja la terminación 990, como en el retail chileno."""
    miles = max(1, int(bruto // 1000))
    return miles * 1000 - 10 if miles * 1000 - 10 > 0 else 990


def generar_productos(seed: int) -> list[dict[str, Any]]:
    """Los 200 esqueletos de producto. El nombre y la descripción los redacta el LLM."""
    rng = random.Random(seed)
    productos: list[dict[str, Any]] = []
    indice = 0

    for categoria, cantidad in REPARTO.items():
        marcas = MARCAS[categoria]
        minimo, maximo = PRECIOS[categoria]
        dominio = ATRIBUTOS[categoria]
        for n in range(cantidad):
            indice += 1
            atributos = _atributos_coherentes(rng, categoria)
            posiciones = [
                dominio[clave].index(valor) / max(1, len(dominio[clave]) - 1)
                for clave, valor in atributos.items()
                if valor in dominio[clave] and len(dominio[clave]) > 1
            ]
            nivel = sum(posiciones) / len(posiciones) if posiciones else 0.5
            # La media de varias posiciones se concentra en 0,5 (efecto del promedio) y
            # dejaría vacíos los extremos de cada rango de precio, justo donde viven los
            # casos con presupuesto ajustado. Se estira en torno al centro antes de acotar.
            proporcion = min(
                1.0, max(0.0, (nivel - 0.5) * ESTIRAMIENTO + 0.5 + rng.uniform(-0.08, 0.08))
            )
            precio = _precio_redondeado(minimo + proporcion * (maximo - minimo))

            marca = marcas[n % len(marcas)]
            productos.append(
                {
                    "id": f"P{indice:04d}",
                    # Nombre provisional: la capa LLM lo reemplaza por uno comercial.
                    "name": f"{marca} {categoria.replace('_', ' ')} modelo {n + 1:02d}",
                    "category": categoria,
                    "brand": marca,
                    "price_clp": precio,
                    "attributes": atributos,
                    "stock": rng.randint(0, 40),
                    # La evaluación promedio sube levemente con el nivel del producto,
                    # pero con ruido: no debe ser una función determinista del precio.
                    "avg_rating": round(
                        min(5.0, max(3.0, 3.4 + nivel * 1.2 + rng.uniform(-0.4, 0.4))), 1
                    ),
                    "description": "",
                }
            )
    return productos


__all__ = [
    "ATRIBUTOS",
    "ESTIRAMIENTO",
    "MARCAS",
    "N_PRODUCTOS",
    "PRECIOS",
    "REPARTO",
    "generar_productos",
]
