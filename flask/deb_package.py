"""Build and verify a Debian installation wrapper for the standalone payload."""

from __future__ import annotations

import argparse
import io
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_standalone_runtime import _recursive_listing, find_offenders  # noqa: E402

FILES = tuple((ROOT / "flask/standalone-files.txt").read_text().splitlines())
COMMANDS = ("chordflask", *(name for name in FILES if name.startswith("chordflask-")))
EXECUTABLES = (*COMMANDS, "chordflask.sh", "install_vamp.sh")


def run(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def validate_bundle(bundle: Path, version: str) -> None:
    if set(path.name for path in bundle.iterdir()) != set(FILES):
        raise ValueError("standalone files differ from standalone-files.txt (missing or forbidden content)")
    for name in FILES:
        path = bundle / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"missing/invalid standalone file: {name}")
    for name in EXECUTABLES:
        if not os.access(bundle / name, os.X_OK):
            raise ValueError(f"standalone command is not executable: {name}")
    if (bundle / "VERSION").read_text().split()[0] != version:
        raise ValueError("standalone version differs from VERSION")
    # PyInstaller's Linux x86_64 bootloader is ELF64, little-endian, EM_X86_64.
    with (bundle / "chordflask").open("rb") as executable:
        header = executable.read(20)
    if header[:6] != b"\x7fELF\x02\x01" or header[18:20] != b"\x3e\x00":
        raise ValueError("standalone executable is not Linux amd64 ELF")
    offenders = find_offenders(_recursive_listing(str(bundle / "chordflask")))
    if offenders:
        raise ValueError(f"forbidden standalone runtime entries: {offenders}")


def verify(package: Path, version: str, archive: Path | None = None) -> None:
    if package.is_symlink() or not re.fullmatch(
        rf"chordflask-[A-Za-z0-9._-]+-x86_64-py[0-9.]+-v{re.escape(version)}[.]deb", package.name
    ):
        raise ValueError("unexpected Debian package filename")
    for field, expected in (("Package", "chordflask"), ("Version", version), ("Architecture", "amd64")):
        if run("dpkg-deb", "-f", str(package), field) != expected:
            raise ValueError(f"Debian {field} differs from {expected}")
    for field in ("Maintainer", "Description"):
        if not run("dpkg-deb", "-f", str(package), field):
            raise ValueError(f"missing Debian metadata: {field}")
    # Validate the archive tree before extraction, including empty directories
    # and symlink targets. Only the known payload and command links are allowed.
    expected_files = {f"opt/chordflask/{name}" for name in FILES}
    expected_links = {f"usr/bin/{name}": f"../../opt/chordflask/{name}" for name in COMMANDS}
    directories = {"", ".", "opt", "opt/chordflask", "usr", "usr/bin"}
    data = subprocess.check_output(["dpkg-deb", "--fsys-tarfile", str(package)])
    with tarfile.open(fileobj=io.BytesIO(data)) as payload:
        for member in payload.getmembers():
            name = member.name.removeprefix("./").rstrip("/")
            if member.isdir() and name in directories:
                continue
            if member.isfile() and name in expected_files:
                continue
            if member.issym() and expected_links.get(name) == member.linkname:
                continue
            raise ValueError(f"unexpected/forbidden Debian package path: {member.name}")
    control_data = subprocess.check_output(["dpkg-deb", "--ctrl-tarfile", str(package)])
    with tarfile.open(fileobj=io.BytesIO(control_data)) as control_archive:
        for member in control_archive.getmembers():
            name = member.name.removeprefix("./").rstrip("/")
            if not ((member.isdir() and name in {"", "."}) or (member.isfile() and name == "control")):
                raise ValueError("unexpected Debian control files or maintainer scripts")
    with tempfile.TemporaryDirectory(prefix="chordflask-deb-verify-") as temp:
        tree = Path(temp)
        subprocess.run(["dpkg-deb", "-x", str(package), temp], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["dpkg-deb", "-e", str(package), str(tree / "control")], check=True)
        if set(path.name for path in (tree / "control").iterdir()) != {"control"}:
            raise ValueError("unexpected Debian control files or maintainer scripts")
        bundle = tree / "opt/chordflask"
        validate_bundle(bundle, version)
        expected_paths = {f"opt/chordflask/{name}" for name in FILES} | {
            f"usr/bin/{name}" for name in COMMANDS
        }
        actual_paths = {
            str(path.relative_to(tree)) for path in tree.rglob("*") if path.is_symlink() or path.is_file()
        }
        if actual_paths != expected_paths | {"control/control"}:
            raise ValueError("unexpected/forbidden Debian package paths")
        for name in COMMANDS:
            link = tree / "usr/bin" / name
            if not link.is_symlink() or os.readlink(link) != f"../../opt/chordflask/{name}":
                raise ValueError(f"invalid command link: {name}")
            if link.resolve() != bundle / name:
                raise ValueError(f"command does not resolve into payload: {name}")
        if archive:
            if package.name != archive.name.removesuffix(".tar.gz") + ".deb":
                raise ValueError("Debian build platform differs from portable archive")
            with tarfile.open(archive) as portable:
                members = [member for member in portable.getmembers() if not member.isdir()]
                archive_root = archive.name.removesuffix(".tar.gz")
                if any(
                    member.isdir() and member.name.rstrip("/") != archive_root
                    for member in portable.getmembers()
                ):
                    raise ValueError("portable archive has forbidden directories")
                roots = {member.name.split("/")[0] for member in members}
                if (
                    roots != {archive_root}
                    or len(members) != len(FILES)
                    or {member.name.split("/", 1)[-1] for member in members} != set(FILES)
                ):
                    raise ValueError("portable archive has missing or forbidden files")
                for member in members:
                    name = member.name.split("/", 1)[-1]
                    if (
                        not member.isfile()
                        or portable.extractfile(member).read() != (bundle / name).read_bytes()
                    ):
                        raise ValueError(f"Debian payload differs from portable archive: {name}")
                    if member.mode & 0o777 != (bundle / name).stat().st_mode & 0o777:
                        raise ValueError(f"Debian payload permissions differ: {name}")


