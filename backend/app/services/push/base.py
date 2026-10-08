"""Push provider abstraction: add new platforms by implementing this interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class PushResult:
    ok: bool
    response: str | None = None
    error: str | None = None


class PushProvider(ABC):
    kind: str = ""
    label: str = ""

    @abstractmethod
    async def send(self, *, digest: dict[str, Any], config: dict[str, Any]) -> PushResult:
        """Deliver a digest. `digest` keys: id, title, lead, content_md, highlights,
        tags, source, author."""


class PushError(RuntimeError):
    pass
