#!/usr/bin/env python3
"""Read-only complete boundary inventory diagnostic over all e8 Rust sources plus a pinned overlay."""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import time

BASE_HEAD = "e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd"
BASE_TREE = "b607ff5f50812c5e0f932d7dae18d4c74f1269cb"
FIXED_UPSTREAM = "b29869e856d08db1bfb066116a9c443376ccc57d"
OVERLAY_SHA256 = "f6335dbb2100f15a6758654d60aed526b09a5ffe403d462dfb290d8dfa818222"
CALLERS_SHA256 = "13b8b2d8d9fbe0768f0b8dd288ee8e147f5641a2affd99f7eed5b2647e107d74"
VERIFIERS = {
    "scripts/verify_hepta_callers.py":
        "16015483d2319a2dbf2f6ab13e4c3c5e5f3a5318ac85f70557004b7fcb450e3f",
    "scripts/hepta_typed_callers.py":
        "3740bc9c17796686f1d6b282675d275d1b07c70a4b22c67945072c7b61a40d38",
}
EXPECTED_BOUNDARIES = 534
EXPECTED_PROTECTED = 390


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def git(root, *args):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    result = subprocess.run(
        ["git", "-C", str(root), *args], check=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=env, timeout=30,
    )
    return result.stdout.decode("utf-8").strip()


def canonical_digest(rows):
    return sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode())


def inventory_text(raw):
    return [
        {"path": path, "bytes": len(text.encode()), "sha256": sha256(text.encode()),
         "git_blob_sha": blob(text.encode())}
        for path, text in sorted(raw.items())
    ]


class ReadOnlyFile:
    def __init__(self, path, raw):
        self.path = path
        self.raw = raw

    def is_file(self):
        return self.path in self.raw

    def read_text(self, encoding="utf-8"):
        if encoding not in ("utf-8", "utf8"):
            raise ValueError("only the original UTF-8 source is available")
        return self.raw[self.path]

    def __str__(self):
        return self.path


class ReadOnlySourceView:
    """Supply exactly the same candidate bytes for definition and caller reads."""
    def __init__(self, raw):
        self.raw = raw

    def __truediv__(self, relative):
        return ReadOnlyFile(str(relative), self.raw)


