"""One interface for every LLM provider.

The LLM only ever does narrow reading tasks (extract a claim, label a source, rephrase
verified quotes). `task` lets the mock route deterministically; real providers ignore it.
"""
from abc import ABC, abstractmethod
from collections import Counter


class LLMError(Exception):
    pass


class LLMClient(ABC):
    name: str = "base"

    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()

    @property
    def total_calls(self) -> int:
        return sum(self.calls.values())

    async def complete(self, task: str, system: str, user: str) -> str:
        self.calls[task] += 1
        return await self._complete(task, system, user)

    @abstractmethod
    async def _complete(self, task: str, system: str, user: str) -> str: ...
