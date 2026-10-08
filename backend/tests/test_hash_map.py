import pytest

from app.data_structures.hash_map import HashMap


def test_put_and_get_values() -> None:
    items: HashMap[str, int] = HashMap()

    items.put("apple", 3)

    assert items.get("apple") == 3


def test_put_replaces_an_existing_value_without_changing_length() -> None:
    items: HashMap[str, int] = HashMap()
    items.put("apple", 3)

    items.put("apple", 5)

    assert items.get("apple") == 5
    assert len(items) == 1


def test_get_returns_default_for_a_missing_key() -> None:
    items: HashMap[str, int] = HashMap()

    assert items.get("missing") is None
    assert items.get("missing", 10) == 10


def test_remove_returns_value_and_decreases_length() -> None:
    items: HashMap[str, int] = HashMap()
    items.put("apple", 3)

    removed = items.remove("apple")

    assert removed == 3
    assert len(items) == 0
    assert "apple" not in items


def test_remove_raises_key_error_for_a_missing_key() -> None:
    items: HashMap[str, int] = HashMap()

    with pytest.raises(KeyError):
        items.remove("missing")


def test_membership_checks_whether_key_exists() -> None:
    items: HashMap[str, int] = HashMap()
    items.put("apple", 3)

    assert "apple" in items
    assert "missing" not in items


def test_collisions_keep_keys_accessible() -> None:
    class CollidingKey:
        def __init__(self, value: str) -> None:
            self.value = value

        def __hash__(self) -> int:
            return 1

        def __eq__(self, other: object) -> bool:
            return isinstance(other, CollidingKey) and self.value == other.value

    items: HashMap[CollidingKey, str] = HashMap()
    first = CollidingKey("first")
    second = CollidingKey("second")

    items.put(first, "one")
    items.put(second, "two")

    assert items.get(first) == "one"
    assert items.get(second) == "two"
    assert len(items) == 2


def test_map_resizes_and_keeps_values_accessible() -> None:
    items: HashMap[int, str] = HashMap()

    for key in range(50):
        items.put(key, f"value-{key}")

    assert len(items) == 50
    for key in range(50):
        assert items.get(key) == f"value-{key}"
