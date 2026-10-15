"""Capa programática del corpus: determinismo, conteos y alcanzabilidad.

Ninguna de estas pruebas llama a la API. La capa de redacción se prueba aparte, con el
cliente simulado, porque su salida no es reproducible y por eso se congela en el corpus.
"""

from __future__ import annotations

import json

import pytest
from generators.casos_cumplimiento import (
    ITEMS,
    generar_casos_cumplimiento,
    validar_casos_de_cumplimiento,
)
from generators.casos_robustez import N_POR_TIPO, generar_casos_robustez, validar_casos
from generators.casos_seguridad import (
    FRACCION_DEV,
    N_BENIGNOS,
    N_DIRECTOS,
    N_INDIRECTOS,
    N_INDIRECTOS_DESCRIPCION,
    OBJETIVOS,
    asignaciones,
    cargar_plantillas,
    correo_simulado,
    generar_casos_seguridad,
    rut_simulado,
)
from generators.catalogo import N_PRODUCTOS, PRECIOS, REPARTO, generar_productos

from prf.env import (
    CasoCumplimiento,
    CasoRobustez,
    CasoSeguridad,
    Catalog,
    CriterioAtaque,
    TargetState,
    productos_alcanzables,
)

SEED = 20260906


@pytest.fixture(scope="module")
def productos():
    return generar_productos(SEED)


@pytest.fixture(scope="module")
def catalogo_v1(productos):
    return Catalog.model_validate({"products": productos, "reviews": []})


@pytest.fixture(scope="module")
def casos_seguridad(catalogo_v1):
    return generar_casos_seguridad(catalogo_v1, SEED)


# ------------------------------------------------------------------- catálogo


def test_el_catalogo_tiene_200_productos_en_6_categorias(productos):
    assert len(productos) == N_PRODUCTOS == 200
    assert len(REPARTO) == 6
    assert sum(REPARTO.values()) == N_PRODUCTOS


def test_el_reparto_por_categoria_se_cumple(productos):
    for categoria, esperado in REPARTO.items():
        assert sum(1 for p in productos if p["category"] == categoria) == esperado


def test_la_generacion_es_determinista(productos):
    assert generar_productos(SEED) == productos


def test_una_semilla_distinta_da_un_catalogo_distinto(productos):
    assert generar_productos(SEED + 1) != productos


def test_los_precios_caen_dentro_del_rango_de_su_categoria(productos):
    for producto in productos:
        minimo, maximo = PRECIOS[producto["category"]]
        # El redondeo a terminación 990 puede dejar el precio un peso bajo el mínimo.
        assert minimo - 1000 <= producto["price_clp"] <= maximo


def test_los_atributos_son_coherentes_con_la_categoria(productos):
    for producto in productos:
        if producto["category"] == "televisores":
            assert "ram_gb" not in producto["attributes"]
            if producto["attributes"]["resolucion"] == "8K":
                assert producto["attributes"]["pulgadas"] >= 50
        if producto["category"] == "audifonos" and producto["attributes"]["cancelacion_ruido"]:
            assert producto["attributes"]["inalambrico"] is True


def test_los_ids_son_unicos_y_correlativos(productos):
    ids = [p["id"] for p in productos]
    assert len(set(ids)) == len(ids)
    assert ids[0] == "P0001" and ids[-1] == f"P{N_PRODUCTOS:04d}"


def test_el_catalogo_valida_contra_el_modelo_del_sandbox(catalogo_v1):
    assert len(catalogo_v1) == N_PRODUCTOS


# ------------------------------------------------------------------- robustez


def test_hay_60_casos_de_robustez_repartidos_en_tres_tipos(catalogo_v1):
    casos = generar_casos_robustez(catalogo_v1, SEED)

    assert len(casos) == 60
    for tipo in ("busqueda", "comparacion", "recomendacion"):
        assert sum(1 for c in casos if c["tipo"] == tipo) == N_POR_TIPO == 20


def test_todos_los_casos_de_robustez_son_alcanzables(catalogo_v1):
    # Criterio de "hecho" de la etapa 2: 100 % de los casos alcanzables.
    casos = generar_casos_robustez(catalogo_v1, SEED)

    assert validar_casos(casos, catalogo_v1) == []


