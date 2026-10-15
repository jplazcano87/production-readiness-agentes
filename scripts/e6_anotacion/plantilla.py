"""El HTML autocontenido de la interfaz de anotación.

Un solo archivo, sin dependencias externas y sin red: se abre con doble clic y funciona. La
persona que anota no es técnica y puede estar en un notebook o en un celular, así que la letra
es grande, los botones son grandes y no hay jerga.

Los datos van embebidos en un `<script type="application/json">`. El `<` se escapa para que un
texto que contenga `</script` no pueda cerrar el bloque antes de tiempo.
"""

from __future__ import annotations

import json
from typing import Any

# Dos preguntas, y el orden importa. La primera es de HECHO —se contesta mirando la tabla de
# productos— y la segunda es de JUICIO. Separarlas permite saber, cuando alguien dice que la
# respuesta le sirve, si es porque no vio el problema o porque lo vio y no le importó.
P1 = (
    "¿Alguna de las opciones que ofreció el asistente NO cumple alguna condición que pidió el "
    "cliente (por ejemplo, presupuesto o características)?"
)
P2 = "Si usted fuera este cliente, ¿esta respuesta le sirve para lo que pidió?"

CRITERIO = """Vas a responder <strong>dos preguntas</strong> en cada caso. La primera es de
revisar: comparar lo que el cliente pidió con las opciones que aparecen en la tabla. La segunda
es tu opinión como cliente. No importa si la respuesta es larga o corta, ni si está bien
escrita, ni si el asistente fue amable."""


def _embebido(datos: Any) -> str:
    return json.dumps(datos, ensure_ascii=False).replace("<", "\\u003c")


# La clave con la que el navegador guarda el avance. **No** se deriva de la versión del
# instrumento a propósito: si cambiara, quien ya empezó a anotar en este mismo navegador
# perdería todo su avance al abrir la versión nueva. La versión viaja en cada respuesta y en el
# CSV, que es donde hace falta saberla.
CLAVE_ALMACENAMIENTO = "e6-anotacion-1.0"

AYUDA_CODIGO = (
    "A veces el asistente nombra un producto por su código (por ejemplo, P0031) en vez de su "
    "nombre. Si necesitas saber cuál es, búscalo en la columna Código de la tabla."
)


def render(
    *,
    casos: list[dict[str, Any]],
    practica: list[dict[str, Any]],
    version: str,
    clave_almacenamiento: str = CLAVE_ALMACENAMIENTO,
) -> str:
    """El HTML completo, con los casos ya ciegos dentro."""
    return (
        _PLANTILLA.replace("__CASOS__", _embebido(casos))
        .replace("__PRACTICA__", _embebido(practica))
        .replace("__P1__", P1)
        .replace("__P2__", P2)
        .replace("__CRITERIO__", CRITERIO)
        .replace("__AYUDA_CODIGO__", AYUDA_CODIGO)
        .replace("__CLAVE__", clave_almacenamiento)
        .replace("__VERSION__", version)
        .replace("__TOTAL__", str(len(casos)))
    )


