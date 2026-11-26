"""Verify retained evidence bytes and simple relative Markdown file links.

This is an integrity check, not scientific acceptance, repository CI status,
or proof that a producer's source/run claims are truthful. ZIPs are inspected
without extraction. Markdown fragments and external URLs are not validated.

A sibling gzip archive supplies the original bytes for a missing SVG or
registered historical record. The published manifest still checks the raw
size and digest. Use `gzip -dc` on the archive to recover the original.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
from urllib.parse import unquote, urlsplit
import zipfile
import zlib


_ARCHIVED_EVIDENCE = frozenset(
    {
        "qualification/hcsn_differentiable/evidence/localization-v2-20261108/publication/publication-http1-v3/stderr.txt",
        "qualification/hcsn_differentiable/evidence/localization-v2-20261108/publication/publication-inline-tree-v1/stderr.txt",
        "qualification/hcsn_differentiable/evidence/p0p5-20261110/publication/native-v8-publisher/verify.stdout",
        "qualification/hcsn_differentiable/evidence/p0p5-c2-progress-20261110/terminal-auditor/preparation/preparation-attempt-01/stderr",
        "qualification/hcsn_differentiable/evidence/p0p5-resource-replay-20261110/full-d-replay/publication/attempt-v1/asset-list-before.stderr",
        "qualification/hcsn_differentiable/evidence/localization-v2-20261108/math/stable-intervals.patch",
        "qualification/hcsn_differentiable/evidence/p0p5-c2-launch-20261110/preparation/v4/DIFF-v3-to-v4.patch",
        "qualification/hcsn_differentiable/evidence/p0p5-terminal-preparation-20261111/documentation-review/CURRENT.diff",
        "qualification/hcsn_differentiable/evidence/p0p5-terminal-preparation-20261111/renderer/program/DIFF-v2-to-v3.patch",
        "qualification/hcsn_differentiable/evidence/p0p5-terminal-preparation-20261111/supervisor/program/DIFF-v2-to-v3.patch",
    }
)


def _sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _relative_name(name):
    if (
        not isinstance(name, str)
        or not name
        or "\\" in name
        or "\0" in name
        or re.match(r"^[A-Za-z]:", name)
    ):
        raise ValueError(f"invalid relative path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in name.split("/")):
        raise ValueError(f"unsafe relative path: {name!r}")
    return path


def _contained(root, path):
    path = Path(path)
    lexical = path if path.is_absolute() else root / path
    resolved = lexical.resolve()
    resolved.relative_to(root)
    if not resolved.is_file():
        raise FileNotFoundError(str(lexical))
    if lexical.is_symlink():
        raise ValueError(f"symlink evidence is unsupported: {lexical}")
    return resolved


def _zip_check(path):
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        names = []
        for member in members:
            name = member.filename[:-1] if member.is_dir() else member.filename
            _relative_name(name)
            if stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError(f"symlink ZIP member: {member.filename}")
            names.append(name)
        if len(names) != len(set(names)):
            raise ValueError("duplicate ZIP member names")
        expanded = sum(member.file_size for member in members)
        if expanded > 1024**3:
            raise ValueError("ZIP expanded size exceeds the 1 GiB inspection budget")
        bad = archive.testzip()
        if bad is not None:
            raise ValueError(f"ZIP CRC mismatch: {bad}")
        return dict(members=len(members), expanded_bytes=expanded, crc_passed=True)


def _manifest_member(root, manifest_dir, name, expected_size):
    logical = manifest_dir / name
    logical.resolve().relative_to(manifest_dir)
    archived_evidence = logical.relative_to(root).as_posix() in _ARCHIVED_EVIDENCE
    if logical.exists() or logical.is_symlink() or (
        logical.suffix != ".svg" and not archived_evidence
    ):
        stored = _contained(root, logical)
        stored.relative_to(manifest_dir)
        return stored, dict(bytes=stored.stat().st_size, sha256=_sha(stored)), None

    # Only a sibling archive may supply bytes, and a raw file is never masked.
    suffix = ".evidence.gz" if archived_evidence else ".gz"
    stored = _contained(root, logical.with_name(logical.name + suffix))
    stored.relative_to(manifest_dir)
    transport_sha = _sha(stored)
    digest = hashlib.sha256()
    size = 0
    with gzip.open(stored, "rb") as stream:
        while chunk := stream.read(min(64 * 1024, expected_size - size + 1)):
            size += len(chunk)
            if size > expected_size:
                raise ValueError("archived evidence exceeds the declared byte count")
            digest.update(chunk)
    return stored, dict(bytes=size, sha256=digest.hexdigest()), transport_sha


def _source_map(root):
    source = root / "qualification/hcsn_differentiable"
    return {
        str(p.relative_to(root)): _sha(p)
        for p in sorted(source.rglob("*"))
        if p.is_file()
        and p.suffix in (".py", ".md", ".json")
        and "evidence" not in p.relative_to(source).parts
        and "__pycache__" not in p.parts
    }


def verify_evidence(repo_root, manifests, markdown=()):
    """Return all observed failures; manifest paths are relative to each manifest."""
    root = Path(repo_root).resolve()
    before = _source_map(root)
    inputs, files, archives, links, errors = {}, {}, {}, [], []
    file_locations, archived_files = {}, {}
    manifests = tuple(manifests)
    if not manifests:
        errors.append(dict(error="at least one evidence manifest is required"))
    for name in manifests:
        try:
            manifest = _contained(root, name)
            relative = str(manifest.relative_to(root))
            inputs[relative] = _sha(manifest)
            document = json.loads(manifest.read_text(), object_pairs_hook=_strict_pairs)
            entries = document["files"]
            if not isinstance(entries, dict) or not entries:
                raise ValueError("manifest files must be a nonempty mapping")
            for member, expected in entries.items():
                try:
                    relative_member = _relative_name(member)
                    if (
                        not isinstance(expected, dict)
                        or isinstance(expected.get("bytes"), bool)
                        or not isinstance(expected.get("bytes"), int)
                        or expected["bytes"] < 0
                        or not re.fullmatch(
                            r"[0-9a-f]{64}", str(expected.get("sha256", ""))
                        )
                    ):
                        raise ValueError("invalid expected bytes/sha256")
                    path, actual, transport_sha = _manifest_member(
                        root, manifest.parent, relative_member, expected["bytes"]
                    )
                    logical = manifest.parent / relative_member
                    logical_name = str(logical.relative_to(root))
                    physical_name = str(path.relative_to(root))
                    location = (physical_name, transport_sha)
                    if logical_name in files and (
                        files[logical_name] != actual
                        or file_locations[logical_name] != location
                    ):
                        raise ValueError("evidence changed between manifests")
                    files[logical_name] = actual
                    file_locations[logical_name] = location
                    if transport_sha is not None:
                        archived_files[logical_name] = dict(
                            path=physical_name, sha256=transport_sha, encoding="gzip"
                        )
                    if actual != {key: expected[key] for key in ("bytes", "sha256")}:
                        raise ValueError("file byte count or SHA256 mismatch")
                    if path.suffix.lower() == ".zip":
                        archives[str(path.relative_to(root))] = _zip_check(path)
                except (
                    OSError,
                    EOFError,
                    ValueError,
                    KeyError,
                    RuntimeError,
                    zipfile.BadZipFile,
                    zlib.error,
                ) as error:
                    errors.append(dict(input=relative, member=member, error=str(error)))
        except (OSError, ValueError, KeyError, TypeError) as error:
            errors.append(dict(input=str(name), error=str(error)))
    for name in markdown:
        try:
            document = _contained(root, name)
            relative = str(document.relative_to(root))
            inputs[relative] = _sha(document)
            content = re.sub(r"```.*?```", "", document.read_text(), flags=re.S)
            for target in re.findall(r"\[[^\]]*\]\(([^\s)]+)\)", content):
                try:
                    parsed = urlsplit(target)
                    if parsed.scheme or parsed.netloc or not parsed.path:
                        continue
                    link = document.parent / unquote(parsed.path)
                    try:
                        path = _contained(root, link)
                    except FileNotFoundError:
                        logical = link.resolve().relative_to(root)
                        archived = archived_files.get(str(logical))
                        if (
                            logical.as_posix() not in _ARCHIVED_EVIDENCE
                            or archived is None
                            or link.is_symlink()
                        ):
                            raise
                        path = _contained(root, archived["path"])
                    links.append(
                        dict(
                            document=relative,
                            target=target,
                            resolved=str(path.relative_to(root)),
                        )
                    )
                except (OSError, ValueError) as error:
                    errors.append(dict(input=relative, target=target, error=str(error)))
        except (OSError, ValueError) as error:
            errors.append(dict(input=str(name), error=str(error)))
    after = _source_map(root)
    if after != before:
        errors.append(dict(error="source files changed during verification"))
    for name, digest in inputs.items():
        if not (root / name).is_file() or _sha(root / name) != digest:
            errors.append(dict(input=name, error="input changed during verification"))
    for name, record in files.items():
        physical_name, transport_sha = file_locations[name]
        try:
            path = _contained(root, physical_name)
            if transport_sha is not None:
                logical = root / name
                if logical.exists() or logical.is_symlink():
                    raise ValueError("raw evidence appeared during archive verification")
            if _sha(path) == (transport_sha or record["sha256"]):
                continue
        except (OSError, ValueError, RuntimeError):
            pass
        errors.append(
            dict(input=name, error="evidence changed during verification")
        )
    try:
        head, tree = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD", "HEAD^{tree}"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).splitlines()
    except (OSError, subprocess.CalledProcessError, ValueError):
        head = tree = None
    return dict(
        schema="hcsn-evidence-chain-integrity-v1",
        passed=not errors,
        errors=errors,
        git_head=head,
        git_committed_tree=tree,
        source_sha256=before,
        source_tree_digest=hashlib.sha256(
            json.dumps(before, sort_keys=True).encode()
        ).hexdigest(),
        input_sha256=inputs,
        verified_files=files,
        archived_files=archived_files,
        archives=archives,
        relative_links=links,
        atomic_snapshot=False,
        markdown_scope="simple inline relative file links; no fragments or external URLs",
        numerical_qualification=False,
        scientific_benefit=False,
        repository_ci_pass=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--manifest", type=Path, action="append", required=True)
    parser.add_argument("--markdown", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("preserve existing evidence; choose a new output path")
    report = verify_evidence(args.repo_root, args.manifest, args.markdown)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            dict(
                passed=report["passed"],
                files=len(report["verified_files"]),
                errors=len(report["errors"]),
            )
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
