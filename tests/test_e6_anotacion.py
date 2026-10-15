"""La interfaz de anotación de E6 no filtra nada que ancle a quien anota.

Es la prueba que la ronda anterior no tenía. El formulario de entonces mostraba
`judge_success` y `judge_reason` junto a la celda por rellenar, y el acuerdo de 64/64 que
salió no se puede verificar. Aquí se comprueba sobre el HTML generado que ninguna de
esas cadenas está dentro, y que lo que sí tiene que estar —el pedido, la conversación, la
tabla de productos— está.
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

from e6_anotacion.datos import (  # noqa: E402
    CODIGO_PRODUCTO,
    MARCADORES,
    ROLES_VISIBLES,
    TranscripcionesIncompletas,
    cargar_muestra,
    cargar_practica,
    con_opciones_mixtas,
    limpiar,
)
from e6_anotacion.generar import (  # noqa: E402
    HISTORIAL,
    PRACTICA,
    SEPARACION_MINIMA,
    TAG_POLITICA,
    VERSION,
    manifiesto,
)
from e6_anotacion.plantilla import AYUDA_CODIGO, CLAVE_ALMACENAMIENTO, render  # noqa: E402
from prf.env import Catalog  # noqa: E402
from prf.infra.config import load_experiments, load_thresholds  # noqa: E402

CSV_CIEGO = RAIZ / "data" / "annotation" / "e6_sample_ciego.csv"


@pytest.fixture(scope="module")
def muestra():
    catalogo = Catalog.from_corpus(load_experiments()["corpus_version"])
    return cargar_muestra(
        CSV_CIEGO,
        RAIZ,
        load_experiments()["seed_global"],
        catalogo,
        separacion=SEPARACION_MINIMA,
    )


@pytest.fixture(scope="module")
def html(muestra):
    casos, _ = muestra
    return render(casos=[c.to_dict() for c in casos], practica=[], version=VERSION)


@pytest.fixture(scope="module")
def filas():
    return list(csv.DictReader(CSV_CIEGO.open(encoding="utf-8")))


@pytest.fixture(scope="module")
def practica():
    catalogo = Catalog.from_corpus(load_experiments()["corpus_version"])
    return cargar_practica(PRACTICA, RAIZ, catalogo)


@pytest.fixture(scope="module")
def catalogo():
    return Catalog.from_corpus(load_experiments()["corpus_version"])


@pytest.fixture(scope="module")
def datos_embebidos(html):
    """El JSON que el HTML lleva dentro: es ahí donde un campo filtrado haría daño.

    Buscar los términos en todo el documento da falsos positivos —`display:none` contiene
    «none», y la cabecera del CSV contiene «human_success», que es la columna que la persona
    rellena— así que la comprobación de campos se hace sobre los datos.
    """
    return "".join(bloques_de_datos(html))


def bloques_de_datos(html: str) -> list[str]:
    bloques = re.findall(r'<script type="application/json"[^>]*>(.*?)</script>', html, re.DOTALL)
    assert bloques, "el HTML debe llevar sus datos en bloques application/json"
    return bloques


# ------------------------------------------------------------------- ciegamiento


def test_el_html_no_contiene_ningun_run_id_ni_case_id(html, filas):
    presentes = [f["run_id"] for f in filas if f["run_id"] in html]
    assert not presentes, f"run_id filtrados: {presentes[:5]}"
    casos = {f["case_id"] for f in filas}
    assert not [c for c in casos if c in html], "case_id filtrados"


def test_los_datos_no_nombran_ninguna_configuracion_de_defensa(datos_embebidos):
    for config in ("dual_llm", "prompt_only", "cte", "none"):
        assert not re.search(rf"\b{config}\b", datos_embebidos), config


def test_los_datos_no_nombran_el_tipo_de_caso(datos_embebidos):
    for tipo in ("busqueda", "comparacion", "recomendacion"):
        assert not re.search(rf"\b{tipo}\b", datos_embebidos), tipo


def test_los_datos_no_traen_ningun_veredicto(datos_embebidos):
    for clave in (
        "state_success",
        "judge_success",
        "judge_reason",
        "human_success",
        "exito",
        "success",
        "evaluacion",
        "target_state",
        "must_compare",
        "min_recomendaciones",
        "constraints",
        "forbidden_tools",
    ):
        assert clave not in datos_embebidos, clave


def test_el_documento_entero_no_trae_veredictos_ajenos(html):
    """`human_success` sí aparece: es la columna que la persona rellena en el CSV que descarga.
    Lo que no puede aparecer en ninguna parte es el veredicto de otro anotador."""
    for clave in ("state_success", "judge_success", "judge_reason", "target_state"):
        assert clave not in html, clave


def test_el_html_no_trae_los_marcadores_internos(html):
    assert not MARCADORES.search(html)
    assert "<<rec:" not in html and "<<cmp:" not in html


def test_el_html_no_trae_el_turno_del_planificador(html, muestra):
    casos, _ = muestra
    assert "planificador" not in html
    for caso in casos:
        assert {t["rol"] for t in caso.turnos} <= set(ROLES_VISIBLES), caso.id_anonimo


def test_la_correspondencia_va_fuera_del_html(muestra, html):
    _, correspondencia = muestra
    assert len(correspondencia) == 68  # 64 de la muestra + 4 repeticiones
    assert {c["id_anonimo"] for c in correspondencia} == {f"C{i:02d}" for i in range(1, 69)}
    # Lo que traduce el id anónimo al run_id no puede estar dentro del archivo que se entrega.
    for fila in correspondencia:
        assert fila["run_id"] not in html


# ------------------------------------------------------------------- contenido útil


def test_estan_las_68_con_id_anonimo(muestra, html):
    casos, _ = muestra
    assert len(casos) == 68
    for caso in casos:
        assert f'"{caso.id_anonimo}"' in html


def test_cada_caso_trae_pedido_conversacion_y_productos(muestra):
    casos, _ = muestra
    for caso in casos:
        assert caso.pedido, caso.id_anonimo
        assert any(t["rol"] == "asistente" for t in caso.turnos), caso.id_anonimo
        # La tabla de productos es lo que permite comprobar una restricción. Sin ella, la
        # pregunta «respetando sus restricciones» no se puede responder.
        assert caso.productos, caso.id_anonimo
        assert all("precio" in p and "atributos" in p for p in caso.productos)
        # «valoracion» y no «evaluacion»: el segundo término queda reservado al veredicto del
        # evaluador, para que el chequeo de filtrado no tenga falsos positivos.
        assert all("evaluacion" not in p for p in caso.productos)


def test_el_orden_es_reproducible_con_la_semilla():
    catalogo = Catalog.from_corpus(load_experiments()["corpus_version"])
    a, _ = cargar_muestra(CSV_CIEGO, RAIZ, 123, catalogo)
    b, _ = cargar_muestra(CSV_CIEGO, RAIZ, 123, catalogo)
    c, _ = cargar_muestra(CSV_CIEGO, RAIZ, 456, catalogo)
    assert [x.pedido for x in a] == [x.pedido for x in b]
    assert [x.pedido for x in a] != [x.pedido for x in c]


def test_los_casos_de_practica_son_de_desarrollo_y_fuera_de_la_muestra(filas):
    dev = set((RAIZ / "data" / "splits" / "v1.2" / "dev.txt").read_text().split())
    en_muestra = {f["run_id"].split("__")[0] for f in filas}
    assert len(PRACTICA) == 4
    for p in PRACTICA:
        caso = Path(p["transcript_path"]).stem.split("__")[0]
        assert caso in dev, p["transcript_path"]
        assert caso not in en_muestra, p["transcript_path"]
        assert p["explicacion"].strip()


# ------------------------------------------------------------------- funcionamiento


def test_el_html_es_autocontenido(html):
    """Sin red: ni un src, ni un href externo, ni una fuente remota."""
    assert not re.search(r"""<(?:script|link|img|iframe)[^>]*\b(?:src|href)=["']https?://""", html)
    assert "cdn" not in html.lower()
    assert "@import" not in html
    assert "fonts.googleapis" not in html