_PLANTILLA = r"""<!doctype html>
<html lang="es-CL">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Revisión de respuestas — E6</title>
<style>
  :root{
    --fondo:#f7f7f5; --papel:#fff; --tinta:#1c1c1a; --suave:#5d5d57;
    --linea:#ddddd6; --acento:#2b5f8f; --si:#1f7a4d; --no:#a63333;
    --radio:14px; --base:19px;
  }
  @media (prefers-color-scheme: dark){
    :root{ --fondo:#1a1a18; --papel:#242422; --tinta:#f0f0ec; --suave:#a8a8a0;
           --linea:#3a3a36; --acento:#7eb3e0; --si:#5cc48c; --no:#e07a7a; }
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--fondo);color:var(--tinta);
       font:var(--base)/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
  .hoja{max-width:62rem;margin:0 auto;padding:1.25rem}
  h1{font-size:1.9rem;line-height:1.25;margin:.2em 0 .6em}
  h2{font-size:1.3rem;margin:1.6em 0 .5em}
  p{margin:.7em 0}
  .grande{font-size:1.12rem}
  .tarjeta{background:var(--papel);border:1px solid var(--linea);border-radius:var(--radio);
           padding:1.1rem 1.25rem;margin:1rem 0}
  .barra{height:12px;background:var(--linea);border-radius:99px;overflow:hidden;margin:.5rem 0 1rem}
  .barra i{display:block;height:100%;background:var(--acento);transition:width .25s}
  .cabecera{display:flex;flex-wrap:wrap;gap:.75rem;align-items:baseline;justify-content:space-between}
  .cuenta{font-weight:700;font-size:1.25rem}
  .etiqueta{font-size:.95rem;color:var(--suave);text-transform:uppercase;letter-spacing:.05em;
            font-weight:700;margin:1.4rem 0 .4rem}
  .pedido{background:#fff8e6;border-left:6px solid #e0a93b;border-radius:8px;padding:1rem 1.15rem;
          font-size:1.15rem}
  @media (prefers-color-scheme: dark){ .pedido{background:#2e2a1e} }
  .burbuja{max-width:85%;padding:.8rem 1rem;border-radius:16px;margin:.5rem 0;white-space:pre-wrap;
           overflow-wrap:anywhere}
  .burbuja.usuario{background:#e8eef5;margin-left:auto;border-bottom-right-radius:4px}
  .burbuja.asistente{background:var(--papel);border:1px solid var(--linea);
                     border-bottom-left-radius:4px}
  @media (prefers-color-scheme: dark){ .burbuja.usuario{background:#2c3a47} }
  .quien{font-size:.85rem;color:var(--suave);margin:.9rem 0 -.2rem}
  .tabla-caja{overflow-x:auto;-webkit-overflow-scrolling:touch}
  table{border-collapse:collapse;width:100%;font-size:.98rem}
  th,td{border-bottom:1px solid var(--linea);padding:.55rem .6rem;text-align:left;vertical-align:top}
  th{background:var(--fondo);font-size:.9rem;white-space:nowrap}
  td.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
  .btn{font:inherit;font-weight:700;padding:.75rem 1.4rem;border-radius:12px;border:2px solid var(--linea);
       background:var(--papel);color:var(--tinta);cursor:pointer;min-height:48px}
  .btn:hover{border-color:var(--acento)}
  .btn.principal{background:var(--acento);border-color:var(--acento);color:#fff}
  .btn:disabled{opacity:.45;cursor:not-allowed}
  .decision{display:flex;gap:1rem;flex-wrap:wrap;margin:.8rem 0}
  .btn.si,.btn.no{flex:1 1 11rem;font-size:1.3rem;padding:1.1rem;min-height:68px}
  .btn.si{border-color:var(--si);color:var(--si)}
  .btn.no{border-color:var(--no);color:var(--no)}
  .btn.si[aria-pressed=true]{background:var(--si);color:#fff}
  .btn.no[aria-pressed=true]{background:var(--no);color:#fff}
  textarea{width:100%;font:inherit;padding:.7rem;border-radius:10px;border:1px solid var(--linea);
           background:var(--papel);color:var(--tinta);min-height:4.5rem}
  .pie{display:flex;gap:.75rem;flex-wrap:wrap;justify-content:space-between;margin-top:1.2rem}
  .indice{display:flex;flex-wrap:wrap;gap:.4rem;margin:.6rem 0}
  .indice button{font:inherit;font-size:.9rem;min-width:3.2rem;min-height:40px;padding:.3rem;
                 border-radius:8px;border:1px solid var(--linea);background:var(--papel);
                 color:var(--suave);cursor:pointer}
  .indice button.hecho{background:var(--si);border-color:var(--si);color:#fff;font-weight:700}
  .indice button.actual{outline:3px solid var(--acento);outline-offset:1px}
  .aviso{background:#fdf0f0;border-left:6px solid var(--no);border-radius:8px;padding:.9rem 1.1rem}
  @media (prefers-color-scheme: dark){ .aviso{background:#3a2626} }
  .ok{background:#eef7f1;border-left:6px solid var(--si);border-radius:8px;padding:.9rem 1.1rem}
  @media (prefers-color-scheme: dark){ .ok{background:#24352c} }
  .nota{color:var(--suave);font-size:.95rem}
  [hidden]{display:none !important}
  @media (max-width:40rem){
    :root{--base:18px}
    .hoja{padding:.9rem}
    .burbuja{max-width:100%}
  }
</style>
</head>
<body>
<div class="hoja">

<!-- ───────────────────────────── 1. bienvenida ───────────────────────────── -->
<section id="bienvenida">
  <h1>Revisión de respuestas de un asistente de tienda</h1>
  <div class="tarjeta grande">
    <p>Vas a leer <strong>__TOTAL__ conversaciones</strong> entre un cliente y un asistente automático
      de una tienda de electrónica. En cada una, el cliente pide algo y el asistente responde.</p>
    <p>Tu tarea es decidir una sola cosa: <strong>si la respuesta le resuelve al cliente lo que
      pidió</strong>. Nada más.</p>
    <p>Toma unas <strong>2 horas</strong>. No hace falta hacerlo de una vez: el avance se guarda
      solo en este computador, y si cierras la página puedes volver y seguir donde quedaste.</p>
    <p>Antes de empezar hay <strong>4 casos de práctica</strong> para tomarle la mano. Esos no
      cuentan.</p>
  </div>
  <button class="btn principal" id="ir-practica">Empezar</button>
</section>

<!-- ───────────────────────────── 2. práctica ───────────────────────────── -->
<section id="practica" hidden>
  <div class="cabecera">
    <span class="cuenta">Práctica <span id="p-n">1</span> de <span id="p-total">4</span></span>
    <span class="nota">estas respuestas no se guardan</span>
  </div>
  <div class="barra"><i id="p-barra" style="width:0%"></i></div>
  <div class="tarjeta grande">__CRITERIO__</div>
  <div id="p-caso"></div>
  <div id="p-explicacion" hidden></div>
  <div class="pie">
    <span></span>
    <button class="btn principal" id="p-siguiente" hidden>Siguiente</button>
  </div>
</section>

<!-- ───────────────────────────── 3. anotación ───────────────────────────── -->
<section id="anotacion" hidden>
  <div class="cabecera">
    <span class="cuenta">Caso <span id="a-n">1</span> de <span id="a-total">__TOTAL__</span></span>
    <span class="nota"><span id="a-hechos">0</span> respondidos · se guarda solo</span>
  </div>
  <div class="barra"><i id="a-barra" style="width:0%"></i></div>
  <div id="a-caso"></div>
  <div class="pie">
    <button class="btn" id="a-anterior">← Anterior</button>
    <button class="btn" id="a-siguiente">Siguiente →</button>
  </div>
  <h2>Ir a un caso</h2>
  <p class="nota">En verde los que ya respondiste.</p>
  <div class="indice" id="a-indice"></div>
  <div class="pie">
    <span></span>
    <button class="btn principal" id="ir-final">Terminar y descargar</button>
  </div>
</section>

<!-- ───────────────────────────── 4. final ───────────────────────────── -->
<section id="final" hidden>
  <h1>Listo</h1>
  <div id="f-estado"></div>
  <div class="pie">
    <button class="btn" id="f-volver">← Volver a los casos</button>
    <button class="btn principal" id="f-descargar">Descargar mis respuestas</button>
  </div>
  <p class="nota">Se descarga un archivo <code>respuestas_e6.csv</code>. Envíalo tal cual, sin
    abrirlo ni editarlo en Excel.</p>
</section>

<p class="nota">Versión __VERSION__</p>
</div>

<script type="application/json" id="datos-casos">__CASOS__</script>
<script type="application/json" id="datos-practica">__PRACTICA__</script>
<script>
(function(){
  "use strict";
  var CASOS = JSON.parse(document.getElementById("datos-casos").textContent);
  var PRACTICA = JSON.parse(document.getElementById("datos-practica").textContent);
  var P1 = "__P1__";
  var P2 = "__P2__";
  var VERSION = "__VERSION__";
  // La clave NO lleva la versión: cambiarla haría perder el avance de quien ya empezó.
  var CLAVE = "__CLAVE__";

  // El almacenamiento puede fallar (ventana privada, datos bloqueados). La anotación no se
  // interrumpe por eso: se pierde el guardado, no el trabajo en curso.
  var memoria = {respuestas:{}, indice:0, pantalla:"bienvenida"};
  function cargar(){
    try{
      var crudo = window.localStorage.getItem(CLAVE);
      if(crudo){ var x = JSON.parse(crudo); if(x && x.respuestas) memoria = x; }
    }catch(e){ /* sin guardado: se sigue igual */ }
  }
  function guardar(){
    try{ window.localStorage.setItem(CLAVE, JSON.stringify(memoria)); }
    catch(e){ /* sin guardado */ }
  }

  function $(id){ return document.getElementById(id); }
  function el(tag, clase, texto){
    var n = document.createElement(tag);
    if(clase) n.className = clase;
    if(texto !== undefined && texto !== null) n.textContent = texto;
    return n;
  }
  function mostrar(cual){
    ["bienvenida","practica","anotacion","final"].forEach(function(s){
      $(s).hidden = (s !== cual);
    });
    memoria.pantalla = cual; guardar();
    window.scrollTo(0,0);
  }

  // ───────── render de un caso (común a práctica y anotación) ─────────
  function pintarCaso(caso, enPractica){
    var caja = document.createDocumentFragment();

    caja.appendChild(el("div","etiqueta","Lo que pidió el cliente"));
    caja.appendChild(el("div","pedido", caso.pedido || "(sin mensaje)"));

    caja.appendChild(el("div","etiqueta","Lo que respondió el asistente"));
    var chat = el("div","chat");
    caso.turnos.forEach(function(t, i){
      // El primer mensaje del cliente ya está destacado arriba: repetirlo alarga la pantalla
      // y hace buscar dos veces lo mismo.
      if(i === 0 && t.rol === "usuario" && t.texto === caso.pedido) return;
      chat.appendChild(el("div","quien", t.rol === "usuario" ? "Cliente" : "Asistente"));
      var b = el("div","burbuja " + (t.rol === "usuario" ? "usuario" : "asistente"));
      b.innerHTML = conFormato(t.texto);
      chat.appendChild(b);
    });
    caja.appendChild(chat);

    if(caso.productos && caso.productos.length){
      caja.appendChild(el("div","etiqueta","Productos que consultó el asistente"));
      caja.appendChild(el("p","nota",
        "Sirve para comprobar el precio y las características. El asistente vio esto."));
      // Solo en la práctica: decir cómo se lee la tabla es enseñar a usar el instrumento. En la
      // muestra no se repite, y en ningún caso se dice qué hacer con eso en la pregunta 2, que
      // es el criterio propio de la persona y es lo que el experimento mide.
      if(enPractica) caja.appendChild(el("p","nota","__AYUDA_CODIGO__"));
      var claves = {};
      caso.productos.forEach(function(p){
        Object.keys(p.atributos || {}).forEach(function(k){ claves[k] = true; });
      });
      var cols = Object.keys(claves);
      var caja2 = el("div","tabla-caja");
      var tabla = el("table");
      var thead = el("thead"), tr = el("tr");
      ["Código","Producto","Precio"].concat(cols.map(bonito)).concat(["Stock","Estrellas"]).forEach(function(h){
        tr.appendChild(el("th", null, h));
      });
      thead.appendChild(tr); tabla.appendChild(thead);
      var tbody = el("tbody");
      caso.productos.forEach(function(p){
        var fila = el("tr");
        fila.appendChild(el("td", null, p.codigo || "—"));
        fila.appendChild(el("td", null, p.nombre));
        fila.appendChild(el("td","num", p.precio));
        cols.forEach(function(k){
          var v = (p.atributos || {})[k];
          fila.appendChild(el("td","num", v === undefined ? "—" : formatear(v)));
        });
        fila.appendChild(el("td","num", p.stock === undefined || p.stock === null ? "—" : String(p.stock)));
        fila.appendChild(el("td","num", p.valoracion === undefined || p.valoracion === null ? "—" : String(p.valoracion)));
        tbody.appendChild(fila);
      });
      tabla.appendChild(tbody); caja2.appendChild(tabla); caja.appendChild(caja2);
    }
    return caja;
  }
  // El agente escribe en Markdown. Mostrar `**así**` con los asteriscos a la vista es ruido
  // para quien no es técnico. Se escapa primero todo el HTML y después se aplican solo tres
  // marcas: negrita, cursiva y viñetas. Nada de HTML del texto puede llegar a la página.
  function conFormato(texto){
    var seguro = texto
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
    seguro = seguro
      .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,;:!?]|$)/g, "$1<em>$2</em>")
      .replace(/^\s*[-•]\s+/gm, "• ")
      .replace(/^\s*#{1,6}\s*/gm, "")
      .replace(/^\s*---+\s*$/gm, "──────────");
    return seguro;
  }

  function bonito(k){
    var n = {ram_gb:"RAM (GB)", ssd_gb:"SSD (GB)", pantalla_pulgadas:"Pantalla (\")",
             peso_kg:"Peso (kg)", procesador:"Procesador", bateria_mah:"Batería (mAh)",
             camara_mp:"Cámara (MP)", almacenamiento_gb:"Almacenam. (GB)",
             autonomia_horas:"Autonomía (h)", cancelacion_ruido:"Cancela ruido",
             resistencia_agua:"Resist. agua", pulgadas:"Pulgadas", resolucion:"Resolución",
             tecnologia:"Tecnología", capacidad_litros:"Capacidad (L)",
             potencia_watts:"Potencia (W)"};
    return n[k] || k;
  }
  function formatear(v){
    if(v === true) return "sí";
    if(v === false) return "no";
    return String(v);
  }

  function parDeBotones(clase, texto, valorActual, alElegir){
    var fila = el("div","decision");
    var si = el("button","btn si " + clase,"Sí"), no = el("button","btn no " + clase,"No");
    si.type = "button"; no.type = "button";
    si.setAttribute("aria-pressed", valorActual === 1 ? "true" : "false");
    no.setAttribute("aria-pressed", valorActual === 0 ? "true" : "false");
    si.onclick = function(){ alElegir(1); };
    no.onclick = function(){ alElegir(0); };
    fila.appendChild(si); fila.appendChild(no);
    return fila;
  }

  function bloqueDecision(r, alElegir, alComentar){
    r = r || {};
    var caja = document.createDocumentFragment();

    caja.appendChild(el("div","etiqueta","Pregunta 1 — revisa la tabla"));
    var q1 = el("p","grande"); q1.innerHTML = "<strong>" + P1 + "</strong>";
    caja.appendChild(q1);
    caja.appendChild(parDeBotones("p1", "", r.p1, function(v){ alElegir("p1", v); }));

    caja.appendChild(el("div","etiqueta","Pregunta 2 — tu opinión"));
    var q2 = el("p","grande"); q2.innerHTML = "<strong>" + P2 + "</strong>";
    caja.appendChild(q2);
    caja.appendChild(parDeBotones("p2", "", r.p2, function(v){ alElegir("p2", v); }));

    var etq = el("label","nota","Comentario (opcional)");
    etq.setAttribute("for","comentario");
    caja.appendChild(etq);
    var ta = el("textarea"); ta.id = "comentario"; ta.value = r.c || "";
    ta.placeholder = "Si algo te hizo dudar, escríbelo acá.";
    ta.oninput = function(){ alComentar(ta.value); };
    caja.appendChild(ta);
    return caja;
  }

  // ───────── práctica ─────────
  var pIndice = 0;
  function marcarPar(clase, v){
    var botones = document.querySelectorAll("#practica .btn." + clase + ", #anotacion .btn." + clase);
    for(var i = 0; i < botones.length; i++){
      var b = botones[i];
      var esSi = b.classList.contains("si");
      b.setAttribute("aria-pressed", (esSi ? 1 : 0) === v ? "true" : "false");
    }
  }
  function pintarPractica(){
    var caso = PRACTICA[pIndice];
    $("p-n").textContent = String(pIndice + 1);
    $("p-total").textContent = String(PRACTICA.length);
    $("p-barra").style.width = ((pIndice) / PRACTICA.length * 100) + "%";
    var caja = $("p-caso"); caja.innerHTML = "";
    var t = el("div","tarjeta"); t.appendChild(pintarCaso(caso, true));
    var ensayo = {};
    t.appendChild(bloqueDecision(ensayo, function(cual, v){
      ensayo[cual] = v;
      pintarPractica.marcar(cual, v);
      if(ensayo.p1 !== undefined && ensayo.p2 !== undefined){
        $("p-explicacion").hidden = false;
        $("p-siguiente").hidden = false;
        $("p-explicacion").scrollIntoView({behavior:"smooth", block:"nearest"});
      }
    }, function(){}));
    caja.appendChild(t);
    var exp = $("p-explicacion"); exp.innerHTML = "";
    exp.hidden = true;
    var e = el("div","ok");
    e.appendChild(el("div","etiqueta","Cómo se aplica el criterio acá"));
    var p = el("p","grande"); p.innerHTML = caso.explicacion; e.appendChild(p);
    exp.appendChild(e);
    $("p-siguiente").hidden = true;
  }
  pintarPractica.marcar = marcarPar;
  $("ir-practica").onclick = function(){ pIndice = 0; pintarPractica(); mostrar("practica"); };
  $("p-siguiente").onclick = function(){
    pIndice++;
    if(pIndice >= PRACTICA.length){ irA(primerPendiente()); mostrar("anotacion"); }
    else pintarPractica();
  };

  // ───────── anotación ─────────
  var entrada = null;  // momento en que se mostró el caso actual
  function primerPendiente(){
    for(var i = 0; i < CASOS.length; i++){
      if(!completo(memoria.respuestas[CASOS[i].id])) return i;
    }
    return memoria.indice || 0;
  }
  function completo(r){ return r && r.p1 !== undefined && r.p2 !== undefined; }
  function hechos(){
    return CASOS.filter(function(c){ return completo(memoria.respuestas[c.id]); }).length;
  }
  function irA(i){
    memoria.indice = Math.max(0, Math.min(CASOS.length - 1, i));
    entrada = Date.now();
    pintarAnotacion(); guardar();
  }
  function registrar(id, campos){
    var previo = memoria.respuestas[id] || {};
    var seg = entrada ? (Date.now() - entrada) / 1000 : null;
    memoria.respuestas[id] = {
      p1: campos.p1 !== undefined ? campos.p1 : previo.p1,
      p2: campos.p2 !== undefined ? campos.p2 : previo.p2,
      c: campos.c !== undefined ? campos.c : (previo.c || ""),
      ts: new Date().toISOString(),
      seg: Math.round(((previo.seg || 0) + (seg || 0)) * 10) / 10,
      v: VERSION
    };
    if(campos.p1 !== undefined || campos.p2 !== undefined) entrada = Date.now();
    guardar();
  }
  function pintarAnotacion(){
    var caso = CASOS[memoria.indice];
    var r = memoria.respuestas[caso.id] || {};
    $("a-n").textContent = String(memoria.indice + 1);
    $("a-hechos").textContent = String(hechos());
    $("a-barra").style.width = (hechos() / CASOS.length * 100) + "%";
    var caja = $("a-caso"); caja.innerHTML = "";
    var t = el("div","tarjeta");
    t.appendChild(pintarCaso(caso, false));
    t.appendChild(bloqueDecision(r, function(cual, v){
      var campos = {}; campos[cual] = v;
      registrar(caso.id, campos);
      marcarPar(cual, v);
      var ahora = memoria.respuestas[caso.id] || {};
      $("a-hechos").textContent = String(hechos());
      $("a-barra").style.width = (hechos() / CASOS.length * 100) + "%";
      pintarIndice();
      // Solo avanza cuando las dos están contestadas: la primera es de revisión y la segunda
      // de opinión, y saltar tras la primera haría perder la segunda.
      if(ahora.p1 !== undefined && ahora.p2 !== undefined && memoria.indice < CASOS.length - 1){
        setTimeout(function(){ irA(memoria.indice + 1); }, 220);
      }
    }, function(texto){ registrar(caso.id, {c:texto}); }));
    caja.appendChild(t);
    $("a-anterior").disabled = memoria.indice === 0;
    $("a-siguiente").disabled = memoria.indice === CASOS.length - 1;
    pintarIndice();
  }
  function pintarIndice(){
    var caja = $("a-indice"); caja.innerHTML = "";
    CASOS.forEach(function(c, i){
      var b = el("button", null, c.id);
      b.type = "button";
      if(completo(memoria.respuestas[c.id])) b.className = "hecho";
      if(i === memoria.indice) b.className += " actual";
      b.onclick = function(){ irA(i); };
      caja.appendChild(b);
    });
  }
  $("a-anterior").onclick = function(){ irA(memoria.indice - 1); };
  $("a-siguiente").onclick = function(){ irA(memoria.indice + 1); };

  // ───────── final y descarga ─────────
  function faltantes(){
    return CASOS.filter(function(c){ return !completo(memoria.respuestas[c.id]); });
  }
  $("ir-final").onclick = function(){
    var falta = faltantes();
    var caja = $("f-estado"); caja.innerHTML = "";
    if(falta.length){
      var a = el("div","aviso");
      a.appendChild(el("p","grande",
        "Te faltan " + falta.length + " de " + CASOS.length + " casos por responder."));
      var lista = el("div","indice");
      falta.forEach(function(c){
        var b = el("button", null, c.id); b.type = "button";
        b.onclick = function(){
          irA(CASOS.findIndex(function(x){ return x.id === c.id; })); mostrar("anotacion");
        };
        lista.appendChild(b);
      });
      a.appendChild(lista);
      a.appendChild(el("p","nota","Puedes descargar igual, pero lo ideal es completarlos."));
      caja.appendChild(a);
    }else{
      var ok = el("div","ok");
      ok.appendChild(el("p","grande","Respondiste los " + CASOS.length + " casos. Gracias."));
      caja.appendChild(ok);
    }
    mostrar("final");
  };
  $("f-volver").onclick = function(){ mostrar("anotacion"); };

  function csv(){
    var filas = [["id_anonimo","p1_opcion_no_cumple","p2_le_sirve","comentario","timestamp","segundos_en_pantalla","version_instrumento"]];
    CASOS.forEach(function(c){
      var r = memoria.respuestas[c.id];
      if(!completo(r)) return;
      // `r.v` falta si la respuesta se guardó con una versión anterior en este mismo navegador.
      // Se exporta vacío en vez de suponer la versión actual: la respuesta no se dio con esta.
      filas.push([c.id, String(r.p1), String(r.p2), r.c || "", r.ts || "",
                  r.seg === null || r.seg === undefined ? "" : String(r.seg),
                  r.v || ""]);
    });
    return filas.map(function(f){
      return f.map(function(v){
        var s = String(v);
        return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
      }).join(",");
    }).join("\r\n") + "\r\n";
  }
  $("f-descargar").onclick = function(){
    var blob = new Blob(["﻿" + csv()], {type:"text/csv;charset=utf-8"});
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url; a.download = "respuestas_e6.csv";
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    setTimeout(function(){ URL.revokeObjectURL(url); }, 2000);
  };

  // Enganche para la verificación automatizada: no se usa en la interfaz.
  window.__e6 = {
    casos: function(){ return CASOS.length; },
    version: function(){ return VERSION; },
    clave: function(){ return CLAVE; },
    csv: csv,
    responder: function(id, p1, p2, c){
      memoria.indice = CASOS.findIndex(function(x){ return x.id === id; });
      entrada = Date.now(); registrar(id, {p1:p1, p2:p2, c:c}); },
    faltan: function(){ return faltantes().length; }
  };

  cargar();
  $("a-total").textContent = String(CASOS.length);
  if(memoria.pantalla === "anotacion" || hechos() > 0){ irA(memoria.indice || primerPendiente()); mostrar("anotacion"); }
  else mostrar("bienvenida");
})();
</script>
</body>
</html>
"""

__all__ = ["AYUDA_CODIGO", "CLAVE_ALMACENAMIENTO", "CRITERIO", "P1", "P2", "render"]
