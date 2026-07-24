"""Bounded, duplicate-safe JSON decoding for control-plane messages."""

from __future__ import annotations

import json
import math


class StrictJSONError(ValueError):
    """The input is not an admissible control-plane JSON document."""


def loads(raw, *, max_bytes=65536, max_depth=20, max_nodes=4096):
    """Decode a bounded JSON document without lossy parser extensions."""
    if isinstance(raw, bytes):
        if len(raw) > max_bytes:
            raise StrictJSONError("JSON document exceeds byte limit")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise StrictJSONError("JSON document is not UTF-8") from exc
    elif isinstance(raw, str):
        try:
            encoded_size = len(raw.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise StrictJSONError("JSON document is not valid Unicode") from exc
        if encoded_size > max_bytes:
            raise StrictJSONError("JSON document exceeds byte limit")
        text = raw
    else:
        raise StrictJSONError("JSON document must be text or bytes")

    def object_no_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise StrictJSONError(f"duplicate JSON object key: {key}")
            result[key] = value
        return result

    def finite_float(token):
        value = float(token)
        if not math.isfinite(value):
            raise StrictJSONError("non-finite JSON number")
        return value

    def bounded_int(token):
        digits = token.lstrip("-")
        if len(digits) > 128:
            raise StrictJSONError("JSON integer exceeds digit limit")
        return int(token)

    def reject_constant(token):
        raise StrictJSONError(f"non-standard JSON constant: {token}")

    try:
        value = json.loads(
            text,
            object_pairs_hook=object_no_duplicates,
            parse_constant=reject_constant,
            parse_float=finite_float,
            parse_int=bounded_int,
        )
    except StrictJSONError:
        raise
    except (TypeError, ValueError, RecursionError) as exc:
        raise StrictJSONError("invalid JSON document") from exc

    nodes = 0
    stack = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > max_nodes:
            raise StrictJSONError("JSON document exceeds node limit")
        if depth > max_depth:
            raise StrictJSONError("JSON document exceeds depth limit")
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
    return value
