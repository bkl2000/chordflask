"""Optional Thai romanization for generated lyric sidecars."""

from __future__ import annotations

import re
from collections.abc import Callable


DEFAULT_ENGINE = "thai2rom_onnx"
SUPPORTED_ENGINES = ("thai2rom_onnx", "tltk", "royin")

_THAI_RUN_RE = re.compile(r"[\u0E00-\u0E7F]+")


class RomanizationError(RuntimeError):
    """The selected optional romanization engine could not be used."""


def contains_thai(text: str) -> bool:
    """Return whether ``text`` contains a character in the Thai Unicode block."""
    return _THAI_RUN_RE.search(text) is not None


def romanize_thai(
    text: str,
    *,
    engine: str = DEFAULT_ENGINE,
    romanize: Callable[..., str] | None = None,
    tokenize: Callable[[str], list[str]] | None = None,
) -> str | None:
    """Romanize Thai runs while preserving all non-Thai text verbatim.

    PyThaiNLP is imported only when Thai is actually present, keeping ordinary
    generation and the core/standalone reader independent of the optional
    generation dependency.
    """
    if not contains_thai(text):
        return None
    if engine not in SUPPORTED_ENGINES:
        raise RomanizationError(f'unsupported Thai romanization engine "{engine}"')

    if romanize is None:
        try:
            from pythainlp.transliterate import romanize as pythainlp_romanize
            from pythainlp.tokenize import word_tokenize
        except ImportError as error:
            raise RomanizationError(
                "Thai romanization requires the source-installation lyrics "
                "dependencies; rerun make setup"
            ) from error
        romanize = pythainlp_romanize
        def tokenize(value: str) -> list[str]:
            return word_tokenize(value, engine="newmm", keep_whitespace=False)
    elif tokenize is None:
        def tokenize(value: str) -> list[str]:
            return [value]

    def replace(match: re.Match[str]) -> str:
        try:
            words = tokenize(match.group(0))
            result = " ".join(romanize(word, engine=engine) for word in words)
        except (ImportError, ModuleNotFoundError) as error:
            raise RomanizationError(
                f'Thai romanization engine "{engine}" is unavailable: {error}'
            ) from error
        except Exception as error:  # PyThaiNLP engines expose differing errors.
            raise RomanizationError(
                f'Thai romanization engine "{engine}" failed: {error}'
            ) from error
        if not isinstance(result, str) or not result.strip():
            raise RomanizationError(
                f'Thai romanization engine "{engine}" returned no text'
            )
        return result

    return _THAI_RUN_RE.sub(replace, text)
