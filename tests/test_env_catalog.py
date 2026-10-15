"""Catálogo: filtros de búsqueda, comparación de atributos y carga desde disco."""

from __future__ import annotations

import json

import pytest

from prf.env import Catalog, cumple_atributo, normalizar


def test_normalizar_ignora_tildes_y_mayusculas():
    assert normalizar("Audífonos") == normalizar("audifonos") == "audifonos"


def test_busqueda_por_termino_encuentra_por_nombre_y_marca(catalogo):
    ids = [p.id for p in catalogo.buscar("cordillera")]

    assert ids == ["P002"]


def test_busqueda_sin_termino_devuelve_todo_el_catalogo(catalogo):
    assert len(catalogo.buscar("")) == len(catalogo)


def test_filtro_de_categoria_es_insensible_a_tildes(catalogo):
    assert [p.id for p in catalogo.buscar("", category="audífonos")] == ["P006"]


def test_filtros_de_precio_acotan_por_ambos_extremos(catalogo):
    ids = [p.id for p in catalogo.buscar("", category="notebooks", max_price=900_000)]

    assert ids == ["P001", "P003"]
    assert [p.id for p in catalogo.buscar("", min_price=1_000_000)] == ["P002"]


def test_filtro_de_atributos_admite_igualdad_y_rango(catalogo):
    exactos = catalogo.buscar("", attributes={"ram_gb": 16})
    minimo = catalogo.buscar("", attributes={"ram_gb": {"min": 16}})

    assert [p.id for p in exactos] == ["P001"]
    assert [p.id for p in minimo] == ["P001", "P002"]


def test_el_orden_es_determinista_entre_llamadas(catalogo):
    # Sin orden estable, el no determinismo del sandbox se confundiría con el del modelo.
    primera = [p.id for p in catalogo.buscar("notebook")]
    segunda = [p.id for p in catalogo.buscar("notebook")]

    assert primera == segunda


def test_los_filtros_se_combinan_con_and(catalogo):
    ids = [
        p.id
        for p in catalogo.buscar(
            "notebook",
            category="notebooks",
            max_price=1_000_000,
            attributes={"ssd_gb": {"min": 512}},
        )
    ]

    assert ids == ["P001"]


@pytest.mark.parametrize(
    ("valor", "requisito", "esperado"),
    [
        (16, 16, True),
        (16, {"min": 16}, True),
        (8, {"min": 16}, False),
        (16, {"max": 32}, True),
        (16, {"min": 8, "max": 32}, True),
        (64, {"min": 8, "max": 32}, False),
        ("Aurora", "aurora", True),
        (True, True, True),
        (True, {"min": 1}, False),  # un booleano no es un número comparable
        ("negro", {"en": ["negro", "plata"]}, True),
        ("azul", {"en": ["negro", "plata"]}, False),
    ],
)
def test_cumple_atributo(valor, requisito, esperado):
    assert cumple_atributo(valor, requisito) is esperado


def test_reviews_de_devuelve_solo_las_del_producto(catalogo):
    assert [r.id for r in catalogo.reviews_de("P001")] == ["R001", "R002"]
    assert catalogo.reviews_de("P006") == []


def test_carga_desde_json_con_reseñas_hermanas(catalogo, tmp_path):
    (tmp_path / "catalog.json").write_text(
        json.dumps({"products": [p.model_dump() for p in catalogo.products]}), encoding="utf-8"
    )
    (tmp_path / "reviews.jsonl").write_text(
        "\n".join(json.dumps(r.model_dump()) for r in catalogo.reviews), encoding="utf-8"
    )

    cargado = Catalog.from_json(tmp_path / "catalog.json")

    assert len(cargado) == len(catalogo)
    assert [r.id for r in cargado.reviews_de("P001")] == ["R001", "R002"]


def test_bloque_resumen_es_estable_byte_a_byte(catalogo):
    # Va en el system prompt con cache_control: cualquier variación invalida la caché.
    assert catalogo.bloque_resumen() == catalogo.bloque_resumen()
    assert "P001" in catalogo.bloque_resumen()


# ------------------------------------------------ índice compacto del prefijo


def test_el_indice_solo_lleva_id_nombre_y_precio(catalogo):
    # Atributos, stock, evaluación y descripción se obtienen con las herramientas, que es
    # donde cada configuración de defensa decide qué dejar pasar. En el prefijo quedarían
    # fuera del alcance de la defensa además de encarecer cada petición.
    indice = catalogo.bloque_indice()

    assert "P001|Notebook Aurora 14|899990" in indice
    assert "stock" not in indice.split("\n", 2)[2]
    assert "evaluación" not in indice.split("\n", 2)[2]


def test_el_indice_agrupa_por_categoria(catalogo):
    indice = catalogo.bloque_indice()

    for categoria in catalogo.categorias:
        assert f"# {categoria}" in indice


def test_el_indice_lleva_el_precio_en_pesos_completos(catalogo):
    # La robustez se juega en respetar el presupuesto: una conversión de unidades en la
    # magnitud que se mide cambiaría un error del agente por uno de aritmética del arnés.
    assert "899990" in catalogo.bloque_indice()


def test_cada_linea_del_indice_es_mas_corta_que_la_ficha_extendida(catalogo):
    # Se compara por línea y no por bloque: con seis productos de prueba la cabecera fija
    # domina el total y la razón no diría nada. La medición sobre el corpus completo está
    # en test_corpus_congelado.py.
    lineas_indice = [x for x in catalogo.bloque_indice().splitlines() if x.startswith("P")]
    lineas_ficha = [x for x in catalogo.bloque_resumen().splitlines() if x.startswith("- P")]

    assert len(lineas_indice) == len(lineas_ficha) == len(catalogo)
    assert max(map(len, lineas_indice)) < min(map(len, lineas_ficha))


def test_el_indice_es_estable_byte_a_byte(catalogo):
    assert catalogo.bloque_indice() == catalogo.bloque_indice()


def test_el_indice_incluye_todos_los_productos(catalogo):
    indice = catalogo.bloque_indice()

    for producto in catalogo.products:
        assert f"{producto.id}|" in indice
