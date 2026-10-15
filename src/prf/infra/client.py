"""Wrapper del SDK de Anthropic para todos los experimentos del framework.

Capacidades exigidas por la etapa 0 del plan:

- llamadas en tiempo real con medición de TTFT (streaming, marca de tiempo del primer
  delta de contenido) — es lo que consume E3;
- envío y recolección de lotes con la Batch API (−50 %) — E1, E2 y E6;
- `cache_control` en el system prompt y en el bloque de catálogo;
- reintentos con backoff exponencial y jitter;
- contabilidad de tokens por llamada, incluida la caché.

Decisiones que quedan fijas aquí:

- Los reintentos los lleva este wrapper, no el SDK: el cliente se construye con
  `max_retries=0` para no encadenar dos políticas de reintento distintas.
- `--dry-run` no usa este módulo para estimar: usa `prf.infra.tokens.approx_tokens`,
  porque la regla de trabajo 3 exige no llamar a la API en ese modo.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import anthropic
from dotenv import load_dotenv

from prf.infra.config import ModelRole, ModelsConfig, load_models
from prf.infra.cost import Usage, estimate_cost_usd
from prf.infra.paths import paths

CacheControl = dict[str, str]
_EPHEMERAL: CacheControl = {"type": "ephemeral"}

# Estados terminales de un lote en la Batch API.
_BATCH_ENDED = "ended"


@dataclass
class CallResult:
    """Resultado de una llamada, con todo lo que los experimentos deben registrar."""

    role: str
    model: str
    text: str
    content: list[dict[str, Any]]
    stop_reason: str | None
    usage: Usage
    latency_s: float | None
    ttft_s: float | None
    # Tiempo hasta el primer token de TEXTO. `ttft_s` marca el primer token de cualquier
    # bloque, incluido el JSON de una llamada a herramienta, que el usuario no ve. Para E3
    # la distinción importa: un agente que empieza invocando una herramienta no ha mostrado
    # nada todavía.
    ttft_texto_s: float | None = None
    timestamp: str | None = None
    api_mode: str = "realtime"
    request_id: str | None = None
    custom_id: str | None = None
    batch: bool = False
    streamed: bool = False
    cache_enabled: bool = False
    n_intentos: int = 1

    def resumen_llamada(self) -> dict[str, Any]:
        """Fila del registro por llamada, sin el contenido: solo lo que E3 necesita."""
        return {
            "role": self.role,
            "model": self.model,
            "request_id": self.request_id,
            "timestamp": self.timestamp,
            "api_mode": self.api_mode,
            "streamed": self.streamed,
            "cache_enabled": self.cache_enabled,
            "ttft_s": self.ttft_s,
            "ttft_texto_s": self.ttft_texto_s,
            "latency_s": self.latency_s,
            **self.usage.to_dict(),
        }

    @property
    def contenido_para_reenvio(self) -> list[dict[str, Any]]:
        """El turno del asistente, listo para volver a enviarse como historial."""
        return bloques_para_reenvio(self.content)

    @property
    def tool_uses(self) -> list[dict[str, Any]]:
        """Bloques `tool_use` de la respuesta, en orden."""
        return [bloque for bloque in self.content if bloque.get("type") == "tool_use"]

    @property
    def input_tokens(self) -> int:
        return self.usage.input_tokens

    @property
    def output_tokens(self) -> int:
        return self.usage.output_tokens

    @property
    def cache_read_tokens(self) -> int:
        return self.usage.cache_read_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "model": self.model,
            "text": self.text,
            "content": self.content,
            "stop_reason": self.stop_reason,
            "latency_s": self.latency_s,
            "ttft_s": self.ttft_s,
            "ttft_texto_s": self.ttft_texto_s,
            "timestamp": self.timestamp,
            "api_mode": self.api_mode,
            "request_id": self.request_id,
            "custom_id": self.custom_id,
            "batch": self.batch,
            "streamed": self.streamed,
            "cache_enabled": self.cache_enabled,
            "n_intentos": self.n_intentos,
            **self.usage.to_dict(),
        }


@dataclass
class BatchOutcome:
    """Resultado de una petición dentro de un lote."""

    custom_id: str
    status: str  # succeeded | errored | canceled | expired
    result: CallResult | None = None
    error: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.status == "succeeded" and self.result is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "custom_id": self.custom_id,
            "status": self.status,
            "result": self.result.to_dict() if self.result else None,
            "error": self.error,
        }


@dataclass
class UsageLedger:
    """Contabilidad acumulada de tokens y costo, por modelo y modo."""

    por_modelo: dict[tuple[str, bool], Usage] = field(default_factory=dict)
    n_llamadas: int = 0

    def add(self, model: str, usage: Usage, *, batch: bool) -> None:
        clave = (model, batch)
        self.por_modelo[clave] = self.por_modelo.get(clave, Usage()) + usage
        self.n_llamadas += 1

    def total(self) -> Usage:
        """El uso acumulado de todos los modelos, sumado."""
        total = Usage()
        for usage in self.por_modelo.values():
            total = total + usage
        return total

    def costo_usd(self, models: ModelsConfig) -> float:
        return sum(
            estimate_cost_usd(models, model, usage, batch=batch)
            for (model, batch), usage in self.por_modelo.items()
        )

    def to_dict(self, models: ModelsConfig | None = None) -> dict[str, Any]:
        """El uso acumulado, por modelo y en total, como va en la metadata del resultado."""
        datos: dict[str, Any] = {
            "n_llamadas": self.n_llamadas,
            "total": self.total().to_dict(),
            "por_modelo": [
                {"model": model, "batch": batch, **usage.to_dict()}
                for (model, batch), usage in sorted(self.por_modelo.items())
            ],
        }
        if models is not None:
            datos["costo_usd_estimado"] = round(self.costo_usd(models), 6)
        return datos


def cargar_credenciales() -> bool:
    """Carga `.env` desde la raíz del repositorio. Devuelve si el archivo existía.

    Se hace aquí y no en cada script porque este wrapper es el único punto del proyecto
    que construye un cliente de la API. `load_dotenv()` sin argumentos resuelve la ruta a
    partir del archivo que la llama, así que un script en `data/generators/` no
    encontraría el `.env` de la raíz: el fallo aparece recién en la primera llamada, con
    un error de autenticación que parece un problema de credenciales y no de rutas.
    """
    archivo = paths.root / ".env"
    if archivo.is_file():
        load_dotenv(archivo)
        return True
    return False


def is_retryable(exc: BaseException) -> bool:
    """¿Conviene reintentar esta excepción?

    Reintentables: límite de tasa, errores de conexión y de tiempo de espera, y errores
    del servidor (5xx). No reintentables: 4xx distintos de 429 (petición inválida,
    autenticación, modelo inexistente), porque reintentar solo repite el fallo.
    """
    if isinstance(exc, anthropic.RateLimitError):
        return True
    if isinstance(exc, anthropic.APIConnectionError):  # incluye APITimeoutError
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code >= 500
    return False


# El SDK `anthropic` 1.4.0 eliminó `temperature`, `top_p` y `top_k` de las firmas tipadas
# de `messages.create` y `messages.stream`. La API sí los sigue aceptando en Sonnet 4.6 y
# Haiku 4.5 (verificado contra la API real), así que viajan por `extra_body`, que inyecta
# campos al cuerpo JSON de la petición. Esto conserva intacta la decisión cerrada de una
# temperatura por rol: lo que cambia es el transporte, no el diseño.
#
# En la Batch API no aplica: allí los parámetros son el cuerpo JSON de cada petición y
# `temperature` va en línea, como un campo más.
CAMPOS_VIA_EXTRA_BODY = ("temperature", "top_p", "top_k")


def dividir_extra_body(params: dict[str, Any]) -> dict[str, Any]:
    """Mueve a `extra_body` los campos que la firma tipada del SDK ya no acepta."""
    resultado = dict(params)
    extra = dict(resultado.pop("extra_body", {}) or {})
    for campo in CAMPOS_VIA_EXTRA_BODY:
        if campo in resultado:
            extra[campo] = resultado.pop(campo)
    if extra:
        resultado["extra_body"] = extra
    return resultado


class AnthropicClient:
    """Cliente único del framework. Todos los módulos llaman a la API a través de aquí."""

    def __init__(
        self,
        models: ModelsConfig | None = None,
        *,
        raw_client: Any | None = None,
        api_key: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.models = models or load_models()
        defaults = self.models.defaults
        self._sleep = sleep
        self._rng = rng or random.Random(0)
        self.max_retries = defaults.max_retries
        self.backoff_base_s = defaults.backoff_base_s
        self.backoff_max_s = defaults.backoff_max_s
        self.ledger = UsageLedger()
        # Una fila por llamada: rol, modelo, request-id, marca de tiempo, modo de API,
        # TTFT y latencia. E3 la necesita para desglosar el TTFT por llamada interna, y el
        # request-id es lo único que permite volver a una petición concreta.
        self.registro: list[dict[str, Any]] = []

        if raw_client is not None:
            self.raw = raw_client
        else:
            cargar_credenciales()
            kwargs: dict[str, Any] = {"max_retries": 0, "timeout": defaults.timeout_s}
            if api_key is not None:
                kwargs["api_key"] = api_key
            # Sin api_key explícita, el SDK resuelve credenciales del entorno
            # (ANTHROPIC_API_KEY o un perfil de `ant auth login`).
            self.raw = anthropic.Anthropic(**kwargs)

    # ------------------------------------------------------------------ prompts

    @staticmethod
    def build_system(
        system_text: str,
        catalog_text: str | None = None,
        *,
        cache: bool = True,
    ) -> list[dict[str, Any]]:
        """System prompt como lista de bloques, con `cache_control` opcional.

        El orden es estable a propósito (prompt de rol, luego catálogo): la caché es un
        acierto por prefijo y cualquier cambio de bytes anterior la invalida. El contenido
        variable de cada caso va en `messages`, nunca aquí.
        """
        bloques: list[dict[str, Any]] = [{"type": "text", "text": system_text}]
        if catalog_text:
            bloques.append({"type": "text", "text": catalog_text})
        if cache:
            for bloque in bloques:
                bloque["cache_control"] = dict(_EPHEMERAL)
        return bloques

    def build_params(
        self,
        role: str,
        messages: Sequence[dict[str, Any]],
        *,
        system: str | list[dict[str, Any]] | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        stop_sequences: Sequence[str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Parámetros de `messages.create` para un rol, sin enviarlos."""
        cfg: ModelRole = self.models.role(role)
        params: dict[str, Any] = {
            "model": cfg.id,
            "max_tokens": max_tokens if max_tokens is not None else cfg.max_tokens,
            "temperature": temperature if temperature is not None else cfg.temperature,
            "messages": list(messages),
        }
        if system is not None:
            params["system"] = system
        if tools:
            params["tools"] = list(tools)
        if tool_choice:
            params["tool_choice"] = tool_choice
        if stop_sequences:
            params["stop_sequences"] = list(stop_sequences)
        if cfg.thinking:
            # El pensamiento extendido está desactivado en todos los roles (models.yaml).
            # Si alguna vez se activa, `temperature` deja de ser configurable.
            params["thinking"] = cfg.thinking
            params.pop("temperature", None)
        if extra:
            params.update(extra)
        return params

    # ------------------------------------------------------------- tiempo real

    def create(
        self,
        role: str,
        messages: Sequence[dict[str, Any]],
        **kwargs: Any,
    ) -> CallResult:
        """Llamada en tiempo real sin streaming. `ttft_s` queda en `None`."""
        params = self.build_params(role, messages, **kwargs)
        envio = dividir_extra_body(params)
        inicio = time.perf_counter()
        mensaje, intentos = self._con_reintentos(lambda: self.raw.messages.create(**envio))
        latencia = time.perf_counter() - inicio
        return self._to_result(
            role=role,
            mensaje=mensaje,
            params=params,
            latency_s=latencia,
            ttft_s=None,
            streamed=False,
            n_intentos=intentos,
        )

    def stream(
        self,
        role: str,
        messages: Sequence[dict[str, Any]],
        **kwargs: Any,
    ) -> CallResult:
        """Llamada en tiempo real con streaming y medición de TTFT.

        `ttft_s` es el tiempo transcurrido hasta el primer `content_block_delta`, es decir
        el primer token de contenido devuelto. Es la medida que consume E3, que además
        exige `cache=False` en el system prompt (sin prompt caching).
        """
        params = self.build_params(role, messages, **kwargs)
        envio = dividir_extra_body(params)

        def _ejecutar() -> tuple[Any, float | None, float | None, float, str | None]:
            inicio = time.perf_counter()
            ttft: float | None = None
            ttft_texto: float | None = None
            with self.raw.messages.stream(**envio) as stream:
                for evento in stream:
                    if getattr(evento, "type", None) != "content_block_delta":
                        continue
                    if ttft is None:
                        ttft = time.perf_counter() - inicio
                    delta = getattr(evento, "delta", None)
                    if ttft_texto is None and getattr(delta, "type", None) == "text_delta":
                        ttft_texto = time.perf_counter() - inicio
                mensaje = stream.get_final_message()
                # El mensaje acumulado del stream no trae `_request_id`; el id vive en el
                # objeto del stream. Sin esto, E3 —que solo usa streaming— registraría
                # `null` en todas sus peticiones y no habría forma de volver a ninguna.
                request_id = getattr(stream, "request_id", None)
            return mensaje, ttft, ttft_texto, time.perf_counter() - inicio, request_id

        (mensaje, ttft, ttft_texto, latencia, request_id), intentos = self._con_reintentos(
            _ejecutar
        )
        return self._to_result(
            role=role,
            mensaje=mensaje,
            params=params,
            latency_s=latencia,
            ttft_s=ttft,
            ttft_texto_s=ttft_texto,
            streamed=True,
            n_intentos=intentos,
            request_id=request_id,
        )

    def count_tokens(
        self,
        role: str,
        messages: Sequence[dict[str, Any]],
        **kwargs: Any,
    ) -> int:
        """Conteo exacto de tokens de entrada con el endpoint del SDK (consume red)."""
        params = self.build_params(role, messages, **kwargs)
        payload = {
            clave: params[clave]
            for clave in ("model", "messages", "system", "tools")
            if clave in params
        }
        respuesta, _ = self._con_reintentos(lambda: self.raw.messages.count_tokens(**payload))
        return int(respuesta.input_tokens)

    # ------------------------------------------------------------------ lotes

    def build_batch_request(
        self,
        custom_id: str,
        role: str,
        messages: Sequence[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Una petición del lote. `custom_id` es la única forma fiable de emparejar
        resultados: la Batch API los devuelve en cualquier orden."""
        return {"custom_id": custom_id, "params": self.build_params(role, messages, **kwargs)}

    def submit_batch(self, requests: Sequence[dict[str, Any]]) -> str:
        """Envía el lote y devuelve su id."""
        if not requests:
            raise ValueError("no se puede enviar un lote vacío")
        ids = [peticion["custom_id"] for peticion in requests]
        if len(set(ids)) != len(ids):
            raise ValueError("los custom_id de un lote deben ser únicos")
        lote, _ = self._con_reintentos(
            lambda: self.raw.messages.batches.create(requests=list(requests))
        )
        return lote.id

    def batch_status(self, batch_id: str) -> str:
        lote, _ = self._con_reintentos(lambda: self.raw.messages.batches.retrieve(batch_id))
        return lote.processing_status

    def wait_for_batch(
        self,
        batch_id: str,
        *,
        poll_interval_s: float = 30.0,
        timeout_s: float = 24 * 3600,
    ) -> str:
        """Espera a que el lote termine. Devuelve el estado final."""
        limite = time.monotonic() + timeout_s
        while True:
            estado = self.batch_status(batch_id)
            if estado == _BATCH_ENDED:
                return estado
            if time.monotonic() >= limite:
                raise TimeoutError(
                    f"el lote {batch_id} sigue en estado {estado!r} tras {timeout_s:.0f} s"
                )
            self._sleep(poll_interval_s)

    def collect_batch(
        self, batch_id: str, *, roles: dict[str, str] | None = None
    ) -> dict[str, BatchOutcome]:
        """Recoge los resultados de un lote terminado, indexados por `custom_id`.

        `roles` permite recuperar el rol con el que se construyó cada petición; si no se
        entrega, el rol queda como `"batch"`.
        """
        resultados: dict[str, BatchOutcome] = {}
        for entrada in self.raw.messages.batches.results(batch_id):
            custom_id = entrada.custom_id
            tipo = entrada.result.type
            if tipo == "succeeded":
                mensaje = entrada.result.message
                resultado = self._to_result(
                    role=(roles or {}).get(custom_id, "batch"),
                    mensaje=mensaje,
                    params=None,
                    latency_s=None,
                    ttft_s=None,
                    streamed=False,
                    batch=True,
                    custom_id=custom_id,
                )
                resultados[custom_id] = BatchOutcome(custom_id, "succeeded", result=resultado)
            else:
                error = getattr(entrada.result, "error", None)
                resultados[custom_id] = BatchOutcome(
                    custom_id,
                    tipo,
                    error=_a_dict(error) if error is not None else None,
                )
        return resultados

    def run_batch(
        self,
        requests: Sequence[dict[str, Any]],
        *,
        poll_interval_s: float = 30.0,
        timeout_s: float = 24 * 3600,
        roles: dict[str, str] | None = None,
    ) -> dict[str, BatchOutcome]:
        """Envía, espera y recoge un lote completo."""
        batch_id = self.submit_batch(requests)
        self.wait_for_batch(batch_id, poll_interval_s=poll_interval_s, timeout_s=timeout_s)
        return self.collect_batch(batch_id, roles=roles)

    # ------------------------------------------------------------------ interno

    def _con_reintentos(self, fn: Callable[[], Any]) -> tuple[Any, int]:
        """Ejecuta `fn` con backoff exponencial y jitter. Devuelve (valor, nº intentos)."""
        ultimo: BaseException | None = None
        for intento in range(self.max_retries + 1):
            try:
                return fn(), intento + 1
            except Exception as exc:  # noqa: BLE001 - se reclasifica en is_retryable
                if not is_retryable(exc) or intento == self.max_retries:
                    raise
                ultimo = exc
                self._sleep(self._espera_backoff(intento))
        raise ultimo  # pragma: no cover - inalcanzable

    def _espera_backoff(self, intento: int) -> float:
        """Backoff exponencial con *equal jitter*: `d/2 + U(0, d/2)`, con `d` acotado.

        El jitter es proporcional al retardo, no un sumando fijo: así la espera crece de
        verdad entre intentos y varias ejecuciones concurrentes no reintentan a la vez.
        """
        retardo = min(self.backoff_base_s * (2**intento), self.backoff_max_s)
        return retardo / 2 + self._rng.uniform(0, retardo / 2)

    def _to_result(
        self,
        *,
        role: str,
        mensaje: Any,
        params: dict[str, Any] | None,
        latency_s: float | None,
        ttft_s: float | None,
        streamed: bool,
        ttft_texto_s: float | None = None,
        batch: bool = False,
        custom_id: str | None = None,
        n_intentos: int = 1,
        request_id: str | None = None,
    ) -> CallResult:
        contenido = [_a_dict(bloque) for bloque in (mensaje.content or [])]
        texto = "".join(
            bloque.get("text", "") for bloque in contenido if bloque.get("type") == "text"
        )
        usage = Usage.from_sdk(mensaje.usage)
        modelo = getattr(mensaje, "model", None) or (params or {}).get("model", "desconocido")
        self.ledger.add(modelo, usage, batch=batch)
        resultado = CallResult(
            role=role,
            model=modelo,
            text=texto,
            content=contenido,
            stop_reason=getattr(mensaje, "stop_reason", None),
            usage=usage,
            latency_s=latency_s,
            ttft_s=ttft_s,
            ttft_texto_s=ttft_texto_s,
            timestamp=datetime.now(UTC).isoformat(timespec="milliseconds"),
            api_mode="batch" if batch else "realtime",
            request_id=request_id or getattr(mensaje, "_request_id", None),
            custom_id=custom_id,
            batch=batch,
            streamed=streamed,
            cache_enabled=_usa_cache(params),
            n_intentos=n_intentos,
        )
        self.registro.append(resultado.resumen_llamada())
        return resultado

    def usage_summary(self) -> dict[str, Any]:
        """Contabilidad acumulada de la sesión, para escribir en `results/*.json`."""
        return self.ledger.to_dict(self.models)


# Campos que la API acepta al reenviar un bloque del asistente. El SDK añade otros al
# acumular un stream (`parsed_output`, `caller`, `toolset_name`) y devolverlos provoca un
# 400 «Extra inputs are not permitted». Se reenvía solo lo que la API espera recibir.
CAMPOS_REENVIO: dict[str, tuple[str, ...]] = {
    "text": ("type", "text"),
    "tool_use": ("type", "id", "name", "input"),
    "thinking": ("type", "thinking", "signature"),
    "redacted_thinking": ("type", "data"),
}


def bloques_para_reenvio(contenido: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deja cada bloque del asistente con los campos que la API acepta de vuelta.

    Reenviar el turno del asistente tal como llegó es lo natural, pero el objeto acumulado
    trae campos que solo tienen sentido de bajada. El fallo únicamente aparece con
    streaming, que es la ruta de E3.
    """
    limpios: list[dict[str, Any]] = []
    for bloque in contenido:
        permitidos = CAMPOS_REENVIO.get(bloque.get("type", ""))
        if permitidos is None:
            limpios.append(bloque)
            continue
        limpios.append({k: v for k, v in bloque.items() if k in permitidos and v is not None})
    return limpios


def _usa_cache(params: dict[str, Any] | None) -> bool:
    """¿La petición llevaba algún `cache_control`?"""
    if not params:
        return False
    if "cache_control" in params:
        return True
    system = params.get("system")
    bloques: Iterable[Any] = system if isinstance(system, list) else []
    return any(isinstance(bloque, dict) and "cache_control" in bloque for bloque in bloques)


def _a_dict(objeto: Any) -> dict[str, Any]:
    """Normaliza un objeto del SDK (pydantic) o un dict a dict plano."""
    if isinstance(objeto, dict):
        return objeto
    for metodo in ("model_dump", "to_dict", "dict"):
        fn = getattr(objeto, metodo, None)
        if callable(fn):
            try:
                return fn()
            except TypeError:  # pragma: no cover - firmas inesperadas
                continue
    return {"repr": repr(objeto)}


__all__ = [
    "CAMPOS_REENVIO",
    "CAMPOS_VIA_EXTRA_BODY",
    "bloques_para_reenvio",
    "cargar_credenciales",
    "AnthropicClient",
    "BatchOutcome",
    "CallResult",
    "UsageLedger",
    "dividir_extra_body",
    "is_retryable",
]
