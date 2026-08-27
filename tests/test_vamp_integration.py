import os
import platform
import sys

import numpy as np
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = REPO_ROOT / "vendor" / "vamp" / "linux-x86_64"
PLUGIN_DIR = Path(os.environ.get("CHORDIFIER_TEST_VAMP_PATH", VENDOR_DIR))

from chordflask.chordflask_config import ANALYSIS_SAMPLE_RATE


def _unavailable(message):
    if os.environ.get("CHORDIFIER_REQUIRE_VAMP", "").lower() in {"1", "true", "yes"}:
        pytest.fail(message)
    pytest.skip(message)


@pytest.fixture(scope="module", autouse=True)
def _set_vamp_path():
    previous = os.environ.get("VAMP_PATH")
    os.environ["VAMP_PATH"] = str(PLUGIN_DIR)
    yield
    if previous is None:
        os.environ.pop("VAMP_PATH", None)
    else:
        os.environ["VAMP_PATH"] = previous


@pytest.fixture(scope="module")
def plugins_exist():
    if sys.platform != "linux" or platform.machine() not in {"x86_64", "AMD64"}:
        _unavailable("Reviewed Vamp plugin binaries require Linux x86_64")
    nnls = PLUGIN_DIR / "nnls-chroma.so"
    qm = PLUGIN_DIR / "qm-vamp-plugins.so"
    if not nnls.exists() or not qm.exists():
        _unavailable(
            "Vamp plugins not found in {}; set CHORDIFIER_TEST_VAMP_PATH to "
            "their directory or run flask/install_vamp.sh --dest {} "
            "first".format(
                PLUGIN_DIR, VENDOR_DIR
            )
        )


@pytest.fixture(scope="module")
def vamp_available():
    try:
        import vamp
    except (ImportError, OSError) as error:
        _unavailable("vamp package is unavailable: {}".format(error))
    return vamp


REQUIRED_PLUGINS = {
    "nnls-chroma:chordino",
    "qm-vamp-plugins:qm-barbeattracker",
}


def test_plugins_are_discovered(plugins_exist, vamp_available):
    vamp = vamp_available
    available = set(vamp.list_plugins())
    missing = REQUIRED_PLUGINS - available
    assert not missing, (
        "Required Vamp plugins not discovered: {}. "
        "VAMP_PATH={}".format(", ".join(sorted(missing)), PLUGIN_DIR)
    )


def test_plugins_have_expected_outputs(plugins_exist, vamp_available):
    vamp = vamp_available
    chordino_outputs = vamp.get_outputs_of("nnls-chroma:chordino")
    assert isinstance(chordino_outputs, list)
    assert "simplechord" in chordino_outputs

    beat_outputs = vamp.get_outputs_of("qm-vamp-plugins:qm-barbeattracker")
    assert isinstance(beat_outputs, list)
    assert "beats" in beat_outputs
    assert "beatcounts" in beat_outputs


def test_vamp_path_env_is_respected(plugins_exist, vamp_available):
    assert os.environ.get("VAMP_PATH") == str(PLUGIN_DIR)
    vamp = vamp_available
    available = set(vamp.list_plugins())
    missing = REQUIRED_PLUGINS - available
    assert not missing, (
        "Plugins not discovered via VAMP_PATH={}: missing {}".format(
            PLUGIN_DIR, ", ".join(sorted(missing))
        )
    )


def test_chordino_processes_synthetic_c_major_audio(
    plugins_exist, vamp_available
):
    sample_rate = ANALYSIS_SAMPLE_RATE
    time = np.arange(sample_rate * 6, dtype=np.float32) / sample_rate
    audio = sum(
        np.sin(2 * np.pi * frequency * time)
        for frequency in (261.6256, 329.6276, 391.9954)
    ).astype(np.float32) / 3

    result = vamp_available.collect(
        audio,
        sample_rate,
        "nnls-chroma:chordino",
        output="simplechord",
    )
    labels = {entry["label"] for entry in result["list"]}
    assert "C" in labels, result


def test_beat_tracker_processes_synthetic_120_bpm_clicks(
    plugins_exist, vamp_available
):
    sample_rate = ANALYSIS_SAMPLE_RATE
    audio = np.zeros(sample_rate * 8, dtype=np.float32)
    for second in np.arange(0, 8, 0.5):
        start = int(second * sample_rate)
        length = min(400, len(audio) - start)
        audio[start : start + length] += np.hanning(length).astype(np.float32)

    result = vamp_available.collect(
        audio,
        sample_rate,
        "qm-vamp-plugins:qm-barbeattracker",
        output="beatcounts",
        parameters={"bpb": 4},
    )
    timestamps = np.array(
        [float(entry["timestamp"]) for entry in result["list"]], dtype=float
    )
    assert len(timestamps) >= 10, result
    assert np.median(np.diff(timestamps)) == pytest.approx(0.5, abs=0.06)
    beat_numbers = {int(entry["label"]) for entry in result["list"]}
    assert beat_numbers == {1, 2, 3, 4}


# ── vamp_runtime guards ────────────────────────────────────────────


def test_vamp_runtime_raises_without_required_plugins(monkeypatch):
    from chordflask.vamp_runtime import require_vamp_plugins, REQUIRED_PLUGINS

    monkeypatch.setattr("vamp.list_plugins", lambda: [])

    try:
        require_vamp_plugins()
    except RuntimeError as error:
        assert "Required Vamp plugins not found" in str(error)
        for plugin in REQUIRED_PLUGINS:
            assert plugin in str(error)
    else:
        raise AssertionError("should raise RuntimeError")


def test_vamp_runtime_succeeds_with_plugins_present(monkeypatch):
    from chordflask.vamp_runtime import require_vamp_plugins

    monkeypatch.setattr("vamp.list_plugins", lambda: list({
        "nnls-chroma:chordino",
        "qm-vamp-plugins:qm-barbeattracker",
    }))

    result = require_vamp_plugins()
    assert "nnls-chroma:chordino" in result


def test_vamp_runtime_reports_missing_plugins_clearly(monkeypatch):
    from chordflask.vamp_runtime import require_vamp_plugins

    monkeypatch.setattr("vamp.list_plugins", lambda: ["nnls-chroma:chordino"])

    try:
        require_vamp_plugins()
    except RuntimeError as error:
        assert "qm-vamp-plugins:qm-barbeattracker" in str(error)
        assert "make plugins" in str(error)
    else:
        raise AssertionError("should raise RuntimeError")


def test_madmom_analysis_still_preflights_beat_tracker(monkeypatch):
    import chordflask.audio_analyzer as audio_analyzer
    import chordflask.vamp_runtime as vamp_runtime

    monkeypatch.setattr(audio_analyzer, "require_system_ffmpeg", lambda: "/usr/bin/ffmpeg")

    def missing_plugins():
        raise RuntimeError("missing qm-vamp-plugins:qm-barbeattracker")

    monkeypatch.setattr(vamp_runtime, "require_vamp_plugins", missing_plugins)

    try:
        audio_analyzer.AudioAnalyzer().analyze("not-opened.mp3", use_madmom=True)
    except RuntimeError as error:
        assert "qm-vamp-plugins:qm-barbeattracker" in str(error)
    else:
        raise AssertionError("madmom analysis must preflight its Vamp beat tracker")
