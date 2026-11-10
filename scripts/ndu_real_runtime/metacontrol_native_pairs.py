"""Collect real READ/finalizer macro pairs, separate from primitive replay.

Both reset branches pay initialization and the same frozen WRITE_TEXT/STOP
suffix. Pins bind bytes, not native authority or complete physical costs.
"""

import argparse
import json
from pathlib import Path
import random
import time

from . import metacontrol_macro_contract
from .metacontrol_macro_contract import (
    SEQUENCES,
    digest,
    read_pin,
    validate_plan,
    write_once,
    observe_branch,
    sha,
)


def bind_public_intervention(host, budget, condition, seed):
    """Fix initial action budget; meter still includes startup and suffix costs."""
    original, overview = host.public_step, dict(host.observation)
    deadline, packet_digest = None, None

    def public_step():
        nonlocal deadline, packet_digest
        if host.steps and host.steps[-1]["action"]["action"] == "READ_ROI":
            if condition == "repeat":
                host.observation = dict(overview)
            elif condition == "noise":
                from PIL import Image

                box = host.observation["bbox"]
                size = (box[2] - box[0], box[3] - box[1])
                raw = random.Random(seed).randbytes(3 * size[0] * size[1])
                path = host.public / "declared-read-noise.png"
                if path.exists():
                    raise ValueError("Noise packet already exists")
                Image.frombytes("RGB", size, raw).save(path, format="PNG")
                host.observation = {
                    **host.observation,
                    "path": path.name,
                    "sha256": sha(path.read_bytes()),
                    "kind": "roi",
                }
            packet_digest = digest(host.observation)
        raw = original()
        if raw is None:
            return None
        public = json.loads(raw)
        now = time.perf_counter()
        if deadline is not None and now >= deadline:
            host.budget_stop = True
            return None
        if deadline is None:
            if public["remaining_seconds"] < budget:
                raise ValueError("Startup exhausted the reserved action budget")
            deadline = now + budget
            public["remaining_seconds"] = budget
        else:
            public["remaining_seconds"] = min(
                public["remaining_seconds"], max(0.0, deadline - now)
            )
        host.last_public = public
        return (
            json.dumps(public, separators=(",", ":"), allow_nan=False) + "\n"
        ).encode()

    host.public_step = public_step
    return lambda: packet_digest


