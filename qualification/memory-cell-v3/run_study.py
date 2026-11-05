"""Execute the frozen v3 protocol, retaining failed runs and exact source bytes."""

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
sys.path.insert(0, str(PACKAGE.parent / "memory-cell-v2"))
sys.path.insert(0, str(PACKAGE.parent / "memory-cell-research"))

from v3.evidence import (  # noqa: E402
    fingerprint,
    seal_run,
    source_identity,
    source_snapshot,
    verify_sources,
    write_json,
)


def run_routes(
    protocol, output, source_commit, seeds, *, base, support_digest, development
):
    from route_graph_study import run_route_graph_study
    from v2.encoder import MiniLMEncoder

    settings = protocol["routing_graph"]
    domains = (
        settings["development_domains"] if development else settings["formal_domains"]
    )
    sources = {}
    for name in domains:
        subdirectory = "held-economy" if name == "unemployment" else "numeric"
        sources[name] = json.loads(
            (PACKAGE / "sources" / subdirectory / f"{name}.json").read_bytes()
        )
    expected_source = json.loads(
        (PACKAGE.parent / "memory-cell-v2" / "MODEL_SOURCE.json").read_bytes()
    )
    expected_digest = fingerprint(
        json.dumps(
            expected_source, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    )["sha256"]
    encoder = MiniLMEncoder(base, expected_source_digest=expected_digest)
    root = output / "routing-graph"
    root.mkdir(parents=True, exist_ok=False)
    return {
        "runs": [
            run_route_graph_study(
                encoder,
                sources,
                root / f"seed-{seed}",
                seed=seed,
                source_commit=source_commit,
                support_digest=support_digest,
                development=development,
                rank=settings["rank"],
            )
            for seed in seeds
        ]
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base", type=Path, default=os.environ.get("MEMORY_CELL_BASE"))
    parser.add_argument("--native-binary", type=Path)
    parser.add_argument(
        "--stage",
        choices=(
            "all",
            "capacity",
            "routing_graph",
            "lifecycle",
            "structure",
            "native",
        ),
        default="all",
    )
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    args.output = args.output.absolute()
    if args.output.exists() or args.output.is_symlink():
        parser.error("output must be new; all failed and earlier runs are preserved")
    if args.stage in {"all", "routing_graph"} and args.base is None:
        parser.error("--base is required for the actual pinned MiniLM router")
    if args.stage in {"all", "native"} and args.native_binary is None:
        parser.error(
            "--native-binary is required for the actual compiled NeuronRuntime"
        )
    identity = source_identity(REPO)
    try:
        verify_sources(identity, REPO, development=args.development)
    except ValueError as error:
        parser.error(str(error) + "; formal experiments require committed source bytes")
    raw_protocol = (PACKAGE / "PROTOCOL.json").read_bytes()
    protocol = json.loads(raw_protocol)
    seeds = protocol["development_seeds"] if args.development else protocol["seeds"]
    requested = protocol["stages"] if args.stage == "all" else [args.stage]
    args.output.mkdir(parents=True, exist_ok=False)
    environment = {
        "python": sys.version,
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "onnxruntime", "tokenizers", "flatbuffers")
        },
        "gpu_used": False,
        "mode": "development_only" if args.development else "frozen_protocol_research",
        "selected_seeds": seeds,
        "stage": args.stage,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "thread_environment": {
            name: os.environ.get(name)
            for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")
        },
    }
    (args.output / "protocol.json").write_bytes(raw_protocol)
    write_json(args.output / "source_identity.json", identity)
    write_json(args.output / "environment.json", environment)
    write_json(
        args.output / "execution_status.json",
        {"execution": "running", "completed_stages": []},
    )
    results, failure = {}, None
    started = time.perf_counter()
    try:
        source_snapshot(args.output / "source_snapshot.zip", identity, REPO)
        for stage in requested:
            tick = time.perf_counter()
            print(
                json.dumps({"event": "stage_started", "stage": stage, "seeds": seeds}),
                flush=True,
            )
            if stage == "capacity":
                from v3.capacity_study import run_capacity

                data = run_capacity(
                    protocol,
                    args.output / "capacity",
                    identity["commit"],
                    seeds,
                    development=args.development,
                )
            elif stage == "routing_graph":
                data = run_routes(
                    protocol,
                    args.output,
                    identity["commit"],
                    seeds,
                    base=args.base,
                    support_digest=fingerprint(raw_protocol)["sha256"],
                    development=args.development,
                )
            elif stage == "lifecycle":
                from v3.lifecycle_study import run_lifecycle

                data = run_lifecycle(
                    protocol,
                    args.output,
                    identity["commit"],
                    seeds,
                    development=args.development,
                )
            elif stage == "structure":
                from structure_study import run_structure

                data = run_structure(
                    protocol,
                    args.output / "structure",
                    identity["commit"],
                    seeds,
                    development=args.development,
                )
            else:
                from native_study import run_native

                data = run_native(
                    protocol,
                    args.output / "native",
                    identity["commit"],
                    seeds,
                    binary_path=args.native_binary,
                    development=args.development,
                )
            results[stage] = {
                "source_commit": identity["commit"],
                "selected_seeds": seeds,
                "development_only": args.development,
                "wall_seconds": time.perf_counter() - tick,
                "data": data,
            }
            write_json(
                args.output / "execution_status.json",
                {"execution": "running", "completed_stages": list(results)},
            )
            print(
                json.dumps(
                    {
                        "event": "stage_completed",
                        "stage": stage,
                        "seconds": results[stage]["wall_seconds"],
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