def checkpoint(path, value):
    # Atomic, fsynced external checkpoint; never modifies the source clone.
    temporary = path.with_name(path.name + ".next")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def progress_event(stream, event, **fields):
    record = {"event": event, "at": datetime.datetime.now(datetime.timezone.utc).isoformat(), **fields}
    line = json.dumps(record, sort_keys=True)
    stream.write(line + "\n")
    stream.flush()
    os.fsync(stream.fileno())
    print(line, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--overlay-json", required=True)
    parser.add_argument("--callers", required=True)
    parser.add_argument("--callers-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.source_root).resolve(strict=True)
    output = Path(args.output).resolve()
    if output.is_relative_to(root):
        raise ValueError("diagnostic output must be external to the source clone")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValueError("a prior diagnostic result must not be overwritten")
    result = {
        "schema": "hepta.scoped-original-all-boundaries-diagnostic.v1",
        "status": "running_scoped_diagnostic",
        "full_gate_status": "not_run",
        "cargo_tests": "not_run",
        "full_source_tree": None,
        "authority_granted": False,
        "source_root": str(root),
        "base_source_sha": BASE_HEAD,
        "base_tree": BASE_TREE,
        "fixed_upstream": FIXED_UPSTREAM,
        "overlay_sha256": OVERLAY_SHA256,
        "callers_sha256": CALLERS_SHA256,
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "All declared 534 boundary and 390 protected rows; not the original full gate.",
        "declared_boundary_ids": [],
        "attempted_boundaries": [],
        "attempted_protected_paths": [],
        "boundaries": [],
        "protected": [],
        "errors": [],
    }
    checkpoint(output, result)
    progress = output.with_name("row-progress.jsonl").open("x", encoding="utf-8")
    print("BEGIN_SCOPED_ORIGINAL_ALL_BOUNDARIES", flush=True)
    started = time.monotonic()
    initial_raw = None
    proof = None
    roots = None
    initial_status = None
    attempted = False
    try:
        if args.callers_sha256 != CALLERS_SHA256:
            raise ValueError("the supplied CALLERS hash is not the frozen preparation")
        if git(root, "rev-parse", "HEAD") != BASE_HEAD:
            raise ValueError("base HEAD mismatch")
        if git(root, "rev-parse", "HEAD^{tree}") != BASE_TREE:
            raise ValueError("base tree mismatch")
        initial_status = git(root, "status", "--porcelain=v1", "--untracked-files=all")
        if initial_status:
            raise ValueError("source clone is not clean")
        for relative, expected in VERIFIERS.items():
            if sha256((root / relative).read_bytes()) != expected:
                raise ValueError("original verifier bytes changed: " + relative)
        overlay_bytes = Path(args.overlay_json).read_bytes()
        if sha256(overlay_bytes) != OVERLAY_SHA256:
            raise ValueError("overlay bytes differ from the root's immutable packet")
        overlay = json.loads(overlay_bytes)
        if (
            overlay["format"] != "hepta-readonly-rust-source-overlay-v1"
            or overlay["base_source_sha"] != BASE_HEAD
            or overlay["base_tree"] != BASE_TREE
            or overlay["fixed_upstream"] != FIXED_UPSTREAM
            or overlay["full_source_tree"] is not None
        ):
            raise ValueError("overlay source identity mismatch")
        caller_bytes = Path(args.callers).read_bytes()
        if sha256(caller_bytes) != CALLERS_SHA256:
            raise ValueError("CALLERS content differs from its frozen identity")
        spec = importlib.util.spec_from_file_location(
            "scoped_original_readback_verifier", root / "scripts/verify_hepta_callers.py"
        )
        proof = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = proof
        spec.loader.exec_module(proof)
        data = proof._load_manifest(Path(args.callers))
        original_data = proof._load_manifest(root / "CALLERS.toml")
        roots = proof._string_tuple(data, "source_roots")
        if roots != proof._string_tuple(original_data, "source_roots"):
            raise ValueError("source roots changed")
        ignored = proof._string_tuple(data, "ignored_path_fragments")
        if ignored != proof._string_tuple(original_data, "ignored_path_fragments"):
            raise ValueError("ignored source fragments changed")
        rows = proof._boundary_rows(data)
        proof._verify_privileged_inventory(data, rows)
        if len(rows) != EXPECTED_BOUNDARIES or len(data["protected_file"]) != EXPECTED_PROTECTED:
            raise ValueError("unexpected prepared manifest scope")
        result["declared_boundary_ids"] = [row.identifier for row in rows]
        result["declared_protected_paths"] = [row["path"] for row in data["protected_file"]]
        checkpoint(output, result)
        # This is the unchanged full original collector, not an overlay-path list.
        files = proof._source_files(root, roots)
        initial_raw = {
            p.relative_to(root).as_posix(): p.read_text(encoding="utf-8") for p in files
        }
        initial_inventory = inventory_text(initial_raw)
        result["base_rust_files"] = len(initial_raw)
        result["base_rust_inventory_sha256"] = canonical_digest(initial_inventory)
        candidate = dict(initial_raw)
        seen = set()
        additions = []
        deletions = []
        for change in overlay["changes"]:
            path = change["path"]
            relative = PurePosixPath(path)
            if (
                path in seen or relative.is_absolute() or ".." in relative.parts
                or relative.as_posix() != path or not path.endswith(".rs")
                or not any(path.startswith(prefix + "/") for prefix in roots)
            ):
                raise ValueError("unsafe, duplicate or non-Rust overlay path: " + path)
            seen.add(path)
            before = change["before_blob"]
            if before is None:
                if path in candidate:
                    raise ValueError("overlay addition already exists: " + path)
                additions.append(path)
            elif path not in candidate or blob(candidate[path].encode()) != before:
                raise ValueError("overlay preimage mismatch: " + path)
            after = change["after_blob"]
            if after is None:
                if before is None:
                    raise ValueError("deletion has no original source: " + path)
                del candidate[path]
                deletions.append(path)
                continue
            content = change["content"]
            encoded = content.encode("utf-8")
            if (
                len(encoded) != change["bytes"]
                or sha256(encoded) != change["sha256"] or blob(encoded) != after
            ):
                raise ValueError("overlay postimage mismatch: " + path)
            candidate[path] = content
        if len(seen) != 25 or len(additions) != 7 or deletions:
            raise ValueError("the frozen overlay must have 25 changes, 7 additions, no deletions")
        if len(candidate) != len(initial_raw) + len(additions) - len(deletions):
            raise ValueError("candidate Rust enumeration was truncated")
        result["candidate_rust_files"] = len(candidate)
        result["overlay_changed_paths"] = sorted(seen)
        result["overlay_added_paths"] = additions
        result["overlay_deleted_paths"] = deletions
        result["candidate_rust_inventory_sha256"] = canonical_digest(inventory_text(candidate))
        source_index = {
            path: proof._strip_cfg_test_items(proof._strip_rust_non_code(raw))
            for path, raw in candidate.items()
        }
        source_view = ReadOnlySourceView(candidate)
        fields_cache = {}
        for position, row in enumerate(rows):
            identifier = row.identifier
            attempted = True
            result["attempted_boundaries"].append(identifier)
            progress_event(progress, "boundary_started", position=position, id=identifier)
            checkpoint(output, result)
            try:
                observed = proof._verify_boundary(
                    source_view, row, source_index, ignored,
                    fields_by_receiver_type=fields_cache,
                )
                observation = {"id": identifier, "status": "passed", "original_result": observed}
            except proof.VerificationFailure as error:
                observation = {"id": identifier, "status": "failed", "error": str(error)}
                result["errors"].append({"phase": "boundary", "id": identifier, "message": str(error)})
            except Exception as error:
                observation = {"id": identifier, "status": "unknown", "type": type(error).__name__, "error": str(error)}
                result["errors"].append({"phase": "boundary_exception", **observation})
            result["boundaries"].append(observation)
            progress_event(progress, "boundary_completed", position=position, **observation)
            checkpoint(output, result)
        for position, row in enumerate(data["protected_file"]):
            path = row["path"]
            result["attempted_protected_paths"].append(path)
            progress_event(progress, "protected_started", position=position, path=path)
            checkpoint(output, result)
            try:
                observed = proof._verify_protected_files(source_view, {"protected_file": [row]})
                observation = {"path": path, "status": "passed", "original_result": observed}
            except proof.VerificationFailure as error:
                observation = {"path": path, "status": "failed", "error": str(error)}
                result["errors"].append({"phase": "protected", "path": path, "message": str(error)})
            except Exception as error:
                observation = {"path": path, "status": "unknown", "type": type(error).__name__, "error": str(error)}
                result["errors"].append({"phase": "protected_exception", **observation})
            result["protected"].append(observation)
            progress_event(progress, "protected_completed", position=position, **observation)
            checkpoint(output, result)
        observations = result["boundaries"] + result["protected"]
        if any(row["status"] == "unknown" for row in observations):
            result["status"] = "unknown_scoped_diagnostic"
        elif result["errors"]:
            result["status"] = "failed_scoped_diagnostic"
        else:
            result["status"] = "passed_scoped_diagnostic"
    except Exception as error:
        result["status"] = "unknown_scoped_diagnostic" if attempted else "rejected_before_boundary_execution"
        result["errors"].append({"phase": "exception", "type": type(error).__name__, "message": str(error)})
    finally:
        try:
            external_unchanged = (
                sha256(Path(args.callers).read_bytes()) == CALLERS_SHA256
                and sha256(Path(args.overlay_json).read_bytes()) == OVERLAY_SHA256
            )
            result["external_frozen_inputs_unchanged"] = external_unchanged
            if not external_unchanged:
                result["status"] = "unknown_external_input_changed"
            if initial_raw is not None:
                fresh = {
                    p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
                    for p in proof._source_files(root, roots)
                }
                unchanged = fresh == initial_raw
                unchanged = unchanged and git(root, "rev-parse", "HEAD") == BASE_HEAD
                unchanged = unchanged and git(root, "rev-parse", "HEAD^{tree}") == BASE_TREE
                unchanged = unchanged and git(
                    root, "status", "--porcelain=v1", "--untracked-files=all"
                ) == initial_status
                unchanged = unchanged and all(
                    sha256((root / path).read_bytes()) == expected
                    for path, expected in VERIFIERS.items()
                )
                result["all_original_rust_and_verifier_inputs_unchanged"] = unchanged
                if not unchanged:
                    result["status"] = "unknown_source_changed"
            else:
                result["all_original_rust_and_verifier_inputs_unchanged"] = None
        except Exception as error:
            result["status"] = "unknown_postcheck_failed"
            result["errors"].append({"phase": "postcheck", "type": type(error).__name__, "message": str(error)})
        completed = {row["id"] for row in result["boundaries"]}
        attempted_ids = set(result["attempted_boundaries"])
        result["not_started_boundary_ids"] = [
            identifier for identifier in result["declared_boundary_ids"] if identifier not in attempted_ids
        ]
        result["unfinished_boundary_ids"] = [
            identifier for identifier in result["attempted_boundaries"] if identifier not in completed
        ]
        completed_paths = {row["path"] for row in result["protected"]}
        attempted_paths = set(result["attempted_protected_paths"])
        result["not_started_protected_paths"] = [
            path for path in result.get("declared_protected_paths", []) if path not in attempted_paths
        ]
        result["unfinished_protected_paths"] = [
            path for path in result["attempted_protected_paths"] if path not in completed_paths
        ]
        result["counts"] = {
            "boundaries": {state: sum(row["status"] == state for row in result["boundaries"])
                           for state in ("passed", "failed", "unknown")},
            "protected": {state: sum(row["status"] == state for row in result["protected"])
                          for state in ("passed", "failed", "unknown")},
        }
        result["elapsed_seconds"] = time.monotonic() - started
        result["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        checkpoint(output, result)
        progress_event(progress, "diagnostic_completed", status=result["status"], counts=result["counts"],
                       not_started_boundary_ids=result["not_started_boundary_ids"],
                       unfinished_boundary_ids=result["unfinished_boundary_ids"],
                       not_started_protected_paths=result["not_started_protected_paths"],
                       unfinished_protected_paths=result["unfinished_protected_paths"])
        progress.close()
        print(json.dumps(result, sort_keys=True), flush=True)
    return 0 if result["status"] == "passed_scoped_diagnostic" else 1


if __name__ == "__main__":
    raise SystemExit(main())
