from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Generic, TypeVar


K = TypeVar("K")
V = TypeVar("V")


@dataclass(frozen=True)
class MemoryLruCacheSnapshot:
    max_bytes: int
    current_bytes: int
    peak_bytes: int
    item_count: int
    hit_count: int
    miss_count: int
    eviction_count: int


class MemorySizedLruCache(Generic[K, V]):
    """Non-thread-safe LRU cache with a byte-based capacity limit."""

    def __init__(self, *, max_bytes: int, sizeof: Callable[[V], int]) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self._max_bytes = int(max_bytes)
        self._sizeof = sizeof
        self._items: OrderedDict[K, V] = OrderedDict()
        self._item_bytes: dict[K, int] = {}
        self._current_bytes = 0
        self._peak_bytes = 0
        self._hit_count = 0
        self._miss_count = 0
        self._eviction_count = 0

    def snapshot(self) -> MemoryLruCacheSnapshot:
        return MemoryLruCacheSnapshot(
            max_bytes=self._max_bytes,
            current_bytes=self._current_bytes,
            peak_bytes=self._peak_bytes,
            item_count=len(self._items),
            hit_count=self._hit_count,
            miss_count=self._miss_count,
            eviction_count=self._eviction_count,
        )

    def get(self, key: K) -> V | None:
        value = self._items.get(key)
        if value is None:
            self._miss_count += 1
            return None
        self._items.move_to_end(key)
        self._hit_count += 1
        return value

    def put(self, key: K, value: V) -> bool:
        size = int(self._sizeof(value))
        if size < 0:
            raise ValueError("sizeof must return a non-negative integer")

        self.pop(key)
        if size > self._max_bytes:
            return False

        while self._items and self._current_bytes + size > self._max_bytes:
            self._evict_oldest()

        self._items[key] = value
        self._item_bytes[key] = size
        self._current_bytes += size
        self._peak_bytes = max(self._peak_bytes, self._current_bytes)
        return True

    def pop(self, key: K) -> V | None:
        value = self._items.pop(key, None)
        if value is None:
            return None
        self._current_bytes -= self._item_bytes.pop(key, 0)
        return value

    def keys(self) -> tuple[K, ...]:
        return tuple(self._items.keys())

    def clear(self) -> None:
        self._items.clear()
        self._item_bytes.clear()
        self._current_bytes = 0

    def _evict_oldest(self) -> None:
        oldest_key, _ = self._items.popitem(last=False)
        self._current_bytes -= self._item_bytes.pop(oldest_key, 0)
        self._eviction_count += 1
