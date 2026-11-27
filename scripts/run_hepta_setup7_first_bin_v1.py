#!/usr/bin/env python3
"""First and only native observation of the seven new setup binary controls.

This module is loaded from one workflow-hashed byte buffer. It performs no native
command until Root admission, original PR/run identity and full source custody
are established. A result is provisional until original whole-job/upload review.
"""

import ctypes
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import struct
import sys
import time
import types
import urllib.error
import urllib.parse
import urllib.request

REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
PARENT_HEAD = "1b2ae899a8956ee96201956bced828f0824ea5f3"
PARENT_TREE = "4944b2a7d5b8ef27f0f0b5c76a717b9127268493"
BASE_BRANCH = "fix/hepta-setup-acl-ready-fail-closed-20261127-7c9e"
HEAD_BRANCH = "fix/hepta-setup7-first-bin-controls-20261127-7c9e"
WORKFLOW = ".github/workflows/hepta-setup7-first-bin-v1.yml"
NEW_PATHS = (
    "scripts/hepta_setup7_windows_owner_v1.py",
    "scripts/hepta_setup7_collector_v1.py",
    "scripts/run_hepta_setup7_first_bin_v1.py",
    "scripts/hepta_setup7_first_bin_inputs_v1.json",
    WORKFLOW,
)
PHASES = (
    "01-metadata",
    "02-cold-single-bin",
    "03-exact-seven-list",
    "04-exact-seven-run",
)
PHASE_CAPS = (60, 800, 60, 80)
LINK_PATH = "codex-rs/vendor/bubblewrap/LICENSE"
LINK_BLOB = "d24842f3cdcf2e447f9a7a26fa387ad63f5c4b91"
SOURCE_LIMIT = 768 * 1024 * 1024
FILE_LIMIT = 256 * 1024 * 1024


def need(value, message):
    if not value:
        raise RuntimeError(message)


def duplicate_free(pairs):
    value = {}
    for key, item in pairs:
        need(key not in value, "duplicate JSON key: " + key)
        value[key] = item
    return value


def parse(raw):
    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=duplicate_free,
        parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
    )


def digest(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(
            b"blob " + str(len(raw)).encode() + b"\0" + raw
        ).hexdigest(),
    }


