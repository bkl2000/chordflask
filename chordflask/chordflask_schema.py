"""Compatibility re-export of the Schema-v3 contract.

The implementation lives in :mod:`chordflask_base.schema`. This module only
keeps ``from chordflask.chordflask_schema import ...`` working for legacy
callers; new code should import from ``chordflask_base``.
"""

from chordflask_base.schema import *  # noqa: F401,F403
