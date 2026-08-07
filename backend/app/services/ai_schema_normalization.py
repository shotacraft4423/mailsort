"""Generic, schema-introspecting repair pass for LLM JSON responses.

response_format={"type": "json_object"} (or an OpenAI-compatible provider
without real structured-output support) only guarantees syntactically valid
JSON — nothing about matching the target pydantic model's shape. In
production this has drifted in every direction the type system allows, each
discovered one field at a time from real user logs:

  1. translated key names            ({"案件か人材か": ...} instead of {"mail_type": ...})
  2. translated enum/literal values  (priority="低" instead of "low", or null
     for a required bool)
  3. list[BaseModel] sent as list[str] (categories=["案件紹介"] instead of
     [{"label": "案件紹介", "confidence": 0.8}])
  4. a single nested object sent as a bare list or string (tool_links=[
     "https://..."] instead of {"other_urls": ["https://..."]})
  5. scalar (X | None) fields sent as list[X] when the source content
     legitimately has more than one candidate value, and list[T] fields
     (Field(default_factory=list)) sent as null
  6. a required (non-Optional) nested-BaseModel field sent as null, a
     bare string sent for a nested object with no obvious re-nesting
     (meeting="8/4(火) 17:00～18:00＠web"), and a str field sent a
     structured dict instead of prose
  7. plain str/int/float type mismatches: a str field given a bare number
     (age: str | None getting 26), or an int/float field given a string
     with the number embedded in units the model left in
     (headcount: int | None getting "2名")
  8. a list[str] field given a list of lists (skills=[["Java","MySQL"],
     ["SQL","VBA"]] when the source email covered multiple candidates and
     the model grouped each candidate's skills instead of flattening them)

Patching each field as it broke (rounds 1-4 above) works but never
converges — every new field on ClassificationResult/ExtractionResult is a
fresh chance for the model to drift the same way again. `normalize_for_schema`
instead walks the target model's fields *once*, generically, using nothing
but each field's pydantic annotation + `model_json_schema()`'s enum list, and
repairs any value whose JSON-level shape doesn't match what that annotation
requires — the same handful of rules regardless of which field or which
model it runs against:

  - list[T] field getting `None` -> `[]`
  - list[BaseModel] field getting bare strings / a lone dict / a lone string,
    or dicts using a plausible alternate key name -> coerced into
    `[{...}, ...]` via a per-field `NestedListSpec`
  - single nested-BaseModel field getting a bare list/string (there's no
    generic way to know how to re-nest arbitrary scalars, e.g. tool_links'
    per-domain routing, so this is delegated to a per-field bucketizer
    callback the caller supplies)
  - required (non-Optional) field getting `None` -> its own field default
    (False for bool, the declared default/default_factory otherwise)
  - scalar `X | None` field getting `list[...]` -> the list's values joined
    into one string (str fields) or its first element (everything else)
  - `X | None` field (X != bool) getting a bare `bool` -> `None` (the model
    treating a free-text field as a yes/no question)
  - Literal/enum-valued field getting a Japanese synonym -> mapped via
    `_ENUM_VALUE_ALIASES`
  - `str` field getting a bare `int`/`float` -> stringified
  - `int`/`float` field getting a string with the number embedded in
    trailing units/counters -> the first number in the string, extracted

A field whose value is already well-formed is never touched. New fields
added to either schema get every rule above "for free" just by being present
in `model_fields` with an ordinary type; only a genuinely new *nesting*
pattern (list[BaseModel] item shape, or a single-nested-object field) needs a
spec/bucketizer registered once by the caller — not a new patch every time
the model drifts on a field that pattern already covers.
"""
from __future__ import annotations

import re
import types
import typing
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel

_NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")


def _extract_number(text: str, target_type: type) -> int | float | None:
    match = _NUMBER_PATTERN.search(text)
    if not match:
        return None
    value = float(match.group())
    return int(value) if target_type is int else value

_ENUM_VALUE_ALIASES: dict[str, str] = {
    # Priority / urgency fields: urgent / high / normal / low
    "緊急": "urgent",
    "至急": "urgent",
    "急ぎ": "urgent",
    "高": "high",
    "高い": "high",
    "中": "normal",
    "普通": "normal",
    "通常": "normal",
    "中程度": "normal",
    "低": "low",
    "低い": "low",
    # Sentiment: positive / neutral / negative
    "ポジティブ": "positive",
    "肯定的": "positive",
    "好意的": "positive",
    "中立": "neutral",
    "ニュートラル": "neutral",
    "ネガティブ": "negative",
    "否定的": "negative",
    # Temperature: hot / warm / cold
    "熱い": "hot",
    "ホット": "hot",
    "温かい": "warm",
    "暖かい": "warm",
    "ウォーム": "warm",
    "冷たい": "cold",
    "コールド": "cold",
}


@dataclass
class NestedListSpec:
    """Config for a list[BaseModel] field: which model each item should
    become, alternate key names the model might send instead of the
    canonical one, and default values to fill in when missing."""

    item_model: type[BaseModel]
    key_aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)
    defaults: dict[str, object] = field(default_factory=dict)


def _unwrap_optional(annotation: Any) -> Any:
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _is_optional(annotation: Any) -> bool:
    origin = typing.get_origin(annotation)
    return origin in (typing.Union, types.UnionType) and type(None) in typing.get_args(annotation)


def _list_item_type(annotation: Any) -> Any | None:
    unwrapped = _unwrap_optional(annotation)
    if typing.get_origin(unwrapped) is list:
        args = typing.get_args(unwrapped)
        return args[0] if args else None
    return None


