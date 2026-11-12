"""Create-only prospective macro execution; reconciliation never launches actors.

Pins establish consistency, not owner attestation. Registered intervention seeds
are shared across arms; model/control RNG remains frozen in the deployment.
Observed elapsed costs include initialization, actions, scoring and admission.
Provider, energy and one-off costs remain unknown, including in fixture runs.
"""

from copy import deepcopy
import argparse
import json
from pathlib import Path
import time

from ndu_real_materials import common
from . import macro_cohort, macro_policy, macro_realization
from .content_identity import SELECTION_SCHEMA
from .macro_execution_plan import ROLES, check_inputs, validate_plan
from .metering import atomic_json
from .metacontrol_macro_contract import SEQUENCES, digest, read_pin, sha
from .metacontrol_native_pairs import bind_public_intervention


def _roster(plan, pin):
    for context in plan["cohort"]["contexts"]:
        for arm in plan["cohort"]["arms"]:
            operation = "macro-" + digest([pin, context, arm["arm_id"]])
            yield operation, context, arm


def _row(context, arm, plan, *, status="NOT_STARTED", operation=None, kind=None):
    return {
        **context,
        "arm_id": arm["arm_id"],
        "status": status,
        "execution_id": operation,
        "shared_sha256": digest(plan["cohort"]["shared"]),
        "content_sha256": arm["content_sha256"],
        "critic_context_sha256": arm["critic_context_sha256"],
        "quality": None,
        "task_cost": None,
        "full_cost_observed": False,
        "evidence_sha256": None,
        "evidence_kind": kind,
    }


def _capture(host, branch, case_id):
    original = host.public_step

    def public_step():
        raw = original()
        if raw is None:
            return None
        value = common.strict_json(raw)
        if (
            set(value)
            != {
                "schema",
                "case_id",
                "step",
                "remaining_seconds",
                "prepared_roi",
                "observation",
                "delivery",
                "text_committed",
                "forced_action",
            }
            or value["schema"] != "ndu.real.actor-step.v1"
            or value["case_id"] != case_id
            or type(value["step"]) is not int
            or not 0 <= value["step"] < 8
            or value["forced_action"] is not None
            or set(value["delivery"]) != {"schema", "case_id", "text", "image"}
            or set(value["observation"]) != {"path", "sha256", "bbox", "kind"}
            or (
                value["delivery"]["image"] is not None
                and set(value["delivery"]["image"])
                != {"path", "sha256", "bytes", "bbox"}
            )
        ):
            raise ValueError("Unexpected public host projection or forced policy input")
        with (branch / f"macro-public-{value['step']:02d}.json").open("xb") as stream:
            stream.write(raw)
        return raw

    host.public_step = public_step


def _admit(plan, branch, result, registered, profile, elapsed):
    case, config = registered["case"], plan["config"]
    if any(
        result.get(k) != v
        for k, v in {
            "original_operation_id": profile["original_operation_id"],
            "case_id": case["id"],
            "source_group_id": case["source_id"],
            "source_sha256": case["source_sha256"],
            "model_sha256": profile["model_sha256"],
        }.items()
    ):
        raise ValueError("Native result differs from its registered operation")
    steps = common.strict_json(common.read_relative(branch, "trajectory.json"))["steps"]
    first = steps[0]["controller"]
    macro, public = first["macro"], first["macro_public_state"]
    macro_policy._state(public)
    policy = common.strict_json(read_pin(profile["macro_policy"]))["policy"]
    if (
        macro not in SEQUENCES
        or public["features"] != steps[0]["public_features"]
        or public["remaining_seconds"] != plan["action_budget_seconds"]
        or any(
            s["controller"].get("macro") != macro
            or s["controller"].get("macro_policy") != policy
            or type(s["controller"].get("macro_step")) is not int
            or s["controller"]["macro_step"] != index
            or s["controller"].get("macro_deployment_sha256")
            != profile["macro_policy"]["sha256"]
            or s["controller"].get("macro_public_state_sha256") != digest(public)
            for index, s in enumerate(steps)
        )
    ):
        raise ValueError("Actual macro choice differs from frozen public deployment")
    launch = common.strict_json(common.read_relative(branch, "launch.json"))
    ready = common.strict_json(launch["stdout"].splitlines()[0])
    if (
        ready.get("macro_policy_sha256") != profile["macro_policy"]["sha256"]
        or ready.get("content_identity_profile") != SELECTION_SCHEMA
    ):
        raise ValueError(
            "Original readiness did not admit this frozen macro/content profile"
        )
    for index in range(len(steps)):
        raw = common.read_relative(branch, f"macro-public-{index:02d}.json")
        exchange = launch["host_exchanges"][index]
        if sha(raw) != exchange.get("reply_sha256") or len(raw) != exchange.get(
            "reply_bytes"
        ):
            raise ValueError(
                "Captured public bytes differ from original actor callback"
            )
    pin = common.binding(
        branch / f"macro-public-{SEQUENCES[macro].index('WRITE_TEXT'):02d}.json", branch
    )
    kwargs = dict(
        directory=branch,
        result=result,
        macro=macro,
        wall_seconds=elapsed,
        tariff=config["latency_weight"],
        config=config,
        expected_source_sha256=plan["observer_sha256"],
        public_input=pin,
        initial_public_input=common.binding(branch / "macro-public-00.json", branch),
    )
    macro_realization.observe_realization(**kwargs)
    score = result["score_components"]
    if (
        score.get("role") not in ROLES
        or score["role"] != case["role"]
        or score.get("reference_sha256") != case["reference"]["sha256"]
    ):
        raise ValueError("Independent admitted score does not release this reference")
    raw = common.read_bound(config["material_root"], case["reference"])
    target = branch / "posthoc-reference.json"
    with target.open("xb") as stream:
        stream.write(raw)
    return macro_realization.observe_realization(
        **kwargs, reference=common.binding(target, branch)
    )


