"""Exercise the Grid's DOM updates without a browser dependency."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


TEMPLATE = Path(__file__).resolve().parents[1] / 'chordflask/templates/home.html'


def test_grid_dom_content_current_state_and_follow():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is unavailable')
    template = TEMPLATE.read_text()
    renderer = template.split('    function renderBeatGrid(', 1)[1].split(
        '    function renderCallbackData(', 1
    )[0]
    renderer = 'function renderBeatGrid(' + renderer
    fixture = {'columns': 8, 'compact_columns': 4, 'cells': [
        {'index': i, 'chord': chord, 'downbeat': i in [0, 3],
         'repeat': i == 7, 'compact_row_start': i == 4}
        for i, chord in enumerate(['F', 'Bbmaj7', 'Ebmaj7', '-', 'N', 'X', 'Db6', 'Db6'])
    ]}
    script = r'''
const assert = require('node:assert/strict');
class Element {
  constructor() {
    this.children = []; this.attrs = {}; this.dataset = {}; this.styles = {};
    this.classes = new Set();
    this.classList = {add: x => this.classes.add(x), remove: x => this.classes.delete(x)};
    this.style = {setProperty: (k, v) => this.styles[k] = v};
  }
  setAttribute(k, v) {this.attrs[k] = v;}
  removeAttribute(k) {delete this.attrs[k];}
  appendChild(c) {this.children.push(c);}
  get firstChild() {return this.children[0];}
  replaceChildren(fragment) {this.children = fragment.children; replacements++;}
}
let replacements = 0;
const document = {createElement: () => new Element(), createDocumentFragment: () => new Element()};
const callbackOutput = new Element();
const callbackContainer = {scrollTop: 100};
let songViewMode = 'grid';
let displayedGridKey = null, activeGridCell = null, gridCells = new Map();
const isNarrowViewport = () => false;
''' + renderer + '\nconst grid = ' + json.dumps(fixture) + r''';
renderBeatGrid(grid, 0);
const original = [...callbackOutput.children];
assert.equal(callbackContainer.scrollTop, 0);
assert.equal(callbackOutput.styles['--grid-columns'], 8);
assert.equal(callbackOutput.styles['--compact-columns'], 4);
assert.equal(original[1].children[0].textContent, 'Bbmaj7');
assert.equal(original[2].children[0].textContent, 'Ebmaj7');
assert.equal(original[3].children[0].textContent, '');
assert.equal(original[3].dataset.chord, '-');
assert.equal(original[4].children[0].textContent, '');
assert.match(original[4].attrs['aria-label'], /No chord \(N\)/);
assert.equal(original[5].children[0].textContent, 'X');
assert.match(original[5].attrs['aria-label'], /Unknown chord/);
assert.match(original[7].attrs['aria-label'], /Held chord Db6/);
assert(original[3].classes.has('bar-start'));
assert(!original[4].classes.has('bar-start'));
callbackContainer.scrollTop = 42;
renderBeatGrid(JSON.parse(JSON.stringify(grid)), 3);
assert.equal(replacements, 1);
assert.deepEqual(callbackOutput.children, original);
assert.equal(callbackContainer.scrollTop, 42);
assert(!original[0].classes.has('current-beat'));
assert(!('aria-current' in original[0].attrs));
assert(original[3].classes.has('current-beat'));
assert.equal(original[3].attrs['aria-current'], 'true');
assert.equal(original[3].children[0].textContent, '');
renderBeatGrid(grid, 3);
assert.equal(replacements, 1);
const nextGrid = {...grid, cells: grid.cells.map(c => ({...c, index: c.index + 8}))};
renderBeatGrid(nextGrid, 8);
assert.equal(replacements, 2);
assert.equal(callbackContainer.scrollTop, 0);
songViewMode = 'song';
callbackContainer.scrollTop = 60;
renderBeatGrid(grid, 2);
assert.equal(callbackContainer.scrollTop, 60);
// Loading clears the container; the same grid must still render again.
callbackOutput.children = [];
renderBeatGrid(grid, 2);
assert.equal(replacements, 4);
assert.equal(callbackOutput.children.length, 8);
assert(!callbackOutput.children.some(c => /[\[\]]/.test(c.children[0].textContent)));
'''
    result = subprocess.run([node, '-e', script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_grid_css_uses_equal_tracks_and_non_layout_playhead():
    template = TEMPLATE.read_text()
    css = template.split('/* Grid presentation:', 1)[1].split('</style>', 1)[0]
    assert 'repeat(var(--grid-columns, 8), minmax(0, 1fr))' in css
    assert 'repeat(var(--compact-columns, 4), minmax(0, 1fr))' in css
    assert 'width: 100%' in css
    assert 'overflow-wrap: anywhere' in css
    assert 'calc(150cqw / var(--label-length, 1))' in css
    assert '.beat-cell.bar-start::before' in css
    assert '.beat-cell.current-beat::after' in css
    playhead = css.split('.beat-cell.current-beat::after', 1)[1].split('}', 1)[0]
    assert 'position: absolute' in playhead
    assert 'var(--accent)' in playhead
    assert 'nth-child' not in css  # bar boundaries never inferred from groups of four


@pytest.mark.parametrize('columns', [3, 4])
def test_grid_follow_target_handles_rows_seeks_and_boundaries(columns):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is unavailable')
    source = TEMPLATE.read_text()
    follow = 'function followBeatGrid(' + source.split(
        '    function followBeatGrid(', 1
    )[1].split('    function renderCallbackData(', 1)[0]
    script = r'''
const assert = require('node:assert/strict');
let narrow = true, songViewMode = 'grid', editMode = false, activeGridCell = null;
const isNarrowViewport = () => narrow;
let writes = [], top = 0, reads = 0;
const callbackContainer = {
  clientTop: 0, clientHeight: 308, scrollHeight: 872,
  get scrollTop() {return top;},
  set scrollTop(value) {top = value; writes.push(value);},
  getBoundingClientRect() {return {top: 100};}
};
const getComputedStyle = () => ({paddingTop: '4px', paddingBottom: '4px'});
const columns = COLUMNS;
let gridCells = new Map();
function fixture(start = 0, count = 18 * columns) {
  gridCells = new Map();
  const cells = Array.from({length: count}, (_, offset) => {
    const beat = {index: start + offset};
    gridCells.set(beat.index, {getBoundingClientRect() {
      reads++;
      const y = 104 + Math.floor(offset / columns) * 48 - top;
      return {top: y, bottom: y + 48, height: 48};
    }});
    return beat;
  });
  callbackContainer.scrollHeight = Math.ceil(count / columns) * 48 + 8;
  return {compact_columns: columns, cells};
}
function update(grid, index, preferredRowFromTop = null) {
  activeGridCell = gridCells.get(index);
  followBeatGrid(grid, index, preferredRowFromTop);
}
function nextRowFits(grid, index) {
  const offset = grid.cells.findIndex(c => c.index === index);
  const next = grid.cells[(Math.floor(offset / columns) + 1) * columns];
  if (next) assert(gridCells.get(next.index).getBoundingClientRect().bottom <= 404);
}
''' .replace('COLUMNS', str(columns)) + follow + r'''
let grid = fixture();
// The default/null target retains the old minimal row-follow behavior.
// Upper/middle/current fifth row and its last beat are safe: no movement.
for (const index of [0, 2 * columns, 5 * columns - 1]) update(grid, index);
assert.deepEqual(writes, []);
// Sixth row: the upcoming seventh row would be partly hidden. Step once now.
update(grid, 5 * columns);
assert.deepEqual(writes, [48]);
nextRowFits(grid, 5 * columns);
update(grid, 6 * columns - 1);
assert.deepEqual(writes, [48]);
nextRowFits(grid, 6 * columns - 1);
// Existing two-bar window advance: new DOM starts two phone rows later.
// Its scroll reset + updated window advance the visible content one row.
top = 0;
grid = fixture(2 * columns);
update(grid, 6 * columns);
assert.deepEqual(writes, [48]);
nextRowFits(grid, 6 * columns);
update(grid, 6 * columns + 1);
assert.deepEqual(writes, [48]);
// Far forward seek within a supplied window: measured row-aligned advance.
grid = fixture(); top = 0; writes = [];
update(grid, 10 * columns);
assert.equal(top, 6 * 48);
assert.equal(writes.length, 1);
nextRowFits(grid, 10 * columns);
update(grid, 10 * columns + 1);
assert.equal(writes.length, 1);
// Backward seek brings the earlier row back into view in one step.
update(grid, columns);
assert.equal(top, 48);
assert.equal(writes.length, 2);
nextRowFits(grid, columns);
// Partial final row: no nonexistent lookahead and no blank overscroll.
grid = fixture(0, 8 * columns - 1); top = 0; writes = [];
update(grid, 7 * columns - 1);
nextRowFits(grid, 7 * columns - 1);
assert(top <= callbackContainer.scrollHeight - callbackContainer.clientHeight);
update(grid, 8 * columns - 2);
assert.equal(writes.length, 1);
assert(activeGridCell.getBoundingClientRect().bottom <= 404);
// When only one row fits, current content takes priority over lookahead.
grid = fixture(); top = 0; callbackContainer.clientHeight = 56;
update(grid, 5 * columns);
assert.equal(top, 5 * 48);
assert(activeGridCell.getBoundingClientRect().top >= 104);
// A preferred second-row target applies only when movement is needed.
callbackContainer.clientHeight = 308;
grid = fixture(); top = 0; writes = [];
update(grid, 0, 1);
assert.equal(top, 0);  // no artificial top padding at song start
assert.deepEqual(writes, []);
update(grid, 5 * columns, 1);
assert.equal(top, 4 * 48);
assert.equal(activeGridCell.getBoundingClientRect().top, 104 + 48);
update(grid, 5 * columns, 1);
assert.equal(writes.length, 1);  // repeated update does not double-step
// Every beat in each subsequent row stays at one stable preferred position.
grid = fixture(); top = 0; writes = [];
const positions = [];
for (let row = 4; row <= 8; row++) {
  for (let beat = 0; beat < columns; beat++) {
    update(grid, row * columns + beat, 1);
    positions.push(top);
  }
}
assert.deepEqual(writes, [3, 4, 5, 6, 7].map(row => row * 48));
assert.deepEqual(positions, [3, 4, 5, 6, 7].flatMap(
  row => Array(columns).fill(row * 48)
));
// Far-forward and backward seeks land on the preferred rendered row.
grid = fixture(); top = 0; writes = [];
update(grid, 10 * columns, 1);
assert.equal(top, 9 * 48);
assert.equal(writes.length, 1);
update(grid, 10 * columns + 1, 1);
assert.equal(top, 9 * 48);
assert.equal(writes.length, 1);
update(grid, columns, 1);
assert.equal(top, 0);
assert.equal(writes.length, 2);
assert.equal(activeGridCell.getBoundingClientRect().top, 104 + 48);
update(grid, columns + 1, 1);
assert.equal(top, 0);
assert.equal(writes.length, 2);
// At song end the browser scroll range wins over the preferred position.
grid = fixture(0, 8 * columns - 1); top = 0; writes = [];
update(grid, 7 * columns - 1, 1);
assert.equal(top, callbackContainer.scrollHeight - callbackContainer.clientHeight);
update(grid, 8 * columns - 2, 1);
assert.equal(writes.length, 1);
assert(activeGridCell.getBoundingClientRect().bottom <= 404);
// Desktop/tablet and Lyrics/Edit views still do no geometry reads or scrolling.
for (const mode of ['desktop', 'tablet', 'lyrics', 'edit']) {
  narrow = !['desktop', 'tablet'].includes(mode);
  songViewMode = mode === 'lyrics' ? 'song' : 'grid';
  editMode = mode === 'edit';
  top = 0; writes = []; reads = 0;
  update(grid, 6 * columns, 1);
  assert.deepEqual(writes, []);
  assert.equal(reads, 0);
}
'''
    result = subprocess.run([node, '-e', script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr

    # Desktop/tablet pass null, while phones use the internal target.
    renderer = source.split('    function renderBeatGrid(', 1)[1].split(
        '    function followBeatGrid(', 1
    )[0]
    assert (
        'isNarrowViewport() ? PHONE_GRID_FOLLOW_ROW : null' in renderer
    )
    assert 'followBeatGrid(grid, activeIndex, preferredRowFromTop)' in renderer
    assert 'const PHONE_GRID_FOLLOW_ROW = 1;' in source