def test_el_guardado_esta_envuelto_en_try_catch(html):
    # En ventana privada `localStorage` lanza al escribir. Debe perderse el guardado, no la
    # sesión de trabajo.
    for trozo in ("localStorage.getItem", "localStorage.setItem"):
        i = html.index(trozo)
        assert "try{" in html[max(0, i - 220) : i], trozo


def test_limpiar_quita_los_marcadores():
    assert limpiar("Te recomiendo esto <<rec:P0001>> y esto <<cmp:P1,P2>>") == (
        "Te recomiendo esto y esto"
    )


def test_el_manifiesto_declara_la_politica_y_el_ciegamiento():
    m = manifiesto(64, 1, load_thresholds())
    assert m["politica"]["thresholds_version"] == str(load_thresholds()["version"])
    assert m["politica"]["tag"] == "policy-v0.3.0"
    # El commit del tag solo se puede resolver donde ese tag existe, y no existe en todas
    # partes: el árbol publicado se exporta sin historia, y una copia de trabajo recién
    # clonada en un CI tampoco trae los tags. Donde no está, el campo queda en `None` y lo
    # que identifica a la política es su versión y su tag, no un SHA que no viaja.
    tag_presente = (
        subprocess.run(
            ["git", "rev-parse", "-q", "--verify", f"refs/tags/{TAG_POLITICA}"],
            cwd=RAIZ,
            capture_output=True,
            text=True,
        ).returncode
        == 0
    )
    if tag_presente:
        assert m["politica"]["commit_del_tag"], "el tag está y su commit tiene que resolver"
    else:  # pragma: no cover - árbol exportado o clon sin tags
        assert m["politica"]["commit_del_tag"] is None
    assert "run_id" in m["ciegamiento"]
    json.dumps(m)  # serializable


