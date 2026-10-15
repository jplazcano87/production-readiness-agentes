#!/usr/bin/env python
"""Recorre la interfaz de anotación en un navegador de verdad y valida el CSV que produce.

Comprobar el HTML leyéndolo no basta: lo que importa es que una persona pueda abrirlo con doble
clic, pasar la práctica, responder y descargar un archivo bien formado. Esto lo hace con
Chromium headless **sobre `file://`**, que es como lo va a abrir quien anota —y donde el
almacenamiento del navegador se comporta distinto que servido por HTTP—.

Requiere `playwright`. No es dependencia del marco: si falta, el script lo dice y no falla el
resto de la suite.

Uso:
    python -m e6_anotacion.verificar
    python -m e6_anotacion.verificar --casos 3
"""

from __future__ import annotations

import argparse
import csv
import io
import os
from pathlib import Path

CABECERA = [
    "id_anonimo",
    "p1_opcion_no_cumple",
    "p2_le_sirve",
    "comentario",
    "timestamp",
    "segundos_en_pantalla",
    "version_instrumento",
]


def _navegador(p):
    """El Chromium de Playwright, o el que ya esté instalado en el sistema.

    La versión de `playwright` y la del navegador descargado no siempre coinciden; en vez de
    bajar otro, se usa el que hay.
    """
    try:
        return p.chromium.launch()
    except Exception:
        cache = Path(os.path.expanduser("~/Library/Caches/ms-playwright"))
        for patron in (
            "chromium_headless_shell-*/*/chrome-headless-shell",
            "chromium-*/*/Chromium.app/Contents/MacOS/Chromium",
        ):
            for binario in sorted(cache.glob(patron), reverse=True):
                if binario.is_file():
                    return p.chromium.launch(executable_path=str(binario))
        raise


