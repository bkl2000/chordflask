"""Verify Vamp plugins are discoverable before audio analysis starts."""

import os
import shlex
import sys
from pathlib import Path

import vamp


REQUIRED_PLUGINS = {
    "nnls-chroma:chordino",
    "qm-vamp-plugins:qm-barbeattracker",
}

DEBIAN_INSTALLER = Path("/opt/chordflask/install_vamp.sh")


def vamp_installation_hint():
    if not getattr(sys, "frozen", False):
        return (
            "Install from a ChordFlask source checkout:\n  make plugins\n\n"
            "Verify:\n  chordflask --check-vamp\n\n"
            "Restart ChordFlask after installation, then retry the analysis."
        )

    executable = Path(os.path.realpath(sys.executable))
    installer = (
        DEBIAN_INSTALLER
        if executable.parent == DEBIAN_INSTALLER.parent
        else executable.with_name("install_vamp.sh")
    )
    verify = "chordflask" if installer == DEBIAN_INSTALLER else shlex.quote(str(executable))
    return (
        f"Install:\n  {shlex.quote(str(installer))}\n\n"
        f"Verify:\n  {verify} --check-vamp\n\n"
        "Restart ChordFlask after installation, then retry the analysis."
    )


def require_vamp_plugins():
    """Raise RuntimeError if the required Vamp plugins are not discoverable.

    ChordFlask never bundles Vamp plugin binaries. Callers receive a runtime
    error before media work starts when the target system has no plugins
    installed and VAMP_PATH does not point to a compatible installation.
    """
    available = set(vamp.list_plugins())
    missing = sorted(REQUIRED_PLUGINS - available)
    if missing:
        vamp_path = os.environ.get("VAMP_PATH", "")
        hint = vamp_installation_hint()
        if vamp_path:
            hint += " (current VAMP_PATH={})".format(vamp_path)
        raise RuntimeError(
            "Chord analysis is unavailable: required Vamp plugins are missing.\n\n"
            "{}\n\nRequired Vamp plugins not found: {}".format(
                hint, ", ".join(missing),
            )
        )
    return list(available)
