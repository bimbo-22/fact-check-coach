"""In-memory TTL stores. Keys are hashes; no post text, usernames or chat IDs are ever stored."""
import hashlib
import time
from typing import Any, Callable

from app.quote_verifier import normalise


def text_hash(text: str) -> str:
    return hashlib.sha256(normalise(text).encode()).hexdigest()


class TTLCache:
    def __init__(self, ttl_seconds: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl = ttl_seconds
        self.clock = clock
        self._data: dict[str, tuple[float, Any]] = {}
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item and self.clock() - item[0] < self.ttl:
            self.hits += 1
            return item[1]
        self._data.pop(key, None)
        self.misses += 1
        return None

    def set(self, key: str, value: Any) -> None:
        self._data[key] = (self.clock(), value)

    def values(self) -> list[Any]:
        return [v for _, v in self._data.values()]

    def keys(self) -> list[str]:
        return list(self._data)


class CheckStore:
    """check_id → pending reveal. Expired IDs are remembered for a while so we can answer 410, not 404."""

    def __init__(self, ttl_seconds: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl = ttl_seconds
        self.clock = clock
        self._live: dict[str, tuple[float, Any]] = {}
        self._expired: dict[str, float] = {}

    def put(self, check_id: str, value: Any) -> None:
        self._purge()
        self._live[check_id] = (self.clock(), value)

    def get(self, check_id: str) -> tuple[str, Any | None]:
        """Return ("ok", value), ("expired", None) or ("missing", None)."""
        self._purge()
        if check_id in self._live:
            return "ok", self._live[check_id][1]
        if check_id in self._expired:
            return "expired", None
        return "missing", None

    def _purge(self) -> None:
        now = self.clock()
        for cid, (created, _) in list(self._live.items()):
            if now - created >= self.ttl:
                del self._live[cid]
                self._expired[cid] = now
        for cid, when in list(self._expired.items()):
            if now - when >= 4 * self.ttl:
                del self._expired[cid]
