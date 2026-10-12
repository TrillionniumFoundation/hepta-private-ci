"""Frozen public-PR source-family extension, not independently judged memory QA.

This reads original Git OBJECT IDENTIFIERS and PR metadata. It never claims to
have fetched or verified their bytes, seen human answer labels, or run a model.
"""

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re

from project_pr_source_precommit import (
    PARTITIONS as PREVIOUS_PARTITIONS,
    check,
    checksum,
    read_pinned,
    strict_json,
    timestamp,
    write_once,
)

SCHEMA = "hepta.memorycell.public-pr-independent-extension.v1"
CUT = "2026-10-12T16:05:00Z"
PREVIOUS_SHA = (
    "ef2a46ce037db4a91affddd2498eb8e089771ae5734bc13c56cb8a97b840a463"
)
PARTITIONS = {
    "python/cpython": "evaluation",
    "pandas-dev/pandas": "train",
    "scikit-learn/scikit-learn": "evaluation",
    "tokio-rs/tokio": "train",
    "prometheus/prometheus": "selection",
    "denoland/deno": "evaluation",
}
POLICY = {
    "selection": (
        "six expressly precommitted bounded public PR heads from six additional "
        "projects, source-only and not statistically randomized"
    ),
    "timestamp_semantics": (
        "Git object/metadata upper bound, not independent historical capture "
        "or future observation"
    ),
    "source_objects": (
        "original exact Git commits, trees and changed-file blob IDs; "
        "decoded bytes remain to be separately verified"
    ),
}
TYPES = ("change_intent", "verification_gap")
PATH = re.compile(r"[A-Za-z0-9_./+@-]{1,512}\Z")


def audit(manifest):
    check(
        isinstance(manifest, dict)
        and set(manifest)
        == {
            "schema", "source_cut_utc", "previous_corpus_sha256", "policy",
            "partitions", "task_types", "no_gold_answers",
            "no_model_outputs", "source_bytes_not_yet_verified",
            "independent_source_families_certified",
            "independent_review_certified", "effective_independent_n",
            "semantic_citation_precision", "production_accepted", "cases",
        },
        "source-only extension has unexpected/missing fields",
    )
    check(
        manifest["schema"] == SCHEMA
        and manifest["source_cut_utc"] == CUT
        and manifest["previous_corpus_sha256"] == PREVIOUS_SHA
        and manifest["policy"] == POLICY
        and manifest["partitions"] == PARTITIONS
        and manifest["task_types"] == list(TYPES),
        "source cut, prior source or fixed family assignment changed",
    )
    check(
        manifest["no_gold_answers"] is True
        and manifest["no_model_outputs"] is True
        and manifest["source_bytes_not_yet_verified"] is True
        and manifest["independent_source_families_certified"] is False
        and manifest["independent_review_certified"] is False
        and manifest["effective_independent_n"] is None
        and manifest["semantic_citation_precision"] is None
        and manifest["production_accepted"] is False,
        "unreviewed source identifiers cannot be promoted to evidence",
    )
    check(
        not set(PARTITIONS).intersection(PREVIOUS_PARTITIONS),
        "original and extension project scopes overlap",
    )
    cases = manifest["cases"]
    check(
        isinstance(cases, list) and len(cases) == len(PARTITIONS),
        "six frozen project cases required",
    )
    names = set()
    blobs = set()
    counts = Counter()
    commits_total = files_total = 0
    cut = timestamp(CUT)
    for case in cases:
        check(
            isinstance(case, dict)
            and set(case)
            == {
                "repo", "partition", "pull_number", "pull_url",
                "created_at", "updated_at", "state_at_capture",
                "head_sha", "head_committed_at", "tree_sha", "parents",
                "commits", "files",
            },
            "unexpected historical PR metadata or answer-like field",
        )
        repo = case["repo"]
        check(
            repo in PARTITIONS
            and repo not in names
            and case["partition"] == PARTITIONS[repo],
            "duplicate project or changed family partition",
        )
        names.add(repo)
        counts[case["partition"]] += 1
        number = case["pull_number"]
        check(
            type(number) is int
            and 1 <= number <= 1_000_000
            and case["pull_url"] == f"https://github.com/{repo}/pull/{number}",
            "noncanonical frozen PR identity",
        )
        check(
            case["state_at_capture"] == "open"
            and timestamp(case["created_at"])
            <= timestamp(case["updated_at"])
            <= cut
            and timestamp(case["head_committed_at"]) <= cut,
            "unbounded PR metadata or future commit",
        )
        head = checksum(case["head_sha"])
        checksum(case["tree_sha"])
        parents = case["parents"]
        check(
            isinstance(parents, list)
            and 1 <= len(parents) <= 2
            and len(set(parents)) == len(parents),
            "original commit parents incomplete",
        )
        for parent in parents:
            checksum(parent)
        commits = case["commits"]
        check(
            isinstance(commits, list)
            and 1 <= len(commits) <= 16
            and isinstance(commits[-1], dict)
            and commits[-1].get("sha") == head,
            "original PR commit list is incomplete",
        )
        seen_commits = set()
        for commit in commits:
            check(
                isinstance(commit, dict)
                and set(commit) == {"sha", "committed_at"},
                "missing or extra original commit field",
            )
            oid = checksum(commit["sha"])
            check(
                oid not in seen_commits
                and timestamp(commit["committed_at"]) <= cut,
                "duplicate or future original commit",
            )
            seen_commits.add(oid)
        files = case["files"]
        check(
            isinstance(files, list) and 1 <= len(files) <= 32,
            "changed-file list absent or unbounded",
        )
        seen_paths = set()
        for source in files:
            check(
                isinstance(source, dict)
                and set(source) == {
                    "path", "blob_sha", "status", "additions",
                    "deletions", "changes",
                },
                "unexpected original changed-file data",
            )
            path = source["path"]
            check(
                isinstance(path, str)
                and PATH.fullmatch(path) is not None
                and all(p not in ("", ".", "..") for p in path.split("/"))
                and path not in seen_paths,
                "unsafe or repeated original Git path",
            )
            seen_paths.add(path)
            blob = checksum(source["blob_sha"])
            check(
                blob not in blobs
                and source["status"] in ("added", "modified"),
                "cross-project blob reused or unsupported file state",
            )
            blobs.add(blob)
            add, delete, changed = (
                source[k] for k in ("additions", "deletions", "changes")
            )
            check(
                all(type(n) is int and 0 <= n < 1_000_000
                    for n in (add, delete, changed))
                and add + delete == changed,
                "source changes do not match public file metadata",
            )
        commits_total += len(commits)
        files_total += len(files)
    check(
        names == set(PARTITIONS)
        and counts == {"train": 2, "selection": 1, "evaluation": 3}
        and commits_total == 14
        and files_total == 32,
        "missing, reweighted or substituted source-family census",
    )
    return {
        "schema": "hepta.memorycell.source-family-extension.audit.v1",
        "original_prior_project_proxies": len(PREVIOUS_PARTITIONS),
        "additional_project_proxies": len(PARTITIONS),
        "combined_project_proxies": len(PARTITIONS) + len(PREVIOUS_PARTITIONS),
        "additional_public_prs": len(cases),
        "original_commit_ids_recorded": commits_total,
        "original_blob_ids_recorded": files_total,
        "tasks_requiring_real_review": len(cases) * len(TYPES),
        "decoded_source_bytes_verified": False,
        "source_independence_certified": False,
        "independent_effective_n": None,
        "new_model_calls": 0,
        "semantic_citation_precision": None,
        "production_accepted": False,
    }