def verificar(html: Path, n_casos: int) -> int:
    """Recorre la interfaz entera en el navegador y comprueba el CSV que descarga."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("falta playwright: uv pip install playwright")
        return 2

    with sync_playwright() as p:
        navegador = _navegador(p)
        pagina = navegador.new_page(viewport={"width": 420, "height": 820})  # tamaño de celular
        errores: list[str] = []
        pagina.on("pageerror", lambda e: errores.append(str(e)))
        pagina.on("console", lambda m: errores.append(m.text) if m.type == "error" else None)
        pagina.goto(html.as_uri())

        # 1. bienvenida
        assert pagina.is_visible("#bienvenida"), "no se ve la bienvenida"
        total = pagina.evaluate("window.__e6.casos()")
        version = pagina.evaluate("window.__e6.version()")
        clave = pagina.evaluate("window.__e6.clave()")
        # La clave no lleva la versión a propósito: si cambiara, quien ya empezó a anotar en
        # este navegador perdería su avance al abrir la versión nueva.
        assert clave == "e6-anotacion-1.0", clave
        assert f"{total} conversaciones" in pagina.inner_text("#bienvenida"), (
            "la bienvenida no declara el número de pantallas que hay"
        )
        print(f"  bienvenida ok · {total} casos cargados · versión {version} · clave {clave}")

        # 2. práctica: responder los cuatro y leer la explicación de cada uno
        pagina.click("#ir-practica")
        for i in range(4):
            # Esperar al repintado: si no, el click cae sobre los botones del caso anterior.
            pagina.wait_for_function(f"document.getElementById('p-n').textContent === '{i + 1}'")
            pagina.wait_for_selector("#practica .btn.p1.no")
            assert pagina.is_hidden("#p-explicacion"), f"la explicación {i + 1} se ve antes"
            pagina.click("#practica .btn.p1.no")
            # La explicación no puede aparecer hasta que estén las DOS respondidas.
            assert pagina.is_hidden("#p-explicacion"), f"explicación {i + 1} tras solo P1"
            pagina.click("#practica .btn.p2.si" if i % 2 == 0 else "#practica .btn.p2.no")
            pagina.wait_for_selector("#p-explicacion:not([hidden])")
            assert len(pagina.inner_text("#p-explicacion")) > 60, f"explicación {i + 1} corta"
            if i == 0:
                # La ayuda de los códigos va en la práctica y solo ahí.
                assert "columna Código" in pagina.inner_text("#p-caso"), "falta la ayuda"
            pagina.click("#p-siguiente")
        pagina.wait_for_selector("#anotacion:not([hidden])")
        assert "columna Código" not in pagina.inner_text("#a-caso"), (
            "la ayuda de los códigos se repite en la muestra"
        )
        print("  práctica ok · 4 casos, explicación solo tras responder las dos")

        # 3. anotación: responder n casos usando los botones reales
        for i in range(n_casos):
            pagina.wait_for_function(f"document.getElementById('a-n').textContent === '{i + 1}'")
            pagina.wait_for_selector("#anotacion .btn.p1.si")
            caso = pagina.inner_text("#a-n")
            pagina.click("#anotacion .btn.p1.si" if i % 2 == 0 else "#anotacion .btn.p1.no")
            pagina.wait_for_timeout(120)
            assert pagina.inner_text("#a-n") == caso, "avanzó con solo P1 respondida"
            pagina.click("#anotacion .btn.p2.si" if i % 2 == 0 else "#anotacion .btn.p2.no")
            pagina.wait_for_timeout(300)  # el avance automático tras las dos
            print(f"  caso {caso} respondido (P1 y P2)")
        hechos = pagina.evaluate("window.__e6.casos() - window.__e6.faltan()")
        assert hechos == n_casos, f"se registraron {hechos} respuestas y se esperaban {n_casos}"

        # 4. el guardado sobrevive a recargar
        pagina.reload()
        pagina.wait_for_selector("#anotacion:not([hidden])")
        tras_recargar = pagina.evaluate("window.__e6.casos() - window.__e6.faltan()")
        assert tras_recargar == n_casos, "el avance no se recuperó al recargar"
        print(f"  guardado ok · {tras_recargar} respuestas tras recargar")

        # 5. pantalla final: avisa de los que faltan antes de descargar
        pagina.click("#ir-final")
        pagina.wait_for_selector("#final:not([hidden])")
        aviso = pagina.inner_text("#f-estado")
        assert f"faltan {total - n_casos}" in aviso.lower(), (
            f"no avisa de los pendientes: {aviso!r}"
        )
        print(f"  aviso de pendientes ok · «{aviso.splitlines()[0]}»")

        # 6. descarga y formato del CSV
        with pagina.expect_download() as descarga:
            pagina.click("#f-descargar")
        archivo = descarga.value
        assert archivo.suggested_filename == "respuestas_e6.csv", archivo.suggested_filename
        crudo = Path(archivo.path()).read_bytes().decode("utf-8-sig")
        filas = list(csv.DictReader(io.StringIO(crudo)))
        assert list(filas[0]) == CABECERA, list(filas[0])
        assert len(filas) == n_casos, f"{len(filas)} filas, se esperaban {n_casos}"
        for f in filas:
            assert f["p1_opcion_no_cumple"] in ("0", "1"), f
            assert f["p2_le_sirve"] in ("0", "1"), f
            assert f["id_anonimo"].startswith("C"), f
            assert f["timestamp"].endswith("Z"), f
            assert float(f["segundos_en_pantalla"]) >= 0, f
            assert f["version_instrumento"] == version, f
        print(
            f"  CSV ok · {len(filas)} filas, cabecera con p1, p2 y version_instrumento, valores 0/1"
        )

        navegador.close()
        if errores:
            print("\nERRORES DE JAVASCRIPT:")
            for e in errores[:10]:
                print("  ", e)
            return 1
        print("\nsin errores de JavaScript")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Recorre el HTML en un navegador real y valida el CSV que descarga."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--html",
        default="exports/e6_ciego/anotacion_e6.html",
        help="Archivo HTML que se recorre en el navegador.",
    )
    parser.add_argument(
        "--casos", type=int, default=3, help="Cuántos casos se responden antes de descargar el CSV."
    )
    args = parser.parse_args(argv)
    html = Path(args.html).resolve()
    if not html.is_file():
        raise SystemExit(f"falta {html}: ejecuta antes python -m e6_anotacion.generar")
    print(f"verificando {html.name} en Chromium headless, viewport de celular")
    return verificar(html, args.casos)


if __name__ == "__main__":
    raise SystemExit(main())
