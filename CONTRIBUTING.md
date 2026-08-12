# Contributing to ChordFlask

Thank you for your interest in contributing to ChordFlask.

## Setup

```bash
make setup
source ~/.venvs/chordifier/bin/activate
```

Required system packages (Ubuntu/Debian):

```bash
sudo apt install ffmpeg pkg-config vamp-plugin-sdk python3-venv python3-dev build-essential libasound2-dev libcairo2-dev
```

Required Vamp plugins:

```bash
scripts/install_vamp_plugins.sh
```

## Development workflow

1. Open or select an issue with a bounded scope.
2. Make focused, testable changes without changing unrelated public APIs.
3. Add tests for public behavior and failure paths affected by the change.
4. Run `make check` before submitting.

## Tests

```bash
make check          # full suite: pytest + compile checks + git diff
make test           # pytest only
make lint           # Ruff (when configured)
```

Tests use pytest with plain `assert`. No `unittest.TestCase`.

## Code style

Keep code simple, compact, and teachable. Prefer small functions and explicit
I/O boundaries. Use type hints where they clarify data flow. Keep existing
public APIs stable unless a change is explicitly agreed first.

## Commit messages

- Small, coherent changes
- Describe what changed and why

## Reporting issues

For security issues, see `SECURITY.md`. For other bugs or feature requests,
open an issue on the project repository.

## License

ChordFlask-owned source is MIT. Third-party components retain their own licenses.
See `THIRD_PARTY_NOTICES.md` and `LICENSE` for details.

By submitting a contribution, you confirm that you created it or otherwise
have the right to submit it, and that it may be distributed under the MIT
license. Identify third-party material explicitly and preserve its applicable
copyright and license notices.
