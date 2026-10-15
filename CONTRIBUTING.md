# Cómo contribuir

*This project's documentation, corpus and results are in Chilean Spanish, and so is this guide.
Issues and pull requests in English are welcome, and so are replications with other models,
providers or jurisdictions. The two rules that matter most: **frozen artifacts are never
modified**, because the published figures would stop corresponding to the data that produced
them, and **every script that calls the API accepts `--dry-run`**, which you run first. The rest
of this document explains both in detail.*

Gracias por mirar esto. El proyecto es un artefacto de investigación de un trabajo de
graduación: las mediciones están cerradas y los artefactos congelados, así que lo que más sirve
no es corregir una cifra sino **medir algo nuevo con el mismo marco**, o encontrar que el marco
se equivoca.

## Contribuciones que sirven

- **Reportes de errores** en el arnés, el evaluador, los verificadores o los scripts.
- **Documentación**: aclarar lo que no se entiende, corregir lo que induce a error, traducir.
- **Configuraciones de defensa nuevas**: otra variante de aislamiento, otro patrón de
  planificación, una defensa publicada que valga la pena comparar.
- **Familias de ataque nuevas**: formulaciones que el corpus no cubre, sobre todo las que eluden
  las defensas que aquí aprueban.
- **Adaptación a otros modelos o proveedores**, incluidos modelos abiertos.
- **Ítems de checklist para otras jurisdicciones**. El checklist vigente deriva de la Ley N°
  21.719 de Chile y de la circular SERNAC 2022; el mecanismo es general.
- **Réplicas con resultados**, incluso si contradicen lo publicado. Sobre todo si lo contradicen.

Si vas a invertir tiempo en algo grande, abre antes un issue. No para pedir permiso, sino para
no duplicar trabajo y para saber de antemano si el cambio choca con algo congelado.

## Lo que no se acepta

**Modificar un artefacto congelado.** Corpus, particiones, umbrales, el registro de lo
congelado, los resultados publicados, las transcripciones y los textos de los prompts con sus
huellas. La lista está en [`AGENTS.md`](AGENTS.md) y sus SHA-256 en
`docs/MANIFIESTO_ARTEFACTOS.json`, que el verificador comprueba. Cambiar uno de esos archivos no
corrige un resultado: lo invalida, porque las cifras publicadas dejan de corresponder a los
datos que las produjeron. Un cambio así falla en las pruebas, no en la revisión.

Lo que afecta a un resultado se hace **creando una versión nueva**, de modo que lo medido antes
siga siendo reproducible y lo nuevo se pueda comparar con ello:

| Qué cambias | Cómo |
|---|---|
| Corpus | Versión nueva, **aditiva**: contiene a la anterior byte a byte, con su manifiesto y su hash de contenido nuevos, y ningún caso heredado cambia de partición |
| Política de aceptación | Versión nueva en `configs/thresholds.yaml`, con su entrada en el registro de cambios del propio archivo, y los veredictos con sufijo, sin pisar los de la política anterior |
| Checklist de cumplimiento | Versión nueva en `src/prf/compliance/checklist.yaml`, con el verificador, al menos un caso del corpus que lo ejercite y una prueba de regresión |

El procedimiento de cada uno, con los comandos, está en [`AGENTS.md`](AGENTS.md).

## Entorno

```bash
git clone https://github.com/jplazcano87/production-readiness-agentes.git
cd production-readiness-agentes
uv sync                                        # o: pip install -e ".[dev]"
pytest -q                                      # sin red, unos pocos segundos
python scripts/verificar_equivalencia.py       # huellas de los artefactos congelados
```

Las dos últimas tienen que pasar **antes y después** de cualquier cambio. La suite no toca la
red ni la API: donde una prueba necesita una respuesta del modelo, usa un doble que valida
contra la firma del SDK instalado.

Antes de abrir un pull request:

```bash
uvx pre-commit run --all-files                        # o: pre-commit install
ruff check . && ruff format --check .
python scripts/verificar_equivalencia.py --completo   # rehace los artefactos y los compara
```

El modo `--completo` tarda cerca de medio minuto: copia el árbol a un directorio temporal, crea
allí su propio entorno virtual con el paquete instalado no editable, vuelve a generar los
artefactos derivados y los compara con los publicados, y comprueba que el repositorio no haya
cambiado mientras tanto. Lo que hace cada paso está en
[`docs/REPRODUCIBILIDAD.md`](docs/REPRODUCIBILIDAD.md).

## Guías para los cuatro aportes típicos

### Una configuración de defensa

1. Añádela en `src/prf/agent/configuraciones.py`, con su entrada en `CONFIGURACIONES`. Si
   necesita un prompt propio, va en `src/prf/agent/prompts.py`; los textos existentes no se
   tocan, porque sus huellas están congeladas.
2. Declara qué hace con el contenido no confiable. Las dos superficies de inyección del corpus
   son la reseña y la descripción comercial del producto, y una defensa que sanee solo una deja
   la otra abierta.
3. Pruebas: una que fije lo que el modelo ve en tu configuración y una por cada regla que tu
   defensa impone al flujo de control. `tests/test_registro_invariante.py` y
   `tests/test_agente_cte.py` son los dos ejemplos a seguir.
