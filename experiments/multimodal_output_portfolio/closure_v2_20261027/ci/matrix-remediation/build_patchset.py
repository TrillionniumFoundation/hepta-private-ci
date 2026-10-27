#!/usr/bin/env python3
"""Freeze independent Matrix candidate patches and their exact source provenance."""

import argparse
import difflib
import gzip
import hashlib
import io
import json
import pathlib
import subprocess
import tarfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def stable_archive(path, members):
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w") as archive:
                for name, source in sorted(members):
                    body = source.read_bytes()
                    info = tarfile.TarInfo(name)
                    info.size = len(body)
                    info.mode = source.stat().st_mode & 0o777
                    archive.addfile(info, io.BytesIO(body))
    with tarfile.open(path, "r:gz") as archive:
        actual = {
            member.name: digest(archive.extractfile(member).read())
            for member in archive.getmembers()
        }
    assert actual == {name: digest(source.read_bytes()) for name, source in members}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=pathlib.Path, required=True)
    parser.add_argument("--work-root", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    candidate = args.work_root / "candidate"
    upstream = args.work_root / "upstream"
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    groups = {
        "matrix-fixture-tests.patch": [
            "codex-rs/hepta-matrix-sdk/tests/store_version_migration.rs",
        ],
        "matrix-context-tests.patch": [
            "codex-rs/hepta-matrix-sdk/Cargo.toml",
            "codex-rs/hepta-matrix-sdk/tests/event_context_migration.rs",
        ],
        "matrix-production.patch": [
            "codex-rs/hepta-matrix-sdk/src/config.rs",
            "codex-rs/hepta-matrix-sdk/src/sdk.rs",
        ],
        "matrix-manifest.patch": ["codex-rs/Cargo.toml"],
        "matrix-toolchain.patch": ["MODULE.bazel", "codex-rs/rust-toolchain.toml"],
        "matrix-toolchain-ci.patch": [
            str(path.relative_to(candidate))
            for path in sorted((candidate / ".github/workflows").glob("*.yml"))
        ] + ["scripts/test_hepta_ci_v8.py", "codex-rs/scripts/setup-windows.ps1"],
    }
    files = []
    for patch_name, paths in groups.items():
        patch = []
        for name in paths:
            before = subprocess.run(
                ["git", "show", f"HEAD:{name}"],
                cwd=args.source_root,
                capture_output=True,
            )
            if before.returncode and (args.source_root / name).exists():
                raise RuntimeError(f"refuse to treat untracked existing source as absent: {name}")
            old = before.stdout if before.returncode == 0 else b""
            new = (candidate / name).read_bytes()
            if old == new:
                raise RuntimeError(f"candidate path has no change: {name}")
            patch.append(f"diff --git a/{name} b/{name}\n")
            if before.returncode:
                patch.append("new file mode 100644\n")
            patch.extend(
                difflib.unified_diff(
                    old.decode().splitlines(keepends=True),
                    new.decode().splitlines(keepends=True),
                    fromfile=f"a/{name}" if old else "/dev/null",
                    tofile=f"b/{name}",
                )
            )
            files.append(
                {
                    "patch": patch_name,
                    "path": name,
                    "before_sha256": digest(old) if old else None,
                    "after_sha256": digest(new),
                }
            )
        (output / patch_name).write_text("".join(patch))

    vendor_members = []
    inventory = []
    for name in ("matrix-sdk-0.19.1", "matrix-sdk-sqlite-0.19.1"):
        folder = candidate / "codex-rs/third_party" / name
        official = upstream / name
        original_paths = {
            path.relative_to(official) for path in official.rglob("*") if path.is_file()
        }
        candidate_paths = {
            path.relative_to(folder) for path in folder.rglob("*") if path.is_file()
        }
        assert original_paths <= candidate_paths, "the full upstream package must be retained"
        for relative in sorted(candidate_paths):
            source = folder / relative
            original = official / relative
            path = str(source.relative_to(candidate))
            current_hash = digest(source.read_bytes())
            original_hash = digest(original.read_bytes()) if original.is_file() else None
            inventory.append(
                {
                    "path": path,
                    "bytes": source.stat().st_size,
                    "sha256": current_hash,
                    "upstream_sha256": original_hash,
                    "status": (
                        "unchanged" if current_hash == original_hash else
                        "modified" if original_hash else "added"
                    ),
                }
            )
            vendor_members.append((path, source))
    stable_archive(output / "matrix-vendor.tar.gz", vendor_members)
    (output / "VENDOR_INVENTORY.json").write_text(json.dumps(inventory, indent=2) + "\n")
    evidence = [
        (f"upstream/{path.name}", path)
        for path in upstream.iterdir()
        if path.is_file()
    ]
    evidence.append(("UPSTREAM_SOURCES.json", args.work_root / "UPSTREAM_SOURCES.json"))
    stable_archive(output / "upstream-evidence.tar.gz", evidence)
    manifest = {
        "schema": "hepta.matrix_dependency_candidate.v1",
        "status": "prepared; Rust compilation and migration qualification have not run",
        "base_local_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=args.source_root, text=True
        ).strip(),
        "base_tree": subprocess.check_output(
            ["git", "rev-parse", "HEAD^{tree}"], cwd=args.source_root, text=True
        ).strip(),
        "generator_sha256": digest(pathlib.Path(__file__).read_bytes()),
        "patch_files": files,
        "artifacts": [
            {"path": name, "bytes": (output / name).stat().st_size,
             "sha256": digest((output / name).read_bytes())}
            for name in sorted(list(groups) + [
                "matrix-vendor.tar.gz", "upstream-evidence.tar.gz", "VENDOR_INVENTORY.json"
            ])
        ],
        "vendor_changed": [
            row for row in inventory if row["status"] != "unchanged"
        ],
        "validation": {
            "archive_roundtrip_all_member_hashes": True,
            "upstream_source_files_omitted": 0,
            "rust_compilation": "not run",
            "old_to_new_store_migration": "not run",
            "cargo_and_bazel_lock_generation": "not run",
            "cargo_deny": "not run",
        },
    }
    (output / "PATCHSET.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({
        "artifacts": manifest["artifacts"],
        "vendor_files": len(inventory),
        "vendor_modified": [row["path"] for row in inventory if row["status"] == "modified"],
        "vendor_added": [row["path"] for row in inventory if row["status"] == "added"],
    }, indent=2))


if __name__ == "__main__":
    main()
