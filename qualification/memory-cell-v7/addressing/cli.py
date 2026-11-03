"""Resolve a natural-language memory request into a pinned, owner-scoped plan."""

import argparse
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT.parent))
sys.path.insert(0, str(PROJECT.parents[1] / "memory-cell-v6"))

from addressing.model import IntentModel
from addressing.planner import AddressPlanner
from v6.encoder import MiniLMEncoder


def load(path, maximum):
    if (
        any(item.is_symlink() for item in (path, *path.parents))
        or not path.is_file()
        or path.stat().st_size > maximum
    ):
        raise ValueError("invalid bounded input file")
    return json.loads(path.read_bytes())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--model-digest", required=True)
    parser.add_argument("--encoder", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    registry = load(args.registry.absolute(), 16_000_000)
    request = load(args.request.absolute(), 16384)
    model = IntentModel.load(args.model, MiniLMEncoder(args.encoder), args.model_digest)
    print(
        json.dumps(
            AddressPlanner(model, registry).plan(request),
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
    )
