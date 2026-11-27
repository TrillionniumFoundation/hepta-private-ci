"""Reviewer-only independent publisher-source target reconstruction for HDCF.

Reconstruct original 4-class held labels from exact immutable public CSV bytes
AFTER pretrained inference/training has sealed. A matching hash authenticates
bytes against the predeclared source, not its publisher or a production grant.
Do not import this module in the feature-producer or training stages.
"""
from __future__ import annotations

import hashlib
from typing import Any

from physical_bank import Denied

ORIGINAL_SOURCE_CSV = {
    "train": "b06e26ac675513959a63135f11b94ea7786ed02da65db93a5650d8838cbc664b",
    "test": "d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d",
}
ORIGINAL_SELECTION_ID = "95dc97bd0700165b431d140e77c35500713bc95dd3f6c31b6dabb9e021d26fad"
TYPE_DOMAIN = "hepta.hdcf.original-type-partition.v1\0"
MAX_CSV_BYTES = 2_000_000


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Denied(message)


def _type_for_original_id(case_id: str) -> str:
    _require(type(case_id) is str and 1 <= len(case_id) <= 128 and case_id.isascii(),
             "invalid original case id")
    raw = hashlib.sha256((TYPE_DOMAIN + case_id).encode("ascii")).digest()
    return "hash0" if raw[0] & 1 == 0 else "hash1"


def _compare_original_cases(public: dict[str, Any], private: dict[str, Any],
                            cases: dict[str, Any]) -> None:
    """Structural comparison; caller must first independently verify CSV SHA."""
    _require(type(cases) is dict and set(cases) == {"fit", "heldout"} and
             type(cases["fit"]) is list and len(cases["fit"]) == 64 and
             type(cases["heldout"]) is list and len(cases["heldout"]) == 32,
             "invalid independently rebuilt original population")
    _require(type(public) is dict and public.get("input_id") == ORIGINAL_SELECTION_ID and
             type(public.get("fit")) is list and len(public["fit"]) == 64 and
             type(public.get("heldout")) is list and len(public["heldout"]) == 32 and
             type(private) is dict and private.get("input_id") == ORIGINAL_SELECTION_ID and
             type(private.get("targets")) is list and len(private["targets"]) == 32 and
             public.get("source_material_sha256") == ORIGINAL_SOURCE_CSV and
             private.get("source_material_sha256") == ORIGINAL_SOURCE_CSV,
             "staged sample/source identity not equal to immutable original")
    seen: set[str] = set()
    for observed, source in zip(public["fit"], cases["fit"], strict=True):
        _require(type(observed) is dict and set(observed) == {"id", "text", "label"} and
                 type(source) is dict and set(source) == {"id", "label"} and
                 observed["id"] == source["id"] and
                 type(source["label"]) is int and 0 <= source["label"] < 4 and
                 type(observed["label"]) is int and observed["label"] == source["label"] and
                 observed["id"] not in seen,
                 "original training label or source case drift")
        seen.add(observed["id"])
    for observed, expected, source in zip(public["heldout"], private["targets"],
                                          cases["heldout"], strict=True):
        _require(type(observed) is dict and set(observed) == {"id", "text"} and
                 type(expected) is dict and set(expected) == {"id", "family", "type", "target"} and
                 type(source) is dict and set(source) == {"id", "label"} and
                 observed["id"] == source["id"] == expected["id"] and
                 observed["id"] not in seen and
                 expected["family"] == "BANKING77-test-original" and
                 expected["type"] == _type_for_original_id(expected["id"]) and
                 type(source["label"]) is int and 0 <= source["label"] < 4 and
                 type(expected["target"]) is int and
                 expected["target"] == source["label"] % 2,
                 "original blind target changed from independently rebuilt publisher labels")
        seen.add(observed["id"])
    _require(len(seen) == 96, "original source case census not complete")


def verify_publisher_held_targets(public: dict[str, Any], private: dict[str, Any],
                                  train_raw: bytes, test_raw: bytes) -> dict[str, Any]:
    """Reject altered original source/labels before consuming final task scores.

    This function must only be invoked inside an independent reviewer process,
    never in an Encoder or training process. No caller-supplied verdict is trusted.
    """
    for kind, raw in (("train", train_raw), ("test", test_raw)):
        _require(type(raw) is bytes and 0 < len(raw) <= MAX_CSV_BYTES and
                 hashlib.sha256(raw).hexdigest() == ORIGINAL_SOURCE_CSV[kind],
                 "missing or changed original publisher CSV bytes")
    from public_source_recount import reconstruct  # independent original-selection parser
    cases = reconstruct(train_raw, test_raw)
    _compare_original_cases(public, private, cases)
    return {
        "schema": "hepta.hdcf.publisher-held-source-review.v1",
        "original_source_csv_sha256": dict(ORIGINAL_SOURCE_CSV),
        "exact_publisher_csv_bytes_matched_predeclared_git_revision": True,
        "all_96_original_case_ids_and_fit_targets_match": True,
        "all_32_blind_binary_targets_reconstructed_from_original_4class": True,
        "held_target_file_accepted_without_source_recount": False,
        "publisher_signature_independently_verified": False,
        "reader_source_family_independence_verified": False,
        "prospective_future_task_success_verified": False,
        "production_authorized": False,
    }


def main(argv: list[str] | None = None) -> int:
    """Reviewer-only disk-byte entrypoint; no generator or training capability."""
    import argparse
    from physical_cli import read_document, write_once
    from public_source_recount import _read_file
    from modernbert_feature_bridge import validate_public

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public", required=True)
    parser.add_argument("--private", required=True)
    parser.add_argument("--train", required=True)
    parser.add_argument("--test", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        pub = read_document(args.public)
        priv = read_document(args.private)
        validate_public(pub, exact_original_source=True)
        receipt = verify_publisher_held_targets(pub, priv,
            _read_file(args.train, MAX_CSV_BYTES),
            _read_file(args.test, MAX_CSV_BYTES))
        write_once(args.out, receipt)
    except (Denied, OSError, ValueError) as exc:
        parser.exit(2, f"DENY_ALL: {type(exc).__name__}: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
