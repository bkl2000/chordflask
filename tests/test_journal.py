"""Journal persistence, API isolation, and preservation of user-authored data."""
from datetime import datetime
import json
import os
from pathlib import Path

import pytest

from chordflask.filerepr import FileRepr
from chordflask.journal import load_journal, update_journal
from chordflask_maintain.migrate import migrate_directory
from chordflask_maintain.storage import (
    cleanup_cached_audio, cleanup_corrupt_backups, cleanup_orphan_temp, inspect_storage,
)
from chordflask_maintain.validate import validate_directory


@pytest.fixture
def journal_path(tmp_path):
    return Path(FileRepr(tmp_path / 'song.mp3').journal_path)


def note(category='note', timestamp=67.2, text='Remember this part'):
    return {'timestamp': timestamp, 'category': category, 'text': text}


def agent(**changes):
    return dict(timestamp=12.3, category='agent', kind='chord', question='Sounds wrong',
                answer='Confirmed and corrected from C to Am.', resolved=False,
                expected_chord='Am', **changes)


def test_missing_journal_has_no_storage_side_effect(journal_path):
    assert load_journal(journal_path) == {'schema_version': 1, 'entries': []}
    assert not journal_path.parent.exists()


@pytest.mark.parametrize('category', ['note', 'info'])
def test_note_info_roundtrip_and_edit_delete(journal_path, category):
    saved = update_journal(journal_path, 'add', note(category))
    entry = saved['entries'][0]
    assert load_journal(journal_path) == saved
    assert entry['text'] == 'Remember this part'
    edited = update_journal(journal_path, 'edit', note(category, 60, 'Changed'), entry['id'])
    assert edited['entries'] == [dict(note(category, 60, 'Changed'), id=entry['id'])]
    assert load_journal(journal_path) == edited
    update_journal(journal_path, 'delete', entry_id=entry['id'])
    assert load_journal(journal_path) == {'schema_version': 1, 'entries': []}
    assert journal_path.exists()  # deliberate minimal empty schema file


@pytest.mark.parametrize('category', ['note', 'info', 'agent'])
def test_song_wide_entry_roundtrip(journal_path, category):
    entry = dict(agent(), timestamp=None) if category == 'agent' else note(category, None)
    saved = update_journal(journal_path, 'add', entry)
    assert saved['entries'][0]['timestamp'] is None
    assert saved['entries'][0]['category'] == category
    assert load_journal(journal_path) == saved
    assert json.loads(journal_path.read_text())['entries'][0]['timestamp'] is None


def test_existing_numeric_journal_loads_unchanged(journal_path):
    data = {'schema_version': 1, 'entries': [dict(note(timestamp=0), id='zero'),
                                          dict(agent(), id='problem', resolved_at=None)]}
    journal_path.parent.mkdir(parents=True)
    journal_path.write_text(json.dumps(data))
    before = journal_path.read_bytes()
    assert load_journal(journal_path) == data
    assert journal_path.read_bytes() == before


def test_song_wide_first_stable_edit_order_and_position_changes(journal_path):
    entries = [note(timestamp=20), note(timestamp=None, text='First song note'),
               note(timestamp=0), note('info', None, 'Second song note'), note(timestamp=10)]
    for entry in entries:
        update_journal(journal_path, 'add', entry)
    saved = load_journal(journal_path)
    assert [e['timestamp'] for e in saved['entries']] == [None, None, 0, 10, 20]
    first, second = saved['entries'][:2]
    edited = update_journal(journal_path, 'edit', note(timestamp=None, text='Changed'), first['id'])
    assert [e['id'] for e in edited['entries'][:2]] == [first['id'], second['id']]
    assert load_journal(journal_path) == edited
    positioned = update_journal(journal_path, 'edit', note(timestamp=5), first['id'])
    assert [e['timestamp'] for e in positioned['entries']] == [None, 0, 5, 10, 20]
    whole_song = update_journal(journal_path, 'edit', note(timestamp=None), first['id'])
    assert [e['id'] for e in whole_song['entries'][:2]] == [second['id'], first['id']]


