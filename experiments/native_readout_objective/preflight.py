"""Numerical preflight and old-record readout parity; no new efficacy study."""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import time
import unittest

import numpy as np

from .head import Q, actions, q24_scores
from . import test_head


def run(old_evidence_root, output):
    output = Path(output)
    if output.exists():
        raise ValueError("Preserve preflight receipts; output must not exist")
    started, cpu_started = time.perf_counter(), time.process_time()
    captured = io.StringIO()
    tests = unittest.TextTestRunner(stream=captured, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromModule(test_head)
    )
    receipt = {
        "schema": "hepta.native-readout-objective.preflight.v1",
        "scope": "numerical unit checks plus arithmetic replay of published old records",
        "new_training_or_confirmation_samples": 0,
        "native_kernel_or_ndu_executed": False,
        "unit_tests": {
            "count": tests.testsRun,
            "passed": tests.wasSuccessful(),
            "log": captured.getvalue(),
        },
        "record_parity": [],
        "source_sha256": {},
    }
    for path in sorted(Path(__file__).parent.glob("*.py")):
        receipt["source_sha256"][path.name] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    study = (Path(old_evidence_root) / "study").resolve()
    checkpoints = sorted((study / "checkpoints").glob("*/native_sparse.json"))
    if len(checkpoints) != 8:
        raise ValueError(
            "Expected the eight original published native reference checkpoints"
        )
    for checkpoint_path in checkpoints:
        checkpoint_bytes = checkpoint_path.read_bytes()
        checkpoint_sha = hashlib.sha256(checkpoint_bytes).hexdigest()
        checkpoint = json.loads(checkpoint_bytes)
        profile_path = (study / checkpoint["profile_path"]).resolve()
        if not profile_path.is_relative_to(study):
            raise ValueError("Profile escaped recovered study")
        profile_bytes = profile_path.read_bytes()
        if hashlib.sha256(profile_bytes).hexdigest() != checkpoint["profile_sha256"]:
            raise ValueError("Original profile identity mismatch")
        profile = json.loads(profile_bytes)
        if any(profile["head_weights_q24"][2]) or profile["head_bias_q24"][2] != 0:
            raise ValueError("Original STOP head was not zero")
        weights = (
            np.vstack(
                (
                    np.asarray(profile["head_weights_q24"][:2]).T,
                    profile["head_bias_q24"][:2],
                )
            )
            / Q
        )
        for split in ("test_id", "test_ood"):
            path = (
                study
                / "episodes"
                / str(checkpoint["seed"])
                / "native_sparse"
                / f"{split}.jsonl.gz"
            )
            total, episodes, mismatch_scores, mismatch_actions = 0, 0, 0, 0
            with gzip.open(path, "rt") as stream:
                for line in stream:
                    episode = json.loads(line)
                    if episode["checkpoint_sha256"] != checkpoint_sha:
                        raise ValueError("Old trajectory/checkpoint identity mismatch")
                    steps = episode["steps"]
                    computed = q24_scores([s["activation_q24"] for s in steps], weights)
                    expected = np.asarray(
                        [s["scores_q24"] for s in steps], dtype=np.int64
                    )
                    mismatch_scores += int(np.count_nonzero(computed != expected))
                    expected_actions = np.asarray(
                        [("wait", "repair", "stop").index(s["action"]) for s in steps]
                    )
                    mismatch_actions += int(
                        np.count_nonzero(actions(computed) != expected_actions)
                    )
                    total += len(steps)
                    episodes += 1
            receipt["record_parity"].append(
                {
                    "seed": checkpoint["seed"],
                    "split": split,
                    "path": str(path.relative_to(study)),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "checkpoint_sha256": checkpoint_sha,
                    "profile_sha256": checkpoint["profile_sha256"],
                    "episodes": episodes,
                    "steps": total,
                    "score_scalar_mismatches": mismatch_scores,
                    "action_mismatches": mismatch_actions,
                }
            )
    receipt["passed"] = tests.wasSuccessful() and all(
        r["score_scalar_mismatches"] == r["action_mismatches"] == 0
        for r in receipt["record_parity"]
    )
    receipt["total_old_record_steps"] = sum(
        r["steps"] for r in receipt["record_parity"]
    )
    receipt["python_cpu_seconds"] = time.process_time() - cpu_started
    receipt["wall_seconds"] = time.perf_counter() - started
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(receipt, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    if not receipt["passed"]:
        raise ValueError("Preflight failed; receipt preserved")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.old_evidence_root, args.output)
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "unit_tests": result["unit_tests"]["count"],
                "old_record_steps": result["total_old_record_steps"],
            }
        )
    )
