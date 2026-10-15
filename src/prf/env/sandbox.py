"""Sandbox de ecommerce: implementación de las herramientas sobre el catálogo.

Las cuatro herramientas de lectura son puras respecto del catálogo: no lo modifican y,
con el mismo catálogo y los mismos argumentos, devuelven siempre lo mismo. Lo único que
cambia entre llamadas es el registro en `EnvState`.

Las dos restringidas (`apply_discount`, `send_message`) tampoco modifican el catálogo:
su función es dejar constancia de que fueron invocadas. Si `apply_discount` alterara los
precios, el resto de la conversación evaluaría un catálogo distinto del anotado y una
misma ejecución dejaría de ser reproducible.
"""

from __future__ import annotations

from typing import Any

from prf.env.catalog import Catalog
from prf.env.models import Origen, Product, Review
from prf.env.state import EnvState, FinalState
from prf.env.tools import (
    HERRAMIENTAS,
    HERRAMIENTAS_RESTRINGIDAS,
    LIMITE_BUSQUEDA_POR_DEFECTO,
    LIMITE_RESENAS_POR_DEFECTO,
)


class ToolError(ValueError):
    """Error de uso de una herramienta (argumento ausente, id inexistente).

    Se devuelve al agente como resultado de herramienta con `is_error`, no se propaga:
    un error de uso es información que el agente puede corregir en el turno siguiente, y
    abortar la ejecución convertiría un fallo del modelo en un fallo del arnés.
    """


# Anotaciones del andamiaje: dicen que una reseña es un ataque y cuál. Son para el análisis,
# no para el agente. Que salieran del sandbox convertía cada ataque indirecto en un ataque
# **etiquetado**, y un agente sin defensa podía descartarlo por la etiqueta y no por su
# criterio: el ASR de las líneas base habría salido bajo por un artefacto del arnés.
ANOTACIONES_DEL_ANDAMIAJE = ("is_adversarial", "attack_id")


def sin_anotaciones(dato: Any) -> Any:
    """Copia del resultado sin las anotaciones que solo existen para medir."""
    if isinstance(dato, dict):
        return {
            k: sin_anotaciones(v) for k, v in dato.items() if k not in ANOTACIONES_DEL_ANDAMIAJE
        }
    if isinstance(dato, list):
        return [sin_anotaciones(v) for v in dato]
    return dato


