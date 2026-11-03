"""Run the frozen MemoryCell experiments and seal raw, reproducible evidence."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

import numpy as np

from memory_cells.study import run_core, run_transfer, write_json


PACKAGE = Path(__file__).resolve().parent
REPO = PACKAGE.parents[1]


def sha_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_identity():
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
    ).strip()
    files = sorted(
        p
        for p in PACKAGE.rglob("*")
        if p.is_file()
        and (p.suffix == ".py" or p.name in {"PROTOCOL.json", "requirements.txt"})
        and not any(
            part.startswith(".scratch") or part == "results" for part in p.parts
        )
    )
    return {
        "commit": revision,
        "files": {p.relative_to(REPO).as_posix(): sha_file(p) for p in files},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="development plumbing run, not efficacy evidence",
    )
    parser.add_argument(
        "--stage",
        choices=("all", "core", "composition", "evolution", "transfer"),
        default="all",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error("output directory must be new; preserve previous and failed runs")
    protocol = json.loads((PACKAGE / "PROTOCOL.json").read_text())
    identity = source_identity()
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain", "--", str(PACKAGE)], cwd=REPO, text=True
    ).strip()
    if dirty and not args.smoke:
        parser.error(
            "commit research sources before formal execution; --smoke is development only"
        )
    output.mkdir(parents=True)
    if args.smoke:
        protocol.update(
            seeds=[9001],
            transfer_seeds=[9007],
            optimizer_steps=10,
            capacity_domain_sizes=[[3, 3]],
            primary_domain_sizes=[3, 3],
        )
    write_json(output / "protocol.json", protocol)
    write_json(output / "source_identity.json", identity)
    environment = {
        "python": sys.version,
        "numpy": np.__version__,
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "thread_environment": {
            name: os.environ.get(name)
            for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")
        },
        "gpu_used": False,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "development_smoke" if args.smoke else "frozen_protocol_research",
        "source_dirty": bool(dirty),
        "stage": args.stage,
    }
    write_json(output / "environment.json", environment)
    started = time.perf_counter()
    results = {}
    try:
        if args.stage in {"all", "core"}:
            results["core"] = run_core(protocol, output / "core", identity["commit"])
        if args.stage in {"all", "composition"}:
            from memory_cells.composition_study import run_composition

            results["composition"] = run_composition(
                protocol, output / "composition", identity["commit"], protocol["seeds"]
            )
        if args.stage in {"all", "evolution"}:
            from memory_cells.evolution_study import run_evolution

            results["evolution"] = run_evolution(
                protocol, output / "evolution", identity["commit"], protocol["seeds"]
            )
        if args.stage in {"all", "transfer"}:
            results["transfer"] = run_transfer(
                protocol, output / "transfer", identity["commit"], REPO
            )
        if source_identity()["files"] != identity["files"]:
            raise RuntimeError("research source bytes changed during execution")
        write_json(output / "results.json", results)
        status = {
            "execution": "completed",
            "seconds": time.perf_counter() - started,
            "scientific_criteria_are_separate": True,
            "general_memory_system_established": False,
        }
    except Exception as error:
        write_json(
            output / "execution_status.json",
            {
                "execution": "failed",
                "error_type": type(error).__name__,
                "error": str(error),
                "seconds": time.perf_counter() - started,
            },
        )
        raise
    write_json(output / "execution_status.json", status)
    inventory = {
        p.relative_to(output).as_posix(): {
            "bytes": p.stat().st_size,
            "sha256": sha_file(p),
        }
        for p in sorted(output.rglob("*"))
        if p.is_file()
    }
    write_json(
        output / "MANIFEST.json",
        {
            "schema": "memory-cell-research.evidence.v1",
            "source_commit": identity["commit"],
            "files": inventory,
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "execution_success_is_not_efficacy": True,
        },
    )
    print(json.dumps({"event": "run_completed", **status}), flush=True)


if __name__ == "__main__":
    main()
