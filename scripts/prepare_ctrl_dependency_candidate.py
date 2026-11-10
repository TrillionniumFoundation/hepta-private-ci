"""Prepare one disposable, source-pinned dependency proposal; never adopt it."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import urllib.request


BASE = "99b194e64c83eb997344680b715c318d8e0d3cc8"
ARCHIVE_SHA = "488e99c397a62007e4229aec669a179816339afc6d2620ca6fa420dbee2e982c"
UPSTREAM = "10462fa4414c6c7f1ed1d39bb31678e3b726878c"
VENDOR = "codex-rs/third_party/sqlx-sqlite-0.9.0"
MATRIX = "codex-rs/third_party/matrix-sdk-sqlite-0.19.1"
PINNED = {
    "codex-rs/Cargo.toml": "d9f1bb1db407de3c2f1650edc4da5009ba3adaf1",
    "codex-rs/Cargo.lock": "46b1be5a5534631bf3151fbf1b3b1884451a8df9",
    MATRIX + "/Cargo.toml.orig": "ed8456d7a2013e879d52c2a119738d0ea3df2fe7",
}
PROPOSAL_FILES = {
    "scripts/prepare_ctrl_dependency_candidate.py",
    "scripts/align_ctrl_bindgen_syn.py",
    "scripts/tests/test_prepare_ctrl_dependency_candidate.py",
    ".github/workflows/ctrl-dependency-proposal.yml",
    "qualification/ctrl-metacontrol-20261109/DEPENDENCY_PROPOSAL.md",
    "qualification/ctrl-metacontrol-20261109/DEPENDENCY_SYN_REPAIR.md",
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError("Expected one exact manifest preimage: " + old)
    return text.replace(old, new)


def unpack(raw, destination):
    if sha(raw) != ARCHIVE_SHA:
        raise ValueError(
            "Official crate archive differs from the original lock checksum"
        )
    if destination.exists():
        raise ValueError("Never overwrite an existing vendor directory")
    files = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        for member in archive.getmembers():
            name = Path(member.name)
            if (
                name.is_absolute()
                or ".." in name.parts
                or not name.parts
                or name.parts[0] != "sqlx-sqlite-0.9.0"
                or member.issym()
                or member.islnk()
                or not (member.isfile() or member.isdir())
            ):
                raise ValueError(
                    "Archive member outside the fixed regular-file profile"
                )
            if member.isdir():
                continue
            relative = Path(*name.parts[1:]).as_posix()
            if relative in files or not relative or member.size > 8 * 1024**2:
                raise ValueError("Duplicate or oversized archive member")
            files[relative] = archive.extractfile(member).read()
            if len(files) > 512 or sum(map(len, files.values())) > 32 * 1024**2:
                raise ValueError("Archive exceeds the fixed extraction budget")
    for name, content in files.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return {name: sha(content) for name, content in files.items()}


def prepare(root, output):
    root, output = root.resolve(), output.resolve()
    if output.is_relative_to(root):
        raise ValueError("Execution evidence must remain outside the source checkout")
    if git(root, "status", "--porcelain"):
        raise ValueError("Candidate checkout must start clean")
    git(root, "merge-base", "--is-ancestor", BASE, "HEAD")
    changed = set(git(root, "diff", "--name-only", BASE, "HEAD").splitlines())
    if not changed <= PROPOSAL_FILES:
        raise ValueError("Existing source changed outside the reviewed proposal files")
    for name, expected in PINNED.items():
        if git(root, "hash-object", name) != expected:
            raise ValueError("Pinned dependency input differs: " + name)
    output.mkdir(parents=True, exist_ok=False)
    before = {name: sha((root / name).read_bytes()) for name in PINNED}
    url = "https://static.crates.io/crates/sqlx-sqlite/sqlx-sqlite-0.9.0.crate"
    with urllib.request.urlopen(url, timeout=60) as response:
        raw = response.read(8 * 1024**2 + 1)
    if len(raw) > 8 * 1024**2:
        raise ValueError("Crate download exceeds the declared bound")
    originals = unpack(raw, root / VENDOR)
    for name in ("Cargo.toml", "Cargo.toml.orig"):
        path = root / VENDOR / name
        path.write_text(
            replace_once(path.read_text(), ">=0.30.1, <0.38.0", ">=0.30.1, <0.40.0")
        )
    path = root / "codex-rs/Cargo.toml"
    text = replace_once(
        path.read_text(),
        'libsqlite3-sys = { version = "0.37",',
        'libsqlite3-sys = { version = "=0.39.1",',
    )
    text = replace_once(
        text, 'rmcp = { version = "=3.1.3",', 'rmcp = { version = "=3.9.0",'
    )
    matrix_line = (
        'matrix-sdk-sqlite = { path = "third_party/matrix-sdk-sqlite-0.19.1" }'
    )
    text = replace_once(
        text,
        matrix_line,
        matrix_line + '\nsqlx-sqlite = { path = "third_party/sqlx-sqlite-0.9.0" }',
    )
    path.write_text(text)
    for name in ("Cargo.toml", "Cargo.toml.orig"):
        path = root / MATRIX / name
        path.write_text(
            replace_once(path.read_text(), 'version = "=0.39.0"', 'version = "=0.41.1"')
        )
    for name, expected in originals.items():
        if (
            name not in {"Cargo.toml", "Cargo.toml.orig"}
            and sha((root / VENDOR / name).read_bytes()) != expected
        ):
            raise ValueError(
                "Vendored implementation differs from the official archive"
            )
    record = {
        "schema": "hepta.ctrl.dependency-proposal.v1",
        "base": BASE,
        "proposal_source": git(root, "rev-parse", "HEAD"),
        "before": before,
        "official_archive_sha256": ARCHIVE_SHA,
        "upstream_bound_backport": UPSTREAM,
        "vendor_original_files": originals,
        "targets": {"rmcp": "3.9.0", "libsqlite3-sys": "0.39.1", "rusqlite": "0.41.1"},
        "status": "prepared_not_resolved",
        "production_adoption": False,
        "custom_http_boundaries_qualified": False,
    }
    (output / "preparation.json").write_text(json.dumps(record, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.root, args.output)