def test_agent_qa_expected_chord_resolve_reopen(journal_path):
    saved = update_journal(journal_path, 'add', agent())
    entry = saved['entries'][0]
    assert entry['question'] == 'Sounds wrong'
    assert entry['answer'] == 'Confirmed and corrected from C to Am.'
    assert entry['expected_chord'] == 'Am'
    assert entry['resolved_at'] is None
    resolved = update_journal(journal_path, 'resolve', entry_id=entry['id'], resolved=True)
    date = resolved['entries'][0]['resolved_at']
    assert datetime.fromisoformat(date).tzinfo is not None
    assert load_journal(journal_path) == resolved
    edited = update_journal(journal_path, 'edit', dict(agent(), resolved=True), entry['id'])
    assert edited['entries'][0]['resolved_at'] == date
    reopened = update_journal(journal_path, 'resolve', entry_id=entry['id'], resolved=False)
    assert reopened['entries'][0]['resolved_at'] is None
    assert not reopened['entries'][0]['resolved']
    assert load_journal(journal_path) == reopened


def test_resolved_at_is_server_owned(journal_path):
    saved = update_journal(journal_path, 'add', dict(agent(), resolved=True, resolved_at='fake'))
    assert saved['entries'][0]['resolved_at'] != 'fake'
    reopened = update_journal(journal_path, 'edit', agent(), saved['entries'][0]['id'])
    assert reopened['entries'][0]['resolved_at'] is None


def test_add_never_reuses_a_supplied_id(journal_path):
    first = update_journal(journal_path, 'add', note())['entries'][0]
    data = update_journal(journal_path, 'add', note('info'), first['id'])
    assert len(data['entries']) == 2
    assert data['entries'][0] == first
    assert data['entries'][1]['id'] != first['id']


def test_timestamp_order_and_same_stem_isolation(tmp_path):
    a = FileRepr(tmp_path / 'song.mp3').journal_path
    b = FileRepr(tmp_path / 'song.mp4').journal_path
    assert a != b
    assert Path(a).name == 'song.mp3.journal.json'
    assert Path(a).parent == tmp_path / '.chordflask' / 'journals'
    assert a != FileRepr(tmp_path / 'song.mp3.journal.mp4').json_path
    update_journal(a, 'add', note(timestamp=20))
    update_journal(a, 'add', note(timestamp=10))
    assert [e['timestamp'] for e in load_journal(a)['entries']] == [10, 20]
    assert load_journal(b)['entries'] == []
    assert load_journal(FileRepr(tmp_path / 'other' / 'song.mp3').journal_path)['entries'] == []


@pytest.mark.parametrize('change', [
    {'timestamp': -1}, {'timestamp': float('nan')}, {'timestamp': True},
    {'timestamp': '12'}, {'category': 'other'}, {'text': ''}, {'text': 9},
])
def test_bad_input_leaves_existing_data_unchanged(journal_path, change):
    update_journal(journal_path, 'add', note())
    before = journal_path.read_bytes()
    with pytest.raises(ValueError):
        update_journal(journal_path, 'add', dict(note(), **change))
    assert journal_path.read_bytes() == before


@pytest.mark.parametrize('content', ['{', '[]', '{"schema_version":2,"entries":[]}',
                                      '{"schema_version":1,"entries":[{}]}'])
def test_malformed_storage_blocks_read_and_mutation(journal_path, content):
    journal_path.parent.mkdir(parents=True)
    journal_path.write_text(content)
    with pytest.raises(ValueError):
        load_journal(journal_path)
    with pytest.raises(ValueError):
        update_journal(journal_path, 'add', note())
    assert journal_path.read_text() == content