def execute(
    plan, output, *, expected_plan_sha256, host_class=None, allow_fixtures=False
):
    """Execute a new frozen roster once. Existing output is never resumed/replayed."""
    plan = deepcopy(plan)
    cases, _ = validate_plan(plan, expected_plan_sha256)
    if host_class is not None and not allow_fixtures:
        raise ValueError("Injected hosts require explicit fixture opt-in")
    kind = "fixture" if host_class is not None else "native_macro"
    if host_class is None:
        from .episode import EpisodeHost

        host_class = EpisodeHost
    root = Path(output)
    if root.exists():
        raise FileExistsError("Existing execution is read-only; use reconcile")
    check_inputs(plan, root)
    root.mkdir(parents=True, exist_ok=False)
    atomic_json(root / "PLAN.json", plan)
    atomic_json(
        root / "RUN.json",
        {
            "schema": "ndu.real.macro-execution.v1",
            "plan_sha256": expected_plan_sha256,
            "evidence_kind": kind,
        },
    )
    for operation, context, arm in _roster(plan, expected_plan_sha256):
        check_inputs(plan, root)
        directory = root / operation
        directory.mkdir()
        start_pin = atomic_json(
            directory / "START.json",
            {
                "schema": "ndu.real.macro-start.v1",
                "plan_sha256": expected_plan_sha256,
                "operation_id": operation,
                "context": context,
                "arm_id": arm["arm_id"],
                "evidence_kind": kind,
                "time_ns": time.time_ns(),
            },
        )
        began, phase, result, report = time.perf_counter(), "constructing", None, None
        row = _row(context, arm, plan, operation=operation, status="UNKNOWN", kind=kind)
        error = None
        try:
            registered = cases[
                tuple(context[k] for k in ("source_id", "case_id", "seed"))
            ]
            profile = {
                **plan["profiles"][arm["arm_id"]],
                "original_operation_id": operation,
            }
            branch = directory / "native"
            host = host_class(
                deepcopy(plan["config"]),
                deepcopy(registered["case"]),
                deepcopy(profile),
                branch,
                training=False,
            )
            bind_public_intervention(
                host,
                plan["action_budget_seconds"],
                registered["read_condition"],
                context["seed"],
            )
            _capture(host, branch, registered["case"]["id"])
            phase = "executing"
            result = host.run()
            phase = "admitting"
            check_inputs(plan, root)
            report = _admit(
                plan, branch, result, registered, profile, time.perf_counter() - began
            )
            check_inputs(plan, root)
            evidence = atomic_json(directory / "REALIZATION.json", report)
            row.update(
                status="COMPLETED",
                quality=report["stages"]["execution"]["quality"],
                evidence_sha256=evidence,
            )
        except Exception as exception:
            row["status"] = "UNKNOWN" if phase == "executing" else "FAILED"
            error = {
                "type": type(exception).__name__,
                "message": str(exception),
                "phase": phase,
            }
        elapsed = time.perf_counter() - began
        row["task_cost"] = elapsed * plan["config"]["latency_weight"]
        atomic_json(
            directory / "TERMINAL.json",
            {
                "schema": "ndu.real.macro-terminal.v1",
                "start_sha256": start_pin,
                "row": row,
                "elapsed_seconds": elapsed,
                "full_cost_observed": False,
                "native_terminal_status": None
                if result is None
                else result.get("terminal_status"),
                "native_error": None if result is None else result.get("error"),
                "source_sha256": None
                if result is None
                else result.get("source_sha256"),
                "runner_error": error,
            },
        )
    return reconcile(
        root, expected_plan_sha256=expected_plan_sha256, allow_fixtures=allow_fixtures
    )


