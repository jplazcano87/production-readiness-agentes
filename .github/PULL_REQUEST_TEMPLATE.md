## Qué cambia, y por qué

<!-- Dos o tres líneas. Si el cambio parece arbitrario sin su razón, la razón va en el código,
     no solo aquí. -->

## La compuerta

- [ ] `pytest -q` pasa, sin red
- [ ] `ruff check .` y `ruff format --check .` limpios
- [ ] `python scripts/verificar_equivalencia.py --completo` pasa
- [ ] Sin secretos, claves ni `.env` en el diff
- [ ] **Ningún artefacto congelado modificado**, o bien el cambio crea una versión nueva: corpus
      aditivo con su hash, política con versión y entrada en su registro de cambios, checklist
      con versión, verificador, caso que lo ejercite y prueba de regresión
- [ ] Documentación al día: `README.md` y su traducción, `docs/` y `CHANGELOG.md` si corresponde

## Si corriste algo que cuesta dinero

- [ ] `--dry-run` primero, y el costo real de la corrida queda en la metadata del resultado

<!-- Si una prueba se elimina, dilo aquí y nombra el código que se elimina con ella. -->
