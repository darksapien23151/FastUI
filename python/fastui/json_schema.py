from __future__ import annotations as _annotations

import json
import re
import typing
from typing import Iterable, Literal, TypeAlias, TypedDict, TypeGuard, cast

from pydantic import BaseModel
from typing_extensions import Required

from .components.forms import (
    FormField,
    FormFieldBoolean,
    FormFieldFile,
    FormFieldInput,
    FormFieldSelect,
    FormFieldSelectSearch,
    InputHtmlType,
)

if typing.TYPE_CHECKING:
    from .forms import SelectOption
else:
    SelectOption = dict

__all__ = 'model_json_schema_to_fields', 'SchemeLocation'


def model_json_schema_to_fields(model: type[BaseModel]) -> list[FormField]:
    schema = cast(JsonSchemaObject, model.model_json_schema())
    defs = schema.get('$defs', {})
    return list(json_schema_obj_to_fields(schema, [], [], defs))


JsonSchemaInput: (
    TypeAlias
) = 'JsonSchemaString | JsonSchemaStringEnum | JsonSchemaFile | JsonSchemaInt | JsonSchemaNumber'
JsonSchemaField: TypeAlias = 'JsonSchemaInput | JsonSchemaBool'
JsonSchemaConcrete: TypeAlias = 'JsonSchemaField | JsonSchemaArray | JsonSchemaObject'
JsonSchemaAny: TypeAlias = 'JsonSchemaConcrete | JsonSchemaAnyOf | JsonSchemaAllOf | JsonSchemaRef'


class JsonSchemaBase(TypedDict, total=False):
    title: str
    description: str


class JsonSchemaString(JsonSchemaBase):
    type: Required[Literal['string']]
    default: str
    format: Literal['date', 'date-time', 'time', 'email', 'uri', 'uuid', 'password']


class JsonSchemaStringEnum(JsonSchemaBase, total=False):
    type: Required[Literal['string']]
    enum: Required[list[str]]
    default: str
    placeholder: str
    enum_labels: dict[str, str]


class JsonSchemaStringSearch(JsonSchemaBase, total=False):
    type: Required[Literal['string']]
    search_url: Required[str]
    placeholder: str
    initial: SelectOption


class JsonSchemaFile(JsonSchemaBase, total=False):
    type: Required[Literal['string']]
    format: Required[Literal['binary']]
    accept: str


class JsonSchemaBool(JsonSchemaBase, total=False):
    type: Required[Literal['boolean']]
    default: bool
    mode: Literal['checkbox', 'switch']


class JsonSchemaInt(JsonSchemaBase, total=False):
    type: Required[Literal['integer']]
    default: int
    minimum: int
    exclusiveMinimum: int
    maximum: int
    exclusiveMaximum: int
    multipleOf: int


class JsonSchemaNumber(JsonSchemaBase, total=False):
    type: Required[Literal['number']]
    default: float
    minimum: float
    exclusiveMinimum: float
    maximum: float
    exclusiveMaximum: float
    multipleOf: float


class JsonSchemaArray(JsonSchemaBase, total=False):
    type: Required[Literal['array']]
    uniqueItems: bool
    minItems: int
    maxItems: int
    prefixItems: list[JsonSchemaAny]
    items: JsonSchemaAny
    search_url: str
    placeholder: str


JsonSchemaDefs = dict[str, JsonSchemaConcrete]
JsonSchemaObject = TypedDict(
    'JsonSchemaObject',
    {
        'type': Required[Literal['object']],
        'properties': dict[str, JsonSchemaAny],
        '$defs': JsonSchemaDefs,
        'required': list[str],
        'title': str,
        'description': str,
    },
    total=False,
)


class JsonSchemaNull(JsonSchemaBase):
    type: Literal['null']


class JsonSchemaAnyOf(JsonSchemaBase):
    anyOf: list[JsonSchemaAny]


class JsonSchemaAllOf(JsonSchemaBase):
    allOf: list[JsonSchemaAny]


JsonSchemaRef = TypedDict('JsonSchemaRef', {'$ref': str})

SchemeLocation = list[str | int]


def json_schema_obj_to_fields(
    schema: JsonSchemaObject, loc: SchemeLocation, title: list[str], defs: JsonSchemaDefs
) -> Iterable[FormField]:
    required = set(schema.get('required', []))
    if properties := schema.get('properties'):
        for key, value in properties.items():
            yield from json_schema_any_to_fields(value, loc + [key], title, key in required, defs)


def json_schema_any_to_fields(
    schema: JsonSchemaAny, loc: SchemeLocation, title: list[str], required: bool, defs: JsonSchemaDefs
) -> Iterable[FormField]:
    schema, required = deference_json_schema(schema, defs, required)
    title = title + [schema.get('title') or loc_to_title(loc)]

    if schema_is_field(schema):
        yield json_schema_field_to_field(schema, loc, title, required)
    elif schema_is_array(schema):
        yield from json_schema_array_to_fields(schema, loc, title, required, defs)
    else:
        assert schema_is_object(schema), f'Unexpected schema type {schema}'

        yield from json_schema_obj_to_fields(schema, loc, title, defs)


def json_schema_field_to_field(
    schema: JsonSchemaField, loc: SchemeLocation, title: list[str], required: bool
) -> FormField:
    name = loc_to_name(loc)
    if schema['type'] == 'boolean':
        return FormFieldBoolean(
            name=name,
            title=title,
            required=required,
            initial=schema.get('default'),
            description=schema.get('description'),
            mode=schema.get('mode', 'checkbox'),
        )
    elif field := special_string_field(schema, name, title, required, False):
        return field
    else:
        return FormFieldInput(
            name=name,
            title=title,
            html_type=input_html_type(schema),
            required=required,
            initial=schema.get('default'),
            description=schema.get('description'),
        )


