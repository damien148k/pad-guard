"""Local language model behind one small interface (CLAUDE.md: Ollama only, nothing leaves the machine).

:class:`LLMClient` is what the rest of the tool uses: one prompt in, one JSON document out,
constrained by a JSON schema, with optional page images. :class:`OllamaClient` is the only
implementation. Tests use a fake client; nothing in the test suite talks to Ollama.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

DEFAULT_MODEL = "qwen3-vl:32b-instruct"
FALLBACK_MODEL = "qwen3-vl:8b-instruct"
SEED = 1234  # fixed: same pages, same model, same answer
DEFAULT_TIMEOUT = 600.0  # seconds per request


class LLMError(Exception):
    """The model could not answer. The message is user-facing (French)."""


@dataclass(frozen=True)
class LLMRequest:
    prompt: str
    schema: dict
    system: str | None = None
    images: tuple[bytes, ...] = ()  # PNG files
    timeout: float = DEFAULT_TIMEOUT


class LLMClient(ABC):
    """A local model that answers with JSON text matching ``request.schema``."""

    model: str

    @abstractmethod
    def generate(self, request: LLMRequest) -> str:
        """Raw JSON text of the answer. Raises LLMError (unreachable, unknown model, timeout)."""


class OllamaClient(LLMClient):
    def __init__(self, model: str = DEFAULT_MODEL, host: str | None = None, num_ctx: int = 16384,
                 seed: int = SEED):
        self.model = model
        self.host = host
        self.num_ctx = num_ctx
        self.seed = seed

    def generate(self, request: LLMRequest) -> str:
        import httpx
        import ollama

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
                                   options={"temperature": 0, "seed": self.seed, "num_ctx": self.num_ctx})
        except ollama.ResponseError as exc:
            if exc.status_code == 404:
                raise LLMError(f"modèle « {self.model} » absent d'Ollama : lancer « ollama pull {self.model} »") from None
            raise LLMError(f"Ollama a refusé la requête ({exc.status_code}) : {exc.error}") from None
        except httpx.TimeoutException:
            raise LLMError(f"Ollama n'a pas répondu en {request.timeout:g} s (modèle {self.model})") from None
        except (httpx.HTTPError, ConnectionError) as exc:
            raise LLMError(f"Ollama injoignable ({exc.__class__.__name__}) : lancer l'application Ollama") from None
        return response.message.content or ""

    def installed(self) -> list[str]:
        """Names of the models installed in Ollama."""
        import ollama

        try:
            return sorted(m.model for m in ollama.Client(host=self.host, timeout=10).list().models)
        except Exception as exc:  # noqa: BLE001 - any failure means Ollama cannot be used
            raise LLMError(f"Ollama injoignable ({exc.__class__.__name__}) : lancer l'application Ollama") from None
