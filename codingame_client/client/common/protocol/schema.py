"""Common schema definitions for the CodinGame API."""

from __future__ import annotations

CgSolutionLanguage = str
"""The programming language used for the reference solution, e.g. "Python3", "Java", "C++", etc.

   Code submitted/played (`TestSession/play`, `TestSession/submit`, contribution
   `updateContribution`/`createContribution`) runs server-side in a sandbox with a specific
   version and, for some languages, specific bundled libraries--relevant to know when writing a
   solution that assumes a particular language feature or library is available. Confirmed:

   - **Python3**: 3.11.5, with NumPy, pandas, and SciPy available.

   Other languages' exact versions/bundled libraries aren't catalogued here yet--see
   https://www.codingame.com/playgrounds/40701/help-center/languages-versions (a client-rendered
   page; fetching it programmatically only returns the loading shell, not the real content, so
   this couldn't be filled in automatically--add entries here as they're confirmed for other
   languages actually in use)."""

_extension_map = {
        "sh": "Bash",
        "py": "Python3",
        "java": "Java",
        "cpp": "C++",
        "c": "C",
        "cs": "C#",
        "d": "D",
        "clj": "Clojure",
        "dart": "Dart",
        "fs": "F#",
        "groovy": "Groovy",
        "hs": "Haskell",
        "kt": "Kotlin",
        "lua": "Lua",
        "m": "ObjectiveC",
        "ml": "OCaml",
        "pas": "Pascal",
        "pl": "Perl",
        "php": "PHP",
        "scala": "Scala",
        "swift": "Swift",
        "vb": "VB.NET",
        "js": "Javascript",
        "ts": "TypeScript",
        "rb": "Ruby",
        "go": "Go",
        "rs": "Rust",
        # Confirmed live (2026-07-28) against `ProgrammingLanguage/findAllIds`--matches this
        # exact 27-entry set of solution-language ID strings. Three values were previously
        # wrong (didn't match any real ID, so `cg_solution_language_to_extension` silently
        # returned None for them): "DMD" -> "D", "Objective-C" -> "ObjectiveC" (no hyphen),
        # "JavaScript" -> "Javascript" (lowercase "s").
    }

def cg_extension_to_solution_language(filename_or_extension: str) -> CgSolutionLanguage | None:
    """Map a file extension to the corresponding Codingame solution language string used in the protocol.
       Returns None if the extension is not recognized."""
    ext = filename_or_extension.lower()
    if ext.startswith("."):
        ext = ext[1:]
    return _extension_map.get(ext)

_language_to_extension_map: dict[str, str] = {lang: ext for ext, lang in _extension_map.items()}

def cg_solution_language_to_extension(language: CgSolutionLanguage) -> str | None:
    """Map a Codingame solution language string to a file extension.
       Returns None if the language is not recognized."""
    return _language_to_extension_map.get(language)