def loc_to_title(loc: SchemeLocation) -> str:
    return as_title(loc[-1])


def json_schema_array_to_fields(
    schema: JsonSchemaArray, loc: SchemeLocation, title: list[str], required: bool, defs: JsonSchemaDefs
) -> Iterable[FormField]:
    items_schema = schema.get('items')
    if items_schema:
        items_schema, required = deference_json_schema(items_schema, defs, required)
        for field_name in 'search_url', 'placeholder':
            if value := schema.get(field_name):
                items_schema[field_name] = value  # type: ignore
        if field := special_string_field(items_schema, loc_to_name(loc), title, required, True):
            return [field]
    raise NotImplementedError('todo')


def special_string_field(
    schema: JsonSchemaConcrete, name: str, title: list[str], required: bool, multiple: bool
) -> FormField | None:
    if schema['type'] == 'string':
        if schema.get('format') == 'binary':
            return FormFieldFile(
                name=name,
                title=title,
                required=required,
                multiple=multiple,
                accept=schema.get('accept'),
                description=schema.get('description'),
            )
        elif enum := schema.get('enum'):
            enum_labels = schema.get('enum_labels', {})
            return FormFieldSelect(
                name=name,
                title=title,
                placeholder=schema.get('placeholder'),
                required=required,
                multiple=multiple,
                options=[SelectOption(value=v, label=enum_labels.get(v) or as_title(v)) for v in enum],
                initial=schema.get('default'),
                description=schema.get('description'),
            )
        elif search_url := schema.get('search_url'):
            return FormFieldSelectSearch(
                search_url=search_url,
                name=name,
                title=title,
                placeholder=schema.get('placeholder'),
                required=required,
                multiple=multiple,
                initial=schema.get('initial'),
                description=schema.get('description'),
            )


def loc_to_name(loc: SchemeLocation) -> str:
    """
    Convert a loc to a string if any item contains a '.' or the first item starts with '[' then encode with JSON,
    otherwise join with '.'.

    The sister method `name_to_loc` is in `form_extra.py`.
    """
    if any(isinstance(v, str) and '.' in v for v in loc):
        return json.dumps(loc)
    elif isinstance(loc[0], str) and loc[0].startswith('['):
        return json.dumps(loc)
    else:
        return '.'.join(str(v) for v in loc)


def deference_json_schema(
    schema: JsonSchemaAny, defs: JsonSchemaDefs, required: bool
) -> tuple[JsonSchemaConcrete, bool]:
    """
    Convert a schema which might be a reference or union to a concrete schema.
    """
    if ref := schema.get('$ref'):
        defs = defs or {}
        def_schema = defs[ref.rsplit('/')[-1]]
        if def_schema is None:
            raise ValueError(f'Invalid $ref "{ref}", not found in {defs}')
        else:
            return def_schema, required
    elif any_of := schema.get('anyOf'):
        if len(any_of) == 2 and sum(s.get('type') == 'null' for s in any_of) == 1:
            # If anyOf is a single type and null, then it is optional
            not_null_schema = next(s for s in any_of if s.get('type') != 'null')

            # copy everything except `anyOf` across to the new schema
            # TODO is this right?
            for key, value in schema.items():  # type: ignore
                if key not in {'anyOf'}:
                    not_null_schema[key] = value  # type: ignore

            return deference_json_schema(not_null_schema, defs, False)
        else:
            raise NotImplementedError('`anyOf` schemas which are not simply `X | None` are not yet supported')
    elif all_of := schema.get('allOf'):
        all_of = cast(list[JsonSchemaAny], all_of)
        if len(all_of) == 1:
            new_schema, required = deference_json_schema(all_of[0], defs, required)
            new_schema.update({k: v for k, v in schema.items() if k != 'allOf'})  # type: ignore
            return new_schema, required
        else:
            raise NotImplementedError('`allOf` schemas with more than 1 choice are not yet supported')
    else:
        return cast(JsonSchemaConcrete, schema), required


def as_title(s: typing.Any) -> str:
    return re.sub(r'[\-_]', ' ', str(s)).title()


type_lookup: dict[str, InputHtmlType] = {
    'string': 'text',
    'string-date': 'date',
    'string-date-time': 'datetime-local',
    'string-time': 'time',
    'string-email': 'email',
    'string-uri': 'url',
    'string-uuid': 'text',
    'string-password': 'password',
    'number': 'number',
    'integer': 'number',
}


def input_html_type(schema: JsonSchemaField) -> InputHtmlType:
    """
    Convert a schema into an HTML type
    """
    key = schema['type']
    if key == 'string':
        if string_format := schema.get('format'):
            key = f'string-{string_format}'

    try:
        return type_lookup[key]
    except KeyError as e:
        raise ValueError(f'Unknown schema: {schema}') from e


def schema_is_field(schema: JsonSchemaConcrete) -> TypeGuard[JsonSchemaField]:
    """
    Determine if a schema is a field `JsonSchemaField`
    """
    return schema['type'] in {'string', 'number', 'integer', 'boolean'}


def schema_is_array(schema: JsonSchemaConcrete) -> TypeGuard[JsonSchemaArray]:
    """
    Determine if a schema is an array `JsonSchemaArray`
    """
    return schema['type'] == 'array'


def schema_is_object(schema: JsonSchemaConcrete) -> TypeGuard[JsonSchemaObject]:
    """
    Determine if a schema is an object `JsonSchemaObject`
    """
    return schema['type'] == 'object'
