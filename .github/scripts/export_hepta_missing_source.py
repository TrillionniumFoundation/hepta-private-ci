#!/usr/bin/env python3
"""Fetch only fixed missing blob IDs and retain bounded, independently readable packs."""

import argparse
import base64
import contextlib
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import signal
import subprocess
import sys
import time

REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
TEMPORARY_REF = "refs/heads/integration/hepta-rust-validation-20261117-59d82"
EXPORTER_SHA256 = "b5c9532fa83ad72d53271eedc309f1c1128fe60a21b5992a3df31312431c97ae"
GRAPH_RESULT_SHA256 = "71ac277821b8c512569ac4c13a1468fe671202301f0724d903c610adcf326083"
OID = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
FETCH_BATCH = 512
PACK_RAW_BYTES = 64 * 1024 * 1024
MAX_SINGLE_BLOB_BYTES = 384 * 1024 * 1024
MAX_OUTPUT_BYTES = 1536 * 1024 * 1024
VOLUME_BYTES = 480 * 1024 * 1024
MAX_VOLUMES = 8
WORK_SECONDS = 1380


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def rows_gz(path, rows):
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as stream:
            for row in rows:
                stream.write(
                    (
                        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                    ).encode()
                )


def regular_files(root):
    found = []
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(), "Artifact contains a symbolic link")
        require(path.is_file() or path.is_dir(), "Artifact contains a special file")
        if path.is_file():
            found.append(path)
    return found


def total_bytes(root):
    return sum(path.stat().st_size for path in regular_files(root))


def request(path, expected_sha256, part):
    require(SHA256.fullmatch(expected_sha256), "Request digest syntax")
    require(sha256_file(path) == expected_sha256, "Request compressed digest")
    require(path.stat().st_size < 512000, "Repository input blob-size bound")
    with gzip.open(path, "rb") as stream:
        raw = stream.read(4 * 1024 * 1024 + 1)
    require(len(raw) <= 4 * 1024 * 1024, "Request decoded bound")
    value = json.loads(raw)
    require(value["schema"] == "hepta.missing-source-request.v1", "Request schema")
    require(value["repository"] == REPOSITORY, "Request repository")
    require(value["parts"] == 16 and value["part"] == part, "Request allocation")
    require(
        value["graph_result_sha256"] == GRAPH_RESULT_SHA256, "Verified graph identity"
    )
    selected = value["rows"]
    require(len(selected) == (5518 if part < 6 else 5517), "Fixed part count")
    require(
        len({row["oid"] for row in selected}) == len(selected), "Repeated source object"
    )
    require(
        selected == sorted(selected, key=lambda row: (row["priority"], row["oid"])),
        "Source priority/order",
    )
    for row in selected:
        require(
            all(OID.fullmatch(row[key]) for key in ("oid", "tip", "tree")),
            "Source witness OID",
        )
        require(
            row["kind"] == "blob" and row["previously_available"] is False,
            "Missing blob witness",
        )
        require(row["priority"] in (0, 1, 2), "Source priority")
        require(row["mode"] in ("100644", "100755", "120000"), "Source blob mode")
        name = PurePosixPath(row["path"])
        require(
            not name.is_absolute()
            and name.parts
            and all(p not in (".", "..") for p in name.parts),
            "Source witness path",
        )
        require(
            "\x00" not in row["path"] and "\\" not in row["path"],
            "Source witness separator",
        )
    return value


