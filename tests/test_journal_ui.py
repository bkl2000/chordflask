"""Exercise journal interactions in Node, without a browser or playback changes."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

TEMPLATE = (Path(__file__).resolve().parents[1] / 'chordflask/templates/home.html').read_text()


@pytest.fixture
def run_journal():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node required for journal interaction tests')
    names = ('toggleFilesPanel', 'toggleJournalPanel', 'closeJournalEntry', 'resetJournal',
             'journalRequest', 'updateJournalFields', 'openJournalEntry', 'saveJournalEntry',
             'deleteJournalEntry', 'journalTime', 'updateJournalHighlight', 'renderJournal')
    functions = '\n'.join(re.search(
        rf'    (?:async )?function {name}\([^\n]*\) \{{.*?\n    \}}', TEMPLATE, re.S)[0]
        for name in names)
    harness = '''
      const assert = require('node:assert/strict');
      function element() {
        const classes = new Set();
        return {value: '', hidden: false, disabled: false, checked: false, children: [], attrs: {}, dataset: {},
          classList: {contains: c => classes.has(c), toggle(c, on) {
            if (on) classes.add(c); else classes.delete(c);
          }, remove(c) {classes.delete(c);}},
          getBoundingClientRect() {return {top: 20, bottom: 40};},
          setAttribute(k,v) {this.attrs[k]=v;}, replaceChildren() {this.children=[];},
          appendChild(c) {this.children.push(c);}, addEventListener(k, fn) {this[k]=fn;},
          focus() {}, textContent: ''};
      }
      const elements = {};
      const document = {getElementById(id) {return elements[id] ||= element();}, createElement: element};
      let journalQueries = 0;
      document.querySelectorAll = selector => {
        journalQueries++;
        const found = [];
        function visit(el) {
          if (el.className === 'journal-time'
              && (!selector.endsWith('.current') || el.classList.contains('current'))) found.push(el);
          el.children.forEach(visit);
        }
        visit(document.getElementById('journalEntries'));
        return found;
      };
      const songBar = element(), filesToggle = document.getElementById('filesToggle');
      let desktop = true;
      const window = {innerHeight: 800, matchMedia() {return {matches: desktop};}};
      let loadedFileName = 'a.mp3', loadedFileDirectory = '/music';
      let journalEntries = [], journalEditingId = null, journalGeneration = 0;
      let journalBusy = false, journalReady = true;
      const video = {currentTime: 67.2, paused: false};
      let scrolls = 0;
      function scrollCurrentFileIntoView() {scrolls++;}
      let confirmation = true;
      function confirm() {return confirmation;}
      const requests = [];
      let fetch = async (url, options) => {
        requests.push(JSON.parse(options.body));
        return {ok: true, json: async () => ({schema_version: 1, entries: []})};
      };
      const tick = () => new Promise(resolve => setImmediate(resolve));
    '''
    def run(assertions):
        result = subprocess.run([node, '-e', harness + functions +
            '\n(async () => {' + assertions + '})().catch(e => {throw e;});'],
            capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
    return run


def test_desktop_only_compact_controls_and_panel():
    assert TEMPLATE.count('id="journalToggle"') == 1
    assert 'class="files-toggle" aria-expanded="false"\n            aria-controls="journalPanel"' in TEMPLATE
    assert '<dialog id="journal' not in TEMPLATE
    assert re.search(r'@media \(max-width: 1023px\) \{\s*#journalToggle, #journalPanel \{ display: none !important;', TEMPLATE)
    assert re.search(r'@media \(min-width: 1024px\) \{\s*\.song-bar.journal-open #journalPanel', TEMPLATE)
    assert 'updateCurrentFileRow(true);\n        resetJournal();' in TEMPLATE
    assert 'onclick="openJournalEntry()">+ Add note</button>' in TEMPLATE
    assert 'onclick="openJournalEntry(null, true)">+ Add at current position</button>' in TEMPLATE
    time_input = re.search(r'<input id="journalTimestamp".*?>', TEMPLATE, re.S)[0]
    assert 'required' not in time_input
    assert 'placeholder="Whole song"' in time_input


def test_snapshot_timestamp_edit_and_form_payload(run_journal):
    run_journal('''
      openJournalEntry(null, true);
      assert.equal(elements.journalTimestamp.value, 67.2);
      video.currentTime = 80;
      assert.equal(elements.journalTimestamp.value, 67.2);
      elements.journalTimestamp.value = '64.8';
      elements.journalText.value = 'Late click';
      await saveJournalEntry({preventDefault(){}});
      assert.equal(requests[0].entry.timestamp, 64.8);
      assert.equal(requests[0].entry.category, 'note');
      assert.equal(requests[0].entry.text, 'Late click');
      assert.equal(requests[0].filename, 'a.mp3');
      assert.equal(elements.journalForm.hidden, true);
      openJournalEntry({id:'stable',timestamp:22,category:'agent',kind:'chord',question:'Wrong?',
                        answer:'Fixed',resolved:true,expected_chord:'Am'});
      assert.equal(elements.journalTimestamp.value, 22);
      assert.equal(elements.journalExpectedLabel.hidden, false);
      assert.equal(elements.journalTextLabel.textContent, 'Q / problem description');
      elements.journalTimestamp.value = '20';
      await saveJournalEntry({preventDefault(){}});
      assert.equal(requests[1].action, 'edit');
      assert.equal(requests[1].id, 'stable');
      assert.equal(requests[1].entry.answer, 'Fixed');
      assert.equal(requests[1].entry.expected_chord, 'Am');
      assert.equal(requests[1].entry.resolved, true);
      assert.equal(video.paused, false);
    ''')


def test_entry_hierarchy_scope_and_secondary_actions(run_journal):
    assert 'class="journal-toolbar"' in TEMPLATE
    assert 'class="journal-toolbar-actions"' in TEMPLATE
    assert '.journal-panel button { height: 24px;' in TEMPLATE
    assert '.journal-actions button { color: var(--muted); font-size: 11px;' in TEMPLATE
    desktop = TEMPLATE.split('@media (min-width: 1024px) {')[1].split('@media')[0]
    assert '.song-panel-controls #filesToggle { flex: 0 0 auto; width: auto; }' in desktop
    assert '.files-toggle[aria-expanded="true"]' in desktop
    run_journal('''
      journalEntries = [
        {id:'note',timestamp:null,category:'note',text:'Cooler sound'},
        {id:'info',timestamp:null,category:'info',text:'Live recording'},
        {id:'agent',timestamp:73.7,category:'agent',kind:'general',question:'Early?',answer:'Checked'},
        {id:'timed',timestamp:90,category:'note',text:'Solo'},
      ];
      renderJournal();
      const rows = elements.journalEntries.children;
      assert.deepEqual(rows.map(r=>r.children[1].textContent),
        ['Cooler sound','Live recording','Q: Early?','Solo']);
      for (const row of rows) {
        assert.equal(row.children[0].className, 'journal-entry-heading');
        assert.equal(row.children.at(-1).className, 'journal-actions');
        assert.deepEqual(row.children.at(-1).children.slice(0,2).map(b=>b.textContent), ['Edit','Delete']);
      }
      assert.equal(rows[0].children[0].children[0].className, 'journal-scope');
      assert.equal(rows[1].children[0].children[0].textContent, 'Song');
      assert.equal(rows[2].children[0].children[0].textContent, '1:13.7');
      assert.equal(rows[2].children[0].children[1].textContent, 'agent / general · Open');
      assert.equal(rows[2].children[2].textContent, 'A: Checked');
      assert.equal(rows[3].children[0].children[0].className, 'journal-time');
    ''')


def test_add_note_and_edit_optional_position(run_journal):
    run_journal('''
      openJournalEntry();
      assert.equal(elements.journalTimestamp.value, '');
      video.currentTime = 100;
      assert.equal(elements.journalTimestamp.value, '');
      elements.journalCategory.value = 'info';
      elements.journalText.value = 'Live recording';
      await saveJournalEntry({preventDefault(){}});
      assert.equal(requests[0].entry.timestamp, null);
      assert.equal(requests[0].entry.category, 'info');
      openJournalEntry({id:'wide',timestamp:null,category:'info',text:'Live recording'});
      assert.equal(elements.journalTimestamp.value, '');
      elements.journalTimestamp.value = '0';
      await saveJournalEntry({preventDefault(){}});
      assert.equal(requests[1].entry.timestamp, 0);
      assert.equal(requests[1].action, 'edit');
      openJournalEntry({id:'wide',timestamp:12.3,category:'note',text:'Solo'});
      elements.journalTimestamp.value = '';
      await saveJournalEntry({preventDefault(){}});
      assert.equal(requests[2].entry.timestamp, null);
      assert.equal(video.paused, false);
    ''')


def test_position_links_seek_without_changing_playback_mode(run_journal):
    run_journal('''
      journalEntries = [
        {id:'song',timestamp:null,category:'note',text:'Whole song'},
        {id:'start',timestamp:0,category:'note',text:'Start'},
        {id:'chord',timestamp:83.4,category:'agent',kind:'chord',question:'Wrong?'},
      ];
      renderJournal();
      const rows = elements.journalEntries.children;
      assert.equal(rows[0].children[0].children.length, 2);
      assert.equal(rows[0].children[0].children[0].textContent, 'Song');
      assert.equal(rows[0].children[0].children[1].textContent, 'note');
      const time = rows[2].children[0].children[0];
      assert.equal(time.className, 'journal-time');
      assert.equal(time.textContent, '1:23.4');
      video.paused = true;
      time.click();
      assert.equal(video.currentTime, 83.4);
      assert.equal(video.paused, true);
      video.paused = false;
      rows[1].children[0].children[0].click();
      assert.equal(video.currentTime, 0);
      assert.equal(video.paused, false);
    ''')


def test_long_content_scrolling_and_controls(run_journal):
    styles = re.search(r'    \.journal-panel \{(.*?)\n    \}', TEMPLATE, re.S)[1]
    assert 'max-height: 300px;' in styles
    assert 'overflow-y: auto;' in styles
    assert 'overflow-x: hidden;' in styles
    assert 'min-width: 0;' in styles
    assert 'overflow-wrap: anywhere;' in styles
    assert '.journal-panel > * { flex-shrink: 0; min-width: 0; }' in TEMPLATE
    assert '.journal-entry p { grid-column: 2; margin: 0; line-height: 1.35; white-space: pre-wrap; overflow-wrap: anywhere; max-width: 100ch; }' in TEMPLATE
    run_journal('''
      const longText = 'UnbrokenText'.repeat(500);
      journalEntries = Array.from({length:50}, (_,i) => ({id:String(i),timestamp:i,
        category:'agent',kind:'lyrics',question:longText,answer:longText,resolved:false}));
      renderJournal();
      const rows = elements.journalEntries.children;
      assert.equal(rows.length, 50);
      assert.equal(rows[49].children[1].textContent, 'Q: ' + longText);
      assert.equal(rows[49].children[2].textContent, 'A: ' + longText);
      assert.deepEqual(rows[49].children.at(-1).children.map(b=>b.textContent), ['Edit','Delete','Resolve']);
      assert.equal(rows[49].children.at(-1).children.at(-1).disabled, false);
    ''')


def test_panel_mutual_exclusivity_and_file_playback_preserved(run_journal):
    run_journal('''
      toggleFilesPanel(true);
      assert.equal(songBar.classList.contains('open'), true);
      assert.equal(scrolls, 1);
      toggleJournalPanel(); await tick();
      assert.equal(songBar.classList.contains('open'), false);
      assert.equal(songBar.classList.contains('journal-open'), true);
      assert.equal(filesToggle.attrs['aria-expanded'], 'false');
      toggleJournalPanel();
      assert.equal(songBar.classList.contains('journal-open'), false);
      toggleJournalPanel(); await tick();
      toggleFilesPanel(true);
      assert.equal(songBar.classList.contains('journal-open'), false);
      assert.equal(elements.journalToggle.attrs['aria-expanded'], 'false');
      assert.equal(songBar.classList.contains('open'), true);
      assert.equal(scrolls, 2);
      assert.equal(video.currentTime, 67.2);
      assert.equal(video.paused, false);
      desktop = false;
      toggleJournalPanel();
      assert.equal(songBar.classList.contains('journal-open'), false);
      assert.equal(songBar.classList.contains('open'), true);
    ''')


def test_song_switch_discards_draft_and_late_responses(run_journal):
    run_journal('''
      openJournalEntry();
      let complete;
      fetch = () => new Promise(resolve => {complete = resolve;});
      const old = journalRequest('load');
      loadedFileName = 'b.mp3';
      resetJournal();
      assert.equal(elements.journalForm.hidden, true);
      assert.equal(elements.journalSong.textContent, 'b.mp3');
      assert.equal(elements.journalAdd.disabled, true);
      complete({ok:true,json:async()=>({entries:[{id:'old',timestamp:2,category:'note',text:'a only'}]})});
      await old;
      assert.deepEqual(journalEntries, []);
      assert.equal(journalReady, false);
    ''')


def test_delete_confirmation_and_resolve_actions(run_journal):
    run_journal('''
      const entry = {id:'one',timestamp:1,category:'agent',kind:'lyrics',question:'Shifted',resolved:false};
      confirmation = false;
      await deleteJournalEntry(entry);
      assert.equal(requests.length, 0);
      confirmation = true;
      await deleteJournalEntry(entry);
      assert.equal(requests[0].action, 'delete');
      assert.equal(requests[0].id, 'one');
      journalEntries = [entry]; renderJournal();
      let row = elements.journalEntries.children[0];
      await row.children.at(-1).children.at(-1).click();
      assert.equal(requests[1].action, 'resolve');
      assert.equal(requests[1].resolved, true);
      journalEntries = [{...entry,resolved:true}]; renderJournal();
      row = elements.journalEntries.children[0];
      assert.equal(row.children.at(-1).children.at(-1).textContent, 'Reopen');
      await row.children.at(-1).children.at(-1).click();
      assert.equal(requests[2].resolved, false);
    ''')


def test_load_failure_keeps_add_disabled_and_safe_text_rendering(run_journal):
    run_journal('''
      fetch = async()=>({ok:false,json:async()=>({error:'Malformed journal'})});
      resetJournal(); await journalRequest('load');
      assert.equal(elements.journalAdd.disabled, true);
      assert.equal(elements.journalStatus.textContent, 'Malformed journal');
      journalEntries = [{id:'x',timestamp:1,category:'note',text:'<script>alert(1)</script>'}];
      renderJournal();
      assert.equal(elements.journalEntries.children[0].children[1].textContent, '<script>alert(1)</script>');
    ''')


def test_highlight_uses_existing_playback_updates_and_inverse_timestamp_style():
    sync = re.search(r'    function syncPlaybackPosition\([^\n]*\) \{.*?\n    \}', TEMPLATE, re.S)[0]
    assert sync.count('updateJournalHighlight();') == 1
    assert sync.index('updateJournalHighlight();') < sync.index('if (positionSyncInFlight)')
    highlight = re.search(r'    function updateJournalHighlight\([^\n]*\) \{.*?\n    \}', TEMPLATE, re.S)[0]
    for forbidden in ('setInterval', 'setTimeout', 'scroll', 'fetch(', '.value ='):
        assert forbidden not in highlight
    assert '.journal-time.current { background: var(--accent-dark); color: #fff; }' in TEMPLATE


def test_highlight_window_song_wide_exclusion_and_visibility(run_journal):
    run_journal('''
      songBar.classList.toggle('journal-open', true);
      document.getElementById('journalForm').hidden = true;
      journalEntries = [
        {id:'song',timestamp:null,category:'note',text:'Whole song'},
        {id:'near',timestamp:10,category:'note',text:'Here'},
        {id:'far',timestamp:30,category:'note',text:'Later'},
      ];
      video.currentTime = 9.999;
      renderJournal();
      const rows = elements.journalEntries.children;
      assert.equal(rows[0].children[0].children.length, 2);
      const near = rows[1].children[0].children[0];
      const far = rows[2].children[0].children[0];
      assert.equal(near.classList.contains('current'), false);
      video.currentTime = 10;
      updateJournalHighlight();
      assert.equal(near.classList.contains('current'), true);
      assert.equal(far.classList.contains('current'), false);
      video.currentTime = 11.999;
      updateJournalHighlight();
      assert.equal(near.classList.contains('current'), true);
      video.currentTime = 12;
      updateJournalHighlight();
      assert.equal(near.classList.contains('current'), false);
      video.currentTime = 10.5;
      elements.journalPanel.scrollTop = 123;
      near.scrollIntoView = () => {throw new Error('Must not scroll');};
      near.getBoundingClientRect = () => ({top: 500, bottom: 520});
      updateJournalHighlight();
      assert.equal(near.classList.contains('current'), false);
      near.getBoundingClientRect = () => ({top: 20, bottom: 40});
      updateJournalHighlight();
      assert.equal(near.classList.contains('current'), true);
      assert.equal(elements.journalPanel.scrollTop, 123);
      assert.equal(scrolls, 0);
    ''')


def test_closed_and_smaller_layouts_do_no_highlight_dom_work(run_journal):
    run_journal('''
      renderJournal();
      const queries = journalQueries;
      updateJournalHighlight();
      assert.equal(journalQueries, queries);
      songBar.classList.toggle('journal-open', true);
      desktop = false;
      updateJournalHighlight();
      assert.equal(journalQueries, queries);
    ''')


@pytest.mark.parametrize('editing', [False, True])
def test_add_edit_suppression_cancel_and_save_resume(run_journal, editing):
    run_journal('''
      songBar.classList.toggle('journal-open', true);
      document.getElementById('journalForm').hidden = true;
      const entry = {id:'one',timestamp:67.2,category:'note',text:'Here'};
      journalEntries = [entry]; renderJournal();
      let time = elements.journalEntries.children[0].children[0].children[0];
      assert.equal(time.classList.contains('current'), true);
      openJournalEntry(''' + ('entry' if editing else 'null, true') + ''');
      assert.equal(time.classList.contains('current'), false);
      const queries = journalQueries;
      video.currentTime = 68;
      updateJournalHighlight();
      assert.equal(journalQueries, queries);
      assert.equal(time.classList.contains('current'), false);
      assert.equal(elements.journalTimestamp.value, 67.2);
      closeJournalEntry();
      assert.equal(time.classList.contains('current'), true);
      openJournalEntry(entry);
      elements.journalText.value = 'Changed';
      fetch = async () => ({ok:true,json:async()=>({entries:[entry]})});
      await saveJournalEntry({preventDefault(){}});
      time = elements.journalEntries.children[0].children[0].children[0];
      assert.equal(elements.journalForm.hidden, true);
      assert.equal(time.classList.contains('current'), true);
      assert.equal(elements.journalTimestamp.value, 67.2);
    ''')
