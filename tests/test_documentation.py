from pathlib import Path
import re


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

    assert "## Download" in readme
    assert "flask/dist/chordflask-debian13-x86_64-py3.12-v0.6.3.tar.gz" in readme
    assert "docs/STANDALONE.md" in readme
    for command in (
        "tar -xzf chordflask-debian13-x86_64-py3.12-v0.6.3.tar.gz",
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
        "docs/MAINTENANCE.md",
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
    assert "scripts/chordflask-export ~/Music" in readme
    assert "--sharps --transpose 2" in readme
    assert "--chord-track original --repeat-mode chords" in readme
    assert ".chordflask/<name>-chords-<track>.md" in readme
    assert "one ZIP" in readme
    assert "--format markdown" in readme
    assert "--format pdf" in readme
    assert "reused" in readme.lower()


def test_helpers_doc_describes_export_options_and_exit_codes():
    helpers = (REPO_ROOT / "docs" / "HELPERS.md").read_text()

    assert "export_cli.py" in helpers
    for option in (
        "--format",
        "--chord-track",
        "--rhythm-track",
        "--transpose",
        "--sharps",
        "--unicode",
        "--repeat-mode",
        "--no-metric-chords",
    ):
        assert option in helpers
    assert "non-recursive" in helpers
    assert "Exit code 0" in helpers
    assert "1 means partial" in helpers
    assert "2 means invalid invocation" in helpers
    assert "matching" in helpers
    assert ".pdf" in helpers


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
    assert "one ZIP" in analysis
    assert "four framed measures" in analysis
    assert "15 rows per page" in analysis


def test_helpers_doc_filenames_exist():
    helpers = (REPO_ROOT / "docs" / "HELPERS.md").read_text()
    listing = helpers.split("## Production Boundary", 1)[0]

    found = []
    for token in re.findall(r"`([^`]+)`", listing):
        if re.fullmatch(r"[A-Za-z0-9_]+\.py", token):
            found.append(token)

    assert found, "HELPERS.md lists no bare .py helper filenames"
    for name in found:
        assert (REPO_ROOT / "flask" / "helpers" / name).is_file(), name


def test_readme_documents_command_line_tools_block():
    readme = (REPO_ROOT / "README.md").read_text()

    assert "### Command-line tools" in readme
    assert "scripts/chordflask.sh" in readme
    assert "scripts/chordflask-analyze song.mp4" in readme
    assert "scripts/chordflask-analyze /music/videos" in readme
    assert "scripts/chordflask-export" in readme
    assert "scripts/chordflask-maintain doctor" in readme
    assert "Chordino is the built-in, default" in readme


def test_readme_documents_responsive_support_and_lan_usage():
    readme = (REPO_ROOT / "README.md").read_text()
    text = re.sub(r"\s+", " ", readme)

    assert (
        "Responsive layouts for desktop, tablet and smartphone are included. "
        "Mobile support is functional but still undergoing broader real-device "
        "testing." in text
    )
    assert "CHORDIFIER_MEDIA_ROOTS" in readme
    assert "--listen" in readme
    assert "--port" in readme
    assert "--listen 0.0.0.0 --port 5000" in text
    assert "platform path separator" in readme
    assert "not automatically exposed" in readme


def test_analysis_doc_documents_command_line_analysis():
    analysis = (REPO_ROOT / "docs" / "ANALYSIS.md").read_text()

    assert "## Command-line analysis" in analysis
    assert "scripts/chordflask-analyze song.mp4" in analysis
    assert "Chordino is the default." in analysis
    assert "--dry-run" in analysis
    assert "--replace" in analysis


def test_public_docs_describe_btc_as_optional():
    readme = (REPO_ROOT / "README.md").read_text()
    analysis = (REPO_ROOT / "docs" / "ANALYSIS.md").read_text()

    # BTC is documented as an explicit, optional analyzer, not the default.
    assert "make setup-btc BTC_ACKNOWLEDGE_WEIGHTS=1" in readme
    assert "make btc-check" in readme
    assert "scripts/chordflask-analyze --analyzer btc song.mp4" in readme
    assert "Chordino is the default." in analysis
    assert "Optional BTC analyzer" in analysis
    assert "chordflask-analyze-btc" not in readme
    assert "chordflask-analyze-btc" not in analysis


def test_maintenance_doc_documents_real_subcommands():
    maintenance = (REPO_ROOT / "docs" / "MAINTENANCE.md").read_text()

    for sub in ("storage report", "storage cleanup", "migrate-schema", "validate", "doctor"):
        assert sub in maintenance
    assert "read-only" in maintenance
    assert "modifies files" in maintenance.lower()


def test_user_docs_do_not_reference_deleted_scripts():
    deleted = (
        "chordbatch.py",
        "chordbatch_mp.py",
        "create_sheet_pdf.py",
        "chordflask_storage.py",
        "install_vamp_plugins.sh",
        "compare_chord_json.py",
        "getscale.py",
        "analyze_pitch.py",
        "process_audio.py",
        "liverecord.py",
        "mp4player_tk.py",
        "romanize.py",
        "webm2mp4",
        "youtube_donwload",
        "install_codex.sh",
        "start_agents.sh",
        "analysis_storage.py",
    )
    user_docs = (
        REPO_ROOT / "README.md",
        REPO_ROOT / "docs" / "ANALYSIS.md",
        REPO_ROOT / "docs" / "MAINTENANCE.md",
        REPO_ROOT / "docs" / "HELPERS.md",
        REPO_ROOT / "docs" / "VAMP.md",
        REPO_ROOT / "docs" / "COMPATIBILITY.md",
    )
    for doc in user_docs:
        text = doc.read_text()
        for name in deleted:
            assert name not in text, f"{doc.name} references deleted {name}"


def test_no_primary_recommendation_for_backend_commands():
    for doc in (
        REPO_ROOT / "README.md",
        REPO_ROOT / "docs" / "ANALYSIS.md",
        REPO_ROOT / "docs" / "MAINTENANCE.md",
    ):
        text = doc.read_text()
        assert "chordflask-analyze-btc" not in text, doc
        assert "chordflask-migrate-schema" not in text, doc
