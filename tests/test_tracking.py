"""MLflow es opcional: el repositorio debe funcionar sin él."""

from __future__ import annotations

from prf.infra.tracking import Tracker


def test_desactivado_por_defecto_y_no_hace_nada():
    tracker = Tracker()

    assert tracker.enabled is False
    with tracker.run("prueba") as activo:
        activo.log_params({"config": "none"})
        activo.log_metrics({"pass_k_1": 0.87})


def test_activado_sin_mlflow_instalado_degrada_sin_fallar(monkeypatch, capsys):
    import builtins

    real_import = builtins.__import__

    def _sin_mlflow(nombre, *args, **kwargs):
        if nombre == "mlflow":
            raise ImportError("simulado: mlflow no instalado")
        return real_import(nombre, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _sin_mlflow)

    tracker = Tracker(enabled=True)

    assert tracker.enabled is False
    assert "mlflow" in capsys.readouterr().out
