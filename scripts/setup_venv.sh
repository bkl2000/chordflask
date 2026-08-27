#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_VENV_DIR="${HOME}/.venvs/chordflask"
LEGACY_VENV_DIR="${HOME}/.venvs/chordifier"
VENV_DIR="${CHORDFLASK_VENV:-${CHORDIFIER_VENV:-${DEFAULT_VENV_DIR}}}"
REQUIREMENTS_FILE="${ROOT_DIR}/requirements.txt"
DEV_REQUIREMENTS_FILE="${ROOT_DIR}/requirements-dev.txt"
BUILD_REQUIREMENTS_FILE="${ROOT_DIR}/requirements-build.txt"
OPTIONAL_REQUIREMENTS_FILE="${ROOT_DIR}/requirements-optional.txt"
PYTHON312_CONSTRAINTS_FILE="${ROOT_DIR}/constraints-python312.txt"
PYTHON_BIN="${CHORDIFIER_PYTHON:-}"
RECREATE=false
INSTALL_DEV=false
INSTALL_OPTIONAL=false

case "${CHORDIFIER_OPTIONAL:-0}" in
    1|true|yes)
        INSTALL_OPTIONAL=true
        ;;
    0|false|no|"")
        ;;
    *)
        echo "Invalid CHORDIFIER_OPTIONAL value: ${CHORDIFIER_OPTIONAL}" >&2
        echo "Use 1/true/yes to enable it or 0/false/no to disable it." >&2
        exit 2
        ;;
esac

MINIMAL_SYSTEM_PACKAGES=(
    python3
    python3-venv
    python3-dev
    build-essential
    pkg-config
    ffmpeg
    vamp-plugin-sdk
    libasound2-dev
    libcairo2-dev
    curl
)

print_minimal_install() {
    echo "On Debian/Ubuntu/Mint install the required system packages with:" >&2
    echo "  sudo apt update" >&2
    echo "  sudo apt install --no-install-recommends ${MINIMAL_SYSTEM_PACKAGES[*]}" >&2
}

usage() {
    cat <<USAGE
Usage: $0 [--venv DIR] [--dev] [--optional] [--recreate]

Creates or updates the Python virtual environment for ChordFlask.

Options:
  --venv DIR   Use DIR instead of ${DEFAULT_VENV_DIR}.
  --dev        Also install developer/test dependencies.
  --optional   Also install optional audio-playback dependencies.
  --recreate   Delete and recreate the venv directory.

Environment:
  CHORDFLASK_VENV     Alternative venv directory (takes precedence).
  CHORDIFIER_VENV     Deprecated alias for CHORDFLASK_VENV.
  CHORDIFIER_PYTHON   Python executable to use, for example python3.12.
  CHORDIFIER_OPTIONAL Set to 1 to install optional dependencies.
USAGE
}

VENV_EXPLICIT=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --venv)
            VENV_DIR="${2:?Missing directory after --venv}"
            VENV_EXPLICIT=true
            shift 2
            ;;
        --recreate)
            RECREATE=true
            shift
            ;;
        --dev)
            INSTALL_DEV=true
            shift
            ;;
        --optional)
            INSTALL_OPTIONAL=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ "$VENV_EXPLICIT" == false && -z "${CHORDFLASK_VENV:-}${CHORDIFIER_VENV:-}" ]]; then
    if [[ ! -d "$VENV_DIR" && -d "$LEGACY_VENV_DIR" ]]; then
        echo "Using the existing legacy virtual environment: ${LEGACY_VENV_DIR}" >&2
        echo "Set CHORDFLASK_VENV or run 'make setup-recreate' to migrate." >&2
        VENV_DIR="$LEGACY_VENV_DIR"
    fi
fi

select_python() {
    if [[ -n "$PYTHON_BIN" ]]; then
        command -v "$PYTHON_BIN"
        return
    fi

    for candidate in python3.12 python3.11 python3.10 python3.13 python3; do
        if command -v "$candidate" >/dev/null 2>&1; then
            command -v "$candidate"
            return
        fi
    done

    return 1
}

