"""Fail-closed, source-only closure of two separately preregistered project cuts.

Only original repository/file byte identity is measured. This is NOT a blinded
joint experiment, task answer, independent reviewer, future-window model result,
or production acceptance. Historical corpus source cuts must remain separate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

BASE_GIT_BLOB = "5600a1eef6ed8a1cfdda77364d7195f2927a1f00"
EXTENSION_GIT_BLOB = "d94cb3d43471d3be3504acdb297066e52c9a5587"
BASE_REPOS = frozenset(
    ("rust-lang/rust", "kubernetes/kubernetes", "numpy/numpy", "astral-sh/ruff")
)
EXTENSION_REPOS = frozenset(
    (
        "denoland/deno",
        "pandas-dev/pandas",
        "prometheus/prometheus",
        "python/cpython",
        "scikit-learn/scikit-learn",
        "tokio-rs/tokio",
    )
)
SOURCE_CUT_A = "2026-10-12T09:45:00Z"
SOURCE_CUT_B = "2026-10-12T16:05:00Z"
BINARY_REPO = "denoland/deno"
BINARY_COMMIT = "707fd96fabc462d710b129e54dbbbb71b51fcd5e"
BINARY_PATH = "tests/testdata/encoding/iso-8859-1.ts"
BINARY_SHA = "a772b57bdd5aa26fbedd07cb057b9006239e784e"
BINARY_SIZE = 23
BINARY_MANIFEST = "cf2b783325d0f1b483953336041476e61877cdb547ad173adcd402f578bf3277"
RECEIPT_SCHEMA = "hepta.memorycell.heldout-nonutf8-blob-recovery.v1"
HEX40 = re.compile(r"[0-9a-f]{40}\Z")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def load_json(path, *, git_blob_sha=None):
    """Read bounded Git-source tracked original material with duplicate rejection."""
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "regular source receipt needed")
    require(path.stat().st_size < 5_000_000, "bounded receipt required")
    content = path.read_bytes()
    if git_blob_sha is not None:
        digest = hashlib.sha1(
            b"blob " + str(len(content)).encode() + b"\0" + content
        ).hexdigest()
        require(digest == git_blob_sha, "original tracked Git JSON source drift")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate receipt JSON keys")
            result[key] = value
        return result

    return json.loads(
        content,
        object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite receipt")),
    )


def bound_records(records, *, byte_key, set_of_repos, verified_fields=()):
    require(isinstance(records, list) and records, "empty original file census")
    seen = set()
    tally = 0
    for record in records:
        require(isinstance(record, dict), "invalid original file record")
        repo, head, path, sha = (
            record.get("repo"),
            record.get("head_sha", record.get("commit")),
            record.get("path"),
            record.get("git_blob_sha1"),
        )
        require(repo in set_of_repos, "project outside frozen population")
        require(isinstance(head, str) and HEX40.fullmatch(head), "unbound head commit")
        require(isinstance(sha, str) and HEX40.fullmatch(sha), "unbound blob object")
        require(isinstance(path, str) and 1 <= len(path) <= 1024, "unbound source path")
        require(
            not path.startswith("/")
            and ".." not in path.split("/")
            and "\\" not in path,
            "unsafe source path",
        )
        size = record.get(byte_key)
        require(
            type(size) is int and 0 < size < 8_000_000, "invalid original byte census"
        )
        for field in verified_fields:
            require(record.get(field) is True, "missing independent byte verification")
        key = (repo, head, path)
        require(key not in seen, "duplicate source binding")
        seen.add(key)
        tally += size
    return seen, tally


def reconcile(base, extension, binary):
    require(
        base.get("verified_git_blob_bytes") == 80, "base 80 original bytes not verified"
    )
    require(base.get("original_file_references") == 80, "base frozen population drift")
    require(
        base.get("source_manifest", {}).get("source_cut_utc") == SOURCE_CUT_A,
        "base cutoff drift",
    )
    a, a_bytes = bound_records(
        base.get("records"),
        byte_key="byte_length",
        set_of_repos=BASE_REPOS,
        verified_fields=("sha1_recomputed", "path_bound_to_head_commit"),
    )
    require(len(a) == 80, "base 80 records missing")
    require(
        a_bytes == base.get("total_verified_raw_source_bytes") == 6503104,
        "base bytes changed",
    )
    require(
        base.get("disposition", {}).get("production_accepted") is False,
        "base falsely promotes production",
    )
    require(
        extension.get("source_cut_utc") == SOURCE_CUT_B, "extension source cutoff drift"
    )
    require(
        extension.get("expected_original_file_bindings") == 32,
        "extension file census drift",
    )
    require(
        extension.get("independently_rehashed_utf8_source_files") == 31,
        "extension verified UTF-8 population drift",
    )
    require(
        extension.get("pending_non_utf8_original_byte_files") == 1,
        "extension original gap was not exactly one",
    )
    b, b_bytes = bound_records(
        extension.get("source_records"),
        byte_key="utf8_bytes",
        set_of_repos=EXTENSION_REPOS,
    )
    require(len(b) == 31, "extension 31 records missing")
    require(
        b_bytes == extension.get("direct_rehashed_original_utf8_bytes") == 1558437,
        "extension previously verified source bytes changed",
    )
    pending = extension.get("pending_original_raw_blobs")
    require(
        isinstance(pending, list) and len(pending) == 1,
        "binary source hole not uniquely registered",
    )
    hole = pending[0]
    require(
        (
            hole.get("repo"),
            hole.get("commit"),
            hole.get("path"),
            hole.get("expected_git_blob_sha1"),
        )
        == (BINARY_REPO, BINARY_COMMIT, BINARY_PATH, BINARY_SHA),
        "binary hole differs from pinned original",
    )
    require(
        hole.get("requires_binary_blob_retrieval") is True,
        "source retrieval method falsely claims complete bytes",
    )
    require(
        set(x[0] for x in a) == BASE_REPOS
        and set(x[0] for x in b) == EXTENSION_REPOS
        and BASE_REPOS.isdisjoint(EXTENSION_REPOS),
        "ten source project partitions not distinct",
    )
    require(
        (BINARY_REPO, BINARY_COMMIT, BINARY_PATH) not in a | b,
        "same original binary file counted twice",
    )
    require(
        binary.get("schema") == RECEIPT_SCHEMA,
        "not an exact recovered original binary response",
    )
    for key, value in (
        ("original_repository", BINARY_REPO),
        ("pinned_head_commit", BINARY_COMMIT),
        ("original_path", BINARY_PATH),
        ("original_blob_sha1", BINARY_SHA),
        ("original_task_manifest_sha256", BINARY_MANIFEST),
        ("source_cut_utc", SOURCE_CUT_B),
        ("verified_binary_bytes", BINARY_SIZE),
    ):
        require(
            binary.get(key) == value and type(binary.get(key)) is type(value),
            "Deno original source identity or binary bytes changed: " + key,
        )
    for key in (
        "head_tree_path_binding_verified",
        "canonical_original_git_blob_hash_recomputed",
        "utf8_recode_forbidden",
    ):
        require(binary.get(key) is True, "source byte check not actually performed")
    for key in (
        "source_bytes_reuploaded",
        "task_answers_or_gold_labels_produced",
        "human_source_sufficiency_certified",
        "source_families_independent_review_certified",
        "parameter_memory_gain_established",
        "production_accepted",
    ):
        require(binary.get(key) is False, "source-only proof promoted as task result")
    require(
        binary.get("model_inference_calls") == 0,
        "source receipt hides neural inference",
    )
    return {
        "schema": "hepta.memorycell.ten-project-exact-bytes-reconciliation.v1",
        "registered_original_source_cuts": [SOURCE_CUT_A, SOURCE_CUT_B],
        "cuts_do_not_form_a_joint_blinded_study": True,
        "original_first_cut_source_files": len(a),
        "original_second_cut_text_files": len(b),
        "newly_independently_verified_non_utf8_files": 1,
        "exact_original_file_bindings": len(a) + len(b) + 1,
        "total_verified_original_blob_bytes": a_bytes + b_bytes + BINARY_SIZE,
        "ten_distinct_named_repositories": sorted(BASE_REPOS | EXTENSION_REPOS),
        "source_byte_hashes_verified_only": True,
        "raw_original_file_bytes_reuploaded": False,
        "historical_pr_discussion_authenticated": False,
        "human_labels_available": False,
        "real_project_task_outcomes_measured": False,
        "matching_llm_reader_tool_permissions_verified": False,
        "independent_future_window_observations": 0,
        "learned_memory_gain_established": False,
        "full_lifecycle_cost_available": False,
        "production_accepted": False,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("base80", type=Path)
    p.add_argument("extension31", type=Path)
    p.add_argument("deno_binary_receipt", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    require(not args.output.exists(), "never overwrite source provenance receipt")
    report = reconcile(
        load_json(args.base80, git_blob_sha=BASE_GIT_BLOB),
        load_json(args.extension31, git_blob_sha=EXTENSION_GIT_BLOB),
        load_json(args.deno_binary_receipt),
    )
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
