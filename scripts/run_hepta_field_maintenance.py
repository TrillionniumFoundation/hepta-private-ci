#!/usr/bin/env python3
"""Run isolated, source-bound maintenance generation; never publish its output."""

import argparse
import ctypes
import ctypes.util
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tomllib

from capture_cargo_deny_diagnostic import capture, checkpoint, identity

BRANCH = "refs/heads/research/parameter-field-maintenance-20261028"
MIB = 1024 * 1024
FILE_CAP, RAW_CAP, ARCHIVE_CAP, FILE_COUNT = 16 * MIB, 64 * MIB, 32 * MIB, 4096
LOCKS = ("codex-rs/Cargo.lock", "MODULE.bazel.lock")
TLS = {
    "rustls": ("0.23.45", "0.23.46"),
    "rustls-webpki": ("0.103.15", "0.103.16"),
    "webpki-root-certs": ("1.0.5", "1.0.10"),
    "webpki-roots": ("1.0.9", "1.0.10"),
}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def safe_name(name):
    path = PurePosixPath(name)
    if not name or "\\" in name or ":" in name or "\0" in name or path.is_absolute():
        raise ValueError(f"unsafe output path: {name!r}")
    if (
        not path.parts
        or path.as_posix() != name
        or any(part in (".", "..") for part in path.parts)
    ):
        raise ValueError(f"noncanonical output path: {name!r}")
    return path


def inventory(root):
    if root.is_symlink() or not root.is_dir():
        raise ValueError("inventory root must be a real directory")
    result, total = {}, 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ValueError(f"nonregular output: {path}")
        if path.is_dir():
            continue
        name = path.relative_to(root).as_posix()
        safe_name(name)
        size = path.stat().st_size
        total += size
        if size > FILE_CAP or total > RAW_CAP or len(result) >= FILE_COUNT:
            raise ValueError("output inventory exceeds its byte/file bound")
        result[name] = identity(path)
    return result


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def expand_bundle(bundle, destination):
    if bundle.is_symlink() or not bundle.is_file() or bundle.stat().st_size > FILE_CAP:
        raise ValueError("bundle must be a bounded regular file")
    library = ctypes.util.find_library("zstd")
    if not library:
        raise ValueError("system libzstd is unavailable; no substitute exports created")
    zstd = ctypes.CDLL(library)
    zstd.ZSTD_decompress.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    zstd.ZSTD_decompress.restype = ctypes.c_size_t
    zstd.ZSTD_isError.argtypes = [ctypes.c_size_t]
    zstd.ZSTD_isError.restype = ctypes.c_uint
    with bundle.open("rb") as source:
        compressed = source.read(FILE_CAP + 1)
    if len(compressed) > FILE_CAP:
        raise ValueError("generated bundle grew beyond its byte bound")
    target = ctypes.create_string_buffer(FILE_CAP)
    size = zstd.ZSTD_decompress(target, FILE_CAP, compressed, len(compressed))
    if zstd.ZSTD_isError(size) or size > FILE_CAP:
        raise ValueError("invalid or oversized generated zstd bundle")
    raw = target.raw[:size]
    exports = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs)
    if set(exports) != {"typescript", "json_schema", "internal_json_schema"}:
        raise ValueError("unexpected generated export groups")
    if exports["internal_json_schema"] != {}:
        raise ValueError("experimental internal exports must remain empty")
    pending, total = {}, 0
    for group in ("typescript", "json_schema"):
        if type(exports[group]) is not dict:
            raise ValueError("export group must be a filename/content map")
        for name, value in exports[group].items():
            safe_name(name)
            if not name.endswith(".ts" if group == "typescript" else ".json"):
                raise ValueError("unexpected export extension")
            if type(value) is not str:
                raise ValueError("export content must be a UTF-8 string")
            data = value.encode("utf-8")
            total += len(data)
            if len(data) > FILE_CAP or total > RAW_CAP or len(pending) >= FILE_COUNT:
                raise ValueError("expanded exports exceed their byte/file bound")
            pending[f"{group}/{name}"] = data
    if any(
        str(parent) in pending
        for name in pending
        for parent in PurePosixPath(name).parents
    ):
        raise ValueError("export file/directory collision")
    if not exports["typescript"] or not exports["json_schema"]:
        raise ValueError("experimental generated groups must be nonempty")
    destination.mkdir(exist_ok=False)
    for name, data in pending.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as out:
            out.write(data)
    return {
        "bundle": identity(bundle),
        "decoded_bytes": size,
        "decoded_sha256": hashlib.sha256(raw).hexdigest(),
        "files": inventory(destination),
    }


