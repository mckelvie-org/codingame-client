"""Refinement of dataclass_wizard.JSONWizard to use stronger JSONDict type hints"""

import json
from collections.abc import Collection
from pathlib import Path
from typing import Any, Protocol, cast

from dataclass_wizard import JSONWizard
from dataclass_wizard.models import Alias, CatchAll
from json_data_types import JsonDict, validate_json_dict

from .typedefs import Self

__all__ = [
    "JSONWizardX", "CatchAll", "JsonDictDecoder",
    "JsonDictEncoder", "JsonDict", "validate_json_dict",
    "DEFAULT_JSON_DECODER",
    "DEFAULT_JSON_ENCODER",
    "Alias",
]

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
    """Refinement of dataclass_wizard.JSONWizard to use stronger JSONDict type hints"""
    
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
