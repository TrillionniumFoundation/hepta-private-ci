"""Restore a physical-state checkpoint in a fresh interpreter and continue."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from experiments.hcsn_validation_r13_20261031.numerics.age_pde import AgePDE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--expected-identity", required=True)
    parser.add_argument("--target-step", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    document = json.loads(args.checkpoint.read_text())
    state = AgePDE.restore(document, args.expected_identity)
    initial_step = state.step
    state.advance_to_step(args.target_step)
    state.write_checkpoint(args.out)
    print(json.dumps({"initial_step": initial_step, "final_step": state.step,
                      "final_time": state.time, "grid_identity": state.identity_hash}))


if __name__ == "__main__":
    main()
