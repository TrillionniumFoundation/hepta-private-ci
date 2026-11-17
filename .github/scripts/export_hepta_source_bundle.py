#!/usr/bin/env python3
"""Export fixed Git objects without exporting repository configuration or credentials."""

import argparse
import base64
import contextlib
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import time

REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
TEMPORARY_REF = "refs/heads/integration/hepta-rust-validation-20261117-59d82"
BASE_ANCHOR = "6ab2631a5ed42040f2f3c3d6d568ac4099d55349"
SNAPSHOT_SHA256 = "e49cb2fabe04aa506c6073d56f2435a102189d022774a0e38a4a0ce037d49326"
SNAPSHOT_RAW_SHA256 = "b0c764f1bcbe36587a086176e3ff280e6facfe59cc146d60440ef87b8d59f8ee"
OID = re.compile(r"[0-9a-f]{40}\Z")
RESERVE_BYTES = 256 * 1024 * 1024
PACK_RAW_BYTES = 64 * 1024 * 1024
SOURCE_ROOTS = {
    ".github",
    "apps",
    "bazel",
    "codex-rs",
    "config",
    "configs",
    "ext",
    "scripts",
    "sdk",
    "tools",
}
SOURCE_SUFFIXES = {
    ".rs",
    ".toml",
    ".lock",
    ".bzl",
    ".bazel",
    ".py",
    ".pyi",
    ".sh",
    ".bash",
    ".ps1",
    ".cmd",
    ".bat",
    ".js",
    ".mjs",
    ".cjs",
    ".jsx",
    ".ts",
    ".tsx",
    ".json",
    ".jsonc",
    ".yaml",
    ".yml",
    ".c",
    ".h",
    ".cc",
    ".cpp",
    ".hpp",
    ".inc",
    ".nix",
    ".proto",
    ".sql",
}
SOURCE_NAMES = {
    "AGENTS.md",
    "BUILD",
    "BUILD.bazel",
    "CALLERS.toml",
    "Dockerfile",
    "Makefile",
    "MODULE.bazel",
    "WORKSPACE",
    "WORKSPACE.bazel",
    "justfile",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
    )


def write_rows(path, rows):
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as stream:
            for row in rows:
                stream.write(
                    (
                        json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n"
                    ).encode()
                )


