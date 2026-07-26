"""Refinement of dataclass_wizard.JSONWizard to use stronger JSONDict type hints"""

import json
import logging
from collections.abc import Collection
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, cast

from dataclass_wizard import JSONWizard
from dataclass_wizard.models import Alias, CatchAll
from json_data_types import JsonDict, validate_json_dict

from .typedefs import Self

logger = logging.getLogger(__name__)

__all__ = [
    "JSONWizardX", "CatchAll", "JsonDictDecoder",
    "JsonDictEncoder", "JsonDict", "validate_json_dict",
    "DEFAULT_JSON_DECODER",
    "DEFAULT_JSON_ENCODER",
    "Alias", "CgEpochMillis",
]


class CgEpochMillis(datetime):
    """A `datetime` subclass used only as the declared type of the private storage field behind a
       millisecond-epoch-int timestamp property (see e.g. `CgNotification.date`). Never exposed
       publicly--the property getter/setter pair around it deals in plain `datetime` values, calling
       `upcast()` in the setter so the stored value always (de)serializes correctly."""

    @classmethod
    def upcast(cls, value: datetime) -> Self:
        """Return `value` unchanged if it's already a `CgEpochMillis`; otherwise return a copy with
           UTC timezone properly inferred. Naive values are assumed to be in the local timezone;
           aware values are converted, preserving the same instant. Property setters should call
           this rather than re-implementing the conversion."""
        return value if isinstance(value, cls) else cls.fromtimestamp(value.timestamp(), tz=timezone.utc)


def _load_cg_epoch_millis(value: int) -> CgEpochMillis:
    return CgEpochMillis.fromtimestamp(value / 1000, tz=timezone.utc)


def _dump_cg_epoch_millis(value: datetime) -> int:
    return int(value.timestamp() * 1000)


class JsonDictDecoder(Protocol):
    """A callable that takes a JSON string and returns a JsonDict. Compatible with json.loads."""
    def __call__(self,
                s: str,
                **kwargs: Any
            ) -> JsonDict:
        ...

class JsonDictEncoder(Protocol):
    """A callable that takes a JsonDict and returns a JSON string. Compatible with json.dumps. Must accept
       keyword arguments for json.dumps, such as indent, separators, sort_keys, etc."""
    def __call__(self,
                obj: JsonDict,
                *,
                indent: int | None,
                sort_keys: bool,
                **kwargs: Any
            ) -> str:
        ...
        
DEFAULT_JSON_DECODER: JsonDictDecoder = json.loads
DEFAULT_JSON_ENCODER: JsonDictEncoder = json.dumps

class JSONWizardX(JSONWizard):
    """Refinement of dataclass_wizard.JSONWizard to use stronger JSONDict type hints.

       All JSON keys are camelCase by convention--this maps them to/from snake_case field
       names by default. Fields left at their default value are omitted when dumping, by
       default. Subclasses that need to customize `Meta` further should inherit from
       `JSONWizardX.Meta` (e.g. `class _(JSONWizardX.Meta): ...`) rather than
       `JSONWizard.Meta` directly, so these defaults aren't lost."""

    class Meta(JSONWizard.Meta):
        case = "CAMEL"
        skip_defaults = True
        type_to_load_hook = {CgEpochMillis: ("runtime", _load_cg_epoch_millis)}
        type_to_dump_hook = {CgEpochMillis: ("runtime", _dump_cg_epoch_millis)}

    def __post_init__(self) -> None:
        """Logs a debug message if the instance has a non-empty `extra_data` (CatchAll) field--i.e.
           the server response included fields not recognized by this dataclass's schema. Runs on
           every construction path (`from_dict`, `from_list`, and direct construction), since
           `dataclasses.__init__` calls `__post_init__` regardless of how it was invoked. Subclasses
           that define their own `__post_init__` should call `super().__post_init__()`."""
        extra_data = getattr(self, "extra_data", None)
        if extra_data:
            logger.debug(
                    "%s: response contained %d unrecognized field(s): %r",
                    type(self).__name__, len(extra_data), extra_data,
                )

    def to_dict(
                self,
                *,
                dict_factory: Any = dict,
                exclude: Collection[str] | None = None,
                skip_defaults: bool | None = None,
            ) -> JsonDict:
        """Convert the dataclass instance to a JSON-compatible dictionary."""
        return super().to_dict(dict_factory=dict_factory, exclude=exclude, skip_defaults=skip_defaults)

    @classmethod
    def from_dict(cls, d: JsonDict) -> Self:
        """Create a dataclass instance from a JSON-compatible dictionary."""
        return super().from_dict(d)

    @classmethod
    def from_list(cls, list_of_dict: list[JsonDict]) -> list[Self]:
        """Create a list of dataclass instances from a JSON-compatible list of dictionaries."""
        return super().from_list(list_of_dict)

    @classmethod
    def normalize(cls, value: Self | JsonDict) -> Self:
        """Normalize a value to an instance of this dataclass. If value is a dict, convert it to an instance."""
        if isinstance(value, cls):
            return value
        else:
            return cls.from_dict(cast(JsonDict, value))

    @classmethod
    def loads(cls,
                text: str,
                *,
                decoder: JsonDictDecoder = DEFAULT_JSON_DECODER,
                **decoder_kwargs: Any
            ) -> Self:
        """Creates an instance of this class from a JSON string.
        
           Keyword parameters are compatible with json.loads.
        """
        jd = validate_json_dict(decoder(text, **decoder_kwargs))
        result = cls.from_dict(jd)
        return result

    @classmethod
    def load(cls,
               path: str | Path,
               *,
               decoder: JsonDictDecoder = DEFAULT_JSON_DECODER,
               **decoder_kwargs: Any
            ) -> Self:
        """Creates an instance of this class from a JSON file.
        
           Keyword parameters are compatible with json.loadds.
        """
        with open(path, encoding="utf-8") as f:
            text = f.read()
            result = cls.loads(text, decoder=decoder, **decoder_kwargs)
            return result
        
    def saves(self, *,
                encoder: JsonDictEncoder = DEFAULT_JSON_ENCODER,
                indent: int | None = 2,
                sort_keys: bool = True,
               **encoder_kwargs: Any
            ) -> str:
        """Converts the dataclass instance to a JSON string.
        
           Keyword parameters are compatible with json.dumps. The default
           values for indent and sort_keys are changed:
                indent=2, sort_keys=True
        """
        jd = self.to_dict()
        text = encoder(jd, indent=indent, sort_keys=sort_keys, **encoder_kwargs)
        return text

    def save(self,
                path: str | Path,
                encoder: JsonDictEncoder = DEFAULT_JSON_ENCODER,
                indent: int | None = 2,
                sort_keys: bool = True,
               **encoder_kwargs: Any
            ) -> None:
        """Saves the dataclass instance to a JSON file, with a newline at the end.
        
           Keyword parameters are compatible with json.dumps. The default
           values for indent and sort_keys are changed:
                indent=2, sort_keys=True
        """
        text = self.saves(encoder=encoder, indent=indent, sort_keys=sort_keys, **encoder_kwargs)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
            f.write("\n")