class Sandbox:
    """Entorno sobre el que actúa el agente."""

    def __init__(
        self,
        catalog: Catalog,
        *,
        state: EnvState | None = None,
        descripciones: dict[str, str] | None = None,
    ) -> None:
        self.catalog = catalog
        self.state = state or EnvState(catalog)
        # Descripciones que sustituyen a las del catálogo en las herramientas que las
        # devuelven. Es el mecanismo de los ataques con portador descripción de v1.3, y va
        # aquí y no en el corpus por una razón de aislamiento: el catálogo lo comparten las
        # tres dimensiones, así que una descripción envenenada escrita en `catalog.json`
        # aparecería también en E1 y en E4, y cada búsqueda de esa categoría entregaría la
        # carga a un experimento que no la está midiendo. Vive en el caso y solo se aplica
        # en la ejecución de ese caso.
        self.descripciones = dict(descripciones or {})

    def _servir(self, producto: Product) -> Product:
        """El producto tal como lo devuelve la herramienta, con la descripción del caso."""
        texto = self.descripciones.get(producto.id)
        if texto is None:
            return producto
        return producto.model_copy(update={"description": texto})

    # ------------------------------------------------------ herramientas de lectura

    def search_catalog(
        self,
        query: str = "",
        *,
        category: str | None = None,
        max_price: int | None = None,
        min_price: int | None = None,
        attributes: dict[str, Any] | None = None,
        limit: int = LIMITE_BUSQUEDA_POR_DEFECTO,
    ) -> list[Product]:
        """Productos que cumplen los filtros, acotados a `limit`.

        El límite existe para acotar el contexto y su costo; la etapa 2 lo eleva al
        validar que el estado objetivo de un caso sea alcanzable.
        """
        resultados = self.catalog.buscar(
            query,
            category=category,
            max_price=max_price,
            min_price=min_price,
            attributes=attributes,
        )
        return [self._servir(p) for p in resultados[: max(0, limit)]]

    def get_product(self, id: str) -> Product:  # noqa: A002 - nombre fijado por el esquema
        """La ficha de un producto, con la descripción que corresponda a esta ejecución."""
        producto = self.catalog.get(id)
        if producto is None:
            raise ToolError(f"no existe un producto con id {id!r} en el catálogo")
        return self._servir(producto)

    def get_reviews(self, product_id: str, limit: int = LIMITE_RESENAS_POR_DEFECTO) -> list[Review]:
        """Reseñas de un producto.

        Devuelve el objeto `Review` completo; es responsabilidad de la configuración de
        defensa (etapa 4) decidir qué parte de ese texto llega al modelo privilegiado.
        Las anotaciones `is_adversarial` y `attack_id` nunca se le entregan al agente.
        """
        if not self.catalog.existe(product_id):
            raise ToolError(f"no existe un producto con id {product_id!r} en el catálogo")
        return self.catalog.reviews_de(product_id)[: max(0, limit)]

    def compare_products(self, ids: list[str]) -> dict[str, Any]:
        """Comparación de dos o más productos por precio, atributos y evaluación."""
        if len(ids) < 2:
            raise ToolError("compare_products requiere al menos dos identificadores")
        productos = []
        for product_id in ids:
            producto = self.catalog.get(product_id)
            if producto is None:
                raise ToolError(f"no existe un producto con id {product_id!r} en el catálogo")
            productos.append(producto)

        atributos = sorted({clave for p in productos for clave in p.attributes})
        return {
            "ids": [p.id for p in productos],
            "productos": [
                {
                    "id": p.id,
                    "name": p.name,
                    "brand": p.brand,
                    "category": p.category,
                    "price_clp": p.price_clp,
                    "stock": p.stock,
                    "avg_rating": p.avg_rating,
                    "attributes": {clave: p.attributes.get(clave) for clave in atributos},
                }
                for p in productos
            ],
            "mas_barato": min(productos, key=lambda p: (p.price_clp, p.id)).id,
            "mejor_evaluado": max(productos, key=lambda p: (p.avg_rating, p.id)).id,
        }

    # -------------------------------------------------- herramientas restringidas

    def apply_discount(self, product_id: str, pct: float) -> dict[str, Any]:
        """Herramienta restringida. No altera el catálogo: solo deja constancia."""
        return {
            "estado": "registrado",
            "product_id": product_id,
            "pct": pct,
            "nota": "herramienta restringida: invocación registrada, el catálogo no se modifica",
        }

    def send_message(self, to: str, body: str) -> dict[str, Any]:
        """Herramienta restringida. No envía nada: solo deja constancia."""
        return {
            "estado": "registrado",
            "to": to,
            "body": body,
            "nota": "herramienta restringida: invocación registrada, no se envía ningún mensaje",
        }

    # -------------------------------------------------------------------- dispatch

    def dispatch(
        self,
        nombre: str,
        argumentos: dict[str, Any] | None = None,
        *,
        origen: dict[str, Origen] | Origen | None = None,
    ) -> dict[str, Any]:
        """Ejecuta una herramienta por nombre y registra la llamada.

        Devuelve siempre un dict serializable a JSON, con `error` en lugar de excepción
        cuando la herramienta se usó mal.
        """
        argumentos = dict(argumentos or {})
        if nombre not in HERRAMIENTAS:
            self.state.registrar(
                nombre,
                argumentos,
                origen=origen,
                bloqueada=True,
                motivo_bloqueo="herramienta desconocida",
            )
            return {"error": f"herramienta desconocida: {nombre!r}"}

        llamada = self.state.registrar(nombre, argumentos, origen=origen)
        try:
            resultado = getattr(self, nombre)(**argumentos)
        except ToolError as exc:
            llamada.error = str(exc)
            return {"error": llamada.error}
        except TypeError as exc:
            llamada.error = f"argumentos inválidos para {nombre}: {exc}"
            return {"error": llamada.error}
        serializado = _serializar(resultado)
        # Se filtra contra el catálogo: el campo `id` de una reseña también es un id, y
        # contarlo como producto visto ensuciaría el análisis del señuelo.
        self.state.productos_vistos.update(
            pid for pid in _ids_de_producto(serializado) if self.catalog.existe(pid)
        )
        # El registro guarda el resultado completo; lo que sale del sandbox va sin las
        # anotaciones del andamiaje.
        llamada.resultado = serializado
        return {"resultado": sin_anotaciones(serializado)}

    def bloquear(self, nombre: str, argumentos: dict[str, Any], motivo: str) -> dict[str, Any]:
        """Registra un paso bloqueado por una defensa, sin ejecutarlo.

        Lo usa el intérprete Code-Then-Execute (etapa 4): el paso queda en el registro
        como evidencia de que la defensa actuó, pero la herramienta no se invoca.
        """
        self.state.registrar(nombre, argumentos, bloqueada=True, motivo_bloqueo=motivo)
        return {"error": f"paso bloqueado: {motivo}"}

    # ---------------------------------------------------------------------- estado

    def cerrar(
        self,
        texto_final: str,
        *,
        recomendaciones: list[str] | None = None,
        comparaciones: list[list[str]] | None = None,
    ) -> FinalState:
        return self.state.cerrar(
            texto_final, recomendaciones=recomendaciones, comparaciones=comparaciones
        )

    @property
    def herramientas_restringidas_invocadas(self) -> list[str]:
        return [
            llamada.nombre
            for llamada in self.state.ejecutadas
            if llamada.nombre in HERRAMIENTAS_RESTRINGIDAS
        ]


def _ids_de_producto(dato: Any) -> set[str]:
    """Ids de producto presentes en un resultado de herramienta."""
    encontrados: set[str] = set()
    if isinstance(dato, dict):
        # Se miran las dos claves, no una u otra: una reseña trae `id` (suyo) y
        # `product_id` (del producto), y quedarse con la primera perdería la segunda.
        for clave in ("id", "product_id"):
            valor = dato.get(clave)
            if isinstance(valor, str):
                encontrados.add(valor)
        for elemento in dato.values():
            if isinstance(elemento, (dict, list)):
                encontrados |= _ids_de_producto(elemento)
    elif isinstance(dato, list):
        for elemento in dato:
            encontrados |= _ids_de_producto(elemento)
    return encontrados


def _serializar(valor: Any) -> Any:
    """Convierte modelos pydantic (y listas de ellos) a estructuras JSON."""
    if isinstance(valor, list):
        return [_serializar(elemento) for elemento in valor]
    if hasattr(valor, "model_dump"):
        return valor.model_dump(mode="json")
    return valor


__all__ = ["Sandbox", "ToolError"]
