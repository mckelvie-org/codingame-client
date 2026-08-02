"""Every real `CgLanguage` plugin lives here, one flat module per language (e.g. `python3.py`,
   `java.py`), each exposing a module-level `LANGUAGE: CgLanguage` singleton.
   `codingame_tools.language.registry` discovers every module under this directory automatically
   at load time (no hardcoded list, no exclusion list)--adding a new language is purely a matter
   of adding a new module here.
"""

from __future__ import annotations
