#!/usr/bin/env python3
"""Audit actual native P2e rows. No mock fallback, dispatch or authority issuance."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

CORPUS_SHA256 = "e63fd2f1b023f214306030c6e782c329e83846cc1460c0da5770d078e98433c9"
UPSTREAM = "092d3acd6bec3e3a14bdc7e7a2810ab628ab759d"
PARENT = "a2d9d5ef229e5dc2ea3baee4e60195b40b3ff056"
MAX_BYTES = 4 * 1024 * 1024


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def read_bytes(path: Path) -> bytes:
    # These are CI-controlled fixture/log files, never an application input API.
    if path.is_symlink() or not path.is_file():
        raise ValueError("expected a regular non-symlink evidence file")
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("evidence exceeds byte budget")
    return data


def load_corpus(path: Path) -> dict[str, Any]:
    data = read_bytes(path)
    if hashlib.sha256(data).hexdigest() != CORPUS_SHA256:
        raise ValueError("corpus changed: independent review and explicit repin required")
    corpus = json.loads(data, object_pairs_hook=unique_object)
    if (corpus["schema"] != 1 or corpus["authority"] != "DENY_ALL"
            or corpus["upstream_commit"] != UPSTREAM or corpus["parent_commit"] != PARENT):
        raise ValueError("invalid corpus provenance")
    cases = corpus["cases"]
    if len(cases) != 50 or len({case["id"] for case in cases}) != 50:
        raise ValueError("missing or repeated case")
    for case in cases:
        if type(case["hepta_accepts"]) is not bool or type(case["native_accepts"]) is not bool:
            raise ValueError("acceptance must be boolean")
        if case["hepta_accepts"] and not case["native_accepts"]:
            raise ValueError("Hepta acceptance is not a native-compatible subset")
        if len(case["raw"].encode()) > 16 * 1024:
            raise ValueError("case exceeds reviewed preflight frame bound")
    return corpus



def expected_projection(case: dict[str, Any]) -> dict[str, Any] | None:
    """An independent projection of raw intent plus explicit protocol defaults."""
    if not case["native_accepts"]:
        return None
    request = json.loads(case["raw"], object_pairs_hook=unique_object)
    p = request["params"]
    return {"request_id": request["id"], "process_id": p["processId"],
            "argv": p["argv"], "cwd": p["cwd"], "env": p["env"], "tty": p["tty"],
            "pipe_stdin": p.get("pipeStdin", False), "arg0": p.get("arg0"),
            "env_policy": p.get("envPolicy"), "shell_snapshot": p.get("shellSnapshot"),
            "sandbox": p.get("sandbox"),
            "enforce_managed_network": p.get("enforceManagedNetwork", False),
            "managed_network": p.get("managedNetwork"), "network_proxy": p.get("networkProxy")}


def same_json(left: Any, right: Any) -> bool:
    # Python equality alone incorrectly identifies false with 0 and true with 1.
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(
        right, sort_keys=True, allow_nan=False)


def rows(path: Path, marker: str) -> dict[str, dict[str, Any]]:
    text = read_bytes(path).decode("utf-8", errors="strict")
    if "test result: ok." not in text or "0 failed" not in text:
        raise ValueError("missing successful native test footer")
    output: dict[str, dict[str, Any]] = {}
    for line in text.splitlines():
        if marker not in line:
            continue
        value = json.loads(line.split(marker, 1)[1], object_pairs_hook=unique_object)
        key = value["id"]
        if key in output:
            raise ValueError("repeated native row")
        output[key] = value
    return output


def audit(corpus: dict[str, Any], hepta: dict[str, Any], local: dict[str, Any],
          upstream: dict[str, Any]) -> dict[str, Any]:
    cases = {case["id"]: case for case in corpus["cases"]}
    if any(set(group) != set(cases) for group in (hepta, local, upstream)):
        raise ValueError("incomplete, foreign or duplicate native evidence")
    for key, case in cases.items():
        h = hepta[key]
        if set(h) != {"id", "accepted", "effect_authority"}:
            raise ValueError("unexpected Hepta evidence fields")
        if h["accepted"] is not case["hepta_accepts"] or h["effect_authority"] is not False:
            raise ValueError("Hepta profile or authority drift")
        for group in (local, upstream):
            row = group[key]
            if set(row) != {"id", "accepted", "projection"}:
                raise ValueError("unexpected native evidence fields")
            if row["accepted"] is not case["native_accepts"]:
                raise ValueError("native acceptance drift")
            if not same_json(row["projection"], expected_projection(case)):
                raise ValueError("native semantic drift")
        if local[key] != upstream[key]:
            raise ValueError("repository and pinned upstream disagree")
    return {"schema": 1, "authority": "DENY_ALL", "physical_dispatch": False,
            "production_ready": False, "corpus_sha256": CORPUS_SHA256,
            "upstream_commit": UPSTREAM, "parent_commit": PARENT, "cases": len(cases),
            "hepta_accepted": sum(c["hepta_accepts"] for c in cases.values()),
            "native_accepted": sum(c["native_accepts"] for c in cases.values()),
            "three_way_protocol_conformance": True,
            "runtime_sandbox_verified": False, "performance_measured": False}


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, text=True, timeout=15).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--hepta-log", type=Path)
    parser.add_argument("--local-log", type=Path)
    parser.add_argument("--upstream-log", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--upstream-root", type=Path)
    parser.add_argument("--upstream-lock-report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    corpus = load_corpus(args.corpus)
    if args.validate_only:
        print(json.dumps({"corpus_valid": True, "cases": len(corpus["cases"]),
                          "native_tests_executed": False, "authority": "DENY_ALL"}))
        return
    if any(value is None for value in (args.hepta_log, args.local_log, args.upstream_log,
                                       args.source_root, args.upstream_root, args.output,
                                       args.upstream_lock_report)):
        parser.error("native logs, both checked-out sources and create-only output are required")
    qualification = json.loads(read_bytes(args.upstream_lock_report),
                               object_pairs_hook=unique_object)
    if (qualification.get("schema") != 1
            or qualification.get("upstream_commit") != UPSTREAM
            or qualification.get("original_lock_git_blob")
               != "1cee1174c2e937758713df47683521233a36b4f7"
            or qualification.get("replacement_count") != 161
            or qualification.get("replacement_from") != "0.0.0"
            or qualification.get("replacement_to") != "0.162.1"
            or qualification.get("external_package_changes") != 0
            or qualification.get("original_upstream_checkout_modified") is not False
            or qualification.get("tracked_upstream_source_changes")
               != ["codex-rs/Cargo.lock"]
            or qualification.get("effect_authority") != "DENY_ALL"):
        raise ValueError("unreviewed upstream lock qualification")
    report = audit(corpus, rows(args.hepta_log, "P2E_HEPTA_ROW "),
                   rows(args.local_log, "P2E_NATIVE_ROW "),
                   rows(args.upstream_log, "P2E_NATIVE_ROW "))
    report["upstream_lock_qualification"] = {
        "original_upstream_lock_git_blob": qualification["original_lock_git_blob"],
        "derived_upstream_lock_git_blob": qualification["qualified_lock_git_blob"],
        "derived_upstream_lock_sha256": qualification["qualified_lock_sha256"],
        "normalized_local_workspace_packages": qualification["replacement_count"],
        "original_upstream_lock_natively_usable_without_normalization": False,
        "upstream_original_tracked_sources_unchanged": True,
    }
    if git(args.upstream_root, "rev-parse", "HEAD") != UPSTREAM:
        raise ValueError("upstream checkout drift")
    git(args.source_root, "merge-base", "--is-ancestor", PARENT, "HEAD")
    for root in (args.source_root, args.upstream_root):
        git(root, "diff", "--exit-code", "HEAD", "--")
    report["tested_commit"] = git(args.source_root, "rev-parse", "HEAD")
    report["tested_tree"] = git(args.source_root, "rev-parse", "HEAD^{tree}")
    report["log_sha256"] = {
        name: hashlib.sha256(read_bytes(path)).hexdigest()
        for name, path in (("hepta", args.hepta_log), ("local", args.local_log),
                           ("upstream", args.upstream_log))}
    # Provenance is a local CI observation, never an independent signature.
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
