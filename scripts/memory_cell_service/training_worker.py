#!/usr/bin/env python3
"""Run the bounded local training worker; its durable queue survives restarts."""

import argparse
import json
import time

from memory_service import MemoryService
from service_types import MemoryCellRoleV1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--cell-id", default="memory")
    parser.add_argument(
        "--role", choices=[r.value for r in MemoryCellRoleV1], default="semantic"
    )
    parser.add_argument("--base", required=True)
    parser.add_argument("--worker-id", default="local")
    parser.add_argument("--steps", type=int, default=128)
    parser.add_argument("--rank", type=int, default=8)
    parser.add_argument("--seed", type=int, default=2718)
    parser.add_argument("--learning-rate", type=float, default=0.001)
    parser.add_argument("--lease-seconds", type=int, default=3600)
    parser.add_argument("--poll-seconds", type=float, default=2)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not 0.1 <= args.poll_seconds <= 30:
        parser.error("poll-seconds must be between 0.1 and 30")
    service = MemoryService(args.root, args.scope, args.cell_id, args.role)
    while True:
        result = service.work_once(
            args.base,
            worker_id=args.worker_id,
            lease_seconds=args.lease_seconds,
            steps=args.steps,
            rank=args.rank,
            seed=args.seed,
            learning_rate=args.learning_rate,
        )
        print(json.dumps(result, sort_keys=True, allow_nan=False), flush=True)
        if args.once:
            return
        if result["status"] == "idle":
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
