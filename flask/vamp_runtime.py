"""Verify Vamp plugins are discoverable before audio analysis starts."""

import os

import vamp


REQUIRED_PLUGINS = {
    "nnls-chroma:chordino",
    "qm-vamp-plugins:qm-barbeattracker",
}

INSTALL_HINT = (
    "From a ChordFlask source checkout, install the required Vamp plugins with: "
    "make plugins"
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
        hint = INSTALL_HINT
        if vamp_path:
            hint += " (current VAMP_PATH={})".format(vamp_path)
        raise RuntimeError(
            "Required Vamp plugins not found: {}. {}".format(
                ", ".join(missing), hint,
            )
        )
    return list(available)