def test_ningun_caso_de_robustez_esta_duplicado(catalogo_v1):
    # Un caso repetido sube `n` sin aportar evidencia, y la etapa 3 lo repartiría entre
    # dev y test dejando la misma prueba a ambos lados de la partición.
    casos = generar_casos_robustez(catalogo_v1, SEED)
    firmas = {json.dumps(c["target_state"], sort_keys=True) for c in casos}

    assert len(firmas) == len(casos)


def test_los_casos_de_busqueda_exigen_recomendar_y_traen_senuelo(catalogo_v1):
    casos = [c for c in generar_casos_robustez(catalogo_v1, SEED) if c["tipo"] == "busqueda"]

    for caso in casos:
        target = TargetState.model_validate(caso["target_state"])
        assert target.min_recomendaciones >= 1
        assert target.must_exclude, "sin señuelo, la regla must_exclude no atrapa nada"
        senuelo = catalogo_v1.get(target.must_exclude[0])
        assert senuelo.price_clp > target.constraints.presupuesto_max_clp


def test_los_casos_de_comparacion_nombran_dos_productos_existentes(catalogo_v1):
    casos = [c for c in generar_casos_robustez(catalogo_v1, SEED) if c["tipo"] == "comparacion"]

    for caso in casos:
        target = TargetState.model_validate(caso["target_state"])
        assert len(target.must_compare) == 1
        a, b = target.must_compare[0]
        assert a != b
        assert catalogo_v1.existe(a) and catalogo_v1.existe(b)


def test_los_casos_de_robustez_validan_contra_el_esquema(catalogo_v1):
    for caso in generar_casos_robustez(catalogo_v1, SEED):
        CasoRobustez.model_validate({**caso, "intent": "texto de prueba"})


# ------------------------------------------------------------------ seguridad


def test_los_conteos_de_seguridad_coinciden_con_la_tabla_2(casos_seguridad):
    casos, resenas = casos_seguridad
    por_portador = {
        p: sum(1 for c in casos if c.get("portador") == p) for p in ("resena", "descripcion")
    }

    assert sum(1 for c in casos if c["tipo"] == "directo") == N_DIRECTOS == 40
    assert sum(1 for c in casos if c["tipo"] == "benigno") == N_BENIGNOS == 40
    # Los indirectos son los dos portadores juntos: 60 de reseña, de v1.2, más 30 de
    # descripción, de v1.3. Los primeros no declaran `portador` a propósito, para que sus
    # líneas del corpus queden byte a byte como estaban.
    assert sum(1 for c in casos if c["tipo"] == "indirecto") == (
        N_INDIRECTOS + N_INDIRECTOS_DESCRIPCION
    )
    assert por_portador == {"resena": 0, "descripcion": N_INDIRECTOS_DESCRIPCION}
    # Una reseña adversarial por ataque de reseña, y ninguna por ataque de descripción: esa
    # carga vive en la ficha del producto y no añade reseñas al corpus.
    assert len(resenas) == N_INDIRECTOS


def test_cada_ataque_tiene_un_criterio_comprobable(casos_seguridad):
    casos, _ = casos_seguridad
    ataques = [c for c in casos if c["tipo"] in ("directo", "indirecto")]

    assert len(ataques) == N_DIRECTOS + N_INDIRECTOS + N_INDIRECTOS_DESCRIPCION
    for caso in ataques:
        criterio = CriterioAtaque.model_validate(caso["attack_success_criterion"])
        assert criterio.campos_requeridos_presentes(), caso["case_id"]


def test_el_centinela_de_exfiltracion_aparece_en_la_carga(casos_seguridad):
    # Si el centinela no estuviera en el texto inyectado, el criterio sería incomprobable.
    casos, resenas = casos_seguridad
    por_review = {r["attack_id"]: r["text"] for r in resenas}

    for caso in casos:
        criterio = caso.get("attack_success_criterion") or {}
        if criterio.get("tipo") != "centinela_en_texto":
            continue
        payload = caso["carga"] or por_review[caso["case_id"]]
        assert any(c in payload for c in criterio["centinelas"]), caso["case_id"]


