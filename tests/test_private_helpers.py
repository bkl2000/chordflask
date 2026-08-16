"""Contract test: production code never imports the private helper directory."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
_PRIVATE_DIR = REPO_ROOT / "flask" / "helpers" / "private"

_PRODUCTION_ROOTS = (
    REPO_ROOT / "flask",
    REPO_ROOT / "chordflask_base",
    REPO_ROOT / "chordflask_maintain",
)

_FORBIDDEN = (
    "helpers.private",
    "helpers/private",
    "from .private",
    "from helpers.private",
)


def _production_sources():
    for root in _PRODUCTION_ROOTS:
        for path in root.rglob("*.py"):
            if path.is_relative_to(_PRIVATE_DIR):
                continue
            yield path


def test_production_does_not_import_private_helpers():
    sources = list(_production_sources())
    assert sources, "no production Python sources found"
    for path in sources:
        text = path.read_text(encoding="utf-8")
        for term in _FORBIDDEN:
            assert term not in text, f"{path} references private helpers: {term}"
