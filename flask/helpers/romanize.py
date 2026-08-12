#!/usr/bin/env python3
"""
Thai -> Romanisierung (RTGS)

Installation:
    pip install pythainlp
"""

from pythainlp.transliterate import romanize


def thai_to_roman(text: str) -> str:
    """
    Wandelt thailaendischen Text in Romanisierung (RTGS) um.
    Kein IPA, keine Tonhoehen, Standard wie in vielen Karaoke-/Lernkontexten.
    """
    if not text:
        return ""
    return romanize(text)


# ------------------------------------------------------------
# Test / Demo
# ------------------------------------------------------------
if __name__ == "__main__":

    thai_text = "ฉันรักเธอ แต่เธอไม่รู้"

    roman = thai_to_roman(thai_text)

    print("Thai:")
    print(thai_text)
    print()
    print("Romanisierung (RTGS):")
    print(roman)

