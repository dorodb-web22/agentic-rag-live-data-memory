from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class HashMap(Generic[K, V]):
    """A small hash map that resolves collisions with buckets."""

    _INITIAL_CAPACITY = 8
    _MAX_LOAD_FACTOR = 0.75

    def __init__(self) -> None:
        self._buckets: list[list[tuple[K, V]]] = [
            [] for _ in range(self._INITIAL_CAPACITY)
        ]
        self._size = 0

    def put(self, key: K, value: V) -> None:
        bucket = self._get_bucket(key)
        for index, (existing_key, _) in enumerate(bucket):
            if existing_key == key:
                bucket[index] = (key, value)
                return

        bucket.append((key, value))
        self._size += 1
        if self._size / len(self._buckets) > self._MAX_LOAD_FACTOR:
            self._resize()

    def get(self, key: K, default: V | None = None) -> V | None:
        bucket = self._get_bucket(key)
        for existing_key, value in bucket:
            if existing_key == key:
                return value
        return default

    def remove(self, key: K) -> V:
        bucket = self._get_bucket(key)
        for index, (existing_key, value) in enumerate(bucket):
            if existing_key == key:
                del bucket[index]
                self._size -= 1
                return value
        raise KeyError(key)

    def __contains__(self, key: object) -> bool:
        bucket = self._get_bucket(key)
        return any(existing_key == key for existing_key, _ in bucket)

    def __len__(self) -> int:
        return self._size

    def _get_bucket(self, key: object) -> list[tuple[K, V]]:
        index = hash(key) % len(self._buckets)
        return self._buckets[index]

    def _resize(self) -> None:
        old_buckets = self._buckets
        self._buckets = [[] for _ in range(len(old_buckets) * 2)]
        for bucket in old_buckets:
            for key, value in bucket:
                self._get_bucket(key).append((key, value))