def artifact_inventory(output, status, started):
    files = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "artifact-files.json":
            files.append(
                {
                    "path": path.relative_to(output).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    write_json(
        output / "artifact-files.json",
        {
            "exit_status": status,
            "elapsed_seconds": time.time() - started,
            "files": files,
        },
    )


def resume_current_capsule(
    git, directory, head, tree_oid, snapshot_identity, expected_objects
):
    require(
        directory.is_dir() and not directory.is_symlink(), "current capsule directory"
    )
    actual_files = set()
    for path in directory.rglob("*"):
        require(
            not path.is_symlink() and (path.is_file() or path.is_dir()),
            "current capsule contains a non-regular path",
        )
        if path.is_file():
            actual_files.add(path.relative_to(directory).as_posix())
    receipt = json.loads(
        (directory / "artifact-files.json").read_text(encoding="utf-8")
    )
    require(receipt["exit_status"] == 0, "current capsule did not complete")
    expected_files = {"artifact-files.json"}
    for row in receipt["files"]:
        relative = PurePosixPath(row["path"])
        require(
            not relative.is_absolute()
            and relative.parts
            and not any(part in (".", "..") for part in relative.parts)
            and "\\" not in row["path"]
            and ":" not in row["path"],
            "current capsule member path",
        )
        require(row["path"] not in expected_files, "duplicate current capsule member")
        expected_files.add(row["path"])
        path = directory.joinpath(*relative.parts)
        require(
            path.stat().st_size == row["bytes"] and sha256_file(path) == row["sha256"],
            "current capsule member bytes",
        )
    require(
        expected_files == actual_files, "current capsule unexpected or missing file"
    )
    record = json.loads(
        (directory / "current-head-complete.json").read_text(encoding="utf-8")
    )
    require(
        record["head"] == head and record["snapshot_identity"] == snapshot_identity,
        "current capsule head or snapshot identity",
    )
    require(
        record["tree"] == tree_oid
        and record["unique_objects"] == len(expected_objects),
        "current capsule tree or object count",
    )
    with gzip.open(
        directory / "current-head-exported-objects.jsonl.gz", "rt", encoding="utf-8"
    ) as stream:
        rows = [json.loads(line) for line in stream]
    inventory = {row["oid"]: (row["type"], row["bytes"]) for row in rows}
    require(
        len(inventory) == len(rows) and inventory == expected_objects,
        "current capsule object inventory differs from actual HEAD closure",
    )
    packed = {}
    for pack in record["packs"]:
        require(
            pack["path"] in actual_files and pack["index_path"] in actual_files,
            "current capsule pack path",
        )
        for member, length, digest in (
            (pack["path"], pack["bytes"], pack["sha256"]),
            (pack["index_path"], pack["index_bytes"], pack["index_sha256"]),
        ):
            path = directory / member
            require(
                path.stat().st_size == length and sha256_file(path) == digest,
                "current capsule declared pack identity",
            )
        for line in git.text(
            "verify-pack", "-v", str(directory / pack["index_path"])
        ).splitlines():
            fields = line.split()
            if fields and OID.fullmatch(fields[0]):
                require(
                    fields[0] not in packed, "duplicate current capsule packed object"
                )
                packed[fields[0]] = (fields[1], int(fields[2]))
    require(
        packed == expected_objects,
        "current capsule pack contents differ from actual HEAD closure",
    )
    return {
        "head": head,
        "artifact_files_sha256": sha256_file(directory / "artifact-files.json"),
        "current_head_manifest_sha256": sha256_file(
            directory / "current-head-complete.json"
        ),
        "objects": len(packed),
        "packs": record["packs"],
        "artifact_name": "hepta-source-broker-head-"
        + head
        + "-"
        + os.environ.get("GITHUB_RUN_ATTEMPT", "fixture"),
    }


def validate_snapshot(path):
    compressed = path.read_bytes()
    require(
        hashlib.sha256(compressed).hexdigest() == SNAPSHOT_SHA256,
        "snapshot compressed hash",
    )
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        raw = stream.read(1024 * 1024 + 1)
    require(len(raw) <= 1024 * 1024, "snapshot decoded length")
    require(
        hashlib.sha256(raw).hexdigest() == SNAPSHOT_RAW_SHA256, "snapshot decoded hash"
    )
    value = json.loads(raw)
    require(value["repository"] == REPOSITORY, "snapshot repository")
    require(value["schema"] == "hepta.source-broker.snapshot.v1", "snapshot schema")
    rows = value["ordinary_refs"]
    names = [row["name"] for row in rows]
    require(len(rows) == value["expected_ordinary_count"] == 7230, "ordinary ref count")
    require(names == sorted(set(names)), "ordinary names order or duplicates")
    require(len(set(value["excluded_names"])) == 249, "protected name count")
    require(len(set(value["excluded_pins"])) == 259, "protected pin count")
    require(not set(names) & set(value["excluded_names"]), "protected name selected")
    require("main" not in names, "main is a separate anchor")
    for row in rows:
        require(OID.fullmatch(row["sha"]), "invalid snapshot OID")
        require(row["sha"] not in value["excluded_pins"], "protected tip selected")
        require(not any(c in row["name"] for c in "\n\r\x00"), "invalid ref name")
    require(
        value["main_anchor"] == "732e934ba496d90fbe042b8d41d479ef901643e5",
        "main anchor",
    )
    return value


class Git:
    """All object reads disable transport; the explicit fetch method is the only network path."""

    def __init__(self, repository, output, token=""):
        self.repository = repository.resolve()
        self.output = output
        self.token = token
        self.commands = output / "commands"
        self.commands.mkdir()
        self.hooks = output / "empty-hooks"
        self.hooks.mkdir()
        self.serial = 0
        self.readers = []
        self.environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_") and key != "BROKER_GITHUB_TOKEN"
        }
        self.environment.update(
            {
                "GIT_NO_LAZY_FETCH": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
            }
        )

    def command(self, args):
        return [
            "git",
            "--no-replace-objects",
            "-C",
            str(self.repository),
            "-c",
            "protocol.allow=never",
            "-c",
            "core.hooksPath=" + str(self.hooks),
            "-c",
            "credential.helper=",
            *args,
        ]

    def run(self, args, data=None, network=False, stdout_path=None, check=True):
        self.serial += 1
        name = f"{self.serial:05d}"
        environment = dict(self.environment)
        command = self.command(args)
        if network:
            require(
                self.token, "explicit fixed-OID fetch needs the ephemeral read token"
            )
            header = (
                "AUTHORIZATION: basic "
                + base64.b64encode(("x-access-token:" + self.token).encode()).decode()
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
                    *args,
                ]
            )
        started = time.monotonic()
        with (
            stdout_path.open("wb")
            if stdout_path
            else contextlib.nullcontext() as target
        ):
            result = subprocess.run(
                command,
                input=data,
                stdout=target or subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
            )
        stderr = result.stderr
        if self.token:
            for secret in (
                self.token,
                base64.b64encode(("x-access-token:" + self.token).encode()).decode(),
            ):
                stderr = stderr.replace(secret.encode(), b"[redacted]")
        (self.commands / (name + ".stderr")).write_bytes(stderr)
        write_json(
            self.commands / (name + ".json"),
            {
                "argv": command,
                "returncode": result.returncode,
                "elapsed_seconds": time.monotonic() - started,
                "stdin_sha256": hashlib.sha256(data).hexdigest()
                if data is not None
                else None,
                "stdin_bytes": len(data) if data is not None else 0,
                "explicit_same_repository_network": network,
                "stdout_file": stdout_path.name if stdout_path else None,
            },
        )
        if check:
            require(
                result.returncode == 0,
                f"Git command {name} failed with status {result.returncode}; see its retained stderr",
            )
        return result

    def text(self, *args, data=None):
        return self.run(list(args), data=data).stdout.decode("utf-8", "strict").strip()

    def refs(self):
        return dict(
            line.split(" ", 1)
            for line in self.text(
                "for-each-ref", "--format=%(refname) %(objectname)"
            ).splitlines()
        )

    def info(self, oids):
        ordered = sorted(set(oids))
        if not ordered:
            return {}
        result = self.text(
            "cat-file",
            "--batch-check=%(objectname) %(objecttype) %(objectsize)",
            data=("\n".join(ordered) + "\n").encode(),
        )
        lines = result.splitlines()
        require(len(lines) == len(ordered), "cat-file inventory length")
        values = {}
        for expected, line in zip(ordered, lines):
            fields = line.split()
            require(fields[0] == expected, "cat-file inventory identity")
            values[expected] = (
                None if fields[1:] == ["missing"] else (fields[1], int(fields[2]))
            )
        return values

    def hydrate(self, oids, kind="blob"):
        """Fetch only fixed object IDs; no refspec destination, tags, FETCH_HEAD, or credentials file."""
        require(all(OID.fullmatch(oid) for oid in oids), "fetch OID syntax")
        if not oids:
            return
        require(kind in ("blob", "commit"), "explicit fetch object kind")
        url = "https://github.com/" + REPOSITORY + ".git"
        destination = url
        options = []
        if kind == "commit":
            origin = self.text("remote", "get-url", "origin")
            require(
                origin in (url, url.removesuffix(".git")),
                "origin is not the approved repository",
            )
            require(
                self.text("config", "--local", "--bool", "remote.origin.promisor")
                == "true",
                "filtered tip fetch requires the existing checkout promisor",
            )
            require(
                self.text("config", "--local", "remote.origin.partialclonefilter")
                == "blob:none",
                "checkout filter differs",
            )
            destination = "origin"
            options = ["--filter=blob:none"]
        rewrites = self.run(
            ["config", "--local", "--get-regexp", r"^url\..*\.insteadof$"], check=False
        )
        require(
            rewrites.returncode == 1 and not rewrites.stdout,
            "local URL rewriting is not accepted",
        )
        self.run(
            [
                "fetch",
                "--quiet",
                "--no-tags",
                "--no-write-fetch-head",
                "--recurse-submodules=no",
                "--no-auto-maintenance",
                *options,
                "--stdin",
                destination,
            ],
            data=("\n".join(oids) + "\n").encode(),
            network=True,
            check=False,
        )


