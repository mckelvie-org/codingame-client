"""Refinement of dataclass_wizard.JSONWizard to use stronger JSONDict type hints.

   ---------------------------------------------------------------------------------------------
   WARNING: this module contains a workaround that reaches into dataclass_wizard's PRIVATE API.
   ---------------------------------------------------------------------------------------------

   See `_CatchAllPreservingDict` and `JSONWizardX._apply_catch_all_workaround` below. In short:
   dataclass_wizard 1.0.0 destroys its own per-class `CatchAll` marker the first time it generates
   load/dump code for a class, so the *second* context that class appears in silently loses every
   unknown field -- and since this client's whole tolerance for an undocumented, changing API rests
   on `CatchAll`, that is not survivable.

   TODO: DELETE THE WORKAROUND once dataclass_wizard ships the fix.
     - Upstream bug: the codegen does `field_to_aliases.pop(CATCH_ALL, None)` on a dict that *is*
       the shared per-class cache (`_loaders.py` and `_dumpers.py`); it should use `.get()`.
     - Reported upstream, with a pull request, against 1.0.0. No response so far.
     - When a release containing the fix appears: bump the pin in `pyproject.toml`, delete
       `_CatchAllPreservingDict`, `_apply_catch_all_workaround` and its three call sites, and drop
       the private imports below. `tests/test_dataclass_wizard_catch_all.py` must keep passing
       untouched--it tests the *behaviour*, not the workaround, so it is exactly the check that
       tells you the fix really landed.

   The dependency is pinned to `dataclass-wizard==1.0.0` **because** of this. Private API means an
   upgrade can break the workaround, so the pin is deliberate, not laziness--do not relax it to a
   range without re-running the catch-all tests.
"""

import json
import logging
from collections.abc import Collection
from dataclasses import is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, Protocol, cast

import yaml
from dataclass_wizard import JSONWizard
from dataclass_wizard.models import Alias, CatchAll
from json_data_types import JsonDict, validate_json_dict

from .typedefs import Self

# --- PRIVATE dataclass_wizard API, used only by the CatchAll workaround --------------------------
# Imported explicitly (rather than defensively) so that an upgrade which moves or renames any of
# them fails loudly at import time, naming this module--rather than leaving the workaround silently
# inert and this client silently discarding every unknown field the server sends.
try:
    from dataclass_wizard._class_helper import (  # noqa: PLC2701
        DATACLASS_FIELD_TO_ALIAS_FOR_DUMP,
        DATACLASS_FIELD_TO_ALIAS_FOR_LOAD,
        setup_config_for_cls,
    )
    from dataclass_wizard.constants import CATCH_ALL  # noqa: PLC2701
except ImportError as e:  # pragma: no cover - only reachable on an unsupported dataclass_wizard
    raise ImportError(
        f"{__name__} depends on dataclass_wizard internals that this version doesn't provide "
        f"({e}). This client pins dataclass-wizard==1.0.0 to work around an upstream CatchAll bug "
        "(see this module's docstring). If you have upgraded deliberately, check whether the "
        "upstream fix has landed--if so, the workaround can be deleted entirely."
    ) from e

logger = logging.getLogger(__name__)

__all__ = [
    "JSONWizardX", "CatchAll", "JsonDictDecoder",
    "JsonDictEncoder", "JsonDict", "validate_json_dict",
    "DEFAULT_JSON_DECODER",
    "DEFAULT_JSON_ENCODER",
    "DEFAULT_YAML_DECODER",
    "DEFAULT_YAML_ENCODER",
    "Alias", "CgEpochMillis",
]


class _CatchAllPreservingDict(dict[Any, Any]):
    """WORKAROUND (see this module's docstring) -- a per-class alias mapping whose `CatchAll` marker
       survives being popped.

       dataclass_wizard 1.0.0's load/dump codegen starts with

           catch_all_field = field_to_aliases.pop(CATCH_ALL, None)

       believing `field_to_aliases` is its own scratch mapping. It isn't: it's a direct reference
       into a module-level, per-class cache. So the pop permanently strips the marker, and the next
       time code is generated for that same class in a different structural context (nested inside
       another dataclass rather than at the top level, say) the class no longer looks like it has a
       catch-all field at all. Unknown keys are then dropped, or the load blows up with an obscure
       `'_UnsetType' object is not callable`.

       Overriding `pop` for that one key keeps the caller's behaviour *within* a codegen pass
       identical--it still receives the value it asked for--while leaving the cached entry intact
       for the next pass.

       **Scoped deliberately.** The obvious alternative is to monkeypatch
       `_loaders.resolve_dataclass_field_to_alias_for_load`/`_dumpers....for_dump` to return copies,
       which is shorter and fixes the bug for the whole process. This client is a *library*: doing
       that would silently change dataclass_wizard's behaviour for every other package in whatever
       application imports us, which is not ours to decide. Installing this dict only under our own
       classes' cache keys leaves every other class in the process exactly as upstream ships it."""

    def pop(self, key: Any, default: Any = None) -> Any:
        if key == CATCH_ALL:
            return self.get(key, default)
        return super().pop(key, default)


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


