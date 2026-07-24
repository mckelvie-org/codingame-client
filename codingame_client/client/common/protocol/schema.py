"""Common schema definitions for the CodinGame API."""

from __future__ import annotations

CgSolutionLanguage = str
"""The programming language used for the reference solution, e.g. "Python3", "Java", "C++", etc."""

_extension_map = {
        "sh": "Bash",
        "py": "Python3",
        "java": "Java",
        "cpp": "C++",
        "c": "C",
        "cs": "C#",
        "d": "DMD",
        "clj": "Clojure",
        "dart": "Dart",
        "fs": "F#",
        "groovy": "Groovy",
        "hs": "Haskell",
        "kt": "Kotlin",
        "lua": "Lua",
        "m": "Objective-C",
        "ml": "OCaml",
        "pas": "Pascal",
        "pl": "Perl",
        "php": "PHP",
        "scala": "Scala",
        "swift": "Swift",
        "vb": "VB.NET",
        "js": "JavaScript",
        "ts": "TypeScript",
        "rb": "Ruby",
        "go": "Go",
        "rs": "Rust",
        # Add more mappings as needed
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
