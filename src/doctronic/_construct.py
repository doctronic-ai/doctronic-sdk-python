"""Build response models from data that doesn't match the contract, instead of failing.

Responses are validated against the generated models first. When that fails, for example because
a field is missing or has a type the contract doesn't describe, `construct()` builds the model
anyway: every value that validates is typed as usual, and the rest is kept as the API sent it.

- A missing field is `None`, or its default when the contract declares one.
- A value of an unexpected type is kept as sent, such as a `str` where the model expects a
  `datetime`.
- An object in a union becomes the member its discriminator names. With no match, it becomes the
  first model member, with the discriminator as sent.
- Fields the contract doesn't list are kept, as they are after normal validation.
"""

from __future__ import annotations

import types
import typing
from collections.abc import Mapping
from typing import Annotated, Any, Literal, get_args, get_origin

import pydantic

__all__ = ["construct"]

_ADAPTERS: dict[Any, pydantic.TypeAdapter[Any]] = {}


def _adapter(annotation: Any) -> pydantic.TypeAdapter[Any]:
    try:
        return _ADAPTERS[annotation]
    except KeyError:
        adapter = _ADAPTERS[annotation] = pydantic.TypeAdapter(annotation)
        return adapter
    except TypeError:  # Unhashable metadata: build it each time. This path is rare.
        return pydantic.TypeAdapter(annotation)


def _unwrap(annotation: Any) -> tuple[Any, list[Any]]:
    """Strip type aliases and `Annotated`, keeping the metadata."""
    metadata: list[Any] = []
    while True:
        if type(annotation).__name__ == "TypeAliasType" and hasattr(annotation, "__value__"):
            annotation = annotation.__value__
        elif get_origin(annotation) is Annotated:
            annotation, *extra = get_args(annotation)
            metadata += extra
        else:
            return annotation, metadata


def _is_model(annotation: Any) -> bool:
    return isinstance(annotation, type) and issubclass(annotation, pydantic.BaseModel)


def construct(annotation: Any, value: Any) -> Any:
    """`value` validated as `annotation`, or built as close to it as the data allows."""
    try:
        return _adapter(annotation).validate_python(value)
    except pydantic.ValidationError:
        return _build(annotation, value)


def _build(annotation: Any, value: Any) -> Any:
    annotation, metadata = _unwrap(annotation)
    if value is None:
        return None
    if _is_model(annotation):
        return _build_model(annotation, value) if isinstance(value, Mapping) else value
    origin = get_origin(annotation)
    if origin is typing.Union or origin is types.UnionType:
        members = [arg for arg in get_args(annotation) if arg is not type(None)]
        return _build_union(members, metadata, value)
    if origin is list and isinstance(value, list):
        (item,) = get_args(annotation) or (Any,)
        return [construct(item, entry) for entry in value]
    if origin is dict and isinstance(value, Mapping):
        _, item = get_args(annotation) or (Any, Any)
        return {key: construct(item, entry) for key, entry in value.items()}
    return value


def _build_union(members: list[Any], metadata: list[Any], value: Any) -> Any:
    for member in members:
        try:
            return _adapter(member).validate_python(value)
        except pydantic.ValidationError:
            continue
    if not isinstance(value, Mapping):
        return value
    models = [model for model in (_unwrap(member)[0] for member in members) if _is_model(model)]
    if not models:
        return value
    discriminator = next(
        (
            item.discriminator
            for item in metadata
            if isinstance(getattr(item, "discriminator", None), str)
        ),
        None,
    )
    if discriminator is not None:
        for model in models:
            field = model.model_fields.get(discriminator)
            if field is None:
                continue
            tag = value.get(field.alias or discriminator, value.get(discriminator))
            literal, _ = _unwrap(field.annotation)
            if get_origin(literal) is Literal and tag in get_args(literal):
                return _build_model(model, value)
    return _build_model(models[0], value)


def _build_model(model: type[pydantic.BaseModel], data: Mapping[str, Any]) -> pydantic.BaseModel:
    values: dict[str, Any] = {}
    fields_set: set[str] = set()
    known: set[str] = set()
    for name, field in model.model_fields.items():
        key = field.alias or name
        known.update((name, key))
        if key in data:
            raw = data[key]
        elif name in data:
            raw = data[name]
        else:
            values[name] = (
                None
                if field.is_required()
                else field.get_default(call_default_factory=True, validated_data=values)
            )
            continue
        values[name] = construct(field.annotation, raw)
        fields_set.add(name)
    extra = {
        key: value
        for key, value in data.items()
        if isinstance(key, str) and key not in known and key != "_fields_set"
    }
    return model.model_construct(fields_set, **values, **extra)
