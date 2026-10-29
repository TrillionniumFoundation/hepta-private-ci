"""Real rebuilt-binary diagnostic training and independent episode verification."""

import argparse
import json
from pathlib import Path

from experiments.continuous_boundary_policy.audit import audit_episode
from experiments.continuous_boundary_policy.audit_integrity import (
    checked_file,
    read_json,
    verify_checkpoint,
    verify_profile,
    verify_training_receipt,
)
from experiments.continuous_boundary_policy.audit_math import (
    expected_specs,
    reference,
    require,
    streams,
)
from experiments.continuous_boundary_policy.common import (
    ARMS,
    CONTROLS,
    canonical,
    save_json,
    sha,
)
from experiments.continuous_boundary_policy.smoke import run as original_smoke
from .identity import verify_binaries
from .sources import BINARY_SHA


def run(output, binaries):
    output = Path(output)
    verify_binaries(binaries)
    summary = original_smoke(output, binaries["native"], binaries["score"])
    ref = reference(expected_specs(991, "diagnostic", 1)[0])
    initial, slots, stream_id = streams(991, "diagnostic", 0, 4, ref)
    verified = []
    for arm in ARMS + CONTROLS:
        checkpoint, profile, cell = None, None, None
        if arm in ARMS:
            checkpoint = read_json(output, f"checkpoints/991/{arm}.json")
            cell = verify_checkpoint(checkpoint, 991, arm)
            receipt = read_json(output, f"training/991/{arm}/TRAINING.json")
            verify_training_receipt(
                receipt, 991, arm, candidate_indices=(1,), epochs=4, development_count=2
            )
            if arm == "native_sparse":
                checked_file(
                    output, checkpoint["profile_path"], checkpoint["profile_sha256"]
                )
                profile = read_json(output, checkpoint["profile_path"])
                verify_profile(profile, 991)
        checkpoint_sha = (
            sha((output / f"checkpoints/991/{arm}.json").read_bytes())
            if arm in ARMS
            else sha(canonical({"arm": arm}))
        )
        records = read_json(output, f"records/{arm}.json")
        require(len(records) == 4, "Incomplete diagnostic record roster")
        for index, record in enumerate(records):
            require(
                record["train_seed"] == 991
                and record["arm"] == arm
                and record["split"] == "diagnostic"
                and record["eval_seed"] == stream_id
                and record["checkpoint_sha256"] == checkpoint_sha
                and record["episode_id"] == f"991.diagnostic.c0.p{index}",
                "Diagnostic stream identity changed",
            )
            audit_episode(
                record,
                checkpoint,
                ref,
                BINARY_SHA["score"],
                profile=profile,
                cell=cell,
                expected_initial=int(initial[index]),
                expected_slots=slots[:, index],
            )
        verified.append({"arm": arm, "independently_verified_episodes": len(records)})
    result = {
        "schema": "hepta.boundary-policy-reproduction.diagnostic-audit.v1",
        "passed": True,
        "seed": 991,
        "binary_sha256": dict(BINARY_SHA),
        "registered_confirmation_accessed": False,
        "original_smoke_summary_sha256": sha((output / "SUMMARY.json").read_bytes()),
        "episodes_verified": sum(
            row["independently_verified_episodes"] for row in verified
        ),
        "training_receipts_verified": len(ARMS),
        "arms": verified,
        "files": {
            str(p.relative_to(output)): sha(p.read_bytes())
            for p in output.rglob("*")
            if p.is_file()
        },
        "scope": "diagnostic seed only; original real training/rollout and unchanged independent episode auditor",
    }
    require(
        summary["episodes"] == result["episodes_verified"] == 52,
        "Diagnostic count mismatch",
    )
    save_json(output / "REPRODUCTION_DIAGNOSTIC_AUDIT.json", result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--native-binary", type=Path, required=True)
    parser.add_argument("--score-binary", type=Path, required=True)
    args = parser.parse_args()
    result = run(
        args.output, {"native": args.native_binary, "score": args.score_binary}
    )
    print(json.dumps({key: value for key, value in result.items() if key != "files"}))


if __name__ == "__main__":
    main()