def test_si_falta_una_transcripcion_no_se_genera_nada(tmp_path):
    """Generar con 63 de 64 produciría una anotación que no se puede comparar sobre la misma
    muestra, y el hueco se descubriría al final."""
    csv_roto = tmp_path / "ciego.csv"
    csv_roto.write_text(
        "run_id,case_id,config,tipo,transcript_path,human_success\n"
        "X__none__0,X,none,busqueda,results/runs_e1/NO_EXISTE.json,\n",
        encoding="utf-8",
    )
    with pytest.raises(TranscripcionesIncompletas, match="faltan 1 de 1"):
        cargar_muestra(csv_roto, RAIZ, 1)


def test_el_texto_del_agente_se_escapa_antes_de_formatearse(html):
    """El agente escribe Markdown y su texto se inserta con innerHTML para ver las negritas.
    El escape de `&`, `<` y `>` tiene que ir ANTES de aplicar cualquier marca: si no, un texto
    del agente podría inyectar HTML en la página de quien anota."""
    i = html.index("function conFormato(")
    cuerpo = html[i : html.index("function bonito(", i)]
    orden = [
        cuerpo.index('replace(/&/g, "&amp;")'),
        cuerpo.index('replace(/</g, "&lt;")'),
        cuerpo.index("<strong>$1</strong>"),
    ]
    assert orden == sorted(orden), "se formatea antes de escapar"


def test_el_pedido_no_se_repite_en_la_conversacion(html):
    # Está destacado arriba; repetirlo en la primera burbuja alarga la pantalla sin aportar.
    assert 't.rol === "usuario" && t.texto === caso.pedido) return;' in html


# ------------------------------------------------- test-retest y las dos preguntas


def test_hay_cuatro_repeticiones_dos_mixtas_y_dos_claras(muestra):
    _, correspondencia = muestra
    repeticiones = [c for c in correspondencia if c["repeticion_de"]]
    assert len(repeticiones) == 4
    clases = [con_opciones_mixtas(RAIZ / c["transcript_path"]) for c in repeticiones]
    assert clases.count(True) == 2, "dos con el patrón de opciones mixtas"
    assert clases.count(False) == 2, "dos claras, de control"


def test_cada_repeticion_esta_lo_bastante_lejos_de_su_original(muestra):
    """Dos pantallas cercanas con el mismo caso se reconocen, y entonces el acuerdo mide
    memoria y no criterio."""
    _, correspondencia = muestra
    posicion = {c["id_anonimo"]: i for i, c in enumerate(correspondencia, start=1)}
    for c in correspondencia:
        if not c["repeticion_de"]:
            continue
        separacion = posicion[c["id_anonimo"]] - posicion[c["repeticion_de"]]
        assert separacion >= SEPARACION_MINIMA, (c["id_anonimo"], separacion)


def test_la_repeticion_muestra_exactamente_el_mismo_caso(muestra):
    casos, correspondencia = muestra
    por_id = {c.id_anonimo: c for c in casos}
    for c in correspondencia:
        if not c["repeticion_de"]:
            continue
        a, b = por_id[c["repeticion_de"]], por_id[c["id_anonimo"]]
        assert a.pedido == b.pedido and a.turnos == b.turnos and a.productos == b.productos