def unsigned_review_worklist(manifest):
    audit(manifest)
    tasks = []
    for case in manifest["cases"]:
        prefix = f"{case['repo']}#{case['pull_number']}@{case['head_sha']}"
        refs = [
            {"path": f["path"], "git_blob_sha1": f["blob_sha"]}
            for f in case["files"]
        ]
        for kind in TYPES:
            question = (
                "Using only the authenticated original code and parent changes, "
                "identify the concrete change intent. Cite original source "
                "spans, or abstain when evidence is insufficient."
                if kind == "change_intent"
                else "Identify a verifiable regression risk or remaining test "
                "gap using only original code and parent changes. Separate "
                "uncertainty and never infer unseen CI outcomes."
            )
            tasks.append({
                "task_id": prefix + "/" + kind,
                "partition": case["partition"],
                "question": question,
                "source_project": case["repo"],
                "source_pr": case["pull_number"],
                "frozen_head_sha": case["head_sha"],
                "original_commit_shas": [x["sha"] for x in case["commits"]],
                "original_blob_ids": refs,
                "decoded_code_verified": False,
                "answer": None,
                "reviewer_verdict": "unreviewed",
                "independent_reviewer_authenticated": False,
                "source_sufficiency": "unknown",
                "model_prediction": None,
            })
    return {
        "schema": "hepta.memorycell.source-family-extension.worklist.v1",
        "unsigned": True,
        "not_model_ready": True,
        "tasks": tasks,
        "independent_semantic_review": False,
        "production_accepted": False,
    }


def prepare(extension_path, prior_path, out_path, *, expected_sha256):
    raw = Path(extension_path)
    check(
        raw.is_file()
        and not raw.is_symlink()
        and 0 < raw.stat().st_size <= 128 * 1024
        and re.fullmatch(r"[0-9a-f]{64}", expected_sha256 or ""),
        "bounded externally pinned public source manifest required",
    )
    content = raw.read_bytes()
    check(
        sha256(content).hexdigest() == expected_sha256,
        "source manifest changed",
    )
    manifest = strict_json(content.decode("utf-8"))
    result = audit(manifest)
    old = read_pinned(prior_path, PREVIOUS_SHA)
    check(
        set(old["partitions"]) == set(PREVIOUS_PARTITIONS),
        "original source population changed",
    )
    plan = unsigned_review_worklist(manifest)
    plan["extension_sha256"] = expected_sha256
    plan["previous_corpus_sha256"] = PREVIOUS_SHA
    write_once(out_path, plan)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("extension", type=Path)
    parser.add_argument("previous", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-sha256", required=True)
    args = parser.parse_args()
    result = prepare(
        args.extension,
        args.previous,
        args.output,
        expected_sha256=args.source_sha256,
    )
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
