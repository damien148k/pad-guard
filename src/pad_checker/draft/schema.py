"""Extraction schema generated from the pydantic profile model (SPEC §13).

The model may only answer on fields that exist: the ``field`` of every finding is an enum of the
dotted paths of the profile leaves (sections format, video, audio, structure). Each path comes
with its French description and expected type, shown to the model in the prompt; the value is
then checked against the exact type of the field (:func:`check_value`). Sections ``meta`` (set by
the tool), ``rules`` (severities, decided by the reviewer) and ``llm`` are not extracted.
"""

from __future__ import annotations

import json
import types
import typing
from dataclasses import dataclass
from functools import cached_property
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError

from pad_checker.rules.profile import Profile

SECTIONS = ("format", "video", "audio", "structure")


@dataclass(frozen=True)
class FieldSpec:
    path: str  # "audio.true_peak_max_dbtp"
    annotation: Any
    description: str

    @cached_property
    def adapter(self) -> TypeAdapter:
        return TypeAdapter(self.annotation)

    @property
    def type_text(self) -> str:
        """Expected JSON type in a few words, for the prompt."""
        schema = self.adapter.json_schema()
        return _type_text(schema, schema.get("$defs", {}))


def _sub_model(annotation: Any) -> type[BaseModel] | None:
    args = typing.get_args(annotation) if (isinstance(annotation, types.UnionType)
                                          or typing.get_origin(annotation) is typing.Union) else (annotation,)
    return next((a for a in args if isinstance(a, type) and issubclass(a, BaseModel)), None)


def _leaves(model: type[BaseModel], prefix: str) -> list[FieldSpec]:
    out = []
    for name, f in model.model_fields.items():
        path = prefix + (f.alias or name)
        sub = _sub_model(f.annotation)
        if sub is not None:
            out += _leaves(sub, path + ".")
        else:
            out.append(FieldSpec(path=path, annotation=f.annotation, description=f.description or ""))
    return out


def catalogue() -> list[FieldSpec]:
    """Every extractable leaf of the profile, in model order."""
    out = []
    for section in SECTIONS:
        out += _leaves(_sub_model(Profile.model_fields[section].annotation), section + ".")
    return out


def _type_text(schema: dict, defs: dict) -> str:
    if "$ref" in schema:
        schema = defs[schema["$ref"].split("/")[-1]]
    if "anyOf" in schema:
        kinds = [_type_text(s, defs) for s in schema["anyOf"] if s.get("type") != "null"]
        return " ou ".join(kinds) + " (ou null)"
    if "enum" in schema:
        return "un de " + ", ".join(json.dumps(v) for v in schema["enum"])
    if "const" in schema:
        return json.dumps(schema["const"])
    kind = schema.get("type")
    if kind == "array":
        if "prefixItems" in schema:
            return "liste [" + ", ".join(_type_text(s, defs) for s in schema["prefixItems"]) + "]"
        return f"liste de {_type_text(schema.get('items', {}), defs)}"
    if kind == "object" and "properties" in schema:
        return "objet {" + ", ".join(f"{k}: {_type_text(v, defs)}" for k, v in schema["properties"].items()) + "}"
    if kind == "object":
        return "objet {clé: " + _type_text(schema.get("additionalProperties", {}), defs) + "}"
    return {"number": "nombre", "integer": "entier", "string": "texte", "boolean": "booléen"}.get(kind, "valeur")


def response_schema(fields: list[FieldSpec]) -> dict:
    """JSON schema imposed on the model: a list of findings on known fields."""
    return {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string", "enum": [f.path for f in fields]},
                        "value": {},
                        "page": {"type": "integer"},
                        "quote": {"type": "string"},
                        "unit": {"type": ["string", "null"]},
                    },
                    "required": ["field", "value", "page", "quote", "unit"],
                },
            },
        },
        "required": ["findings"],
    }


def check_value(spec: FieldSpec, value: Any) -> tuple[Any, str | None]:
    """(value converted to the field type, None) or (None, French reason)."""
    if value is None:
        return None, "valeur vide"
    try:
        checked = spec.adapter.validate_python(value)
    except ValidationError as exc:
        return None, f"valeur {value!r} incompatible avec le champ ({exc.errors()[0]['msg']})"
    return spec.adapter.dump_python(checked, mode="json"), None
