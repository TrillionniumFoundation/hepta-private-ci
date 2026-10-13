"""Compatibility entrypoint for experiments 3 and 4.

The shared implementation lives in ``experiments/shared_stem_multimodal_system2``
so its JSON schemas and plan files remain together.  This entrypoint follows
the existing ``scripts/memory_cell`` convention used by the Stem and Reader
diagnostics and exposes a small Python API for CI or local smoke runs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT_ROOT = REPO_ROOT / "experiments" / "shared_stem_multimodal_system2"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.shared_stem_multimodal_system2 import runner  # noqa: E402


CONFIGS = {
    "multimodal_differentiation": EXPERIMENT_ROOT / "config" / "multimodal_differentiation.v1.json",
    "ndu_system2_ablation": EXPERIMENT_ROOT / "config" / "ndu_system2_ablation.v1.json",
}


def run_experiment(kind: str, observations: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate observations and produce a diagnostic-only receipt."""
    try:
        config_path = CONFIGS[kind]
    except KeyError as error:
        raise runner.ExperimentError(f"unknown experiment kind: {kind}") from error
    config = runner.validate_config(runner.read_json(config_path))
    return runner.make_receipt(config, observations, runner.digest(observations))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=tuple(CONFIGS))
    parser.add_argument("observations", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    try:
        rows, observations_digest = runner._load_jsonl(args.observations)
        config = runner.validate_config(runner.read_json(CONFIGS[args.kind]))
        receipt = runner.make_receipt(config, rows, observations_digest)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"receipt": str(args.output), "receipt_digest": receipt["receipt_digest"]}, sort_keys=True))
        return 0
    except runner.ExperimentError as error:
        parser.error(str(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
