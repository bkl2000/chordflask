#!/usr/bin/env python3

"""
Flask application for MP4 chord analysis and playback.
"""

import argparse
import sys
from flask import Flask, render_template, jsonify, request, send_file, make_response
import os
import glob
import logging
import math
from datetime import datetime
from pathlib import Path

from analysis_queue import AnalysisQueue
from chordflask_config import (
    ANALYSIS_DIR_NAME, LEGACY_ANALYSIS_DIR_NAME, ALLOWED_MEDIA_ROOTS_ENV, LISTEN_ENV,
    PORT_ENV, DEBUG_ENV, DEFAULT_HOST, DEFAULT_PORT,
)
from filerepr import FileRepr  # Import FileRepr class for file path management
from ffmpeg_runtime import require_system_ffmpeg

from mp4playerflask import MP4PlayerFlask  # Import the MP4PlayerFlask class


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

        # Set up file logging only
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]',
            handlers=[
                logging.FileHandler('/tmp/flask_app.log'),  # Log to the file
            ]
        )

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
            raise SystemExit(1)

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
        directory = Path(value).expanduser().resolve()
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
        media = (directory / filename).resolve()
        if not self._is_allowed_directory(media.parent):
            raise PermissionError("Media file is outside allowed media roots")
        if media.suffix.lower() not in {".mp4", ".webm"}:
            raise ValueError("Only .mp4 and .webm files are supported")
        if not media.is_file():
            raise FileNotFoundError("Media file does not exist")
        return media

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
            from chorddata import ChordTrackRepository

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
        self.app.add_url_rule('/load_file', 'load_file', self.load_file, methods=['POST'])
        self.app.add_url_rule('/reanalyze', 'reanalyze', self.reanalyze, methods=['POST'])
        self.app.add_url_rule('/video', 'serve_video', self.serve_video)
        self.app.add_url_rule('/get_callback_output', 'get_callback_output', self.get_callback_output, methods=['GET'])
        self.app.add_url_rule('/set_position', 'set_position', self.set_position, methods=['POST'])
        self.app.add_url_rule('/update_semitones', 'update_semitones', self.update_semitones, methods=['POST'])
        self.app.add_url_rule('/update_display_options', 'update_display_options', self.update_display_options, methods=['POST'])
        self.app.add_url_rule('/update_analysis_tracks', 'update_analysis_tracks', self.update_analysis_tracks, methods=['POST'])
        self.app.add_url_rule('/get_stored_directories', 'get_stored_directories', self.get_stored_directories, methods=['GET'])
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
        List all .mp4 and .webm files in the provided directory.
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

        # Use glob to find all .mp4 and .webm files
        mp4_files = sorted(glob.glob(os.path.join(dirname, "*.mp4")) + glob.glob(os.path.join(dirname, "*.webm")))
        logging.info(f"Found {len(mp4_files)} files before filtering")

        if matchstring:
            mp4_files = [f for f in mp4_files if matchstring in os.path.basename(f).lower()]
            logging.info(f"{len(mp4_files)} files after applying matchstring filter")

        if structured:
            directories = []
            for entry in sorted(os.scandir(dirname), key=lambda item: item.name.lower()):
                if (
                    not entry.is_dir()
                    or entry.name in {ANALYSIS_DIR_NAME, LEGACY_ANALYSIS_DIR_NAME}
                ):
                    continue
                stat = entry.stat()
                directories.append({
                    "type": "directory",
                    "name": entry.name,
                    "path": os.path.join(dirname, entry.name),
                    "size_mb": None,
                    "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    "mtime_epoch": stat.st_mtime,
                })

            files = []
            for file in mp4_files:
                stat = os.stat(file)
                files.append({
                    "type": "file",
                    "name": os.path.basename(file),
                    "path": file,
                    "size_mb": stat.st_size // 1000000,
                    "size_bytes": stat.st_size,
                    "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    "mtime_epoch": stat.st_mtime,
                })
            return jsonify({
                "current_dir": dirname,
                "parent_dir": os.path.join(dirname, os.pardir),
                "directories": directories,
                "files": files,
            })

        file_size_mb = [os.path.getsize(file) // 1000000 for file in mp4_files]
        file_names = [os.path.basename(file) for file in mp4_files]
        res = [f"{name} | {size}M" for name, size in zip(file_names, file_size_mb)]

        return jsonify(res)

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
        Load the selected .mp4 file and check if a corresponding .json file exists.
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

        state = self.player.analysis_track_state()

        return jsonify({
            'status': 'ready',
            'mp4_file': self.file_repr.get(),
            'json_file': self.file_repr.get("json") if self.file_repr.get("json") else None,
            'analysis_valid': analysis_valid,
            'title': f"ChordFlask - {filename}",
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

        queue_status = self.analysis_queue.enqueue(str(media), force=True)
        logging.info("Queued reanalysis for %s: %s", media.name, queue_status)
        return jsonify({
            'status': queue_status,
            'message': (
                'Added reanalysis to queue'
                if queue_status == 'queued'
                else 'Reanalysis already in queue'
            ),
            'mp4_file': str(media),
        })

    def serve_video(self):
        """
        Serve the MP4 file as the video source for the front-end player.
        :return: MP4 file as a response.
        """
        if self.file_repr and os.path.exists(self.file_repr.get()):
            logging.info(f"Serving MP4 file: {self.file_repr.get()}")
            response = make_response(send_file(self.file_repr.get(), mimetype='video/mp4'))
            response.headers['Cache-Control'] = 'no-store'
            return response
        else:
            logging.error("Video file not found")
            return "Video file not found.", 404

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
        self.current_position = position

        # Avoid unnecessary updates if position hasn't changed
        if self.old_current_position == self.current_position:
            payload = self.player.get_callback_output() if self.player else {
                "callback_output": [], "bpm": 100
            }
            payload["success"] = True
            return jsonify(payload)

        self.old_current_position = self.current_position
        #logging.info(f"Setting video position to: {self.current_position} seconds")

        if self.player:
            self.player.update_position(self.current_position)
            payload = self.player.get_callback_output()
            payload["success"] = True
            return jsonify(payload)

        return jsonify(success=True, callback_output=[], bpm=100)

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
                f"{ALLOWED_MEDIA_ROOTS_ENV} must contain at least one directory "
                "before ChordFlask can listen beyond loopback"
            )
        debug = os.environ.get(DEBUG_ENV, "0") == "1"
        if debug and not is_loopback:
            raise ValueError("Flask debug mode is only supported on loopback")
        self.print_startup_message(host, port)
        self.app.run(
            host=host,
            port=port,
            debug=debug,
            use_reloader=False,
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
            raise SystemExit(1)
        print("Vamp plugin check passed:")
        for plugin in sorted(plugins):
            if plugin in REQUIRED_PLUGINS:
                print(f"  {plugin}")
        raise SystemExit(0)

    quiet = args.worker
    flask_app = FlaskMP4App(quiet=quiet, metric_chords=args.metric_chords)
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
    finally:
        if supervisor:
            supervisor.stop()