def validate_tls(before, after):
    def packages(document):
        result = {}
        for package in document["package"]:
            key = (package["name"], package["version"], package.get("source"))
            if key in result:
                raise ValueError("duplicate Cargo package identity")
            result[key] = dict(package)
        return result

    old, new = packages(before), packages(after)
    registry = "registry+https://github.com/rust-lang/crates.io-index"
    for entries, index in ((old, 0), (new, 1)):
        expected = {(name, versions[index], registry) for name, versions in TLS.items()}
        if {key for key in entries if key[0] in TLS} != expected:
            raise ValueError("unexpected exact TLS package identity")
    remap = {f"{name} {old}": f"{name} {new}" for name, (old, new) in TLS.items()}
    for value in old.values():
        if value["name"] not in TLS and "dependencies" in value:
            value["dependencies"] = [
                remap.get(dep, dep) for dep in value["dependencies"]
            ]
    unchanged = {key: value for key, value in old.items() if key[0] not in TLS}
    if unchanged != {key: value for key, value in new.items() if key[0] not in TLS}:
        raise ValueError("resolver changed packages outside the four TLS identities")
    if {**before, "package": []} != {**after, "package": []}:
        raise ValueError("unexpected Cargo lock metadata change")


def command(rec, out, root, label, argv, timeout=120, limit=MIB):
    checkpoint(out / "delivery", rec, label)
    result = capture(argv, root, out / "payload", label, timeout=timeout, limit=limit)
    rec["commands"].append({"label": label, **result})
    checkpoint(out / "delivery", rec, label + "_finished")
    if result["exit_code"] != 0 or result["timed_out"]:
        raise RuntimeError(
            f"{label} failed: exit={result['exit_code']} timeout={result['timed_out']}"
        )
    if result["streams"]["stdout"]["truncated"]:
        return None
    data = (out / "payload" / f"{label}.stdout.log").read_bytes() + (
        out / "payload" / f"{label}.stdout.tail.log"
    ).read_bytes()
    return data.decode("utf-8", errors="replace")


def git(rec, out, root, label, *args):
    return command(rec, out, root, label, ["git", *args], limit=65536)


def copy_locks(root, target):
    target.mkdir(exist_ok=True)
    for name in LOCKS:
        source = root / name
        if (
            source.is_symlink()
            or not source.is_file()
            or source.stat().st_size > FILE_CAP
        ):
            raise ValueError("lock output must be a bounded regular file")
        shutil.copyfile(source, target / source.name)


def initialize(root, out, mode):
    if (
        os.environ.get("GITHUB_EVENT_NAME") != "push"
        or os.environ.get("GITHUB_REF") != BRANCH
    ):
        raise ValueError("this generator runs only for the dedicated maintenance push")
    runner_temp = Path(os.environ["RUNNER_TEMP"]).resolve()
    if runner_temp not in out.parents or root in out.parents:
        raise ValueError("output must be a fresh external runner-temp subdirectory")
    out.mkdir(exist_ok=False)
    (out / "payload").mkdir()
    (out / "delivery").mkdir()
    rec = {
        "schema_version": 1,
        "mode": mode,
        "source_head": os.environ["GITHUB_SHA"],
        "ref": BRANCH,
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "commands": [],
        "generation_passed": False,
        "qualification": False,
        "resource_environment": {
            name: os.environ.get(name)
            for name in (
                "CARGO_INCREMENTAL",
                "CARGO_BUILD_JOBS",
                "CARGO_PROFILE_DEV_DEBUG",
                "CARGO_PROFILE_TEST_DEBUG",
            )
        },
        "bounds": {
            "file_bytes": FILE_CAP,
            "payload_and_tar_bytes": RAW_CAP,
            "archive_bytes": ARCHIVE_CAP,
            "compressed_plus_uncompressed_bytes": RAW_CAP + ARCHIVE_CAP,
            "file_count": FILE_COUNT,
            "log_bytes_per_stream": MIB,
        },
    }
    checkpoint(out / "delivery", rec, "initialized")
    actual = git(rec, out, root, "identity", "rev-parse", "HEAD", "HEAD^{tree}")
    if actual is None or actual.splitlines()[0] != rec["source_head"]:
        raise ValueError("checkout does not match github.sha")
    rec["source_tree"] = actual.splitlines()[1]
    status = git(rec, out, root, "before_status", "status", "--porcelain", "-uall")
    rec["worktree_clean_before"] = status == ""
    if not rec["worktree_clean_before"]:
        raise ValueError("maintenance input checkout is not clean")
    sources = (
        *LOCKS,
        "justfile",
        "scripts/run_hepta_field_maintenance.py",
        "scripts/capture_cargo_deny_diagnostic.py",
        ".github/workflows/hepta-field-maintenance.yml",
    )
    rec["source_inputs"] = {name: identity(root / name) for name in sources}
    if mode == "locks":
        copy_locks(root, out / "payload/before")
    else:
        write_json(
            out / "payload" / "schema-before.json",
            inventory(root / "codex-rs/app-server-protocol/schema"),
        )
    checkpoint(out / "delivery", rec, "ready")


