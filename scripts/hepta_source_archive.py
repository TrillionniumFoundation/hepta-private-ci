"""Compare a complete tar source archive with a clean, pinned Git checkout.

This POSIX-only integrity check never extracts members. It does not authenticate
test execution, CI, publication, runtime use, or scientific/production adoption.
"""

import argparse
from contextlib import ExitStack
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile

from hepta_cell_joint_config import (
    directory_root,
    file_fingerprint,
    git,
    parent_directory,
    read_artifact,
    regular_file,
    source_identity,
    strict_json,
)


SCHEMA = "hepta.source-archive-binding.v1"
CHUNK = 1024 * 1024
OID = re.compile(r"[0-9a-f]{40}")


def result_base():
    return {
        "schema": "hepta.source-archive-integrity.v1",
        "scope": "complete tracked Git source bytes and Git modes only",
        "integrity_only": True,
        "integrity_verified": False,
        "test_execution_authenticated": False,
        "ci_authenticated": False,
        "publication_authenticated": False,
        "runtime_use_authenticated": False,
        "research_advancement": False,
        "production_qualification": False,
        "authority_granted": False,
    }


def source_pin(value):
    if not isinstance(value, dict) or set(value) != {"commit", "tree"}:
        raise ValueError("source pin requires exactly commit and tree")
    if any(not isinstance(x, str) or OID.fullmatch(x) is None for x in value.values()):
        raise ValueError("source pin requires complete lowercase Git SHA-1 identities")
    return dict(value)


def safe_path(name):
    if (
        not isinstance(name, str)
        or not name
        or "\\" in name
        or "\0" in name
        or ":" in name
        or any(part in ("", ".", "..") for part in name.split("/"))
    ):
        raise ValueError(f"noncanonical or escaping archive path: {name!r}")
    return name


def safe_link(name, target):
    if not target or target.startswith("/") or any(c in target for c in "\\\0:"):
        raise ValueError(f"absolute or ambiguous symlink target: {name}")
    parts = name.split("/")[:-1]
    for part in target.split("/"):
        if part == "..":
            if not parts:
                raise ValueError(f"escaping symlink target: {name}")
            parts.pop()
        elif part not in ("", "."):
            parts.append(part)


class LimitedReader:
    """Bound decompressed metadata and payload before tarfile allocates it."""

    def __init__(self, stream, limit):
        self.stream = stream
        self.remaining = limit

    def read(self, size):
        if size < 0:
            raise ValueError("unbounded archive read refused")
        raw = self.stream.read(min(size, self.remaining + 1))
        self.remaining -= len(raw)
        if self.remaining < 0:
            raise ValueError("archive exceeds the complete Git tree size bound")
        return raw


def tree_entries(root, tree):
    raw = subprocess.check_output(
        ["git", "-C", str(root), "ls-tree", "-rlz", "--full-tree", tree],
        stderr=subprocess.PIPE,
    )
    files, directories = {}, set()
    for item in raw.split(b"\0"):
        if not item:
            continue
        header, name = item.split(b"\t", 1)
        mode, kind, oid, size = header.split()
        if kind != b"blob" or mode not in (b"100644", b"100755", b"120000"):
            raise ValueError("source requires tracked blobs, no submodules")
        name = safe_path(os.fsdecode(name))
        files[name] = (mode.decode(), oid.decode(), int(size))
        parts = name.split("/")
        directories.update("/".join(parts[:n]) for n in range(1, len(parts)))
    return files, directories


