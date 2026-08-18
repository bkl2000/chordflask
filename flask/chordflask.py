#!/usr/bin/env python3

"""Flask application for media chord analysis and playback."""

import argparse
import logging
import math
import os
import sys
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

# Ensure the repository root (and the neutral ``chordflask_base`` package) is
# importable when this entry point is run directly as ``python flask/chordflask.py``.
_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from flask import Flask, render_template, jsonify, request, send_file, make_response

from analysis_queue import AnalysisQueue, MAX_BATCH_SIZE
from chord_markdown import download_track_slug, format_chord_markdown
from chord_sheet_pdf import ChordSheetPdfRenderer
from chordflask_config import (
    ANALYSIS_DIR_NAME, LEGACY_ANALYSIS_DIR_NAME, ALLOWED_MEDIA_ROOTS_ENV, LISTEN_ENV,
    PORT_ENV, DEBUG_ENV, DEFAULT_HOST, DEFAULT_PORT,
    SUPPORTED_MEDIA_SUFFIXES,
)
from filerepr import FileRepr  # Import FileRepr class for file path management
from ffmpeg_runtime import require_system_ffmpeg
from media_library import preferred_media_files

from mp4playerflask import MP4PlayerFlask, STEMS_AUDIO_SET_ID  # Import the MP4PlayerFlask class
from playbackview import GRID_MODES

from chordflask_base import DEMUCS_STEM_NAMES


def _load_version():
    """Read VERSION semver and append git date+hash when available."""
    if getattr(sys, "frozen", False):
        frozen_version = os.path.join(os.path.dirname(sys.executable), "VERSION")
        if os.path.isfile(frozen_version):
            return open(frozen_version).read().strip()
        return "unknown"
    script_dir = os.path.dirname(os.path.abspath(__file__))
    version_file = os.path.join(script_dir, os.pardir, "VERSION")
    base = open(version_file).read().strip() if os.path.isfile(version_file) else "unknown"
    try:
        import subprocess
        git_info = subprocess.run(
            ["git", "log", "-1", "--format=%cd %h", "--date=format:%Y-%m-%d %H:%M"],
            capture_output=True, text=True,
            cwd=os.path.join(script_dir, os.pardir),
        ).stdout.strip()
        if git_info:
            return f"{base} {git_info}"
    except Exception:
        pass
    return base


def _build_argument_parser():
    parser = argparse.ArgumentParser(description="ChordFlask chord analyzer web app")
    parser.add_argument("--listen", metavar="ADDR", default=None,
                        help="Bind address (default: %(default)s, env: CHORDIFIER_LISTEN)")
    parser.add_argument("--port", metavar="PORT", type=int, default=None,
                        help="Port (default: 5000, env: CHORDIFIER_PORT)")
    parser.add_argument("--debug", action="store_true",
                        help="Enable Flask debug mode (env: CHORDIFIER_DEBUG=1)")
    parser.add_argument("--worker", action="store_true",
                        help="Run analysis queue worker instead of web UI")
    parser.add_argument("--no-worker", action="store_true",
                        help="Run the web UI without starting an analysis worker")
    parser.add_argument("--check-vamp", action="store_true",
                        help="Verify Vamp plugins and exit")
    metric_group = parser.add_mutually_exclusive_group()
    metric_group.add_argument(
        "--metric-chords", dest="metric_chords", action="store_true", default=None,
        help="Use rhythm-aware chord display filtering (default for the web UI)",
    )
    metric_group.add_argument(
        "--no-metric-chords", dest="metric_chords", action="store_false",
        help="Use the unfiltered nearest-beat chord display",
    )
    parser.add_argument("--version", action="version",
                        version=f"ChordFlask {_load_version()}")
    return parser


def _parse_cli_args(argv=None):
    parser = _build_argument_parser()
    args = parser.parse_args(argv)

    if args.worker and args.no_worker:
        parser.error("--worker and --no-worker cannot be used together")
    if args.worker and args.metric_chords is True:
        parser.error("--metric-chords cannot be used with --worker")

    if args.worker:
        args.metric_chords = False
    else:
        args.metric_chords = args.metric_chords is not False
    return args