def _is_basemodel_type(annotation: Any) -> bool:
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


def _flatten_to_str(value: object) -> str:
    if isinstance(value, list):
        return "、".join(_flatten_to_str(v) for v in value)
    if isinstance(value, dict):
        return "、".join(f"{k}: {_flatten_to_str(v)}" for k, v in value.items())
    return str(value)


def _coerce_nested_list_item(item: object, spec: NestedListSpec) -> object:
    primary_field = next(iter(spec.item_model.model_fields))
    if isinstance(item, str):
        return {primary_field: item, **spec.defaults}
    if isinstance(item, dict):
        remapped = dict(item)
        for canonical, aliases in spec.key_aliases.items():
            if canonical in remapped:
                continue
            for alias in aliases:
                if alias in remapped:
                    remapped[canonical] = remapped.pop(alias)
                    break
        for key, default_value in spec.defaults.items():
            remapped.setdefault(key, default_value)
        return remapped
    return item


def normalize_for_schema(
    model_cls: type[BaseModel],
    raw: dict,
    *,
    nested_list_specs: dict[str, NestedListSpec] | None = None,
    nested_object_bucketizers: dict[str, Callable[[list], dict]] | None = None,
) -> dict:
    if not isinstance(raw, dict):
        return raw

    nested_list_specs = nested_list_specs or {}
    nested_object_bucketizers = nested_object_bucketizers or {}
    normalized = dict(raw)
    schema_properties = model_cls.model_json_schema().get("properties", {})

    for field_name, field_info in model_cls.model_fields.items():
        if field_name not in normalized:
            continue
        value = normalized[field_name]
        annotation = field_info.annotation
        optional = _is_optional(annotation)
        unwrapped = _unwrap_optional(annotation)
        item_type = _list_item_type(annotation)

        # list[T] field: None -> [], and repair list[BaseModel] shape drift.
        if item_type is not None:
            if value is None:
                normalized[field_name] = []
            elif field_name in nested_list_specs:
                items = value if isinstance(value, list) else [value]
                normalized[field_name] = [
                    _coerce_nested_list_item(item, nested_list_specs[field_name]) for item in items
                ]
            elif item_type is str and isinstance(value, list):
                # list[str] field getting a list of lists/dicts instead of
                # strings (skills=[["Java","MySQL"], ["SQL","VBA"]] when the
                # source email covers multiple candidates and the model
                # grouped each candidate's skills instead of flattening
                # them) — flatten whichever items aren't already strings.
                normalized[field_name] = [item if isinstance(item, str) else _flatten_to_str(item) for item in value]
            continue

        # single nested BaseModel field sent as a bare list/string instead
        # of an object -> hand off to a caller-supplied bucketizer (there's
        # no generic way to know how arbitrary scalars should re-nest). A
        # *required* such field (e.g. tool_links: ToolLinks =
        # Field(default_factory=ToolLinks)) getting null needs its own
        # check here too — this branch used to `continue` unconditionally
        # for any BaseModel-typed field, which meant the generic
        # "required field got null" rule further down was never reached
        # for tool_links at all and it fell back to local_mock every time.
        if _is_basemodel_type(unwrapped):
            if value is None and not optional:
                normalized[field_name] = {}
            elif isinstance(value, (list, str)):
                bucketizer = nested_object_bucketizers.get(field_name)
                if bucketizer is not None:
                    items = value if isinstance(value, list) else [value]
                    normalized[field_name] = bucketizer(items)
            continue

        # required (non-Optional) field getting null -> its own default.
        if value is None and not optional:
            if unwrapped is bool:
                normalized[field_name] = False
            elif not field_info.is_required():
                normalized[field_name] = field_info.get_default(call_default_factory=True)
            continue

        # scalar field getting a list/dict where the model was asked for one
        # value (e.g. candidate_summary: str | None getting a structured
        # {"name": ..., "age": ...} dict instead of prose).
        if unwrapped in (str, int, float) and isinstance(value, (list, dict)):
            if unwrapped is str:
                if isinstance(value, list):
                    normalized[field_name] = "、".join(str(v) for v in value) if value else None
                else:
                    normalized[field_name] = "、".join(f"{k}: {v}" for k, v in value.items()) if value else None
            elif isinstance(value, list):
                normalized[field_name] = value[0] if value else None
            continue

        # str field getting a bare number instead of text (age: str | None
        # getting 26, unit_price: str | None getting 650000) -> stringify.
        if unwrapped is str and isinstance(value, (int, float)) and not isinstance(value, bool):
            normalized[field_name] = str(value)
            continue

        # int/float field getting a string with the number embedded in
        # units/counters the model left in (headcount: int | None getting
        # "2名", interview_count: int | None getting "1回") -> extract it.
        if unwrapped in (int, float) and isinstance(value, str):
            number = _extract_number(value, unwrapped)
            if number is not None:
                normalized[field_name] = number
            continue

        # Optional non-bool field getting a bare bool (yes/no misread of a
        # free-text field, e.g. sales_opportunity: str | None sent as False).
        if optional and unwrapped is not bool and isinstance(value, bool):
            normalized[field_name] = None
            continue

        # Literal/enum field getting a Japanese synonym instead of the
        # literal value the schema requires.
        if isinstance(value, str):
            allowed = schema_properties.get(field_name, {}).get("enum")
            if allowed and value not in allowed:
                mapped = _ENUM_VALUE_ALIASES.get(value)
                if mapped in allowed:
                    normalized[field_name] = mapped

    return normalized
