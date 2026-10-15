"""Catálogo del sandbox: productos, reseñas y la comparación de atributos.

El catálogo es de solo lectura durante una evaluación. El corpus se congela en la etapa 2
y nunca se regenera al evaluar (decisión cerrada), así que aquí no hay ninguna operación
que lo modifique.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from prf.env.models import Product, Review
from prf.infra.paths import paths


def normalizar(texto: str) -> str:
    """Minúsculas sin tildes, para que «audífonos» y «audifonos» sean lo mismo.

    Los usuarios sintéticos escriben en español de Chile con y sin tildes; hacer depender
    una búsqueda de eso introduciría fallos que no son del agente sino del sandbox.
    """
    descompuesto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")


def cumple_atributo(valor: Any, requisito: Any) -> bool:
    """¿El atributo `valor` satisface `requisito`?

    Tres formas, porque las restricciones del corpus no siempre son de igualdad
    («al menos 16 GB de RAM» no es «exactamente 16»):

    - escalar: igualdad (con texto, normalizada sin tildes ni mayúsculas);
    - `{"min": n}` / `{"max": n}`: comparación numérica, combinables;
    - `{"en": [a, b]}`: pertenencia a un conjunto.
    """
    if isinstance(requisito, dict):
        if "min" in requisito or "max" in requisito:
            if not isinstance(valor, (int, float)) or isinstance(valor, bool):
                return False
            if "min" in requisito and valor < requisito["min"]:
                return False
            if "max" in requisito and valor > requisito["max"]:
                return False
            return True
        if "en" in requisito:
            return any(cumple_atributo(valor, opcion) for opcion in requisito["en"])
        return False
    if isinstance(requisito, str) and isinstance(valor, str):
        return normalizar(valor) == normalizar(requisito)
    return valor == requisito


class Catalog(BaseModel):
    """Catálogo sintético: productos indexados por id y reseñas por producto."""

    model_config = ConfigDict(extra="forbid")

    products: list[Product] = Field(default_factory=list)
    reviews: list[Review] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        """Construye los índices por id y por producto. Lo llama pydantic al validar."""
        self._por_id: dict[str, Product] = {p.id: p for p in self.products}
        self._resenas_por_producto: dict[str, list[Review]] = {}
        for review in self.reviews:
            self._resenas_por_producto.setdefault(review.product_id, []).append(review)

    # ------------------------------------------------------------------ acceso

    def get(self, product_id: str) -> Product | None:
        return self._por_id.get(product_id)

    def existe(self, product_id: str) -> bool:
        return product_id in self._por_id

    def reviews_de(self, product_id: str) -> list[Review]:
        return list(self._resenas_por_producto.get(product_id, []))

    @property
    def categorias(self) -> list[str]:
        return sorted({p.category for p in self.products})

    def __len__(self) -> int:
        return len(self.products)

    # --------------------------------------------------------------- búsqueda

    def buscar(
        self,
        query: str = "",
        *,
        category: str | None = None,
        max_price: int | None = None,
        min_price: int | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> list[Product]:
        """Productos que cumplen todos los filtros, ordenados de forma determinista.

        El orden es `(-relevancia, id)`: sin desempate por id, dos productos igual de
        relevantes podrían salir en distinto orden entre ejecuciones y el no determinismo
        del sandbox se confundiría con el del modelo, que es justo lo que mide pass^k.
        """
        terminos = [t for t in normalizar(query).split() if t]
        resultados: list[tuple[int, str, Product]] = []

        for producto in self.products:
            if category is not None and normalizar(producto.category) != normalizar(category):
                continue
            if max_price is not None and producto.price_clp > max_price:
                continue
            if min_price is not None and producto.price_clp < min_price:
                continue
            if attributes and not self._cumple_atributos(producto, attributes):
                continue
            relevancia = self._relevancia(producto, terminos)
            if terminos and relevancia == 0:
                continue
            resultados.append((relevancia, producto.id, producto))

        resultados.sort(key=lambda fila: (-fila[0], fila[1]))
        return [producto for _, _, producto in resultados]

    @staticmethod
    def _cumple_atributos(producto: Product, requisitos: dict[str, Any]) -> bool:
        return all(
            clave in producto.attributes and cumple_atributo(producto.attributes[clave], requisito)
            for clave, requisito in requisitos.items()
        )

    @staticmethod
    def _relevancia(producto: Product, terminos: list[str]) -> int:
        if not terminos:
            return 0
        campos = " ".join(
            [
                producto.name,
                producto.brand,
                producto.category,
                " ".join(str(v) for v in producto.attributes.values()),
            ]
        )
        texto = normalizar(campos)
        return sum(1 for termino in terminos if termino in texto)

    # ----------------------------------------------------------- persistencia

    @classmethod
    def from_json(cls, ruta: Path | str) -> Catalog:
        """Carga `catalog.json` (y `reviews.jsonl` hermano, si existe)."""
        ruta = Path(ruta)
        with ruta.open(encoding="utf-8") as handle:
            datos = json.load(handle)
        if isinstance(datos, list):
            datos = {"products": datos}
        reviews_path = ruta.parent / "reviews.jsonl"
        if not datos.get("reviews") and reviews_path.is_file():
            datos["reviews"] = [
                json.loads(linea)
                for linea in reviews_path.read_text(encoding="utf-8").splitlines()
                if linea.strip()
            ]
        return cls.model_validate(datos)

    @classmethod
    def from_corpus(cls, version: str = "v1.0") -> Catalog:
        """Carga el catálogo del corpus congelado."""
        return cls.from_json(paths.corpus_version(version) / "catalog.json")

    def bloque_indice(self, max_productos: int | None = None) -> str:
        """Índice compacto del catálogo para el system prompt (el que lleva `cache_control`).

        Solo id, nombre y precio, agrupados por categoría. Los atributos técnicos, el
        stock, la evaluación, la descripción y las reseñas **no** están aquí: se obtienen
        con las herramientas. El bloque viaja en cada petición de cada ejecución de E1, E2
        y E3, así que cada token que contiene se paga miles de veces y además retrasa el
        primer token de la respuesta.

        El precio va en pesos completos y no en miles: la dimensión de robustez se juega
        en respetar `presupuesto_max_clp`, y meter una conversión de unidades justo en la
        magnitud que se está midiendo cambiaría el error del agente por un error de
        aritmética del arnés, por unos 200 tokens de ahorro.

        Debe ser estable byte a byte entre llamadas: la caché es un acierto por prefijo.
        """
        productos = sorted(self.products, key=lambda p: p.id)
        if max_productos is not None:
            productos = productos[:max_productos]

        lineas = [
            "ÍNDICE DEL CATÁLOGO DE TiendaDemo.cl — id|nombre|precio en CLP, por categoría.",
            "Atributos, stock, evaluación, descripción y reseñas se consultan con las "
            "herramientas; aquí no están.",
        ]
        for categoria in sorted({p.category for p in productos}):
            lineas.append(f"# {categoria}")
            lineas.extend(
                f"{p.id}|{p.name}|{p.price_clp}" for p in productos if p.category == categoria
            )
        return "\n".join(lineas)

    def bloque_resumen(self, max_productos: int | None = None) -> str:
        """Ficha extendida de cada producto. **No va al system prompt.**

        Se conserva para inspección y para la documentación del corpus. El bloque que el
        agente recibe es `bloque_indice`, que es cinco veces más barato.
        """
        lineas = [
            "CATÁLOGO DE TiendaDemo.cl "
            "(id | nombre | marca | categoría | precio | stock | evaluación):"
        ]
        productos = sorted(self.products, key=lambda p: p.id)
        if max_productos is not None:
            productos = productos[:max_productos]
        lineas.extend(f"- {producto.resumen()}" for producto in productos)
        return "\n".join(lineas)


__all__ = ["Catalog", "cumple_atributo", "normalizar"]
