#!/usr/bin/env python3
"""Snapshot completed local engineering receipts and their hash-bound raw logs.

Input is read-only. Unsigned local execution records are evidence, not authority,
stage qualification, physical resource measurements or complete historical cost.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile
import time


TERMINAL = {"passed", "failed", "rejected", "interrupted"}
MAX_JSON = 1024 * 1024
MAX_FILE = 64 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def nonfinite(_):
        raise ValueError("nonfinite JSON number")

    def decimal(value):
        result = float(value)
        return result if math.isfinite(result) else nonfinite(value)

    return json.loads(data, object_pairs_hook=pairs, parse_constant=nonfinite, parse_float=decimal)


def relative_name(value):
    if not isinstance(value, str) or not value or "\\" in value or any(ord(char) < 32 for char in value):
        raise ValueError("invalid relative evidence path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("evidence path escapes its record root")
    return path.as_posix()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def stamp(metadata):
    return {key: getattr(metadata, key) for key in
            ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")}


class SnapshotReader:
    def __init__(self, root):
        self.root = root
        self.fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def close(self):
        os.close(self.fd)

    def read(self, name, limit=MAX_FILE):
        parts = relative_name(name).split("/")
        parent = os.dup(self.fd)
        try:
            for part in parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=parent)
                os.close(parent)
                parent = child
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
            with os.fdopen(fd, "rb") as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                    raise ValueError("not a bounded regular evidence file")
                data = stream.read(limit + 1)
                after = os.fstat(stream.fileno())
            if stamp(before) != stamp(after) or len(data) != before.st_size:
                raise ValueError("evidence changed during read")
            return {"path": name, "bytes": len(data), "sha256": sha256(data),
                    "stat": stamp(after), "data": data}
        finally:
            os.close(parent)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def number(value):
    try:
        return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None
    except OverflowError:
        return None


def git_sha(value):
    return isinstance(value, str) and len(value) == 40 and all(char in "0123456789abcdef" for char in value)


def clean_claim(identity):
    claims = []
    if "dirty" in identity:
        if type(identity["dirty"]) is not bool:
            return None
        claims.append(not identity["dirty"])
    if "dirty_porcelain" in identity:
        if not isinstance(identity["dirty_porcelain"], str):
            return None
        claims.append(identity["dirty_porcelain"] == "")
    return claims[0] if claims and all(value == claims[0] for value in claims) else None


def instant(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def normalized_source(document, rejected):
    before = document.get("before", document.get("inputs_before"))
    after = document.get("after", document.get("inputs_after"))
    before = before if isinstance(before, dict) else {}
    after = after if isinstance(after, dict) else {}
    commit, tree = before.get("commit"), before.get("tree")
    if not isinstance(commit, str):
        commit = None
    if not isinstance(tree, str):
        tree = None
    head = document.get("head", document.get("source_commit"))
    head = head if isinstance(head, str) else None
    clean = clean_claim(before) is True and clean_claim(after) is True
    shapes = git_sha(commit) and git_sha(tree)
    same = bool(shapes and before == after and clean)
    source, tested = document.get("source_sha"), document.get("tested_sha")
    declared = None
    if "source_sha" in document or "tested_sha" in document:
        declared = git_sha(source) and git_sha(tested) and tested == commit
        if document.get("lane") == "base-merge":
            base, parents = document.get("base_sha"), before.get("parents")
            declared = bool(declared and git_sha(base) and isinstance(parents, list)
                            and len(parents) == 2 and all(git_sha(parent) for parent in parents)
                            and parents == [base, source])
        else:
            declared = bool(declared and source == commit)
    return {
        "declared_source_sha": document.get("source_sha") or None,
        "declared_tested_sha": document.get("tested_sha") or None,
        "observed_commit": commit or head or None,
        "observed_tree": tree,
        "before": before or None, "after": after or None,
        "observed_sha_shapes_valid": shapes,
        "dirty_claims_consistent": clean_claim(before) is not None and clean_claim(after) is not None,
        "declared_to_observed_identity_consistent": declared,
        "identity_before_after_equal_and_clean": same,
        "scope": ("preflight_observation_only" if rejected else
                  "recorded_source_identity" if same and declared is not False else "partial_or_unknown"),
        "source_checkout_reverified_by_collector": False,
        "external_authentication": False,
    }


def adapt(document, name):
    if not isinstance(document, dict):
        return None
    parent = PurePosixPath(name).parent
    kind = document.get("kind")
    if "lane" in document and "source_sha" in document and "command" in document:
        status = document.get("status")
        if status not in TERMINAL or not instant(document.get("finished_at")):
            raise ValueError("execution receipt is not terminal")
        adapter = "hepta_ci_exec"
        log_name = document.get("log_file")
        log_digest = document.get("log_sha256")
        if not log_name and not (status == "rejected" and document.get("command_exit_code") is None):
            raise ValueError("completed dispatched receipt has no bound log")
    elif kind == "source_bound_existing_workflow_execution":
        if document.get("state") != "finished" or type(document.get("workflow_exit_code")) is not int:
            raise ValueError("workflow receipt is not terminal")
        adapter, log_name = "workflow_container", "workflow-console.log"
        log_digest = document.get("console_log_sha256")
        status = "passed" if document["workflow_exit_code"] == 0 else "failed"
    elif kind == "exact_retained_workflow_json_comparison":
        if type(document.get("command_exit_code")) is not int:
            raise ValueError("comparison receipt is not terminal")
        adapter, log_name = "retained_result_comparison", document.get("log_file")
        log_digest = document.get("log_sha256")
        status = "passed" if document["command_exit_code"] == 0 else "failed"
    elif all(key in document for key in ("argv", "cwd", "head", "log_sha256", "finished_utc", "exit_code")):
        if type(document["exit_code"]) is not int or not document["finished_utc"]:
            raise ValueError("legacy execution receipt is not terminal")
        adapter = "legacy_completed_record_with_sibling_log_hash"
        log_name = PurePosixPath(name).with_suffix(".log").name
        log_digest = document["log_sha256"]
        status = "passed" if document["exit_code"] == 0 else "failed"
    elif document.get("scope") == "dependency-resolution-only-uncommitted-integration":
        if type(document.get("exit_code")) is not int or not instant(document.get("finished_at")):
            raise ValueError("dependency resolution receipt is not terminal")
        adapter = "dependency_resolution_uncommitted_input_snapshot"
        log_name, log_digest = document.get("log_file"), document.get("log_sha256")
        status = "passed" if document["exit_code"] == 0 else "failed"
    else:
        return None
    links = []
    if log_name:
        relative_name(log_name)
        if not isinstance(log_digest, str) or len(log_digest) != 64:
            raise ValueError("missing recorded log SHA-256")
        links.append((relative_name(str(parent / log_name)), log_digest))
    if adapter == "retained_result_comparison":
        for field, digest in (("actual_record", "actual_sha256"),):
            links.append((relative_name(str(parent / relative_name(document[field]))), document[digest]))
        links.append((str(parent / "CURRENT_RESULT.original.json"), document["retained_original_sha256"]))
    return adapter, status, links


def activity(document, adapter, status, log):
    command = document.get("command", document.get("argv", []))
    tokens = command if isinstance(command, list) else []
    tests = number(document.get("observed_passed_tests"))
    failures = number(document.get("observed_failed_tests"))
    if status == "rejected":
        phase = "preflight_rejection_no_command_dispatched"
    elif adapter == "workflow_container":
        phase = "workflow_container_not_an_additional_test_run"
    elif adapter == "retained_result_comparison":
        phase = "evidence_comparison"
    elif (any(token in tokens for token in ("update", "fetch", "metadata", "sync", "vendor", "deps", "bazel-lock-update"))
          or ("scripts/hepta_ci_v8.py" in tokens and "--run" not in tokens)):
        phase = "dependency_preparation"
    elif (tests or failures):
        phase = "test_execution_with_possible_build_work"
    elif "could not compile" in log and "error" in log:
        phase = "compilation_failure_before_observed_tests"
    elif any(token in tokens for token in ("build", "check")):
        phase = "compilation_or_static_check"
    elif "unittest" in tokens:
        phase = "test_command_with_unreported_test_count"
    else:
        phase = "command_with_unmeasured_phase_breakdown"
    return {"classification": phase, "command": command or None,
            "observed_passed_tests_as_reported": tests,
            "observed_failed_tests_as_reported": failures,
            "phase_cpu_or_wall_allocation_known": False}


def event_from(document, receipt, adapter, status, links, blobs):
    log = blobs[links[0][0]]["data"].decode("utf-8", errors="replace") if links else ""
    started = document.get("started_at", document.get("started_utc"))
    finished = document.get("finished_at", document.get("finished_utc"))
    start, end = instant(started), instant(finished)
    return {
        "id": receipt["sha256"], "receipt": receipt["path"], "adapter": adapter,
        "status_as_recorded_or_exit_derived": status,
        "scope_as_recorded": document.get("scope"),
        "command_exit_code": document.get("command_exit_code", document.get("workflow_exit_code", document.get("exit_code"))),
        "runner_exit_code": document.get("exit_code"), "error_as_recorded": document.get("error"),
        "activity": activity(document, adapter, status, log),
        "source": normalized_source(document, status == "rejected"),
        "time": {"started_at_as_recorded": started, "finished_at_as_recorded": finished,
                 "interval_known": bool(start and end and start <= end),
                 "elapsed_seconds_as_reported": number(document.get("elapsed_seconds")),
                 "elapsed_scope": "command_or_wrapper_wall_time_only",
                 "missing_timestamps_inferred": False},
        "raw_files": [receipt["path"], *(path for path, _ in links)],
        "physical_cost": None, "full_history_cost": None,
        "full_history_cost_known": False, "stage_qualification": False,
    }


def collect(root, output, required=(), settle_seconds=0.25, exclude_subtrees=(), external_pairs=()):
    root, output = Path(root).absolute(), Path(output).absolute()
    if output == root:
        raise ValueError("output must be a new directory distinct from the input root")
    excluded_trees = [relative_name(value) for value in exclude_subtrees]
    if output.is_relative_to(root):
        excluded_trees.append(output.relative_to(root).as_posix())
    output.mkdir(parents=True, exist_ok=False)
    started = utc_now()
    reader = SnapshotReader(root)
    readers, locations, external_roots = [reader], {}, {}
    all_required = list(required)
    blobs, events, exclusions = {}, [], []
    ignored_json = []

    def consume(name, owner, namespace="", explicit_log=None):
        archive_name = namespace + name
        try:
            receipt = owner.read(name, MAX_JSON)
            document = strict_json(receipt["data"])
            parsed = adapt(document, name)
            if parsed is None and explicit_log is not None:
                if (not isinstance(document, dict) or type(document.get("exit_code")) is not int
                        or not (document.get("finished_at") or document.get("finished_utc"))):
                    raise ValueError("explicit external pair has no completed execution record")
                parsed = ("explicit_external_completed_pair", "passed" if document["exit_code"] == 0 else "failed",
                          [(explicit_log, document.get("log_sha256"))])
            if parsed is None:
                ignored_json.append(archive_name)
                return
            adapter, status, links = parsed
            if explicit_log is not None and [path for path, _ in links] != [explicit_log]:
                raise ValueError("explicit external log differs from receipt reference")
            receipt["path"] = archive_name
            candidate, bindings = {archive_name: receipt}, {archive_name: (owner, name)}
            for path, expected in links:
                blob = owner.read(path)
                if expected is not None and blob["sha256"] != expected:
                    raise ValueError("referenced file SHA-256 differs from receipt: " + path)
                if expected is None and explicit_log is None:
                    raise ValueError("unbound log requires an explicit external pair")
                blob["path"] = namespace + path
                candidate[blob["path"]], bindings[blob["path"]] = blob, (owner, path)
            if any(path in locations and locations[path][0].root != owner.root for path in candidate):
                raise ValueError("archive namespace collision")
            if sum(blob["bytes"] for blob in {**blobs, **candidate}.values()) > MAX_TOTAL:
                raise ValueError("collection byte limit exceeded")
            blobs.update(candidate)
            locations.update(bindings)
            mapped_links = [(namespace + path, digest) for path, digest in links]
            event = event_from(document, receipt, adapter, status, mapped_links, blobs)
            event["record_root"] = str(owner.root)
            event["receipt_log_hash_verified"] = bool(links) and all(digest is not None for _, digest in links)
            event["log_linkage"] = ("no_command_log" if not links else "receipt_sha256" if event["receipt_log_hash_verified"]
                                    else "explicit_pair_observed_hash_only_not_bound_by_receipt")
            events.append(event)
        except (OSError, ValueError, KeyError, TypeError) as error:
            exclusions.append({"path": archive_name, "reason": str(error)})

    try:
        paths = []
        for directory, directories, files in os.walk(root, followlinks=False):
            relative = Path(directory).relative_to(root)
            directories[:] = [name for name in directories
                              if (relative / name).as_posix() not in excluded_trees
                              and not (Path(directory) / name).is_symlink()]
            paths.extend((Path(directory) / name).relative_to(root).as_posix()
                         for name in files if name.endswith((".json", ".jsonl", ".log")))
        for name in sorted(path for path in paths if path.endswith(".json")):
            consume(name, reader)
        for receipt_path, log_path in external_pairs:
            receipt_path, log_path = Path(receipt_path), Path(log_path)
            if (not receipt_path.is_absolute() or not log_path.is_absolute()
                    or receipt_path.parent != log_path.parent or receipt_path.is_relative_to(root)
                    or ".." in receipt_path.parts or ".." in log_path.parts):
                raise ValueError("external pair requires explicit absolute sibling paths outside the primary root")
            owner = SnapshotReader(receipt_path.parent)
            readers.append(owner)
            namespace = "external-sources/" + sha256(str(owner.root).encode())[:16] + "/"
            external_roots[namespace] = str(owner.root)
            identifier = namespace + relative_name(receipt_path.name)
            if identifier in all_required:
                raise ValueError("duplicate external receipt")
            all_required.append(identifier)
            consume(receipt_path.name, owner, namespace, relative_name(log_path.name))
        time.sleep(settle_seconds)
        unstable = set()
        for name, original in blobs.items():
            try:
                owner, original_name = locations[name]
                current = owner.read(original_name)
                if current["sha256"] != original["sha256"] or current["stat"] != original["stat"]:
                    raise ValueError("bytes or file identity changed between collection passes")
            except (OSError, ValueError) as error:
                unstable.add(name)
                exclusions.append({"path": name, "reason": str(error)})
        accepted = []
        for event in events:
            if unstable.intersection(event["raw_files"]):
                exclusions.append({"path": event["receipt"], "reason": "referenced evidence was unstable; entire event omitted"})
            else:
                accepted.append(event)
        events = accepted
        retained = {path for event in events for path in event["raw_files"]}
        blobs = {path: blob for path, blob in blobs.items() if path in retained}
        for name in sorted(path for path in paths if path.endswith((".log", ".jsonl")) and path not in retained):
            exclusions.append({"path": name, "reason": "not referenced by an accepted terminal receipt; completion or binding unknown"})
    finally:
        for owner in readers:
            owner.close()
    events.sort(key=lambda event: (str(event["time"]["started_at_as_recorded"] or ""), event["receipt"]))
    overlaps = []
    for index, left in enumerate(events):
        if not left["time"]["interval_known"]:
            continue
        a, b = (instant(left["time"][key]) for key in ("started_at_as_recorded", "finished_at_as_recorded"))
        for right in events[index + 1:]:
            if not right["time"]["interval_known"]:
                continue
            c, d = (instant(right["time"][key]) for key in ("started_at_as_recorded", "finished_at_as_recorded"))
            if max(a, c) < min(b, d):
                overlaps.append({"left": left["id"], "right": right["id"],
                                 "relation": "overlapping_recorded_wall_intervals",
                                 "workflow_container_involved": "workflow_container" in (left["adapter"], right["adapter"]),
                                 "parallel_cpu_execution_proven": False})
    archive = output / "execution-evidence.tar.gz"
    with archive.open("xb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|") as tar:
                for name, blob in sorted(blobs.items()):
                    item = tarfile.TarInfo("original/" + name)
                    item.size, item.mode, item.mtime = blob["bytes"], 0o444, 0
                    tar.addfile(item, io.BytesIO(blob["data"]))
        raw.flush()
        os.fsync(raw.fileno())
    missing = sorted(set(all_required) - {event["receipt"] for event in events})
    manifest = {
        "schema": "hepta.engineering-execution-history.v1",
        "collector_sha256": sha256(Path(__file__).read_bytes()),
        "records_root": str(root), "collection_started_at": started,
        "collection_finished_at": utc_now(), "required_receipts": all_required,
        "required_receipts_missing": missing,
        "capture_status": ("required_receipts_missing" if missing else
                           "snapshot_created" if events else "no_completed_receipts"),
        "completion_guard": "terminal record plus unchanged no-follow bytes/stat on two passes; per-event log_linkage distinguishes recorded hashes from explicitly paired unbound supplements",
        "unsigned_local_records_are_external_authority": False,
        "input_source_or_logs_modified": False, "settle_seconds": settle_seconds,
        "events": events, "overlapping_intervals": overlaps,
        "source_commits_as_recorded": sorted({event["source"]["observed_commit"] for event in events if git_sha(event["source"]["observed_commit"])}),
        "status_counts": dict(Counter(event["status_as_recorded_or_exit_derived"] for event in events)),
        "unrecognized_json_not_archived": [name for name in ignored_json if name not in blobs],
        "excluded_subtrees": excluded_trees,
        "explicit_external_roots": external_roots,
        "excluded": exclusions,
        "physical_cost": None, "full_history_cost": None, "full_history_cost_known": False,
        "complete_execution_history": False, "command_wall_sum_seconds": None,
        "cpu_seconds": None, "learning_cost": None, "final_candidate_pass": False,
        "qualification_evaluation": "not_performed_by_collector", "stage_advancement_claimed": False,
        "cost_limitation": "Individual reported wall times are retained without summation or attribution to CPU, learning or complete historical cost. Missing timing stays unknown; overlapping intervals and differing source identities remain separate.",
        "archive": {"file": archive.name, "bytes": archive.stat().st_size,
                    "sha256": sha256(archive.read_bytes()),
                    "metadata": "regular inert files, mode 0444, uid/gid/mtime zero; original bytes unchanged"},
        "files": [{key: value for key, value in blob.items() if key != "data"}
                  for _, blob in sorted(blobs.items())],
    }
    target = output / "execution-history.json"
    with target.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--require-receipt", action="append", default=[])
    parser.add_argument("--exclude-subtree", action="append", default=[])
    parser.add_argument("--external-pair", nargs=2, action="append", default=[], metavar=("RECEIPT", "LOG"))
    parser.add_argument("--settle-seconds", type=float, default=0.25)
    args = parser.parse_args()
    if not math.isfinite(args.settle_seconds) or not 0 <= args.settle_seconds <= 10:
        parser.error("settle-seconds must be between 0 and 10")
    try:
        required = [relative_name(value) for value in args.require_receipt]
        result = collect(args.records_root, args.output_dir, required, args.settle_seconds,
                         args.exclude_subtree, args.external_pair)
    except (OSError, ValueError) as error:
        parser.exit(2, f"History capture refused: {error}\n")
    print(json.dumps({"capture_status": result["capture_status"], "events": len(result["events"]),
                      "archive": result["archive"], "required_receipts_missing": result["required_receipts_missing"],
                      "qualification_evaluation": result["qualification_evaluation"]}, sort_keys=True))
    return 2 if result["required_receipts_missing"] or not result["events"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
