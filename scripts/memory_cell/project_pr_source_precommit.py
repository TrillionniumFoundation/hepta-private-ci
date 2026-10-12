"""Source-only, future-review worklist for independently pinned public project PRs.

No answer labels, model calls, production owner or semantic reviewer are created.
The frozen Git head/tree/file blobs can later supply exact source to an
independent reviewer, without relabelling mutable PR descriptions as history.
"""

import argparse
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from datetime import datetime, timezone

SCHEMA = "hepta.memorycell.real-project-pr-source-cut.v1"
CUT = "2026-10-12T09:45:00Z"
PARTITIONS = {
    "rust-lang/rust": "train",
    "kubernetes/kubernetes": "selection",
    "numpy/numpy": "evaluation",
    "astral-sh/ruff": "evaluation",
}
COUNTS = {"train": 2, "selection": 2, "evaluation": 4}
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
PATH = re.compile(r"[a-zA-Z0-9_./+@-]{1,512}\Z")
TYPES = ("change_intent", "verification_gap")


def check(ok, message):
    if not ok:
        raise ValueError(message)


def strict_json(raw):
    def pairs(items):
        out = {}
        for name, value in items:
            check(name not in out, "duplicate JSON property")
            out[name] = value
        return out

    def invalid(value):
        raise ValueError("nonfinite JSON number: " + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def timestamp(value):
    check(isinstance(value, str) and re.fullmatch(r"20[0-9]{2}-[01][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z", value), "UTC timestamp required")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid UTC timestamp") from exc


def checksum(value):
    check(isinstance(value, str) and HEX40.fullmatch(value) is not None, "exact Git object SHA required")
    return value


def audit(manifest):
    check(isinstance(manifest, dict) and set(manifest) == {
        "schema", "source_cut_utc", "policy", "partitions", "cases", "task_types",
        "no_answers_or_labels", "independent_review_certified", "prospective_outcomes_observed",
        "task_improvement_established", "model_executions", "production_accepted",
    }, "source-only manifest key census")
    check(manifest["schema"] == SCHEMA and manifest["source_cut_utc"] == CUT, "unregistered historical cut")
    check(manifest["partitions"] == PARTITIONS and manifest["task_types"] == list(TYPES), "cross-project partition or task change")
    check(manifest["policy"] == {
        "source_type": "public-github-open-pull-requests",
        "source_content": "immutable_git_commit_trees_and_file_blob_refs",
        "candidate_selection": "two_updated_before_cut_per_project_fixed_before_review",
        "full_code_and_human_label_not_in_this_manifest": True,
        "published_source_pretraining_contamination_unknown": True,
        "reopened_pr_chronology_not_certified": True,
    }, "source policy drift or invalid provenance claim")
    check(
        manifest["no_answers_or_labels"] is True
        and manifest["independent_review_certified"] is False
        and manifest["prospective_outcomes_observed"] is False
        and manifest["task_improvement_established"] is False
        and manifest["model_executions"] == 0
        and manifest["production_accepted"] is False,
        "a source-only cut cannot carry scores, labels, or admission",
    )
    cut = timestamp(CUT)
    cases = manifest["cases"]
    check(isinstance(cases, list) and len(cases) == 8, "exact eight real project PRs required")
    seen = set()
    distribution = Counter()
    nfiles = 0
    ncommits = 0
    for row in cases:
        check(isinstance(row, dict) and set(row) == {
            "repo", "partition", "pull_number", "pull_url", "title", "created_at",
            "last_updated_at", "state_at_capture", "head_sha", "tree_sha", "parents",
            "head_committed_at", "commits", "files", "description_sha256",
        }, "unexpected or missing PR source field")
        repo = row["repo"]
        check(repo in PARTITIONS and row["partition"] == PARTITIONS[repo], "cross-project partition leakage")
        number = row["pull_number"]
        check(type(number) is int and 1 <= number <= 1_000_000 and (repo, number) not in seen, "duplicate/invalid original PR")
        seen.add((repo, number))
        distribution[repo] += 1
        check(row["pull_url"] == f"https://github.com/{repo}/pull/{number}", "noncanonical original PR URL")
        check(isinstance(row["title"], str) and 1 <= len(row["title"]) <= 180, "bounded original PR title")
        check(row["state_at_capture"] == "open", "only precommitted open projects admitted")
        check(timestamp(row["created_at"]) <= timestamp(row["last_updated_at"]) <= cut, "PR public metadata after frozen source cut")
        head = checksum(row["head_sha"])
        checksum(row["tree_sha"])
        check(timestamp(row["head_committed_at"]) <= cut, "future head commit in source-only cohort")
        check(isinstance(row["description_sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", row["description_sha256"]), "PR description digest required")
        parents = row["parents"]
        check(isinstance(parents, list) and 1 <= len(parents) <= 2 and len(set(parents)) == len(parents), "invalid immutable commit parents")
        for p in parents:
            checksum(p)
        commits = row["commits"]
        check(isinstance(commits, list) and 1 <= len(commits) <= 32 and commits[-1]["sha"] == head, "missing exact frozen PR commit chain")
        known = set()
        for c in commits:
            check(isinstance(c, dict) and set(c) == {"sha", "committed_at", "summary"}, "unexpected immutable commit field")
            checksum(c["sha"])
            check(c["sha"] not in known, "duplicate immutable commit")
            known.add(c["sha"])
            check(timestamp(c["committed_at"]) <= cut, "commit made after source cut")
            check(isinstance(c["summary"], str) and 1 <= len(c["summary"]) <= 180, "invalid bounded original commit summary")
        files = row["files"]
        check(isinstance(files, list) and 1 <= len(files) <= 32, "missing or oversized original changed-file list")
        names = set()
        for f in files:
            check(isinstance(f, dict) and set(f) == {"path", "status", "blob_sha", "additions", "deletions"}, "unexpected original-file field")
            path = f["path"]
            check(isinstance(path, str) and PATH.fullmatch(path) is not None and ".." not in path.split("/") and not path.startswith("/"), "unsafe or fabricated original source path")
            check(path not in names, "duplicate source-file evidence")
            names.add(path)
            check(f["status"] in ("added", "modified", "removed", "renamed", "copied", "changed", "unchanged"), "unknown changed-file status")
            checksum(f["blob_sha"])
            for k in ("additions", "deletions"):
                check(type(f[k]) is int and 0 <= f[k] < 10**6, "invalid changed-file line count")
        nfiles += len(files)
        ncommits += len(commits)
    check(set(distribution) == set(PARTITIONS) and all(n == 2 for n in distribution.values()), "source-family overlap or missing group")
    check(sum(distribution[repo] for repo in PARTITIONS if PARTITIONS[repo] == "evaluation") == COUNTS["evaluation"], "wrong held-out development source count")
    return dict(
        schema="hepta.memorycell.real-project-pr-source-cut.audit.v1",
        source_cut_utc=CUT,
        families=len(distribution),
        source_prs=len(cases),
        immutable_commit_refs=ncommits,
        file_blob_refs=nfiles,
        partition_pr_counts={k: sum(distribution[r] for r in PARTITIONS if PARTITIONS[r] == k) for k in COUNTS},
        unsigned_review_questions=len(cases) * len(TYPES),
        independent_semantic_review=False,
        model_calls=0,
        production_accepted=False,
    )


def review_worklist(manifest):
    audit(manifest)
    items = []
    for c in manifest["cases"]:
        case_id = f"{c['repo']}#{c['pull_number']}@{c['head_sha']}"
        sources = [f"https://github.com/{c['repo']}/commit/{x['sha']}" for x in c["commits"]]
        file_refs = [f"{c['repo']}:{f['path']}@{c['head_sha']}" for f in c["files"]]
        for category in TYPES:
            question = (
                "Identify the actual code change and relevant pre-cut regression/intent using only the pinned commit and file evidence. Cite exact original commit and file references. Abstain if evidence is insufficient."
                if category == "change_intent" else
                "Identify any outstanding regression surface and verification gap from the pinned source before the cut. Separate directly supported evidence from uncertainty; abstain if it cannot be established."
            )
            items.append(dict(
                case_id=case_id, task_type=category, question=question,
                source_commit_urls=sources, original_file_refs=file_refs,
                reviewer_verdict="unreviewed", reviewer_authentication=False,
                gold_answer_unavailable=True, semantic_citation_precision=None,
            ))
    return dict(schema="hepta.memorycell.real-project-unsigned-review-worklist.v1",
        canonical_source_digest_sha256=sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest(),
        unsigned_only=True, cases=items, independent_semantic_review=False,
        production_accepted=False)


def read_pinned(path, expected):
    check(isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected), "external SHA-256 required")
    p = Path(path)
    check(p.is_file() and not p.is_symlink() and 0 < p.stat().st_size <= 256 * 1024, "bounded regular pinned source manifest")
    content = p.read_bytes()
    check(sha256(content).hexdigest() == expected, "external frozen-source SHA mismatch")
    manifest = strict_json(content.decode("utf-8"))
    audit(manifest)
    return manifest


def write_once(path, obj):
    p = Path(path)
    with p.open("x", encoding="utf-8") as output:
        json.dump(obj, output, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("--source-sha256", required=True)
    p.add_argument("--worklist", type=Path)
    args = p.parse_args()
    source = read_pinned(args.source, args.source_sha256)
    result = audit(source)
    if args.worklist:
        write_once(args.worklist, review_worklist(source))
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
