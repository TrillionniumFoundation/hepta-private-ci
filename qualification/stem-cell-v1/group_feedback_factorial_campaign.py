"""Four frozen pretrained Granite97 Group TRAIN policy arms.

Research-only: four separate actual model loads, frozen Encoder forwards,
Head/critic training and complete System2 evaluation. No production effects.
It deliberately pays duplicated full-run costs; no free reuse is claimed.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import json

from group_attention_campaign import OPTIMIZER_PROFILES, run
from group_feedback_factorial_review import MATRIX, review_factorial


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--output-root", required=True)
    ap.add_argument("--seed", type=int, default=41)
    ap.add_argument("--steps", type=int, default=120)
    ap.add_argument("--train-count", type=int, default=256)
    ap.add_argument("--heldout-count", type=int, default=96)
    ap.add_argument("--training-profile", choices=tuple(OPTIMIZER_PROFILES),
                    default="sgd_v1")
    ap.add_argument("--review-only", action="store_true")
    args = ap.parse_args()
    root = Path(args.output_root)
    if not args.review_only:
        root.mkdir(parents=True, exist_ok=False)
        for name, (terminal, feedback) in MATRIX.items():
            run(args.snapshot, root / name, seed=args.seed, steps=args.steps,
                train_count=args.train_count, heldout_count=args.heldout_count,
                terminal_guard=terminal, training_feedback_policy=feedback,
                training_profile=args.training_profile)
    if not root.is_dir() or not all((root / key).is_dir() for key in MATRIX):
        raise ValueError("four immutable original run directories required")
    result = review_factorial({k: root / k for k in MATRIX})
    with (root / "factorial-independent-review.json").open("x") as file:
        json.dump(result, file, sort_keys=True, allow_nan=False)
    print(json.dumps(dict(passed=result["passed"],
        source_consistent_not_independently_attested=True,
        production_promotion_permitted=False, output=str(root)), sort_keys=True))


if __name__ == "__main__":
    main()
