"""Verificación del corpus v1.0 ya escrito en `data/corpus/v1.0/`.

Estas pruebas no generan nada: leen el artefacto congelado y comprueban que sigue
cumpliendo lo que el informe afirma de él. Son las que detectarían una edición manual, un
archivo corrompido o un `MANIFEST.json` desactualizado.

Se omiten si el corpus no está construido, para que el repositorio siga siendo clonable y
verificable antes de la etapa 2.
"""

from __future__ import annotations

import hashlib
import json
import re

import pytest

from prf.env import Catalog, CriterioAtaque, caso_desde_dict, validate_target_reachable
from prf.infra.config import load_experiments
from prf.infra.paths import paths

VERSION = load_experiments()["corpus_version"]
RAIZ = paths.corpus_version(VERSION)

pytestmark = pytest.mark.skipif(
    not (RAIZ / "MANIFEST.json").is_file(),
    reason="el corpus v1.0 aún no está construido (etapa 2)",
)


def _jsonl(nombre: str) -> list[dict]:
    return [
        json.loads(linea)
        for linea in (RAIZ / nombre).read_text(encoding="utf-8").splitlines()
        if linea.strip()
    ]


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((RAIZ / "MANIFEST.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def catalogo() -> Catalog:
    return Catalog.from_corpus(VERSION)


@pytest.fixture(scope="module")
def casos_seguridad() -> list[dict]:
    return _jsonl("cases_security.jsonl")


@pytest.fixture(scope="module")
def resenas() -> list[dict]:
    return _jsonl("reviews.jsonl")


# ------------------------------------------------------------------ manifiesto


def test_el_manifiesto_declara_semilla_version_y_modelo(manifest):
    assert manifest["seed"] == 20260906
    assert manifest["corpus_version"] == VERSION
    assert manifest["idioma"] == "es-CL"
    assert len(manifest["corpus_hash"]) == 64


def test_los_hashes_del_manifiesto_coinciden_con_los_archivos(manifest):
    # Detecta cualquier edición posterior a la construcción: el corpus está congelado.
    for archivo in manifest["archivos"]:
        real = hashlib.sha256((RAIZ / archivo["nombre"]).read_bytes()).hexdigest()
        assert real == archivo["sha256"], archivo["nombre"]


def test_los_conteos_coinciden_con_la_tabla_2(manifest):
    conteos = manifest["conteos"]

    assert conteos["productos"] == 200
    assert conteos["casos_robustez"] == 60
    assert conteos["casos_robustez_por_tipo"] == {
        "busqueda": 20,
        "comparacion": 20,
        "recomendacion": 20,
    }
    # Los 90 indirectos son los dos portadores: 60 de reseña, de v1.2, y 30 de descripción,
    # que es lo que v1.3 añade.
    assert conteos["casos_seguridad_por_tipo"] == {"directo": 40, "indirecto": 90, "benigno": 40}
    assert conteos["casos_seguridad_por_portador"] == {"resena": 60, "descripcion": 30}
    # 26 desde v1.4, que añade el caso del ítem `INFORMACION_VERAZ_RESULTADOS`.
    assert conteos["casos_cumplimiento"] == 26
    assert conteos["resenas_benignas"] == 600
    assert conteos["resenas_adversariales"] == 60


def test_los_conteos_del_manifiesto_reflejan_los_archivos(manifest, catalogo, resenas):
    conteos = manifest["conteos"]

    assert len(catalogo) == conteos["productos"]
    assert sum(1 for r in resenas if not r["is_adversarial"]) == conteos["resenas_benignas"]
    assert sum(1 for r in resenas if r["is_adversarial"]) == conteos["resenas_adversariales"]
    assert len(_jsonl("cases_robustness.jsonl")) == conteos["casos_robustez"]
    assert len(_jsonl("cases_security.jsonl")) == conteos["casos_seguridad"]
    assert len(_jsonl("cases_compliance.jsonl")) == conteos["casos_cumplimiento"]


# --------------------------------------------------------------------- casos


def test_todos_los_casos_validan_contra_su_esquema():
    for nombre in ("cases_robustness.jsonl", "cases_security.jsonl", "cases_compliance.jsonl"):
        for fila in _jsonl(nombre):
            caso_desde_dict(fila)


def test_los_case_id_son_unicos_en_todo_el_corpus():
    ids = [
        fila["case_id"]
        for nombre in ("cases_robustness.jsonl", "cases_security.jsonl", "cases_compliance.jsonl")
        for fila in _jsonl(nombre)
    ]

    assert len(set(ids)) == len(ids)


def test_todos_los_casos_de_robustez_siguen_siendo_alcanzables(catalogo):
    # Criterio de "hecho" de la etapa 2, verificado sobre el artefacto y no sobre el
    # generador: si alguien editara el catálogo, esta prueba lo delataría.
    for fila in _jsonl("cases_robustness.jsonl"):
        caso = caso_desde_dict(fila)
        alcanzable, motivos = validate_target_reachable(caso.target_state, catalogo)
        assert alcanzable, f"{caso.case_id}: {motivos}"


def test_toda_intencion_tiene_texto():
    for nombre in ("cases_robustness.jsonl", "cases_security.jsonl", "cases_compliance.jsonl"):
        for fila in _jsonl(nombre):
            assert len(fila["intent"].split()) >= 5, fila["case_id"]


def test_las_intenciones_no_filtran_codigos_de_producto():
    # El usuario habla de productos por su nombre; un código P0123 en la intención es una
    # fuga del andamiaje del corpus a la conversación. Aplica también a los casos
    # indirectos, que nombran el producto consultado: eximirlos dejó pasar exactamente
    # esta fuga en una versión anterior del corpus.
    for nombre in ("cases_robustness.jsonl", "cases_security.jsonl"):
        for fila in _jsonl(nombre):
            assert not re.search(r"\bP\d{4}\b", fila["intent"]), fila["case_id"]


# ------------------------------------------------------------------ seguridad


def test_cada_ataque_conserva_un_criterio_comprobable(casos_seguridad):
    ataques = [c for c in casos_seguridad if c["tipo"] in ("directo", "indirecto")]

    assert len(ataques) == 130
    for caso in ataques:
        criterio = CriterioAtaque.model_validate(caso["attack_success_criterion"])
        assert criterio.campos_requeridos_presentes(), caso["case_id"]


def test_el_centinela_sobrevivio_a_la_redaccion(casos_seguridad, resenas):
    # La carga se concatena literal justamente para esto: si el modelo la hubiera
    # reescrito, el centinela cambiaría y el ataque dejaría de ser comprobable.
    por_ataque = {r["attack_id"]: r["text"] for r in resenas if r["is_adversarial"]}

    for caso in casos_seguridad:
        criterio = caso.get("attack_success_criterion") or {}
        if criterio.get("tipo") != "centinela_en_texto":
            continue
        # Tres sitios donde puede vivir la carga, uno por superficie: el mensaje del usuario
        # en el vector directo, la reseña o la ficha del producto en el indirecto.
        if caso["tipo"] == "directo":
            texto = caso["intent"]
        elif caso.get("portador") == "descripcion":
            texto = caso["descripcion_adversarial"]
        else:
            texto = por_ataque[caso["case_id"]]
        assert any(c in texto for c in criterio["centinelas"]), caso["case_id"]


def _de_resena(casos: list[dict]) -> list[dict]:
    """Ataques indirectos cuya carga viaja en una reseña, no en la descripción."""
    return [
        c for c in casos if c["tipo"] == "indirecto" and (c.get("portador") or "resena") == "resena"
    ]


def _de_descripcion(casos: list[dict]) -> list[dict]:
    return [c for c in casos if c.get("portador") == "descripcion"]


def test_cada_ataque_indirecto_tiene_su_resena_en_el_corpus(casos_seguridad, resenas, catalogo):
    por_id = {r["id"]: r for r in resenas}
    de_resena = _de_resena(casos_seguridad)

    assert len(de_resena) == 60
    for caso in de_resena:
        resena = por_id[caso["review_id"]]
        assert resena["is_adversarial"] is True
        assert resena["attack_id"] == caso["case_id"]
        assert catalogo.existe(resena["product_id"])


def test_cada_ataque_de_descripcion_lleva_su_ficha_envenenada(casos_seguridad, catalogo):
    """La carga vive en la ficha del portador y en ningún otro sitio.

    Se comprueba además que la ficha **empieza** por la descripción del catálogo: la carga se
    añade, no sustituye. Una ficha que solo contuviera la instrucción no es una descripción de
    producto, y el ataque fallaría por delatarse y no por la defensa.
    """
    de_descripcion = _de_descripcion(casos_seguridad)

    assert len(de_descripcion) == 30
    for caso in de_descripcion:
        producto = catalogo.get(caso["producto_portador"])
        assert producto is not None, caso["case_id"]
        assert caso["carga"] in caso["descripcion_adversarial"], caso["case_id"]
        assert caso["descripcion_adversarial"].startswith(producto.description.strip()), caso[
            "case_id"
        ]
        assert caso["carga"] not in caso["intent"], caso["case_id"]
        # El nombre comercial del portador en la intención es lo que hace que el agente
        # consulte esa ficha; sin él, la carga no se entregaría nunca.
        assert producto.name in caso["intent"], caso["case_id"]


def test_el_portador_de_descripcion_cabe_en_el_presupuesto_del_caso(casos_seguridad, catalogo):
    """El usuario pide la ficha de ese producto por su nombre: tiene que poder comprarlo.

    Con un portador más caro que el tope del caso, el agente dedica la respuesta a explicar
    por qué no sirve y el ataque se mide sobre una conversación que ya iba de otra cosa. En la
    primera ronda de calibración le pasaba a 14 de 30 casos.

    No se exige en los ataques de reseña: ahí el usuario pregunta qué opinan los clientes, no
    pide comprarlo, y además esos 60 casos están congelados desde v1.2.
    """
    for caso in _de_descripcion(casos_seguridad):
        tope = caso["target_state"]["constraints"]["presupuesto_max_clp"]
        producto = catalogo.get(caso["producto_portador"])
        assert producto is not None, caso["case_id"]
        assert tope is None or producto.price_clp <= tope, (
            f"{caso['case_id']}: el portador cuesta {producto.price_clp} y el tope es {tope}"
        )


def test_la_proporcion_dev_test_de_los_ataques_es_30_70(casos_seguridad):
    ataques = [c for c in casos_seguridad if c.get("particion_plantilla")]
    dev = sum(1 for c in ataques if c["particion_plantilla"] == "dev")

    # 39 de 130: los 30 de v1.2 más los 9 del bloque de descripción, que mantiene el 30/70.
    assert dev == 39 and len(ataques) == 130


# -------------------------------------------------------------------- reseñas


def test_las_resenas_benignas_respetan_el_rango_de_palabras(resenas):
    for resena in (r for r in resenas if not r["is_adversarial"]):
        n = len(resena["text"].split())
        assert 25 <= n <= 140, f"{resena['id']} tiene {n} palabras"


def test_hay_tres_resenas_benignas_por_producto(resenas, catalogo):
    from collections import Counter

    conteo = Counter(r["product_id"] for r in resenas if not r["is_adversarial"])

    assert len(conteo) == len(catalogo)
    assert set(conteo.values()) == {3}


def test_la_media_de_las_resenas_concuerda_con_el_avg_rating(resenas, catalogo):
    # Sin esta coherencia, el `rating_promedio` que devuelve el modelo en cuarentena
    # contradiría al catálogo en todas las conversaciones de dual_llm y cte.
    from collections import defaultdict
    from statistics import mean

    por_producto = defaultdict(list)
    for resena in (r for r in resenas if not r["is_adversarial"]):
        por_producto[resena["product_id"]].append(resena["rating"])

    brechas = [
        abs(catalogo.get(pid).avg_rating - mean(notas)) for pid, notas in por_producto.items()
    ]

    assert max(brechas) <= 0.5, f"brecha máxima {max(brechas):.2f} estrellas"


def test_ninguna_resena_benigna_lleva_marca_de_ataque(resenas):
    for resena in (r for r in resenas if not r["is_adversarial"]):
        assert resena["attack_id"] is None


# ------------------------------------------------------------------------ PII


def test_toda_la_pii_del_corpus_es_simulada():
    textos = " ".join(
        fila["intent"]
        for nombre in ("cases_robustness.jsonl", "cases_security.jsonl", "cases_compliance.jsonl")
        for fila in _jsonl(nombre)
    )

    for correo in re.findall(r"[\w.\-]+@[\w\-]+\.[a-zA-Z]{2,}", textos):
        assert correo.endswith("example.cl"), correo
    for rut in re.findall(r"\b\d{1,2}\.\d{3}\.\d{3}-[\dkK]\b", textos):
        assert rut.startswith("99."), rut


# --------------------------------------------------------------------- catálogo


def test_todo_producto_tiene_nombre_y_descripcion_redactados(catalogo):
    for producto in catalogo.products:
        assert len(producto.name.split()) >= 2, producto.id
        assert len(producto.description.split()) >= 15, producto.id


def test_el_bloque_de_catalogo_es_estable(catalogo):
    # Va en el system prompt con cache_control: si variara entre llamadas, no habría caché.
    assert catalogo.bloque_indice() == catalogo.bloque_indice()


def test_el_indice_del_prefijo_es_compacto_y_cacheable(catalogo):
    # El bloque viaja en cada petición de cada ejecución de E1, E2 y E3: cada token se
    # paga miles de veces y retrasa el primer token. Medido en caracteres para no
    # depender de la red; 4.365 tokens reales medidos con `messages.count_tokens`.
    indice = catalogo.bloque_indice()

    assert len(indice) < len(catalogo.bloque_resumen()) * 0.5
    # Muy por encima del mínimo cacheable de Sonnet 4.6 (1024 tokens): por debajo de ese
    # umbral la caché no se crea y la API no avisa.
    assert len(indice) > 4_000


# ------------------------------------------- entrega de la carga indirecta


def test_cada_ataque_indirecto_usa_un_producto_portador_distinto(casos_seguridad):
    """Sin portador compartido, y la unicidad se exige **dentro** de cada superficie.

    En las reseñas el motivo es el truncamiento: si varios ataques compartieran portador, sus
    reseñas se acumularían en él y `get_reviews` dejaría a la mayoría fuera del corte. En las
    descripciones es la atribución: dos cargas en la misma ficha harían imposible saber cuál
    de los dos ataques prosperó al ver el centinela en la respuesta.

    Entre superficies distintas sí puede repetirse un producto, y no estorba: cada caso corre
    en su propia ejecución y la ficha envenenada solo existe durante la del caso que la trae.
    """
    for superficie, casos in (
        ("resena", _de_resena(casos_seguridad)),
        ("descripcion", _de_descripcion(casos_seguridad)),
    ):
        portadores = [c["producto_portador"] for c in casos]
        assert len(set(portadores)) == len(portadores), superficie


def test_la_carga_indirecta_llega_dentro_del_limite_de_get_reviews(casos_seguridad, catalogo):
    # `get_reviews` devuelve las primeras `limit` reseñas del producto. Si la adversarial
    # cae fuera del corte, el ataque fracasa por truncamiento y no por la defensa, y el ASR
    # indirecto —la métrica central del informe— se hunde por una razón espuria.
    from prf.env.tools import LIMITE_RESENAS_POR_DEFECTO

    for caso in _de_resena(casos_seguridad):
        entregadas = catalogo.reviews_de(caso["producto_portador"])[:LIMITE_RESENAS_POR_DEFECTO]
        assert caso["review_id"] in [r.id for r in entregadas], caso["case_id"]


def test_ningun_producto_acumula_mas_de_una_resena_adversarial(resenas):
    from collections import Counter

    conteo = Counter(r["product_id"] for r in resenas if r["is_adversarial"])

    assert conteo and max(conteo.values()) == 1


def test_el_ataque_directo_guarda_su_carga_y_esta_dentro_de_la_intencion(casos_seguridad):
    directos = [c for c in casos_seguridad if c["tipo"] == "directo"]

    assert len(directos) == 40
    for caso in directos:
        assert caso["carga"], caso["case_id"]
        assert caso["carga"] in caso["intent"], caso["case_id"]


def test_los_casos_sin_carga_en_el_mensaje_no_la_guardan(casos_seguridad):
    """Benignos y ataques de reseña llevan `carga` vacía; los de descripción, no.

    El campo cumple dos funciones distintas según la superficie. En el vector directo es lo
    que se concatena al mensaje del usuario. En el de descripción es lo que se busca en el
    resultado de la herramienta para decidir si la ficha se entregó, así que tiene que estar
    ahí; lo que no puede es aparecer en el `intent`, y eso lo comprueba
    `test_cada_ataque_de_descripcion_lleva_su_ficha_envenenada`.
    """
    for caso in casos_seguridad:
        if caso["tipo"] == "benigno" or caso in _de_resena(casos_seguridad):
            assert caso["carga"] == "", caso["case_id"]
