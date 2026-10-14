"""Source-hash-selected fresh AG News cohort, frozen before model invocation.

A cross-sectional replication check on a separately SHA256-pinned val2 file
from the same public dataset family. No guarantee of unseen pretraining data or chronological future.
Only a source-HASH based selection plan can enter this experiment: neither
observed predictions nor any trial score participates in cohort selection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from public_agnews_panel import OPTIONS, QUESTION, canonical, load_parquet, sha

SOURCE_PANEL_SHA256 = "2f7a013648e16b60c74614b0fcf1496aa06475f7285f215adddaa51fe29e01a4"
SELECTOR_DOMAIN = b"hepta.stem.agnews-confirmatory-selection.20261014.v1\0"
CASES_PER_CLASS = 64
CONFIRM_SOURCE = ("data/val2-00000-of-00001.parquet",
                  "51ea52a70f2751cbd13183773186dfc833099c7a17f2664535688baa85aa68f9")
SCHEMA = "hepta.stem.agnews-fresh-cross-sectional-cohort.v1"


class ConfirmatoryError(ValueError):
    """Unfrozen public source, overlapping cases or unsupported future claim."""


def check_new_source_file(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ConfirmatoryError("missing or unsafe independently pinned val2 asset")
    length, checksum = 0, hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            length += len(chunk)
            if length > 4 * 1024 * 1024:
                raise ConfirmatoryError("oversized replication parquet input")
            checksum.update(chunk)
    if checksum.hexdigest() != CONFIRM_SOURCE[1]:
        raise ConfirmatoryError("val2 bytes differ from independently preregistered SHA256")
    return checksum.hexdigest()


def _source_digest(text: str) -> str:
    return sha(text.encode("utf-8"))


def _check_origin(original_panel: dict) -> tuple[str, set[str]]:
    from agnews_paired_shadow import check_panel

    try:
        digest, _ = check_panel(original_panel)
    except ValueError as exc:
        raise ConfirmatoryError("invalid original train/calibration/test source panel") from exc
    if digest != SOURCE_PANEL_SHA256:
        raise ConfirmatoryError("original panel digest differs from prior frozen study")
    seen = {c["source_digest"] for c in original_panel["cases"]}
    if len(seen) != 224:
        raise ConfirmatoryError("original panel source uniqueness invalid")
    return digest, seen


def create_panel(original_panel: dict, holdout_rows: list[dict]) -> dict:
    original_digest, used = _check_origin(original_panel)
    if not isinstance(holdout_rows, list) or not holdout_rows:
        raise ConfirmatoryError("no pinned public holdout rows supplied")
    by_source: dict[str, tuple[str, int]] = {}
    for row in holdout_rows:
        if not isinstance(row, dict) or not {"text", "label"} <= row.keys():
            raise ConfirmatoryError("unrecognized parquet row")
        label, text = row["label"], row["text"]
        if type(label) is not int or not isinstance(text, str):
            raise ConfirmatoryError("nonliteral label or missing source text")
        if label not in (0, 1):
            continue
        if not 1 <= len(text.encode("utf-8")) <= 8192:
            continue
        identity = _source_digest(text)
        if identity in used:
            continue
        previous = by_source.get(identity)
        if previous is not None and previous != (text, label):
            raise ConfirmatoryError("identical asset with contradictory labels")
        by_source[identity] = (text, label)
    samples = {0: [], 1: []}
    for digest, (text, label) in by_source.items():
        key = hashlib.sha256(SELECTOR_DOMAIN + bytes.fromhex(digest)).hexdigest()
        samples[label].append((key, digest, text))
    cases = []
    for label in (0, 1):
        selected = sorted(samples[label])[:CASES_PER_CLASS]
        if len(selected) != CASES_PER_CLASS:
            raise ConfirmatoryError("64 independent previously unused source rows per class required")
        for _, digest, text in selected:
            joint = {"question": QUESTION, "options": list(OPTIONS), "state": text}
            cases.append({
                "case_id": digest[:24], "group_id": digest,
                "source_digest": digest, "joint_input_digest": sha(canonical(joint)),
                "split": "new_holdout", "label": label, "label_name": OPTIONS[label],
                "joint_input": joint,
            })
    cases.sort(key=lambda c: c["case_id"])
    if len({c["case_id"] for c in cases}) != len(cases):
        raise ConfirmatoryError("truncated stable case identifiers collide")
    result = {
        "schema": SCHEMA,
        "original_panel_digest": original_digest,
        "dataset_file_sha256": CONFIRM_SOURCE[1],
        "dataset_source_path": CONFIRM_SOURCE[0],
        "selection_domain_sha256": sha(SELECTOR_DOMAIN),
        "cases_per_class": CASES_PER_CLASS,
        "cases": cases,
        "case_count": len(cases),
        "new_source_rows_disjoint_from_previous_study": True,
        "selection_uses_model_predictions": False,
        "same_public_source_family": True,
        "chronological_future_claim": False,
        "foundation_pretraining_overlap_ruled_out": False,
        "source_signer_independently_authenticated": False,
        "production_promotion": "DENY_ALL",
    }
    check_panel(result, original_panel)
    return result


def check_panel(panel: dict, original_panel: dict) -> tuple[str, list[dict]]:
    original_digest, original_sources = _check_origin(original_panel)
    if not isinstance(panel, dict) or set(panel) != {
        "schema", "original_panel_digest", "dataset_file_sha256",
        "dataset_source_path",
        "selection_domain_sha256", "cases_per_class", "cases", "case_count",
        "new_source_rows_disjoint_from_previous_study", "selection_uses_model_predictions",
        "same_public_source_family", "chronological_future_claim",
        "foundation_pretraining_overlap_ruled_out",
        "source_signer_independently_authenticated", "production_promotion",
    }:
        raise ConfirmatoryError("unexpected or incomplete replication panel")
    if (panel["schema"] != SCHEMA or panel["original_panel_digest"] != original_digest
            or panel["dataset_file_sha256"] != CONFIRM_SOURCE[1]
            or panel["dataset_source_path"] != CONFIRM_SOURCE[0]
            or panel["selection_domain_sha256"] != sha(SELECTOR_DOMAIN)
            or panel["cases_per_class"] != CASES_PER_CLASS
            or panel["case_count"] != 2 * CASES_PER_CLASS
            or panel["new_source_rows_disjoint_from_previous_study"] is not True
            or panel["selection_uses_model_predictions"] is not False
            or panel["same_public_source_family"] is not True
            or panel["chronological_future_claim"] is not False
            or panel["foundation_pretraining_overlap_ruled_out"] is not False
            or panel["source_signer_independently_authenticated"] is not False
            or panel["production_promotion"] != "DENY_ALL"):
        raise ConfirmatoryError("source revision, cohort or authority mismatch")
    rows = panel["cases"]
    if not isinstance(rows, list) or len(rows) != 2 * CASES_PER_CLASS:
        raise ConfirmatoryError("new untouched cohort incomplete")
    counts = Counter()
    case_ids, digests = set(), set()
    for case in rows:
        if not isinstance(case, dict) or set(case) != {
            "case_id", "group_id", "source_digest", "joint_input_digest",
            "split", "label", "label_name", "joint_input",
        }:
            raise ConfirmatoryError("unbound source case")
        joint = case["joint_input"]
        if (not isinstance(joint, dict) or set(joint) != {"question", "options", "state"}
                or joint["question"] != QUESTION or joint["options"] != list(OPTIONS)
                or not isinstance(joint["state"], str)
                or type(case["label"]) is not int or case["label"] not in (0, 1)
                or case["split"] != "new_holdout"
                or case["label_name"] != joint["options"][case["label"]]
                or case["source_digest"] != _source_digest(joint["state"])
                or case["group_id"] != case["source_digest"]
                or case["case_id"] != case["source_digest"][:24]
                or case["joint_input_digest"] != sha(canonical(joint))
                or case["source_digest"] in original_sources
                or case["case_id"] in case_ids or case["source_digest"] in digests):
            raise ConfirmatoryError("tampered, duplicated or overlapping case")
        case_ids.add(case["case_id"])
        digests.add(case["source_digest"])
        counts[case["label"]] += 1
    if counts != Counter({0: CASES_PER_CLASS, 1: CASES_PER_CLASS}):
        raise ConfirmatoryError("class balance differs from frozen protocol")
    if [c["case_id"] for c in rows] != sorted(case_ids):
        raise ConfirmatoryError("noncanonical case order")
    return sha(canonical(panel)), rows


def main():
    parser = argparse.ArgumentParser(description="Pre-score extra untouched AG News rows")
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--holdout-parquet", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    check_new_source_file(args.holdout_parquet)
    original = json.loads(args.original.read_text(encoding="utf-8"))
    panel = create_panel(original, load_parquet(args.holdout_parquet))
    args.out.write_bytes(canonical(panel))
    print(json.dumps({"new_cohort_digest": sha(canonical(panel)),
                      "case_count": panel["case_count"],
                      "chronological_future_claim": False,
                      "production_promotion": "DENY_ALL"}, sort_keys=True))


if __name__ == "__main__":
    main()
