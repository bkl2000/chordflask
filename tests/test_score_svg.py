from pathlib import Path

import pytest

from chordflask_score.svg import MAX_SVG_BYTES, validate_svg


def svg(body="", attrs=""):
    return f'<svg xmlns="http://www.w3.org/2000/svg" {attrs}>{body}</svg>'.encode()


def test_actual_verovio_output_is_safe():
    path = Path(__file__).parent / "fixtures/score/verovio.svg"
    root = validate_svg(path.read_bytes())
    assert any(n.get("id") == "right-measure-1" for n in root.iter())
    assert sum("tempo" in node.get("class", "").split() for node in root.iter()) == 1


@pytest.mark.parametrize("content", [
    svg('<script>alert(1)</script>'), svg('<foreignObject/>'), svg(attrs='onload="alert(1)"'),
    svg('<use href="https://example.org/x.svg#a"/>'), svg('<use href="//example.org/x"/>'),
    svg('<use href="data:image/svg+xml;base64,AA"/>'),
    svg('<style>@import "https://example.org/style";</style>'),
    svg('<path style="fill:url(https://example.org/a)"/>'),
    svg('<path style="fill:url(//example.org/a)"/>'),
    svg('<style>path{fill:u\\72l(https://example.org/a)}</style>'),
    b'<!DOCTYPE svg [<!ENTITY x "bad">]>' + svg(),
    b'<?xml-stylesheet href="https://example.org/a"?>' + svg(),
    svg(attrs='xml:base="https://example.org/"'), svg('<a href="#a"/>'),
    svg('<image href="#a"/>'), b'x' * (MAX_SVG_BYTES + 1),
])
def test_unsafe_svg_is_rejected(content):
    with pytest.raises(ValueError):
        validate_svg(content)


def test_local_glyph_and_css_fragment_references_are_allowed():
    validate_svg(svg('<defs><path id="glyph"/></defs><use href="#glyph"/><path fill="url(#glyph)"/>'))