def test_el_html_hace_las_dos_preguntas_en_orden(html):
    from e6_anotacion.plantilla import P1, P2

    assert "NO cumple alguna condición" in P1
    assert "¿esta respuesta le sirve" in P2
    # P1 es de hecho y va primero; P2 es de juicio.
    assert html.index('var P1 = "') < html.index('var P2 = "')
    assert "Pregunta 1 — revisa la tabla" in html
    assert "Pregunta 2 — tu opinión" in html


def test_el_csv_exporta_las_dos_respuestas_y_la_version(html):
    # `version_instrumento` va AL FINAL: así un CSV de la 1.0 y uno de la 1.1 se leen con el
    # mismo código, y quien abra el archivo ve primero lo que respondió.
    assert (
        '"id_anonimo","p1_opcion_no_cumple","p2_le_sirve","comentario","timestamp",'
        '"segundos_en_pantalla","version_instrumento"' in html
    )
    assert "human_success" not in html
    assert "v: VERSION" in html, "la versión no se guarda en cada respuesta"


def test_un_caso_cuenta_como_hecho_solo_con_las_dos_respondidas(html):
    assert "function completo(r){ return r && r.p1 !== undefined && r.p2 !== undefined; }" in html


def test_la_practica_no_contiene_ningun_caso_con_opciones_mixtas():
    """El patrón difícil tiene que aparecer por primera vez en la muestra. Explicarlo en la
    práctica fijaría el criterio que el experimento quiere medir."""
    for p in PRACTICA:
        assert not con_opciones_mixtas(RAIZ / p["transcript_path"]), p["transcript_path"]


def test_la_bienvenida_no_explica_el_caso_de_opciones_mixtas(html):
    bienvenida = html[
        html.index('<section id="bienvenida">') : html.index('<section id="practica"')
    ]
    for pista in ("mAh", "no cumplen", "alguna no cumple", "basta con que una"):
        assert pista not in bienvenida, pista


def test_el_manifiesto_del_instrumento_esta_versionado_y_coincide_con_lo_entregado():
    """El HTML no se versiona —lleva las transcripciones dentro— así que lo que queda en el
    repositorio es su huella. Sin ella, dentro de seis meses no hay forma de saber si el
    archivo que alguien conserva es el que se anotó."""
    import hashlib

    doc = (RAIZ / "docs" / "E6_INSTRUMENTO.md").read_text(encoding="utf-8")
    entregado = RAIZ / "exports" / "e6_ciego" / "anotacion_e6.html"
    if not entregado.is_file():  # pragma: no cover
        pytest.skip("el HTML no está generado en este árbol")
    assert hashlib.sha256(entregado.read_bytes()).hexdigest() in doc
    assert hashlib.sha256(CSV_CIEGO.read_bytes()).hexdigest() in doc
    assert "policy-v0.3.0" in doc
    assert str(load_experiments()["seed_global"]) in doc


def test_el_html_es_determinista(tmp_path):
    """La huella del manifiesto solo sirve si regenerar da el mismo archivo."""
    catalogo = Catalog.from_corpus(load_experiments()["corpus_version"])
    semilla = load_experiments()["seed_global"]
    uno, _ = cargar_muestra(CSV_CIEGO, RAIZ, semilla, catalogo, separacion=SEPARACION_MINIMA)
    dos, _ = cargar_muestra(CSV_CIEGO, RAIZ, semilla, catalogo, separacion=SEPARACION_MINIMA)
    a = render(casos=[c.to_dict() for c in uno], practica=[], version=VERSION)
    b = render(casos=[c.to_dict() for c in dos], practica=[], version=VERSION)
    assert a == b


# ------------------------------------- v1.1: los códigos de producto en la tabla


# Los cuatro pares de repeticiones tal como quedaron en la versión 1.0 del instrumento. La 1.1
# no puede mover a nadie: si cambiara el orden o los identificadores, quien ya empezó a anotar
# en el mismo navegador vería respuestas suyas en casos que no son los que contestó.
PARES_DE_LA_VERSION_1_0 = {("C10", "C44"), ("C19", "C48"), ("C36", "C61"), ("C31", "C66")}