class Reader:
    def __init__(self, git):
        self.git = git
        self.process = subprocess.Popen(
            git.command(["cat-file", "--batch"]),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=git.environment,
        )
        self.closed = False
        git.readers.append(self)

    def read(self, oid, retain=True):
        require(OID.fullmatch(oid), "reader OID")
        self.process.stdin.write((oid + "\n").encode())
        self.process.stdin.flush()
        header = self.process.stdout.readline().decode().strip().split()
        require(
            len(header) == 3 and header[0] == oid, "missing or invalid object " + oid
        )
        kind, length = header[1], int(header[2])
        require(
            not retain or length <= 64 * 1024 * 1024,
            "metadata object too large for bounded reader",
        )
        git_hash = hashlib.sha1((kind + " " + str(length) + "\0").encode())
        digest = hashlib.sha256()
        pieces = []
        remaining = length
        while remaining:
            block = self.process.stdout.read(min(1024 * 1024, remaining))
            require(block, "truncated object " + oid)
            remaining -= len(block)
            git_hash.update(block)
            digest.update(block)
            if retain:
                pieces.append(block)
        require(self.process.stdout.read(1) == b"\n", "cat-file object terminator")
        require(git_hash.hexdigest() == oid, "object content identity " + oid)
        return kind, length, digest.hexdigest(), b"".join(pieces)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.process.stdin.close()
        while self.process.stdout.read(1024 * 1024):
            pass
        stderr = self.process.stderr.read()
        status = self.process.wait()
        require(status == 0 and not stderr, "cat-file reader termination")


