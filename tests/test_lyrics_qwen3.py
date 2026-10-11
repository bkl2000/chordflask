"""Offline V2 regression tests; neither Torch nor real model weights required."""
from types import SimpleNamespace

import pytest

from chordflask.lyrics_paths import lyrics_path
from chordflask_lyrics import cli, qwen3, qwen3_worker as worker
from chordflask_lyrics.lrclib import TimedLyricLine
from test_lyrics_cli import make_analysis, FakeClient
from test_flask_app import make_client, load_ready_media


def result_lines():
    return (TimedLyricLine(0.2, "First"), TimedLyricLine(2.0, ""),
            TimedLyricLine(4.2, "Again"), TimedLyricLine(5.0, ""))


def fake_timed(media):
    return result_lines(), {"x_chordflask_language": "English", "x_chordflask_audio": str(media),
                            "x_chordflask_device": "cpu", "x_chordflask_analyzer": "qwen3"}


def test_independent_paths_force_dry_run_and_failure(tmp_path, monkeypatch):
    media = tmp_path / "song.mp3"
    make_analysis(media)
    v1, v2 = lyrics_path(media), lyrics_path(media, "v2")
    v1.write_text("V1 unchanged")
    monkeypatch.setattr(qwen3, "timed_lyrics", fake_timed)
    client = FakeClient()
    assert cli.generate_file(media, client=client, analyzer="qwen3", dry_run=True)[0] == "dry-run"
    assert not v2.exists()
    assert cli.generate_file(media, client=client, analyzer="qwen3")[0] == "written"
    assert not client.calls
    assert v1.read_text() == "V1 unchanged"
    original = v2.read_bytes()
    assert cli.generate_file(media, client=client, analyzer="qwen3")[0] == "skipped"
    assert cli.generate_file(media, client=client, analyzer="qwen3", force=True)[0] == "written"
    assert v2.read_bytes() == original
    monkeypatch.setattr(qwen3, "timed_lyrics", lambda media: (_ for _ in ()).throw(RuntimeError("bad alignment")))
    with pytest.raises(RuntimeError, match="bad alignment"):
        cli.generate_file(media, client=client, analyzer="qwen3", force=True)
    assert v2.read_bytes() == original
    assert v1.read_text() == "V1 unchanged"
    assert not list(tmp_path.glob(".*.tmp"))


def test_symlink_never_written_even_with_force(tmp_path, monkeypatch):
    media = tmp_path / "song.mp3"
    make_analysis(media)
    other = tmp_path / "other.cho"
    other.write_text("preserved")
    lyrics_path(media, "v2").symlink_to(other)
    with pytest.raises(cli.GenerationError, match="symlink"):
        cli.generate_file(media, client=FakeClient(), analyzer="qwen3", force=True)
    assert other.read_text() == "preserved"


@pytest.mark.parametrize("flags", [["--lyrics", "lrc:embedded:lrclib"], ["--tag", "song"]])
def test_v1_sources_rejected_for_qwen(tmp_path, flags, capsys):
    assert cli.run(cli.build_parser().parse_args(["--analyzer", "qwen3", *flags, str(tmp_path)])) == 2
    assert "cannot be combined" in capsys.readouterr().err


def test_text_and_alignment_are_separate_and_language_check_is_alignment_owned():
    class ASR:
        def transcribe(self, **kwargs):
            assert kwargs["language"] is None
            return [SimpleNamespace(text="สวัสดี", language="Thai")]
    assert worker.recognize_text(ASR(), "audio") == ("สวัสดี", "Thai")
    with pytest.raises(ValueError, match="Thai.*not officially supported"):
        worker.check_alignment_language("Thai")
    with pytest.raises(ValueError, match="German"):
        worker.check_alignment_language("German", SimpleNamespace(get_supported_languages=lambda: ["English"]))


def aligner(items):
    return SimpleNamespace(align=lambda **kwargs: [items], get_supported_languages=lambda: ["English"])


