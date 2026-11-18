"""JSON stdio inference using unchanged retained research source and model gates."""

import argparse
import contextlib
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

LIMIT = 262144


def file_hash(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            value.update(block)
    return value.hexdigest()


def send(value):
    sys.stdout.buffer.write(
        json.dumps(value, sort_keys=True, allow_nan=False).encode() + b"\n"
    )
    sys.stdout.buffer.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--module-root", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    root, modules, run = (
        value.resolve(strict=True)
        for value in (args.artifact_root, args.module_root, args.run_dir)
    )
    core, research, helpers = (
        root / "candidate-qwen-03/scripts",
        root / "research-sft-v1-source",
        root / "e1e2-operation-helpers-04",
    )
    if not all(path.is_dir() for path in (core, research, helpers, modules, run)):
        raise ValueError("existing retained source and output directories required")
    pool, request_id, closed = None, None, False
    try:
        with contextlib.redirect_stdout(sys.stderr):
            sys.path[:0] = [str(core), str(research)]
            import cell_experiments

            cell_experiments.__path__.append(str(modules))
            import research_sft_contract_v1 as legacy

            legacy.bind_helpers(helpers)
            from cell_experiments import data
            from cell_experiments.online_v4.circuit_contract import (
                CellSpec,
                visible_request,
            )
            from cell_experiments.online_v4.shared_pool_v4 import SharedAdapterPool

            def inventory():
                return {
                    "legacy": legacy.sources(),
                    "online_v4": {
                        path.name: file_hash(path)
                        for path in sorted((modules / "online_v4").glob("*.py"))
                    },
                }

            source = inventory()
            modes = {
                "F": "final_answer",
                "T": "trajectory",
                "C": "controlled_correction",
            }
            paths = {
                cell: root
                / "research-sft-02/workers"
                / (mode + "-primary/research-model/manifest.json")
                for cell, mode in modes.items()
            }
            manifests = {
                cell: data._parse(path.read_bytes()) for cell, path in paths.items()
            }
            pool = SharedAdapterPool(manifests, root)
            cells = {}
            for cell, manifest in manifests.items():
                base, evidence = (
                    manifest["base_manifest"],
                    pool.parameter_evidence(cell),
                )
                cells[cell] = asdict(
                    CellSpec(
                        cell,
                        data.digest(manifest),
                        data.digest(base),
                        data.digest(base["files"]),
                        data.digest(base["runtime"]),
                        evidence["active_parameters"],
                        evidence["parameter_evidence_digest"],
                    )
                )
        send(
            {
                "status": "READY",
                "schema": "hepta.diagnostic-provider.v1",
                "pid": os.getpid(),
                "ppid": os.getppid(),
                "cells": cells,
                "pool": pool.snapshot(),
                "sources": source,
                "manifest_files": {
                    cell: {"path": str(path), "sha256": file_hash(path)}
                    for cell, path in paths.items()
                },
                "script_sha256": file_hash(__file__),
                "interpreter_sha256": file_hash(sys.executable),
                "evidence_scope": "actual_shared_adapter_pool",
                "source_gates_unchanged": True,
            }
        )
        for expected_id in range(1, 10001):
            raw = sys.stdin.buffer.readline(LIMIT + 1)
            if not raw or len(raw) > LIMIT or not raw.endswith(b"\n"):
                raise ValueError(
                    "bounded complete request line required; EOF is not close"
                )
            message = data._parse(raw)
            request_id = message.get("id")
            if type(request_id) is not int or request_id != expected_id:
                raise ValueError("request sequence differs")
            if inventory() != source:
                raise ValueError("retained provider source changed")
            if message == {"op": "close", "id": request_id}:
                tick = time.perf_counter()
                with contextlib.redirect_stdout(sys.stderr):
                    pool.close()
                closed = True
                send(
                    {
                        "status": "CLOSED",
                        "id": request_id,
                        "pid": os.getpid(),
                        "release_wall_seconds": time.perf_counter() - tick,
                        "source_inventory_unchanged": inventory() == source,
                    }
                )
                return
            if (
                set(message) != {"op", "id", "cell", "request", "call_dir"}
                or message["op"] != "generate"
            ):
                raise ValueError("unknown provider operation or fields")
            request = message["request"]
            if visible_request(request) != request or message["cell"] not in cells:
                raise ValueError(
                    "only declared Cells and whitelisted visible requests accepted"
                )
            directory = Path(message["call_dir"])
            resolved = directory.resolve(strict=True)
            if (
                not directory.is_absolute()
                or resolved != directory
                or not directory.is_dir()
                or run not in directory.parents
            ):
                raise ValueError("call directory must be an existing child of this run")
            with contextlib.redirect_stdout(sys.stderr):
                output = pool.generate(message["cell"], request, directory)
            send({"status": "OUTPUT", "id": request_id, "output": output})
        raise ValueError("provider request bound exceeded")
    except BaseException as error:
        traceback.print_exc(file=sys.stderr)
        send(
            {
                "status": "ERROR",
                "id": request_id,
                "error_type": type(error).__name__,
                "error": str(error),
                "cost_complete": False,
                "automatic_retry": False,
            }
        )
        raise
    finally:
        if pool is not None and not closed:
            with contextlib.redirect_stdout(sys.stderr):
                pool.close()


if __name__ == "__main__":
    main()
