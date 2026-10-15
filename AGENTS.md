# Guía para contribuir al código

Para quien vaya a tocar este repositorio, con o sin ayuda de un asistente de programación. No
sustituye a [`CONTRIBUTING.md`](CONTRIBUTING.md), que explica qué contribuciones se reciben y
cómo se revisan: esto es lo que hay que saber **antes de editar un archivo**.

## Qué es

Un marco para decidir si un agente de pre-venta basado en un modelo de lenguaje está listo para
producción. Mide tres dimensiones y las consolida en un veredicto conjuntivo:

- **Robustez**: consistencia bajo no determinismo, con la métrica pass^k.
- **Seguridad**: inyección de instrucciones directa e indirecta, con cuatro configuraciones de
  defensa y la tasa de éxito de ataque como métrica.
- **Cumplimiento**: un checklist ejecutable derivado de la Ley N° 21.719 de Chile y de la
  circular SERNAC 2022.

El código vive en `src/prf/` —`env/` el sandbox y el evaluador, `agent/` las configuraciones de
defensa, `eval/` las métricas, `compliance/` el checklist, `verdict/` el veredicto, `infra/`
configuración y resultados—. Los experimentos se lanzan desde `scripts/`.

## Lo primero

```bash
uv sync                                        # o pip install -e ".[dev]"
pytest -q                                      # sin red, unos pocos segundos
python scripts/verificar_equivalencia.py       # huellas de los artefactos congelados
```

Las dos cosas tienen que pasar **antes y después** de cualquier cambio. La suite no toca la red
ni la API: si una prueba necesita una respuesta del modelo, usa el doble que valida contra la
firma del SDK instalado.

Antes de abrir un pull request, además:

```bash
ruff check . && ruff format --check .
python scripts/verificar_equivalencia.py --completo   # rehace los artefactos y los compara
```

El modo `--completo` tarda cerca de medio minuto: copia el árbol a un directorio temporal, crea
allí **su propio entorno virtual** con el paquete instalado no editable, vuelve a generar los
artefactos derivados y los compara con los publicados. Comprueba también que el repositorio no
haya cambiado mientras tanto.

## Lo que no se toca

Estos archivos **describen lo que se midió**. Cambiarlos no corrige un resultado: lo invalida,
porque las cifras publicadas dejan de corresponder a los datos que las produjeron.

| Qué | Dónde |
|---|---|
| Corpus, con su manifiesto y su hash de contenido | `data/corpus/<versión>/` |
| Particiones de desarrollo y prueba | `data/splits/<versión>/` |
| Umbrales y política de decisión | `configs/thresholds.yaml` |
| Registro de lo congelado para la corrida final | `configs/congelado_corrida_final.json` |
| Resultados publicados | `results/*.json` |
| Transcripciones por ejecución | `results/runs_*/` |
| Textos de los prompts y sus huellas | `src/prf/agent/prompts.py` |

`docs/MANIFIESTO_ARTEFACTOS.json` guarda el SHA-256 de cada uno y el verificador los comprueba.
Un cambio accidental falla en las pruebas, no en la revisión.

Las versiones de los componentes —agente, evaluador, criterio de ataque, checklist, política—
tampoco se tocan: describen con qué se midió, y cada resultado las declara en su metadata. La
versión del paquete en `pyproject.toml` sí avanza con las publicaciones; las otras no.

## Cómo se cambia algo que afecta a un resultado

Nunca editando lo anterior. Siempre **creando una versión nueva**, de modo que lo medido antes
siga siendo reproducible y lo nuevo se pueda comparar con ello.

### Corpus

Las versiones son **incrementales y solo añaden**. Una versión nueva contiene a la anterior byte
a byte —prefijo exacto de líneas en los `.jsonl`, archivos idénticos en los `.json`— y ningún
caso heredado cambia de partición: al reparticionar se le pasa la asignación de la versión base,
porque sin eso añadir un caso rebaraja su estrato y mueve casos ya medidos.

```bash
python data/generators/build_corpus.py --base v1.4 --version v1.5 --reusar-texto
python scripts/make_splits.py --check
```

`--reusar-texto` redacta solo las intenciones de los casos nuevos, así que añadir casos no
obliga a pagar de nuevo la redacción de los antiguos. `tests/test_corpus_incremental.py`
comprueba la contención y la estabilidad de las particiones.

### Política de aceptación

`configs/thresholds.yaml` lleva su propia versión y un registro de cambios. Cada regla declara
`id`, `campo` y `vincula`; cargar la política **falla** si una regla no declara si vincula, y
una prueba comprueba que el `campo` de cada regla resuelve sobre el JSON del experimento que la
alimenta. Un cambio de política se publica con versión nueva y los veredictos se escriben con
sufijo, sin pisar los de la política anterior.

### Checklist de cumplimiento

`src/prf/compliance/checklist.yaml` lleva su propia versión. Añadir o cambiar un ítem exige tres
cosas: el verificador, al menos un caso del corpus que lo ejercite, y una prueba de regresión
que compruebe que lo que antes se reprobaba con razón se sigue reprobando. Es la salvaguarda
contra la forma más fácil de «arreglar» un verificador: aflojarlo hasta que apruebe todo.

## Cómo se corre algo que cuesta dinero

Todo script que llama a la API acepta `--dry-run`, que imprime tokens y costo estimado en
dólares sin llamar a nada. **Se ejecuta primero, siempre.** La clave va en `ANTHROPIC_API_KEY`,
dentro de un `.env` que nunca se versiona; `.env.example` lista las variables sin valores.

Quien contribuya asume el costo de sus propias corridas. La compuerta de pre-vuelo
(`scripts/prevuelo.py`) hace trece comprobaciones antes de gastar en una corrida larga.

Los recálculos que **no** llaman a la API —reaplicar el evaluador, reclasificar con un criterio
nuevo, consolidar el veredicto, generar tablas y figuras— están en el README y son los que el
verificador rehace.

## Convenciones

- **Español de Chile** en todo el texto generado para el corpus, y en comentarios y
  documentación. El código, en inglés donde ya lo está.
- Los comentarios explican **por qué**, no qué hace la línea de al lado. Varias decisiones de
  este repositorio parecen arbitrarias hasta que se lee la razón; esa razón va en el código.
- `ruff` con la configuración de `pyproject.toml`, línea de 100 caracteres.
- Una prueba se elimina solo junto con el código que prueba, y el pull request lo dice.

## Si un agente trabaja en este repositorio

Esto son instrucciones operativas. La política para contribuciones asistidas por IA está en
[`CONTRIBUTING.md`](CONTRIBUTING.md) y no se repite aquí.

- **No toca los artefactos congelados** de la tabla de arriba. El error más caro que puede
  cometer un agente en este repositorio es regenerar un artefacto medido para «arreglar» una
  prueba.
- **No ejecuta nada que gaste API** sin que lo decida quien contribuye. Todo script que llama a
  la API acepta `--dry-run`, y es lo que corre primero.
- Conviene darle este archivo como contexto, junto con qué está congelado y por qué. Varias
  decisiones de aquí parecen arbitrarias hasta que se lee la razón, y sin ella un asistente las
  «corrige».
