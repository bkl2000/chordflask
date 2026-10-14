"""Active-song, persisted Score display and external-runtime boundaries."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from chordflask.app import CLIENT_COOKIE, FlaskMP4App
from chordflask import media_preparation, score
from chordflask_score import storage
from test_score_storage_cli import song as score_song, staged as score_staged, finish


song = score_song
staged = score_staged


@pytest.fixture
def display(song, staged, monkeypatch, tmp_path):
    monkeypatch.setenv('CHORDFLASK_QUEUE_DIR', str(tmp_path / 'queue'))
    manifest = finish(song, staged, monkeypatch)
    app = FlaskMP4App()
    client = app.app.test_client()
    state = app.clients.get_or_create('score-display')
    client.set_cookie(CLIENT_COOKIE, 'score-display')
    assert client.post('/load_file', json={'dirname': str(song.parent), 'filename': song.name}).status_code == 200
    return app, client, state, manifest


def test_metadata_and_validated_svg_without_runtime(display, song, monkeypatch):
    _, client, _, _ = display
    monkeypatch.setenv('CHORDFLASK_SCORE_VENV', '/nonexistent/score')
    result = client.get('/score', query_string={'media': str(song)})
    assert result.status_code == 200
    data = result.get_json()
    assert data['pages'] == 1
    assert data['measures'][0]['start_seconds'] == 0
    response = client.get('/score/page/1', query_string={'media': str(song), 'generation': data['generation']})
    assert response.status_code == 200
    assert response.mimetype == 'image/svg+xml'
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert "default-src 'none'" in response.headers['Content-Security-Policy']
    assert b'<svg' in response.data
    for page in (0, 2, 9999):
        assert client.get(f'/score/page/{page}', query_string={'media': str(song), 'generation': data['generation']}).status_code == 404
    assert client.get('/score/page/1', query_string={'media': str(song), 'generation': 'old'}).status_code == 404


@pytest.mark.parametrize('damage', ['source', 'missing', 'hash', 'unsafe', 'malformed', 'symlink', 'manifest'])
def test_invalid_score_is_not_exposed(display, song, damage):
    _, client, _, path = display
    manifest = storage.read_json(path)
    svg = path.parent / manifest['generation'] / 'page-0001.svg'
    if damage == 'source':
        song.write_bytes(b'changed source')
    elif damage == 'missing':
        svg.unlink()
    elif damage == 'hash':
        svg.write_bytes(svg.read_bytes() + b' ')
    elif damage in ('unsafe', 'malformed'):
        svg.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>' if damage == 'unsafe' else b'<svg')
        manifest['artifacts'][svg.name] = {'size': svg.stat().st_size, 'sha256': storage.hash_file(svg)}
        path.write_text(json.dumps(manifest))
    elif damage == 'symlink':
        content = svg.read_bytes()
        svg.unlink()
        external = song.parent / 'outside.svg'
        external.write_bytes(content)
        svg.symlink_to(external)
    else:
        path.write_text('{}')
    assert client.get('/score', query_string={'media': str(song)}).status_code == 404
    assert client.get('/score/page/1', query_string={'media': str(song), 'generation': manifest['generation']}).status_code == 404


def test_song_change_and_late_request(display, song, monkeypatch):
    _, client, state, _ = display
    assert client.get('/score', query_string={'media': 'other.mp3'}).status_code == 409
    original = score.read_score
    def switch(media):
        result = original(media)
        with state.lock:
            state.file_repr = None
        return result
    monkeypatch.setattr(score, 'read_score', switch)
    assert client.get('/score', query_string={'media': str(song)}).status_code == 409
    assert client.get('/score', query_string={'media': str(song)}).status_code == 409


def test_absent_score_and_runtime(display, song, monkeypatch):
    app, client, _, path = display
    path.unlink()
    assert client.get('/score', query_string={'media': str(song)}).status_code == 404
    from chordflask.stem_preparation import BackgroundPreparationManager
    app.score_preparation = BackgroundPreparationManager(
        capability_probe=lambda: {'available': False, 'reason': 'Score runtime missing'},
        runner=lambda _: pytest.fail('must not run'), label='Score')
    response = client.post('/prepare_score', json={'dirname': str(song.parent), 'filename': song.name})
    assert response.status_code == 409
    assert response.get_json()['status'] == 'unavailable'


def test_display_survives_producer_upgrade(display, song, monkeypatch):
    _, client, _, _ = display
    monkeypatch.setattr(storage, 'code_identity', lambda: 'new code')
    assert storage.classify(song).label == 'STALE'
    assert client.get('/score', query_string={'media': str(song)}).status_code == 200


def test_score_helper_uses_isolated_external_interpreter(tmp_path, monkeypatch):
    helper = tmp_path / 'runtime/bin/chordflask-score'
    helper.parent.mkdir(parents=True)
    helper.write_text('#!/bin/sh\n')
    helper.chmod(0o755)
    monkeypatch.setenv('CHORDFLASK_SCORE_VENV', str(helper.parent.parent))
    commands = []
    monkeypatch.setattr(media_preparation, '_run_helper', lambda _, command, **kwargs: commands.append(command) or 0)
    assert media_preparation.run_score_preparation(tmp_path / 'song.mp3') == 0
    assert commands == [[str(helper.parent / 'python'), '-I', str(helper), '--replace', str(tmp_path / 'song.mp3')]]


def test_web_reader_has_no_heavy_imports():
    root = Path(__file__).resolve().parents[1]
    code = f'import sys; sys.path.insert(0, {str(root)!r}); import chordflask.score; '
    code += "assert not {'torch','transkun','verovio','music21','pretty_midi'} & set(sys.modules)"
    result = subprocess.run([sys.executable, '-I', '-c', code], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_multiple_pages_are_served_by_manifest(song, staged, monkeypatch):
    mapping_path = staged / 'measures.json'
    mapping = storage.read_json(mapping_path)
    mapping['measures'][1]['page'] = 2
    mapping_path.write_text(json.dumps(mapping))
    (staged / 'page-0002.svg').write_bytes((staged / 'page-0001.svg').read_bytes())
    finish(song, staged, monkeypatch)
    _, metadata = score.read_score(song)
    assert metadata['pages'] == 2
    assert metadata['measures'][1]['page'] == 2
    assert score.read_page(song, 2, metadata['generation']).startswith(b'<svg')


def test_explicit_preparation_and_active_song_contract(display, song):
    from chordflask.stem_preparation import BackgroundPreparationManager
    import threading
    app, client, _, path = display
    path.unlink()
    called = threading.Event()
    app.score_preparation = BackgroundPreparationManager(
        capability_probe=lambda: {'available': True, 'cuda': False, 'reason': ''},
        runner=lambda media: called.set() or 0, label='Score')
    assert not called.is_set()
    assert client.get('/score', query_string={'media': str(song)}).status_code == 404
    assert not called.is_set()
    assert client.post('/prepare_score', json={'dirname': str(song.parent), 'filename': 'absent.mp3'}).status_code != 202
    assert not called.is_set()
    response = client.post('/prepare_score', json={'dirname': str(song.parent), 'filename': song.name})
    assert response.status_code == 202
    assert called.wait(2)


@pytest.mark.parametrize('frozen', [False, True])
def test_score_capability_checks_only_external_runtime(tmp_path, monkeypatch, frozen):
    helper = tmp_path / 'bin/chordflask-score'
    helper.parent.mkdir()
    helper.write_text('#!/bin/sh\n')
    helper.chmod(0o755)
    monkeypatch.setenv('CHORDFLASK_SCORE_VENV', str(tmp_path))
    monkeypatch.setattr(sys, 'frozen', frozen, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', '/bundle', raising=False)
    monkeypatch.setenv('LD_LIBRARY_PATH', '/bundle:/system/lib')
    monkeypatch.setenv('PYTHONHOME', '/bundle')
    monkeypatch.setenv('PYTHONPATH', '/bundle')
    media_preparation.clear_capability_cache()
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        env = kwargs['env']
        assert env['LD_LIBRARY_PATH'] == ('/system/lib' if frozen else '/bundle:/system/lib')
        assert ('PYTHONHOME' in env) is not frozen
        assert ('PYTHONPATH' in env) is not frozen
        if command[-1] == '--check':
            assert kwargs['timeout'] == 60
        return subprocess.CompletedProcess(command, 0, '{}', '')
    monkeypatch.setattr(media_preparation.subprocess, 'run', run)
    assert media_preparation.score_capability()['available']
    assert commands == [[str(tmp_path / 'bin/python'), '-I', '-m', 'chordflask_score.worker', '--check']]
    assert media_preparation.run_score_preparation(tmp_path / 'song.mp3') == 0
    assert commands[-1] == [str(tmp_path / 'bin/python'), '-I', str(helper), '--replace', str(tmp_path / 'song.mp3')]
    media_preparation.clear_capability_cache()


def test_successful_preparation_enables_persisted_display(display, song):
    from chordflask.stem_preparation import BackgroundPreparationManager
    from test_media_preparation import _wait_status
    app, client, _, path = display
    complete = storage.read_json(path)
    path.unlink()
    app.score_preparation = BackgroundPreparationManager(
        capability_probe=lambda: {'available': True, 'cuda': False, 'reason': ''},
        runner=lambda _: storage.write_atomic(path, complete) or 0, label='Score')
    assert client.get('/score', query_string={'media': str(song)}).status_code == 404
    assert client.post('/prepare_score', json={'dirname': str(song.parent), 'filename': song.name}).status_code == 202
    assert _wait_status(client, '/score_preparation_status', 'ready')['available']
    assert client.get('/score', query_string={'media': str(song)}).status_code == 200


def test_score_javascript_is_served(display):
    _, client, _, _ = display
    response = client.get('/static/score.js')
    assert response.status_code == 200
    assert response.data == (Path(__file__).resolve().parents[1] / 'chordflask/static/score.js').read_bytes()


@pytest.mark.parametrize('damage', ['missing', 'rhythm'])
def test_completed_score_becoming_invalid_can_be_prepared_again(display, song, damage):
    from chordflask.stem_preparation import BackgroundPreparationManager
    from chordflask_base import ChordTrackRepository, analysis_json_path
    from test_media_preparation import _wait_status
    app, client, _, path = display
    manifest = storage.read_json(path)
    path.unlink()
    app.score_preparation = BackgroundPreparationManager(
        capability_probe=lambda: {'available': True, 'cuda': False, 'reason': ''},
        runner=lambda _: storage.write_atomic(path, manifest) or 0, label='Score')
    body = {'dirname': str(song.parent), 'filename': song.name}
    assert client.post('/prepare_score', json=body).status_code == 202
    _wait_status(client, '/score_preparation_status', 'ready')
    if damage == 'missing':
        path.unlink()
    else:
        repository = ChordTrackRepository()
        data = repository.load(analysis_json_path(song))
        rhythm = data.rhythm_track_data('qm_barbeattracker')
        rhythm['beat_times'][-1] += .1
        data.set_rhythm_track('qm_barbeattracker', **rhythm)
        repository.save(data, analysis_json_path(song))
    status = client.get('/score_preparation_status').get_json()
    assert status['state'] == 'error'
    assert status['available']
    assert client.get('/score', query_string={'media': str(song)}).status_code == 404
    assert client.post('/prepare_score', json=body).status_code == 202
    _wait_status(client, '/score_preparation_status', 'ready' if damage == 'missing' else 'error')


def test_display_reuses_media_digest_but_revalidates_artifacts(display, song, monkeypatch):
    import os
    from chordflask_base import analysis
    _, client, _, path = display
    analysis._cached_source_identity.cache_clear()
    original = analysis.media_source_identity
    calls = []
    def hash_media(media):
        calls.append(media)
        return original(media)
    monkeypatch.setattr(analysis, 'media_source_identity', hash_media)
    manifest = storage.read_json(path)
    query = {'media': str(song), 'generation': manifest['generation']}
    for _ in range(3):
        assert client.get('/score', query_string=query).status_code == 200
        assert client.get('/score/page/1', query_string=query).status_code == 200
        assert client.get('/score_preparation_status').get_json()['state'] == 'ready'
    assert len(calls) == 1
    svg = path.parent / manifest['generation'] / 'page-0001.svg'
    content = svg.read_bytes()
    svg.write_bytes(content + b' ')
    assert client.get('/score/page/1', query_string=query).status_code == 404
    svg.write_bytes(content)
    stamp = song.stat()
    song.write_bytes(b'x' * stamp.st_size)
    os.utime(song, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert client.get('/score/page/1', query_string=query).status_code == 404
    assert len(calls) == 2