def execute(root, out, rec):
    def run(label, argv, cwd=root):
        return command(rec, out, cwd, label, argv, timeout=30 * 60)

    for tool in ("rustc", "cargo", "just"):
        run(tool + "_version", [tool, "--version"])
    if rec["mode"] == "locks":
        run("bazel_version", ["bazel", "--version"])
        before = tomllib.loads((out / "payload/before/Cargo.lock").read_text())
        for name, (old, new) in TLS.items():
            current = tomllib.loads((root / LOCKS[0]).read_text())["package"]
            versions = [p["version"] for p in current if p["name"] == name]
            if len(versions) != 1 or versions[0] not in (old, new):
                raise ValueError("intermediate TLS package identity is unexpected")
            run(
                "update_" + name,
                ["cargo", "update", "-p", f"{name}@{versions[0]}", "--precise", new],
                root / "codex-rs",
            )
        validate_tls(before, tomllib.loads((root / LOCKS[0]).read_text()))
        rec["tls_update_scope_verified"] = True
        run("bazel_lock_update", ["just", "bazel-lock-update"])
        run("bazel_lock_check", ["just", "bazel-lock-check"])
    else:
        generated = out / "generated"
        for label, options in (
            ("schema_stable", []),
            ("schema_experimental", ["--experimental"]),
        ):
            stdout = run(
                label,
                [
                    "just",
                    "write-app-server-schema",
                    "--schema-root",
                    str(generated),
                    *options,
                ],
            )
            if (
                stdout is None
                or "test schema_fixtures_tests::write_schema_fixtures_from_env ... ok"
                not in stdout
                or "1 passed; 0 failed; 0 ignored;" not in stdout
            ):
                raise ValueError("canonical writer test execution was not observed")
        if not inventory(generated / "typescript") or not inventory(generated / "json"):
            raise ValueError("stable schema generator outputs are missing")
        rec["experimental_expansion"] = expand_bundle(
            generated / "precomputed/app-server-exports-experimental.json.zst",
            out / "expanded-experimental",
        )
    rec["generation_passed"] = True


class BoundedTar(io.BytesIO):
    def write(self, data):
        if self.tell() + len(data) > RAW_CAP:
            raise ValueError("uncompressed tar exceeds its byte bound")
        return super().write(data)


