"""Collection processing utilities."""
from collections import defaultdict
from typing import Any
from typing import Callable
from typing import Iterable
from typing import TypeVar

T = TypeVar("T")


def deduplicate(items: list[T]) -> list[T]:
    """Remove duplicates preserving insertion order."""
    seen: set = set()
    result: list[T] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def merge_dicts(base: dict, override: dict) -> dict:
    """Shallow merge: override wins on key conflict."""
    return {**base, **override}


def paginate(items: list[T], page: int, page_size: int = 10) -> list[T]:
    """Return a page of items. Pages are 1-indexed. Invalid pages return []."""
    if page < 1 or page_size < 1:
        return []
    start = (page - 1) * page_size
    end = start + page_size
    return items[start:end]


def group_by(items: Iterable[T], key_fn: Callable[[T], Any]) -> dict[Any, list[T]]:
    """Group items by the result of key_fn."""
    groups: dict[Any, list[T]] = defaultdict(list)
    for item in items:
        groups[key_fn(item)].append(item)
    return dict(groups)


def flatten(nested: Iterable) -> list:
    """Recursively flatten nested iterables (except strings)."""
    result: list = []
    for item in nested:
        if isinstance(item, Iterable) and not isinstance(item, str):
            result.extend(flatten(item))
        else:
            result.append(item)
    return result


def take_while(predicate: Callable[[T], bool], items: Iterable[T]) -> list[T]:
    """Return leading items while predicate is true. Stop at first false."""
    result: list[T] = []
    for item in items:
        if not predicate(item):
            break
        result.append(item)
    return result
