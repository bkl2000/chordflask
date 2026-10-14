/* Persisted QM intervals are audio seconds, independent of Grid display lead. */
function scoreMeasureAt(measures, seconds) {
  return measures.find(row => row.start_seconds <= seconds && seconds < row.end_seconds) || null;
}

class ScoreDisplay {
  constructor(container, clock, changed) {
    this.container = container;
    this.clock = clock;
    this.changed = changed;
    this.reset();
  }

  reset() {
    this.token = (this.token || 0) + 1;
    this.media = '';
    this.metadata = null;
    this.page = null;
    this.row = null;
    this.document = null;
    this.line = null;
    this.highlight = null;
    this.measure = null;
    this.container.replaceChildren();
  }

  async load(media) {
    this.reset();
    this.media = media;
    const token = this.token;
    try {
      const response = await fetch('/score?' + new URLSearchParams({media}), {cache: 'no-store'});
      if (!response.ok) throw new Error('Score unavailable');
      const metadata = await response.json();
      if (token !== this.token) return;
      this.metadata = metadata;
      this.changed(true);
    } catch (_) {
      if (token === this.token) this.changed(false);
    }
  }

  showPage(page) {
    if (!this.metadata || page < 1 || page > this.metadata.pages || page === this.page) return;
    this.page = page;
    this.document = null;
    this.line = null;
    this.highlight = null;
    this.measure = null;
    const token = this.token;
    const controls = document.createElement('div');
    controls.className = 'score-pages';
    for (const [label, target] of [['Previous', page - 1], ['Next', page + 1]]) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = label;
      button.disabled = target < 1 || target > this.metadata.pages;
      button.addEventListener('click', () => this.showPage(target));
      controls.appendChild(button);
    }
    const label = document.createElement('span');
    label.textContent = `Page ${page} / ${this.metadata.pages}`;
    controls.appendChild(label);
    // A separate SVG document isolates Verovio styles from the application.
    // Only the validated active-song endpoint supplies the object, never HTML.
    const object = document.createElement('object');
    object.type = 'image/svg+xml';
    object.setAttribute('aria-label', `Piano score page ${page}`);
    object.data = `/score/page/${page}?` + new URLSearchParams({
      media: this.media, generation: this.metadata.generation
    });
    object.addEventListener('load', () => {
      if (token !== this.token || this.page !== page) return;
      const doc = object.contentDocument;
      if (!doc || doc.documentElement.localName !== 'svg') {
        this.fail();
        return;
      }
      this.document = doc;
      const svg = doc.documentElement;
      const box = svg.viewBox.baseVal;
      let width = box.width || parseFloat(svg.getAttribute('width'));
      let height = box.height || parseFloat(svg.getAttribute('height'));
      if (!box.width) svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
      // Fit engraved content instead of scaling empty paper margins as well.
      const content = svg.getBBox();
      if (content.width > 0 && content.height > 0) {
        const margin = content.width * 0.025;
        width = content.width + 2 * margin;
        height = content.height + 2 * margin;
        svg.setAttribute('viewBox', `${content.x - margin} ${content.y - margin} ${width} ${height}`);
      }
      object.style.aspectRatio = `${width} / ${height}`;
      svg.setAttribute('width', '100%');
      svg.setAttribute('height', '100%');
      this.sync(false);
    });
    object.addEventListener('error', () => {
      if (token === this.token && this.page === page) this.fail();
    });
    this.container.replaceChildren(controls, object);
  }

  fail() {
    this.reset();
    this.changed(false);
  }

  sync(follow = true) {
    if (!this.metadata || this.container.hidden) return;
    const seconds = this.clock();
    const row = scoreMeasureAt(this.metadata.measures, seconds);
    const rowChanged = row !== this.row;
    if (follow) this.row = row;
    if (!row) {
      if (this.highlight) this.highlight.remove();
      this.highlight = null;
      this.measure = null;
      if (this.page === null || (follow && rowChanged && seconds < this.metadata.measures[0].start_seconds)) this.showPage(1);
      return;
    }
    if (this.page === null || (follow && rowChanged && row.page !== this.page)) this.showPage(row.page);
    if (!this.document || row.page !== this.page) return;
    const measure = this.document.getElementById(row.svg_id);
    if (!measure) { this.fail(); return; }
    if (this.measure === measure) return;
    this.measure = measure;
    if (this.highlight) this.highlight.remove();
    const box = measure.getBBox();
    const rect = this.document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    for (const [key, value] of Object.entries({x: box.x, y: box.y, width: box.width,
      height: box.height, fill: '#6aa9df', opacity: 0.16, 'pointer-events': 'none'})) {
      rect.setAttribute(key, value);
    }
    measure.insertBefore(rect, measure.firstChild);
    this.highlight = rect;
    let system = measure.parentElement;
    while (system && !system.classList.contains('system')) system = system.parentElement;
    if (system && system !== this.line) {
      this.line = system;
      const object = this.container.querySelector('object');
      const viewport = this.container.parentElement;
      const bounds = system.getBoundingClientRect();
      const top = object.getBoundingClientRect().top - viewport.getBoundingClientRect().top
        + viewport.scrollTop + bounds.top;
      const margin = viewport.clientHeight * 0.12;
      if (top < viewport.scrollTop + margin || top + bounds.height > viewport.scrollTop + viewport.clientHeight - margin) {
        viewport.scrollTop = Math.max(0, top - margin);
      }
    }
  }
}
