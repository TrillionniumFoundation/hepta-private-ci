"""JSONL request-to-Cell-address process. Request fields must be exactly three."""

import argparse
import json
from pathlib import Path
import sys
import time

from compact_router import CompactRouter, deterministic_decisions
from v5.router import Router


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--model", type=Path)
    mode.add_argument("--deterministic", action="store_true")
    mode.add_argument("--v5-model", type=Path)
    parser.add_argument("--sha256")
    args = parser.parse_args()
    if args.deterministic:
        predict = deterministic_decisions
    else:
        if not args.sha256:
            parser.error("a frozen artifact/manifest SHA256 is required")
        router = CompactRouter.load(args.model, args.sha256) if args.model else Router.load(args.v5_model, args.sha256)
        predict = router.decisions
    for line in sys.stdin:
        started = time.perf_counter_ns()
        try:
            if len(line.encode("utf-8")) > 32768:
                raise ValueError("JSONL request exceeds 32 KiB")
            request = json.loads(line)
            decision = predict([request])[0]
            decision["inference_ns"] = time.perf_counter_ns() - started
            decision["contract"] = "memory-cell-v5.six-operations"
            print(json.dumps(decision, sort_keys=True), flush=True)
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            print(json.dumps({"error": type(exc).__name__, "message": str(exc), "accepted": False, "accepted_intent": None}), flush=True)


if __name__ == "__main__":
    main()