def load_exporter(path):
    require(path.is_file() and not path.is_symlink(), "Exporter regular file")
    require(sha256_file(path) == EXPORTER_SHA256, "Reviewed exporter bytes")
    spec = importlib.util.spec_from_file_location("hepta_fixed_source_exporter", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_broker(args):
    require(
        sys.platform.startswith("linux"),
        "The bounded process group runner is Linux-only",
    )
    require(os.environ.get("GITHUB_REPOSITORY") == REPOSITORY, "Runtime repository")
    require(os.environ.get("GITHUB_EVENT_NAME") == "push", "Runtime event")
    require(os.environ.get("GITHUB_REF") == TEMPORARY_REF, "Runtime temporary branch")
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    require(event.get("deleted") is False, "Deletion pushes cannot fetch source")
    runtime_head = os.environ.get("GITHUB_SHA", "")
    require(OID.fullmatch(runtime_head), "Runtime head syntax")
    value = request(args.request, args.request_sha256, args.part)
    legacy = load_exporter(args.exporter)
    args.output.mkdir(exist_ok=False)
    args.repository.mkdir(exist_ok=False)
    token = os.environ.get("BROKER_GITHUB_TOKEN", "")
    require(bool(token), "Ephemeral read token required")
    started = time.monotonic()
    deadline = started + WORK_SECONDS

    class BoundedGit(legacy.Git):
        """Keep reviewed fetch argv/auth rules; add a bounded owned process group."""

        def run(self, argv, data=None, network=False, stdout_path=None, check=True):
            remaining = deadline - time.monotonic()
            require(remaining > 0, "Source-only work deadline reached")
            self.serial += 1
            name = f"{self.serial:05d}"
            environment = dict(self.environment)
            command = self.command(argv)
            if network:
                require(self.token, "Fixed-OID fetch needs ephemeral read token")
                header = (
                    "AUTHORIZATION: basic "
                    + base64.b64encode(
                        ("x-access-token:" + self.token).encode()
                    ).decode()
                )
                environment.update(
                    {
                        "GIT_CONFIG_COUNT": "2",
                        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
                        "GIT_CONFIG_VALUE_0": "",
                        "GIT_CONFIG_KEY_1": "http.https://github.com/.extraheader",
                        "GIT_CONFIG_VALUE_1": header,
                    }
                )
                command = self.command(
                    [
                        "-c",
                        "protocol.https.allow=always",
                        "-c",
                        "http.followRedirects=false",
                        *argv,
                    ]
                )
            began = time.monotonic()
            timed_out = False
            with (
                stdout_path.open("wb")
                if stdout_path
                else contextlib.nullcontext() as target
            ):
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=target or subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=environment,
                    start_new_session=True,
                )
                try:
                    stdout, stderr = process.communicate(
                        data, timeout=min(300, remaining)
                    )
                except subprocess.TimeoutExpired:
                    timed_out = True
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        stdout, stderr = process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        stdout, stderr = process.communicate()
            for secret in (
                self.token,
                base64.b64encode(("x-access-token:" + self.token).encode()).decode(),
            ):
                stderr = stderr.replace(secret.encode(), b"[redacted]")
                if stdout is not None:
                    stdout = (
                        stdout.replace(secret.encode(), b"[redacted]")
                        if network
                        else stdout
                    )
            (self.commands / (name + ".stderr")).write_bytes(stderr)
            write_json(
                self.commands / (name + ".json"),
                {
                    "argv": command,
                    "returncode": process.returncode,
                    "timed_out": timed_out,
                    "elapsed_seconds": time.monotonic() - began,
                    "stdin_sha256": hashlib.sha256(data).hexdigest()
                    if data is not None
                    else None,
                    "stdin_bytes": len(data) if data is not None else 0,
                    "explicit_same_repository_network": network,
                    "stdout_file": stdout_path.name if stdout_path else None,
                },
            )
            require(
                not timed_out,
                f"Git command {name} reached its original work allocation; no retry",
            )
            if check:
                require(
                    process.returncode == 0,
                    f"Git command {name} failed; retained stderr",
                )
            return subprocess.CompletedProcess(
                command, process.returncode, stdout, stderr
            )

    git = BoundedGit(args.repository, args.output, token)
    template = args.output / "empty-template"
    template.mkdir()
    git.run(["init", "--bare", "--object-format=sha1", "--template=" + str(template)])
    before = git.refs()
    require(not before, "Source-only store must start without refs")
    selected = value["rows"]
    statuses = {
        row["oid"]: dict(
            row, status="not_attempted", bytes=None, sha256=None, pack=None
        )
        for row in selected
    }
    attempts = []
    packs = []
    exported = set()
    values = {}
    pending = []
    pending_bytes = 0
    reader = legacy.Reader(git)
    failure = None
    network_failures = 0
    write_json(
        args.output / "invocation.json",
        {
            "schema": "hepta.missing-source-invocation.v1",
            "repository": REPOSITORY,
            "runtime_head": runtime_head,
            "runtime_run_id": os.environ.get("GITHUB_RUN_ID"),
            "runtime_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "part": args.part,
            "parts": 16,
            "request_sha256": args.request_sha256,
            "exporter_sha256": EXPORTER_SHA256,
            "driver_sha256": sha256_file(Path(__file__)),
            "python": sys.version,
            "platform": platform.platform(),
            "git": git.text("--version"),
            "fixed_blob_fetch_batch": FETCH_BATCH,
            "original_pack_raw_bound": PACK_RAW_BYTES,
            "original_pack_object_bound": 8192,
            "work_seconds": WORK_SECONDS,
            "job_timeout_minutes": 30,
            "retries": 0,
            "new_commit_tree_or_head_export": False,
            "source_payload_execution": False,
            "remote_ref_writes": False,
        },
    )

    def save_progress():
        rows_gz(
            args.output / "source-object-status.jsonl.gz",
            [statuses[row["oid"]] for row in selected],
        )
        rows_gz(args.output / "hydration-attempts.jsonl.gz", attempts)
        write_json(
            args.output / "verified-packs.json",
            {"packs": packs, "exported_objects": len(exported)},
        )

    def flush():
        nonlocal pending, pending_bytes
        if not pending:
            return
        require(
            total_bytes(args.output) + pending_bytes + pending_bytes // 50 + 1024 * 1024
            <= MAX_OUTPUT_BYTES,
            "Measured source output capacity reached",
        )
        before_pack_count = len(packs)
        legacy.pack_objects(
            git, args.output, pending, values, exported, packs, required=True
        )
        require(
            set(pending) <= exported, "Buffered fixed source blobs were not all packed"
        )
        require(
            len(packs) == before_pack_count + 1,
            "Bounded buffer must produce exactly one independent pack",
        )
        for pack in packs[before_pack_count:]:
            for oid in pending:
                statuses[oid]["status"] = "verified_and_exported"
                statuses[oid]["pack"] = pack["path"]
        pending, pending_bytes = [], 0
        save_progress()

    try:
        save_progress()
        for priority in range(3):
            layer = [row["oid"] for row in selected if row["priority"] == priority]
            for start in range(0, len(layer), FETCH_BATCH):
                require(
                    time.monotonic() < deadline, "Source-only work deadline reached"
                )
                require(
                    shutil.disk_usage(args.repository).free >= 4 * legacy.RESERVE_BYTES,
                    "Measured bare-store free space is below the original reserve",
                )
                require(
                    total_bytes(args.output) < MAX_OUTPUT_BYTES,
                    "Measured source output capacity reached",
                )
                batch = layer[start : start + FETCH_BATCH]
                before_batch = git.info(batch)
                require(
                    all(
                        item is None or item[0] == "blob"
                        for item in before_batch.values()
                    ),
                    "Existing requested object type",
                )
                missing_batch = [oid for oid in batch if before_batch[oid] is None]
                for oid in batch:
                    statuses[oid]["status"] = (
                        "fetch_requested"
                        if oid in missing_batch
                        else "present_from_previous_fetch"
                    )
                attempts.append(
                    {
                        "priority": priority,
                        "selected": batch,
                        "requested": missing_batch,
                        "obtained": [],
                        "completed": False,
                    }
                )
                save_progress()
                fetch_record = {"returncode": 0, "not_needed": not missing_batch}
                if missing_batch:
                    git.hydrate(missing_batch, kind="blob")
                    fetch_record = json.loads(
                        (git.commands / f"{git.serial:05d}.json").read_text()
                    )
                    if fetch_record["returncode"] != 0:
                        network_failures += 1
                after = git.info(batch)
                require(
                    all(item is None or item[0] == "blob" for item in after.values()),
                    "Fetched source type differs from blob",
                )
                values.update(after)
                for oid in batch:
                    info = after[oid]
                    if info is None:
                        statuses[oid]["status"] = "not_returned_by_single_fetch"
                        continue
                    length = info[1]
                    statuses[oid]["bytes"] = length
                    attempts[-1]["obtained"].append(oid)
                    if length > MAX_SINGLE_BLOB_BYTES:
                        statuses[oid]["status"] = "not_exported_single_blob_capacity"
                        continue
                    kind, actual_length, raw_sha256, unused_raw = reader.read(
                        oid, retain=False
                    )
                    require(
                        kind == "blob"
                        and actual_length == length
                        and unused_raw == b"",
                        "Streamed blob identity",
                    )
                    statuses[oid].update(
                        status="verified_pending_pack", sha256=raw_sha256
                    )
                    if pending and (
                        pending_bytes + length > PACK_RAW_BYTES or len(pending) >= 8192
                    ):
                        flush()
                    pending.append(oid)
                    pending_bytes += length
                    if pending_bytes >= PACK_RAW_BYTES:
                        flush()
                attempts[-1]["completed"] = True
                attempts[-1]["fetch_returncode"] = fetch_record["returncode"]
                save_progress()
            flush()
        require(
            not network_failures,
            "At least one original fetch returned failure; retained objects do not erase that failure",
        )
    except Exception as error:
        failure = {"type": type(error).__name__, "message": str(error)}
    finally:
        try:
            reader.close()
        except Exception as error:
            failure = failure or {"type": type(error).__name__, "message": str(error)}
        save_progress()
        refs_unchanged = None
        try:
            refs_unchanged = git.refs() == before
            require(refs_unchanged, "Source-only fetch changed local refs")
        except Exception as error:
            failure = failure or {"type": type(error).__name__, "message": str(error)}
        missing = [
            statuses[row["oid"]] for row in selected if row["oid"] not in exported
        ]
        rows_gz(args.output / "missing-objects.jsonl.gz", missing)
        complete = not missing and failure is None
        write_json(
            args.output / "manifest.json",
            {
                "schema": "hepta.missing-source-export.v1",
                "repository": REPOSITORY,
                "part": args.part,
                "parts": 16,
                "runtime_head": runtime_head,
                "request_sha256": args.request_sha256,
                "source_graph_result_sha256": value["graph_result_sha256"],
                "source_result_sha256": value["source_result_sha256"],
                "source_witnesses_sha256": value["source_witnesses_sha256"],
                "fixed_branch_tree_vector_sha256": value[
                    "fixed_branch_tree_vector_sha256"
                ],
                "requested": len(selected),
                "verified_exported": len(exported),
                "missing": len(missing),
                "complete": complete,
                "failure": failure,
                "failed_original_fetches": network_failures,
                "preexisting_refs_unchanged": refs_unchanged,
                "local_source_only_store_has_no_ref_destinations": True,
                "original_head_or_graph_exported": False,
                "packs": packs,
                "source_policy_is_runtime_dependency_qualification": False,
                "elapsed_seconds": time.monotonic() - started,
            },
        )
    return 0 if complete else 1


