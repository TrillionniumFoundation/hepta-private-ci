"""Cross-check five-model raw predictions against independently replayed UCI rows.

This check binds reported sample identities and cohort fingerprints to exact
pinned-source bytes, NOT to a verified model forward, a model identity, or
future/publisher-independent data. Passing remains review-only and DENY_ALL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from replacement_gate import EXPECTED, SPLITS
from prepare_news_cohorts import ARCHIVE_SHA256, load_cohorts
from replacement_physical import choose_rows
from replacement_physical_audit import load_directory


def _frozen_rows_sha256(selected: dict[str, list[dict]]) -> str:
    """Reproduce the physical runner's exact ordered source-row digest."""
    identity = {
        split: [(r["source_id"], r["source_row_sha256"], r["label"])
                for r in selected[split]]
        for split in SPLITS
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def assess_source_binding(observations: Any, manifest: Any,
                          selected: Any, per_split: int) -> dict:
    errors = []
    if (not isinstance(manifest, dict)
            or manifest.get("source_archive_sha256") != ARCHIVE_SHA256):
        errors.append("archive provenance not bound to pinned upstream bytes")
    if (type(per_split) is not int
            or per_split != 0 and not (8 <= per_split <= 128 and per_split % 4 == 0)):
        errors.append("unregistered sample-size contract")
    if not isinstance(selected, dict) or set(selected) != set(SPLITS):
        errors.append("replayed source cohorts missing or changed")
    if not isinstance(observations, dict) or set(observations) != set(EXPECTED):
        errors.append("five raw model arms missing or substituted")
    if errors:
        return _result(errors)

    try:
        frozen_sha = _frozen_rows_sha256(selected)
        for split in SPLITS:
            source_rows = selected[split]
            if (not isinstance(source_rows, list) or not source_rows
                    or per_split != 0 and len(source_rows) != per_split):
                raise ValueError(f"{split}: fixed cohort count mismatch")
            if len({row["source_id"] for row in source_rows}) != len(source_rows):
                raise ValueError(f"{split}: replay source IDs are not unique")
        for name in EXPECTED:
            result = observations[name]
            if not isinstance(result, dict):
                errors.append(f"{name}: raw result absent")
                continue
            if result.get("candidate") != name:
                errors.append(f"{name}: result candidate identity drift")
            if result.get("per_split_limit") != per_split:
                errors.append(f"{name}: sample plan differs from replay")
            if result.get("source_archive_sha256") != ARCHIVE_SHA256:
                errors.append(f"{name}: original archive pin differs from replay")
            if result.get("frozen_selected_rows_sha256") != frozen_sha:
                errors.append(f"{name}: reported source-row fingerprint differs from replay")
            observed = result.get("scores")
            if not isinstance(observed, dict) or set(observed) != set(SPLITS):
                errors.append(f"{name}: original five raw prediction splits missing")
                continue
            for split in SPLITS:
                claim = observed[split]
                if not isinstance(claim, dict) or not isinstance(claim.get("rows"), list):
                    errors.append(f"{name}:{split}: original prediction rows absent")
                    continue
                source_rows = selected[split]
                reported_rows = claim["rows"]
                if len(reported_rows) != len(source_rows):
                    errors.append(f"{name}:{split}: prediction count differs from replay")
                    continue
                for i, (src, raw) in enumerate(zip(source_rows, reported_rows, strict=True)):
                    if (not isinstance(raw, dict)
                            or raw.get("source_id") != src["source_id"]
                            or raw.get("source_group_id") != src["source_group_id"]
                            or raw.get("label") != src["label"]
                            or raw.get("is_ood") is not (split == "ood")
                            or raw.get("language") != "en"):
                        errors.append(f"{name}:{split}: row {i} not sourced from pinned UCI cohort")
                        break
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        errors.append(f"pinned-source replay rejected: {exc}")
    return _result(errors)


def _result(errors: list[str]) -> dict:
    return {
        "schema": "hepta.neuron.replacement-source-binding-audit.v1",
        "source_binding_preflight": "BLOCKED" if errors else "REVIEW_REQUIRED",
        "blockers": sorted(set(errors)),
        "physical_model_forward_independently_attested": False,
        "model_input_tensor_bytes_independently_attested": False,
        "prospective_non_english_or_retrieval_evaluation": False,
        "target_host_and_lifecycle_qualified": False,
        "authority": "DENY_ALL",
        "mode": "SHADOW_ONLY",
        "release": "HOLD_NO_GO",
        "production_activation_allowed": False,
        "all_six_production_blockers_closed": False,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-directory", type=Path, required=True)
    p.add_argument("--cohorts", type=Path, required=True)
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    try:
        observations = load_directory(args.input_directory)
        manifest, cohorts = load_cohorts(args.cohorts, archive=args.archive)
        per_splits = {item.get("per_split_limit")
                      for item in observations.values() if isinstance(item, dict)}
        if len(observations) != len(EXPECTED) or len(per_splits) != 1:
            raise ValueError("five arms and one common sample plan required")
        per_split = next(iter(per_splits))
        if type(per_split) is not int:
            raise ValueError("invalid original sample budget")
        selected = choose_rows(cohorts, per_split)
        report = assess_source_binding(observations, manifest, selected, per_split)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        report = _result([f"physical source replay unavailable or rejected: {exc}"])
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 1 if report["source_binding_preflight"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