def parse_tree(raw):
    entries = []
    position = 0
    while position < len(raw):
        space = raw.index(b" ", position)
        zero = raw.index(b"\0", space)
        mode = raw[position:space].decode("ascii")
        name = raw[space + 1 : zero]
        require(
            name and b"/" not in name and name not in (b".", b".."),
            "invalid Git tree name",
        )
        require(zero + 21 <= len(raw), "truncated tree entry")
        entries.append(
            (
                mode,
                name.decode("utf-8", "surrogateescape"),
                raw[zero + 1 : zero + 21].hex(),
            )
        )
        position = zero + 21
    return entries


def source_name(path, full):
    name = path.rsplit("/", 1)[-1]
    return (
        full
        or "/" not in path
        or name in SOURCE_NAMES
        or Path(name).suffix.lower() in SOURCE_SUFFIXES
    )


def ensure_available(git, oids, output, label, kind="blob"):
    values = git.info(oids)
    missing = [oid for oid, value in values.items() if value is None]
    attempts = []
    for start in range(0, len(missing), 64):
        batch = missing[start : start + 64]
        if shutil.disk_usage(output).free < 2 * RESERVE_BYTES:
            break
        git.hydrate(batch, kind=kind)
        after = git.info(batch)
        attempts.append(
            {
                "requested": batch,
                "obtained": [oid for oid in batch if after[oid] is not None],
            }
        )
        values.update(after)
    write_rows(output / (label + "-hydration.jsonl.gz"), attempts)
    return values


def pack_objects(git, output, oids, values, exported, packs, required):
    group = []
    size = 0

    def emit():
        nonlocal group, size
        if not group:
            return True
        if shutil.disk_usage(output).free < size + size // 50 + RESERVE_BYTES:
            require(
                not required, "insufficient measured space for required object pack"
            )
            return False
        name = f"objects-{len(packs):05d}"
        pack = output / (name + ".pack")
        git.run(
            [
                "pack-objects",
                "--stdout",
                "--window=0",
                "--no-reuse-delta",
                "--threads=1",
                "--compression=6",
            ],
            data=("\n".join(group) + "\n").encode(),
            stdout_path=pack,
        )
        git.run(["index-pack", "--index-version=2", str(pack)])
        index = pack.with_suffix(".idx")
        verification = git.text("verify-pack", "-v", str(index))
        actual = {}
        for line in verification.splitlines():
            fields = line.split()
            if fields and OID.fullmatch(fields[0]):
                actual[fields[0]] = (fields[1], int(fields[2]))
        require(
            actual == {oid: values[oid] for oid in group},
            "pack contains different objects",
        )
        packs.append(
            {
                "path": pack.name,
                "bytes": pack.stat().st_size,
                "sha256": sha256_file(pack),
                "index_path": index.name,
                "index_bytes": index.stat().st_size,
                "index_sha256": sha256_file(index),
                "objects": len(group),
            }
        )
        exported.update(group)
        group, size = [], 0
        return True

    for oid in sorted(set(oids) - exported):
        if values.get(oid) is None:
            require(not required, "required object missing " + oid)
            continue
        length = values[oid][1]
        if group and (size + length > PACK_RAW_BYTES or len(group) >= 8192):
            if not emit():
                return
        group.append(oid)
        size += length
    emit()


def protected_witnesses(parents, ordinary, protected):
    relevant = sorted(set(parents) & set(protected))
    if not relevant:
        return
    own = {oid: 1 << index for index, oid in enumerate(relevant)}
    bits = {}
    for oid, predecessors in parents.items():
        require(
            all(parent in bits for parent in predecessors),
            "parent graph is not in reverse topological order",
        )
        value = own.get(oid, 0)
        for parent in predecessors:
            value |= bits[parent]
        bits[oid] = value
    names = {}
    for row in ordinary:
        names.setdefault(row["sha"], []).append(row["name"])
    for tip, aliases in sorted(names.items()):
        present = [
            oid for index, oid in enumerate(relevant) if bits[tip] & (1 << index)
        ]
        if present:
            yield {
                "tip": tip,
                "ordinary_names": aliases,
                "protected_pins": present,
                "witness_graph": "commit-parent-graph.jsonl.gz",
            }


