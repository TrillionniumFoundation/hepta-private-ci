"""Functional old-head evaluation wrapper; historical data, no acceptance grant."""
import argparse
from pathlib import Path

from ...abc_next.native.evaluate_candidate import evaluate


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("candidates", "protocol", "model", "data", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.candidates, args.model, args.data, args.output)