def reconcile(output, *, expected_plan_sha256, allow_fixtures=False):
    """Read retained inventory only; START without terminal is always UNKNOWN."""
    root = Path(output)
    plan = common.strict_json(common.read_relative(root, "PLAN.json"))
    validate_plan(plan, expected_plan_sha256)
    run = common.strict_json(common.read_relative(root, "RUN.json"))
    if (
        set(run) != {"schema", "plan_sha256", "evidence_kind"}
        or run["schema"] != "ndu.real.macro-execution.v1"
        or run["plan_sha256"] != expected_plan_sha256
        or run["evidence_kind"] not in ("fixture", "native_macro")
        or run["evidence_kind"] == "fixture"
        and not allow_fixtures
    ):
        raise ValueError(
            "Unexpected execution identity or unauthorized fixture evidence"
        )
    roster = list(_roster(plan, expected_plan_sha256))
    if {p.name for p in root.iterdir()} - {
        "PLAN.json",
        "RUN.json",
        *(r[0] for r in roster),
    }:
        raise ValueError("Unregistered or duplicate operation artifacts")
    rows, terminals = [], []
    for operation, context, arm in roster:
        row = _row(context, arm, plan)
        directory = root / operation
        if directory.exists():
            if directory.is_symlink() or {p.name for p in directory.iterdir()} - {
                "START.json",
                "TERMINAL.json",
                "REALIZATION.json",
                "native",
            }:
                raise ValueError("Duplicate/unknown execution outcome or symlink")
            if (directory / "START.json").exists():
                raw = common.read_relative(directory, "START.json")
                start = common.strict_json(raw)
                expected = {
                    "schema": "ndu.real.macro-start.v1",
                    "plan_sha256": expected_plan_sha256,
                    "operation_id": operation,
                    "context": context,
                    "arm_id": arm["arm_id"],
                    "evidence_kind": run["evidence_kind"],
                    "time_ns": start.get("time_ns"),
                }
                if start != expected or type(start["time_ns"]) is not int:
                    raise ValueError("Start identity differs from registered item")
                row.update(
                    status="UNKNOWN",
                    execution_id=operation,
                    evidence_kind=run["evidence_kind"],
                )
                if (directory / "TERMINAL.json").exists():
                    terminal = common.strict_json(
                        common.read_relative(directory, "TERMINAL.json")
                    )
                    actual = terminal["row"]
                    invariant = set(row) - {
                        "status",
                        "quality",
                        "task_cost",
                        "evidence_sha256",
                    }
                    if (
                        set(terminal)
                        != {
                            "schema",
                            "start_sha256",
                            "row",
                            "elapsed_seconds",
                            "full_cost_observed",
                            "native_terminal_status",
                            "native_error",
                            "source_sha256",
                            "runner_error",
                        }
                        or terminal["schema"] != "ndu.real.macro-terminal.v1"
                        or terminal["start_sha256"] != sha(raw)
                        or any(actual[k] != row[k] for k in invariant)
                        or actual["status"]
                        not in {"COMPLETED", "FAILED", "CANCELLED", "UNKNOWN"}
                        or terminal["full_cost_observed"] is not False
                        or not macro_cohort.number(terminal["elapsed_seconds"])
                        or terminal["elapsed_seconds"] < 0
                        or actual["task_cost"]
                        != terminal["elapsed_seconds"]
                        * plan["config"]["latency_weight"]
                    ):
                        raise ValueError(
                            "Terminal identity, status or measured cost differs"
                        )
                    if actual["status"] == "COMPLETED":
                        evidence = common.read_relative(directory, "REALIZATION.json")
                        report = common.strict_json(evidence)
                        if (
                            sha(evidence) != actual["evidence_sha256"]
                            or report["operation_id"] != operation
                            or report["observer_source_sha256"]
                            != plan["observer_sha256"]
                            or actual["quality"]
                            != report["stages"]["execution"]["quality"]
                        ):
                            raise ValueError(
                                "Completed outcome differs from retained admission"
                            )
                        for name, pin in report["artifact_sha256s"].items():
                            if (
                                sha(common.read_relative(directory / "native", name))
                                != pin
                            ):
                                raise ValueError("Admitted native artifact changed")
                        for pin in report["optional_inputs"].values():
                            common.read_bound(directory / "native", pin)
                    row = actual
                    terminals.append(terminal)
            elif any(directory.iterdir()):
                raise ValueError("Execution artifacts exist without a prior START")
        rows.append(row)
    return {
        "schema": "ndu.real.macro-execution-report.v1",
        "plan_sha256": expected_plan_sha256,
        "evidence_kind": run["evidence_kind"],
        "rows": rows,
        "terminals": terminals,
        "cohort": macro_cohort.evaluate(
            plan["cohort"],
            rows,
            expected_plan_sha256=plan["cohort_sha256"],
            allow_fixtures=allow_fixtures,
        ),
        "seed_scope": "registered READ intervention; model/control RNG frozen separately",
        "cost_scope": "elapsed initialization, selection, action, scoring, admission; provider/energy/oneoff unknown",
        "full_cost_observed": False,
        "native_owner_authenticated": False,
        "policy_efficacy_proved": False,
        "production_admission": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("execute", "reconcile"):
        command = commands.add_parser(name)
        if name == "execute":
            command.add_argument("--plan", required=True)
        command.add_argument("--output", required=True)
        command.add_argument("--expected-plan-sha256", required=True)
        command.add_argument("--allow-fixtures", action="store_true")
    args = parser.parse_args(argv)
    kwargs = {
        "expected_plan_sha256": args.expected_plan_sha256,
        "allow_fixtures": args.allow_fixtures,
    }
    report = (
        execute(common.strict_json(Path(args.plan).read_bytes()), args.output, **kwargs)
        if args.command == "execute"
        else reconcile(args.output, **kwargs)
    )
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
