from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """LLM call failed; message is safe to show to the user."""


class LLMProvider(Protocol):
    async def parse(self, *, system: str, user: str, schema: type[T]) -> T: ...
