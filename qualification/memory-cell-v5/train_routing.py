"""Train the fixed V5 candidates; never open an independent held directory."""

import argparse
import re
from pathlib import Path

from v5.config import DEFAULT_CONFIG
from v5.training import train_routing
from v5.contracts import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seeds", nargs="+", type=int, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--development", action="store_true")
    parser.add_argument("--candidate-names", nargs="+")
    args = parser.parse_args()
    if len(set(args.seeds)) != len(args.seeds):
        parser.error("duplicate seed")
    allowed = {8011, 8017} if args.development else set(DEFAULT_CONFIG["seeds"])
    if not set(args.seeds) <= allowed:
        parser.error("seeds are outside the declared development/formal partition")
    if not args.development and not re.fullmatch(r"[0-9a-f]{40}", args.source_commit):
        parser.error("formal training requires a frozen source commit identity")
    if args.candidate_names and not args.development:
        parser.error("candidate subsets are limited to disclosed development increments")
    if not args.development:
        from v5.training_guard import REQUIRED_TRAINING_SOURCES, verify_training_freeze

        frozen_before, identity_before = verify_training_freeze(args.source_commit)
    train_routing(args.output, args.seeds, source_commit=args.source_commit, development=args.development, candidate_names=args.candidate_names)
    if not args.development:
        frozen_after, identity_after = verify_training_freeze(args.source_commit)
        if frozen_before != frozen_after or identity_before != identity_after:
            raise ValueError("project freeze changed during formal training")
        write_json(Path(args.output) / "FORMAL_FREEZE_CHECK.json", {
            "schema": "memory-cell-v5.formal-training-freeze.v1",
            "source_commit": args.source_commit,
            "freeze_before": identity_before, "freeze_after": identity_after,
            "required_training_sources": list(REQUIRED_TRAINING_SOURCES),
            "validated_before_and_after_fitting": True,
            "held_materializer_called": False,
        })


if __name__ == "__main__":
    main()
