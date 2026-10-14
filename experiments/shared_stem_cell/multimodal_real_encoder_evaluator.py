"""Independent ingress for FUTURE_TARGETS; not imported by the train producer.

Must run with a separate operator-supplied sealed future corpus and in an
independent evaluation context. No claim that process isolation is enforced
by a Python module; access policy belongs to the executing host.
"""
import argparse
from pathlib import Path

from multimodal_real_encoder import run_offline


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline held-out text targets for independent evaluator")
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--profile-sha256", required=True)
    parser.add_argument("--model-snapshot", type=Path, required=True)
    parser.add_argument("--future-targets", type=Path, required=True)
    parser.add_argument("--future-targets-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run_offline(args.profile, args.profile_sha256, args.model_snapshot,
                args.future_targets, args.future_targets_sha256,
                args.output_dir, "future_targets")


if __name__ == "__main__":
    main()
