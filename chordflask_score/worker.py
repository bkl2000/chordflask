"""Heavy Score operations, executed exclusively inside the optional runtime."""

import argparse
from contextlib import contextmanager
import importlib.metadata
import json
from pathlib import Path
import sys
import warnings

from .notation import NoteTimeError
from .runtime import check_python, code_identity
from .timing import BeatGrid


@contextmanager
def _ignore_known_upstream_warnings():
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"pkg_resources is deprecated as an API\..*",
            category=DeprecationWarning,
        )
        warnings.filterwarnings(
            "ignore",
            message=r"torch\.utils\.checkpoint: the use_reentrant parameter should be passed explicitly\..*",
            category=UserWarning,
        )
        yield


def check_runtime():
    check_python(sys.version_info)
    import torch
    import torchaudio
    import verovio
    import music21
    from importlib.resources import files
    with _ignore_known_upstream_warnings():
        import pkg_resources  # noqa: F401 -- the optional upstream console command needs it
        from transkun.transcribe import readAudio
    from chordflask_demucs.audio import hash_file

    del readAudio
    root = files("transkun") / "pretrained"
    weight, conf = Path(str(root / "2.0.pt")), Path(str(root / "2.0.conf"))
    if not weight.is_file() or not conf.is_file():
        raise RuntimeError("Packaged Transkun weights/configuration missing; rerun make setup-score")
    toolkit = verovio.toolkit()
    return {"python": sys.version.split()[0], "torch": torch.__version__,
            "torchaudio": torchaudio.__version__, "transkun": importlib.metadata.version("transkun"),
            "music21": music21.__version__, "verovio": toolkit.getVersion(),
            "weights": hash_file(weight), "configuration": hash_file(conf),
            "code": code_identity(), "cuda": bool(torch.cuda.is_available())}


def transcribe(audio, midi, device):
    # Use upstream APIs so pre-MIDI event seconds retain their full precision.
    from importlib.resources import files
    import moduleconf
    with _ignore_known_upstream_warnings():
        from transkun.transcribe import readAudio
    from transkun.Data import writeMidi
    import torch

    torch.set_num_threads(2)
    root = files("transkun") / "pretrained"
    configuration = moduleconf.parseFromFile(str(root / "2.0.conf"))["Model"]
    model = configuration.module.TransKun(conf=configuration.config).to(device)
    checkpoint = torch.load(str(root / "2.0.pt"), map_location=device)
    state = checkpoint.get("best_state_dict", checkpoint.get("state_dict"))
    model.load_state_dict(state, strict=False)  # same upstream loading contract
    model.eval()
    fs, samples = readAudio(str(audio))
    if fs != model.fs:
        import soxr
        samples = soxr.resample(samples, fs, model.fs)
    with torch.no_grad(), _ignore_known_upstream_warnings():
        events = model.transcribe(torch.from_numpy(samples).to(device), discardSecondHalf=False)
    payload = original_events(events)
    writeMidi(events).write(str(midi))
    # Validate the final serialized MIDI too, without using its rounded times for notation.
    read_midi(midi)
    return payload


def original_events(events):
    from .notation import validate_notes
    payload = {"notes": [], "controllers": []}
    for event in events:
        if event.pitch > 0:
            payload["notes"].append({"pitch": int(event.pitch), "velocity": int(event.velocity),
                                     "start": float(event.start), "end": float(event.end)})
        else:
            payload["controllers"].extend([
                {"number": -int(event.pitch), "value": int(event.velocity), "time": float(event.start)},
                {"number": -int(event.pitch), "value": 0, "time": float(event.end)}])
    payload["notes"].sort(key=lambda n: (n["start"], n["pitch"], n["end"], n["velocity"]))
    payload["controllers"].sort(key=lambda c: (c["time"], c["number"], c["value"]))
    validate_notes(payload)
    return payload


def read_midi(midi):
    import pretty_midi
    from .notation import validate_notes
    performance = pretty_midi.PrettyMIDI(str(midi))
    payload = {"notes": [], "controllers": []}
    for instrument in performance.instruments:
        # pretty_midi exposes parsed seconds as numpy.float64. Normalize that
        # representation at the parser boundary; keep the serialized MIDI intact.
        payload["notes"].extend({"pitch": int(n.pitch), "velocity": int(n.velocity),
                                 "start": float(n.start), "end": float(n.end)}
                                for n in instrument.notes)
        payload["controllers"].extend({"number": int(c.number), "value": int(c.value),
                                       "time": float(c.time)}
                                       for c in instrument.control_changes)
    payload["notes"].sort(key=lambda n: (n["start"], n["pitch"], n["end"], n["velocity"]))
    payload["controllers"].sort(key=lambda c: (c["time"], c["number"], c["value"]))
    validate_notes(payload)
    return payload


def render(xml, output, mapping):
    import verovio
    import xml.etree.ElementTree as ET
    from .svg import validate_svg
    toolkit = verovio.toolkit()
    # Glyphs remain local path definitions; don't embed/link a CSS font resource.
    if not toolkit.setOptions({"xmlIdSeed": 1, "smuflTextFont": "none"}):
        raise RuntimeError("Verovio rejected rendering options")
    if not toolkit.loadFile(str(xml)):
        raise RuntimeError("Verovio could not load generated MusicXML")
    count = toolkit.getPageCount()
    if not 1 <= count <= 1024:
        raise RuntimeError("Invalid or excessive Verovio page count")
    mei = ET.fromstring(toolkit.getMEI())
    measures = mei.findall(".//{http://www.music-encoding.org/ns/mei}measure")
    if len(measures) != len(mapping["measures"]):
        raise RuntimeError("Verovio measure count differs from QM measure map")
    for row, measure in zip(mapping["measures"], measures, strict=True):
        identifier = measure.attrib["{http://www.w3.org/XML/1998/namespace}id"]
        page = toolkit.getPageWithElement(identifier)
        if not 1 <= page <= count:
            raise RuntimeError("Verovio measure lacks a rendered page")
        row.update({"svg_id": identifier, "page": page})
    for page in range(1, count + 1):
        content = toolkit.renderToSVG(page).encode("utf-8")
        validate_svg(content)
        (output / f"page-{page:04d}.svg").write_bytes(content)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--rhythm", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    args = parser.parse_args(argv)
    report = check_runtime()
    if args.check:
        print(json.dumps(report, sort_keys=True))
        return 0
    if not all((args.audio, args.rhythm, args.output)):
        parser.error("--audio, --rhythm and --output are required")
    if args.device == "cuda" and not report["cuda"]:
        raise RuntimeError("CUDA is unavailable; choose --device cpu")
    from .notation import write_notation
    grid = BeatGrid.from_track(json.loads(args.rhythm.read_text()))
    args.output.mkdir()
    midi = args.output / "original.mid"
    try:
        payload = transcribe(args.audio, midi, args.device)
    except NoteTimeError as error:
        print(f"Invalid transcription data: {error}", file=sys.stderr)
        return 1
    (args.output / "notes.json").write_text(json.dumps(payload, sort_keys=True, allow_nan=False) + "\n")
    mapping = write_notation(payload, grid, args.output / "score.musicxml")
    render(args.output / "score.musicxml", args.output, mapping)
    (args.output / "measures.json").write_text(json.dumps(mapping, sort_keys=True, allow_nan=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
