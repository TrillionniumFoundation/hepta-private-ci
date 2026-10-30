#!/usr/bin/env python3
"""Retain original audit bytes in deterministic, bounded archives outside Git.

This script does not run tests, edit a checkout, copy to repository evidence,
publish, or derive a qualification result from execution records.
"""

import argparse
import gzip
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path


LIMIT = 512_000
SOURCE_FILES = (
    ".gitattributes",
    "CALLERS.toml",
    "defs.bzl",
    "codex-rs/hepta-agentd/BUILD.bazel",
    "scripts/verify_hepta_callers.py",
    "qa/b4-no-bypass/test_verify_hepta_callers.py",
    ".github/scripts/run_bazel_with_buildbuddy.py",
    ".github/scripts/test_run_bazel_native_msvc_toolchain.py",
    ".github/workflows/hepta-pon-native-pair.yml",
)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def source_hashes(checkout):
    if checkout is None:
        return None
    return {
        name: {"bytes": len(raw), "sha256": digest(raw)}
        for name in SOURCE_FILES
        for raw in [(checkout / name).read_bytes()]
    }


def archive_bytes(members):
    output = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0, compresslevel=9) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for name, raw in sorted(members):
                info = tarfile.TarInfo(name)
                info.size = len(raw)
                info.mtime = info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mode = 0o644
                archive.addfile(info, io.BytesIO(raw))
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation-root", type=Path, required=True)
    parser.add_argument("--selection", type=Path, action="append", required=True)
    parser.add_argument("--readme", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-checkout", type=Path)
    args = parser.parse_args()
    root = args.validation_root.resolve()
    output = args.output.resolve()
    if not output.is_relative_to(root) or output == root or output.exists():
        raise SystemExit("output must be a new directory below validation-root, outside the checkout")
    for parent in (output, *output.parents):
        git = parent / ".git"
        if (git.is_dir() and (git / "HEAD").is_file()) or (git.is_file() and git.read_bytes().startswith(b"gitdir:")):
            raise SystemExit("repository output is deliberately unsupported")
    checkout = args.source_checkout.resolve() if args.source_checkout else None
    if checkout and output.is_relative_to(checkout):
        raise SystemExit("repository output is deliberately unsupported")
    before = source_hashes(checkout)
    selections = [json.loads(path.read_bytes()) for path in args.selection]
    context = selections[0]["context"]
    groups = {}
    scopes = {}
    records = []
    originals = {}
    seen = set()
    for selection in selections:
        if "context" in selection and selection["context"] != context:
            raise SystemExit("supplement context differs from the base selection")
        for group in selection["groups"]:
            name = group["name"]
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
                raise SystemExit(f"unsafe archive group: {name}")
            if name in scopes and scopes[name] != group["scope"]:
                raise SystemExit(f"conflicting group scope: {name}")
            scopes[name] = group["scope"]
            for relative in group["files"]:
                path = root / relative
                if Path(relative).is_absolute() or ".." in Path(relative).parts or path.is_symlink() or not path.resolve().is_relative_to(root):
                    raise SystemExit(f"unsafe input path: {relative}")
                if relative in seen:
                    raise SystemExit(f"duplicate input; retain it in only one group: {relative}")
                seen.add(relative)
                raw = path.read_bytes()
                originals[relative] = digest(raw)
                groups.setdefault(name, []).append((relative, raw))
                record = {"source": relative, "archive": name + ".tar.gz", "member": relative,
                          "bytes": len(raw), "sha256": digest(raw), "scope": group["scope"]}
                if path.suffix == ".json":
                    value = json.loads(raw)
                    if isinstance(value, dict):
                        record["original_observation_fields"] = {
                            key: value[key] for key in ("scope", "command", "status", "exit_code", "source_stable", "red", "green")
                            if key in value
                        }
                records.append(record)
    products = {name + ".tar.gz": archive_bytes(members) for name, members in sorted(groups.items())}
    after = source_hashes(checkout)
    if before != after:
        raise SystemExit("checkout source changed during assembly; no bundle written")
    if any(digest((root / relative).read_bytes()) != sha for relative, sha in originals.items()):
        raise SystemExit("an original input changed during assembly; no bundle written")
    index = {
        "purpose": "Raw observations and source identity only; not a status authority, waiver, plan, acceptance or qualification.",
        "context": context,
        "source_observation": {"files": after, "stable_during_assembly": before == after} if checkout else None,
        "source_observation_note": "Current source bytes, including configured pair workflow, do not retarget prior execution records to a new commit or pair.",
        "archives": [{"path": name, "bytes": len(raw), "sha256": digest(raw)} for name, raw in sorted(products.items())],
        "members": sorted(records, key=lambda row: (row["archive"], row["member"])),
        "storage": {"blob_limit_exclusive": LIMIT, "tar_mtime_uid_gid": 0, "gzip_mtime": 0, "compression_level": 9},
    }
    support = {
        "selection.json": json_bytes({"context": context, "groups": [group for selection in selections for group in selection["groups"]]}),
        "README.md": args.readme.read_bytes(),
        "assemble_ci_followup.py": Path(__file__).read_bytes(),
    }
    index["support_files"] = [{"path": name, "bytes": len(raw), "sha256": digest(raw)} for name, raw in sorted(support.items())]
    products.update(support)
    products["index.json"] = json_bytes(index)
    for name, raw in products.items():
        if len(raw) >= LIMIT:
            raise SystemExit(f"{name} has {len(raw)} bytes; split its input group before publishing")
    output.mkdir(parents=True)
    for name, raw in sorted(products.items()):
        (output / name).write_bytes(raw)
    print(json.dumps({"output": str(output), "files": len(products), "original_members": len(records),
                      "total_bytes": sum(map(len, products.values())), "largest_blob": max(map(len, products.values())),
                      "index_sha256": digest(products["index.json"])}, sort_keys=True))


if __name__ == "__main__":
    main()
