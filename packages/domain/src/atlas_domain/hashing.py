"""Versioned deterministic JSON hashing for immutable application artifacts."""

import hashlib
import json
from typing import TypeAlias

JSONValue: TypeAlias = "None | bool | int | float | str | list[JSONValue] | dict[str, JSONValue]"


def canonical_json(value: JSONValue) -> bytes:
    """Serialize JSON v1: sorted keys, UTF-8, no whitespace or nonfinite values.

    This is an application encoding, not RFC 8785. Numeric representations remain
    distinct (1 versus 1.0); callers normalize units/types before hashing.
    """
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def content_hash(value: JSONValue) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()
