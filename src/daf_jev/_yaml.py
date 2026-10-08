"""Safe, unambiguous literal configuration for frozen experiments."""
from __future__ import annotations

import math
from typing import Any

import yaml


class _StrictSafeLoader(yaml.SafeLoader):
    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(yaml.events.AliasEvent):
            raise ValueError("YAML aliases are unsupported in frozen configuration")
        return super().compose_node(parent, index)

    def construct_mapping(self, node: Any, deep: bool = False) -> dict[Any, Any]:
        self.flatten_mapping(node)
        keys: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                if key in keys:
                    raise ValueError("duplicate YAML mapping key")
                keys.add(key)
            except TypeError as exc:
                raise ValueError("unhashable YAML mapping key") from exc
        return super().construct_mapping(node, deep=deep)


def _finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite YAML number")
    if isinstance(value, dict):
        for key, item in value.items():
            _finite(key)
            _finite(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            _finite(item)


def strict_yaml_loads(value: str | bytes) -> Any:
    """Reject duplicate/merged keys, aliases, unsafe tags and nonfinite numbers.

    Loader registration is private; global PyYAML behavior is unchanged. Keys
    or values from malformed configuration never appear in our error text.
    """
    loader = _StrictSafeLoader(value)
    try:
        result = loader.get_single_data()
        _finite(result)
        return result
    except (yaml.YAMLError, RecursionError) as exc:
        raise ValueError("invalid literal YAML configuration") from exc
    finally:
        loader.dispose()