def package(out, rec, roots):
    entries = {}
    for prefix, directory in roots.items():
        for name, meta in inventory(directory).items():
            name = str(safe_name(prefix + "/" + name))
            entries[name] = (directory / name.removeprefix(prefix + "/"), meta)
    if len(entries) >= FILE_COUNT:
        raise ValueError("combined delivery file count exceeds bound")
    manifest = {
        "source_head": rec["source_head"],
        "files": {name: value[1] for name, value in entries.items()},
    }
    manifest_path = out / "delivery/MANIFEST.json"
    write_json(manifest_path, manifest)
    entries["MANIFEST.json"] = (manifest_path, identity(manifest_path))
    stream = BoundedTar()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, (path, meta) in sorted(entries.items()):
            with path.open("rb") as source:
                data = source.read(FILE_CAP + 1)
            if {
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            } != meta:
                raise ValueError("file changed after inventory")
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), 0o644, 0
            archive.addfile(info, io.BytesIO(data))
    compressed = gzip.compress(stream.getvalue(), mtime=0)
    if len(compressed) > ARCHIVE_CAP:
        raise ValueError("compressed archive exceeds its byte bound")
    destination = out / "delivery/maintenance.tar.gz"
    destination.write_bytes(compressed)
    rec["archive"] = {
        **identity(destination),
        "uncompressed_tar_bytes": stream.tell(),
        "member_count": len(entries),
        "input_bytes_verified": True,
    }
    rec["manifest"] = identity(manifest_path)


def finalize(root, out, rec, outcome):
    rec["workflow_generation_step_outcome"] = outcome
    roots = {"evidence": out / "payload"}
    try:
        actual = git(
            rec, out, root, "final_identity", "rev-parse", "HEAD", "HEAD^{tree}"
        )
        values = actual.splitlines() if actual is not None else []
        rec["source_identity_after"] = values
        rec["source_identity_unchanged"] = values == [
            rec["source_head"],
            rec.get("source_tree"),
        ]
        status = git(rec, out, root, "after_status", "status", "--porcelain", "-uall")
        rec["worktree_clean_after"] = status == ""
        changed = None if status is None else {line[3:] for line in status.splitlines()}
        allowed = set(LOCKS) if rec["mode"] == "locks" else set()
        rec["changed_paths"] = None if changed is None else sorted(changed)
        if rec["mode"] == "locks":
            after = out / "payload/after"
            copy_locks(root, after)
            rec["lock_outputs"] = inventory(after)
            if rec["generation_passed"]:
                validate_tls(
                    tomllib.loads((out / "payload/before/Cargo.lock").read_text()),
                    tomllib.loads((after / "Cargo.lock").read_text()),
                )
        else:
            for name in ("generated", "expanded-experimental"):
                directory = out / name
                if directory.exists():
                    rec[name] = inventory(directory)
                    roots[name] = directory
        if changed is None or not changed <= allowed:
            raise ValueError("unexpected worktree changes outside generated lock scope")
        if not rec["source_identity_unchanged"]:
            raise ValueError("final source commit/tree differs from initialization")
        if outcome != "success" or not rec["generation_passed"]:
            raise ValueError("generation did not complete successfully")
    except Exception as error:
        rec["finalize_error"] = f"{type(error).__name__}: {error}"
        rec["generation_passed"] = False
    write_json(out / "payload/PROVENANCE.json", rec)
    try:
        package(out, rec, roots)
    except Exception as error:
        rec["artifact_collection_error"] = f"{type(error).__name__}: {error}"
        rec["generated_outputs_omitted_from_fallback"] = sorted(
            set(roots) - {"evidence"}
        )
        rec["generation_passed"] = False
        write_json(out / "payload/PROVENANCE.json", rec)
        package(out, rec, {"evidence": out / "payload"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("locks", "schemas"), required=True)
    parser.add_argument(
        "--phase", choices=("initialize", "run", "finalize"), required=True
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--step-outcome", default="unknown")
    args = parser.parse_args()
    root, out = Path(__file__).resolve().parents[1], args.output_dir.resolve()
    if args.phase == "initialize":
        initialize(root, out, args.mode)
        return 0
    rec = json.loads((out / "delivery/receipt.json").read_text())
    if rec["mode"] != args.mode or rec["source_head"] != os.environ.get("GITHUB_SHA"):
        raise ValueError("maintenance phase identity mismatch")
    try:
        if args.phase == "run":
            execute(root, out, rec)
        else:
            finalize(root, out, rec, args.step_outcome)
        checkpoint(out / "delivery", rec, args.phase + "_finished", "completed")
    except Exception as error:
        rec["error"] = f"{type(error).__name__}: {error}"
        rec["generation_passed"] = False
        checkpoint(out / "delivery", rec, args.phase + "_failed", "capture_error")
    return 0 if rec["generation_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
