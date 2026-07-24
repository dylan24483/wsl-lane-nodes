"""Adversarial parser bounds for the physical control plane."""

import pytest

from lane_node.strict_json import StrictJSONError, loads


@pytest.mark.parametrize("raw", [
    '{"lane":21,"lane":22}',
    '{"value":NaN}',
    '{"value":Infinity}',
    '{"value":-Infinity}',
    '{"value":1e9999}',
    '{"value":' + ('[' * 21) + '0' + (']' * 21) + '}',
])
def test_strict_control_json_rejects_lossy_or_unbounded_forms(raw):
    with pytest.raises(StrictJSONError):
        loads(raw, max_bytes=65536, max_depth=20, max_nodes=4096)


def test_strict_control_json_enforces_byte_and_node_limits():
    with pytest.raises(StrictJSONError, match="byte limit"):
        loads('"' + ("x" * 100) + '"', max_bytes=32)
    with pytest.raises(StrictJSONError, match="node limit"):
        loads("[0,1,2,3]", max_nodes=4)
