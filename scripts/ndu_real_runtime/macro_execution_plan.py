"""Validate prospective macro registrations and frozen inputs without execution."""

from dataclasses import asdict
from pathlib import Path, PurePosixPath

from ndu_real_materials import common
from . import macro_actor, macro_cohort, macro_policy, macro_realization
from .controllers import ACTIONS, ControlPlan
from .critic_context import context_digest
from .metacontrol_macro_contract import SEQUENCES, digest, read_pin, sha
from .objective import utility_profile

ROLES = {"train", "development", "retention_validation"}


def source_inventory(config):
    """Freeze actual imported runtime/material sources and the actor's core."""
    runtime = Path(__file__).resolve().parent
    if (
        Path(config["scripts_root"]).resolve() != runtime.parent
        or Path(config["repository_root"]).resolve() != runtime.parent.parent
    ):
        raise ValueError("Configured subprocess roots differ from imported sources")
    paths = {
        p.resolve()
        for directory in (runtime, runtime.parent / "ndu_real_materials")
        for p in directory.glob("*.py")
        if not p.name.startswith("test_")
    }
    paths.add(
        runtime.parents[1]
        / "experiments/multimodal_output_portfolio/joint_hepta_20261029/hepta_core.py"
    )
    return [{"path": str(p), "sha256": sha(p.read_bytes())} for p in sorted(paths)]


def shared_context(config, control):
    """Identity of the executing legal rules, objective, finalizer and tariff."""
    return {
        **macro_actor.host_context(config, digest(utility_profile(control))),
        "action_sha256": macro_policy.ACTION_SHA256,
        "legal_actions_sha256": digest(
            {
                "schema": "ndu.real.macro-legal-actions.v1",
                "actions": ACTIONS,
                "macros": SEQUENCES,
                "codec_sha256": macro_actor.codec_sha256(),
                "actor_sha256": sha(Path(__file__).with_name("actor.py").read_bytes()),
            }
        ),
    }


def validate_plan(plan, pin):
    """Check the external freeze and complete unsealed registration, without I/O."""
    if (
        digest(plan) != pin
        or set(plan)
        != {
            "schema",
            "cohort",
            "cohort_sha256",
            "config",
            "registered_cases",
            "profiles",
            "action_budget_seconds",
            "source_pins",
            "observer_sha256",
        }
        or plan["schema"] != "ndu.real.macro-execution-plan.v1"
    ):
        raise ValueError("Execution requires the exact externally frozen plan")
    contexts, arms = macro_cohort.validate_plan(
        plan["cohort"], expected_plan_sha256=plan["cohort_sha256"]
    )
    cases, sources, hashes = {}, {}, {}
    for registered in plan["registered_cases"]:
        if set(registered) != {
            "source_id",
            "case_id",
            "seed",
            "case",
            "read_condition",
        }:
            raise ValueError("Unexpected registered case fields")
        key = tuple(registered[k] for k in ("source_id", "case_id", "seed"))
        case = registered["case"]
        if (
            type(registered["seed"]) is not int
            or key not in contexts
            or key in cases
            or case["source_id"] != key[0]
            or case["id"] != key[1]
            or case["role"] not in ROLES
            or not macro_cohort._sha(case.get("source_sha256"))
            or sources.get(key[0], case["source_sha256"]) != case["source_sha256"]
            or hashes.get(case["source_sha256"], key[0]) != key[0]
            or registered["read_condition"] not in {"original", "repeat", "noise"}
        ):
            raise ValueError("Unknown/duplicate case, sealed role or intervention")
        cases[key] = registered
        sources[key[0]], hashes[case["source_sha256"]] = case["source_sha256"], key[0]
    budget, config = plan["action_budget_seconds"], plan["config"]
    if (
        set(cases) != contexts
        or set(plan["profiles"]) != set(arms)
        or not macro_cohort.number(budget)
        or not 0 < budget < config["episode_wall_seconds"]
        or not macro_cohort.number(config["latency_weight"])
        or config["latency_weight"] <= 0
    ):
        raise ValueError("Incomplete Cartesian registration or invalid budget/tariff")
    pins = plan["source_pins"]
    if (
        not pins
        or any(set(p) != {"path", "sha256"} for p in pins)
        or len({p["path"] for p in pins}) != len(pins)
        or any(str(Path(p["path"]).resolve()) != p["path"] for p in pins)
    ):
        raise ValueError("Unique absolute source inventory is required")
    return cases, arms