def finalize(args):
    """Preserve every generated file, including incomplete packs, by actual bytes."""
    require(
        args.output.is_dir() and not args.output.is_symlink(),
        "Existing isolated source output",
    )
    if args.bootstrap is not None:
        require(
            args.bootstrap.is_dir() and not args.bootstrap.is_symlink(),
            "Original bootstrap directory",
        )
        destination = args.output / "bootstrap-inputs"
        destination.mkdir(exist_ok=False)
        for original in regular_files(args.bootstrap):
            target = destination / original.relative_to(args.bootstrap)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
            require(
                sha256_file(original) == sha256_file(target), "Bootstrap original bytes"
            )
    files = regular_files(args.output)
    require(files, "No generated evidence to retain")
    records = []
    groups = {}
    for path in files:
        relative = path.relative_to(args.output).as_posix()
        row = {
            "path": relative,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "filesystem_mode": format(path.stat().st_mode & 0o777, "04o"),
        }
        records.append(row)
        group = (
            path.stem
            if path.parent == args.output and path.suffix in (".pack", ".idx", ".rev")
            else relative
        )
        groups.setdefault(group, []).append(row)
    allocations = []
    # Actual pack + sidecar totals stay together. Non-pack evidence remains byte exact.
    reserve = 4 * 1024 * 1024
    for name, members in sorted(
        groups.items(),
        key=lambda item: (-sum(row["bytes"] for row in item[1]), item[0]),
    ):
        size = sum(row["bytes"] for row in members)
        require(
            size <= VOLUME_BYTES - reserve,
            "One atomic member group exceeds bounded artifact capacity",
        )
        for volume in allocations:
            if volume["bytes"] + size <= VOLUME_BYTES - reserve:
                break
        else:
            require(
                len(allocations) < MAX_VOLUMES,
                "More than the fixed eight upload volumes required",
            )
            volume = {"bytes": 0, "groups": [], "files": []}
            allocations.append(volume)
        volume["groups"].append(name)
        volume["files"].extend(members)
        volume["bytes"] += size
    args.artifacts.mkdir(exist_ok=False)
    common = {
        "schema": "hepta.missing-source-artifact-volumes.v1",
        "part": args.part,
        "parts": 16,
        "runtime_head": os.environ.get("GITHUB_SHA"),
        "runtime_run_id": os.environ.get("GITHUB_RUN_ID"),
        "runtime_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "original_files": records,
        "volumes": [
            {
                "volume": index,
                "actual_original_bytes": item["bytes"],
                "groups": item["groups"],
                "paths": [row["path"] for row in item["files"]],
            }
            for index, item in enumerate(allocations)
        ],
        "pack_validation_is_only_in_original_verified_packs_receipt": True,
        "interrupted_pack_bytes_are_not_accepted_objects": True,
        "all_original_files_exactly_once": True,
    }
    raw_manifest = (json.dumps(common, sort_keys=True, indent=2) + "\n").encode()
    require(len(raw_manifest) < reserve, "Volume metadata reserve")
    for index, volume in enumerate(allocations):
        destination = args.artifacts / f"volume-{index}"
        destination.mkdir()
        for row in volume["files"]:
            source = args.output / row["path"]
            target = destination / "original" / row["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            os.chmod(target, int(row["filesystem_mode"], 8))
            require(
                target.stat().st_size == row["bytes"]
                and sha256_file(target) == row["sha256"],
                "Volume member byte preservation",
            )
        (destination / "volume-manifest.json").write_bytes(raw_manifest)
        write_json(
            destination / "part-identity.json",
            {
                "part": args.part,
                "volume": index,
                "volumes": len(allocations),
                "common_manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(),
            },
        )
        require(
            total_bytes(destination) < VOLUME_BYTES, "Measured artifact payload limit"
        )
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
            stream.write(f"volume_{index}=true\n")
    print(
        json.dumps(
            {
                "retained_original_files": len(records),
                "actual_original_bytes": sum(row["bytes"] for row in records),
                "volumes": len(allocations),
                "volume_payload_limit": VOLUME_BYTES,
            }
        )
    )
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("collect", "finalize"))
    parser.add_argument("--part", required=True, type=int, choices=range(16))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--request-sha256")
    parser.add_argument("--exporter", type=Path)
    parser.add_argument("--repository", type=Path)
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--bootstrap", type=Path)
    args = parser.parse_args()
    if args.mode == "collect":
        require(
            all((args.request, args.request_sha256, args.exporter, args.repository)),
            "Collect arguments",
        )
        try:
            return source_broker(args)
        except Exception as error:
            if args.output.is_dir() and not args.output.is_symlink():
                write_json(
                    args.output / "launcher-failure.json",
                    {
                        "type": type(error).__name__,
                        "message": str(error),
                        "completed": False,
                    },
                )
            raise
    require(args.artifacts is not None, "Finalize artifact directory")
    return finalize(args)


if __name__ == "__main__":
    raise SystemExit(main())