def source_priority(witness):
    path = witness["path"]
    name = path.rsplit("/", 1)[-1]
    suffix = Path(name).suffix.lower()
    if suffix in {".rs", ".toml", ".lock", ".bzl", ".bazel"} or name in SOURCE_NAMES:
        return 0
    if suffix in SOURCE_SUFFIXES:
        return 1
    return 2


def hydrate_source_packs(git, output, witnesses, exported, packs):
    values = git.info(witnesses)
    require(
        all(value is None or value[0] == "blob" for value in values.values()),
        "source policy selected a non-blob",
    )
    ordered = sorted(witnesses, key=lambda oid: (source_priority(witnesses[oid]), oid))
    attempts = []
    for priority in range(3):
        layer = [
            oid
            for oid in ordered
            if source_priority(witnesses[oid]) == priority and oid not in exported
        ]
        present = [oid for oid in layer if values[oid] is not None]
        pack_objects(git, output, present, values, exported, packs, required=False)
        if set(present) - exported:
            break
        missing = [oid for oid in layer if values[oid] is None]
        batch_size = 32 if priority < 2 else 1
        for start in range(0, len(missing), batch_size):
            batch = missing[start : start + batch_size]
            if shutil.disk_usage(output).free < 4 * RESERVE_BYTES:
                break
            git.hydrate(batch)
            after = git.info(batch)
            require(
                all(value is None or value[0] == "blob" for value in after.values()),
                "fetched source object type",
            )
            values.update(after)
            obtained = [oid for oid in batch if after[oid] is not None]
            pack_objects(git, output, obtained, values, exported, packs, required=False)
            attempts.append(
                {
                    "priority": priority,
                    "requested": batch,
                    "obtained": obtained,
                    "packed": [oid for oid in obtained if oid in exported],
                    "free_bytes_after": shutil.disk_usage(output).free,
                }
            )
            if set(obtained) - exported:
                break
        if set(layer) - exported:
            break
    write_rows(output / "ordinary-tip-source-hydration.jsonl.gz", attempts)


def export_capsule(
    git, output, snapshot, head, base_anchor, phase="all", current_capsule=None
):
    try:
        return export_objects(
            git, output, snapshot, head, base_anchor, phase, current_capsule
        )
    finally:
        for reader in git.readers:
            reader.close()