def test_alignment_preserves_unicode_repetitions_and_measured_pause():
    items = [SimpleNamespace(text="héllo", start_time=1.0, end_time=1.5),
             SimpleNamespace(text="héllo", start_time=6.0, end_time=6.5)]
    spans = worker.align_text(aligner(items), "audio", "héllo! héllo!", "English", 8)
    assert worker.lines_from_spans(spans) == [(1.0, "héllo!"), (1.5, ""), (6.0, "héllo!"), (6.5, "")]
    with pytest.raises(ValueError, match="complete"):
        worker.align_text(aligner(items[:1]), "audio", "héllo héllo", "English", 8)


@pytest.mark.parametrize("start,end", [(None, 2), (float("nan"), 2), (-1, 2), (2, 1), (1, 1), (1, 9)])
def test_invalid_times_are_rejected(start, end):
    with pytest.raises(ValueError):
        worker.validate_spans([{"text": "text", "start": start, "end": end}], 8)


def test_overlap_and_empty_alignment_rejected():
    with pytest.raises(ValueError, match="overlapping"):
        worker.validate_spans([{"text": "a", "start": 1, "end": 3},
                               {"text": "b", "start": 2, "end": 4}], 8)
    with pytest.raises(ValueError, match="No usable"):
        worker.validate_spans([], 8)


def test_missing_runtime_and_models_are_actionable(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDFLASK_QWEN3_VENV", str(tmp_path))
    with pytest.raises(RuntimeError, match="setup-qwen3-asr"):
        qwen3.timed_lyrics(tmp_path / "song.mp3")
    with pytest.raises(ValueError, match="Missing model"):
        worker.model_paths(tmp_path)


@pytest.mark.parametrize("available,arch,expected", [(False, ["sm_80"], "cpu"),
                                                    (True, ["sm_80"], "cuda:0"),
                                                    (True, ["sm_90"], "cpu")])
def test_cpu_cuda_selection(available, arch, expected):
    torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: available,
                            get_device_capability=lambda _: (8, 0), get_arch_list=lambda: arch),
                            zeros=lambda *a, **k: None, float16="fp16", float32="fp32")
    options = worker.device_options(torch)
    assert options["device_map"] == expected
    assert options["dtype"] == ("fp32" if expected == "cpu" else "fp16")


def test_batch_retry_restores_qwen_analyzer(tmp_path, monkeypatch):
    from chordflask_lyrics import batch
    media = tmp_path / "song.mp3"
    media.write_bytes(b"media")
    calls = []
    def failure(media, **kwargs):
        calls.append(kwargs)
        raise RuntimeError("alignment failed")
    monkeypatch.setattr(cli, "generate_file", failure)
    args = cli.build_parser().parse_args(["--recursive", "--analyzer", "qwen3", "--force", str(tmp_path)])
    assert cli.run(args) == 1
    assert batch.load_failures(tmp_path)["options"]["analyzer"] == "qwen3"
    assert cli.run(cli.build_parser().parse_args(["--retry-failed", str(tmp_path)])) == 1
    assert all(call["analyzer"] == "qwen3" and call["force"] for call in calls)


@pytest.mark.parametrize("versions", [[], ["v1"], ["v2"], ["v1", "v2"]])
def test_gui_version_availability_and_selection(tmp_path, versions):
    _, client = make_client()
    for version in versions:
        lyrics_path(tmp_path / "song.mp3", version).write_text(f"[C]{version}")
    _, response = load_ready_media(client, tmp_path)
    assert response.json["lyrics_versions"] == versions
    assert response.json["song_view_available"] == bool(versions)
    sheet = client.get("/get_song_sheet", headers={"X-Lyrics-Version": "v2"})
    if versions:
        selected = "v2" if "v2" in versions else "v1"
        assert sheet.json["lyrics_version"] == selected
        assert sheet.json["blocks"][0]["runs"][0]["lyric"] == selected
    else:
        assert sheet.status_code == 404