def test_maintenance_preserves_even_malformed_journals(tmp_path, monkeypatch, journal_path):
    monkeypatch.setenv('CHORDFLASK_QUEUE_DIR', str(tmp_path / 'queue'))
    journal_path.parent.mkdir(parents=True)
    journal_path.write_text('{malformed user data')
    before = journal_path.read_bytes()
    categories = inspect_storage(tmp_path).categories
    assert [(c.name, c.status) for c in categories] == [('user journals', 'protected')]
    assert validate_directory(tmp_path) == {'valid': 0, 'invalid': 0}
    assert migrate_directory(tmp_path) == {'files': 0, 'migrated': 0, 'skipped': 0, 'failed': 0}
    store = journal_path.parent.parent
    (tmp_path / 'song.mp4').write_bytes(b'media')
    cache = store / 'song.mp3'
    cache.write_bytes(b'cached audio')
    temporary = store / '.song.analyze-abc'
    temporary.mkdir()
    (temporary / 'partial.json').write_text('{}')
    corrupt = store / 'song.corrupt-20260101T123456123456Z-abcdef12.json'
    corrupt.write_text('{}')
    os.utime(corrupt, (1, 1))
    cleanup_orphan_temp(tmp_path)
    cleanup_cached_audio(tmp_path)
    cleanup_corrupt_backups(tmp_path, 1)
    assert not temporary.exists()
    assert not cache.exists()
    assert not corrupt.exists()
    assert journal_path.read_bytes() == before


def test_atomic_write_failure_preserves_journal(journal_path, monkeypatch):
    update_journal(journal_path, 'add', note())
    before = journal_path.read_bytes()
    def fail_replace(*args):
        raise OSError('Cannot replace destination')
    monkeypatch.setattr('chordflask_base.schema.os.replace', fail_replace)
    with pytest.raises(OSError):
        update_journal(journal_path, 'add', note('info'))
    assert journal_path.read_bytes() == before
    assert not list(journal_path.parent.glob('*.tmp'))


def test_deletion_never_touches_other_song_data(tmp_path, journal_path):
    saved = update_journal(journal_path, 'add', note())
    others = [tmp_path / 'song.mp3', tmp_path / 'song.lrc', journal_path.parent / 'song.json',
              journal_path.parent / 'song.mp3', journal_path.parent / 'stems' / 'vocals.mp3']
    for path in others:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'keep me')
    update_journal(journal_path, 'delete', entry_id=saved['entries'][0]['id'])
    assert all(path.read_bytes() == b'keep me' for path in others)


def test_api_roundtrip_isolation_errors(tmp_path, monkeypatch):
    from chordflask.app import FlaskMP4App
    monkeypatch.setenv('CHORDFLASK_QUEUE_DIR', str(tmp_path / 'queue'))
    app = FlaskMP4App()
    client = app.app.test_client()
    for name in ('a.mp3', 'b.mp3'):
        (tmp_path / name).write_bytes(b'media')
    def request(name='a.mp3', **fields):
        return client.post('/journal', json=dict(dirname=str(tmp_path), filename=name, **fields))
    assert request().json['entries'] == []
    assert not (tmp_path / '.chordflask').exists()
    response = request(action='add', entry=note())
    assert response.status_code == 200
    assert request().json == response.json
    assert request('b.mp3').json['entries'] == []
    identity = response.json['entries'][0]['id']
    assert request(action='edit', id=identity, entry=note('info', 3)).json['entries'][0]['timestamp'] == 3
    assert request(action='add', entry=note(timestamp=-1)).status_code == 400
    assert request(action='delete', id='missing').status_code == 400
    assert request('../a.mp3').status_code == 400
    assert request(action='delete', id=identity).json['entries'] == []
    song_wide = request(action='add', entry=note('info', None))
    assert song_wide.status_code == 200
    assert request().json == song_wide.json
    assert song_wide.json['entries'][0]['timestamp'] is None
    path = Path(FileRepr(tmp_path / 'a.mp3').journal_path)
    path.write_text('{broken')
    assert request().status_code == 400
    assert request(action='add', entry=note()).status_code == 400
    assert path.read_text() == '{broken'