4. Correr E1 a E4 con la configuración nueva cuesta dinero. Primero `--dry-run`.

### Una plantilla de ataque

1. Las plantillas viven en `data/templates/attacks/dev/` y `data/templates/attacks/test/`, y
   **ninguna cadena se repite entre las dos**. Es lo que permite afirmar que lo medido en prueba
   no se ajustó durante la calibración.
2. **Calibra solo en desarrollo.** Mirar la partición de prueba mientras ajustas una carga
   invalida la separación para siempre, y no hay forma de deshacerlo.
3. Cada plantilla declara su objetivo de ataque y su criterio programático de éxito. El criterio
   vigente, 1.2.0, distingue citar de obedecer: un agente que menciona lo que la carga pedía y
   se niega a hacerlo no cuenta como ataque exitoso.
4. Un corpus con plantillas nuevas es una versión nueva del corpus, aditiva, con su hash.

### Un ítem de checklist

1. El ítem va en `src/prf/compliance/checklist.yaml`, con su fuente normativa, su criticidad y
   su verificador.
2. El verificador va en `src/prf/compliance/verifiers.py` y recibe la respuesta y el estado del
   sandbox, no el texto suelto.
3. Hace falta **al menos un caso del corpus que lo ejercite**. Un ítem que ningún caso ejercita
   no mide nada, y el proyecto ya arrastra una limitación de ese tipo.
4. Hace falta **una prueba de regresión** que compruebe que lo que antes se reprobaba con razón
   se sigue reprobando. Es la salvaguarda contra la forma más fácil de «arreglar» un
   verificador: aflojarlo hasta que apruebe todo.
5. Un ítem nuevo es una versión nueva del checklist, y los resultados anteriores no se
   recalculan con ella sin decirlo.

### Correr con otro modelo o proveedor

1. Los roles y sus modelos están en `configs/models.yaml`: el agente, el modelo en cuarentena,
   el planificador, el simulador de usuario y el juez.
2. **`--dry-run` primero, siempre.** Imprime tokens y costo estimado en dólares sin llamar a
   nada. Después un piloto corto, y solo entonces la corrida completa. La compuerta de
   pre-vuelo (`scripts/prevuelo.py`) hace trece comprobaciones antes de gastar en una corrida
   larga.
3. **El costo lo asume quien contribuye.** No hay presupuesto del proyecto.
4. La clave va en `ANTHROPIC_API_KEY`, dentro de un `.env` que **nunca se versiona**.
   `.env.example` lista las variables sin valores. Si subes una clave por accidente, revócala
   antes de hacer cualquier otra cosa.
5. Cambiar de modelo obliga a volver a medir todo: la política de aceptación no es una propiedad
   del sistema sino del par sistema-modelo, y el repositorio tiene la medición que lo demuestra.

## Flujo

1. **Issue antes de un cambio grande.** Para algo pequeño, el pull request basta.
2. **Rama** desde `main`, con un nombre que diga qué hace.
3. **Pull request** con la plantilla, que lleva la lista de la compuerta: pruebas, verificador de
   equivalencia, sin secretos, sin cambios en artefactos congelados (o la versión nueva que
   corresponde) y documentación al día.
4. **Revisión.** El proyecto se mantiene con dedicación parcial: cuenta con una primera
   respuesta en una o dos semanas, y con que una réplica o una configuración nueva tome más,
   porque hay que leerla de verdad. Si pasan tres semanas sin respuesta, comenta en el pull
   request; no es desinterés.
5. Las pruebas corren en CI sobre Python 3.11 y 3.12, sin secretos, porque la suite entera es
   sin red.

### Convenciones

- **Español de Chile** en el texto del corpus, en los comentarios y en la documentación. El
  código, en inglés donde ya lo está.
- Los comentarios explican **por qué**, no qué hace la línea de al lado.
- `ruff` con la configuración de `pyproject.toml`, línea de 100 caracteres.
- Una prueba se elimina solo junto con el código que prueba, y el pull request lo dice.
- Sin rayas (el guion largo) en los textos en español, por coherencia con el informe. Hay una
  prueba que lo exige.

## Contribuciones con asistentes de IA

Están permitidas.

- **Quien contribuye responde por cada línea que envía**: la entiende, la probó y puede
  explicarla en la revisión, igual que si la hubiera escrito sin ayuda.
- **No se exige declarar el uso**, y tampoco se prohíben los trailers que agreguen las
  herramientas.
- Si un agente trabaja en el repositorio, tiene que seguir [`AGENTS.md`](AGENTS.md): **no toca
  artefactos congelados** y **no ejecuta nada que gaste API** sin que lo decida quien
  contribuye.
- Issues, reportes de seguridad y comentarios de revisión **van leídos por una persona**. No se
  aceptan textos generados que nadie revisó: cuestan más tiempo de revisión del que ahorran.

## Conducta y seguridad

La convivencia se rige por [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md). Las vulnerabilidades y
las formas nuevas de eludir las defensas se reportan por el canal privado que describe
[`SECURITY.md`](SECURITY.md), no en un issue público.
