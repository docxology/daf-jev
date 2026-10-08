"""Literal configuration cannot silently shadow frozen execution settings."""
from pathlib import Path

import pytest
import yaml

from daf_jev._yaml import strict_yaml_loads
from daf_jev.benchmark_runner import plan_run


@pytest.mark.parametrize("text", [
    'budget_usd: "100"\nbudget_usd: "25"\n',
    'options:\n  provider:\n    allow_fallbacks: true\n    allow_fallbacks: false\n',
    '"budget_usd": "100"\n"budget_\\u0075sd": "25"\n',
    'limits: {<<: {max_tokens: 20}, max_tokens: 512}',
    'self: &self {child: *self}', 'one: &one 1\ntwo: *one',
    'cost: .nan', 'cost: .inf', 'cost: -.inf', '.nan: cost',
    'nested: [0, {bad: .inf}]', '? [one, two]\n: unhashable',
    'x: !!set {.nan: null}', 'x: !!pairs [{a: .inf}]', 'x: !!omap [{a: .inf}]',
    'private: !!python/object/apply:os.system [echo forbidden]', 'broken: [',
])
def test_strict_yaml_rejects_ambiguous_unsafe_or_nonfinite(text: str) -> None:
    with pytest.raises(ValueError):
        strict_yaml_loads(text)


def test_strict_yaml_preserves_literal_types_order_and_global_loader() -> None:
    value = strict_yaml_loads(b'backends: [{id: local, options: {temperature: 0.0}}]\nbudget_usd: "25"')
    assert list(value) == ["backends", "budget_usd"]
    assert value["budget_usd"] == "25" and value["backends"][0]["options"]["temperature"] == 0.0
    assert strict_yaml_loads("") is None
    assert yaml.safe_load('x: 1\nx: 2') == {"x": 2}


def test_ambiguous_config_fails_before_plan_creation(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    raw = b'format: dafjev.benchmark-run/1\nbudget_usd: "100"\nbudget_usd: "25"\n'
    path.write_bytes(raw)
    output = tmp_path / "runs"
    with pytest.raises(ValueError, match="duplicate"):
        plan_run(path, output)
    assert path.read_bytes() == raw and not output.exists()