def test_deleted_v2_falls_back_and_export_uses_selected_version(tmp_path):
    _, client = make_client()
    for version in ("v1", "v2"):
        lyrics_path(tmp_path / "song.mp3", version).write_text(f"[C]{version}")
    load_ready_media(client, tmp_path)
    body = {"dirname": str(tmp_path), "filename": "song.mp4", "format": "chordpro", "lyrics_version": "v2"}
    assert "v2" in client.post("/download_chords", json=body).text
    lyrics_path(tmp_path / "song.mp3", "v2").unlink()
    assert client.get("/get_song_sheet", headers={"X-Lyrics-Version": "v2"}).json["lyrics_version"] == "v1"
    assert "v1" in client.post("/download_chords", json=body).text
    assert client.get("/get_song_sheet", headers={"X-Lyrics-Media": "/previous/song.mp3"}).status_code == 409


def test_atomic_no_force_does_not_replace_concurrent_file(tmp_path):
    destination = tmp_path / "song.v2.cho"
    destination.write_text("concurrent user edit")
    with pytest.raises(FileExistsError):
        cli._write_atomic(destination, "new", replace_existing=False)
    assert destination.read_text() == "concurrent user edit"
    assert not list(tmp_path.glob(".*.tmp"))


def test_original_audio_and_valid_existing_vocals(tmp_path, monkeypatch):
    from chordflask_demucs import storage
    from chordflask_base import ChordTrackRepository
    media = tmp_path / "song.mp3"
    monkeypatch.setattr(storage, "classify", lambda path: storage.DemucsStatus(storage.STALE))
    assert qwen3.audio_input(media) == media
    monkeypatch.setattr(storage, "classify", lambda path: storage.DemucsStatus(storage.CURRENT))
    monkeypatch.setattr(ChordTrackRepository, "load", lambda self, path: SimpleNamespace(
        audio_track_data=lambda track: {"tracks": {"vocals": {"path": ".chordflask/stems/vocals.flac"}}}))
    assert qwen3.audio_input(media) == tmp_path / ".chordflask/stems/vocals.flac"


def test_worker_bridge_validates_results_and_reports_input_language(tmp_path, monkeypatch):
    import json
    import subprocess
    runtime = tmp_path / "runtime"
    (runtime / "bin").mkdir(parents=True)
    (runtime / "bin/python").touch()
    monkeypatch.setenv("CHORDFLASK_QWEN3_VENV", str(runtime))
    media = tmp_path / "song.mp3"
    monkeypatch.setattr(qwen3, "audio_input", lambda path: path)
    result = {"spans": [{"text": "Hello!", "start": 1, "end": 2}], "duration": 8,
              "device": "cpu", "languages": ["English"]}
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, json.dumps(result), "")
    monkeypatch.setattr(qwen3.subprocess, "run", run)
    lines, provenance = qwen3.timed_lyrics(media)
    assert lines == (TimedLyricLine(1, "Hello!"), TimedLyricLine(2, ""))
    assert provenance["x_chordflask_language"] == "English"
    assert calls[0][1]["env"]["HF_HUB_OFFLINE"] == "1"
    result["spans"] = []
    with pytest.raises(RuntimeError, match="Invalid Qwen3 result"):
        qwen3.timed_lyrics(media)


