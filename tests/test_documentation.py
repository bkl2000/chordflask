from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_readme_has_one_copyable_beginner_path():
    readme = (REPO_ROOT / "README.md").read_text()

    commands = (
        "sudo apt update",
        "git clone https://github.com/bkl2000/chordflask.git",
        "make setup-runtime",
        "make plugins",
        "make run",
    )
    positions = [readme.index(command) for command in commands]
    assert positions == sorted(positions)
    assert "http://localhost:5000" in readme
    assert "you do not need to\nactivate that environment" in readme
    assert "First use" in readme
    assert ".chordflask" in readme


def test_readme_names_portable_archive_and_complete_guide():
    readme = (REPO_ROOT / "README.md").read_text()
    guide = (REPO_ROOT / "docs" / "STANDALONE.md").read_text()

    assert "source code only, not a ready-made executable" in readme
    assert "flask/dist/chordflask-linux-x86_64.tar.gz" in readme
    assert "docs/STANDALONE.md" in readme
    for command in (
        "tar -xzf chordflask-linux-x86_64.tar.gz",
        "./install_vamp.sh",
        "./chordflask --version",
        "./chordflask.sh",
    ):
        assert command in guide


def test_public_documentation_links_resolve():
    readme = (REPO_ROOT / "README.md").read_text()
    linked_files = (
        "SECURITY.md",
        "docs/ANALYSIS.md",
        "docs/HELPERS.md",
        "docs/VAMP.md",
        "docs/STANDALONE.md",
        "docs/COMPATIBILITY.md",
        "CONTRIBUTING.md",
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
    )

    for relative_path in linked_files:
        assert f"]({relative_path})" in readme
        assert (REPO_ROOT / relative_path).is_file()


def test_readme_documents_batch_leadsheet_export():
    readme = (REPO_ROOT / "README.md").read_text()

    assert "Batch leadsheet export" in readme
    assert "~/.venvs/chordifier/bin/python flask/helpers/chordleadsheet_batch.py ~/Music" in readme
    assert "--sharps --transpose 2" in readme
    assert "--chord-track original --repeat-mode chords" in readme
    assert ".chordflask/<name>-chords-<track>.md" in readme
    assert "reused" in readme.lower()


def test_helpers_doc_describes_batch_helper_options_and_exit_codes():
    helpers = (REPO_ROOT / "docs" / "HELPERS.md").read_text()

    assert "chordleadsheet_batch.py" in helpers
    for option in (
        "--chord-track",
        "--rhythm-track",
        "--transpose",
        "--sharps",
        "--unicode",
        "--repeat-mode",
        "--no-metric-chords",
    ):
        assert option in helpers
    assert "non-recursively" in helpers
    assert "Exit code 0" in helpers
    assert "1 means partial" in helpers
    assert "2 means invalid invocation" in helpers


def test_analysis_doc_describes_leadsheet_save_output():
    analysis = (REPO_ROOT / "docs" / "ANALYSIS.md").read_text()

    assert "Saving a leadsheet" in analysis
    assert "**120 BPM · 4/4 · Edited · Flats · Transpose 0**" in analysis
    assert "two complete measures" in analysis
    assert "`text` code block" in analysis
    assert "`-`" in analysis
    assert "Auftakt (Zählzeiten …)" in analysis
    assert "Original/Edited" in analysis
    assert "A-B-A" in analysis
    assert "A-B-C" not in analysis
