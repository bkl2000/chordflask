"""Run real Score synchronization and existing view controls with a small DOM."""

from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_score_midi_menu_visibility(tmp_path):
    if not shutil.which('node'):
        pytest.skip('Node is required for the focused JavaScript regression')
    home = (ROOT / 'chordflask/templates/home.html').read_text()
    assert 'data-export-format="score-midi" hidden>Score MIDI</button>' in home
    start = home.index('available => {', home.index('const scoreDisplay ='))
    end = home.index('\n    });', start)
    callback = home[start:end] + '\n}'
    harness = r'''
const assert = require('node:assert/strict');
const button = {hidden: true};
const document = {getElementById: () => button};
let scoreViewAvailable = false, songViewMode = 'grid', preferredSongViewMode = 'grid', editMode = false;
const prepareActions = {score: {state: 'idle'}}, desktopPrepare = {matches: true};
const scoreDisplay = {metadata: null, sync() {}};
function updatePrepareButtons() {}
function applySongViewMode() {}
'''
    checks = r'''
changed(false); assert.equal(button.hidden, true);
scoreDisplay.metadata = {score_midi_available: true};
changed(true); assert.equal(button.hidden, false);
scoreDisplay.metadata = {score_midi_available: false};
changed(true); assert.equal(button.hidden, true);
scoreDisplay.metadata = {score_midi_available: true};
changed(true); assert.equal(button.hidden, false);
changed(false); assert.equal(button.hidden, true);
scoreDisplay.metadata = null;
changed(false); assert.equal(button.hidden, true);
'''
    script = tmp_path / 'score-midi-menu.cjs'
    script.write_text(harness + 'const changed = ' + callback + ';\n' + checks)
    result = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_score_sync_and_view_switches(tmp_path):
    if not shutil.which('node'):
        pytest.skip('Node is required for the focused JavaScript regression')
    home = (ROOT / 'chordflask/templates/home.html').read_text()
    controls = home[home.index('    function updateSongViewControl()'):home.index('    function resetSongView(')]
    reset = home[home.index('    function resetSongView('):home.index('    function appendSongText(')]
    switching = home[home.index('    function setSongViewMode('):home.index('    function updateLyricsHighlight(')]
    viewport_control = home[home.index('    function handleSongViewportChange()'):home.index('    function updateTrackSelectors(')]
    js = (ROOT / 'chordflask/static/score.js').read_text()
    harness = r'''
const assert = require('node:assert/strict');
class Element {
  constructor() { this.hidden = false; this.style = {}; this.children = []; this.attrs = {}; this.events = {};
    this.classList = {contains: x => this.system && x === 'system', toggle: () => {}}; }
  setAttribute(k,v) {this.attrs[k]=v;}
  addEventListener(k,v) {this.events[k]=v;}
  appendChild(el) {this.children.push(el);}
  replaceChildren(...els) {this.children=els;}
  querySelector() {return this.children.find(el => el.type === 'image/svg+xml');}
  getBoundingClientRect() {return {top: this.top || 0, height: 60};}
  getBBox() {return {x: 20, y: this.top || 0, width: 100, height: 80};}
  insertBefore(el) {this.children.unshift(el);}
  remove() {this.removed=true;}
}
const document = {createElement: () => new Element(), createElementNS: () => new Element()};
const viewport = new Element(); viewport.clientHeight=300; viewport.scrollTop=0;
const container = new Element(); container.parentElement=viewport;
let seconds=1;
const display = new ScoreDisplay(container, () => seconds, () => {});
const rows = [
 {number:0, start_seconds:1,end_seconds:2,page:1,svg_id:'pickup'},
 {number:1, start_seconds:2,end_seconds:4,page:1,svg_id:'m1'},
 {number:2, start_seconds:4,end_seconds:6,page:1,svg_id:'m2'},
 {number:3, start_seconds:6,end_seconds:8,page:2,svg_id:'m3'}];
assert.equal(scoreMeasureAt(rows,0),null);
assert.equal(scoreMeasureAt(rows,1).number,0);
assert.equal(scoreMeasureAt(rows,2).number,1);
assert.equal(scoreMeasureAt(rows,8),null);
display.metadata={pages:2, generation:'abc', measures:rows}; display.media='song';
const line1=new Element(); line1.system=true;
const line2=new Element(); line2.system=true; line2.top=400;
const measures={pickup:new Element(),m1:new Element(),m2:new Element(),m3:new Element()};
measures.pickup.parentElement=line1; measures.m1.parentElement=line1;
measures.m2.parentElement=line2; measures.m3.parentElement=line1;
function loaded() {
 const object=container.querySelector();
 const root=new Element(); root.localName='svg'; root.viewBox={baseVal:{width:100,height:200}};
 object.contentDocument={documentElement:root, getElementById:id=>measures[id], createElementNS:document.createElementNS};
 object.events.load();
}
display.sync(); loaded();
assert.equal(display.page,1); assert.equal(display.measure,measures.pickup);
const highlight=display.highlight;
display.sync(); assert.equal(display.highlight,highlight); // Pause/resume leaves the page still.
// Previous/Next survives repeated 90-ms ticks within the same measure.
container.children[0].children[1].events.click(); loaded();
for (let i=0;i<20;i++) display.sync();
assert.equal(display.page,2); assert.equal(display.highlight,null);
seconds=1.9; display.sync(); assert.equal(display.page,2);
seconds=2; display.sync(); assert.equal(display.page,1); loaded();
// Manual Previous on page two remains until the playback measure changes.
seconds=6; display.sync(); loaded();
container.children[0].children[0].events.click(); loaded();
display.sync(); assert.equal(display.page,1);
seconds=1; display.sync(); loaded(); // Repeat.
// Before the first measured interval, browsing also remains stable.
seconds=0; display.sync();
display.showPage(2); loaded(); display.sync(); assert.equal(display.page,2);
seconds=1; display.sync(); assert.equal(display.page,1); loaded();
viewport.scrollTop=17; seconds=2; display.sync();
assert.equal(viewport.scrollTop,17); // Same notation line, no scroll.
seconds=4; display.sync(); assert.ok(viewport.scrollTop>17);
seconds=2; display.sync(); assert.equal(display.line,line1); // Seek backwards.
seconds=6; display.sync(); assert.equal(display.page,2); loaded();
seconds=1; display.sync(); assert.equal(display.page,1); loaded(); // Repeat/pickup.
seconds=9; display.sync(); assert.equal(display.highlight,null);
display.showPage(0); assert.equal(display.page,1);
display.showPage(3); assert.equal(display.page,1);
const staleObject=container.querySelector(); display.reset(); staleObject.events.load();
assert.equal(display.document,null); // Old page after song change.

let songViewGeneration=0, songSheetCache={}, lyricChordMarkers=[], lyricLineMarkers=[];
let activeLyricMarkerIndex=-1, activeLyricLineIndex=-1, activeLyricBeatIndex=null;
let songViewAvailable=true, scoreViewAvailable=true;
let desktopSongView={matches:true}, desktopPrepare={matches:true};
let songViewMode='grid', preferredSongViewMode='grid', editMode=false, editRequestInFlight=false;
let songSheetRequestInFlight=false, lyricsVersions=['v1'];
let songViewSwitch=new Element(), lyricsVersionSelect=new Element(), gridViewButton=new Element();
let songViewButton=new Element(), scoreViewButton=new Element(), chordPanel=new Element();
let chordViewTitle=new Element(), callbackOutput=new Element(), songSheet=new Element(), scoreSheet=new Element();
let lyricsMedia='song', loadSongSheet=()=>{};
let scoreResets=0, scoreLoads=0;
let scoreDisplay={sync:()=>{}, reset:()=>{scoreResets++;}, media:'song', metadata:{}, load:()=>{scoreLoads++;}}, storageKeys={preferredSongView:'view'};
let localStorage={setItem:(_,value)=>{localStorage.value=value;}};
let gridSyncs=0;
let setExportMenuOpen=()=>{}, refreshSongSheetLabels=()=>{}, syncPlaybackPosition=()=>{gridSyncs++;};
let editGridContainer=new Element(), editTools=new Element();
document.getElementById=id=>id==='editTools'?editTools:editGridContainer;
'''
    checks = r'''
setSongViewMode('score'); assert.equal(songViewMode,'score'); assert.equal(localStorage.value,'score');
assert.equal(scoreSheet.hidden,false); assert.equal(songSheet.hidden,true); assert.equal(callbackOutput.hidden,true);
assert.equal(chordViewTitle.textContent,'Score'); assert.equal(editTools.hidden,true);
resetSongView(true, false); assert.equal(songViewMode,'score');
assert.equal(scoreViewAvailable,true); assert.equal(scoreResets,0); assert.equal(scoreLoads,0);
setSongViewMode('song'); assert.equal(songViewMode,'song'); assert.equal(songSheet.hidden,false);
assert.equal(chordViewTitle.textContent,'Lyrics'); assert.equal(editTools.hidden,true);
const beforeGrid=gridSyncs;
setSongViewMode('grid'); assert.equal(songViewMode,'grid'); assert.equal(callbackOutput.hidden,false);
assert.equal(gridSyncs,beforeGrid+1); assert.equal(chordViewTitle.textContent,'Grid');
// Tools are visible only in Grid + Edit; neither other view can expose them.
for (const mode of ['grid','song','score']) {
 for (const editing of [false,true]) {
  songViewMode=mode; editMode=editing; applySongViewMode();
  assert.equal(editTools.hidden,mode!=='grid'||!editing);
  assert.equal(editGridContainer.hidden,mode!=='grid'||!editing);
  assert.equal(callbackOutput.hidden,mode!=='grid'||editing);
 }
}
songViewMode='grid'; editMode=true;
setSongViewMode('song'); assert.equal(songViewMode,'grid');
setSongViewMode('score'); assert.equal(songViewMode,'grid');
editMode=false; applySongViewMode();
scoreViewAvailable=false; updateSongViewControl(); assert.equal(scoreViewButton.hidden,true);
setSongViewMode('score'); assert.equal(songViewMode,'grid');
scoreViewAvailable=true; desktopPrepare.matches=false; updateSongViewControl(); assert.equal(scoreViewButton.hidden,true);
setSongViewMode('score'); assert.equal(songViewMode,'grid');
desktopPrepare.matches=true; editMode=true; setSongViewMode('score'); assert.equal(songViewMode,'grid');
editMode=false; setSongViewMode('score'); desktopPrepare.matches=false; handleSongViewportChange();
assert.equal(songViewMode,'grid'); assert.equal(preferredSongViewMode,'score');
desktopPrepare.matches=true; handleSongViewportChange(); assert.equal(songViewMode,'score');
const beforeScoreReturn=gridSyncs; setSongViewMode('grid');
assert.equal(gridSyncs,beforeScoreReturn+1); assert.equal(callbackOutput.hidden,false);
(async () => {
 let resolveOld;
 let responses = [];
 global.fetch = () => new Promise(resolve => { resolveOld=resolve; });
 const asyncDisplay = new ScoreDisplay(container, () => 0, available => responses.push(available));
 const old = asyncDisplay.load('old.mp3');
 asyncDisplay.reset();
 resolveOld({ok:true, json:async () => ({pages:1,measures:rows})});
 await old;
 assert.equal(asyncDisplay.metadata,null); assert.deepEqual(responses,[]);
 global.fetch = async () => ({ok:false});
 await asyncDisplay.load('missing.mp3'); assert.deepEqual(responses,[false]);
 global.fetch = async () => ({ok:true,json:async()=>({pages:2,measures:rows})});
 await asyncDisplay.load('new.mp3'); assert.deepEqual(responses,[false,true]);
 assert.equal(asyncDisplay.metadata.pages,2);
})().catch(error => {console.error(error);process.exitCode=1;});
'''
    script = tmp_path / 'score-test.cjs'
    script.write_text(js + harness + controls + reset + switching + viewport_control + checks)
    result = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
