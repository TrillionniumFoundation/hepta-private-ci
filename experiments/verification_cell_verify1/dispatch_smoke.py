"""Actual subprocess dispatch/label qualification on controlled file workloads.

No independent task sampling or physical-cost completeness is established.
The checker receives a public goal and candidate only, never a terminal label.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from .checker_dispatch import (
    CheckerBinding,
    CheckerReply,
    DispatchJournal,
    scheduler_identity,
)
from .checker_effects import CheckerSpec, EffectScope, PairedPanel, fit_checker_effects
from .contracts import canonical_json, digest
from .cost_ledger import CostItem, CostReceipt, summarize_costs
from .prospective import FrozenAttempt, ShadowJournal
from .shadow_risk import Prediction, Snapshot, Target, TerminalLabel
from .shadow_schedule import observation_context


CHECKER = "import json,sys; p=json.load(open(sys.argv[1])); print(json.dumps({'outcome':'pass' if p.get('value')==7 else 'fail'}))"
LABELER = "import json,sys; value=json.load(open(sys.argv[1])); print(json.dumps({'error': value != {'value':7}}))"
SCENARIOS = (
    "pass",
    "fail",
    "unknown",
    "invalid",
    "stale",
    "exception",
    "timeout",
    "pending",
    "blocked",
)


def run(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    raw, receipts, costs, rows = [], [], [], []

    def save(name, value):
        with (output / name).open("x", encoding="utf-8") as stream:
            stream.write(
                json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
            )

    def process(program, path, operation, timeout=10):
        start = time.monotonic_ns()
        argv = [sys.executable, "-I", "-c", program, str(path)]
        try:
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raw.append(
                dict(
                    operation_id=operation,
                    exception="TimeoutExpired",
                    argv=argv,
                    timeout_seconds=timeout,
                    started_ns=start,
                    finished_ns=time.monotonic_ns(),
                    exit_code=None,
                )
            )
            raise
        end = time.monotonic_ns()
        record = dict(
            operation_id=operation,
            argv=[sys.executable, "-I", "-c", program, str(path)],
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            started_ns=start,
            finished_ns=end,
        )
        raw.append(record)
        if result.returncode:
            raise RuntimeError("checker/label subprocess failed")
        return json.loads(result.stdout), digest(record)

    target = Target(
        "controlled-files",
        "terminal_file_wrong",
        1,
        digest({"policy": "frozen-no-repair"}),
    )
    risk = digest(
        {"probability": 0.5, "fit": "declared engineering prior, not learned"}
    )
    version, evaluator = (
        hashlib.sha256(CHECKER.encode()).hexdigest(),
        hashlib.sha256(LABELER.encode()).hexdigest(),
    )
    paths, snapshots = {}, {}
    for scenario in SCENARIOS:
        path = output / (scenario + ".json")
        path.write_text(canonical_json({"value": 8 if scenario == "fail" else 7}))
        paths[scenario] = path
        snapshots[scenario] = Snapshot(
            scenario,
            "smoke-heldout",
            hashlib.sha256(path.read_bytes()).hexdigest(),
            target,
            0,
            (1,),
        )
    sample = snapshots["pass"]
    scope = EffectScope(
        target.domain,
        target.event,
        0,
        1,
        target.continuation_policy_sha256,
        observation_context(sample),
    )
    checkers = (CheckerSpec("file-goal", version, 0.25),)
    panels = tuple(
        PairedPanel(
            str(i),
            "declared-fit",
            digest({"panel": i}),
            scope,
            ("file-goal",),
            (version,),
            ("fail" if i >= 2 else "pass",),
            i >= 2,
            digest({"label": i}),
            (digest({"check": i}),),
        )
        for i in range(4)
    )
    effects = fit_checker_effects(
        panels,
        scope=scope,
        checkers=checkers,
        training_groups=("declared-fit",),
        heldout_groups=("smoke-heldout",),
    )
    journal = ShadowJournal.create(
        output / "shadow.sqlite",
        target=target,
        roster=tuple(
            FrozenAttempt(s, "smoke-heldout", snapshots[s].subject_sha256)
            for s in SCENARIOS
        ),
        frontiers=(0,),
        risk_model_sha256=risk,
        checker_model_sha256=effects.model_sha256,
        scheduler_sha256=scheduler_identity(),
        producer_id="file-owner",
        evaluator_id="separate-label-process",
        evaluator_version_sha256=evaluator,
    )
    for snapshot in snapshots.values():
        journal.record(Prediction(snapshot, 0.5, risk))
    for scenario in SCENARIOS:
        path, snapshot = paths[scenario], snapshots[scenario]
        operation, calls, retained = scenario + "/check", [], []

        def read_snapshot(snap):
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            return digest(asdict(snap)) if actual == snap.subject_sha256 else actual

        def execute(op, snap):
            calls.append(op)
            if scenario == "timeout":
                process("import time;time.sleep(30)", path, op, timeout=0.05)
            value, evidence = process(CHECKER, path, op)
            reply = CheckerReply(
                op,
                "file-goal",
                version,
                digest(asdict(snap)),
                "unknown" if scenario == "unknown" else value["outcome"],
                evidence,
            )
            retained.append(reply)
            if scenario == "stale":
                path.write_text(canonical_json({"value": 8}))
            if scenario == "exception":
                raise RuntimeError("injected callback failure after subprocess")
            if scenario == "pending":
                raise KeyboardInterrupt("injected lost caller after subprocess")
            return {"invalid": True} if scenario == "invalid" else reply

        dispatch = DispatchJournal.create(
            output / (scenario + ".sqlite"),
            manifest_sha256=journal.manifest_sha256,
            risk_model_sha256=risk,
            checker_model_sha256=effects.model_sha256,
            scheduler_sha256=scheduler_identity(),
            effects_body_sha256=digest(asdict(effects)),
        )
        binding = (CheckerBinding("file-goal", version, execute),)
        args = (
            Prediction(snapshot, 0.5, risk),
            effects,
            (),
            ("accept", "reject"),
            ((0, 50), (5, 5)),
            10,
        )
        kwargs = dict(
            hard_checks_complete=scenario != "blocked",
            operation_id=operation,
            checkers=binding,
            read_snapshot=read_snapshot,
        )
        start, cpu = time.monotonic_ns(), time.process_time()
        try:
            result = dispatch.dispatch_one(*args, **kwargs)
        except KeyboardInterrupt:
            dispatch = DispatchJournal(output / (scenario + ".sqlite"))
            pending = dispatch.dispatch_one(*args, **kwargs)
            if len(calls) != 1 or pending["status"] != "pending":
                raise RuntimeError("pending dispatch was replayed")

            def authenticate_reply(op, reply, request_sha, config_sha):
                return (
                    op == operation
                    and reply == retained[0]
                    and request_sha == pending["request_sha256"]
                    and config_sha == dispatch.config_sha256
                )

            result = dispatch.reconcile(
                operation,
                retained[0],
                read_snapshot=read_snapshot,
                authenticate=authenticate_reply,
            )
        end, parent_cpu = time.monotonic_ns(), time.process_time() - cpu
        item = CostItem(
            operation, scenario, "checker", "host-parent", "smoke-monotonic"
        )
        costs.append(item)
        receipts.append(
            CostReceipt(
                item,
                "completed" if result["status"] == "completed" else "failed",
                start,
                end,
                parent_cpu,
                None,
                None,
                None,
                digest(result),
                (
                    "parent CPU excludes child CPU",
                    "memory energy and charges unmeasured",
                ),
            )
        )
        outcome = (result.get("observation") or {}).get("outcome")
        disposition = (
            "interrupted"
            if scenario == "pending"
            else (
                "accept"
                if outcome == "pass"
                else "reject"
                if outcome == "fail"
                else "unknown"
            )
        )
        journal.finish(scenario, disposition)
        start, cpu = time.monotonic_ns(), time.process_time()
        truth, evidence = process(LABELER, path, scenario + "/label")
        end, parent_cpu = time.monotonic_ns(), time.process_time() - cpu
        label = TerminalLabel(
            scenario,
            "smoke-heldout",
            snapshot.subject_sha256,
            target,
            disposition,
            truth["error"],
            1,
            evidence,
            None,
        )

        def authenticate(issuer, supplied, pinned_version, manifest):
            return (
                issuer == "separate-label-process"
                and supplied == label
                and pinned_version == evaluator
                and manifest == journal.manifest_sha256
            )

        journal.label(
            label, evaluator_id="separate-label-process", authenticate=authenticate
        )
        item = CostItem(
            scenario + "/label",
            scenario,
            "evaluation",
            "host-parent",
            "smoke-monotonic",
        )
        costs.append(item)
        receipts.append(
            CostReceipt(
                item,
                "completed",
                start,
                end,
                parent_cpu,
                None,
                None,
                None,
                evidence,
                (
                    "parent CPU excludes child CPU",
                    "memory energy and charges unmeasured",
                ),
            )
        )
        rows.append(
            dict(scenario=scenario, result=result, actual_subprocess_calls=len(calls))
        )
    costs.append(
        CostItem(
            "setup-fit-and-history", "shared", "fit", "host-parent", "smoke-monotonic"
        )
    )
    report = dict(
        schema="hepta.verify.dispatch-smoke.v1",
        rows=rows,
        subprocess_records=raw,
        cost_receipts=[asdict(row) for row in receipts],
        cost_roster=[asdict(row) for row in costs],
        cost_summary=summarize_costs(costs, receipts),
        shadow_report=journal.report(),
        controlled_workload=True,
        independent_real_task_evaluation=False,
        production_effects=0,
        scientific_admission="HOLD",
        full_physical_cost_complete=False,
    )
    expected = {
        "pass": "completed",
        "fail": "completed",
        "unknown": "completed",
        "invalid": "unknown",
        "stale": "unknown",
        "exception": "unknown",
        "timeout": "unknown",
        "pending": "completed",
        "blocked": "not_run",
    }
    for row in rows:
        if row["result"]["status"] != expected[row["scenario"]]:
            raise RuntimeError("unexpected dispatch outcome")
        if row["actual_subprocess_calls"] != (0 if row["scenario"] == "blocked" else 1):
            raise RuntimeError("duplicate or missing checker invocation")
    if len(raw) != 17 or report["shadow_report"]["known_labels"] != 9:
        raise RuntimeError("incomplete process or label roster")
    save("RESULT.json", report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = run(args.output)
    print(
        json.dumps(
            {
                "scenarios": len(report["rows"]),
                "subprocesses": len(report["subprocess_records"]),
                "scientific_admission": report["scientific_admission"],
            }
        )
    )


if __name__ == "__main__":
    main()
