"""El verificador de equivalencia detecta lo que tiene que detectar.

Un verificador que siempre dice «todo bien» es peor que no tenerlo: da por comprobado lo que
nadie comprobó. Aquí se le dan artefactos alterados y se exige que falle, además de correrlo
en modo rápido sobre el árbol real, que debe pasar.

El modo completo —que rehace los artefactos en una copia con su propio entorno virtual— no se
ejecuta aquí: tarda medio minuto, instala un paquete y necesita `uv`. Va en el CI y en la
compuerta de cada PR.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

import verificar_equivalencia as ve  # noqa: E402


@pytest.fixture
def manifiesto() -> dict:
    return json.loads(ve.MANIFIESTO.read_text(encoding="utf-8"))


# ------------------------------------------------------------------- el árbol real


def test_el_modo_rapido_pasa_sobre_el_arbol_real():
    assert ve.main([]) == 0


def test_el_manifiesto_cubre_el_contrato_de_rutas(manifiesto):
    """Lo que el informe cita por nombre tiene que estar congelado, no solo existir."""
    cubiertos = set(manifiesto["artefactos"])
    sin_congelar = [
        r for r in ve.CONTRATO if r not in cubiertos and not r.startswith(("tables/", "figures/"))
    ]
    assert not sin_congelar, sin_congelar
    # Las tablas no van en el manifiesto a propósito: son derivadas y se comprueban
    # rehaciéndolas, que es una garantía más fuerte que un hash.
    assert not [r for r in manifiesto["artefactos"] if r.startswith("tables/")]


def test_el_manifiesto_trae_las_cinco_versiones_del_corpus_y_sus_particiones(manifiesto):
    for version in ve.VERSIONES_CORPUS:
        assert f"data/corpus/{version}/MANIFEST.json" in manifiesto["artefactos"], version
        assert f"data/splits/{version}/dev.txt" in manifiesto["artefactos"], version
    # Los corpus de trabajo de la calibración no son artefactos congelados.
    assert not [r for r in manifiesto["artefactos"] if "-dev/" in r]


def test_el_bloqueo_de_dependencias_esta_congelado(manifiesto):
    """Describe el entorno de las corridas de octubre, así que modificarlo tiene que fallar en
    las pruebas y en el CI, no quedar a la vista de quien revise el diff."""
    assert "requirements-lock.txt" in manifiesto["artefactos"]
    assert "requirements-lock.txt" in ve.CONFIGURACION


def test_los_retenidos_declaran_su_motivo(manifiesto):
    assert set(manifiesto["retenidos"]) == set(ve.RETENIDOS)
    for rel, dato in manifiesto["retenidos"].items():
        assert dato["motivo"].strip(), rel
        assert len(dato["sha256_original"]) == 64, rel


def test_las_transcripciones_pendientes_quedan_ancladas_antes_de_publicarse(manifiesto):
    """Se anotan ahora para que el PR que las publique no pueda alterarlas por el camino."""
    pendientes = manifiesto["pendientes_de_publicar"]
    assert set(ve.PENDIENTES) <= set(pendientes)
    assert not set(ve.PENDIENTES) & set(manifiesto["colecciones"])


# ------------------------------------------------------------------- detecta cambios


def test_detecta_un_artefacto_alterado(tmp_path, monkeypatch, manifiesto):
    falso = dict(manifiesto)
    falso["artefactos"] = dict(manifiesto["artefactos"])
    falso["artefactos"]["configs/thresholds.yaml"] = {"sha256": "0" * 64, "bytes": 1}
    destino = tmp_path / "manifiesto.json"
    destino.write_text(json.dumps(falso), encoding="utf-8")
    monkeypatch.setattr(ve, "MANIFIESTO", destino)
    fallos = ve.comprobar_huellas(RAIZ)
    assert any("configs/thresholds.yaml" in f for f in fallos), fallos


def test_detecta_un_artefacto_que_falta(tmp_path, monkeypatch, manifiesto):
    falso = dict(manifiesto)
    falso["artefactos"] = {**manifiesto["artefactos"], "results/no_existe.json": {"sha256": "x"}}
    destino = tmp_path / "manifiesto.json"
    destino.write_text(json.dumps(falso), encoding="utf-8")
    monkeypatch.setattr(ve, "MANIFIESTO", destino)
    assert any("no_existe" in f for f in ve.comprobar_huellas(RAIZ))


def test_detecta_una_coleccion_con_un_archivo_de_mas(tmp_path, monkeypatch, manifiesto):
    """El hash de árbol cubre la lista de archivos, no solo su contenido: añadir una
    transcripción a una colección congelada también es un cambio."""
    falso = dict(manifiesto)
    falso["colecciones"] = {
        **manifiesto["colecciones"],
        "results/runs_e4": {
            **manifiesto["colecciones"]["results/runs_e4"],
            "sha256_del_arbol": "0" * 64,
        },
    }
    destino = tmp_path / "manifiesto.json"
    destino.write_text(json.dumps(falso), encoding="utf-8")
    monkeypatch.setattr(ve, "MANIFIESTO", destino)
    assert any("runs_e4" in f for f in ve.comprobar_huellas(RAIZ))


def test_el_manifiesto_no_se_regenera_encima_de_si_mismo():
    """Se genera una sola vez. Regenerarlo en silencio convertiría cualquier cambio en el
    estado nuevo y el verificador dejaría de verificar nada."""
    assert ve.generar(RAIZ, agregar=False) == 2
    assert json.loads(ve.MANIFIESTO.read_text(encoding="utf-8"))["artefactos"]


# ------------------------------------------------- lo que el agente recibe del sandbox


def test_la_salida_de_las_herramientas_es_la_fijada():
    """El hueco que esto cubre: las huellas cubren el corpus y los prompts, pero no el código
    que sirve esos datos. Un campo nuevo en un modelo, un filtro que deja pasar una clave más
    o un orden de resultados distinto cambian lo que el agente ve sin tocar ni el corpus ni el
    prompt."""
    assert ve.comprobar_salida_de_herramientas(RAIZ) == []


def test_la_sonda_cubre_una_dimension_de_cada_una_y_las_tres_herramientas():
    assert set(ve.SONDA_DE_HERRAMIENTAS) == {"robustez", "seguridad", "cumplimiento"}
    salida = ve.salida_de_herramientas()
    for tipo in ve.SONDA_DE_HERRAMIENTAS:
        assert set(salida[tipo]) == {
            "caso",
            "del_sandbox",
            "con_la_defensa_que_quita_la_descripcion",
        }, tipo
        for capa in ("del_sandbox", "con_la_defensa_que_quita_la_descripcion"):
            assert set(salida[tipo][capa]) == {
                "search_catalog",
                "get_product",
                "get_reviews",
            }, (tipo, capa)


def test_la_sonda_es_determinista():
    """Si no lo fuera, la comprobación fallaría sola y dejaría de mirarse."""
    assert ve.salida_de_herramientas() == ve.salida_de_herramientas()


def test_un_campo_distinto_en_la_salida_de_herramientas_se_detecta(tmp_path, monkeypatch):
    referencia = json.loads(ve.SALIDA_HERRAMIENTAS.read_text(encoding="utf-8"))
    referencia["robustez"]["del_sandbox"]["get_product"]["resultado"]["price_clp"] = 1
    destino = tmp_path / "salida.json"
    destino.write_text(json.dumps(referencia), encoding="utf-8")
    monkeypatch.setattr(ve, "SALIDA_HERRAMIENTAS", destino)
    fallos = ve.comprobar_salida_de_herramientas(RAIZ)
    assert fallos and "price_clp" in fallos[0]


def test_la_referencia_no_trae_anotaciones_del_andamiaje():
    """Las reseñas llevan `is_adversarial` y `attack_id` en el corpus, y el sandbox las quita
    antes de servirlas. Si volvieran, el agente vería cada ataque etiquetado como ataque, que
    es un defecto que este repositorio ya tuvo una vez."""
    crudo = ve.SALIDA_HERRAMIENTAS.read_text(encoding="utf-8")
    assert "is_adversarial" not in crudo
    assert "attack_id" not in crudo


def test_la_referencia_fija_que_la_defensa_quita_la_descripcion():
    """La otra superficie de inyección indirecta. La capa de la defensa tiene que llegar sin
    `description` y la del sandbox con ella: si las dos coincidieran, la defensa no estaría
    haciendo nada y la referencia lo diría."""
    referencia = json.loads(ve.SALIDA_HERRAMIENTAS.read_text(encoding="utf-8"))
    for tipo in ve.SONDA_DE_HERRAMIENTAS:
        del_sandbox = json.dumps(referencia[tipo]["del_sandbox"])
        con_defensa = json.dumps(referencia[tipo]["con_la_defensa_que_quita_la_descripcion"])
        assert '"description"' in del_sandbox, tipo
        assert '"description"' not in con_defensa, tipo


# ------------------------------------------------------------------- campos volátiles


def test_los_campos_descriptivos_van_en_su_propia_lista_y_son_los_declarados():
    """Volátil y descriptivo no son lo mismo y no pueden compartir lista.

    Un campo volátil cambia solo en cada ejecución; uno descriptivo lo cambia una edición, y
    por eso entra de uno en uno y con el motivo escrito al lado. Mezclarlos convertiría la
    lista de exclusiones en un cajón donde cabe cualquier diferencia incómoda.
    """
    assert ve.DESCRIPTIVOS == {"metadata.reclasificado.motivo"}
    assert not ve.DESCRIPTIVOS & ve.VOLATILES


def test_un_campo_descriptivo_se_ignora_pero_el_resto_del_documento_no():
    a = {"metadata": {"reclasificado": {"motivo": "porque sí", "n_cambios": 28}}}
    b = {"metadata": {"reclasificado": {"motivo": "por otra razón", "n_cambios": 28}}}
    assert ve.diferencias_json(a, b) == []
    b["metadata"]["reclasificado"]["n_cambios"] = 27
    assert ve.diferencias_json(a, b) == [".metadata.reclasificado.n_cambios"]


def test_la_reclasificacion_de_e2_esta_entre_los_pasos_que_se_rehacen():
    """Escribe dos resultados publicados; si no se rehiciera, nadie comprobaría que el
    criterio corregido sigue dando la misma clasificación."""
    ordenes = [" ".join(p["orden"]) for p in ve.PASOS]
    assert "scripts/e2_reclasificar.py --entrada e2_security" in ordenes
    assert "scripts/e2_reclasificar.py --entrada e2_security_haiku" in ordenes
    escribe = {rel for p in ve.PASOS for rel in p["escribe"]}
    assert "results/e2_security_criterio1.2.0.json" in escribe
    assert "results/e2_security_haiku_criterio1.2.0.json" in escribe


def test_la_lista_de_volatiles_es_cerrada_y_solo_trae_lo_que_no_es_resultado():
    assert ve.VOLATILES == {
        "metadata.timestamp",
        "metadata.git_commit",
        "metadata.git_dirty",
        "versiones.por_resultado.e1.timestamp",
        "versiones.por_resultado.e2.timestamp",
        "versiones.por_resultado.e3.timestamp",
        "versiones.por_resultado.e4.timestamp",
    }


def test_los_volatiles_se_ignoran_y_lo_demas_no():
    a = {"metadata": {"timestamp": "ayer", "seed": 20260906}, "asr": 0.1}
    b = {"metadata": {"timestamp": "hoy", "seed": 20260906}, "asr": 0.1}
    assert ve.diferencias_json(a, b) == []
    b["asr"] = 0.2
    assert ve.diferencias_json(a, b) == [".asr"]
    b["asr"] = 0.1
    b["metadata"]["seed"] = 1
    assert ve.diferencias_json(a, b) == [".metadata.seed"]


def test_una_lista_mas_corta_se_detecta():
    assert ve.diferencias_json({"x": [1, 2, 3]}, {"x": [1, 2]}) == [".x (largo 3 vs 2)"]


def test_un_campo_que_desaparece_se_detecta():
    assert ve.diferencias_json({"a": 1, "b": 2}, {"a": 1}) == [".b"]


# ------------------------------------------------------------------- prompts y contrato


def test_las_huellas_de_los_prompts_son_las_congeladas():
    assert ve.comprobar_prompts(RAIZ) == []


def test_el_contrato_de_rutas_se_cumple():
    assert ve.comprobar_contrato(RAIZ) == []


def test_cada_paso_sin_api_declara_lo_que_escribe():
    for paso in ve.PASOS:
        assert paso["orden"][0].startswith("scripts/"), paso
        assert paso["escribe"], paso
        for rel in paso["escribe"]:
            assert (RAIZ / rel).is_file(), rel


# ------------------------------------- las figuras en una plataforma que no es la suya


def _png(ruta, cambios: dict) -> None:
    from PIL import Image

    imagen = Image.new("RGB", (100, 100), (128, 128, 128))
    for (x, y), color in cambios.items():
        imagen.putpixel((x, y), color)
    imagen.save(ruta)


def test_en_su_plataforma_cualquier_diferencia_de_figura_falla(tmp_path, monkeypatch):
    original, rehecho = tmp_path / "a.png", tmp_path / "b.png"
    _png(original, {})
    _png(rehecho, {(0, 0): (128, 128, 129)})
    monkeypatch.setattr(ve, "plataforma_actual", lambda: ve.PLATAFORMA_DE_LAS_FIGURAS)
    monkeypatch.setattr(ve, "AVISOS", [])

    problemas = ve.comparar(original, rehecho, "figures/informe/f.png")
    assert problemas and "delta máximo 1" in problemas[0]
    assert ve.AVISOS == []


def test_en_otra_plataforma_un_canal_de_diferencia_se_declara_y_no_falla(tmp_path, monkeypatch):
    """El tratamiento preregistrado en `docs/REPRODUCIBILIDAD.md`: una diferencia de
    renderizado se declara con sus cifras; no se silencia y no hace fallar."""
    original, rehecho = tmp_path / "a.png", tmp_path / "b.png"
    _png(original, {})
    _png(rehecho, {(0, 0): (128, 128, 129)})
    monkeypatch.setattr(ve, "plataforma_actual", lambda: ("Linux", "x86_64"))
    monkeypatch.setattr(ve, "AVISOS", [])

    assert ve.comparar(original, rehecho, "figures/informe/f.png") == []
    assert len(ve.AVISOS) == 1
    assert "diferencia de plataforma declarada" in ve.AVISOS[0]
    assert "Linux/x86_64" in ve.AVISOS[0]


def test_en_otra_plataforma_una_diferencia_de_datos_sigue_fallando(tmp_path, monkeypatch):
    """El límite existe para distinguir renderizado de datos: cuarenta canales con delta 72 son
    datos, y eso falla en cualquier plataforma."""
    original, rehecho = tmp_path / "a.png", tmp_path / "b.png"
    _png(original, {})
    _png(rehecho, {(x, 0): (200, 128, 128) for x in range(40)})
    monkeypatch.setattr(ve, "plataforma_actual", lambda: ("Linux", "x86_64"))
    monkeypatch.setattr(ve, "AVISOS", [])

    problemas = ve.comparar(original, rehecho, "figures/informe/f.png")
    assert problemas and "delta máximo 72" in problemas[0]
    assert ve.AVISOS == []


def test_el_limite_de_plataforma_es_estrecho_y_esta_fijado():
    assert ve.DELTA_DE_PLATAFORMA == 1
    assert ve.PROPORCION_DE_PLATAFORMA == 0.001
    assert ve.PLATAFORMA_DE_LAS_FIGURAS == ("Darwin", "arm64")
