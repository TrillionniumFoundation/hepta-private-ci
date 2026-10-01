#!/usr/bin/env python3
"""Validate bounded fuzz execution separately from initial seed replay."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

MAX_RUNS = 1_000_000
TOOLCHAIN = "nightly-2026-09-20"
CARGO_FUZZ_VERSION = "0.12.0"
RUN_KEYS = {"types": "canonicalValidate", "wire": "platformTypesJson"}
SEED_LINE = re.compile(r"^INFO: seed corpus: files:\s*(\d+)\b", re.MULTILINE)
INITED_LINE = re.compile(r"^#(\d+)\s+INITED\b([^\n]*)$", re.MULTILINE)
DONE_LINE = re.compile(r"^#(\d+)\s+DONE\b([^\n]*)$", re.MULTILINE)


def run_budget(value: object) -> int:
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*", value):
        value = int(value)
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= MAX_RUNS
    ):
        raise ValueError(
            f"fuzz run budget must be a positive integer <= {MAX_RUNS}: {value!r}"
        )
    return value


def _seed_counts(output: Path) -> tuple[bytes, dict[str, int]]:
    path = output / "corpus-seeds.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError("fuzz seed receipt must be a regular non-symlink file")
    raw = path.read_bytes()
    receipt = json.loads(raw)
    if (
        receipt.get("schema") != "hepta.platform-types.fuzz-corpus.v1"
        or receipt.get("schemaVersion") != 1
    ):
        raise ValueError("unsupported fuzz seed receipt")
    seeds = receipt.get("seeds")
    if not isinstance(seeds, list) or not seeds:
        raise ValueError("missing fuzz seeds")
    counts = {target: 0 for target in RUN_KEYS}
    for row in seeds:
        if not isinstance(row, dict) or row.get("target") not in counts:
            raise ValueError("invalid fuzz seed lane")
        counts[row["target"]] += 1
    if any(count == 0 for count in counts.values()):
        raise ValueError("both fuzz lanes require seeds")
    return raw, counts


def check_budgets(output: Path, types: object, wire: object) -> dict[str, int]:
    budgets = {"types": run_budget(types), "wire": run_budget(wire)}
    _, counts = _seed_counts(output)
    for target, budget in budgets.items():
        # Coarse preflight only: actual initialization may replay inputs for LSan.
        if budget <= counts[target] + 1:
            raise ValueError(
                f"{target} fuzz budget does not exceed initial seed replay"
            )
    return budgets


def execution_counts(raw: bytes, requested: int, seeds: int) -> dict[str, int]:
    requested = run_budget(requested)
    if requested <= seeds + 1:
        raise ValueError("fuzz budget does not exceed initial seed replay")
    text = raw.decode("utf-8", errors="replace")
    seed_lines = list(SEED_LINE.finditer(text))
    initial_lines = list(INITED_LINE.finditer(text))
    done_lines = list(DONE_LINE.finditer(text))
    if (
        len(seed_lines) != 1
        or seed_lines[0].group(1) != str(seeds)
        or len(initial_lines) != 1
        or len(done_lines) != 1
        or not seed_lines[0].start() < initial_lines[0].start() < done_lines[0].start()
    ):
        raise ValueError(
            "fuzz log must bind one seed count and ordered unique INITED/DONE counters"
        )
    initialized = int(initial_lines[0].group(1))
    executed = int(done_lines[0].group(1))
    if not requested <= executed <= MAX_RUNS or not 0 < initialized < executed:
        raise ValueError(
            "fuzz DONE execution count is insufficient or exceeds the bounded cap"
        )
    if re.search(r"\bcov:\s*[1-9][0-9]*\b", done_lines[0].group(2)) is None:
        raise ValueError(
            "terminal fuzz execution has no instrumentation coverage counter"
        )
    return {
        "executedRuns": executed,
        "initialCorpusFiles": seeds,
        "initializationExecutions": initialized,
        "postInitializationExecutionRuns": executed - initialized,
    }


def check_toolchain(toolchain: object, version: object) -> None:
    if toolchain != TOOLCHAIN or version != CARGO_FUZZ_VERSION:
        raise ValueError(
            "fuzz qualification requires its pinned toolchain and cargo-fuzz version"
        )


def validate_fuzz_summary(value: dict[str, object], output: Path) -> None:
    if (
        value.get("schema") != "hepta.platform-types.coverage-fuzz.v2"
        or value.get("schemaVersion") != 2
        or value.get("module") != "platform.types"
        or value.get("status") != "passed"
        or value.get("executionPolicy") != "bounded_runs_beyond_initialization_v1"
    ):
        raise ValueError("invalid bounded fuzz summary header")
    check_toolchain(value.get("toolchain"), value.get("cargoFuzzVersion"))
    runs = value.get("runs")
    if not isinstance(runs, dict) or set(runs) != set(RUN_KEYS.values()):
        raise ValueError("fuzz summary requires both run budgets")
    budgets = check_budgets(output, runs[RUN_KEYS["types"]], runs[RUN_KEYS["wire"]])
    seed_raw, counts = _seed_counts(output)
    if value.get("corpusSeeds") != {
        "receipt": "corpus-seeds.json",
        "receiptSha256": hashlib.sha256(seed_raw).hexdigest(),
        "counts": counts,
    }:
        raise ValueError("fuzz seed receipt binding mismatch")
    targets = value.get("targets")
    if not isinstance(targets, list) or len(targets) != len(RUN_KEYS):
        raise ValueError("fuzz summary requires both execution logs")
    for record, target in zip(targets, RUN_KEYS):
        if (
            not isinstance(record, dict)
            or record.get("target") != target
            or record.get("log") != f"{target}.log"
        ):
            raise ValueError("fuzz execution lane/log mismatch")
        log = output / f"{target}.log"
        if log.is_symlink() or not log.is_file():
            raise ValueError("fuzz execution log must be a regular non-symlink file")
        raw = log.read_bytes()
        expected = {
            "logSha256": hashlib.sha256(raw).hexdigest(),
            "logBytes": len(raw),
            **execution_counts(raw, budgets[target], counts[target]),
        }
        if any(record.get(key) != item for key, item in expected.items()):
            raise ValueError("fuzz execution evidence differs from its bound log")


def build_summary(
    output: Path, toolchain: str, version: str, types: object, wire: object
) -> dict[str, object]:
    budgets = check_budgets(output, types, wire)
    seed_raw, counts = _seed_counts(output)
    targets = []
    for target in RUN_KEYS:
        log = output / f"{target}.log"
        raw = log.read_bytes()
        targets.append(
            {
                "target": target,
                "log": log.name,
                "logSha256": hashlib.sha256(raw).hexdigest(),
                "logBytes": len(raw),
                **execution_counts(raw, budgets[target], counts[target]),
                "artifactFiles": sorted(
                    str(path.relative_to(output))
                    for path in (output / target / "artifacts").glob("**/*")
                    if path.is_file()
                ),
            }
        )
    value: dict[str, object] = {
        "schema": "hepta.platform-types.coverage-fuzz.v2",
        "schemaVersion": 2,
        "module": "platform.types",
        "toolchain": toolchain,
        "cargoFuzzVersion": version,
        "runs": {RUN_KEYS[target]: count for target, count in budgets.items()},
        "executionPolicy": "bounded_runs_beyond_initialization_v1",
        "corpusSeeds": {
            "receipt": "corpus-seeds.json",
            "receiptSha256": hashlib.sha256(seed_raw).hexdigest(),
            "counts": counts,
        },
        "wireDecoders": [
            "PromptDeliveryObservationV2",
            "RuntimeTopologyCandidateV1",
            "RandomStreamManifestV1",
            "ExternalSystemManifestV1",
            "SensorCalibrationManifestV1",
        ],
        "targets": targets,
        "status": "passed",
        "claimBoundary": "bounded exact-candidate libFuzzer execution; not exhaustive proof or coverage gain",
    }
    validate_fuzz_summary(value, output)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    budgets = commands.add_parser("budgets")
    budgets.add_argument("types")
    budgets.add_argument("wire")
    budgets.add_argument("toolchain")
    budgets.add_argument("version")
    preflight = commands.add_parser("preflight")
    preflight.add_argument("output", type=Path)
    preflight.add_argument("types")
    preflight.add_argument("wire")
    summary = commands.add_parser("summary")
    summary.add_argument("output", type=Path)
    summary.add_argument("toolchain")
    summary.add_argument("version")
    summary.add_argument("types")
    summary.add_argument("wire")
    args = parser.parse_args()
    try:
        if args.command == "budgets":
            run_budget(args.types)
            run_budget(args.wire)
            check_toolchain(args.toolchain, args.version)
        elif args.command == "preflight":
            check_budgets(args.output, args.types, args.wire)
        else:
            value = build_summary(
                args.output, args.toolchain, args.version, args.types, args.wire
            )
            (args.output / "summary.json").write_text(
                json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f"platform.types fuzz evidence: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