make_continuation_cmd() {
    local cmd="make setup"
    local extra=()
    local quoted
    if [[ "$VENV_DIR" != "$DEFAULT_VENV_DIR" ]]; then
        printf -v quoted '%q' "$VENV_DIR"
        extra+=("VENV_DIR=$quoted")
    fi
    if [[ -n "${CHORDIFIER_PYTHON:-}" ]]; then
        printf -v quoted '%q' "$CHORDIFIER_PYTHON"
        extra+=("PYTHON_BIN=$quoted")
    fi
    if [[ "$INSTALL_OPTIONAL" == true ]]; then
        extra+=("CHORDIFIER_OPTIONAL=1")
    fi
    [[ ${#extra[@]} -gt 0 ]] && cmd="${extra[*]} $cmd"
    printf '%s' "$cmd"
}

make_recreate_cmd() {
    local setup_cmd
    setup_cmd="$(make_continuation_cmd)"
    printf '%s setup-recreate' "${setup_cmd% setup}"
}

format_command() {
    printf '%q ' "$@"
}

run_setup_command() {
    local description="$1"
    shift
    local status

    if "$@"; then
        return 0
    else
        status=$?
    fi

    echo "" >&2
    echo "Setup failed: ${description}." >&2
    echo "Failed command:" >&2
    echo "  $(format_command "$@")" >&2
    echo "" >&2
    echo "Fix the reported error, then retry with:" >&2
    echo "  $(make_continuation_cmd)" >&2
    return "$status"
}

check_system_prerequisites() {
    local required_packages=("${MINIMAL_SYSTEM_PACKAGES[@]}")
    local missing_packages=()

    local is_debian=false
    if [[ -f /etc/debian_version ]] && command -v dpkg-query >/dev/null 2>&1; then
        is_debian=true
    fi

    if [[ "$is_debian" == true ]]; then
        for pkg in "${required_packages[@]}"; do
            if ! dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q 'install ok installed'; then
                missing_packages+=("$pkg")
            fi
        done
    else
        local missing_items=()
        command -v python3 >/dev/null 2>&1       || missing_items+=("python3 command")
        python3 -c "import venv" 2>/dev/null       || missing_items+=("python3-venv (try: python3 -c 'import venv')")
        command -v pkg-config >/dev/null 2>&1      || missing_items+=("pkg-config")
        command -v ffmpeg >/dev/null 2>&1          || missing_items+=("ffmpeg")
        command -v cc >/dev/null 2>&1              || missing_items+=("build-essential (C compiler)")
        command -v curl >/dev/null 2>&1            || command -v wget >/dev/null 2>&1 || missing_items+=("curl or wget (download tool)")
        local python_include=""
        if command -v python3 >/dev/null 2>&1; then
            python_include="$(python3 -c "import sysconfig; print(sysconfig.get_config_var('INCLUDEPY') or '')" 2>/dev/null || true)"
        fi
        [[ -n "$python_include" && -f "${python_include}/Python.h" ]] \
                                                    || missing_items+=("python3-dev (Python headers)")
        pkg-config --exists vamp-sdk 2>/dev/null    || missing_items+=("vamp-plugin-sdk (pkg-config)")
        pkg-config --exists alsa 2>/dev/null         || missing_items+=("libasound2-dev (pkg-config)")
        pkg-config --exists cairo 2>/dev/null        || missing_items+=("libcairo2-dev (pkg-config)")

        if [[ ${#missing_items[@]} -gt 0 ]]; then
            echo "Setup paused: required system packages are missing." >&2
            echo "" >&2
            echo "Missing:" >&2
            for item in "${missing_items[@]}"; do
                printf '  - %s\n' "$item" >&2
            done
            echo "" >&2
            echo "Automatic package-name mapping is only available on Debian/Ubuntu/Mint." >&2
            echo "Install the equivalent packages for your distribution and rerun:" >&2
            echo "  $(make_continuation_cmd)" >&2
            echo "" >&2
            echo "No virtual environment was created or modified." >&2
            exit 2
        fi
        return
    fi

    if [[ ${#missing_packages[@]} -gt 0 ]]; then
        echo "Setup paused: required system packages are missing." >&2
        echo "" >&2
        echo "Install them with:" >&2
        echo "  sudo apt update" >&2
        echo "  sudo apt install --no-install-recommends ${missing_packages[*]}" >&2
        echo "" >&2
        echo "Then continue with:" >&2
        echo "  $(make_continuation_cmd)" >&2
        echo "" >&2
        echo "No virtual environment was created or modified." >&2
        exit 2
    fi
}

validate_existing_venv() {
    local venv_python="${VENV_DIR}/bin/python3"
    if [[ ! -x "$venv_python" ]]; then
        echo "Existing virtual environment is incomplete: ${VENV_DIR}" >&2
        echo "Its Python interpreter is missing or not executable." >&2
        echo "Recreate it with:" >&2
        echo "  $(make_recreate_cmd)" >&2
        return 1
    fi

    if ! "$venv_python" -c 'import sys' >/dev/null 2>&1; then
        echo "Existing virtual environment is unusable: ${VENV_DIR}" >&2
        echo "Its Python interpreter could not start." >&2
        echo "Recreate it with:" >&2
        echo "  $(make_recreate_cmd)" >&2
        return 1
    fi
}

verify_installation() {
    local import_check
import_check=$(cat <<'PY'
import chordflask
import chordflask.analysis_queue
import chordflask.analysis_worker
import chordflask.chordanalyzer
import chordflask.chorddata
import chordflask.chordutils
import chordflask.filerepr
PY
)
    run_setup_command \
        "required application imports could not be verified" \
        "${VENV_DIR}/bin/python3" -c "$import_check"

    run_setup_command \
        "the installed chordflask command could not be verified" \
        "${VENV_DIR}/bin/chordflask" --version
    run_setup_command \
        "the installed chordflask help could not be verified" \
        "${VENV_DIR}/bin/chordflask" --help
    run_setup_command \
        "the installed chordflask-analyze command could not be verified" \
        "${VENV_DIR}/bin/chordflask-analyze" --help
    run_setup_command \
        "the installed chordflask-export command could not be verified" \
        "${VENV_DIR}/bin/chordflask-export" --help
    run_setup_command \
        "the installed chordflask-maintain command could not be verified" \
        "${VENV_DIR}/bin/chordflask-maintain" --help
    run_setup_command \
        "the installed chordflask-demucs command could not be verified" \
        "${VENV_DIR}/bin/chordflask-demucs" --help

    if [[ "$INSTALL_DEV" == true ]]; then
        run_setup_command \
            "developer/test imports could not be verified" \
            python3 -c 'import PyInstaller; import mido; import pytest; import ruff'
    fi

    if [[ "$INSTALL_OPTIONAL" == true ]]; then
        run_setup_command \
            "optional audio-playback imports could not be verified" \
            python3 -c 'import pydub; import simpleaudio'
    fi

    local vendor_dir="${ROOT_DIR}/vendor/vamp/linux-x86_64"
    if [[ -f "${vendor_dir}/nnls-chroma.so" && -f "${vendor_dir}/qm-vamp-plugins.so" ]]; then
        local plugin_check
        plugin_check=$(cat <<'PY'
import vamp

required = {
    "nnls-chroma:chordino",
    "qm-vamp-plugins:qm-barbeattracker",
}
available = set(vamp.list_plugins())
missing = sorted(required - available)
if missing:
    raise SystemExit("Vendored Vamp plugins were not discovered: " + ", ".join(missing))
PY
)
        run_setup_command \
            "vendored Vamp plugins could not be discovered" \
            env VAMP_PATH="$vendor_dir" python3 -c "$plugin_check"
    fi
}

PYTHON_BIN="$(select_python || true)"

if [[ -z "$PYTHON_BIN" ]]; then
    echo "No supported Python interpreter found (Python 3.10-3.14)." >&2
    echo "" >&2
    print_minimal_install
    echo "" >&2
    echo "Then rerun:" >&2
    echo "  $(make_continuation_cmd)" >&2
    echo "" >&2
    echo "No virtual environment was created or modified." >&2
    exit 2
fi

PYTHON_VERSION="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
case "$PYTHON_VERSION" in
    3.10|3.11|3.12|3.13)
        ;;
    3.14)
        echo "Using Python ${PYTHON_VERSION}. If a scientific package fails to build, retry with Python 3.12 or 3.13." >&2
        ;;
    *)
        echo "Unsupported or untested Python version: ${PYTHON_VERSION} (${PYTHON_BIN})" >&2
        echo "Use Python 3.10-3.14, for example:" >&2
        echo "  CHORDIFIER_PYTHON=python3.12 $0" >&2
        exit 1
        ;;
esac

if [[ ! -f "$REQUIREMENTS_FILE" ]]; then
    echo "Requirements file not found: ${REQUIREMENTS_FILE}" >&2
    exit 1
fi
if [[ "$INSTALL_DEV" == true && ! -f "$DEV_REQUIREMENTS_FILE" ]]; then
    echo "Developer requirements file not found: ${DEV_REQUIREMENTS_FILE}" >&2
    exit 1
fi
if [[ "$INSTALL_DEV" == true && ! -f "$BUILD_REQUIREMENTS_FILE" ]]; then
    echo "Build requirements file not found: ${BUILD_REQUIREMENTS_FILE}" >&2
    exit 1
fi
if [[ "$INSTALL_OPTIONAL" == true && ! -f "$OPTIONAL_REQUIREMENTS_FILE" ]]; then
    echo "Optional requirements file not found: ${OPTIONAL_REQUIREMENTS_FILE}" >&2
    exit 1
fi
if [[ ! -f "$PYTHON312_CONSTRAINTS_FILE" ]]; then
    echo "Python 3.12 constraints file not found: ${PYTHON312_CONSTRAINTS_FILE}" >&2
    exit 1
fi

check_system_prerequisites

if [[ "$RECREATE" == true && -d "$VENV_DIR" ]]; then
    echo "Removing existing virtual environment: ${VENV_DIR}"
    rm -rf "$VENV_DIR"
fi

if [[ ! -d "$VENV_DIR" ]]; then
    echo "Creating virtual environment with ${PYTHON_BIN} ${PYTHON_VERSION}: ${VENV_DIR}"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
else
    echo "Using existing virtual environment: ${VENV_DIR}"
    validate_existing_venv
    VENV_VERSION="$("${VENV_DIR}/bin/python3" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    case "$VENV_VERSION" in
        3.10|3.11|3.12|3.13)
            ;;
        3.14)
            echo "Existing venv uses Python ${VENV_VERSION}. If a scientific package fails to build, retry with Python 3.12 or 3.13." >&2
            ;;
        *)
            echo "Existing venv uses unsupported Python ${VENV_VERSION}: ${VENV_DIR}" >&2
            echo "Recreate it with:" >&2
            echo "  CHORDIFIER_PYTHON=python3.12 $0 --recreate" >&2
            exit 1
            ;;
    esac
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

ACTIVE_PYTHON_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PIP_CONSTRAINT_ARGS=()
if [[ "$ACTIVE_PYTHON_VERSION" == "3.12" ]]; then
    if [[ ! -f "$PYTHON312_CONSTRAINTS_FILE" ]]; then
        echo "Python 3.12 constraints file not found: ${PYTHON312_CONSTRAINTS_FILE}" >&2
        exit 1
    fi
    PIP_CONSTRAINT_ARGS=(-c "$PYTHON312_CONSTRAINTS_FILE")
fi

run_setup_command \
    "packaging prerequisites could not be installed" \
    python3 -m pip install --upgrade pip setuptools wheel
run_setup_command \
    "NumPy and Cython build prerequisites could not be installed" \
    python3 -m pip install "${PIP_CONSTRAINT_ARGS[@]}" --upgrade numpy Cython

run_setup_command \
    "the Python Vamp host could not be installed" \
    python3 -m pip install "${PIP_CONSTRAINT_ARGS[@]}" --no-build-isolation vamp
run_setup_command \
    "runtime requirements could not be installed" \
    python3 -m pip install "${PIP_CONSTRAINT_ARGS[@]}" -r "$REQUIREMENTS_FILE"

if [[ "$INSTALL_DEV" == true ]]; then
    run_setup_command \
        "developer/test requirements could not be installed" \
        python3 -m pip install "${PIP_CONSTRAINT_ARGS[@]}" -r "$DEV_REQUIREMENTS_FILE"
    run_setup_command \
        "standalone build requirements could not be installed" \
        python3 -m pip install "${PIP_CONSTRAINT_ARGS[@]}" -r "$BUILD_REQUIREMENTS_FILE"
fi

if [[ "$INSTALL_OPTIONAL" == true ]]; then
    run_setup_command \
        "optional requirements could not be installed" \
        python3 -m pip install "${PIP_CONSTRAINT_ARGS[@]}" -r "$OPTIONAL_REQUIREMENTS_FILE"
fi

run_setup_command \
    "the ChordFlask editable install could not be installed" \
    python3 -m pip install --no-deps --editable "${ROOT_DIR}"

verify_installation

# Retain the absolute checkout marker for compatibility and diagnostics. Normal
# source startup uses the editable install and does not read this marker.
ROOT_FILE="${VENV_DIR}/.chordflask-root"
printf '%s\n' "${ROOT_DIR}" > "${ROOT_FILE}"

cat <<DONE

Virtual environment is ready:
  ${VENV_DIR}

Activate it with:
  source "${VENV_DIR}/bin/activate"

Next steps:
  make check
  make run
DONE