def collect(plan, output, *, host_class=None):
    validate_plan(plan)
    for pin in plan["source_pins"]:
        read_pin(pin)
    read_pin(
        {"path": plan["profile"]["weights"], "sha256": plan["profile"]["model_sha256"]}
    )
    control = json.loads(
        read_pin(
            {
                "path": plan["profile"]["control_plan"],
                "sha256": plan["profile"]["control_plan_sha256"],
            }
        )
    )
    if control["control"].get("memory_mode") != "reset":
        raise ValueError("Actual frozen control plan must reset memory")
    native = host_class is None
    if native:
        from .episode import EpisodeHost

        host_class = EpisodeHost
    if native:
        import inspect

        host_path = Path(inspect.getfile(host_class)).resolve()
        runtime = host_path.parent
        if (
            Path(plan["config"]["scripts_root"]).resolve() != runtime.parent
            or Path(plan["config"]["repository_root"]).resolve()
            != runtime.parent.parent
        ):
            raise ValueError(
                "Subprocess actor/scorer roots differ from imported host inventory"
            )
        required = {
            str(Path(__file__).resolve()),
            str(host_path),
            str(Path(metacontrol_macro_contract.__file__).resolve()),
        }
        for directory in (runtime, runtime.parent / "ndu_real_materials"):
            required.update(
                str(p.resolve())
                for p in directory.glob("*.py")
                if not p.name.startswith("test_")
            )
        required.add(
            str(
                (
                    Path(plan["config"]["repository_root"])
                    / "experiments/multimodal_output_portfolio/joint_hepta_20261029/hepta_core.py"
                ).resolve()
            )
        )
        pinned = {str(Path(p["path"]).resolve()) for p in plan["source_pins"]}
        if not required <= pinned:
            raise ValueError("Collector and actual host source pins are required")
        evidence_kind = "native_module_execution"
    else:
        evidence_kind = "fixture"
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    write_once(root / "PLAN.json", plan)
    rows = []
    for pair in plan["pairs"]:
        branches = {}
        order = ["STOP", "READ"] if pair["seed"] % 2 == 0 else ["READ", "STOP"]
        for macro in order:
            directory = root / (pair["pair_id"] + "-" + macro)
            profile = {
                **plan["profile"],
                "original_operation_id": pair["pair_id"] + "/" + macro,
            }
            started = time.perf_counter()
            try:
                for pin in plan["source_pins"]:
                    read_pin(pin)
                read_pin(
                    {"path": profile["weights"], "sha256": profile["model_sha256"]}
                )
                read_pin(
                    {
                        "path": profile["control_plan"],
                        "sha256": profile["control_plan_sha256"],
                    }
                )
                host = host_class(
                    plan["config"],
                    pair["case"],
                    profile,
                    directory,
                    training=True,
                    exploration=SEQUENCES[macro],
                )
                packet = bind_public_intervention(
                    host,
                    plan["action_budget_seconds"],
                    pair["read_condition"],
                    pair["seed"],
                )
                result = host.run()
                if (
                    result["original_operation_id"] != profile["original_operation_id"]
                    or result["case_id"] != pair["case"]["id"]
                    or result["source_group_id"] != pair["case"]["source_id"]
                    or result["model_sha256"] != profile["model_sha256"]
                ):
                    raise ValueError(
                        "Actual operation, source, case or model differs from plan"
                    )
                observed = observe_branch(
                    directory,
                    result,
                    SEQUENCES[macro],
                    time.perf_counter() - started,
                    plan["latency_tariff"],
                    plan["config"],
                )
                observed.update(read_packet_sha256=packet(), status="completed")
                for pin in plan["source_pins"]:
                    read_pin(pin)
                read_pin(
                    {"path": profile["weights"], "sha256": profile["model_sha256"]}
                )
                read_pin(
                    {
                        "path": profile["control_plan"],
                        "sha256": profile["control_plan_sha256"],
                    }
                )
            except Exception as error:
                observed = {
                    "operation_id": profile["original_operation_id"],
                    "status": "failed_or_unresolved",
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "provider_cost": None,
                    "energy_joules": None,
                }
            observed["outer_wall_seconds"] = time.perf_counter() - started
            observed["latency_cost"] = (
                plan["latency_tariff"] * observed["outer_wall_seconds"]
            )
            observed["artifact_sha256s"] = {
                name: sha((directory / name).read_bytes())
                for name in ("result.json", "launch.json", "trajectory.json")
                if (directory / name).is_file()
            }
            branches[macro] = observed
        invariant = ("initial_public_state_sha256", "evaluator_sha256", "rubric_sha256")
        complete = all(b["status"] == "completed" for b in branches.values())
        matched = complete and all(
            branches["STOP"][k] == branches["READ"][k] for k in invariant
        )
        gain = (
            (
                branches["READ"]["quality"]
                - branches["STOP"]["quality"]
                - (branches["READ"]["latency_cost"] - branches["STOP"]["latency_cost"])
            )
            if matched
            else None
        )
        value = {
            "schema": "ndu.real.native-macro-pair.v1",
            "pair_id": pair["pair_id"],
            "split": pair["split"],
            "source_group": pair["case"]["source_id"],
            "read_condition": pair["read_condition"],
            "branches": branches,
            "evidence_kind": evidence_kind,
            "net_latency_gain": gain,
            "status": "completed" if matched else "failed_or_unresolved",
            "initial_public_state_matched": matched,
            "plan_sha256": digest(plan),
            "physical_full_cost_observed": False,
            "wall_cost_scope": "branch constructor, native run and artifact observation; outer collector/control-plane excluded",
            "native_owner_authentication": "SEPARATE_REQUIRED",
            "policy_evaluation_performed": False,
        }
        write_once(root / (pair["pair_id"] + ".json"), value)
        rows.append(value)
    summary = {
        "planned_pairs": len(rows),
        "completed_pairs": sum(r["status"] == "completed" for r in rows),
        "policy_benefit_qualified": False,
        "production_admission": False,
        "evidence_kind": evidence_kind,
        "scope": "fixed macro collection; not prospective learned-policy evaluation",
    }
    write_once(root / "SUMMARY.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    plan = json.loads(
        read_pin({"path": args.plan, "sha256": args.expected_plan_sha256})
    )
    print(json.dumps(collect(plan, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
