import logging

import openai
from openai import AsyncOpenAI

from app.config import Settings
from app.llm.base import LLMError, T

log = logging.getLogger(__name__)


class OpenAIProvider:
    """Swap `AsyncOpenAI` for `AsyncAzureOpenAI` here when moving to Azure OpenAI."""

    def __init__(self, settings: Settings, model: str | None = None) -> None:
        self._model = model or settings.openai_model
        self._temperature = settings.openai_temperature
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            base_url=settings.openai_base_url,
            max_retries=3,
            timeout=120,
        )

    async def parse(self, *, system: str, user: str, schema: type[T]) -> T:
        kwargs = {} if self._temperature is None else {"temperature": self._temperature}
        try:
            completion = await self._client.chat.completions.parse(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format=schema,
                **kwargs,
            )
        except openai.AuthenticationError as exc:
            raise LLMError("OpenAI rejected the API key.") from exc
        except openai.RateLimitError as exc:
            raise LLMError("OpenAI rate limit or quota exceeded.") from exc
        except openai.OpenAIError as exc:
            log.warning("OpenAI call failed: %s", type(exc).__name__)
            raise LLMError(f"OpenAI request failed ({type(exc).__name__}).") from exc

        message = completion.choices[0].message
        if message.parsed is None:
            raise LLMError(message.refusal or "The model returned an empty response.")
        return message.parsed
