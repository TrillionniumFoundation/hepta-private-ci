"""Prove a single lost non-UTF8 byte against a precommitted Git object hash.

An official text-only GitHub file accessor emitted a UTF-8 replacement codepoint.
This is a *hash-constrained reconstruction*, not a direct original-byte API
receipt. Exactly one unknown byte is exhaustively tested; never infer general
binary-source fidelity from this special case or grant task/model qualification.
"""

import argparse
import base64
import hashlib
import json
from pathlib import Path

from deno_binary_git_source_gate import (
    BLOB, COMMIT, ROOT_TREE, PATH, REPOSITORY, CUTOFF,
    git_blob_sha,
)

LOSSY_PROJECTION_BASE64 = "ZXhwb3J0IGRlZmF1bHQgImNhZu+/vSI7Cg=="
REPLACEMENT = "\ufffd".encode("utf-8")
ORIGINAL_BYTE_COUNT = 23


def recover_single_byte_projection(encoded, *, original_sha=BLOB,
                                    original_size=ORIGINAL_BYTE_COUNT):
    """Only allow *one* replacement of exactly one byte; compare all 256 guesses."""
    if not isinstance(encoded, str) or len(encoded) > 1024:
        raise ValueError("bounded, registered lossy projection required")
    try:
        altered_bytes = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error):
        raise ValueError("unverified source-view encoding") from None
    if altered_bytes.count(REPLACEMENT) != 1:
        raise ValueError("exactly one UTF-8 replacement codepoint required")
    if len(altered_bytes) != original_size + len(REPLACEMENT) - 1:
        raise ValueError("lossy source byte count differs from registered original")
    left, right = altered_bytes.split(REPLACEMENT)
    matches = []
    for byte in range(256):
        guess = left + bytes([byte]) + right
        if git_blob_sha(guess) == original_sha:
            matches.append((byte, guess))
    if len(matches) != 1:
        raise ValueError("no unique precommitted Git object matches source bytes")
    byte, original = matches[0]
    try:
        original.decode("utf-8")
    except UnicodeDecodeError:
        pass
    else:
        raise ValueError("recovered byte is not actually non-UTF8")
    return {
        "schema": "hepta.memorycell.single-byte-lossy-blob-preimage.v1",
        "original_git_object_sha1": original_sha,
        "original_byte_count": len(original),
        "sha1_recomputed_from_exhaustive_candidate": git_blob_sha(original),
        "candidate_bytes_tested": 256,
        "hash_matching_byte_candidates": len(matches),
        "single_unknown_original_byte_hex": f"{byte:02x}",
        "non_utf8_original_recovered": True,
        "input_was_utf8_replacement_projection_not_original_git_base64": True,
        "projection_sha256": hashlib.sha256(altered_bytes).hexdigest(),
        "recovery_method": "exhaustive_one_byte_search_with_precommitted_git_blob_sha1",
        "bytes_uploaded_or_materialized": False,
        "actual_binary_github_api_response_received": False,
    }


def frozen_proof():
    report = recover_single_byte_projection(LOSSY_PROJECTION_BASE64)
    report.update({
        "source_repository": REPOSITORY,
        "original_commit": COMMIT,
        "original_commit_tree": ROOT_TREE,
        "original_source_path": PATH,
        "original_source_cut": CUTOFF,
        "original_commit_tree_path_binding_previously_inspected": True,
        "human_review_certified": False,
        "source_byte_sha_proof_is_not_task_answer_truth": True,
        "independent_source_population_qualified": False,
        "model_inference_calls": 0,
        "learned_memory_gain_established": False,
        "production_accepted": False,
    })
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError("original research receipt cannot be overwritten")
    report = frozen_proof()
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
