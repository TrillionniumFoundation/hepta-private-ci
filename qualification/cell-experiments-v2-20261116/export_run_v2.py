"""Create a complete, create-only archive after the v2 supervisor is terminal."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import zipfile
import zlib

PAYLOAD_BYTES = 491520
BINARY_LIMIT = 512000
EXPECTED_SOURCE = "fdcd9466664b6847bab4d4f547c5e8452a0eb5fe831452c9b4aa4607408aeae1"
BASE_BYTES = 269060552
BASE_SHA256 = "5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c"
EXTERNAL_PATH = "run/base/model.safetensors"
FIXTURE_PATH = "qualification/cell-experiments-v2-20261116/task-fixtures"


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def identity(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("symlink is not an immutable original: " + str(path))
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("regular file required: " + str(path))
        sha256, git = (
            hashlib.sha256(),
            hashlib.sha1(b"blob " + str(before.st_size).encode() + b"\0"),
        )
        size = 0
        for block in iter(lambda: stream.read(1048576), b""):
            sha256.update(block)
            git.update(block)
            size += len(block)
        after = os.fstat(stream.fileno())
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if size != before.st_size or any(
        getattr(before, k) != getattr(after, k) for k in fields
    ):
        raise ValueError("original changed while reading: " + str(path))
    return {"bytes": size, "sha256": sha256.hexdigest(), "git_blob": git.hexdigest()}


def write_new(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def files_under(root, *, omit_bytecode=False):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("ordinary source directory required")
    found = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in list(dirs):
            path = Path(directory) / name
            if path.is_symlink():
                raise ValueError("symlink directory in original tree: " + str(path))
            if omit_bytecode and name == "__pycache__":
                dirs.remove(name)
        for name in files:
            path = Path(directory) / name
            if path.is_symlink() or not path.is_file():
                raise ValueError("nonregular original: " + str(path))
            if omit_bytecode and path.suffix in (".pyc", ".pyo"):
                continue
            found.append(path)
    return sorted(found)


def zip_info(name, compression=zipfile.ZIP_DEFLATED):
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = compression
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def split_stream(path, destination):
    """Each publishable part is a valid small ZIP containing one raw payload."""
    path, destination = Path(path), Path(destination)
    parts = []
    with path.open("rb") as stream:
        while block := stream.read(PAYLOAD_BYTES):
            number = len(parts)
            name = path.stem + f".part-{number:03d}.zip"
            output = destination / name
            with zipfile.ZipFile(
                output, "x", compression=zipfile.ZIP_STORED
            ) as archive:
                archive.writestr(zip_info("payload.bin", zipfile.ZIP_STORED), block)
            item = identity(output)
            if item["bytes"] >= BINARY_LIMIT:
                raise ValueError("Git binary exceeds strict publication limit")
            with zipfile.ZipFile(output) as archive:
                if (
                    archive.namelist() != ["payload.bin"]
                    or archive.read("payload.bin") != block
                ):
                    raise ValueError("part roundtrip differs")
            parts.append(
                {
                    "index": number,
                    "file": name,
                    **item,
                    "payload_bytes": len(block),
                    "payload_sha256": hashlib.sha256(block).hexdigest(),
                }
            )
    return {"file": path.name, **identity(path), "parts": parts}


def collect(run_root, logs_root, source_root, expected_source):
    terminal = json.loads((logs_root / "RESULT.json").read_bytes())
    if terminal.get("status") not in ("COMPLETE_DEVELOPMENT", "INCOMPLETE"):
        raise ValueError(
            "supervisor terminal RESULT.json required; do not export a live run"
        )
    if terminal.get("source_digest") != expected_source:
        raise ValueError("terminal supervisor source binding differs")
    frozen = json.loads((run_root / "FREEZE.json").read_bytes())
    for name, expected in frozen["input_files"].items():
        relative = Path(name)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or identity(run_root / relative)["sha256"] != expected
        ):
            raise ValueError("frozen original input changed")
    package = source_root / "scripts/cell_experiments"
    observed = {p.name: identity(p)["sha256"] for p in sorted(package.glob("*.py"))}
    if (
        len(observed) != 44
        or observed != frozen["source_inventory"]
        or hashlib.sha256(canonical(observed)).hexdigest() != expected_source
    ):
        raise ValueError(
            "the 44 executed Python source files differ from the frozen run"
        )
    fixture_root = source_root / FIXTURE_PATH
    fixture_files = files_under(fixture_root)
    fixture_map = {
        str(p.relative_to(fixture_root)): identity(p)["sha256"] for p in fixture_files
    }
    if fixture_map != frozen["fixture_inventory"]:
        raise ValueError("reviewed task fixture originals changed")
    mapping = {}
    for prefix, root in (("run", run_root), ("execution-logs", logs_root)):
        for path in files_under(root):
            mapping[prefix + "/" + path.relative_to(root).as_posix()] = path
    # Keep every supplied runtime source dependency, including Hepta modules,
    # and the exact reviewed fixture corpus. Python caches are transient copies.
    for path in (
        files_under(source_root / "scripts", omit_bytecode=True) + fixture_files
    ):
        mapping["source/" + path.relative_to(source_root).as_posix()] = path
    for name in ("AGENTS.md", "justfile"):
        if (source_root / name).is_file():
            mapping["source/" + name] = source_root / name
    entries = []
    for name, path in sorted(mapping.items()):
        item = {"path": name, **identity(path)}
        item["archive"] = (
            "external_base"
            if name == EXTERNAL_PATH
            else "base-metadata.zip"
            if name.startswith("run/base/")
            else "checkpoints.zip"
            if name.startswith("run/models/")
            and (path.suffix == ".safetensors" or path.name == "optimizer.pt")
            else "receipts.zip"
        )
        entries.append(item)
    external = [item for item in entries if item["archive"] == "external_base"]
    if (
        len(external) != 1
        or external[0]["bytes"] != BASE_BYTES
        or external[0]["sha256"] != BASE_SHA256
    ):
        raise ValueError("the only omitted file must be the exact pinned public base")
    return mapping, entries, terminal, frozen


def archive_stream(name, entries, mapping, destination):
    selected = [item for item in entries if item["archive"] == name]
    path = destination / name
    with zipfile.ZipFile(
        path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        for item in selected:
            original = mapping[item["path"]]
            if identity(original) != {
                key: item[key] for key in ("bytes", "sha256", "git_blob")
            }:
                raise ValueError("original changed before archiving")
            with (
                original.open("rb") as source,
                archive.open(zip_info(item["path"]), "w") as target,
            ):
                for block in iter(lambda: source.read(1048576), b""):
                    target.write(block)
    with zipfile.ZipFile(path) as archive:
        if archive.namelist() != [item["path"] for item in selected]:
            raise ValueError("archive inventory differs")
        for item in selected:
            digest, git = (
                hashlib.sha256(),
                hashlib.sha1(b"blob " + str(item["bytes"]).encode() + b"\0"),
            )
            size = 0
            with archive.open(item["path"]) as stream:
                for block in iter(lambda: stream.read(1048576), b""):
                    size += len(block)
                    digest.update(block)
                    git.update(block)
            if (size, digest.hexdigest(), git.hexdigest()) != (
                item["bytes"],
                item["sha256"],
                item["git_blob"],
            ):
                raise ValueError("archive member differs from original")
    stream = split_stream(path, destination)
    stream["member_count"] = len(selected)
    stream["members"] = [item["path"] for item in selected]
    return stream


def export(options):
    run, logs, source, output = [
        Path(value).absolute()
        for value in (
            options.run_root,
            options.logs_root,
            options.source_root,
            options.output,
        )
    ]
    if any(
        output == parent or output.is_relative_to(parent)
        for parent in (run, logs, source)
    ):
        raise ValueError("export must be outside all original trees")
    if not re.fullmatch(r"[0-9a-f]{64}", options.expected_source_digest) or (
        options.source_commit is not None
        and not re.fullmatch(r"[0-9a-f]{40}", options.source_commit)
    ):
        raise ValueError("full source SHA256 and optional Git commit required")
    output.mkdir(parents=True, exist_ok=False)
    started, cpu, wall = time.time_ns(), time.process_time(), time.perf_counter()
    write_new(
        output / "STARTED.json",
        {
            "started_at_ns": started,
            "run_root": str(run),
            "logs_root": str(logs),
            "source_root": str(source),
            "expected_source_digest": options.expected_source_digest,
            "operator_must_observe_supervisor_terminal_before_invocation": True,
        },
    )
    try:
        mapping, entries, terminal, frozen = collect(
            run, logs, source, options.expected_source_digest
        )
        inventory = {
            "schema": "hepta.repository-study.inventory.v2",
            "inventory": entries,
            "file_count": len(entries),
            "roots": {
                "run": str(run),
                "execution-logs": str(logs),
                "source": str(source),
            },
            "source_package_files": 44,
            "source_digest": options.expected_source_digest,
            "source_snapshot_included": True,
            "fixture_snapshot_included": True,
            "transient_source_bytecode_excluded": True,
            "terminal_supervisor_status": terminal["status"],
        }
        write_new(output / "INVENTORY.json", inventory)
        streams = {
            name: archive_stream(name, entries, mapping, output)
            for name in ("receipts.zip", "base-metadata.zip", "checkpoints.zip")
        }
        # Re-scan names and bytes after archiving; a live or changing run fails.
        second_mapping, second_entries, second_terminal, second_frozen = collect(
            run, logs, source, options.expected_source_digest
        )
        if (
            set(second_mapping) != set(mapping)
            or second_entries != entries
            or second_terminal != terminal
            or second_frozen != frozen
        ):
            raise ValueError("original tree changed during export")
        tools = {}
        for path in (Path(__file__), Path(options.restore_script)):
            if not path.is_file():
                raise ValueError("both export and restore tools must be retained")
            tools[path.name] = identity(path)
        manifest = {
            "schema": "hepta.repository-study.export.v2",
            "status": "COMPLETE",
            "started_at_ns": started,
            "completed_at_ns": time.time_ns(),
            "inventory": {
                "file": "INVENTORY.json",
                **identity(output / "INVENTORY.json"),
            },
            "archives": streams,
            "payload_chunk_bytes": PAYLOAD_BYTES,
            "part_format": "ZIP_STORED with exactly one member payload.bin; concatenate extracted payloads, never ZIP containers",
            "strict_git_binary_limit_bytes": BINARY_LIMIT,
            "every_part_below_limit": True,
            "source_digest": options.expected_source_digest,
            "source_git_commit": options.source_commit,
            "source_snapshot_complete_for_supplied_scripts_and_fixtures": True,
            "tools": tools,
            "zlib_version": zlib.ZLIB_VERSION,
            "external_base": {
                "path": EXTERNAL_PATH,
                "bytes": BASE_BYTES,
                "sha256": BASE_SHA256,
                "repository": "HuggingFaceTB/SmolLM2-135M-Instruct",
                "revision": "12fd25f77366fa6b3b4b768ec3050bf629380bac",
                "file": "model.safetensors",
                "git_blob": next(
                    item["git_blob"]
                    for item in entries
                    if item["path"] == EXTERNAL_PATH
                ),
            },
            "publish_files": ["INVENTORY.json", "EXPORT.json"]
            + [part["file"] for stream in streams.values() for part in stream["parts"]],
            "do_not_publish_whole_streams_over_binary_limit": True,
            "original_absolute_paths_preserved": True,
            "training_or_inference_performed": False,
            "optimizer_resume_verified": False,
            "portable_owner_recovery_verified": False,
            "wall_seconds": time.perf_counter() - wall,
            "cpu_seconds": time.process_time() - cpu,
        }
        write_new(output / "EXPORT.json", manifest)
        return {
            "status": "COMPLETE",
            "output": str(output),
            "files": len(entries),
            "archive_parts": sum(len(s["parts"]) for s in streams.values()),
            "export_sha256": identity(output / "EXPORT.json")["sha256"],
            "source_digest": options.expected_source_digest,
        }
    except Exception as failure:
        write_new(
            output / "FAILED.json",
            {
                "error": type(failure).__name__ + ": " + str(failure),
                "completed_at_ns": time.time_ns(),
                "partial_artifacts_retained": True,
            },
        )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("run-root", "logs-root", "source-root", "output", "restore-script"):
        parser.add_argument("--" + field, required=True)
    parser.add_argument("--expected-source-digest", default=EXPECTED_SOURCE)
    parser.add_argument("--source-commit")
    print(json.dumps(export(parser.parse_args()), sort_keys=True))
