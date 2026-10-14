"""Bounded, fail-closed SVG validation shared by producer and future readers."""

import re
import xml.etree.ElementTree as ET

MAX_SVG_BYTES = 8 * 1024 * 1024
SVG_NS = "http://www.w3.org/2000/svg"
ELEMENTS = frozenset({"svg", "g", "defs", "path", "use", "symbol", "text", "tspan",
                      "rect", "line", "polyline", "polygon", "circle", "ellipse",
                      "title", "desc", "style", "clipPath"})


def validate_svg(content):
    if not isinstance(content, bytes) or not 0 < len(content) <= MAX_SVG_BYTES:
        raise ValueError("SVG exceeds size limit or is empty")
    text = content.decode("utf-8", errors="strict")
    if "<!" in text and re.search(r"<!\s*(?:DOCTYPE|ENTITY)", text, re.I):
        raise ValueError("SVG DTD/entities are forbidden")
    if "<?" in text.replace('<?xml version="1.0" encoding="UTF-8"?>', ""):
        raise ValueError("SVG processing instructions are forbidden")
    root = ET.fromstring(content)
    if root.tag != f"{{{SVG_NS}}}svg":
        raise ValueError("Expected an SVG document")
    for element in root.iter():
        if not element.tag.startswith(f"{{{SVG_NS}}}") or element.tag.split("}")[-1] not in ELEMENTS:
            raise ValueError("SVG contains a forbidden element")
        for key, value in element.attrib.items():
            name = key.split("}")[-1].lower()
            if name.startswith("on") or name in {"base", "src"}:
                raise ValueError("SVG event attributes/base/src are forbidden")
            if name == "href" and not re.fullmatch(r"#[A-Za-z_][\w.:-]*", value):
                raise ValueError("SVG permits only local fragment references")
            validate_css(value)
        if element.tag == f"{{{SVG_NS}}}style":
            validate_css("".join(element.itertext()))
    return root


def validate_css(value):
    # Reject escaped/comment-obfuscated CSS rather than attempting a CSS parser.
    if any(token in value for token in ("\\", "/*", "*/", "<", ">")):
        raise ValueError("SVG contains unsafe CSS/attribute content")
    if re.search(r"@|expression\s*\(|javascript\s*:|https?\s*:|data\s*:", value, re.I):
        raise ValueError("SVG contains external or executable content")
    for target in re.findall(r"url\s*\((.*?)\)", value, re.I):
        if not re.fullmatch(r"\s*['\"]?#[A-Za-z_][\w.:-]*['\"]?\s*", target):
            raise ValueError("SVG CSS permits only local fragment URLs")