def build(bundle: Path, output: Path, version: str) -> Path:
    validate_bundle(bundle, version)
    output.mkdir(parents=True, exist_ok=True)
    package = output / f"{bundle.name}.deb"
    with tempfile.TemporaryDirectory(prefix=".deb-", dir=output) as temp:
        staging = Path(temp) / "root"
        payload = staging / "opt/chordflask"
        shutil.copytree(bundle, payload, copy_function=shutil.copy2)
        commands = staging / "usr/bin"
        commands.mkdir(parents=True)
        for name in COMMANDS:
            (commands / name).symlink_to(f"../../opt/chordflask/{name}")
        # Measure only the installed tree, before adding Debian control files.
        installed_size_kib = int(run("du", "-sk", str(staging)).split()[0])
        control = staging / "DEBIAN"
        control.mkdir()
        (control / "control").write_text(
            f"Package: chordflask\nVersion: {version}\nArchitecture: amd64\n"
            "Maintainer: ChordFlask Maintainer <git@isarlab.de>\n"
            "Section: sound\nPriority: optional\nDepends: ffmpeg\n"
            f"Installed-Size: {installed_size_kib}\n"
            "Description: Local chord and rhythm analysis with synchronized playback\n"
            " Bundled standalone runtime. Vamp plugins are installed separately.\n"
        )
        temporary_package = Path(temp) / package.name
        subprocess.run(
            ["dpkg-deb", "--root-owner-group", "-Zgzip", "--build", str(staging), str(temporary_package)],
            check=True,
        )
        verify(temporary_package, version)
        temporary_package.replace(package)
    return package


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    builder = actions.add_parser("build")
    builder.add_argument("bundle", type=Path)
    builder.add_argument("output", type=Path)
    verifier = actions.add_parser("verify")
    verifier.add_argument("package", type=Path)
    verifier.add_argument("--archive", type=Path)
    args = parser.parse_args()
    version = (ROOT / "VERSION").read_text().strip()
    try:
        if args.action == "build":
            print(build(args.bundle, args.output, version))
        else:
            verify(args.package, version, args.archive)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"ERROR: {error}\n")


if __name__ == "__main__":
    main()
