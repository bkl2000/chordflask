"""Per-browser client playback state for the ChordFlask web server.

Each browser cookie jar maps to one in-memory ``ClientState`` so independent
browsers/devices on the same LAN can play and control different media without
interfering. The state is intentionally process-local and session-scoped: it
is lost when the server restarts and is not shared across multiple worker
processes.

Two tabs or windows in the same browser profile share the same cookie and
therefore intentionally share one ``ClientState``. True per-tab isolation is
out of scope.
"""

import threading
import time

# Inactive client states are dropped during opportunistic sweeps after this
# many seconds. Kept as an internal constant; not configurable via environment
# variables or command-line options.
TTL_SECONDS = 24 * 3600

# Sweeps only run once the registry grows past this size and only once per
# ``SWEEP_INTERVAL_SECONDS``. Both are internal tuning constants.
SWEEP_THRESHOLD = 50
SWEEP_INTERVAL_SECONDS = 60.0


class ClientState:
    """All playback, display, and editing state private to one browser."""

    def __init__(self):
        self.file_repr = None
        self.player = None
        self.current_position = 0
        self.old_current_position = 0
        self.old_grid_mode = "compact"
        self.semitones = 0
        self.use_unicode = False
        self.prefer_flats = True
        self.repeat_mode = "changes"
        self.json_mtime_ns = None
        self.last_used = time.monotonic()
        self.lock = threading.Lock()


class ClientRegistry:
    """In-memory mapping from an opaque client id to its ``ClientState``.

    Registry operations are guarded by one short-lived lock that is never held
    while a request mutates a ``ClientState`` or streams a media response.
    Those use the per-``ClientState`` lock instead.
    """

    def __init__(self):
        self._states = {}
        self._lock = threading.Lock()
        self._last_sweep = time.monotonic()

    def get_or_create(self, client_id):
        with self._lock:
            state = self._states.get(client_id)
            if state is None:
                state = ClientState()
                self._states[client_id] = state
            return state

    def get(self, client_id):
        with self._lock:
            return self._states.get(client_id)

    def sweep(self, exclude_id=None):
        """Drop long-inactive client states (opportunistic, no scheduler)."""
        now = time.monotonic()
        with self._lock:
            if now - self._last_sweep < SWEEP_INTERVAL_SECONDS:
                return
            self._last_sweep = now
            if len(self._states) <= SWEEP_THRESHOLD:
                return
            for client_id in list(self._states):
                if client_id == exclude_id:
                    continue
                if now - self._states[client_id].last_used > TTL_SECONDS:
                    del self._states[client_id]


class PathLockRegistry:
    """One ``threading.Lock`` per analysis JSON path.

    Chord editing is a read-modify-write cycle on a shared JSON file, and the
    per-``ClientState`` locks cannot serialize two clients editing the same
    song. This process-global, keyed lock registry makes the check-and-save
    sequence atomic per file without serializing unrelated songs.
    """

    def __init__(self):
        self._locks = {}
        self._lock = threading.Lock()

    def get(self, path):
        with self._lock:
            lock = self._locks.get(path)
            if lock is None:
                lock = threading.Lock()
                self._locks[path] = lock
            return lock