def test_gui_switch_and_late_responses_preserve_playback():
    import shutil
    import subprocess
    from test_flask_app import javascript_function

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable")
    _, client = make_client()
    body = client.get("/").text
    declarations = body[body.index("    let lyricsVersionSelect ="):body.index("    let songViewAvailable =")]
    functions = "\n".join(javascript_function(body, name) for name in (
        "loadSongSheet", "refreshSongSheetLabels", "updateSongViewControl",
    ))
    script = r'''
const assert = require('node:assert/strict');
const handlers = {};
const select = { value: '', hidden: true, children: [],
  replaceChildren() { this.children = []; }, appendChild(o) { this.children.push(o); },
  addEventListener(name, callback) { handlers[name] = callback; } };
const document = { getElementById: () => select, createElement: () => ({}) };
const window = { addEventListener() {} };
const desktopSongView = { matches: true };
const video = { currentTime: 42.5, paused: false };
let songSheetCache = null, songSheetRequestInFlight = false, songViewGeneration = 0;
let songViewMode = 'song';
let songViewAvailable = true, editMode = false, editRequestInFlight = false;
const songViewSwitch = { hidden: true };
const gridViewButton = { setAttribute() {} }, songViewButton = { setAttribute() {} };
const songSheet = { replaceChildren() {} };
const pending = [];
function fetch(url, options) { return new Promise(resolve => pending.push({resolve, options})); }
let rendered = null;
function renderSongSheet(data) { rendered = data; }
function renderSongError(error) { throw new Error(error); }
function appendSongText() {}
'''
    script += declarations + "\n" + functions
    script += r'''
(async () => {
  updateLyricsVersions([]); assert.equal(select.hidden, true);
  updateLyricsVersions(['v1']); assert.equal(select.value, 'v1'); assert.equal(select.hidden, true);
  updateLyricsVersions(['v2']); assert.equal(select.value, 'v2'); assert.equal(select.hidden, true);
  updateLyricsVersions(['v1', 'v2']); assert.equal(select.hidden, false);
  songViewMode = 'grid'; updateSongViewControl(); assert.equal(select.hidden, true);
  updateLyricsVersions(['v1', 'v2']); assert.equal(select.hidden, true);
  assert.equal(select.value, 'v2');
  songViewMode = 'song'; updateSongViewControl(); assert.equal(select.hidden, false);
  assert.equal(select.value, 'v2');
  lyricsMedia = '/song one.mp3'; lyricsVersion = 'v1';
  loadSongSheet();
  select.value = 'v2'; handlers.change();
  assert.equal(pending.length, 2);
  assert.equal(pending[1].options.headers['X-Lyrics-Version'], 'v2');
  const settle = async (request, version, text, versions=['v1','v2']) => {
    request.resolve({ok:true,json:async()=>({lyrics_versions:versions,lyrics_version:version,text})});
    await new Promise(resolve=>setImmediate(resolve));
  };
  await settle(pending[0], 'v1', 'stale version'); assert.equal(rendered, null);
  await settle(pending[1], 'v2', 'current version'); assert.equal(rendered.text, 'current version');
  assert.equal(video.currentTime, 42.5); assert.equal(video.paused, false);
  refreshSongSheetLabels();
  // The actual song-load function invalidates this generation at request start.
  songViewGeneration += 1; songSheetRequestInFlight = false;
  lyricsMedia = '/new song.mp3'; refreshSongSheetLabels();
  await settle(pending[2], 'v2', 'stale song'); assert.equal(rendered.text, 'current version');
  await settle(pending[3], 'v1', 'fallback after deletion', ['v1']);
  assert.equal(lyricsVersion, 'v1'); assert.equal(select.hidden, true);
  assert.equal(rendered.text, 'fallback after deletion');
  desktopSongView.matches = false; updateLyricsVersions(['v1','v2']); assert.equal(select.hidden,true);
  updateSongViewControl(); assert.equal(select.hidden, true);
  assert.equal(video.currentTime, 42.5); assert.equal(video.paused, false);
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_retry_explicit_analyzer_mismatch_is_rejected(tmp_path, monkeypatch, capsys):
    from chordflask_lyrics import batch
    media = tmp_path / "song.mp3"
    media.touch()
    args = cli.build_parser().parse_args(["--analyzer", "qwen3", str(tmp_path)])
    batch.save_failures(tmp_path, batch.generation_options(args), [{"path": str(media), "reason": "failed"}])
    assert cli.run(cli.build_parser().parse_args(["--retry-failed", "--analyzer", "v1", str(tmp_path)])) == 2
    assert "saved analyzer" in capsys.readouterr().err


def test_timeout_cleans_parent_owned_work_directory(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setenv("CHORDFLASK_QWEN3_VENV", str(tmp_path))
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin/python").touch()
    monkeypatch.setattr(qwen3, "audio_input", lambda path: path)
    work_directories = []
    def timeout(command, **kwargs):
        from pathlib import Path
        work = Path(command[command.index("--work-directory") + 1])
        work_directories.append(work)
        (work / "decoded.wav").write_bytes(b"partial audio")
        raise subprocess.TimeoutExpired(command, 1)
    monkeypatch.setattr(qwen3.subprocess, "run", timeout)
    with pytest.raises(RuntimeError, match="timed out"):
        qwen3.timed_lyrics(tmp_path / "song.mp3")
    assert all(not directory.exists() for directory in work_directories)


@pytest.mark.parametrize("results", [[], [SimpleNamespace(text=None, language="English")],
                                     [SimpleNamespace(text="hello", language=None)]])
def test_incomplete_asr_results_fail(results):
    with pytest.raises(ValueError, match="ASR"):
        worker.recognize_text(SimpleNamespace(transcribe=lambda **kwargs: results), "audio")


def test_gui_unicode_media_identity_and_invalid_version(tmp_path):
    from urllib.parse import quote
    _, client = make_client()
    media, _ = load_ready_media(client, tmp_path, name="เพลง.mp3")
    lyrics_path(media, "v2").write_text("[C]Unicode")
    response = client.get("/get_song_sheet", headers={"X-Lyrics-Version": "v2",
                                                      "X-Lyrics-Media": quote(str(media))})
    assert response.status_code == 200
    assert client.get("/get_song_sheet", headers={"X-Lyrics-Version": "v3"}).status_code == 400


def test_model_check_rejects_missing_weight_shards(tmp_path):
    import json
    for name in (worker.ASR_MODEL, worker.ALIGN_MODEL):
        model = tmp_path / name
        model.mkdir()
        (model / "config.json").write_text("{}")
        (model / "model-00001.safetensors").write_bytes(b"weights")
    assert len(worker.model_paths(tmp_path)) == 2
    (tmp_path / worker.ASR_MODEL / "model.safetensors.index.json").write_text(json.dumps(
        {"weight_map": {"first": "model-00001.safetensors", "missing": "model-00002.safetensors"}}))
    with pytest.raises(ValueError, match="Incomplete"):
        worker.model_paths(tmp_path)


def test_chunk_boundaries_keep_independent_transcripts_readable():
    spans = [{"text": "last word", "start": 29, "end": 30},
             {"text": "next word", "start": 30, "end": 31, "break_before": True}]
    assert worker.lines_from_spans(spans) == [(29, "last word"), (30, ""), (30, "next word"), (31, "")]


def test_corrected_point_word_preserves_text_without_inventing_duration():
    items = [SimpleNamespace(text="This", start_time=0.0, end_time=0.16),
             SimpleNamespace(text="is", start_time=0.16, end_time=0.32),
             SimpleNamespace(text="a", start_time=0.32, end_time=0.32),
             SimpleNamespace(text="test", start_time=0.32, end_time=0.64)]
    spans = worker.align_text(aligner(items), "audio", "This is a test.", "English", 1)
    assert spans[2] == {"text": "a ", "start": 0.32, "end": 0.32}
    assert worker.lines_from_spans(spans) == [(0.0, "This is a test."), (0.64, "")]
    with pytest.raises(ValueError, match="no usable duration"):
        worker.validate_spans([{"text": "word", "start": 0.32, "end": 0.32}], 1)


@pytest.mark.parametrize("collapsed", [False, True])
def test_infer_leaves_official_correction_in_place(tmp_path, monkeypatch, collapsed):
    """Mock inference with recorded upstream correction, including a point word.

    Raw [24800, 24480, 24960, 25600] is corrected by qwen-asr 0.0.6 to
    [24800, 24800, 24960, 25600]. Normal tests do not import the ML runtime.
    """
    import sys
    processor = SimpleNamespace()
    calls = []
    raw = [24800, 24480, 24960, 25600]
    def official_correction(values):
        assert values == raw
        calls.append(values)
        return [24800] * 4 if collapsed else [24800, 24800, 24960, 25600]
    processor.fix_timestamp = official_correction
    class FakeAligner:
        aligner_processor = processor
        def get_supported_languages(self):
            return ["English"]
        def align(self, **kwargs):
            values = self.aligner_processor.fix_timestamp(raw)
            return [[SimpleNamespace(text=text, start_time=values[index * 2] / 1000,
                                     end_time=values[index * 2 + 1] / 1000)
                     for index, text in enumerate(["Your", "daddy"])]]
    class Sound:
        samplerate = 16000
        def __len__(self):
            return (210 if collapsed else 30) * self.samplerate
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, count, **kwargs):
            return [0] * count
        def seek(self, start):
            pass
    monkeypatch.setitem(sys.modules, "soundfile", SimpleNamespace(SoundFile=lambda path: Sound()))
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(float32="fp32", cuda=SimpleNamespace(is_available=lambda: False)))
    transcripts = iter([""] * 6 + ["Your daddy"] if collapsed else ["Your daddy"])
    monkeypatch.setitem(sys.modules, "qwen_asr", SimpleNamespace(
        Qwen3ASRModel=SimpleNamespace(from_pretrained=lambda *args, **kwargs: SimpleNamespace(
            transcribe=lambda **kwargs: [SimpleNamespace(text=next(transcripts), language="English")])),
        Qwen3ForcedAligner=SimpleNamespace(from_pretrained=lambda *args, **kwargs: FakeAligner())))
    monkeypatch.setattr(worker, "model_paths", lambda root: [tmp_path / "asr", tmp_path / "aligner"])
    monkeypatch.setattr(worker, "require_package_version", lambda: None)
    monkeypatch.setattr(worker.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    if collapsed:
        with pytest.raises(worker.AlignmentDurationError, match="no usable duration") as failure:
            worker.infer(tmp_path / "clip.wav", tmp_path)
        assert (failure.value.start, failure.value.end) == (180, 210)
        assert calls == [raw]
        assert processor.fix_timestamp is official_correction
        return
    result = worker.infer(tmp_path / "clip.wav", tmp_path)
    assert calls == [raw]
    assert processor.fix_timestamp is official_correction
    assert result["spans"][0]["start"] == result["spans"][0]["end"] == 24.8
    assert worker.lines_from_spans(result["spans"]) == [(24.8, "Your daddy"), (25.6, "")]


@pytest.mark.parametrize("known", [False, True])
def test_worker_failure_payload_preserves_stderr(tmp_path, monkeypatch, capsys, known):
    import json
    import sys
    error = (worker.AlignmentDurationError("Alignment has no usable duration", 180, 210)
             if known else ValueError("Invalid, overlapping or out-of-audio alignment timestamps"))
    def fail(*args):
        raise error
    monkeypatch.setattr(worker, "infer", fail)
    monkeypatch.setattr(sys, "argv", ["worker", "--models", str(tmp_path), "--audio", "song.mp3"])
    assert worker.main() == 1
    output = capsys.readouterr()
    assert str(error) in output.err
    if known:
        assert json.loads(output.out) == {"error": "alignment_no_duration", "start": 180, "end": 210}
    else:
        assert output.out == ""


@pytest.mark.parametrize("batch_mode", [False, True])
@pytest.mark.parametrize("existing_v2", [False, True])
def test_known_alignment_cli_failure_is_short_and_preserves_files(
        tmp_path, monkeypatch, capsys, batch_mode, existing_v2):
    import json
    import subprocess
    from chordflask_lyrics import batch
    media = tmp_path / "a.mp3"
    make_analysis(media)
    v1, v2 = lyrics_path(media), lyrics_path(media, "v2")
    v1.write_text("V1 unchanged")
    if existing_v2:
        v2.write_text("V2 unchanged")
    runtime = tmp_path / ".runtime"
    (runtime / "bin").mkdir(parents=True)
    (runtime / "bin/python").touch()
    monkeypatch.setenv("CHORDFLASK_QWEN3_VENV", str(runtime))
    monkeypatch.setattr(qwen3, "audio_input", lambda path: path)
    diagnostic = "Transformers diagnostic\nAlignmentDurationError: Alignment failed at 180.0s: Alignment has no usable duration"
    def run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, json.dumps(
            {"error": "alignment_no_duration", "start": 180, "end": 210}), diagnostic)
    monkeypatch.setattr(qwen3.subprocess, "run", run)
    if batch_mode:
        other = tmp_path / "b.mp3"
        make_analysis(other)
        timed = qwen3.timed_lyrics
        monkeypatch.setattr(qwen3, "timed_lyrics", lambda path: fake_timed(path) if path == other else timed(path))
    flags = ["--recursive"] if batch_mode else []
    args = cli.build_parser().parse_args([
        "--analyzer", "qwen3", "--force", *flags, str(tmp_path if batch_mode else media)])
    assert cli.run(args, client=FakeClient()) == 1
    output = capsys.readouterr()
    assert "Qwen3 could not reliably align the vocals at 180–210 s" in output.err
    assert "No V2 file was written; existing lyrics remain unchanged." in output.err
    assert "Transformers diagnostic" not in output.err
    assert "AlignmentDurationError" not in output.err
    assert media.read_bytes() == b"media"
    assert v1.read_text() == "V1 unchanged"
    assert v2.read_text() == "V2 unchanged" if existing_v2 else not v2.exists()
    if batch_mode:
        assert lyrics_path(other, "v2").exists()
        state = batch.load_failures(tmp_path)
        assert state["options"]["analyzer"] == "qwen3"
        assert state["failed"] == [{"path": str(media), "reason": "Qwen3 failed: " + diagnostic}]
        assert "OK: 1\nFAILED: 1" in output.out
    with pytest.raises(qwen3.Qwen3AlignmentError) as failure:
        qwen3.timed_lyrics(media)
    assert diagnostic in str(failure.value.__cause__)


@pytest.mark.parametrize("payload", [
    "", '{"error": "other", "start": 180, "end": 210}',
    '{"error": "alignment_no_duration", "start": true, "end": 210}',
    '{"error": "alignment_no_duration", "start": 210, "end": 180}',
    '{"error": "alignment_no_duration"}',
])
def test_other_worker_failures_keep_technical_error(tmp_path, monkeypatch, payload):
    import subprocess
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin/python").touch()
    monkeypatch.setenv("CHORDFLASK_QWEN3_VENV", str(tmp_path))
    monkeypatch.setattr(qwen3, "audio_input", lambda path: path)
    monkeypatch.setattr(qwen3.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 1, payload, "CUDA out of memory"))
    with pytest.raises(RuntimeError, match="Qwen3 failed: CUDA out of memory") as failure:
        qwen3.timed_lyrics(tmp_path / "song.mp3")
    assert not isinstance(failure.value, qwen3.Qwen3AlignmentError)


def test_point_only_lyric_row_is_rejected_even_beside_valid_words():
    spans = [{"text": "valid ", "start": 0, "end": 1},
             {"text": "point", "start": 5, "end": 5}]
    worker.validate_spans(spans, 6)
    with pytest.raises(ValueError, match="row has no usable duration"):
        worker.lines_from_spans(spans)


@pytest.mark.parametrize("spans", [
    [{"text": "a", "start": 1, "end": 2}, {"text": "b", "start": 0.5, "end": 1}],
    [{"text": "a", "start": 1, "end": 2}, {"text": "b", "start": 1.5, "end": 1.5}],
    [{"text": "a", "start": 1, "end": 2}, {"text": "b", "start": 2.5, "end": 2}],
])
def test_corrected_output_still_rejects_real_backward_boundaries(spans):
    with pytest.raises(ValueError, match="Invalid"):
        worker.validate_spans(spans, 6)
