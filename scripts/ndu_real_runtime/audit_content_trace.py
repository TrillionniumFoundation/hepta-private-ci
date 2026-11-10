"""Read-only legacy WRITE_TEXT audit; hashes bind bytes, not observer authority.

The caller supplies an independently pinned artifact manifest. Original records
are never rewritten. Missing selection provenance remains unknown, even when a
serialized text happens to match exactly one recorded candidate.
"""

import argparse
import hashlib
import json
from pathlib import Path

from ndu_real_materials.common import read_relative, strict_json


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    return _sha(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    )


def _read(root, name, expected):
    raw = read_relative(root, name, limit=8 * 1024**2)
    if not isinstance(expected, str) or len(expected) != 64 or _sha(raw) != expected:
        raise ValueError("Artifact differs from caller-supplied SHA256")
    return raw, strict_json(raw)


def audit(root, pins, *, evaluator_sha256, reference=None):
    """Describe original payload/delivery/scorer links without revealing text."""
    if (
        not isinstance(evaluator_sha256, str)
        or len(evaluator_sha256) != 64
        or any(c not in "0123456789abcdef" for c in evaluator_sha256)
    ):
        raise ValueError("Expected evaluator identity must be a SHA256")

    def read(name):
        return _read(root, name, pins[name])

    _, trajectory = read("trajectory.json")
    steps = trajectory["steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= 8:
        raise ValueError("Original trajectory exceeds the episode bound")
    case_id = steps[0].get("case_id")
    if (
        not isinstance(case_id, str)
        or not case_id
        or trajectory.get("case_id", case_id) != case_id
        or any(
            step.get("case_id") != case_id or step.get("step") != index
            for index, step in enumerate(steps)
        )
    ):
        raise ValueError("Original trajectory action identities differ")
    target, target_sha256 = None, None
    if reference is not None:
        from ndu_real_materials.evaluator import canonical

        target_raw, target = read(reference)
        target_sha256 = _sha(target_raw)
        if canonical(target["expected_text"], target["field"]) is None:
            raise ValueError("Reference cannot be scored by the frozen normalizer")
    snapshots = []
    for index in range(len(steps) + 1):
        name = f"delivery-{index:02d}/"
        raw, delivery = read(name + "delivery.json")
        _, score = read(name + "evaluation.json")
        if (
            delivery.get("schema") != "ndu.real.delivery.v1"
            or score.get("schema") != "ndu.real.independent-evaluation.v1"
            or delivery.get("case_id") != case_id
            or score.get("case_id") != case_id
            or score.get("evaluator_source_sha256") != evaluator_sha256
            or (
                target is not None
                and (
                    target["case_id"] != case_id
                    or score.get("reference_sha256") != target_sha256
                )
            )
        ):
            raise ValueError("Original delivery/evaluator/reference identity differs")
        snapshots.append((raw, delivery, score))
    rows = []
    for index, step in enumerate(steps):
        action = step["action"]
        if action["action"] != "WRITE_TEXT":
            continue
        if (
            step.get("step") != index
            or step.get("case_id") != snapshots[index][1]["case_id"]
        ):
            raise ValueError("Original action identity differs from its snapshot")
        payload = action["arguments"]["text"]
        candidates = step.get("candidate_metadata")
        if not isinstance(payload, str) or len(payload.encode()) > 8192:
            raise ValueError("Original action text exceeds the frozen bound")
        if candidates is not None and (
            not isinstance(candidates, list) or not 1 <= len(candidates) <= 128
        ):
            raise ValueError("Original candidate list exceeds the frozen bound")
        _, delivery, score = snapshots[index + 1]
        candidate_matches = (
            None
            if candidates is None
            else sum(c["text"] == payload for c in candidates)
        )
        exact_available = delivered_exact = score_agrees = None
        if target is not None:
            expected = canonical(target["expected_text"], target["field"])
            exact_available = (
                None
                if candidates is None
                else any(
                    canonical(c["text"], target["field"]) == expected
                    for c in candidates
                )
            )
            delivered_exact = canonical(delivery["text"], target["field"]) == expected
            score_agrees = score.get("text_quality") == float(delivered_exact)
        rows.append(
            {
                "step": index,
                "candidate_set_sha256": None
                if candidates is None
                else _digest(candidates),
                "serialized_action_sha256": _digest(action),
                "delivered_bytes_sha256": _sha(snapshots[index + 1][0]),
                "serialized_text_matching_candidate_count": candidate_matches,
                "selection_provenance": "unknown_legacy_selected_index_not_recorded",
                "action_text_reached_delivery": payload == delivery["text"],
                "evaluator_received_delivery_bytes": score.get("delivery_sha256")
                == _sha(snapshots[index + 1][0]),
                "action_text_still_in_terminal_delivery": payload
                == snapshots[-1][1]["text"],
                "terminal_evaluator_received_delivery_bytes": snapshots[-1][2].get(
                    "delivery_sha256"
                )
                == _sha(snapshots[-1][0]),
                "normalized_reference_candidate_available": exact_available,
                "delivered_text_matches_reference": delivered_exact,
                "evaluator_text_score_agrees": score_agrees,
            }
        )
    return {
        "schema": "ndu.content.legacy-trace-audit.v1",
        "write_text": rows,
        "originals_modified": False,
        "selection_root_cause_established": False,
        "reference_checked": target is not None,
        "policy_benefit_established": False,
        "observer_authority_authenticated": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--expected-evaluator-sha256", required=True)
    parser.add_argument(
        "--reference", help="Optional caller-authorized private reference"
    )
    args = parser.parse_args(argv)
    _, pins = _read(args.root, args.manifest, args.expected_manifest_sha256)
    report = audit(
        args.root,
        pins,
        evaluator_sha256=args.expected_evaluator_sha256,
        reference=args.reference,
    )
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