class FlaskMP4App:
    """
    FlaskMP4App encapsulates the entire Flask application and related logic
    into an object-oriented structure to avoid global variables and maintain better code organization.
    """

    __version__ = _load_version()

    def __init__(self, quiet=False, metric_chords=False):
        """
        Initialize the FlaskMP4App, set up initial state, routes, logging, and resources.
        """
        self.__quiet = quiet
        self.__metric_chords = metric_chords
        self.app = Flask(__name__, template_folder=self.resource_path('templates'), static_folder=self.resource_path('static'))

        # Variables to store file and player state
        self.file_repr = None
        self.player = None
        self.old_current_position = 0
        self.old_grid_mode = "compact"
        self.current_position = 0
        self.total_duration = 600  # Example: 600 seconds (10 minutes)
        self.max_lines = 23  # Limit to the last 23 lines of callback output
        self.semitones = 0  # Default value for semitone transposition
        self.use_unicode = False  # Flag to determine if Unicode representations should be used for output
        self.prefer_flats = True
        self.repeat_mode = "changes"
        self.analysis_queue = AnalysisQueue()
        self.worker_supervisor = None
        self.allowed_roots = self._parse_allowed_roots()
        self._resolve_ffmpeg()
        self.plugins_available = True

        self.stored_directories = self.default_video_directories()

        # Reduce verbosity of the werkzeug logging for Flask requests
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR)

        # Setup the routes for the Flask app
        self.setup_routes()

    def _json_body(self):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return None, (jsonify(error="Request body must be a JSON object."), 400)
        return data, None

    def _parse_allowed_roots(self):
        raw = os.environ.get(ALLOWED_MEDIA_ROOTS_ENV, "")
        if not raw.strip():
            return None
        roots = []
        for candidate in raw.split(os.pathsep):
            if not candidate.strip():
                raise ValueError(
                    f"{ALLOWED_MEDIA_ROOTS_ENV} contains an empty path entry"
                )
            resolved = Path(candidate).expanduser().resolve()
            if not resolved.is_dir():
                raise ValueError(f"Media root is not a directory: {resolved}")
            roots.append(resolved)
        return roots if roots else None

    def _resolve_ffmpeg(self):
        try:
            require_system_ffmpeg()
        except RuntimeError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            raise SystemExit(1) from None

    def _is_allowed_directory(self, directory):
        if self.allowed_roots is None:
            return True
        for root in self.allowed_roots:
            try:
                directory.relative_to(root)
                return True
            except ValueError:
                pass
        return False

    def _existing_directory(self, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("dirname must be a non-empty string")
        try:
            directory = Path(value).expanduser().resolve()
        except (OSError, RuntimeError) as error:
            raise PermissionError(f"Directory cannot be resolved: {value}") from error
        if not directory.is_dir():
            raise FileNotFoundError("Directory does not exist")
        if not self._is_allowed_directory(directory):
            raise PermissionError("Directory is outside allowed media roots")
        return directory

    def _existing_media_file(self, dirname, filename):
        directory = self._existing_directory(dirname)
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError("filename must be a non-empty string")
        filename = filename.split(" | ", 1)[0]
        if Path(filename).name != filename or filename in {".", ".."}:
            raise ValueError("filename must not contain a path")
        requested_media = directory / filename
        if requested_media.suffix.lower() not in SUPPORTED_MEDIA_SUFFIXES:
            raise ValueError("Only .mp3, .mp4, and .webm files are supported")
        if not requested_media.is_file():
            raise FileNotFoundError("Media file does not exist")

        preferred = {
            path.stem.casefold(): path
            for path in preferred_media_files(directory)
        }.get(requested_media.stem.casefold())
        if preferred is not None and preferred.name != requested_media.name:
            raise ValueError(
                f"{preferred.name} takes precedence over {requested_media.name}"
            )

        try:
            media = requested_media.resolve()
        except (OSError, RuntimeError) as error:
            raise PermissionError(f"Media file cannot be resolved: {requested_media.name}") from error
        if not self._is_allowed_directory(media.parent):
            raise PermissionError("Media file is outside allowed media roots")
        if media.suffix.lower() not in SUPPORTED_MEDIA_SUFFIXES:
            raise ValueError("Only .mp3, .mp4, and .webm files are supported")
        return media

    @staticmethod
    def _media_kind(media):
        return "audio" if Path(media).suffix.lower() == ".mp3" else "video"

    def _path_error(self, error):
        if isinstance(error, PermissionError):
            status = 403
        elif isinstance(error, FileNotFoundError):
            status = 404
        else:
            status = 400
        return jsonify(error=str(error)), status

    @staticmethod
    def __analysis_is_valid(json_path):
        try:
            from chordflask_base import ChordTrackRepository

            ChordTrackRepository().load(json_path)
            return True
        except (OSError, UnicodeError, ValueError, TypeError, KeyError) as error:
            logging.warning("Invalid current analysis %s: %s", json_path, error)
            return False

    def resource_path(self, relative_path):
        """
        Get the absolute path to resource, works for dev and for PyInstaller
        :param relative_path: Relative path to the resource.
        :return: Absolute path to the resource.
        """
        try:
            base_path = sys._MEIPASS  # PyInstaller temp path
        except Exception:
            base_path = os.path.abspath(os.path.dirname(__file__))  # Get the directory where chordflask.py is located
        return os.path.join(base_path, relative_path)

    def is_frozen(self):
        return getattr(sys, "frozen", False)

    def print_startup_message(self, host, port):
        print(f"ChordFlask {self.__version__}  http://{host}:{port}")
        if host not in {"127.0.0.1", "localhost", "::1"}:
            print("SECURITY: No authentication, TLS, or CSRF. LAN only on trusted networks.")
        if self.__quiet:
            return
        try:
            require_system_ffmpeg()
        except RuntimeError:
            print("WARNING: ffmpeg not found — sudo apt install ffmpeg")

    def app_base_dir(self):
        if self.is_frozen():
            return os.path.dirname(os.path.abspath(sys.executable))
        return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))

    def default_video_directories(self):
        """
        Return stable video directory suggestions for development and standalone runs.
        Keep the familiar relative development shortcuts visible, and add
        absolute candidates so PyInstaller binaries do not depend on the shell's
        current working directory.
        """
        base_dir = self.app_base_dir()
        candidates = [
            "./videos",
            "../videos",
            os.path.join(base_dir, "videos"),
            os.path.join(os.getcwd(), "videos"),
            os.path.abspath(os.path.join(os.getcwd(), os.pardir, "videos")),
        ]

        directories = []
        seen = set()
        for candidate in candidates:
            expanded = os.path.expanduser(candidate)
            if expanded in seen:
                continue
            seen.add(expanded)
            directories.append(expanded)
        return directories


    def setup_vamp_plugins(self):
        """
        Configure Vamp plugin lookup and verify plugins are discoverable.

        Development runs prefer the private vendored plugins when present.
        Standalone and public-source runs use VAMP_PATH or ~/.vamp and never
        copy plugin binaries at startup.
        """
        quiet = self.__quiet
        vamp_path = os.environ.get("VAMP_PATH", "")
        if vamp_path:
            if not quiet:
                print(f"Using VAMP_PATH={vamp_path}")
        elif not self.is_frozen():
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
            vendored_vamp_dir = os.path.join(project_root, "vendor", "vamp", "linux-x86_64")
            if os.path.isdir(vendored_vamp_dir):
                os.environ["VAMP_PATH"] = vendored_vamp_dir
                if not quiet:
                    print(f"Using vendored VAMP_PATH={vendored_vamp_dir}")
        elif os.path.isdir(os.path.expanduser("~/.vamp")):
            os.environ["VAMP_PATH"] = os.path.expanduser("~/.vamp")
            if not quiet:
                print("Using VAMP_PATH=~/.vamp")
        else:
            if not quiet:
                print("VAMP_PATH is not set and ~/.vamp does not exist.")
                print("Install plugins with: bash install_vamp.sh")
                print("Or set VAMP_PATH to a directory containing the .so files.")

        try:
            from vamp_runtime import require_vamp_plugins
            require_vamp_plugins()
        except (RuntimeError, ImportError, OSError) as error:
            if not quiet:
                print(f"WARNING: {error}")
            self.plugins_available = False

    def setup_routes(self):
        """
        Set up all routes for the Flask application.
        This method centralizes the route setup for better organization.
        """
        self.app.add_url_rule('/', 'index', self.index)
        self.app.add_url_rule('/list_files', 'list_files', self.list_files, methods=['POST'])
        self.app.add_url_rule('/enqueue_batch', 'enqueue_batch', self.enqueue_batch, methods=['POST'])
        self.app.add_url_rule('/load_file', 'load_file', self.load_file, methods=['POST'])
        self.app.add_url_rule('/reanalyze', 'reanalyze', self.reanalyze, methods=['POST'])
        self.app.add_url_rule('/video', 'serve_video', self.serve_video)
        self.app.add_url_rule('/stem/<stem_name>', 'serve_stem', self.serve_stem)
        self.app.add_url_rule('/get_callback_output', 'get_callback_output', self.get_callback_output, methods=['GET'])
        self.app.add_url_rule('/set_position', 'set_position', self.set_position, methods=['POST'])
        self.app.add_url_rule('/update_semitones', 'update_semitones', self.update_semitones, methods=['POST'])
        self.app.add_url_rule('/update_display_options', 'update_display_options', self.update_display_options, methods=['POST'])
        self.app.add_url_rule('/update_analysis_tracks', 'update_analysis_tracks', self.update_analysis_tracks, methods=['POST'])
        self.app.add_url_rule('/start_chord_editing', 'start_chord_editing', self.start_chord_editing, methods=['POST'])
        self.app.add_url_rule('/set_chord_version', 'set_chord_version', self.set_chord_version, methods=['POST'])
        self.app.add_url_rule('/edit_chord', 'edit_chord', self.edit_chord, methods=['POST'])
        self.app.add_url_rule('/reset_edited_chords', 'reset_edited_chords', self.reset_edited_chords, methods=['POST'])
        self.app.add_url_rule('/download_chords', 'download_chords', self.download_chords, methods=['POST'])
        self.app.add_url_rule('/get_stored_directories', 'get_stored_directories', self.get_stored_directories, methods=['GET'])
        self.app.add_url_rule('/browse_roots', 'browse_roots', self.browse_roots, methods=['GET'])
        self.app.add_url_rule('/analysis_queue_status', 'analysis_queue_status', self.analysis_queue_status, methods=['GET'])
        self.app.add_url_rule('/toggle_unicode', 'toggle_unicode', self.toggle_unicode, methods=['POST'])

    def index(self):
        """
        Serve the main HTML page with the video player and file selection interface.
        :return: Rendered home.html template.
        """
        return render_template('home.html')



    def list_files(self):
        """
        List all supported media files in the provided directory.
        If the directory is new, it is added to the stored directories.
        :return: JSON list of video files with their sizes.
        """
        data, error_response = self._json_body()
        if error_response:
            return error_response
        matchstring = data.get('matchstring', '')
        structured = data.get('structured', False)
        if not isinstance(matchstring, str) or not isinstance(structured, bool):
            return jsonify(error="matchstring must be a string and structured must be a boolean"), 400
        matchstring = matchstring.lower()
        try:
            directory = self._existing_directory(data.get('dirname'))
        except (ValueError, FileNotFoundError, PermissionError) as error:
            return self._path_error(error)
        dirname = str(directory)
        logging.info(f"Listing files in directory: {dirname} with matchstring: '{matchstring}'")

        # Add new directory to stored directories if it's not already there
        if dirname not in self.stored_directories:
            self.stored_directories.append(dirname)
            logging.info(f"Added new directory to stored_directories: {dirname}")

        media_files = [str(entry) for entry in preferred_media_files(directory)]
        logging.info(f"Found {len(media_files)} files before filtering")

        if matchstring:
            media_files = [
                media for media in media_files
                if matchstring in os.path.basename(media).lower()
            ]
            logging.info(f"{len(media_files)} files after applying matchstring filter")

        if structured:
            directories = []
            try:
                scan_entries = sorted(os.scandir(dirname), key=lambda item: item.name.lower())
            except (PermissionError, OSError):
                scan_entries = []
            for entry in scan_entries:
                try:
                    if (
                        not entry.is_dir()
                        or entry.name in {ANALYSIS_DIR_NAME, LEGACY_ANALYSIS_DIR_NAME}
                    ):
                        continue
                    stat = entry.stat()
                except (PermissionError, OSError):
                    continue
                directories.append({
                    "type": "directory",
                    "name": entry.name,
                    "path": os.path.join(dirname, entry.name),
                    "size_mb": None,
                    "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    "mtime_epoch": stat.st_mtime,
                })

            files = []
            for file in media_files:
                try:
                    stat = os.stat(file)
                except (PermissionError, OSError):
                    continue
                files.append({
                    "type": "file",
                    "media_kind": self._media_kind(file),
                    "name": os.path.basename(file),
                    "path": file,
                    "size_mb": stat.st_size // 1000000,
                    "size_bytes": stat.st_size,
                    "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    "mtime_epoch": stat.st_mtime,
                })
            try:
                parent = directory.parent.resolve()
            except (OSError, RuntimeError):
                parent = directory
            parent_dir = None
            if parent != directory and self._is_allowed_directory(parent):
                parent_dir = str(parent)
            return jsonify({
                "current_dir": dirname,
                "parent_dir": parent_dir,
                "directories": directories,
                "files": files,
            })

        res = []
        for file in media_files:
            try:
                size_mb = os.path.getsize(file) // 1000000
            except (PermissionError, OSError):
                continue
            res.append(f"{os.path.basename(file)} | {size_mb}M")

        return jsonify(res)

    def enqueue_batch(self):
        """Queue the next N missing analyses in the submitted GUI order."""
        data, error_response = self._json_body()
        if error_response:
            return error_response
        filenames = data.get("filenames")
        limit = data.get("limit")
        if not isinstance(filenames, list) or not all(
            isinstance(filename, str) for filename in filenames
        ):
            return jsonify(error="filenames must be a list of strings"), 400
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= MAX_BATCH_SIZE
        ):
            return jsonify(error=f"limit must be an integer from 1 to {MAX_BATCH_SIZE}"), 400

        try:
            directory = self._existing_directory(data.get("dirname"))
        except (ValueError, FileNotFoundError, PermissionError) as error:
            return self._path_error(error)

        available = {}
        for path in preferred_media_files(directory):
            try:
                available[path.name] = path.resolve()
            except (OSError, RuntimeError):
                continue
        ordered_media = []
        seen = set()
        for filename in filenames:
            if Path(filename).name != filename or filename in {"", ".", ".."}:
                return jsonify(error="filenames must not contain paths"), 400
            media = available.get(filename)
            if media is None:
                return jsonify(error=f"Unsupported or unavailable media file: {filename}"), 400
            if media not in seen:
                seen.add(media)
                ordered_media.append(media)

        candidates = []
        analyzed_count = 0
        for media in ordered_media:
            file_repr = FileRepr(str(media), datapath=ANALYSIS_DIR_NAME)
            json_path = file_repr.get("json")
            if os.path.exists(json_path) and self.__analysis_is_valid(json_path):
                analyzed_count += 1
            else:
                candidates.append(media)

        result = self.analysis_queue.enqueue_many(candidates, limit)
        return jsonify({
            "status": "queued",
            "queued_count": len(result["queued"]),
            "queued_paths": result["queued"],
            "already_queued_count": len(result["already_queued"]),
            "skipped_analyzed_count": analyzed_count,
            "remaining_count": len(result["deferred"]),
        })

    def analysis_error_message(self, filename, error):
        error_text = str(error)
        if "moov atom not found" in error_text:
            return (
                f"Could not analyze {filename}: the MP4 file is not readable by ffmpeg "
                "(moov atom not found). The file is probably incomplete or corrupted. "
                "Re-download or repair the video file, then try again."
            )
        if "Invalid data found when processing input" in error_text:
            return (
                f"Could not analyze {filename}: ffmpeg reports invalid input data. "
                "The file is probably not a valid playable media file."
            )
        return f"Could not generate chords: {error}"



    def load_file(self):
        """
        Load the selected media file and check if a corresponding .json file exists.
        If not, it queues analysis for the external worker and leaves the
        current player unchanged.
        :return: JSON response with mp4 and json file paths.
        """
        data, error_response = self._json_body()
        if error_response:
            return error_response
        try:
            media = self._existing_media_file(data.get('dirname'), data.get('filename'))
        except (ValueError, FileNotFoundError, PermissionError) as error:
            return self._path_error(error)
        dirname = str(media.parent)
        filename = media.name

        logging.info(f"Loading file: {filename} from directory: {dirname}")

        requested_chord_track_id = data.get('chord_track_id')
        requested_rhythm_track_id = data.get('rhythm_track_id')

        # Create a FileRepr instance for managing paths
        analysis_dir = os.path.join(dirname, ANALYSIS_DIR_NAME)
        requested_file_repr = FileRepr(str(media), datapath=analysis_dir)

        # Check if the JSON file exists. If not, queue it and keep the
        # currently playing video/player active.
        if not os.path.exists(requested_file_repr.get("json")):
            queue_status = self.analysis_queue.enqueue(requested_file_repr.get())
            logging.info(f"Queued missing analysis for {filename}: {queue_status}")
            return jsonify({
                'status': queue_status,
                'message': 'Added to analysis queue' if queue_status == 'queued' else 'Already in analysis queue',
                'mp4_file': requested_file_repr.get(),
                'media_kind': self._media_kind(media),
                'json_file': None,
                'title': f"ChordFlask - {filename}"
            })

        analysis_valid = self.__analysis_is_valid(requested_file_repr.get("json"))

        # Reset semitones to 0 initially for files that can actually be loaded.
        self.semitones = 0
        self.file_repr = requested_file_repr

        # Initialize the player with the selected file and display settings.
        self.player = MP4PlayerFlask(
            self.file_repr,
            semitones=self.semitones,
            max_lines=self.max_lines,
            use_unicode=self.use_unicode,
            metric_chords=self.__metric_chords,
        )
        self.player.set_prefer_flats(self.prefer_flats)
        self.player.set_repeat_mode(self.repeat_mode)

        self.player.select_analysis_tracks(
            chord_track_id=requested_chord_track_id if isinstance(requested_chord_track_id, str) else None,
            rhythm_track_id=requested_rhythm_track_id if isinstance(requested_rhythm_track_id, str) else None,
            soft_fallback=True,
        )

        producer_requested = (
            isinstance(requested_chord_track_id, str)
            and requested_chord_track_id.strip()
        )
        if not producer_requested and self._analysis_has_edited_track(
            self.file_repr.get("json")
        ):
            self.player.select_analysis_tracks(chord_track_id="user_edited")

        # The next position request must apply the current viewport mode to the
        # newly created player, even when the media starts at the old position.
        self.old_current_position = None
        self.old_grid_mode = None
        state = self.player.analysis_track_state()

        return jsonify({
            'status': 'ready',
            'mp4_file': self.file_repr.get(),
            'media_kind': self._media_kind(media),
            'json_file': self.file_repr.get("json") if self.file_repr.get("json") else None,
            'analysis_valid': analysis_valid,
            'title': f"ChordFlask - {filename}",
            'stems': self.player.audio_stems_state(),
            **state,
        })

    def reanalyze(self):
        """Queue a safe refresh of the currently loaded media analysis."""
        data, error_response = self._json_body()
        if error_response:
            return error_response
        if self.file_repr is None:
            return jsonify(error="No active media file to reanalyze."), 409

        try:
            media = self._existing_media_file(data.get('dirname'), data.get('filename'))
        except (ValueError, FileNotFoundError, PermissionError) as error:
            return self._path_error(error)

        active_media = Path(self.file_repr.get()).resolve()
        if media != active_media:
            return jsonify(error="Requested media is not the active file."), 409

        if not self.__analysis_is_valid(self.file_repr.get("json")):
            return jsonify(error="The active file has no valid analysis to replace."), 409

        discard_edits = data.get("discard_edits", False)
        if not isinstance(discard_edits, bool):
            return jsonify(error="discard_edits must be a boolean"), 400
        if self._media_is_queued(media):
            return jsonify(error="This file already has queued analysis work."), 409
        if self._analysis_has_edited_track(self.file_repr.get("json")) and not discard_edits:
            return jsonify(
                error="This file has edited chords. Confirm discarding them before reanalysis."
            ), 409

        queue_status = self.analysis_queue.enqueue(
            str(media), force=True, discard_edits=discard_edits
        )
        logging.info("Queued reanalysis for %s: %s", media.name, queue_status)
        return jsonify({
            'status': queue_status,
            'message': (
                'Added reanalysis to queue'
                if queue_status == 'queued'
                else 'Reanalysis already in queue'
            ),
            'mp4_file': str(media),
            'media_kind': self._media_kind(media),
        })

    # ── chord editing routes ──────────────────────────────────────────

    def _media_is_queued(self, media_path):
        target = str(Path(media_path).resolve())
        return any(
            item.get("path") == target
            for item in self.analysis_queue.status().get("pending", [])
        )

    @staticmethod
    def _analysis_has_edited_track(json_path):
        from chordflask_base import ChordData

        try:
            track = ChordData(json_path)
        except (OSError, ValueError, TypeError, KeyError):
            return False
        return track.has_chord_track("user_edited")

    def _active_editing_media(self, data):
        """Return the active media Path, or a JSON error response to return."""
        if self.player is None:
            return jsonify(error="Player not initialized"), 409
        try:
            media = self._existing_media_file(data.get("dirname"), data.get("filename"))
        except (ValueError, FileNotFoundError, PermissionError) as error:
            return self._path_error(error)
        if media != Path(self.file_repr.get()).resolve():
            return jsonify(error="Requested media is not the active file."), 409
        return media

    def _validate_editing_request(self, data):
        media_or_error = self._active_editing_media(data)
        if not isinstance(media_or_error, Path):
            return media_or_error
        if self._media_is_queued(media_or_error):
            return jsonify(error="The active file has queued analysis work."), 409
        return None

    def _save_player_chord_data(self, previous_track_state):
        json_path = self.file_repr.get("json")
        try:
            self.player.chord_data.save_to_file(json_path)
        except (OSError, ValueError) as error:
            self.player.reload_chord_data(
                chord_track_id=previous_track_state["active_chord_track_id"],
                rhythm_track_id=previous_track_state["active_rhythm_track_id"],
            )
            return jsonify(error=f"Could not save chord data: {error}"), 500
        return None

    def start_chord_editing(self):
        data, error_response = self._json_body()
        if error_response:
            return error_response
        validation_error = self._validate_editing_request(data)
        if validation_error:
            return validation_error
        previous_track_state = self.player.analysis_track_state()
        try:
            state = self.player.start_chord_editing()
        except ValueError as error:
            return jsonify(error=str(error)), 400
        save_error = self._save_player_chord_data(previous_track_state)
        if save_error:
            return save_error
        return jsonify({
            "success": True,
            "grid": self.player.edit_grid(self.current_position),
            **state,
        })

    def set_chord_version(self):
        data, error_response = self._json_body()
        if error_response:
            return error_response
        media_or_error = self._active_editing_media(data)
        if not isinstance(media_or_error, Path):
            return media_or_error
        try:
            self.player.set_chord_version(data.get("version"))
        except ValueError as error:
            return jsonify(error=str(error)), 400
        self.player.update_position(self.current_position)
        return jsonify({"success": True, **self.player.analysis_track_state()})

    def edit_chord(self):
        data, error_response = self._json_body()
        if error_response:
            return error_response
        validation_error = self._validate_editing_request(data)
        if validation_error:
            return validation_error
        previous_track_state = self.player.analysis_track_state()
        try:
            self.player.edit_chord(data.get("beat_index"), data.get("chord"))
        except ValueError as error:
            return jsonify(error=str(error)), 400
        save_error = self._save_player_chord_data(previous_track_state)
        if save_error:
            return save_error
        self.player.update_position(self.current_position)
        return jsonify({
            "success": True,
            "grid": self.player.edit_grid(self.current_position),
            **self.player.analysis_track_state(),
        })

    def reset_edited_chords(self):
        data, error_response = self._json_body()
        if error_response:
            return error_response
        validation_error = self._validate_editing_request(data)
        if validation_error:
            return validation_error
        previous_track_state = self.player.analysis_track_state()
        try:
            self.player.reset_edited_chords()
        except ValueError as error:
            return jsonify(error=str(error)), 400
        save_error = self._save_player_chord_data(previous_track_state)
        if save_error:
            return save_error
        self.player.update_position(self.current_position)
        return jsonify({"success": True, **self.player.analysis_track_state()})

    def download_chords(self):
        """Return the active displayed beat-level chords as Markdown and PDF."""
        data, error_response = self._json_body()
        if error_response:
            return error_response
        media_or_error = self._active_editing_media(data)
        if not isinstance(media_or_error, Path):
            return media_or_error

        snapshot = self.player.chord_download_snapshot()
        if not snapshot["beats"]:
            return jsonify(error="The active analysis has no beat grid to export."), 409

        export_stem = (
            f"{media_or_error.stem}-chords-"
            f"{download_track_slug(snapshot['chord_track_id'])}"
        )
        markdown = format_chord_markdown(
            title=media_or_error.stem,
            chord_track=snapshot["chord_track_label"],
            rhythm_track=snapshot["rhythm_track_label"],
            version=snapshot["version"].capitalize(),
            transpose=snapshot["transpose"],
            spelling="Flats" if snapshot["prefer_flats"] else "Sharps",
            unicode_symbols=snapshot["use_unicode"],
            bpm=snapshot["bpm"],
            meter=snapshot["meter"],
            beats=snapshot["beats"],
            repeat_mode=snapshot["repeat_mode"],
        )
        try:
            pdf = ChordSheetPdfRenderer().render_markdown(markdown)
            archive = BytesIO()
            with ZipFile(archive, "w", compression=ZIP_DEFLATED) as output:
                output.writestr(f"{export_stem}.md", markdown.encode("utf-8"))
                output.writestr(f"{export_stem}.pdf", pdf)
            archive.seek(0)
        except Exception:  # noqa: BLE001 - preserve the all-or-nothing download contract
            logging.exception("Could not render the chord leadsheet PDF")
            return jsonify(error="Could not render the chord leadsheet PDF."), 500
        return send_file(
            archive,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"{export_stem}.zip",
        )

    def serve_video(self):
        """
        Serve the selected audio or video source to the front-end player.
        """
        if self.file_repr and os.path.exists(self.file_repr.get()):
            media_path = self.file_repr.get()
            mime_types = {
                ".mp3": "audio/mpeg",
                ".mp4": "video/mp4",
                ".webm": "video/webm",
            }
            logging.info(f"Serving media file: {media_path}")
            response = make_response(send_file(
                media_path,
                mimetype=mime_types[Path(media_path).suffix.lower()],
            ))
            response.headers['Cache-Control'] = 'no-store'
            return response
        else:
            logging.error("Media file not found")
            return "Media file not found.", 404

    def serve_stem(self, stem_name):
        """Serve one FLAC stem of the currently loaded song's grouped set.

        Only stems referenced by the loaded, validated audio-track set are
        served. No arbitrary filesystem path is accepted: the stem name must be
        one of the four expected names and the resolved path must stay inside
        the media's ``.chordflask`` storage boundary (no traversal, no symlink
        escape).
        """
        if self.file_repr is None or self.player is None:
            return "Stem not available.", 404
        if stem_name not in DEMUCS_STEM_NAMES:
            return "Unknown stem.", 404
        if not self.player.audio_stems_state():
            return "Stems are not available for the current song.", 404
        try:
            set_data = self.player.chord_data.audio_track_data(STEMS_AUDIO_SET_ID)
            stem = set_data["tracks"][stem_name]
        except (KeyError, ValueError):
            return "Stem not available.", 404

        media_path = Path(self.file_repr.get())
        storage_root = (media_path.parent / ANALYSIS_DIR_NAME).resolve()
        try:
            candidate = media_path.parent / Path(stem["path"])
            if candidate.is_symlink():
                return "Stem not available.", 404
            resolved = candidate.resolve()
        except (OSError, RuntimeError):
            return "Stem not available.", 404
        if not resolved.is_relative_to(storage_root):
            return "Stem not available.", 404
        if not resolved.is_file():
            return "Stem not available.", 404

        response = make_response(send_file(resolved, mimetype="audio/flac"))
        response.headers['Cache-Control'] = 'no-store'
        return response


    def get_callback_output(self):
        """
        Return the last lines of callback output from the MP4PlayerFlask instance.
        :return: JSON list of callback output.
        """
        if self.player:
            return jsonify(self.player.get_callback_output())  # Send the last lines of output
        else:
            return jsonify({"callback_output":[], "bpm":100})

    def set_position(self):
        """
        Set the video playback position from the slider control in the UI.
        :return: Success response.
        """
        data, error_response = self._json_body()
        if error_response:
            return error_response
        position = data.get('position')
        if isinstance(position, bool) or not isinstance(position, (int, float)) or not math.isfinite(position) or position < 0:
            return jsonify(error="position must be a finite non-negative number"), 400
        include_edit_grid = data.get('include_edit_grid', False)
        if not isinstance(include_edit_grid, bool):
            return jsonify(error="include_edit_grid must be a boolean"), 400
        grid_mode = data.get("grid_mode", "compact")
        if not isinstance(grid_mode, str) or grid_mode not in GRID_MODES:
            return jsonify(
                error=f"grid_mode must be one of: {', '.join(sorted(GRID_MODES))}"
            ), 400
        self.current_position = position

        # Avoid unnecessary updates if position hasn't changed
        if (
            self.old_current_position == self.current_position
            and self.old_grid_mode == grid_mode
        ):
            payload = self.player.get_callback_output() if self.player else {
                "callback_output": [], "bpm": 100
            }
            payload["success"] = True
        else:
            self.old_current_position = self.current_position
            self.old_grid_mode = grid_mode
            #logging.info(f"Setting video position to: {self.current_position} seconds")

            if self.player:
                self.player.update_position(
                    self.current_position,
                    grid_mode=grid_mode,
                )
                payload = self.player.get_callback_output()
                payload["success"] = True
            else:
                payload = {"success": True, "callback_output": [], "bpm": 100}

        if include_edit_grid and self.player:
            payload["edit_grid"] = self.player.edit_grid(self.current_position)
        return jsonify(payload)

    def update_semitones(self):
        data, error_response = self._json_body()
        if error_response:
            return error_response
        semitones = data.get('semitones')
        if isinstance(semitones, bool) or not isinstance(semitones, int) or not -24 <= semitones <= 24:
            return jsonify(error="semitones must be an integer between -24 and 24"), 400
        self.semitones = semitones
        logging.info(f"Updating semitones to: {self.semitones}")

        if self.player:
            self.player.set_transpose(self.semitones)
            return jsonify(success=True)

        logging.warning("Attempted to update semitones but player is not initialized")
        return jsonify(error="Player not initialized"), 400

    def update_display_options(self):
        data, error_response = self._json_body()
        if error_response:
            return error_response
        prefer_flats = data.get("prefer_flats", self.prefer_flats)
        if not isinstance(prefer_flats, bool):
            return jsonify(error="prefer_flats must be a boolean"), 400
        self.prefer_flats = prefer_flats
        repeat_mode = data.get("repeat_mode", self.repeat_mode)
        if repeat_mode not in {"chords", "changes"}:
            return jsonify(error="repeat_mode must be 'chords' or 'changes'"), 400
        self.repeat_mode = repeat_mode

        if self.player:
            self.player.set_prefer_flats(self.prefer_flats)
            self.player.set_repeat_mode(self.repeat_mode)
            self.player.update_position(self.current_position)
            return jsonify(success=True)

        return jsonify(error="Player not initialized"), 400

    def update_analysis_tracks(self):
        data, error_response = self._json_body()
        if error_response:
            return error_response
        if self.player is None:
            return jsonify(error="Player not initialized"), 400

        chord_track_id = data.get('chord_track_id')
        rhythm_track_id = data.get('rhythm_track_id')
        if chord_track_id is None and rhythm_track_id is None:
            return jsonify(error="At least one of chord_track_id or rhythm_track_id is required"), 400

        try:
            self.player.select_analysis_tracks(
                chord_track_id=chord_track_id, rhythm_track_id=rhythm_track_id,
                soft_fallback=False,
            )
        except ValueError as error:
            return jsonify(error=str(error)), 400

        self.player.update_position(self.current_position)
        return jsonify({"success": True, **self.player.analysis_track_state()})

    def get_stored_directories(self):
        """
        Return the list of previously stored directories for video files.
        :return: JSON list of stored directories.
        """
        logging.info("Fetching stored directories")
        return jsonify(self.stored_directories)

    def browse_roots(self):
        """Return safe starting directories for the browser file picker."""
        roots = self.allowed_roots or [Path.home().resolve()]
        seen = set()
        entries = []
        for root in roots:
            try:
                resolved = Path(root).resolve()
                if resolved in seen or not resolved.is_dir():
                    continue
                mtime_epoch = resolved.stat().st_mtime
            except (OSError, RuntimeError):
                continue
            seen.add(resolved)
            entries.append({
                "type": "directory",
                "name": resolved.name or str(resolved),
                "path": str(resolved),
                "mtime": "",
                "mtime_epoch": mtime_epoch,
            })
        return jsonify({"roots": entries})

    def analysis_queue_status(self):
        """
        Return pending and failed local analysis queue entries.
        """
        from analysis_worker import AnalysisWorker

        status = self.analysis_queue.status()
        status["worker"] = {
            "running": AnalysisWorker.is_running(self.analysis_queue),
            "managed": bool(
                self.worker_supervisor
                and self.worker_supervisor.child_running()
            ),
        }
        return jsonify(status)

    def toggle_unicode(self):
        """
        Toggle the Unicode representation flag for chord outputs.
        :return: Success response.
        """
        data, error_response = self._json_body()
        if error_response:
            return error_response
        flag = data.get('use_unicode')
        if not isinstance(flag, bool):
            return jsonify(error="use_unicode must be a boolean"), 400
        self.use_unicode = flag
        logging.info(f"Toggling Unicode flag to: {self.use_unicode}")

        if self.player:
            self.player.chord_data.set_unicode(self.use_unicode)
            self.player.reset_render_cache()
            self.player.update_position(self.current_position)
            return jsonify(success=True)

        return jsonify(success=False, error="Player not initialized"), 400

    def run(self, listen=None, port=None):
        port = int(port or os.environ.get(PORT_ENV, str(DEFAULT_PORT)))
        host = listen or os.environ.get(LISTEN_ENV, DEFAULT_HOST)
        is_loopback = host in {"127.0.0.1", "localhost", "::1"}
        if not is_loopback and self.allowed_roots is None:
            raise ValueError(
                "Listening beyond localhost requires at least one allowed "
                "media root.\n\n"
                f"Set {ALLOWED_MEDIA_ROOTS_ENV}, for example:\n\n"
                f"    {ALLOWED_MEDIA_ROOTS_ENV}=/home/user/Music "
                "chordflask --listen 0.0.0.0\n\n"
                "Multiple directories are separated using the platform path "
                "separator:\n"
                "    Linux/macOS: :\n"
                "    Windows:     ;\n\n"
                "Example with multiple directories:\n\n"
                f"    {ALLOWED_MEDIA_ROOTS_ENV}=\"/home/user/Music:/mnt/media/videos\" "
                "chordflask --listen 0.0.0.0"
            )
        debug = os.environ.get(DEBUG_ENV, "0") == "1"
        if debug and not is_loopback:
            raise ValueError("Flask debug mode is only supported on loopback")
        self._configure_web_logging()
        self.print_startup_message(host, port)
        self.app.run(
            host=host,
            port=port,
            debug=debug,
            use_reloader=False,
        )

    def _configure_web_logging(self):
        log_dir = self.analysis_queue.queue_dir
        log_dir.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]',
            handlers=[
                logging.FileHandler(log_dir / "web.log"),
                logging.StreamHandler(),
            ]
        )


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()

    args = _parse_cli_args()

    if args.debug:
        os.environ[DEBUG_ENV] = "1"

    if args.check_vamp:
        from vamp_runtime import REQUIRED_PLUGINS, require_vamp_plugins
        try:
            plugins = require_vamp_plugins()
        except (RuntimeError, ImportError, OSError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            raise SystemExit(1) from None
        print("Vamp plugin check passed:")
        for plugin in sorted(plugins):
            if plugin in REQUIRED_PLUGINS:
                print(f"  {plugin}")
        raise SystemExit(0)

    quiet = args.worker
    try:
        flask_app = FlaskMP4App(quiet=quiet, metric_chords=args.metric_chords)
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from None
    flask_app.setup_vamp_plugins()
    if args.worker:
        from analysis_worker import AnalysisWorker
        raise SystemExit(AnalysisWorker(queue=flask_app.analysis_queue).run_forever())

    supervisor = None
    if not args.no_worker:
        from analysis_worker import WorkerSupervisor
        supervisor = WorkerSupervisor(flask_app.analysis_queue)
        supervisor.start()
        flask_app.worker_supervisor = supervisor

    try:
        flask_app.run(listen=args.listen, port=args.port)
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        if supervisor:
            supervisor.stop()