def _turnos_visibles_a_mano(ruta: Path) -> list[dict[str, str]]:
    """Las mismas transformaciones que aplica el exportador, reimplementadas aquí.

    A propósito no se llama a `limpiar` ni a `caso_desde`: si el test reusara el código del
    exportador, una transformación nueva que reescribiera el texto pasaría desapercibida. Lo
    que se comprueba es que las únicas transformaciones son estas dos —quitar los marcadores
    internos y colapsar los espacios que dejan— y que el resto del texto es el de la
    transcripción, carácter por carácter.
    """
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    salida = []
    for turno in datos["ejecucion"]["transcripcion"]:
        if turno["rol"] not in ROLES_VISIBLES:
            continue
        texto = re.sub(r"<<(?:rec|cmp):[^>]*>>", "", turno["texto"])
        texto = re.sub(r"[ \t]{2,}", " ", texto).strip()
        if texto:
            salida.append({"rol": turno["rol"], "texto": texto})
    return salida


def test_el_texto_de_cada_turno_es_el_de_la_transcripcion(muestra, practica):
    """Ni una palabra del asistente ni del cliente se reescribe.

    La versión 1.1 añade el código del producto a la **tabla**, no al texto. Reemplazar un
    código por un nombre, o añadir una aclaración dentro de la respuesta, mejoraría solo las
    respuestas que usan códigos y sesgaría la comparación entre configuraciones: se juzga la
    respuesta que recibió el cliente.
    """
    casos, correspondencia = muestra
    por_id = {c.id_anonimo: c for c in casos}
    revisados = 0
    for fila in correspondencia:
        caso = por_id[fila["id_anonimo"]]
        esperado = _turnos_visibles_a_mano(RAIZ / fila["transcript_path"])
        assert caso.turnos == esperado, fila["id_anonimo"]
        revisados += 1
    for caso, p in zip(practica, PRACTICA, strict=True):
        assert caso.turnos == _turnos_visibles_a_mano(RAIZ / p["transcript_path"]), caso.id_anonimo
        revisados += 1
    assert revisados == 72, revisados  # 68 pantallas de la muestra + 4 de práctica


def test_los_codigos_del_texto_llegan_tal_cual(muestra):
    """El mismo control, apuntado al cambio que se consideró y se descartó: sustituir el código
    por el nombre del producto dentro de la respuesta."""
    casos, correspondencia = muestra
    por_id = {c.id_anonimo: c for c in casos}
    for fila in correspondencia:
        caso = por_id[fila["id_anonimo"]]
        crudo = json.loads((RAIZ / fila["transcript_path"]).read_text(encoding="utf-8"))
        # Sin los marcadores internos: ahí el código es instrumentación del marco, no algo
        # que el cliente vería, y la 1.0 ya los quitaba.
        del_texto = CODIGO_PRODUCTO.findall(
            MARCADORES.sub(
                "",
                " ".join(
                    t["texto"]
                    for t in crudo["ejecucion"]["transcripcion"]
                    if t["rol"] in ROLES_VISIBLES
                ),
            )
        )
        mostrados = CODIGO_PRODUCTO.findall(" ".join(t["texto"] for t in caso.turnos))
        assert sorted(mostrados) == sorted(del_texto), caso.id_anonimo


def test_todo_codigo_que_el_asistente_escribe_esta_en_la_tabla(muestra, practica):
    """El defecto que la 1.1 arregla.

    En 14 de las 68 pantallas el asistente nombra un producto solo por su código («el más
    económico es P0031»). Sin el código en la tabla, quien anota no sabe de qué producto habla
    la respuesta y la pregunta 1 queda sin respuesta posible sobre esa opción.
    """
    casos, _ = muestra
    con_codigos = 0
    for caso in list(casos) + list(practica):
        citados = {
            c
            for t in caso.turnos
            if t["rol"] == "asistente"
            for c in CODIGO_PRODUCTO.findall(t["texto"])
        }
        if not citados:
            continue
        con_codigos += 1
        en_tabla = {p["codigo"] for p in caso.productos}
        assert citados <= en_tabla, (caso.id_anonimo, sorted(citados - en_tabla))
    assert con_codigos == 17, con_codigos  # 14 de la muestra + 3 de práctica