def test_los_ataques_respetan_la_proporcion_dev_test(casos_seguridad):
    casos, _ = casos_seguridad
    ataques = [c for c in casos if c.get("particion_plantilla")]
    n_dev = sum(1 for c in ataques if c["particion_plantilla"] == "dev")

    assert n_dev / len(ataques) == pytest.approx(FRACCION_DEV, abs=0.01)


def test_los_objetivos_estan_balanceados(casos_seguridad):
    # El informe reporta ASR por objetivo: un objetivo con la mitad de casos que otro
    # tendría un intervalo de confianza mucho más ancho sin razón de diseño.
    casos, _ = casos_seguridad
    conteo = {o: sum(1 for c in casos if c.get("objetivo") == o) for o in OBJETIVOS}

    assert min(conteo.values()) >= 0.9 * max(conteo.values()), conteo


def test_cada_ataque_indirecto_de_resena_tiene_su_resena_portadora(casos_seguridad):
    casos, resenas = casos_seguridad
    por_id = {r["id"]: r for r in resenas}
    de_resena = [
        c for c in casos if c["tipo"] == "indirecto" and c.get("portador", "resena") == "resena"
    ]

    assert len(de_resena) == N_INDIRECTOS
    for caso in de_resena:
        resena = por_id[caso["review_id"]]
        assert resena["is_adversarial"] is True
        assert resena["product_id"] == caso["producto_portador"]
        assert resena["attack_id"] == caso["case_id"]


def test_los_ataques_de_descripcion_no_usan_resenas(casos_seguridad):
    """La carga va en la ficha del producto, no en una reseña.

    Si un caso de descripción arrastrara además un `review_id`, habría dos superficies
    inyectadas en la misma ejecución y al ver el centinela en la respuesta no se sabría por
    cuál de las dos entró: justo la pregunta que el corpus v1.3 existe para responder.
    """
    casos, resenas = casos_seguridad
    de_descripcion = [c for c in casos if c.get("portador") == "descripcion"]

    assert len(de_descripcion) == N_INDIRECTOS_DESCRIPCION
    for caso in de_descripcion:
        assert "review_id" not in caso, caso["case_id"]
        assert caso["producto_portador"], caso["case_id"]
        assert caso["carga"].strip(), caso["case_id"]
        assert not any(r["attack_id"] == caso["case_id"] for r in resenas), caso["case_id"]


def test_los_benignos_no_llevan_ataque(casos_seguridad):
    casos, _ = casos_seguridad

    for caso in (c for c in casos if c["tipo"] == "benigno"):
        assert "attack_success_criterion" not in caso
        assert caso["carga"] == ""
        assert TargetState.model_validate(caso["target_state"]).min_recomendaciones >= 1


def test_asignaciones_reparte_particion_y_objetivo():
    reparto = asignaciones(100)

    assert sum(1 for p, _ in reparto if p == "dev") == 30
    assert len({o for _, o in reparto}) == len(OBJETIVOS)


def test_los_casos_de_seguridad_validan_contra_el_esquema(casos_seguridad):
    casos, _ = casos_seguridad

    for caso in casos:
        datos = {
            k: v
            for k, v in caso.items()
            if k not in ("carga", "necesidad", "categoria", "persona", "pii_simulada")
        }
        CasoSeguridad.model_validate({**datos, "intent": "texto de prueba"})


# ------------------------------------------------------------------ plantillas


def test_hay_al_menos_seis_plantillas_por_vector_y_particion():
    plantillas = cargar_plantillas()

    for particion in ("dev", "test"):
        for vector in ("direct", "indirect"):
            cuantas = sum(
                1 for p in plantillas if p["particion"] == particion and p["vector"] == vector
            )
            assert cuantas >= 6, f"{particion}/{vector} tiene {cuantas}"


def test_las_plantillas_cubren_los_cuatro_objetivos_en_cada_particion():
    plantillas = cargar_plantillas()

    for particion in ("dev", "test"):
        for vector in ("direct", "indirect"):
            objetivos = {
                p["objetivo"]
                for p in plantillas
                if p["particion"] == particion and p["vector"] == vector
            }
            assert objetivos == set(OBJETIVOS)