def durable(path, raw):
    with open(path, "xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {**digest(raw), "path": str(path)}


def json_file(path, value):
    return durable(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def read_bound(path, limit):
    with open(path, "rb") as stream:
        raw = stream.read(limit + 1)
    need(len(raw) <= limit, "original file byte bound: " + str(path))
    return raw


def source_module(name, path, expected):
    raw = read_bound(path, 128 * 1024)
    need(digest(raw)["sha256"] == expected, "source loader hash mismatch: " + str(path))
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    sys.modules[name] = module
    try:
        exec(compile(raw, str(path), "exec"), module.__dict__)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module, raw


def utc(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def tree_map(value):
    need(value.get("truncated") is False, "truncated original Git tree")
    entries = value.get("tree")
    need(isinstance(entries, list) and len(entries) < 40000, "Git tree entry bound")
    leaves, directories, seen = {}, {}, set()
    for entry in entries:
        path = entry["path"]
        need(
            isinstance(path, str)
            and path
            and "\\" not in path
            and not path.startswith("/")
            and all(p not in ("", ".", "..") for p in path.split("/")),
            "unsafe original Git path",
        )
        need(path not in seen, "duplicate Git tree path")
        seen.add(path)
        if entry["type"] == "tree":
            directories[path] = entry["sha"]
        else:
            need(
                entry["type"] == "blob"
                and entry["mode"] in ("100644", "100755", "120000"),
                "submodule or unsupported tree leaf",
            )
            need(
                isinstance(entry.get("size"), int) and 0 <= entry["size"] <= FILE_LIMIT,
                "Git blob size bound",
            )
            need(re.fullmatch("[0-9a-f]{40}", entry["sha"]), "Git blob identity")
            leaves[path] = {
                "mode": entry["mode"],
                "git_blob": entry["sha"],
                "bytes": entry["size"],
            }
    need(
        len({p.casefold() for p in leaves}) == len(leaves),
        "Windows case-colliding tracked paths",
    )
    need(
        sum(v["bytes"] for v in leaves.values()) <= SOURCE_LIMIT,
        "full source byte bound",
    )
    # Reconstruct native Git trees from all leaves, then check every API tree.
    nested = {}
    for path, entry in leaves.items():
        pieces = path.split("/")
        node = nested
        for piece in pieces[:-1]:
            child = node.setdefault(piece, {})
            need(isinstance(child, dict), "file/directory prefix collision")
            node = child
        need(pieces[-1] not in node, "Git leaf collision")
        node[pieces[-1]] = (entry["mode"], entry["git_blob"])

    def merkle(node, prefix):
        items = []
        for name, child in node.items():
            if isinstance(child, dict):
                sha = merkle(child, prefix + name + "/")
                items.append((name.encode("utf-8") + b"/", "40000", name, sha))
            else:
                mode, sha = child
                items.append((name.encode("utf-8"), mode, name, sha))
        data = b"".join(
            mode.encode() + b" " + name.encode("utf-8") + b"\0" + bytes.fromhex(sha)
            for _, mode, name, sha in sorted(items)
        )
        sha = hashlib.sha1(
            b"tree " + str(len(data)).encode() + b"\0" + data
        ).hexdigest()
        if prefix:
            need(
                directories.get(prefix[:-1]) == sha,
                "API subtree Merkle mismatch: " + prefix,
            )
        return sha

    need(merkle(nested, "") == value["sha"], "full source tree Merkle mismatch")
    return leaves


class Api:
    def __init__(self, output, token, deadline):
        self.output = output
        self.token = token
        self.deadline = deadline
        self.reads = []

    def get(self, suffix, label):
        need(
            suffix not in [item["suffix"] for item in self.reads],
            "duplicate original API read",
        )
        need(time.monotonic() < self.deadline, "original preparation deadline")
        need(re.fullmatch("[A-Za-z0-9_.-]+", label), "unsafe API observation label")
        request_url = "https://api.github.com/repos/" + REPOSITORY + "/" + suffix
        row = {
            "suffix": suffix,
            "label": label,
            "attempts": 1,
            "status": "UNKNOWN",
            "request_url": request_url,
            "received_bytes": 0,
            "retained_bytes": 0,
            "body_complete": False,
            "body_truncated": False,
            "retention_errors": [],
        }
        self.reads.append(row)
        request = urllib.request.Request(
            request_url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": "Bearer " + self.token,
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "hepta-setup7-original-read-v1",
            },
        )
        chunks = []
        original_error = None

        def capture_headers(response):
            # Preserve the original status and available headers before any body IO.
            row["status"] = response.getcode()
            row["response_url"] = response.geturl()
            row["headers"] = {
                key: response.headers.get(key)
                for key in ("Date", "ETag", "X-GitHub-Request-Id", "Link")
            }

        def keep_delivered(block, limit):
            row["received_bytes"] += len(block)
            remaining = max(0, limit - row["retained_bytes"])
            kept = block[:remaining]
            if kept:
                chunks.append(kept)
                row["retained_bytes"] += len(kept)
            overflow = block[len(kept) :]
            if overflow:
                row["body_truncated"] = True
                row["unretained_overflow_bytes"] = (
                    row["received_bytes"] - row["retained_bytes"]
                )
                # Normal reads request at most one byte beyond the original cap.
                # Keep that probe, without presenting it as a complete body.
                row["overflow_probe_hex"] = overflow[:1].hex()
                row["overflow_block_sha256"] = hashlib.sha256(overflow).hexdigest()

        def read_body(response, limit):
            row["body_limit_bytes"] = limit
            while True:
                need(time.monotonic() < self.deadline, "original API read deadline")
                wanted = min(65536, limit - row["retained_bytes"] + 1)
                try:
                    block = response.read(wanted)
                except BaseException as read_error:
                    row["body_read_error"] = repr(read_error)
                    partial = getattr(read_error, "partial", None)
                    if isinstance(partial, bytes) and partial:
                        keep_delivered(partial, limit)
                    raise
                if not block:
                    row["body_complete"] = True
                    return b"".join(chunks)
                keep_delivered(block, limit)
                need(not row["body_truncated"], "original API response byte bound")

        try:
            with urllib.request.urlopen(
                request, timeout=max(0.1, min(10, self.deadline - time.monotonic()))
            ) as response:
                capture_headers(response)
                need(row["status"] == 200, "original GitHub GET was not 200")
                need(
                    row["response_url"].startswith(
                        "https://api.github.com/repos/" + REPOSITORY + "/"
                    ),
                    "API redirect outside the bound repository",
                )
                raw = read_body(response, 12 * 1024 * 1024)
                need(
                    not response.headers.get("Link"),
                    "unconsumed original API pagination",
                )
            row["raw"] = durable(self.output / (label + ".raw.json"), raw)
            # Raw original is durable before interpretation.
            return parse(raw)
        except BaseException as error:
            original_error = error
            row["error"] = repr(error)
            if isinstance(error, urllib.error.HTTPError):
                try:
                    with error:
                        capture_headers(error)
                        read_body(error, 1024 * 1024)
                except BaseException as body_error:
                    row["http_error_body_error"] = repr(body_error)
                row["error_body_truncated"] = row["body_truncated"]
            if "raw" not in row:
                try:
                    row["raw"] = durable(
                        self.output / (label + ".partial.raw"), b"".join(chunks)
                    )
                except BaseException as retention_error:
                    row["retention_errors"].append("body: " + repr(retention_error))
            raise
        finally:
            try:
                json_file(self.output / (label + ".read.json"), row)
            except BaseException as retention_error:
                row["retention_errors"].append("read record: " + repr(retention_error))
                # The live row is also attached to the main RESULT. Do not replace
                # the original request/read exception with its retention failure.
                if original_error is None:
                    raise


def enumerate_files(root, allowed_generated=()):
    result = set()
    for parent, dirs, files in os.walk(root, topdown=True, followlinks=False):
        parent_path = Path(parent)
        if parent_path == root and ".git" in dirs:
            dirs.remove(".git")
        for name in dirs:
            path = parent_path / name
            need(
                not path.is_symlink() and not path.is_junction(),
                "untracked reparse directory",
            )
        for name in files:
            path = parent_path / name
            relative = path.relative_to(root).as_posix()
            if relative not in allowed_generated:
                result.add(relative)
    return result


def main():
    result = {
        "schema": "hepta-setup7-first-native-observation-v1",
        "status": "FAIL_OR_UNKNOWN",
        "native_observation_pass": False,
        "whole_job_acceptance": "PENDING_ORIGINAL_PLATFORM_AND_UPLOAD_REVIEW",
        "frozen_scope": {
            "E2_parameter_updates_consumed": "two students, 8 + 8 = 16 / 16",
            "E6_seconds_remaining_unchanged": 1.9960488015785813,
            "budget_transferred": 0,
            "old_windows167_invocations": 0,
            "global_frozen_roster_complete_claim": False,
        },
        "commands": [],
        "phase_attempts": [],
        "errors": [],
        "unlaunched_phases": list(PHASES),
        "hermetic_reuse_authorized": False,
        "production_acl_account_firewall_qualification": False,
    }
    output = None
    owner = None
    api_native = None
    cancellation = None
    held = []
    source_files = []
    source_before = []
    tool_files = []
    tool_before = []
    generated_files = []
    prepared = False
    final_io_pass = False
    operation_deadline = None
    cleanup_deadline = None
    finish_deadline = None
    start = time.monotonic()
    repo = Path(os.environ.get("GITHUB_WORKSPACE", "")).absolute()
    try:
        run_id = os.environ.get("GITHUB_RUN_ID", "")
        need(re.fullmatch("[1-9][0-9]*", run_id), "original workflow run ID")
        output = Path(os.environ["RUNNER_TEMP"]).absolute() / ("hepta-setup7-" + run_id)
        need(
            output.is_dir(),
            "first workflow step must own the fresh observation directory",
        )
        need(
            set(p.name for p in output.iterdir()) == {"BOOTSTRAP.json"},
            "observation directory is not fresh",
        )
        boot_raw = read_bound(output / "BOOTSTRAP.json", 16384)
        boot = parse(boot_raw)
        if sys.platform == "win32":
            clock_kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            clock_kernel.GetTickCount64.restype = ctypes.c_uint64
            clock_kernel.GetTickCount64.argtypes = []
            current_tick = int(clock_kernel.GetTickCount64())
            need(
                isinstance(boot.get("tick_count_ms"), int)
                and 0 <= boot["tick_count_ms"] <= current_tick,
                "original bootstrap cost clock",
            )
            start = time.monotonic() - (current_tick - boot["tick_count_ms"]) / 1000
            operation_deadline, cleanup_deadline, finish_deadline = (
                start + 1000,
                start + 1140,
                start + 1200,
            )
        need(
            boot["run_id"] == run_id and boot["run_attempt"] == "1",
            "original bootstrap identity",
        )
        input_raw = read_bound(repo / NEW_PATHS[3], 65536)
        need(
            digest(input_raw)["sha256"] == os.environ.get("HEPTA_SETUP7_INPUT_SHA256"),
            "workflow/input byte identity",
        )
        config = parse(input_raw)
        result["input"] = durable(output / "INPUT.original.json", input_raw)
        need(config["schema"] == "hepta.setup7.first_native_input.v1", "input schema")
        need(
            config["root_execution_authorized"] is True
            and config["root_budget_accepted"] is True
            and config["root_first_native_clearance"] is True,
            "Root first-native admission is inactive",
        )
        need(
            config["parent"] == {"head": PARENT_HEAD, "tree": PARENT_TREE},
            "actual7164 parent binding",
        )
        need(
            config["scope_id"] == "hepta-setup7-first-bin-20261127-7c9e",
            "frozen new scope identity",
        )
        for key in (
            "root_admission_sha256",
            "first_native_clearance_sha256",
            "root_source_review_sha256",
        ):
            need(
                re.fullmatch("[0-9a-f]{64}", config.get(key) or ""),
                "missing original Root receipt: " + key,
            )
        need(
            config["budget"]
            == {
                "whole_seconds": 1200,
                "work_seconds": 1000,
                "retention_seconds": 200,
                "platform_upload_reserve_seconds": 60,
                "phase_seconds": [60, 800, 60, 80],
            },
            "original independent budget changed",
        )
        need(
            config["tool_capture_policy"]
            == "root-approved-first-observation-no-hermetic-reuse",
            "unapproved mutable runner tool policy",
        )
        need(
            config["exact_tests"] and len(config["exact_tests"]) == 7,
            "input exact-seven roster",
        )
        need(
            sys.platform == "win32" and sys.version_info >= (3, 12),
            "native Windows Python 3.12+",
        )
        owner, owner_raw = source_module(
            "hepta_setup7_windows_owner_v1",
            repo / NEW_PATHS[0],
            config["source_sha256"][NEW_PATHS[0]],
        )
        collector, collector_raw = source_module(
            "hepta_setup7_collector_v1",
            repo / NEW_PATHS[1],
            config["source_sha256"][NEW_PATHS[1]],
        )
        need(
            list(collector.TESTS) == config["exact_tests"],
            "collector/input roster drift",
        )
        api_native = owner.NativeWindows()
        now_ticks = int(api_native.GetTickCount64())
        need(
            isinstance(boot["tick_count_ms"], int)
            and 0 <= boot["tick_count_ms"] <= now_ticks,
            "original cross-process monotonic clock",
        )
        start = time.monotonic() - (now_ticks - boot["tick_count_ms"]) / 1000
        operation_deadline, cleanup_deadline, finish_deadline = (
            start + 1000,
            start + 1140,
            start + 1200,
        )
        need(
            time.monotonic() < operation_deadline,
            "setup already exhausted original work budget",
        )
        api_dir = output / "original-api"
        api_dir.mkdir()
        reader = Api(api_dir, os.environ["GH_TOKEN"], operation_deadline)
        result["original_api_reads"] = reader.reads
        event_raw = read_bound(Path(os.environ["GITHUB_EVENT_PATH"]), 2 * 1024 * 1024)
        result["original_event"] = durable(output / "ORIGINAL_EVENT.json", event_raw)
        event = parse(event_raw)
        need(
            os.environ.get("GITHUB_EVENT_NAME") == "pull_request"
            and event.get("action") == "opened",
            "only the original opened event is admitted",
        )
        need(
            os.environ.get("GITHUB_REPOSITORY") == REPOSITORY
            and os.environ.get("GITHUB_RUN_ATTEMPT") == "1",
            "repository/attempt changed",
        )
        pr = event["pull_request"]
        need(
            pr["head"]["repo"]["full_name"]
            == REPOSITORY
            == pr["base"]["repo"]["full_name"],
            "foreign repository",
        )
        need(
            pr["head"]["ref"] == HEAD_BRANCH and pr["base"]["ref"] == BASE_BRANCH,
            "original fixed branch pair",
        )
        need(
            pr["base"]["sha"] == PARENT_HEAD
            and pr["user"]["login"] == "ProfHepta"
            and event["sender"]["login"] == "ProfHepta",
            "Root source event identity",
        )
        head = pr["head"]["sha"]
        need(re.fullmatch("[0-9a-f]{40}", head), "real source head")
        result["source_head"] = head
        result["pr_number"] = pr["number"]
        original_run = reader.get("actions/runs/" + run_id, "01-original-run")
        need(
            original_run["run_attempt"] == 1
            and original_run["head_sha"] == head
            and original_run["event"] == "pull_request"
            and original_run["path"] == WORKFLOW,
            "original workflow run identity",
        )
        jobs = reader.get(
            "actions/runs/" + run_id + "/attempts/1/jobs?per_page=100",
            "02-original-jobs",
        )
        need(
            jobs["total_count"] == len(jobs["jobs"]) == 1, "original single native job"
        )
        job = jobs["jobs"][0]
        need(
            job["name"] == "first-seven-native"
            and job["run_id"] == int(run_id)
            and job["status"] == "in_progress",
            "original job envelope",
        )
        pre_boot = (utc(boot["utc"]) - utc(job["started_at"])).total_seconds()
        need(pre_boot >= -2, "UTC/monotonic original job clock disagreement")
        # Charge runner/setup time before the first script as well as all actions.
        start -= max(0, pre_boot)
        operation_deadline, cleanup_deadline, finish_deadline = (
            start + 1000,
            start + 1140,
            start + 1200,
        )
        reader.deadline = operation_deadline
        result["clock"] = {
            "job_started_at": job["started_at"],
            "bootstrap": boot,
            "pre_first_step_seconds": max(0, pre_boot),
            "original_start_monotonic": start,
            "work_deadline": operation_deadline,
            "cleanup_deadline": cleanup_deadline,
            "whole_deadline": finish_deadline,
            "final_platform_envelope_required": True,
        }
        pulls = reader.get(
            "pulls?state=all&head="
            + urllib.parse.quote("TrillionniumFoundation:" + HEAD_BRANCH, safe="")
            + "&per_page=100",
            "03-original-branch-prs",
        )
        need(
            isinstance(pulls, list)
            and len(pulls) == 1
            and pulls[0]["number"] == pr["number"],
            "this fixed scope branch has a competing/reopened PR",
        )
        need(
            pulls[0]["head"]["sha"] == head
            and pulls[0]["created_at"] == pr["created_at"],
            "original first PR identity changed",
        )
        runs = reader.get(
            "actions/runs?head_sha=" + head + "&per_page=100", "04-original-head-runs"
        )
        need(
            runs["total_count"] == len(runs["workflow_runs"]) < 100,
            "complete head run directory",
        )
        scope_runs = [r for r in runs["workflow_runs"] if r["path"] == WORKFLOW]
        need(
            len(scope_runs) == 1
            and scope_runs[0]["id"] == int(run_id)
            and scope_runs[0]["run_attempt"] == 1,
            "same-head/same-scope replay is refused",
        )
        commit = reader.get("git/commits/" + head, "05-original-source-commit")
        need(
            [p["sha"] for p in commit["parents"]] == [PARENT_HEAD], "source sole parent"
        )
        original_parent = reader.get(
            "git/trees/" + PARENT_TREE + "?recursive=1", "06-original-parent-tree"
        )
        original_current = reader.get(
            "git/trees/" + commit["tree"]["sha"] + "?recursive=1",
            "07-original-source-tree",
        )
        need(
            original_parent["sha"] == PARENT_TREE
            and original_current["sha"] == commit["tree"]["sha"],
            "API/source tree identity",
        )
        parent, current = tree_map(original_parent), tree_map(original_current)
        need(
            len(parent) == 16147
            and sum(x["bytes"] for x in parent.values()) == 335617461,
            "actual7164 complete parent inventory",
        )
        need(
            {p for p in parent if parent[p]["mode"] == "120000"} == {LINK_PATH}
            and parent[LINK_PATH]
            == {"mode": "120000", "git_blob": LINK_BLOB, "bytes": 7},
            "original symlink inventory",
        )
        changed = {
            p for p in set(parent) | set(current) if parent.get(p) != current.get(p)
        }
        need(
            changed == set(NEW_PATHS) and not set(NEW_PATHS) & set(parent),
            "candidate must add exactly five new source paths",
        )
        need(all(current[p]["mode"] == "100644" for p in NEW_PATHS), "new source modes")
        need(len(current) == 16152, "full current source leaf count")
        attrs = {
            p: value
            for p, value in current.items()
            if PurePosixPath(p).name == ".gitattributes"
        }
        need(
            set(attrs) == set(config["attributes_sha256"]),
            "complete applicable Git attributes",
        )
        need(
            not (repo / ".git/info/attributes").exists(),
            "untracked Git attribute injection",
        )
        need(
            enumerate_files(repo) == set(current),
            "untracked, missing or alternate source inputs",
        )
        directories = {repo}
        for path in current:
            node = (repo / path).parent
            while node != repo:
                directories.add(node)
                node = node.parent
        for path in sorted(directories, key=lambda item: (len(item.parts), str(item))):
            need(
                time.monotonic() < operation_deadline,
                "source custody preparation deadline",
            )
            held.append(owner.PinnedFile(api_native, path, 0, directory=True))
        for path, entry in sorted(current.items()):
            need(
                time.monotonic() < operation_deadline,
                "source custody byte audit deadline",
            )
            pin = owner.PinnedFile(api_native, repo / path, FILE_LIMIT)
            held.append(pin)
            source_files.append((path, pin))
            info, raw = pin.read(
                keep_bytes=path in NEW_PATHS or path == LINK_PATH,
                deadline=operation_deadline,
            )
            need(
                info["bytes"] == entry["bytes"]
                and info["git_blob"] == entry["git_blob"],
                "physical source/Git byte mismatch: " + path,
            )
            info = {**info, "repo_path": path, "git_mode": entry["mode"]}
            source_before.append(info)
            if path in config["source_sha256"]:
                need(
                    info["sha256"] == config["source_sha256"][path],
                    "approved source pin: " + path,
                )
            if path in config["attributes_sha256"]:
                need(
                    info["sha256"] == config["attributes_sha256"][path],
                    "attribute byte identity: " + path,
                )
            if path == LINK_PATH:
                need(raw == b"COPYING", "original Windows symlink text materialization")
            if path in NEW_PATHS:
                durable(
                    output / ("source-" + str(NEW_PATHS.index(path)) + ".original"), raw
                )
        need(
            dict((p, f.before["sha256"]) for p, f in source_files)[NEW_PATHS[3]]
            == digest(input_raw)["sha256"],
            "input changed between bootstrap and held source custody",
        )
        result["source_before"] = json_file(
            output / "SOURCE_BEFORE.json", source_before
        )
        result["source_tree"] = commit["tree"]["sha"]
        result["source_changes"] = sorted(changed)
        # The API commit is not a substitute for the physical checkout HEAD.
        # Retain original Git metadata while build scripts may read it.
        git_directory = repo / ".git"
        held.append(owner.PinnedFile(api_native, git_directory, 0, directory=True))
        git_metadata = []
        for name in ("HEAD", "config", "index", "shallow", "packed-refs"):
            path = git_directory / name
            if not path.exists():
                need(
                    name not in ("HEAD", "config", "index"),
                    "required local Git metadata missing",
                )
                git_metadata.append({"path": str(path), "exists": False})
                continue
            pin = owner.PinnedFile(api_native, path, FILE_LIMIT)
            held.append(pin)
            generated_files.append(pin)
            info, raw = pin.read(keep_bytes=name == "HEAD", deadline=operation_deadline)
            if name == "HEAD":
                need(
                    raw == (head + "\n").encode("ascii"),
                    "physical detached HEAD differs from original event",
                )
            git_metadata.append({**info, "exists": True})
        need(
            not (git_directory / "objects/info/alternates").exists(),
            "unapproved alternate Git object store",
        )
        result["local_git_before"] = json_file(
            output / "SOURCE_LOCAL_GIT_BEFORE.json", git_metadata
        )
        result["symlink_mode_materialized_text"] = {
            "path": LINK_PATH,
            "bytes": 7,
            "git_blob": LINK_BLOB,
        }
        result["tool_setup_steps"] = [
            s
            for s in job["steps"]
            if s["number"]
            < next(
                s["number"]
                for s in job["steps"]
                if s["name"] == "Observe the first seven native controls"
            )
        ]
        need(
            all(step["conclusion"] == "success" for step in result["tool_setup_steps"]),
            "original provisioning steps did not finish successfully",
        )
        # Original runner tools are captured, not asserted hermetic or reusable.
        rustup = Path(os.environ["RUSTUP_HOME"]).absolute()
        cargo_home = Path(os.environ["CARGO_HOME"]).absolute()
        toolchain = rustup / "toolchains/1.96.0-x86_64-pc-windows-msvc/bin"
        tools = {
            "cargo": toolchain / "cargo.exe",
            "rustc": toolchain / "rustc.exe",
            "nextest": cargo_home / "bin/cargo-nextest.exe",
            "python": Path(sys.executable),
        }
        tool_directories = set()
        for path in tools.values():
            for parent_directory in path.absolute().parents:
                if parent_directory != Path(parent_directory.anchor):
                    tool_directories.add(parent_directory)
        for path in sorted(
            tool_directories, key=lambda item: (len(item.parts), str(item))
        ):
            held.append(owner.PinnedFile(api_native, path, 0, directory=True))
        for name, path in tools.items():
            pin = owner.PinnedFile(api_native, path, FILE_LIMIT)
            held.append(pin)
            tool_files.append((name, pin))
            info, _ = pin.read(deadline=operation_deadline)
            tool_before.append({"tool": name, **info})
        result["tools_before"] = json_file(output / "TOOLS_BEFORE.json", tool_before)
        result["runtime"] = {
            "python": sys.version,
            "executable": sys.executable,
            "os_version": list(sys.getwindowsversion()),
            "image_os": os.environ.get("ImageOS"),
            "image_version": os.environ.get("ImageVersion"),
            "runner_arch": os.environ.get("RUNNER_ARCH"),
            "rust_toolchain_requested": "1.96.0",
            "nextest_requested": "0.9.103",
            "provisioned_tool_reuse": False,
        }
        for external in (cargo_home / "config", cargo_home / "config.toml"):
            need(not external.exists(), "unapproved external Cargo config")
        target = output / "cold-target"
        target.mkdir(exist_ok=False)
        output_directories = [target, output]
        parent_directory = output.parent
        while parent_directory != Path(parent_directory.anchor):
            output_directories.append(parent_directory)
            parent_directory = parent_directory.parent
        for path in reversed(output_directories):
            held.append(owner.PinnedFile(api_native, path, 0, directory=True))
        (output / "commands").mkdir()
        junit_path = repo / "codex-rs/target/nextest/local/junit.xml"
        need(
            not (repo / "codex-rs/target").exists(),
            "cold workspace has a previous target or JUnit store",
        )
        child_env = dict(os.environ)
        for key in list(child_env):
            upper = key.upper()
            if upper.startswith(
                ("NEXTEST_", "CARGO_", "RUST", "GIT_", "PYTHON")
            ) or upper in ("GH_TOKEN", "GITHUB_TOKEN", "LD_PRELOAD", "LD_LIBRARY_PATH"):
                del child_env[key]
        child_env.update(
            {
                "CARGO_HOME": str(cargo_home),
                "RUSTUP_HOME": str(rustup),
                "RUSTUP_TOOLCHAIN": "1.96.0-x86_64-pc-windows-msvc",
                "CARGO": str(tools["cargo"]),
                "RUSTC": str(tools["rustc"]),
                "CARGO_TARGET_DIR": str(target),
                "CARGO_BUILD_JOBS": "1",
                "CARGO_INCREMENTAL": "0",
                "CARGO_TERM_COLOR": "never",
                "NEXTEST_PROFILE": "local",
                "RUST_MIN_STACK": "8388608",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_ATTR_NOSYSTEM": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        need(child_env.get("RUNNER_ARCH") == "X64", "native x64 runner required")
        result["child_environment"] = {
            key: value
            for key, value in child_env.items()
            if key.startswith(("CARGO", "RUST", "NEXTEST", "GIT_", "PYTHON"))
            or key in ("PATH", "PATHEXT", "SystemRoot", "TEMP", "TMP")
        }
        result["dependency_materialization"] = (
            "Original locked resolution and fresh compiled target; registry bytes may be fetched once and costs are charged."
        )
        cancellation = owner.Cancellation(api_native)
        cancellation.__enter__()
        workspace = repo / "codex-rs"
        meta_path = output / "cargo-metadata.windows.json"
        binary_path = output / "binaries-metadata.windows.json"
        phase_rows = []

        def invoke(index, argv):
            cancellation.check()
            need(index == len(phase_rows), "phase order or repeated phase")
            now = time.monotonic()
            need(now < operation_deadline, "original shared work budget exhausted")
            for external in (cargo_home / "config", cargo_home / "config.toml"):
                need(not external.exists(), "external Cargo configuration appeared")
            need(
                not (repo / ".git/info/attributes").exists()
                and not (repo / ".git/objects/info/alternates").exists(),
                "external Git attributes/object store appeared",
            )
            phase_deadline = min(operation_deadline, now + PHASE_CAPS[index])
            result["unlaunched_phases"].remove(PHASES[index])
            attempt = {
                "phase": PHASES[index],
                "argv": argv,
                "max_attempts": 1,
                "started_monotonic": now,
                "operation_deadline": phase_deadline,
                "owner_returned": False,
                "launch_state": "UNKNOWN_UNTIL_ORIGINAL_OWNER_RETURN",
            }
            result["phase_attempts"].append(attempt)
            json_file(output / (PHASES[index] + ".ORIGINAL_ATTEMPT.json"), attempt)
            row = owner.run_owned(
                api_native,
                cancellation,
                argv,
                workspace,
                child_env,
                output / "commands" / PHASES[index],
                operation_deadline=phase_deadline,
                cleanup_deadline=cleanup_deadline,
                limits=config["owner_limits"],
            )
            phase_rows.append(row)
            result["commands"].append(row)
            attempt["owner_returned"] = True
            attempt["launch_state"] = {
                "created": row["created"],
                "launch_attempts": row["launch_attempts"],
            }
            attempt["original_receipt"] = row["receipt_path"]
            after_owner_io = time.monotonic()
            attempt["owner_returned_monotonic"] = after_owner_io
            attempt["seconds_including_owner_receipt_io"] = after_owner_io - now
            attempt["within_original_phase_ceiling"] = after_owner_io <= phase_deadline
            need(
                attempt["within_original_phase_ceiling"],
                "owner receipt IO exceeded the original phase ceiling",
            )
            collector.command_terminal(row)
            cancellation.check()
            need(
                time.monotonic() < operation_deadline,
                "phase and diagnostics exhausted shared work budget",
            )
            return row

        def retain_stdout(row, destination):
            raw = read_bound(
                row["stdout"]["path"], config["owner_limits"]["stream_bytes"]
            )
            need(
                digest(raw)["sha256"] == row["stdout"]["sha256"],
                "owned stdout source mismatch",
            )
            durable(destination, raw)
            pin = owner.PinnedFile(api_native, destination, FILE_LIMIT)
            held.append(pin)
            generated_files.append(pin)
            info, same = pin.read(keep_bytes=True, deadline=operation_deadline)
            need(same == raw, "generated metadata publication changed")
            return raw

        prepared = True
        row = invoke(
            0, [str(tools["cargo"]), "metadata", "--locked", "--format-version", "1"]
        )
        metadata_raw = retain_stdout(row, meta_path)
        full_metadata, package = collector.metadata(metadata_raw, workspace, target)
        need(
            full_metadata.get("resolve") is not None,
            "complete original dependency resolve graph required",
        )
        nextest = [
            str(tools["nextest"]),
            "nextest",
            "--color",
            "never",
            "--config-file",
            str(workspace / ".config/nextest.toml"),
        ]
        row = invoke(
            1,
            nextest
            + [
                "list",
                "--cargo-metadata",
                str(meta_path),
                "--locked",
                "--target",
                "x86_64-pc-windows-msvc",
                "--target-dir",
                str(target),
                "--cargo-profile",
                "dev-small",
                "-p",
                collector.PACKAGE,
                "--bin",
                collector.TARGET,
                "--list-type",
                "binaries-only",
                "--message-format",
                "json",
            ],
        )
        binary_raw = retain_stdout(row, binary_path)
        binary_list, binary = collector.binaries(binary_raw, package, target)
        harness_parent = Path(binary["binary-path"]).parent
        harness_directories = []
        while harness_parent != output.parent:
            harness_directories.append(harness_parent)
            harness_parent = harness_parent.parent
        for path in reversed(harness_directories):
            held.append(owner.PinnedFile(api_native, path, 0, directory=True))
        harness = owner.PinnedFile(api_native, binary["binary-path"], FILE_LIMIT)
        held.append(harness)
        generated_files.append(harness)
        binary_info, binary_bytes = harness.read(
            keep_bytes=True, deadline=operation_deadline
        )
        need(
            binary_bytes[:2] == b"MZ" and len(binary_bytes) >= 64,
            "original native PE harness",
        )
        offset = struct.unpack_from("<I", binary_bytes, 60)[0]
        need(
            offset + 6 <= len(binary_bytes)
            and binary_bytes[offset : offset + 4] == b"PE\0\0"
            and struct.unpack_from("<H", binary_bytes, offset + 4)[0] == 0x8664,
            "x64 PE harness identity",
        )
        del binary_bytes
        result["cold_harness_before"] = binary_info
        reuse = [
            "--cargo-metadata",
            str(meta_path),
            "--binaries-metadata",
            str(binary_path),
        ]
        row = invoke(
            2,
            nextest
            + [
                "list",
                *reuse,
                "--list-type",
                "full",
                "--message-format",
                "json",
                "-E",
                collector.FILTER,
            ],
        )
        list_raw = retain_stdout(row, output / "full-list.windows.json")
        result["inventory"] = collector.listed(
            list_raw, binary_list, package, workspace
        )
        need(not junit_path.exists(), "JUnit must be absent before the first test body")
        row = invoke(
            3,
            nextest
            + [
                "run",
                *reuse,
                "--test-threads",
                "1",
                "--retries",
                "0",
                "--no-tests",
                "fail",
                "--no-fail-fast",
                "--status-level",
                "pass",
                "--final-status-level",
                "fail",
                "--hide-progress-bar",
                "--no-input-handler",
                "-E",
                collector.FILTER,
            ],
        )
        stdout = read_bound(
            row["stdout"]["path"], config["owner_limits"]["stream_bytes"]
        )
        stderr = read_bound(
            row["stderr"]["path"], config["owner_limits"]["stream_bytes"]
        )
        result["log_verification"] = collector.execution_logs(stdout, stderr, row)
        junit_file = owner.PinnedFile(api_native, junit_path, 2 * 1024 * 1024)
        held.append(junit_file)
        generated_files.append(junit_file)
        _, junit_raw = junit_file.read(keep_bytes=True, deadline=operation_deadline)
        result["junit_raw"] = durable(output / "junit.original.xml", junit_raw)
        result["junit"] = collector.junit(junit_raw)
        need(
            len(result["commands"]) == 4 and not result["unlaunched_phases"],
            "four original phases",
        )
        cancellation.check()
        need(
            time.monotonic() < operation_deadline,
            "all work/diagnostics exceeded original1000",
        )
        result["native_observation_pass"] = True
    except BaseException as error:
        result["errors"].append(repr(error))
    finally:
        result["prepared_before_first_native_launch"] = prepared
        if output is not None and output.is_dir():
            # Retention remains charged even on malformed input/bootstrap failure.
            if source_files:
                after = []
                try:
                    for path, pin in source_files:
                        info, _ = pin.read(deadline=cleanup_deadline)
                        after.append({"repo_path": path, **info})
                    result["source_after"] = json_file(
                        output / "SOURCE_AFTER.json", after
                    )
                    result["source_unchanged"] = all(
                        (
                            item["repo_path"],
                            item["sha256"],
                            item["git_blob"],
                            item["bytes"],
                        )
                        == (
                            previous["repo_path"],
                            previous["sha256"],
                            previous["git_blob"],
                            previous["bytes"],
                        )
                        for item, previous in zip(after, source_before)
                    ) and len(after) == len(source_before)
                    allowed = {"codex-rs/target/nextest/local/junit.xml"}
                    expected = {path for path, _ in source_files}
                    result["no_untracked_source_after"] = (
                        enumerate_files(repo, allowed) == expected
                    )
                    need(
                        not (repo / ".git/info/attributes").exists()
                        and not (repo / ".git/objects/info/alternates").exists(),
                        "final Git configuration/object injection",
                    )
                    if "cargo_home" in locals():
                        need(
                            not (cargo_home / "config").exists()
                            and not (cargo_home / "config.toml").exists(),
                            "final external Cargo configuration injection",
                        )
                except BaseException as error:
                    result["source_unchanged"] = False
                    result["errors"].append("final source audit: " + repr(error))
            else:
                result["source_unchanged"] = False
            if tool_files:
                after = []
                try:
                    for name, pin in tool_files:
                        info, _ = pin.read(deadline=cleanup_deadline)
                        after.append({"tool": name, **info})
                    result["tools_after"] = json_file(
                        output / "TOOLS_AFTER.json", after
                    )
                    result["tools_unchanged"] = after == tool_before
                except BaseException as error:
                    result["tools_unchanged"] = False
                    result["errors"].append("final tool audit: " + repr(error))
            else:
                result["tools_unchanged"] = False
            for pin in generated_files:
                try:
                    pin.read(deadline=cleanup_deadline)
                except BaseException as error:
                    result["errors"].append(
                        "generated input/binary drift: " + repr(error)
                    )
            for pin in reversed(held):
                try:
                    pin.close()
                except BaseException as error:
                    result["errors"].append("held source/tool cleanup: " + repr(error))
            if cancellation is not None:
                # This is a standalone observer. Retain the pure-latch handlers
                # through durable RESULT and final stdout; the OS releases them
                # at observer exit. Restoring defaults here would reopen a
                # normal-signal gap before the original result is durable.
                result["cancellation"] = {
                    "count": cancellation.count,
                    "events": cancellation.events,
                    "handlers_retained_through_observer_exit": True,
                    "late_or_forced_platform_termination_requires_original_review": True,
                }
                if cancellation.count:
                    result["errors"].append("scope cancelled")
            result["elapsed_through_final_audit_seconds"] = time.monotonic() - start
            result["source_retention_within_original_reserve"] = (
                cleanup_deadline is not None and time.monotonic() <= cleanup_deadline
            )
            result["native_observation_pass"] = bool(
                result["native_observation_pass"]
                and not result["errors"]
                and result.get("source_unchanged")
                and result.get("tools_unchanged")
                and result.get("no_untracked_source_after")
                and result["source_retention_within_original_reserve"]
            )
            result["status"] = (
                "NATIVE_PASS_PENDING_FINAL_IO_AND_ORIGINAL_WHOLE_JOB_REVIEW"
                if result["native_observation_pass"]
                else "FAIL_OR_UNKNOWN"
            )
            result["original_total_budget_seconds"] = 1200
            result["upload_and_outer_job_not_yet_observed"] = True
            result["retention_clock_basis"] = "before durable RESULT and final stdout"
            result["final_io_acceptance"] = (
                "PENDING_AFTER_IO_RECORD_AND_ACTUAL_OBSERVER_EXIT"
            )
            result_pin = None
            tail_errors = []
            try:
                result_pin = json_file(output / "RESULT.json", result)
            except BaseException as error:
                tail_errors.append("RESULT retention: " + repr(error))
            after_result_io = time.monotonic()
            candidate = bool(
                result["native_observation_pass"]
                and result_pin is not None
                and cleanup_deadline is not None
                and after_result_io <= cleanup_deadline
                and not (cancellation is not None and cancellation.count)
            )
            try:
                print(
                    json.dumps(
                        {
                            "status": "FINAL_IO_PENDING"
                            if candidate
                            else "FAIL_OR_UNKNOWN",
                            "candidate_before_this_stdout": candidate,
                            "elapsed_after_RESULT_io_seconds": after_result_io - start,
                            "this_stdout_and_terminal_record_io_not_yet_observed": True,
                            "tail_errors": tail_errors,
                            "original_native_retention_limit_seconds": 1140,
                            "original_whole_limit_seconds": 1200,
                        }
                    ),
                    flush=True,
                )
            except BaseException as error:
                tail_errors.append("final stdout: " + repr(error))
                candidate = False
            after_stdout_io = time.monotonic()
            candidate = bool(
                candidate
                and not tail_errors
                and cleanup_deadline is not None
                and after_stdout_io <= cleanup_deadline
                and not (cancellation is not None and cancellation.count)
            )
            after_io = {
                "schema": "hepta.setup7.after_result_and_stdout_io.v1",
                "RESULT": result_pin,
                "elapsed_after_RESULT_io_seconds": after_result_io - start,
                "elapsed_after_final_stdout_io_seconds": after_stdout_io - start,
                "candidate_before_this_record_io": candidate,
                "tail_errors": tail_errors,
                "cancellation_count": cancellation.count
                if cancellation is not None
                else None,
                "original_native_retention_limit_seconds": 1140,
                "this_record_io_and_actual_exit_still_require_outer_terminal": True,
                "original_whole_job_and_upload_review_required": True,
            }
            try:
                json_file(output / "AFTER_IO.json", after_io)
                final_io_pass = candidate
            except BaseException as error:
                final_io_pass = False
                try:
                    print(
                        json.dumps(
                            {
                                "fatal_after_io_retention_error": repr(error),
                                "native_pass": False,
                            }
                        ),
                        file=sys.stderr,
                        flush=True,
                    )
                except BaseException:
                    pass
            # No normal output after this actual post-fsync clock. The immutable
            # AFTER_IO record describes its own earlier boundary; the outer
            # bootstrap's original exit/clock remains required for acceptance.
            after_final_io = time.monotonic()
            final_io_pass = bool(
                final_io_pass
                and cleanup_deadline is not None
                and after_final_io <= cleanup_deadline
                and not (cancellation is not None and cancellation.count)
            )
        else:
            print(
                json.dumps({"status": "BOOTSTRAP_FAILURE", "errors": result["errors"]}),
                file=sys.stderr,
                flush=True,
            )
    if cancellation is not None and cancellation.count:
        return 1
    return (
        0
        if (
            final_io_pass
            and cleanup_deadline is not None
            and time.monotonic() <= cleanup_deadline
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