def test_cada_producto_de_la_tabla_trae_su_codigo_del_catalogo(muestra, practica, catalogo):
    casos, _ = muestra
    for caso in list(casos) + list(practica):
        for producto in caso.productos:
            codigo = producto["codigo"]
            assert CODIGO_PRODUCTO.fullmatch(codigo), (caso.id_anonimo, codigo)
            del_catalogo = catalogo.get(codigo)
            assert del_catalogo is not None, (caso.id_anonimo, codigo)
            assert producto["nombre"] == del_catalogo.name, (caso.id_anonimo, codigo)


def test_la_columna_de_codigo_va_primera(html):
    assert '["Código","Producto","Precio"]' in html
    assert 'fila.appendChild(el("td", null, p.codigo || "—"));' in html


def test_el_codigo_no_identifica_configuracion_caso_ni_veredicto(html, filas):
    """Lo único que se añadió a los datos es el id de catálogo del producto.

    No dice qué configuración produjo la respuesta —las cuatro comparten catálogo— ni qué
    `case_id` es, ni qué dijo ningún evaluador. Se comprueba que no entró nada más.
    """
    casos = [
        c for bloque in bloques_de_datos(html) for c in json.loads(bloque.replace("\\u003c", "<"))
    ]
    for caso in casos:
        assert set(caso) <= {"id", "pedido", "turnos", "productos", "explicacion"}, set(caso)
        for producto in caso["productos"]:
            assert set(producto) == {
                "codigo",
                "nombre",
                "precio",
                "precio_num",
                "stock",
                "valoracion",
                "atributos",
            }, set(producto)
    # Y los códigos no son ninguno de los identificadores que sí anclarían.
    for fila in filas:
        assert not CODIGO_PRODUCTO.fullmatch(fila["case_id"])
        assert not CODIGO_PRODUCTO.fullmatch(fila["run_id"])


def test_la_version_1_1_no_mueve_a_nadie(muestra):
    """El orden, los identificadores anónimos y las repeticiones son los de la 1.0."""
    _, correspondencia = muestra
    pares = {(c["repeticion_de"], c["id_anonimo"]) for c in correspondencia if c["repeticion_de"]}
    assert pares == PARES_DE_LA_VERSION_1_0
    assert [c["id_anonimo"] for c in correspondencia] == [f"C{i:02d}" for i in range(1, 69)]


def test_la_clave_de_almacenamiento_no_lleva_la_version(html):
    """Si la clave cambiara, quien ya empezó a anotar en este navegador perdería su avance."""
    assert CLAVE_ALMACENAMIENTO == "e6-anotacion-1.0"
    assert VERSION == "1.1"
    assert 'var CLAVE = "e6-anotacion-1.0";' in html
    assert "e6-anotacion-" + VERSION not in html


def test_la_bienvenida_declara_las_pantallas_que_hay(html, muestra):
    casos, _ = muestra
    bienvenida = html[
        html.index('<section id="bienvenida">') : html.index('<section id="practica"')
    ]
    assert f"<strong>{len(casos)} conversaciones</strong>" in bienvenida
    assert "68 conversaciones" in bienvenida
    # No se menciona que haya casos repetidos: saberlo haría buscarlos.
    for pista in ("repetid", "dos veces", "64 conversaciones"):
        assert pista not in bienvenida, pista


def test_la_ayuda_del_codigo_va_solo_en_la_practica(html):
    assert "columna Código" in AYUDA_CODIGO
    assert "P0031" in AYUDA_CODIGO
    assert 'if(enPractica) caja.appendChild(el("p","nota","' + AYUDA_CODIGO + '"));' in html
    # No dice nada sobre cómo pesar eso en la pregunta 2: ese criterio es el que se mide.
    for palabra in ("pregunta 2", "le sirve", "no cumple", "debes", "tienes que"):
        assert palabra not in AYUDA_CODIGO.lower(), palabra


def test_el_historial_registra_el_cambio_y_que_es_anterior_a_las_respuestas():
    versiones = [v["version"] for v in HISTORIAL]
    assert versiones == ["1.0", "1.1"]
    assert versiones[-1] == VERSION
    ultimo = HISTORIAL[-1]
    assert ultimo["fecha"] == "2026-10-12"
    assert "código" in ultimo["motivo"]
    assert "no se tocó" in ultimo["no_cambio"]
    assert "antes de recibir ninguna respuesta" in ultimo["cuando"]
    doc = (RAIZ / "docs" / "E6_INSTRUMENTO.md").read_text(encoding="utf-8")
    assert "## Historial de versiones" in doc
    assert f"### Versión {VERSION} — {ultimo['fecha']}" in doc
