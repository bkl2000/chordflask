"""Cross-process serialization for analysis JSON read-modify-write transactions."""

from contextlib import contextmanager
import fcntl
from pathlib import Path


@contextmanager
def analysis_json_lock(json_path):
    """Lock one resolved analysis path using F6's persistent lock namespace.

    Acquire before reading current state and hold through validation/publication.
    This lock is not reentrant: transaction owners must not acquire it again.
    Never unlink the lock file; replacing its inode defeats process exclusion.
    Atomic snapshot saves alone do not provide read-modify-write isolation.
    """
    path = Path(json_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.parent / f".{path.stem}.analysis.lock"
    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