def _yaml_decode(s: str, **kwargs: Any) -> JsonDict:
    if kwargs:
        raise TypeError(f"YAML decoder does not accept extra keyword arguments: {sorted(kwargs)}")
    result = yaml.safe_load(s)
    if result is None:
        # An empty or comment-only YAML document decodes to None, not {}--e.g. a config file
        # whose only real field is commented out as a documentation example. Treat that as an
        # empty mapping (all fields unset/default) rather than rejecting it as "not a dict".
        result = {}
    return cast(JsonDict, result)


def _yaml_encode(
            obj: JsonDict,
            *,
            indent: int | None = 2,
            sort_keys: bool = True,
            **kwargs: Any
        ) -> str:
    kwargs.setdefault("default_flow_style", False)
    return cast(str, yaml.safe_dump(obj, indent=indent, sort_keys=sort_keys, **kwargs))


DEFAULT_YAML_DECODER: JsonDictDecoder = _yaml_decode
DEFAULT_YAML_ENCODER: JsonDictEncoder = _yaml_encode

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

    _catch_all_workaround_pending: ClassVar[list[type["JSONWizardX"]]] = []
    """Subclasses registered but not yet protected--see `_apply_catch_all_workaround`."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Register the subclass for the CatchAll workaround (see this module's docstring).

           Registration only--the protection itself can't happen here. `__init_subclass__` runs
           during class *creation*, which is before `@dataclass` has been applied to the class body,
           so there are no fields yet for dataclass_wizard to build an alias mapping from."""
        super().__init_subclass__(**kwargs)
        JSONWizardX._catch_all_workaround_pending.append(cls)

    @staticmethod
    def _apply_catch_all_workaround() -> None:
        """WORKAROUND (see this module's docstring). Swap every registered subclass's cached alias
           mapping for a `_CatchAllPreservingDict`, so the codegen can't destroy its own marker.

           Applied to *every* registered class rather than just the one being loaded, and applied
           before any codegen runs. That's the whole point: the bug bites a class the second time
           code is generated for it, which for a nested schema is typically triggered by loading its
           *parent*. Protecting only the class you were asked for would leave every nested one
           exposed.

           Amortized to nothing--the pending list is drained on the first call and refilled only
           when a new subclass is defined."""
        pending = JSONWizardX._catch_all_workaround_pending
        while pending:
            cls = pending.pop()
            if not is_dataclass(cls):
                continue  # not a usable schema class; nothing to protect
            setup_config_for_cls(cls)
            for cache in (DATACLASS_FIELD_TO_ALIAS_FOR_LOAD, DATACLASS_FIELD_TO_ALIAS_FOR_DUMP):
                entry = cache.get(cls)
                if entry is not None and not isinstance(entry, _CatchAllPreservingDict):
                    cache[cls] = _CatchAllPreservingDict(entry)

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
        """Convert the dataclass instance to a JSON-compatible dictionary.

           If `skip_defaults` is not given (None), this class's own `Meta.skip_defaults` setting
           applies (True by default--see the class docstring). Passing `skip_defaults=None`
           through unconditionally to `dataclass_wizard`'s own `to_dict()` would NOT do this--it
           only consults `Meta.skip_defaults` when the keyword is omitted from the call entirely,
           not when it's explicitly present as None--so the keyword is only forwarded here when
           the caller actually wants to override the Meta-configured default.
        """
        self._apply_catch_all_workaround()  # WORKAROUND -- see this module's docstring
        kwargs: dict[str, Any] = {}
        if skip_defaults is not None:
            kwargs["skip_defaults"] = skip_defaults
        return super().to_dict(dict_factory=dict_factory, exclude=exclude, **kwargs)

    @classmethod
    def from_dict(cls, d: JsonDict) -> Self:
        """Create a dataclass instance from a JSON-compatible dictionary."""
        cls._apply_catch_all_workaround()  # WORKAROUND -- see this module's docstring
        return super().from_dict(d)

    @classmethod
    def from_list(cls, list_of_dict: list[JsonDict]) -> list[Self]:
        """Create a list of dataclass instances from a JSON-compatible list of dictionaries."""
        cls._apply_catch_all_workaround()  # WORKAROUND -- see this module's docstring
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

    @classmethod
    def from_yaml(cls, text: str) -> Self:
        """Creates an instance of this class from a YAML string. Convenience wrapper over
           `loads()` using a YAML decoder instead of the default JSON one."""
        return cls.loads(text, decoder=DEFAULT_YAML_DECODER)

    @classmethod
    def load_yaml(cls, path: str | Path) -> Self:
        """Creates an instance of this class from a YAML file. Convenience wrapper over `load()`
           using a YAML decoder instead of the default JSON one."""
        return cls.load(path, decoder=DEFAULT_YAML_DECODER)

    def to_yaml(self) -> str:
        """Converts the dataclass instance to a YAML string. Convenience wrapper over `saves()`
           using a YAML encoder instead of the default JSON one."""
        return self.saves(encoder=DEFAULT_YAML_ENCODER)

    def save_yaml(self, path: str | Path) -> None:
        """Saves the dataclass instance to a YAML file, with a newline at the end. Convenience
           wrapper over `save()` using a YAML encoder instead of the default JSON one."""
        self.save(path, encoder=DEFAULT_YAML_ENCODER)
