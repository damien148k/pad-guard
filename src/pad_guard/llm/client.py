"""Local language model behind one small interface (CLAUDE.md: Ollama only, nothing leaves the machine).

:class:`LLMClient` is what the rest of the tool uses: one prompt in, one JSON document out,
constrained by a JSON schema, with optional page images. :class:`OllamaClient` is the only
implementation. Tests use a fake client; nothing in the test suite talks to Ollama.

Context size: Ollama loads a model with 4096 tokens of context unless ``num_ctx`` is given, and a
draft-profile request is 4000 to 9200 tokens, plus the answer (up to 8000 tokens measured). The
caller sets ``num_ctx`` once for a whole run (changing it reloads the model, and changes the
output). Ollama 0.40 refuses a prompt longer than the context instead of truncating it; that
refusal, an answer cut at the end of the context and a generation stopped for repetition all
become a clear :class:`LLMError`.
"""

from __future__ import annotations

import hashlib
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

# The one default model of draft-profile and of the report synthesis, CLI and interface (decision of
# Damien, 24/10/2026: the 32B is too slow on the RTX 3080 Ti, kept for occasional acceptance runs).
DEFAULT_MODEL = "qwen3-vl:8b-instruct"
SEED = 1234  # fixed: same pages, same model, same context, same answer
DEFAULT_TIMEOUT = 600.0  # seconds per request
# Default repeat_penalty of draft-profile. None: not sent, Ollama applies 1.0 (no penalty).
REPEAT_PENALTY: float | None = None

_TOO_LONG = re.compile(r"request \((\d+) tokens\) exceeds the available context size \((\d+) tokens\)")


def request_fingerprint(system: str, prompt: str, images: tuple[bytes, ...], schema: dict) -> str:
    """SHA-256 of everything the model is given for one request: two requests with the same
    fingerprint differ only by the model or its settings."""
    h = hashlib.sha256()
    for part in (system, prompt, json.dumps(schema, sort_keys=True, ensure_ascii=False),
                 *(hashlib.sha256(image).hexdigest() for image in images)):
        h.update(part.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


class LLMError(Exception):
    """The model could not answer. The message is user-facing (French)."""


@dataclass(frozen=True)
class LLMRequest:
    prompt: str
    schema: dict
    system: str | None = None
    images: tuple[bytes, ...] = ()  # PNG files
    timeout: float = DEFAULT_TIMEOUT


@dataclass(frozen=True)
class Usage:
    """Tokens of the last answer, as counted by the engine."""

    prompt_tokens: int | None
    output_tokens: int | None
    num_ctx: int | None


class LLMClient(ABC):
    """A local model that answers with JSON text matching ``request.schema``."""

    model: str
    num_ctx: int | None = None  # context size in tokens; None: the caller chooses it before the first request

    @abstractmethod
    def generate(self, request: LLMRequest) -> str:
        """Raw JSON text of the answer. Raises LLMError (unreachable, unknown model, context, timeout)."""

    def usage(self) -> Usage | None:
        """Tokens of the last answer, when the engine gives them."""
        return None

    def settings(self) -> dict:
        """Generation settings sent to the engine (recorded with every answer)."""
        return {}

    def release(self) -> None:
        """Free the model from memory (GPU) when the work is done. Never raises."""


class OllamaClient(LLMClient):
    def __init__(self, model: str = DEFAULT_MODEL, host: str | None = None, num_ctx: int | None = None,
                 seed: int = SEED, repeat_penalty: float | None = None):
        self.model = model
        self.host = host
        self.num_ctx = num_ctx
        self.seed = seed
        # None: not sent, Ollama applies 1.0 (no penalty: measured, whatever its documentation says).
        self.repeat_penalty = repeat_penalty
        self._usage: Usage | None = None

    def settings(self) -> dict:
        options = {"temperature": 0, "seed": self.seed, "num_ctx": self.num_ctx}
        if self.repeat_penalty is not None:
            options["repeat_penalty"] = self.repeat_penalty
        return options

    def generate(self, request: LLMRequest) -> str:
        import httpx
        import ollama

        if self.num_ctx is None:
            raise LLMError("taille de contexte (num_ctx) non fixée : sans elle, Ollama tronquerait à 4096 jetons")
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        user = {"role": "user", "content": request.prompt}
        if request.images:
            user["images"] = list(request.images)
        messages.append(user)
        client = ollama.Client(host=self.host, timeout=request.timeout)
        try:
            response = client.chat(model=self.model, messages=messages, format=request.schema,
                                   options=self.settings())
        except ollama.ResponseError as exc:
            raise LLMError(self._refusal(exc.status_code, str(exc.error))) from None
        except httpx.TimeoutException:
            raise LLMError(timeout_message(self.model, request.timeout)) from None
        except (httpx.HTTPError, ConnectionError) as exc:
            raise LLMError(f"Ollama injoignable ({exc.__class__.__name__}) : lancer l'application Ollama") from None
        self._usage = Usage(response.prompt_eval_count, response.eval_count, self.num_ctx)
        if response.done_reason == "length":
            raise LLMError(f"réponse coupée à la fin du contexte ({response.prompt_eval_count} jetons de demande + "
                           f"{response.eval_count} de réponse = {self.num_ctx}) : relancer avec "
                           f"--num-ctx {_round_up(self.num_ctx * 3 // 2)}")
        return response.message.content or ""

    def _refusal(self, status: int, error: str) -> str:
        if status == 404:
            return f"modèle « {self.model} » absent d'Ollama : lancer « ollama pull {self.model} »"
        m = _TOO_LONG.search(error)
        if m:
            return (f"demande de {m[1]} jetons, plus que le contexte de {m[2]} jetons : Ollama la refuse plutôt que "
                    f"de la tronquer. Relancer avec --num-ctx {_round_up(int(m[1]) + 10240)}")
        if "repeat limit" in error:
            return (f"le modèle {self.model} répète la même sortie en boucle : Ollama a interrompu la génération "
                    f"({error})")
        return f"Ollama a refusé la requête ({status}) : {error}"

    def usage(self) -> Usage | None:
        return self._usage

    def release(self) -> None:
        import ollama

        try:
            ollama.Client(host=self.host, timeout=30).generate(model=self.model, prompt="", keep_alive=0)
        except Exception:  # noqa: BLE001 - freeing memory is best effort, the work is done
            pass

    def installed(self) -> list[str]:
        """Names of the models installed in Ollama."""
        import ollama

        try:
            return sorted(m.model for m in ollama.Client(host=self.host, timeout=10).list().models)
        except Exception as exc:  # noqa: BLE001 - any failure means Ollama cannot be used
            raise LLMError(f"Ollama injoignable ({exc.__class__.__name__}) : lancer l'application Ollama") from None


def pick_model(model: str | None, installed: list[str]) -> str:
    """The model to use: the one asked for, else DEFAULT_MODEL, if Ollama has it."""
    model = model or DEFAULT_MODEL
    if model not in installed:
        raise LLMError(f"modèle absent d'Ollama : {model} (lancer « ollama pull {model} »)")
    return model


def timeout_message(model: str, timeout: float) -> str:
    """What the user reads when a request outlives its timeout, and what to do about it."""
    text = f"Ollama n'a pas répondu en {timeout:g} s (modèle {model}) : modèle trop lent sur cette machine"
    if model != DEFAULT_MODEL:
        return f"{text}, choisir {DEFAULT_MODEL}"
    return f"{text} : fermer les programmes qui occupent la carte graphique (DaVinci Resolve…) et relancer"


def _round_up(tokens: int, step: int = 1024) -> int:
    return -(-tokens // step) * step
