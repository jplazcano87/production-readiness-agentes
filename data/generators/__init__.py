"""Generadores del corpus v1.0.

Dos capas, deliberadamente separadas:

- **programática** (`catalogo`, `casos_robustez`, `casos_seguridad`, `casos_cumplimiento`):
  determinista, sin LLM y sin red. Con la misma semilla produce byte a byte el mismo
  esqueleto. Es la que fija los conteos de la tabla 2 del informe y los estados objetivo.
- **de redacción** (`redaccion`): llama al LLM para escribir el texto en español de Chile.
  Su salida no es reproducible por semilla, y por eso se guarda íntegra en el corpus: el
  corpus se congela con hash y **nunca se regenera al evaluar**.

`build_corpus` orquesta ambas y escribe `data/corpus/v1.0/`.
"""

SEED_GLOBAL = 20260906
CORPUS_VERSION = "v1.0"

__all__ = ["CORPUS_VERSION", "SEED_GLOBAL"]