def export_objects(git, output, snapshot, head, base_anchor, phase, current_capsule):
    """Produce verified non-thin packs; absence is explicit, never a substituted snapshot tip."""
    before = git.refs()
    write_rows(
        output / "original-ref-vector.jsonl.gz",
        ({"ref": name, "oid": oid} for name, oid in sorted(before.items())),
    )
    ordinary = snapshot["ordinary_refs"]
    names = [row["name"] for row in ordinary]
    require(
        len(names) == len(set(names)) and "main" not in names, "ordinary name boundary"
    )
    require(not set(names) & set(snapshot["excluded_names"]), "protected name selected")
    require(
        not {row["sha"] for row in ordinary} & set(snapshot["excluded_pins"]),
        "protected tip selected",
    )
    require(
        git.text("rev-parse", "HEAD") == head,
        "checkout does not equal expected push head",
    )
    require(
        git.text("rev-parse", "--is-shallow-repository") == "false",
        "full commit history required",
    )
    require(
        git.text("rev-parse", "--show-object-format") == "sha1",
        "unsupported object format",
    )
    grafts = Path(git.text("rev-parse", "--git-path", "info/grafts"))
    if not grafts.is_absolute():
        grafts = git.repository / grafts
    require(
        not grafts.exists() or grafts.stat().st_size == 0,
        "legacy grafts are not accepted",
    )
    git.run(["merge-base", "--is-ancestor", base_anchor, head])
    roots = {row["sha"] for row in ordinary} | {snapshot["main_anchor"], head}
    snapshot_identity = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    reader = Reader(git)
    trees = {}
    exported, packs = set(), []
    source_witness = {}
    head_files, head_objects = [], {head}

    def tree(oid):
        if oid not in trees:
            kind, _, _, raw = reader.read(oid)
            require(kind == "tree", "tree object type")
            trees[oid] = parse_tree(raw)
        return trees[oid]

    def root_tree(oid):
        kind, _, _, raw = reader.read(oid)
        require(kind == "commit", "snapshot anchor is not a commit " + oid)
        first = raw.split(b"\n", 1)[0]
        require(
            first.startswith(b"tree ") and OID.fullmatch(first[5:].decode()),
            "commit tree header",
        )
        return first[5:].decode()

    def current_walk(oid, prefix=""):
        head_objects.add(oid)
        for mode, name, child in tree(oid):
            path = prefix + name
            if mode == "40000":
                current_walk(child, path + "/")
            elif mode in ("100644", "100755", "120000"):
                head_objects.add(child)
                head_files.append({"path": path, "mode": mode, "oid": child})
            elif mode == "160000":
                head_files.append(
                    {"path": path, "mode": mode, "oid": child, "external_gitlink": True}
                )
            else:
                raise ValueError("unsupported tree mode " + mode)

    current_tree = root_tree(head)
    current_walk(current_tree)
    head_values = (
        git.info(head_objects)
        if phase == "history"
        else ensure_available(git, head_objects, output, "current-head")
    )
    require(
        all(value is not None for value in head_values.values()),
        "current HEAD tracked objects unavailable",
    )
    prerequisite = None
    if phase == "history":
        require(current_capsule is not None, "history phase requires current capsule")
        prerequisite = resume_current_capsule(
            git, current_capsule, head, current_tree, snapshot_identity, head_values
        )
        exported.update(head_objects)
    else:
        hashes = {}
        for row in head_files:
            if row.get("external_gitlink"):
                continue
            oid = row["oid"]
            if oid not in hashes:
                kind, length, digest, _ = reader.read(oid, retain=False)
                require(kind == "blob", "tracked file is not a blob")
                hashes[oid] = (length, digest)
            row["bytes"], row["sha256"] = hashes[oid]
        write_rows(output / "current-head-files.jsonl.gz", head_files)
        pack_objects(
            git, output, head_objects, head_values, exported, packs, required=True
        )
        write_rows(
            output / "current-head-exported-objects.jsonl.gz",
            (
                {"oid": oid, "type": head_values[oid][0], "bytes": head_values[oid][1]}
                for oid in sorted(head_objects)
            ),
        )
        write_json(
            output / "current-head-complete.json",
            {
                "head": head,
                "tree": current_tree,
                "snapshot_identity": snapshot_identity,
                "tracked_entries": len(head_files),
                "tracked_raw_bytes": sum(row.get("bytes", 0) for row in head_files),
                "unique_objects": len(head_objects),
                "packs": list(packs),
                "lfs_external_payloads": "not requested; exact Git pointer bytes are preserved",
                "gitlinks": "foreign object databases are not imported",
            },
        )
        if phase == "current":
            require(git.refs() == before, "current phase changed local refs")
            result = {
                "schema": "hepta.current-head-object-store.v1",
                "expected_head": head,
                "tree": current_tree,
                "current_head_tracked_tree_complete": True,
                "historical_tip_export": "not started",
                "packs": packs,
                "full_bundle": None,
            }
            write_json(output / "manifest.json", result)
            return result

    tip_values = ensure_available(git, roots, output, "fixed-tips", kind="commit")
    require(
        all(
            value is not None and value[0] == "commit" for value in tip_values.values()
        ),
        "fixed tip missing or not a commit; current HEAD capsule remains available",
    )
    root_input = ("\n".join(sorted(roots)) + "\n").encode()
    metadata_text = git.text(
        "rev-list",
        "--objects",
        "--no-object-names",
        "--filter=blob:none",
        "--missing=print",
        "--stdin",
        data=root_input,
    )
    metadata = set(metadata_text.splitlines())
    require(
        all(OID.fullmatch(oid) for oid in metadata), "commit/tree closure incomplete"
    )
    metadata_values = git.info(metadata)
    require(
        all(
            value is not None and value[0] in ("commit", "tree")
            for value in metadata_values.values()
        ),
        "commit/tree closure contains a missing or unexpected object",
    )
    parents = {}
    for line in git.text(
        "rev-list", "--parents", "--topo-order", "--reverse", "--stdin", data=root_input
    ).splitlines():
        fields = line.split()
        require(all(OID.fullmatch(value) for value in fields), "commit graph identity")
        parents[fields[0]] = fields[1:]
    require(
        all(parent in parents for values in parents.values() for parent in values),
        "commit graph has missing parent",
    )
    write_rows(
        output / "commit-parent-graph.jsonl.gz",
        ({"commit": oid, "parents": values} for oid, values in sorted(parents.items())),
    )
    witness_count = 0

    def counted_witnesses():
        nonlocal witness_count
        for row in protected_witnesses(parents, ordinary, snapshot["excluded_pins"]):
            witness_count += 1
            yield row

    write_rows(output / "protected-ancestor-witnesses.jsonl.gz", counted_witnesses())
    pack_objects(git, output, metadata, metadata_values, exported, packs, required=True)
    write_json(
        output / "metadata-complete.json",
        {
            "commits": len(parents),
            "trees": sum(value[0] == "tree" for value in metadata_values.values()),
            "protected_tip_witness_rows": witness_count,
            "meaning": "Read-only custody only; an ancestry intersection does not authorize merging that history.",
        },
    )

    visited = set()

    def source_walk(oid, tip, prefix="", full=False):
        key = (oid, full, not prefix)
        if key in visited:
            return
        visited.add(key)
        for mode, name, child in tree(oid):
            path = prefix + name
            selected = full or (not prefix and name in SOURCE_ROOTS)
            if mode == "40000":
                source_walk(child, tip, path + "/", selected)
            elif mode in ("100644", "100755", "120000") and source_name(path, selected):
                source_witness.setdefault(
                    child, {"tip": tip, "path": path, "mode": mode}
                )

    labels = {}
    ref_rows = []
    namespace = "refs/audit-export/source-broker/"
    require(
        not any(name.startswith(namespace) for name in before),
        "local export namespace already exists",
    )
    for number, row in enumerate(ordinary):
        label = namespace + f"ordinary/{number:05d}"
        labels[label] = row["sha"]
        tip_tree = root_tree(row["sha"])
        source_walk(tip_tree, row["sha"])
        tracking = before.get("refs/remotes/origin/" + row["name"])
        ref_rows.append(
            {
                **row,
                "tree": tip_tree,
                "export_label": label,
                "fetched_tracking_oid": tracking,
                "tracking_drift": tracking != row["sha"],
            }
        )
    labels[namespace + "anchors/main"] = snapshot["main_anchor"]
    labels[namespace + "anchors/running-head"] = head
    write_rows(output / "snapshot-refs.jsonl.gz", ref_rows)
    reader.close()
    hydrate_source_packs(git, output, source_witness, exported, packs)

    closure_text = git.text(
        "rev-list",
        "--objects",
        "--no-object-names",
        "--missing=print",
        "--stdin",
        data=root_input,
    )
    closure = {line.removeprefix("?") for line in closure_text.splitlines()}
    require(all(OID.fullmatch(oid) for oid in closure), "closure inventory identity")
    values = git.info(closure)
    require(not exported - closure, "exported object outside requested closure")
    missing = []
    for oid in sorted(closure - exported):
        value = values[oid]
        missing.append(
            {
                "oid": oid,
                "type": value[0] if value else "blob",
                "bytes": value[1] if value else None,
                "local_object_present": value is not None,
                "selected_tip_source": oid in source_witness,
                "source_witness": source_witness.get(oid),
                "reason": "selected source unavailable or measured disk limit"
                if oid in source_witness
                else "historical or non-source blob not included in capsule",
            }
        )
    write_rows(output / "omitted-object-ledger.jsonl.gz", missing)
    write_rows(
        output / "exported-object-inventory.jsonl.gz",
        (
            {"oid": oid, "type": values[oid][0], "bytes": values[oid][1]}
            for oid in sorted(exported)
        ),
    )
    write_rows(
        output / "source-policy-witnesses.jsonl.gz",
        (
            {"oid": oid, **value, "exported": oid in exported}
            for oid, value in sorted(source_witness.items())
        ),
    )
    transaction = [
        "start",
        *("create " + name + " " + oid for name, oid in sorted(labels.items())),
        "prepare",
        "commit",
    ]
    git.run(["update-ref", "--stdin"], data=("\n".join(transaction) + "\n").encode())
    require(git.refs() == {**before, **labels}, "pre-existing local refs changed")
    write_rows(
        output / "original-ref-vector.jsonl.gz",
        ({"ref": name, "oid": oid} for name, oid in sorted(before.items())),
    )
    write_rows(
        output / "export-ref-vector.jsonl.gz",
        ({"ref": name, "oid": oid} for name, oid in sorted(labels.items())),
    )
    bundle = None
    raw_bound = sum(value[1] for value in values.values() if value is not None)
    if (
        all(value is not None for value in values.values())
        and shutil.disk_usage(output).free
        >= raw_bound + raw_bound // 50 + RESERVE_BYTES
    ):
        bundle_path = output / "unverified-history.bundle.partial"
        git.run(
            ["bundle", "create", str(bundle_path), "--stdin"],
            data=("\n".join(sorted(labels)) + "\n").encode(),
        )
        git.run(["bundle", "verify", str(bundle_path)])
        actual = dict(
            line.split(" ", 1)[::-1]
            for line in git.text("bundle", "list-heads", str(bundle_path)).splitlines()
        )
        require(
            actual == labels, "bundle advertised refs differ from fixed export labels"
        )
        with bundle_path.open("rb") as stream:
            header = []
            while line := stream.readline():
                if line == b"\n":
                    break
                header.append(line)
        require(
            not any(line.startswith(b"-") for line in header),
            "complete bundle has prerequisites",
        )
        bundle_path = bundle_path.rename(output / "complete-history.bundle")
        bundle = {
            "path": bundle_path.name,
            "bytes": bundle_path.stat().st_size,
            "sha256": sha256_file(bundle_path),
        }
    source_complete = set(source_witness) <= exported
    result = {
        "schema": "hepta.partial-object-store.v1",
        "repository": REPOSITORY,
        "expected_head": head,
        "base_anchor": base_anchor,
        "main_anchor": snapshot["main_anchor"],
        "snapshot": snapshot.get("snapshot"),
        "ordinary_refs": len(ordinary),
        "ordinary_unique_tips": len({row["sha"] for row in ordinary}),
        "current_head_tracked_tree_complete": True,
        "all_tip_commit_tree_closure_complete": True,
        "ordinary_tip_source_policy_complete": source_complete,
        "source_policy": {
            "entire_roots": sorted(SOURCE_ROOTS),
            "suffixes": sorted(SOURCE_SUFFIXES),
            "names": sorted(SOURCE_NAMES),
            "all_root_files": True,
            "qualification": "A literal object-selection policy, not proof of every compiler or runtime dependency.",
        },
        "exported_objects": len(exported),
        "closure_objects": len(closure),
        "omitted_objects": len(missing),
        "selected_source_omissions": len(set(source_witness) - exported),
        "protected_ancestry": "Recorded without changing any protected reference or authorizing any merge.",
        "packs": packs,
        "full_bundle": bundle,
        "prerequisite_current_head_capsule": prerequisite,
        "full_bundle_skip": None
        if bundle
        else "Some closure objects are absent, or measured free space is below the uncompressed upper-bound planning requirement.",
        "remote_ref_writes": False,
        "preexisting_local_refs_unchanged": True,
    }
    write_json(output / "manifest.json", result)
    return result