def compare_archive(source_fd, artifact_fd, pin, version, files, directories, prefix):
    seen, observed, inventory = set(), set(), []
    wrappers = (
        {"/".join(prefix.split("/")[:n]) for n in range(1, len(prefix.split("/")) + 1)}
        if prefix
        else set()
    )
    limit = sum((size + 511) // 512 * 512 for _, _, size in files.values())
    limit += (len(files) + len(directories) + len(wrappers) + 1) * 16384 + 10240
    with ExitStack() as stack:
        stream = stack.enter_context(regular_file(artifact_fd, pin["path"]))
        if file_fingerprint(os.fstat(stream.fileno())) != version:
            raise ValueError("archive changed after its byte pin was verified")
        magic = stream.read(2)
        stream.seek(0)
        compressed = magic == b"\x1f\x8b"
        decoded = (
            stack.enter_context(gzip.GzipFile(fileobj=stream)) if compressed else stream
        )
        archive = stack.enter_context(
            tarfile.open(fileobj=LimitedReader(decoded, limit), mode="r|")
        )
        for member in archive:
            name = (
                member.name[:-1]
                if member.isdir() and member.name.endswith("/")
                else member.name
            )
            safe_path(name)
            if name in seen:
                raise ValueError(f"duplicate archive member: {name}")
            seen.add(name)
            if member.type not in (
                tarfile.REGTYPE,
                tarfile.AREGTYPE,
                tarfile.DIRTYPE,
                tarfile.SYMTYPE,
            ):
                raise ValueError(f"unsupported archive member type: {name}")
            if member.mode & ~0o777 or member.sparse is not None:
                raise ValueError(
                    f"special permissions or sparse member refused: {name}"
                )
            if name in wrappers:
                if not member.isdir() or member.size:
                    raise ValueError(
                        "archive prefix must contain only directory envelopes"
                    )
                continue
            if prefix:
                if not name.startswith(prefix + "/"):
                    raise ValueError(
                        f"member is outside the explicit archive prefix: {name}"
                    )
                name = name[len(prefix) + 1 :]
            if member.isdir():
                if name not in directories or member.size:
                    raise ValueError(f"extra or malformed archive directory: {name}")
                continue
            if name not in files:
                raise ValueError(f"extra archive source: {name}")
            mode, oid, size = files[name]
            digest = hashlib.sha256()
            blob = hashlib.sha1(b"blob " + str(size).encode() + b"\0")
            if mode == "120000":
                if not member.issym() or member.size:
                    raise ValueError(f"archive symlink type mismatch: {name}")
                safe_link(name, member.linkname)
                raw = os.fsencode(member.linkname)
                with parent_directory(source_fd, name) as (parent, leaf):
                    if raw != os.fsencode(os.readlink(leaf, dir_fd=parent)):
                        raise ValueError(f"archive symlink bytes differ: {name}")
                if len(raw) != size:
                    raise ValueError(f"archive symlink size differs: {name}")
                digest.update(raw)
                blob.update(raw)
            else:
                actual_mode = "100755" if member.mode & 0o111 else "100644"
                if not member.isfile() or actual_mode != mode or member.size != size:
                    raise ValueError(f"archive file type, mode or size differs: {name}")
                with (
                    regular_file(source_fd, name) as original,
                    archive.extractfile(member) as payload,
                ):
                    before = file_fingerprint(os.fstat(original.fileno()))
                    total = 0
                    while raw := payload.read(CHUNK):
                        total += len(raw)
                        if original.read(len(raw)) != raw:
                            raise ValueError(f"archive file bytes differ: {name}")
                        digest.update(raw)
                        blob.update(raw)
                    if (
                        total != size
                        or original.read(1)
                        or file_fingerprint(os.fstat(original.fileno())) != before
                    ):
                        raise ValueError(
                            f"source file changed during archive comparison: {name}"
                        )
            if blob.hexdigest() != oid:
                raise ValueError(
                    f"archive bytes differ from the pinned Git blob: {name}"
                )
            observed.add(name)
            inventory.append(
                {
                    "path": name,
                    "git_mode": mode,
                    "git_blob": oid,
                    "archive_mode": oct(member.mode),
                    "bytes": size,
                    "sha256": digest.hexdigest(),
                }
            )
        # tarfile stops at the first zero header; consume every remaining byte.
        if archive.fileobj.tell() - archive.offset != 512:
            raise ValueError("archive is missing its first end marker")
        padding = 0
        while raw := archive.fileobj.read(CHUNK):
            padding += len(raw)
            if any(raw):
                raise ValueError("trailing nonzero archive data refused")
        if padding < 512 or padding % 512:
            raise ValueError("archive is missing its complete end markers")
        if file_fingerprint(os.fstat(stream.fileno())) != version:
            raise ValueError("archive changed during comparison")
    missing = sorted(set(files) - observed)
    if missing:
        raise ValueError(
            f"archive is missing {len(missing)} tracked paths: {missing[:10]!r}"
        )
    return sorted(
        inventory, key=lambda item: item["path"]
    ), "tar.gz" if compressed else "tar"


def verify(binding, source_root, artifact_root):
    required = {"schema", "tested_source", "archive"}
    optional = {"archive_prefix", "runtime_configuration", "release_source"}
    if (
        not isinstance(binding, dict)
        or not required <= set(binding)
        or set(binding) - required - optional
    ):
        raise ValueError(
            "binding has missing or unknown fields; exclusions are unsupported"
        )
    if binding["schema"] != SCHEMA:
        raise ValueError("unsupported source archive binding schema")
    tested = source_pin(binding["tested_source"])
    release = (
        source_pin(binding["release_source"]) if "release_source" in binding else None
    )
    prefix = binding.get("archive_prefix", "")
    if prefix != "":
        safe_path(prefix)
    before = source_identity(source_root)
    if {key: before[key] for key in tested} != tested:
        raise ValueError("clean checkout does not match the exact tested commit/tree")
    if release is not None:
        observed = {
            "commit": git(
                source_root, "rev-parse", "--verify", release["commit"] + "^{commit}"
            ),
            "tree": git(
                source_root, "rev-parse", "--verify", release["commit"] + "^{tree}"
            ),
        }
        if observed != release:
            raise ValueError(
                "release observation differs from the supplied commit/tree"
            )
    files, directories = tree_entries(source_root, tested["tree"])
    with (
        directory_root(source_root) as source_fd,
        directory_root(artifact_root) as artifact_fd,
    ):
        pin, _, version = read_artifact(artifact_fd, binding["archive"])
        config, config_version = None, None
        if "runtime_configuration" in binding:
            config, _, config_version = read_artifact(
                artifact_fd, binding["runtime_configuration"]
            )
        inventory, archive_format = compare_archive(
            source_fd, artifact_fd, pin, version, files, directories, prefix
        )
        for item, expected in ((pin, version), (config, config_version)):
            if item is not None:
                with regular_file(artifact_fd, item["path"]) as stream:
                    if file_fingerprint(os.fstat(stream.fileno())) != expected:
                        raise ValueError(
                            "bound artifact path changed during verification"
                        )
    if source_identity(source_root) != before:
        raise ValueError("source checkout changed during verification")
    result = result_base()
    result.update(
        {
            "integrity_verified": True,
            "tested_source": before,
            "release_observation": release,
            "release_observation_scope": "local Git commit/tree only; no publication or execution inference",
            "source_archive": pin,
            "archive_format": archive_format,
            "archive_prefix": prefix,
            "runtime_configuration": config,
            "mode_policy": "Git kind and executable classification; original tar permission bits retained; special bits refused",
            "files": inventory,
            "inventory_sha256": hashlib.sha256(
                json.dumps(
                    inventory, sort_keys=True, ensure_ascii=True, separators=(",", ":")
                ).encode()
            ).hexdigest(),
        }
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        with args.binding.open("rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError("binding exceeds the 64 KiB limit")
        report = verify(strict_json(raw), args.source_root, args.artifact_root)
        status = 0
    except (
        ValueError,
        OSError,
        EOFError,
        tarfile.TarError,
        subprocess.CalledProcessError,
    ) as error:
        report = result_base()
        report["error"] = str(error)
        status = 1
    output = json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    if args.output is None:
        print(output, end="")
    else:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(output)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
