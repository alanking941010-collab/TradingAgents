import os
from typing import Any, Optional

from langchain_anthropic import ChatAnthropic

from .base_client import BaseLLMClient, normalize_content
from .validators import validate_model

KIMI_CODING_BASE_URL = "https://api.kimi.com/coding"
KIMI_CODING_USER_AGENT = "claude-code/0.1.0"

_PASSTHROUGH_KWARGS = (
    "timeout", "max_retries", "api_key", "max_tokens",
    "callbacks", "http_client", "http_async_client", "effort",
)


class NormalizedKimiCodingChatAnthropic(ChatAnthropic):
    """ChatAnthropic transport for Kimi Coding Plan with normalized text output."""

    def invoke(self, input, config=None, **kwargs):
        return normalize_content(super().invoke(input, config, **kwargs))


class KimiCodingClient(BaseLLMClient):
    """Client for Kimi Coding Plan's Anthropic Messages endpoint.

    Kimi Coding Plan keys (``sk-kimi-...``) do not authenticate against the
    Moonshot OpenAI-compatible endpoint. They should use
    ``https://api.kimi.com/coding`` and the Anthropic Messages wire protocol.
    """

    provider = "kimi-coding"

    def __init__(self, model: str, base_url: Optional[str] = None, **kwargs):
        super().__init__(model, base_url, **kwargs)

    def get_llm(self) -> Any:
        """Return configured ChatAnthropic-compatible Kimi Coding instance."""
        self.warn_if_unknown_model()
        llm_kwargs = {
            "model": self.model,
            "base_url": self.base_url or KIMI_CODING_BASE_URL,
            "default_headers": {"User-Agent": KIMI_CODING_USER_AGENT},
        }

        api_key = self.kwargs.get("api_key") or os.environ.get("KIMI_API_KEY")
        if api_key:
            llm_kwargs["api_key"] = api_key

        for key in _PASSTHROUGH_KWARGS:
            if key in self.kwargs and key not in llm_kwargs:
                llm_kwargs[key] = self.kwargs[key]

        return NormalizedKimiCodingChatAnthropic(**llm_kwargs)

    def validate_model(self) -> bool:
        """Validate Kimi Coding Plan model name."""
        return validate_model(self.provider, self.model)