def verify_push_event(expected_head):
    event_path = Path(os.environ["GITHUB_EVENT_PATH"])
    require(event_path.stat().st_size <= 2 * 1024 * 1024, "push event size")
    event = json.loads(event_path.read_text(encoding="utf-8"))
    require(event.get("deleted") is False, "branch-deletion pushes are not exports")
    require(
        event.get("after") == expected_head,
        "push event after differs from expected head",
    )
    require(event.get("ref") == TEMPORARY_REF, "push event ref")
    require(
        event.get("repository", {}).get("full_name") == REPOSITORY,
        "push event repository",
    )
    return {
        "deleted": False,
        "after": expected_head,
        "ref": TEMPORARY_REF,
        "repository": REPOSITORY,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--phase", required=True, choices=("current", "history"))
    parser.add_argument("--current-capsule", type=Path)
    args = parser.parse_args()
    require(OID.fullmatch(args.expected_head), "expected head syntax")
    require(os.environ.get("GITHUB_REPOSITORY") == REPOSITORY, "workflow repository")
    require(os.environ.get("GITHUB_EVENT_NAME") == "push", "workflow event")
    require(os.environ.get("GITHUB_REF") == TEMPORARY_REF, "workflow branch")
    output = args.output.resolve()
    require(not output.exists(), "output must be a new owned directory")
    output.mkdir(parents=True)
    started = time.time()
    try:
        write_json(
            output / "push-event-identity.json", verify_push_event(args.expected_head)
        )
        snapshot_path = Path(__file__).with_name("hepta_source_bundle_refs.json.gz")
        snapshot = validate_snapshot(snapshot_path)
        shutil.copyfile(snapshot_path, output / snapshot_path.name)
        git = Git(Path.cwd(), output, os.environ.get("BROKER_GITHUB_TOKEN", ""))
        result = export_capsule(
            git,
            output,
            snapshot,
            args.expected_head,
            BASE_ANCHOR,
            args.phase,
            args.current_capsule,
        )
        status = (
            0
            if args.phase == "current" or result["ordinary_tip_source_policy_complete"]
            else 2
        )
    except Exception as error:
        write_json(
            output / "failure.json",
            {
                "error_type": type(error).__name__,
                "message": str(error),
                "elapsed_seconds": time.time() - started,
                "partial_files_are_not_a_complete_bundle": True,
            },
        )
        status = 1
    artifact_inventory(output, status, started)
    return status


if __name__ == "__main__":
    sys.exit(main())
