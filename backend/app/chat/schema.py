"""JSON schemas for structured model output."""

import copy
from typing import Any

from pydantic import BaseModel

_DROPPED_KEYS = {"title", "default", "examples"}


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """A schema in the strict subset providers accept for constrained decoding.

    References are inlined, every property is required and objects forbid extra properties.
    Optional values stay expressible as ``anyOf`` with ``null``.
    """
    schema = model.model_json_schema()
    definitions: dict[str, Any] = schema.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(item) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            return walk(copy.deepcopy(definitions[node["$ref"].rsplit("/", 1)[-1]]))
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key in _DROPPED_KEYS:
                continue
            if key == "properties":
                out[key] = {name: walk(sub) for name, sub in value.items()}
            else:
                out[key] = walk(value)
        if "properties" in out:
            out["required"] = list(out["properties"])
            out["additionalProperties"] = False
        return out

    result: dict[str, Any] = walk(schema)
    return result
