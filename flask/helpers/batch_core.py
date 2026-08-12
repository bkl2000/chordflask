from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


VIDEO_SUFFIXES = (".mp4", ".webm")


def find_media_files(media_dir):
    root = Path(media_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"Media directory does not exist: {media_dir}")
    files = [
        path
        for path in root.iterdir()
        if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES
    ]
    return sorted(files, key=lambda path: (path.stat().st_size, path.name.lower()))


def analyze_file(filename, analyzer_factory):
    path = Path(filename)
    analyzer = analyzer_factory(str(path))
    analyzer.process()
    return {
        "filename": str(path),
        "size_mb": path.stat().st_size // 1000000,
        "ok": True,
        "error": None,
    }


def analyze_file_safe(filename, analyzer_factory):
    try:
        return analyze_file(filename, analyzer_factory)
    except Exception as exc:
        path = Path(filename)
        return {
            "filename": str(path),
            "size_mb": path.stat().st_size // 1000000 if path.exists() else 0,
            "ok": False,
            "error": str(exc),
        }


def run_serial(media_dir, analyzer_factory, output=print):
    files = find_media_files(media_dir)
    total = len(files)
    output(f"Found {total} media files in {media_dir}")
    results = []

    for index, path in enumerate(files, 1):
        size_mb = path.stat().st_size // 1000000
        output("")
        output("-" * 80)
        output(f"Analyzing {index}/{total} {size_mb}MB {path}")
        result = analyze_file_safe(path, analyzer_factory)
        results.append(result)
        if result["ok"]:
            output(f"Finished: {path}")
        else:
            output(f"Error: {path}: {result['error']}")

    summarize(results, output=output)
    return results


def _analyze_file_with_default_factory(filename):
    from chordanalyzer import ChordAnalyzer

    return analyze_file_safe(filename, ChordAnalyzer)


def run_parallel(media_dir, workers=2, output=print):
    files = find_media_files(media_dir)
    total = len(files)
    output(f"Found {total} media files in {media_dir}")
    results = []

    with ProcessPoolExecutor(max_workers=workers) as executor:
        future_to_path = {
            executor.submit(_analyze_file_with_default_factory, str(path)): path
            for path in files
        }
        for index, future in enumerate(as_completed(future_to_path), 1):
            path = future_to_path[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "filename": str(path),
                    "size_mb": path.stat().st_size // 1000000 if path.exists() else 0,
                    "ok": False,
                    "error": str(exc),
                }
            results.append(result)
            status = "ok" if result["ok"] else f"error: {result['error']}"
            output(f"[{index}/{total}] {status}: {path}")

    summarize(results, output=output)
    return results


def summarize(results, output=print):
    ok_count = sum(1 for result in results if result["ok"])
    failed = [result for result in results if not result["ok"]]
    output("")
    output(f"Done: {ok_count} ok, {len(failed)} failed")
    for result in failed:
        output(f"Failed: {result['filename']}: {result['error']}")
