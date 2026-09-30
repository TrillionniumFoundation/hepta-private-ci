#!/usr/bin/env python3
"""Render/check cognitive-store status and dossier from a single state manifest.

--write is an authoring operation only. CI uses --check and never updates source.
Execution receipts remain immutable run artifacts rather than self-certified flags.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "docs/modules/cognitive.store"
OPERATION_STATUS = DIRECTORY / "OPERATION_STATUS.json"
READINESS = DIRECTORY / "READINESS.json"


def render(state: dict, plan: dict) -> dict[str, str]:
    lines = ["# cognitive.store current status", "", "Generated from `CURRENT_STATE.json`; do not hand-edit.", "",
             "Source presence is not execution, target-host qualification, or acceptance.", "",
             "| Gate | State |", "|---|---|"]
    for name, value in state["gates"].items():
        lines.append(f"| `{name}` | `{str(value).lower()}` |")
    lines += ["", "## Invariant traceability", "",
              "| Invariant | Source | Regression / measurement | Evidence scope |", "|---|---|---|---|"]
    for row in state["invariants"]:
        lines.append(f"| `{row['id']}` — {row['invariant']} | "
                     + "<br>".join(f"`{value}`" for value in row["sources"])
                     + " | " + "<br>".join(f"`{value}`" for value in row["tests"])
                     + f" | {row['scope']} |")
    lines += ["", "## Remaining external evidence", ""]
    lines += ["- " + value for value in state["externalEvidence"]]
    lines += ["", "The detailed architecture remains in `TECHNICAL.md`; this projection records its current",
              "source/execution boundary without replacing that design. See `EXECUTION_DOSSIER.md`.", ""]
    dossier = ["# cognitive.store execution dossier index", "",
               "Generated from `CURRENT_STATE.json` and `QUALIFICATION_PLAN.json`; this is not a pass receipt.", "",
               "Both lanes use the same frozen source and base. The merge lane verifies ordered parents",
               "and recomputes the merge tree. Every command has an exclusive record and bounded log.", "",
               "| Required record | Working directory | Command | Minimum observed tests |",
               "|---|---|---|---|"]
    for row in plan["commands"]:
        dossier.append(f"| `{row['record']}` | `{row['cwd']}` | `{' '.join(row['command'])}` | {row['minimumTests']} |")
    dossier += ["", "A v2 qualification manifest is retained even when work fails or is not executed.",
                "It binds source/base/tested commits and trees, workflow blob/SHA, runner image, toolchain,",
                "run ID/attempt, actual command exit codes, minimum/observed test counts, raw-log digests,",
                "and artifact digests. Missing/skipped/running evidence cannot become terminal-success.", "",
                "## Host and data-lifecycle boundary", "",
                "The process-exit regression uses the real writer and SQLite, but fixture authority.",
                "The post-rename regression injects a real Linux directory-fsync failure through",
                "the public recovery entry, but it is not selected-host filesystem evidence. A",
                "trusted target-host run must separately establish signer governance, witness",
                "reconciliation, filesystem fault injection, canary, restart, and strictly newer",
                "rollback generations.", "",
                "History profiles measure corrections, tombstones, growth, snapshots, and reopen cuts.",
                "They neither implement history pruning nor prove payload erasure in backups or derived artifacts.", ""]
    return {"CURRENT_STATUS.md": "\n".join(lines), "EXECUTION_DOSSIER.md": "\n".join(dossier)}


def validate_operation_status(mapping: dict) -> int:
    status = json.loads(OPERATION_STATUS.read_text(encoding="utf-8"))
    readiness = json.loads(READINESS.read_text(encoding="utf-8"))
    if status.get("schema") != "hepta.cognitive-store-operation-status.v1":
        raise SystemExit("unknown cognitive operation-status schema")
    if readiness.get("schema") != "hepta.cognitive-store-readiness.v1":
        raise SystemExit("unknown cognitive readiness schema")
    expected = {row["operation"] for row in mapping["operations"]}
    observed = set(status.get("operations", {}))
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        raise SystemExit(f"operation-status coverage drift: missing={missing}, extra={extra}")
    known = {row["id"] for row in readiness.get("knownRegressions", [])}
    dimensions = (
        "source_present",
        "compiled",
        "repository_qualified",
        "target_host_qualified",
        "released",
    )
    for name, row in status["operations"].items():
        if set(dimensions) - set(row):
            raise SystemExit("operation-status dimensions missing: " + name)
        if not all(isinstance(row[field], bool) for field in dimensions):
            raise SystemExit("operation-status dimension is not boolean: " + name)
        if not row["source_present"]:
            raise SystemExit("mapped source operation cannot be marked absent: " + name)
        if any(row[field] for field in dimensions[1:]):
            raise SystemExit("source documents cannot self-certify operation execution: " + name)
        regression = row.get("known_regression")
        if regression is not None and regression not in known:
            raise SystemExit("operation names an unknown regression: " + name)
        for field in ("last_tested_sha", "last_successful_run_id", "evidence_digest"):
            if row.get(field) is not None:
                raise SystemExit("unqualified operation embeds execution evidence: " + name)
    return len(observed)


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args()
    state = json.loads((DIRECTORY / "CURRENT_STATE.json").read_text(encoding="utf-8"))
    plan = json.loads((DIRECTORY / "QUALIFICATION_PLAN.json").read_text(encoding="utf-8"))
    if state.get("schema") != "hepta.cognitive-store-current-state.v1":
        raise SystemExit("unknown cognitive status schema")
    expected = render(state, plan)
    if args.write:
        for name, text in expected.items():
            (DIRECTORY / name).write_text(text, encoding="utf-8")
        return 0
    for name, text in expected.items():
        if (DIRECTORY / name).read_text(encoding="utf-8") != text:
            raise SystemExit("generated cognitive status drift: " + name)
    mapping = json.loads((DIRECTORY / "IMPLEMENTATION_MAP.json").read_text(encoding="utf-8"))
    bound = {row["path"] for row in mapping["sourceObjects"]}
    commands = {row["record"] for row in plan["commands"]}
    ids = set()
    for row in state["invariants"]:
        if row["id"] in ids:
            raise SystemExit("duplicate invariant: " + row["id"])
        ids.add(row["id"])
        for value in row["sources"] + row["tests"]:
            path = value.split(".rs::", 1)[0] + ".rs" if ".rs::" in value else value
            if path not in bound or not (ROOT / path).is_file():
                raise SystemExit("invariant lacks exact source binding: " + path)
            if ".rs::" in value:
                symbol = value.split(".rs::", 1)[1].split("::")[-1]
                if symbol not in (ROOT / path).read_text(encoding="utf-8"):
                    raise SystemExit("invariant symbol is absent: " + value)
        if not set(row["records"]).issubset(commands):
            raise SystemExit("invariant names a missing qualification command")
    operation_count = validate_operation_status(mapping)
    for name in ("productionImplementation", "productExecutionProved", "independentAcceptance", "activation", "release"):
        if state["gates"].get(name) is not False or mapping["claimBoundary"].get(name) is not False:
            raise SystemExit("source documents cannot self-certify execution or acceptance")
    print(json.dumps({"status": "passed", "invariants": len(ids),
                      "operations": operation_count, "executionClaim": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
