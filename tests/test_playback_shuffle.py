"""Exercise the actual playback functions in Node without launching a browser."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest


TEMPLATE = (Path(__file__).resolve().parents[1] / "chordflask/templates/home.html").read_text()


def playback_function(name):
    return re.search(
        rf"    function {name}\([^\n]*\) \{{.*?\n    \}}",
        TEMPLATE,
        re.DOTALL,
    )[0]


@pytest.fixture
def run_playback():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to exercise browser playback functions")
    names = (
        "navigationAnchorName", "updateNavigationButtons", "updatePlaybackControlLabels",
        "setRepeat", "toggleRepeat", "setLoop", "toggleLoop", "setContinue",
        "toggleContinue", "toggleShuffle", "navigateFile", "playNextFileIfContinue",
        "shuffleFileOrder", "compareNames", "compareEntries", "sortedEntries",
        "sortBrowserEntries", "renderBrowserTable", "updateCurrentFileRow",
        "scrollCurrentFileIntoView", "toggleFilesPanel", "toggleMobileMenu",
        "loadFiles", "discardQueuedLoadIntents", "selectPreferredFile",
    )
    functions = "\n".join(playback_function(name) for name in names)
    defaults = "\n".join(re.findall(
        r"    let is(?:Repeating|Continuing|Looping|Shuffling) = false;", TEMPLATE
    ))
    harness = """
      const assert = require('node:assert/strict');
      const buttons = {};
      const scrolls = [];
      function element() {
        const el = {
          className: '', children: [], dataset: {}, attributes: {}, listeners: {},
          set innerHTML(value) {this.children = [];},
          appendChild(child) {this.children.push(child);},
          setAttribute(name, value) {this.attributes[name] = value;},
          removeAttribute(name) {delete this.attributes[name];},
          addEventListener(name, callback) {this.listeners[name] = callback;},
          querySelectorAll(selector) {
            return this.children.filter(row => selector.slice(1).split('.')
              .every(cls => row.classList.contains(cls)));
          },
          querySelector(selector) {return this.querySelectorAll(selector)[0];},
          scrollIntoView(options) {scrolls.push({name: this.dataset.filename, ...options});},
        };
        el.classList = {
          contains(cls) {return el.className.split(' ').includes(cls);},
          add(cls) {this.toggle(cls, true);},
          toggle(cls, enabled) {
            const classes = new Set(el.className.split(' ').filter(Boolean));
            if (enabled) classes.add(cls); else classes.delete(cls);
            el.className = [...classes].join(' ');
          },
        };
        return el;
      }
      const document = {getElementById(id) {
        return buttons[id] ||= {
          textContent: '', classes: new Set(), attributes: {'aria-pressed': 'false'},
          classList: {toggle(name, enabled) {
            if (enabled) buttons[id].classes.add(name);
            else buttons[id].classes.delete(name);
          }},
          setAttribute(name, value) {this.attributes[name] = value;}
        };
      }, createElement: element, body: element()};
      const fileTableBody = element();
      const mobileMenuButton = document.getElementById('mobileMenuButton');
      const filesToggle = document.getElementById('filesToggle');
      const songBar = element();
      const video = {loop: false};
      const loopToggleButton = document.getElementById('loopToggleButton');
      const previousFileButton = document.getElementById('previousFileButton');
      const nextFileButton = document.getElementById('nextFileButton');
      const mobilePlaybackControls = {matches: false};
      let currentFiles = ['a.mp3', 'b.mp4', 'c.webm'].map(name => ({name}));
      let currentDirectories = [];
      let parentDirectory = '';
      let currentDirectory = '/music';
      let loadedFileDirectory = '/music';
      let selectedFileName = 'b.mp4';
      let loadedFileName = 'b.mp4';
      let pendingAnalysisLoad = null;
      let loadRequestInFlight = false;
      let loadIntentQueue = [];
      const fileStatus = {innerText: ''};
      const dirnameInput = {value: '/music'};
      let sortKey = 'name';
      let sortDirection = 'asc';
      const nameCollator = new Intl.Collator(undefined, {numeric: true});
      const storageKeys = {};
      const localStorage = {getItem() {return null;}, setItem() {}};
      let fetch;
      const loads = [];
      function renderDirectoryRow() {}
      function updateSortHeaders() {}
      function updateBatchButton() {}
      function updateCurrentPath() {}
      function loadSelectedFile(options) {loads.push({name: selectedFileName, ...options});}
      function visibleNames() {return fileTableBody.children.map(row => row.dataset.filename);}
      function currentRow() {return fileTableBody.querySelector('.file-row.current');}
      async function refresh(files, directory = '/music') {
        document.getElementById('matchstring').value = '';
        fetch = () => Promise.resolve({ok: true, json: () => Promise.resolve({
          files: files.map(name => ({name})), current_dir: directory
        })});
        loadFiles({autoload: false});
        await new Promise(resolve => setImmediate(resolve));
      }
      Math.random = () => 0;
    """

    def run(assertions):
        result = subprocess.run(
            [node, "-e", harness + defaults + functions
             + '\n(async () => {' + assertions + '})().catch(error => {throw error;});'],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, result.stderr

    return run


def test_shuffle_control_and_phone_styling():
    assert TEMPLATE.count('id="shuffleButton"') == 1
    assert 'onclick="toggleShuffle()"' in TEMPLATE
    assert 'aria-label="Shuffle playback order"' in TEMPLATE
    assert 'aria-pressed="false">Shuffle</button>' in TEMPLATE
    phone = TEMPLATE[TEMPLATE.rindex('@media (max-width: 640px)'):TEMPLATE.index('</style>')]
    assert '.playback-controls {\n        gap: 1px;\n        flex-wrap: nowrap;' in phone
    for name, active in (('repeat', 'repeat'), ('continue', 'continue'), ('shuffle', 'shuffle')):
        assert f'.control-bar #{name}Button.{active}-on' in phone
    assert 'color: #4ade80;' in phone
    assert 'height: 38px;\n        padding: 0 3px;\n        flex-shrink: 0;' in phone
    labels = playback_function('updatePlaybackControlLabels')
    assert 'Rep ${' not in labels
    assert 'Rep Off' not in labels
    assert 'Rep On' not in labels


def test_labels_toggle_and_reload_defaults(run_playback):
    run_playback("""
      assert.equal(isShuffling, false);
      assert.equal(isRepeating, false);
      assert.equal(isContinuing, false);
      updatePlaybackControlLabels();
      assert.equal(buttons.shuffleButton.textContent, 'Shuffle');
      assert.equal(buttons.repeatButton.textContent, 'Repeat Off');
      assert.equal(buttons.continueButton.textContent, 'Auto Off');
      mobilePlaybackControls.matches = true;
      for (const enabled of [false, true]) {
        setRepeat(enabled);
        setContinue(enabled);
        if (isShuffling !== enabled) toggleShuffle();
        assert.equal(buttons.repeatButton.textContent, 'Rep');
        assert.equal(buttons.continueButton.textContent, 'Auto');
        assert.equal(buttons.shuffleButton.textContent, 'Rnd');
        for (const [id, cls] of [['repeat', 'repeat'], ['continue', 'continue'],
                                 ['shuffle', 'shuffle']]) {
          const button = buttons[id + 'Button'];
          assert.equal(button.classes.has(cls + '-on'), enabled);
          assert.equal(button.attributes['aria-pressed'], String(enabled));
        }
      }
      toggleShuffle();
      assert.equal(isShuffling, false);
      mobilePlaybackControls.matches = false; // Tablet/desktop share labels.
      updatePlaybackControlLabels();
      assert.equal(buttons.shuffleButton.textContent, 'Shuffle');
    """)


@pytest.mark.parametrize("scenario", [
    "isContinuing = true; playNextFileIfContinue(); assert.equal(loads[0].name, 'c.webm');",
    "isContinuing = true; toggleShuffle(); playNextFileIfContinue(); "
    "assert.equal(loads[0].name, visibleNames()[1]); assert.equal(loads[0].autoplay, true); "
    "assert.equal(loads[0].analysisWaitReason, 'continue');",
    "isShuffling = true; playNextFileIfContinue(); assert.equal(loads.length, 0);",
    "isContinuing = true; Math.random = () => 0.999; toggleShuffle(); "
    "playNextFileIfContinue(); assert.equal(loads[0].name, 'a.mp3');",
    "isContinuing = true; selectedFileName = 'a.mp3'; toggleShuffle(); "
    "playNextFileIfContinue(); assert.notEqual(loads[0].name, loadedFileName);",
    "isContinuing = true; currentFiles = [{name: 'b.mp4'}]; toggleShuffle(); "
    "playNextFileIfContinue(); assert.equal(loads.length, 0); assert.equal(isContinuing, false);",
    "isContinuing = true; isShuffling = true; currentFiles = []; "
    "playNextFileIfContinue(); assert.equal(loads.length, 0);",
    "isContinuing = true; selectedFileName = 'c.webm'; playNextFileIfContinue(); "
    "assert.equal(loads.length, 0); assert.equal(isContinuing, false); "
    "assert.equal(fileStatus.innerText, 'End of directory');",
    "isContinuing = true; loadedFileName = selectedFileName = 'c.webm'; toggleShuffle(); "
    "playNextFileIfContinue(); assert.equal(loads[0].name, visibleNames()[1]);",
    "isContinuing = true; isShuffling = true; toggleRepeat(); "
    "assert.equal(video.loop, true); assert.equal(isContinuing, false); "
    "playNextFileIfContinue(); assert.equal(loads.length, 0); "
    "isContinuing = true; playNextFileIfContinue(); assert.equal(loads.length, 0);",
    "toggleShuffle(); toggleRepeat(); toggleContinue(); "
    "assert.equal(isRepeating, false); assert.equal(video.loop, false); "
    "playNextFileIfContinue(); assert.equal(loads[0].name, visibleNames()[1]);",
    "isShuffling = true; toggleContinue(); toggleLoop(); "
    "assert.equal(isRepeating, false); assert.equal(isContinuing, false); "
    "playNextFileIfContinue(); assert.equal(loads.length, 0);",
    "toggleShuffle(); navigateFile(1); navigateFile(-1); "
    "assert.equal(loads[0].name, visibleNames()[1]); assert.equal(loads[1].name, visibleNames()[0]);",
    "toggleShuffle(); navigateFile(1); assert.equal(loads[0].name, visibleNames()[1]);",
    "isContinuing = true; isShuffling = true; pendingAnalysisLoad = {filename: 'a.mp3'}; "
    "playNextFileIfContinue(); assert.equal(loads.length, 0);",
    "isContinuing = true; isShuffling = true; loadRequestInFlight = true; "
    "playNextFileIfContinue(); assert.equal(loads.length, 0);",
    "isContinuing = true; isShuffling = true; loadIntentQueue = [{}]; "
    "playNextFileIfContinue(); assert.equal(loads.length, 0);",
])
def test_automatic_and_manual_playback(run_playback, scenario):
    run_playback(scenario)


def test_file_view_order_toggle_and_current_marker(run_playback):
    run_playback("""
      renderBrowserTable(currentDirectories, currentFiles);
      assert.deepEqual(visibleNames(), ['a.mp3', 'b.mp4', 'c.webm']);
      assert.equal(currentRow().dataset.filename, 'b.mp4');
      assert.equal(currentRow().attributes['aria-current'], 'true');
      selectedFileName = 'a.mp3'; // A pending selection is distinct from loaded media.
      toggleShuffle();
      assert.deepEqual(visibleNames(), ['b.mp4', 'c.webm', 'a.mp3']);
      assert.equal(currentRow().dataset.filename, 'b.mp4');
      assert.equal(selectedFileName, 'b.mp4');
      assert.equal(loadedFileName, 'b.mp4');
      assert.equal(loads.length, 0); // Toggling never restarts playback.
      const shuffled = visibleNames();
      sortBrowserEntries();
      renderBrowserTable(currentDirectories, currentFiles);
      assert.deepEqual(visibleNames(), shuffled);
      toggleShuffle();
      assert.deepEqual(visibleNames(), ['a.mp3', 'b.mp4', 'c.webm']);
      assert.equal(currentRow().dataset.filename, 'b.mp4');
      assert.equal(selectedFileName, 'b.mp4');
      assert.equal(loads.length, 0);
      sortDirection = 'desc';
      toggleShuffle(); toggleShuffle();
      assert.deepEqual(visibleNames(), ['c.webm', 'b.mp4', 'a.mp3']);
    """)


def test_current_marker_after_navigation_and_scrolling(run_playback):
    run_playback("""
      toggleShuffle();
      isContinuing = true;
      const next = visibleNames()[1];
      Math.random = () => {throw new Error('Advancement must not reshuffle');};
      playNextFileIfContinue();
      assert.equal(loads[0].name, next);
      assert.equal(currentRow().dataset.filename, 'b.mp4'); // Still loaded until activation.
      loadedFileName = next;
      updateCurrentFileRow(true); // Successful activation uses this same call.
      assert.equal(currentRow().dataset.filename, next);
      assert.equal(fileTableBody.querySelectorAll('.file-row.current').length, 1);
      assert.deepEqual(scrolls.at(-1), {name: next, block: 'nearest', inline: 'nearest'});
      const count = scrolls.length;
      updateCurrentFileRow(); updateNavigationButtons(); updatePlaybackControlLabels();
      assert.equal(scrolls.length, count); // Ordinary updates do not force scrolling.
      toggleFilesPanel(true);
      assert.equal(scrolls.length, count + 1);
      toggleFilesPanel(false);
      assert.equal(scrolls.length, count + 1);
      toggleMobileMenu(true);
      assert.equal(scrolls.length, count + 2);
      renderBrowserTable(currentDirectories, currentFiles);
      assert.equal(scrolls.length, count + 3);
      assert.equal(currentRow().dataset.filename, next);
      currentDirectory = '/other';
      renderBrowserTable(currentDirectories, currentFiles);
      assert.equal(currentRow(), undefined); // Same basename in another directory is not current.
      assert.equal(scrolls.length, count + 3);
    """)


def test_shuffle_refresh_preserves_order_and_rebuilds_changed_set(run_playback):
    run_playback("""
      toggleShuffle();
      const before = visibleNames();
      Math.random = () => {throw new Error('Same-set refresh must preserve permutation');};
      await refresh(['a.mp3', 'b.mp4', 'c.webm']);
      assert.deepEqual(visibleNames(), before);
      assert.equal(currentRow().dataset.filename, 'b.mp4');
      Math.random = () => 0;
      await refresh(['a.mp3', 'b.mp4', 'd.mp3', 'e.mp3']);
      assert.equal(visibleNames()[0], 'b.mp4');
      assert.deepEqual([...visibleNames()].sort(), ['a.mp3', 'b.mp4', 'd.mp3', 'e.mp3']);
      assert.equal(currentRow().dataset.filename, 'b.mp4');
      assert.equal(loads.length, 0);
      await refresh(['a.mp3', 'd.mp3']); // Loaded track filtered/removed.
      assert.equal(currentRow(), undefined);
      assert.deepEqual([...visibleNames()].sort(), ['a.mp3', 'd.mp3']);
      await refresh([]);
      assert.equal(currentFiles.length, 0);
      assert.equal(currentRow(), undefined);
      currentFiles = [{name: 'b.mp4'}];
      renderBrowserTable([], currentFiles);
      assert.equal(currentRow().dataset.filename, 'b.mp4');
    """)


def test_shuffled_end_stops_without_wrap(run_playback):
    run_playback("""
      toggleShuffle();
      isContinuing = true;
      selectedFileName = loadedFileName = visibleNames().at(-1);
      updateNavigationButtons();
      assert.equal(nextFileButton.disabled, true);
      playNextFileIfContinue();
      assert.equal(loads.length, 0);
      assert.equal(isContinuing, false);
      assert.equal(fileStatus.innerText, 'End of directory');
      assert.equal(isShuffling, true);
    """)


def test_manual_selection_marks_loaded_track_until_new_track_is_ready(run_playback):
    run_playback("""
      renderBrowserTable(currentDirectories, currentFiles);
      fileTableBody.children[0].listeners.click();
      assert.equal(loads[0].name, 'a.mp3');
      assert.equal(loads[0].autoplay, true);
      assert.equal(currentRow().dataset.filename, 'b.mp4');
      assert.equal(fileTableBody.children[0].classList.contains('selected'), true);
      loadedFileName = 'a.mp3';
      updateCurrentFileRow(true);
      assert.equal(currentRow().dataset.filename, 'a.mp3');
      assert.equal(scrolls.at(-1).name, 'a.mp3');
    """)


def test_shuffle_without_loaded_track_and_directory_change(run_playback):
    run_playback("""
      loadedFileName = '';
      toggleShuffle();
      assert.deepEqual([...visibleNames()].sort(), ['a.mp3', 'b.mp4', 'c.webm']);
      assert.equal(currentRow(), undefined);
      assert.equal(loads.length, 0);
      loadedFileName = 'b.mp4';
      await refresh(['a.mp3', 'b.mp4', 'c.webm'], '/other');
      assert.equal(currentRow(), undefined);
      assert.equal(currentFiles.length, 3);
      assert.equal(loads.length, 0);
    """)


def test_current_row_activation_is_separate_from_timed_playback_updates():
    activation = playback_function('processNextLoadIntent')
    assert 'loadedFileDirectory = dirname;\n        updateCurrentFileRow(true);' in activation
    assert 'scrollCurrentFileIntoView' not in playback_function('syncPlaybackPosition')
    assert 'updateCurrentFileRow' not in playback_function('syncPlaybackPosition')
    assert '.browser-row.current td:first-child' in TEMPLATE
