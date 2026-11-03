"""Execute a frozen v2 protocol and preserve both success and failure evidence."""

import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
import time


PACKAGE = Path(__file__).resolve().parent
REPO = PACKAGE.parents[1]
sys.path.insert(0, str(PACKAGE))
sys.path.insert(0, str(PACKAGE.parent / "memory-cell-research"))

from v2.evidence import (
    seal_run,
    source_identity,
    source_snapshot,
    verify_sources,
    write_json,
)  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base", type=Path, default=os.environ.get("MEMORY_CELL_BASE"))
    parser.add_argument(
        "--stage",
        choices=("all", "routing", "real", "growth", "external"),
        default="all",
    )
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error("output must be new; preserve all previous and failed runs")
    if args.stage in {"all", "real"} and args.base is None:
        parser.error("--base must point to the verified pinned MiniLM files")
    identity = source_identity(REPO)
    try:
        verify_sources(identity, REPO, development=args.development)
    except ValueError as error:
        parser.error(str(error) + "; commit all sources before formal execution")
    raw_protocol = (PACKAGE / "PROTOCOL.json").read_bytes()
    protocol = json.loads(raw_protocol)
    seeds = protocol["development_seeds"] if args.development else protocol["seeds"]
    environment = {
        "python": sys.version,
        "platform": platform.platform(),
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "onnxruntime", "tokenizers", "flatbuffers")
        },
        "cpu_count": os.cpu_count(),
        "gpu_used": False,
        "thread_environment": {
            name: os.environ.get(name)
            for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")
        },
        "mode": "development_only" if args.development else "frozen_protocol_research",
        "selected_seeds": seeds,
        "stage": args.stage,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "protocol.json").write_bytes(raw_protocol)
    write_json(args.output / "source_identity.json", identity)
    write_json(args.output / "environment.json", environment)
    started = time.perf_counter()
    results, failure = {}, None
    status = {"execution": "running"}
    write_json(args.output / "execution_status.json", status)
    try:
        source_snapshot(args.output / "source_snapshot.zip", identity, REPO)
        for stage in ("routing", "real", "growth", "external"):
            if args.stage not in {"all", stage}:
                continue
            print(
                json.dumps({"event": "stage_started", "stage": stage, "seeds": seeds}),
                flush=True,
            )
            stage_started = time.perf_counter()
            kwargs = {"development": args.development}
            if stage == "routing":
                from v2.router_study import run_routing as run
            elif stage == "real":
                from v2.real_study import run_real as run

                kwargs["base_path"] = args.base
            elif stage == "growth":
                from v2.growth import run_growth as run
            else:
                from v2.external_domains import run_external as run
            results[stage] = run(
                protocol, args.output, identity["commit"], seeds, **kwargs
            )
            print(
                json.dumps(
                    {
                        "event": "stage_completed",
                        "stage": stage,
                        "seconds": time.perf_counter() - stage_started,
                    }
                ),
                flush=True,
            )
        verify_sources(identity, REPO, development=args.development)
        write_json(args.output / "results.json", results)
        status = {
            "execution": "completed",
            "seconds": time.perf_counter() - started,
            "completed_stages": list(results),
            "general_memory_system_established": False,
        }
    except BaseException as error:
        failure = error
        status = {
            "execution": "aborted"
            if isinstance(error, (KeyboardInterrupt, SystemExit))
            else "failed",
            "seconds": time.perf_counter() - started,
            "completed_stages": list(results),
            "error_type": type(error).__name__,
            "error": str(error),
        }
        write_json(args.output / "partial_results.json", results)
    finally:
        write_json(args.output / "execution_status.json", status)
        seal = seal_run(args.output, identity)
        print(
            json.dumps({"event": "run_sealed", **status, "manifest": seal}), flush=True
        )
    if failure:
        raise failure


if __name__ == "__main__":
    main()