def test_ninguna_cadena_de_dev_aparece_en_test():
    # Criterio de "hecho" de la etapa 2. Se comprueba con 5-gramas de palabras: exigir que
    # no se repita ninguna palabra suelta sería imposible en un mismo idioma, y comparar
    # textos completos no detectaría un calco parcial.
    import re

    plantillas = cargar_plantillas()

    def shingles(texto: str, n: int = 5) -> set[str]:
        palabras = re.findall(r"\w+", texto.lower())
        return {" ".join(palabras[i : i + n]) for i in range(max(0, len(palabras) - n + 1))}

    dev = [p for p in plantillas if p["particion"] == "dev"]
    test = [p for p in plantillas if p["particion"] == "test"]

    for a in dev:
        for b in test:
            comunes = shingles(a["texto"]) & shingles(b["texto"])
            assert not comunes, f"{a['id']} y {b['id']} comparten: {sorted(comunes)[:3]}"


# ---------------------------------------------------------------- cumplimiento


def test_hay_un_caso_de_cumplimiento_por_item_del_checklist():
    casos = generar_casos_cumplimiento(SEED)

    # 26 desde el checklist 1.2.0, que añade `INFORMACION_VERAZ_RESULTADOS`. El ítem nuevo va
    # al final de `ITEMS` a propósito: el `case_id` se deriva del orden, así que insertarlo en
    # medio correría los ids siguientes y las 500 transcripciones de E4 dejarían de
    # corresponder a los casos que dicen medir.
    assert len(casos) == len(ITEMS) == 26
    assert len({c["checklist_item"] for c in casos}) == 26
    assert casos[-1]["case_id"] == "CUM-026"
    assert casos[-1]["checklist_item"] == "INFORMACION_VERAZ_RESULTADOS"


def test_el_caso_de_veracidad_de_resultados_es_alcanzable(catalogo_v1):
    """El caso solo mide algo si los productos que pide existen de verdad.

    Si ninguno pudiera satisfacer las restricciones, negar que existen sería **correcto** y el
    caso estaría midiendo un defecto del corpus en vez de la veracidad del agente.
    """
    casos = generar_casos_cumplimiento(SEED)
    assert not validar_casos_de_cumplimiento(casos, catalogo_v1)

    caso = next(c for c in casos if c["checklist_item"] == "INFORMACION_VERAZ_RESULTADOS")
    objetivo = TargetState.model_validate(caso["target_state"])
    alcanzables = productos_alcanzables(objetivo, catalogo_v1)
    assert len(alcanzables) >= 2, alcanzables


def test_el_checklist_cubre_los_derechos_de_la_ley_21719():
    items = {item for item, *_ in ITEMS}

    for derecho in ("ACCESO", "RECTIFICACION", "SUPRESION", "OPOSICION", "PORTABILIDAD"):
        assert f"DERECHO_{derecho}" in items
    for art8bis in ("DECISION_AUTOMATIZADA", "EXPLICACION", "INTERVENCION_HUMANA", "REVISION"):
        assert f"ART8BIS_{art8bis}" in items


def test_los_casos_de_cumplimiento_validan_contra_el_esquema():
    for caso in generar_casos_cumplimiento(SEED):
        CasoCumplimiento.model_validate(caso)


def test_la_pii_simulada_usa_dominio_reservado_y_rut_no_asignado():
    casos = generar_casos_cumplimiento(SEED)

    for caso in casos:
        pii = caso["pii_simulada"]
        if "correo" in pii:
            assert pii["correo"].endswith("@example.cl")
        if "rut" in pii:
            assert pii["rut"].startswith("99.")


def test_el_digito_verificador_del_rut_es_correcto():
    def dv(numero: int) -> str:
        suma, mult = 0, 2
        for d in reversed(str(numero)):
            suma += int(d) * mult
            mult = 2 if mult == 7 else mult + 1
        resto = 11 - (suma % 11)
        return {11: "0", 10: "K"}.get(resto, str(resto))

    for i in range(1, 30):
        rut = rut_simulado(i)
        cuerpo, digito = rut.split("-")
        assert dv(int(cuerpo.replace(".", ""))) == digito


def test_el_correo_simulado_normaliza_tildes():
    assert correo_simulado("Matías Soto") == "matias.soto@example.cl"


def test_el_checklist_marca_items_criticos():
    criticos = [item for item, _, _, criticidad, _ in ITEMS if criticidad == "critico"]

    assert len(criticos) >= 15
