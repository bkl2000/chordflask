import pytest

from chordflask_demucs.audio import AudioFacts
from chordflask_demucs.runtime import RuntimeInfo
from chordflask_demucs.validation import (
    DemucsValidationError,
    build_audio_track_set,
    max_tail_delta_samples,
    pipeline_fingerprint,
    validate_normalized_stems,
    validate_raw_stems,
)


def _facts(sample_count=44100, *, format="wav", codec="pcm_s16le"):
    return AudioFacts(format, codec, 44100, 2, sample_count, sample_count / 44100)


def _stems(sample_count=44100):
    return {stem: _facts(sample_count) for stem in ("bass", "drums", "other", "vocals")}


def test_small_tail_differences_are_recorded_without_time_shift():
    source = _facts()
    stems = _stems(source.sample_count - 100)

    adjustments = validate_raw_stems(source, stems)

    assert max_tail_delta_samples() == 2205
    assert adjustments == {stem: 100 for stem in stems}


def test_large_or_nonzero_start_difference_is_rejected():
    source = _facts()
    stems = _stems(source.sample_count - 2206)
    with pytest.raises(DemucsValidationError, match="maximum allowed"):
        validate_raw_stems(source, stems)

    stems = _stems()
    stems["vocals"] = AudioFacts("wav", "pcm_s16le", 44100, 2, 44100, 1.0, start_time=0.1)
    with pytest.raises(DemucsValidationError, match="non-zero start"):
        validate_raw_stems(source, stems)


def test_normalized_stems_must_be_exactly_sample_aligned():
    source = _facts()
    stems = {stem: _facts(format="flac", codec="flac") for stem in ("bass", "drums", "other", "vocals")}
    validate_normalized_stems(source, stems)

    stems["other"] = _facts(44099, format="flac", codec="flac")
    with pytest.raises(DemucsValidationError, match="sample-aligned"):
        validate_normalized_stems(source, stems)


def test_audio_set_contains_source_and_timeline_metadata(tmp_path):
    runtime = RuntimeInfo(tmp_path / "venv", tmp_path / "python", "4.0.1", "2.6.0")
    source = _facts()
    stems = {stem: _facts(format="flac", codec="flac") for stem in ("bass", "drums", "other", "vocals")}
    paths = {stem: tmp_path / f"{stem}.flac" for stem in stems}

    result = build_audio_track_set(
        source=source,
        source_hash="a" * 64,
        source_size=10,
        source_timeline={"available": False},
        runtime=runtime,
        device="cpu",
        stem_paths=paths,
        stem_facts=stems,
        stem_hashes={stem: f"{index + 1:064x}" for index, stem in enumerate(stems)},
        stem_sizes={stem: 100 for stem in stems},
        tail_adjustments={stem: 0 for stem in stems},
        relative_to=tmp_path,
    )

    assert result["provider"] == "demucs"
    assert set(result["tracks"]) == {"bass", "drums", "other", "vocals"}
    assert result["metadata"]["source_timeline"] == {"available": False}
    assert result["metadata"]["sync"]["start_sample"] == 0
    assert result["metadata"]["pipeline_fingerprint"] == pipeline_fingerprint(runtime, device="cpu")