def check_inputs(plan, output):
    """Check frozen code and every arm before/after each operation."""
    config, profiles = plan["config"], plan["profiles"]
    read_roots = [Path(p).resolve() for p in config["runtime_roots"]]
    for profile in profiles.values():
        read_roots.extend(
            Path(p).resolve()
            for p in (
                profile["weights"],
                profile["control_plan"],
                profile["macro_policy"]["path"],
            )
        )
        for name in ("deployment-profile.json", "receipt.json"):
            adjacent = Path(profile["weights"]).resolve().with_name(name)
            if adjacent.exists():
                read_roots.append(adjacent)
    material = Path(config["material_root"]).resolve()
    for registered in plan["registered_cases"]:
        case, pin = registered["case"], registered["case"]["reference"]
        relative = PurePosixPath(pin["path"])
        reference = (material / relative).resolve()
        if (
            case["role"] not in ROLES
            or set(pin) != {"path", "sha256", "bytes"}
            or relative.is_absolute()
            or str(relative) != pin["path"]
            or "\\" in pin["path"]
            or any(p in (".", "..") for p in relative.parts)
            or material not in reference.parents
            or any(reference == p or p in reference.parents for p in read_roots)
        ):
            raise ValueError(
                "Registered private reference is exposed or escapes its root"
            )
    root = Path(output).resolve()
    if any(root == p or p in root.parents or root in p.parents for p in read_roots):
        raise ValueError("Output references would enter an actor runtime read root")
    for pin in plan["source_pins"]:
        read_pin(pin)
    pinned = {p["path"]: p["sha256"] for p in plan["source_pins"]}
    if any(pinned.get(p["path"]) != p["sha256"] for p in source_inventory(config)):
        raise ValueError("Actual runtime/material/core source inventory is incomplete")
    if digest(macro_realization.source_manifest()) != plan["observer_sha256"]:
        raise ValueError("Observer differs from its pre-execution freeze")
    control_pin = None
    for arm in plan["cohort"]["arms"]:
        profile = profiles[arm["arm_id"]]
        if profile["core"] != "ordinary" or profile["memory_mode"] != "reset":
            raise ValueError("Ordinary reset content is required")
        for path_key, sha_key in (
            ("weights", "model_sha256"),
            ("control_plan", "control_plan_sha256"),
        ):
            read_pin({"path": profile[path_key], "sha256": profile[sha_key]})
        if profile["model_sha256"] != arm["content_sha256"]:
            raise ValueError("Arm content differs from frozen weights")
        pin = profile["macro_policy"]
        if set(pin) != {"path", "sha256"}:
            raise ValueError("A frozen per-arm macro deployment is required")
        raw = read_pin(pin)
        for name in ("deployment-profile.json", "receipt.json"):
            adjacent = Path(profile["weights"]).resolve().with_name(name)
            if adjacent.exists():
                if str(adjacent) not in pinned:
                    raise ValueError("Adjacent deployment inputs require source pins")
        control_wire = common.strict_json(Path(profile["control_plan"]).read_bytes())
        if set(control_wire) != {
            "control",
            "episode_wall_seconds",
            "fixed_schedule",
            "seed",
        }:
            raise ValueError("Closed original control plan required")
        control = ControlPlan(**control_wire["control"])
        if (
            control.memory_mode != "reset"
            or control_wire["episode_wall_seconds"] != config["episode_wall_seconds"]
            or control.latency_weight != config["latency_weight"]
            or control_pin not in (None, profile["control_plan_sha256"])
            or shared_context(config, control) != plan["cohort"]["shared"]
        ):
            raise ValueError(
                "Control, legal actions, evaluator or tariff differs between arms"
            )
        control_pin = profile["control_plan_sha256"]
        adapter = macro_actor.FrozenMacroControl(
            raw,
            pin["sha256"],
            weights_sha256=profile["model_sha256"],
            control_sha256=digest(asdict(control)),
        )
        if (
            adapter.deployment["policy"] != arm["policy"]
            or context_digest(adapter.context) != arm["critic_context_sha256"]
            or any(
                getattr(adapter.context, k) != v
                for k, v in macro_actor.host_context(
                    config, digest(utility_profile(control))
                ).items()
            )
        ):
            raise ValueError("Actual frozen policy context differs from its arm")
        checkpoint = common.strict_json(adapter.deployment["checkpoint_utf8"])
        for field, split in (
            ("fit_sources", "fit"),
            ("calibration_sources", "calibration"),
        ):
            if set(checkpoint[field]) != set(plan["cohort"]["partitions"][split]):
                raise ValueError(
                    "Frozen policy sources differ from registered partitions"
                )
        fitted_sources = checkpoint["source_bindings"]
        if any(
            c["source_id"] in fitted_sources
            or c["case"]["source_sha256"] in fitted_sources.values()
            for c in plan["registered_cases"]
        ):
            raise ValueError("Evaluation reuses fitting/calibration source bytes")
