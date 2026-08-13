# Security Policy

## Supported deployment

ChordFlask is a **local-first trusted-user application**. It is designed for a
single user on a trusted machine. The server binds to loopback (`127.0.0.1`) by
default.

## What ChordFlask is NOT

- ChordFlask has **no authentication**, **no TLS**, and **no CSRF protection**.
- ChordFlask must not be exposed to untrusted networks, the public internet, or
  multi-user environments without explicit hardening.
- LAN exposure is opt-in only and remains restricted to configured media roots
  on a trusted network. Even then, ChordFlask provides no authentication.

## Supported versions

Only the latest `main` revision or latest published release is supported.

## Reporting a vulnerability

If you discover a security issue, please report it privately to the maintainer
at `git@isarlab.de`.
Do not open a public issue.

1. Describe the issue, affected components, and reproduction steps.
2. The maintainer will acknowledge within 5 business days.
3. A fix will be prepared and released before public disclosure.

## Local-first boundaries

- Non-loopback operation requires explicitly configured media roots, and the
  app rejects traversal outside them. Loopback-only trusted-user operation may
  browse other locally readable directories for compatibility.
- The web directory browser starts at the local user's home directory on
  loopback. On non-loopback listeners it exposes only configured media roots
  and hides parent navigation at each boundary.
- Flask debug mode is disabled by default and is rejected on non-loopback
  listeners even when explicitly requested.
- File-system operations resolve paths with `Path.resolve()` and validate
  containment.
- The queue persists to the user's home directory (`~/.chordflask/`) with file
  locking and atomic writes.
- No credentials, secrets, or authentication tokens are stored or transmitted.

## Third-party components

Vamp plugins and FFmpeg are external runtimes with their own security postures.
See `THIRD_PARTY_NOTICES.md` for provenance and licensing.
