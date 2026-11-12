"""Convert retained complete native macros into source-bound research pairs.

This is posthoc byte admission, not a native-owner attestation or policy trial.
Missing/failed planned pairs remain UNKNOWN. Only measured outer branch wall
cost is exported; acquisition and selection are never inferred from quality.
"""

from dataclasses import asdict
import math
from pathlib import Path

from ndu_real_materials import common, evaluator

from . import macro_realization
from .controllers import ACTIONS, ControlPlan
from .critic_context import context_digest, require_context
from .macro_actor import codec_sha256, host_context
from .macro_policy import ACTION_SHA256, LABELS, _pairs, _state
from .metacontrol_macro_contract import (
    INITIAL_FIELDS,
    SEQUENCES,
    digest,
    read_pin,
    sha,
    validate_plan,
)
from .objective import utility_profile


def source_manifest():
    root = Path(__file__).resolve().parents[1]
    names = (
        "macro_training_pairs.py",
        "macro_actor.py",
        "macro_policy.py",
        "macro_policy_checkpoint.py",
        "metacontrol.py",
        "critic_context.py",
        "controllers.py",
        "objective.py",
        "metacontrol_native_pairs.py",
        "actor.py",
        "episode.py",
        "ocr.py",
    )
    return {
        **macro_realization.source_manifest(),
        **{
            f"ndu_real_runtime/{n}": sha((root / "ndu_real_runtime" / n).read_bytes())
            for n in names
        },
    }


def source_sha256():
    return digest(source_manifest())


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


class _Reads:
    def __init__(self):
        self.pins = {}

    def raw(self, root, name, limit=8 * 1024 * 1024):
        raw = common.read_relative(root, name, limit=limit)
        key = (str(Path(root).resolve()), name, limit)
        pin = {"path": name, "bytes": len(raw), "sha256": sha(raw)}
        if key in self.pins and self.pins[key] != pin:
            raise ValueError("Retained bytes changed during conversion")
        self.pins[key] = pin
        return raw

    def bound(self, root, pin, limit=32 * 1024 * 1024):
        raw = common.read_bound(root, pin, limit=limit)
        if self.raw(root, pin["path"], limit) != raw:
            raise ValueError("Registered bytes changed during conversion")
        return raw

    def check(self):
        for (root, name, limit), pin in self.pins.items():
            common.read_bound(root, pin, limit=limit)


def _inputs(plan, context):
    profile, config = plan["profile"], plan["config"]
    for pin in plan["source_pins"]:
        if type(pin) is not dict or set(pin) != {"path", "sha256"}:
            raise ValueError("Closed producer source pins required")
        read_pin(pin)
    for field, identity in (
        ("weights", "model_sha256"),
        ("control_plan", "control_plan_sha256"),
    ):
        raw = read_pin({"path": profile[field], "sha256": profile[identity]})
        if field == "control_plan":
            control_wire = common.strict_json(raw)
    if set(control_wire) != {
        "control",
        "episode_wall_seconds",
        "fixed_schedule",
        "seed",
    }:
        raise ValueError("Complete frozen actor control plan required")
    control = ControlPlan(**control_wire["control"])
    if (
        control.memory_mode != "reset"
        or not _number(config["episode_wall_seconds"])
        or control_wire["episode_wall_seconds"] != config["episode_wall_seconds"]
        or type(control_wire["episode_wall_seconds"]) not in (int, float)
        or control.latency_weight != config["latency_weight"]
        or not _number(config["latency_weight"])
        or plan["latency_tariff"] != config["latency_weight"]
        or type(control_wire["seed"]) is not int
        or type(control_wire["fixed_schedule"]) is not list
        or set(control_wire["fixed_schedule"]) - set(ACTIONS)
    ):
        raise ValueError("Actual reset, budget or wall-cost objective differs")
    utility, control_sha = digest(utility_profile(control)), digest(asdict(control))
    expected = {
        "encoder_sha256": profile["model_sha256"],
        "answer_sha256": profile["model_sha256"],
        "generator_sha256": sha(Path(__file__).with_name("ocr.py").read_bytes()),
        "public_state_sha256": codec_sha256(),
        "action_sha256": ACTION_SHA256,
        **host_context(config, utility),
    }
    if (
        any(getattr(context, key) != value for key, value in expected.items())
        or sha(Path(evaluator.__file__).read_bytes()) != config["evaluator_sha256"]
    ):
        raise ValueError("Actual producer and complete-macro context differ")
    return utility, control_sha


def _native_inventory(plan):
    runtime = Path(__file__).resolve().parent
    config = plan["config"]
    if (
        Path(config["scripts_root"]).resolve() != runtime.parent
        or Path(config["repository_root"]).resolve() != runtime.parent.parent
    ):
        raise ValueError("Native actor/scorer roots differ from current source")
    required = {
        p.resolve()
        for folder in (runtime, runtime.parent / "ndu_real_materials")
        for p in folder.glob("*.py")
        if not p.name.startswith("test_")
    }
    required.add(
        runtime.parent.parent
        / "experiments/multimodal_output_portfolio/joint_hepta_20261029/hepta_core.py"
    )
    pinned = {Path(p["path"]).resolve() for p in plan["source_pins"]}
    if not required <= pinned:
        raise ValueError("Original native producer inventory is incomplete")


def _project(step, budget):
    legal = step["legal_actions"]
    if (
        type(legal) is not list
        or any(type(a) is not str for a in legal)
        or len(legal) != len(set(legal))
        or set(legal) - set(ACTIONS)
        or not {"STOP", "WRITE_TEXT", "PREPARE_ROI"} <= set(legal)
        or not _number(step["remaining_seconds"])
        or step["remaining_seconds"] != budget
    ):
        raise ValueError("Original state lacks the frozen budget or both legal macros")
    state = {
        "features": step["public_features"],
        "context_belief": [1.0],
        "pending_evidence": False,
        "freshness_seconds": 0.0,
        "remaining_seconds": step["remaining_seconds"],
        "legal_macros": ["STOP", "READ"],
    }
    _state(state)
    detail = step.get("controller", {})
    if type(detail) is not dict:
        raise ValueError("Original controller witness is malformed")
    if "macro_public_state" in detail:
        _state(detail["macro_public_state"])
        if digest(detail["macro_public_state"]) != digest(state):
            raise ValueError("Original macro public state differs from projection")
    if "macro_public_state_sha256" in detail and detail[
        "macro_public_state_sha256"
    ] != digest(state):
        raise ValueError("Original macro public digest differs from projection")
    return state, digest({key: step[key] for key in INITIAL_FIELDS})


def _source(plan, case, results, reads):
    config, case_id = plan["config"], case["id"]
    root = Path(config["material_root"])
    index_raw = reads.raw(root, "private/reference-index.v2.json")
    index = common.strict_json(index_raw)
    if (
        type(index) is not dict
        or sha(index_raw) != config["reference_index_sha256"]
        or index.get("schema") != "ndu.real.reference-index.v2"
    ):
        raise ValueError("Pinned role-bound source registry differs")
    # Role metadata and already-admitted scorer roles precede any reference read.
    if (
        index["case_roles"][case_id] != "train"
        or case["role"] != "train"
        or any(r["score_components"].get("role") != "train" for r in results)
    ):
        raise PermissionError("Sealed or non-training source role")
    pin = index["cases"][case_id]
    if pin != case["reference"] or any(
        r["score_components"].get("reference_sha256") != pin["sha256"] for r in results
    ):
        raise ValueError("Registered reference differs from original scorer/plan")
    if sha(reads.bound(root, index["rubric"])) != config["rubric_sha256"]:
        raise ValueError("Registered rubric differs")
    reference = common.strict_json(reads.bound(root, pin, 2 * 1024 * 1024))
    if (
        reference["case_id"] != case_id
        or reference["role"] != "train"
        or reference["source_group"] != case["source_id"]
        or reference["episode_group"] != case["episode_group"]
        or any(
            r["score_components"].get("source_group") != case["source_id"]
            or r["score_components"].get("episode_group") != case["episode_group"]
            for r in results
        )
    ):
        raise ValueError("Private registered source group differs")
    source_sha = sha(reads.bound(root, reference["source_image"]))
    if any(r.get("source_sha256") != source_sha for r in results):
        raise ValueError("Native source bytes differ from registered source")
    return source_sha, {
        "reference": pin,
        "source_image": reference["source_image"],
        "reference_index_sha256": sha(index_raw),
    }


def _branch(root, pair, macro, summary, plan, profiles, reads):
    directory = root / (pair["pair_id"] + "-" + macro)
    evidence = summary["branches"][macro]
    wall = evidence["outer_wall_seconds"]
    if (
        evidence["status"] != "completed"
        or not _number(wall)
        or not _number(evidence["quality"])
        or not _number(evidence["latency_cost"])
        or evidence["latency_cost"] != wall * plan["latency_tariff"]
    ):
        raise ValueError("Completed branch with measured consistent wall cost required")
    raw = {
        n: reads.raw(directory, n)
        for n in ("result.json", "launch.json", "trajectory.json")
    }
    if evidence["artifact_sha256s"] != {n: sha(v) for n, v in raw.items()}:
        raise ValueError("Original pair artifact pins differ")
    result, launch, trajectory = (common.strict_json(raw[n]) for n in raw)
    if (
        any(type(v) is not dict for v in (result, launch, trajectory))
        or type(launch.get("stdout")) is not str
    ):
        raise ValueError("Original branch artifacts must be objects")
    profile, case = plan["profile"], pair["case"]
    expected = {
        **profile,
        "original_operation_id": pair["pair_id"] + "/" + macro,
        "case_id": case["id"],
        "source_group_id": case["source_id"],
        "episode_group": case["episode_group"],
        "split": "train",
        "model_sha256": profile["model_sha256"],
        "control_plan_sha256": profile["control_plan_sha256"],
        "utility_profile_sha256": profiles[0],
        "control_profile_sha256": profiles[1],
        "memory_mode": "reset",
    }
    if (
        any(result.get(k) != v for k, v in expected.items())
        or digest(result.get("utility_profile")) != profiles[0]
        or not _number(result.get("gross_score"))
    ):
        raise ValueError("Original operation, model, source or objective differs")
    events = [
        common.strict_json(line.encode())
        for line in launch["stdout"].splitlines()
        if line.strip()
    ]
    if any(type(event) is not dict for event in events):
        raise ValueError("Original actor events must be objects")
    if any(
        event.get(k) != expected[k]
        for event in events
        for k in ("utility_profile_sha256", "control_profile_sha256", "memory_mode")
    ):
        raise ValueError("Original actor producer profile differs")
    public_input = None
    try:
        public = reads.raw(directory, "public-input.json", 131072)
    except FileNotFoundError:
        pass
    else:
        public_input = {
            "path": "public-input.json",
            "bytes": len(public),
            "sha256": sha(public),
        }
    observed = macro_realization.observe_realization(
        directory,
        result,
        macro,
        wall,
        plan["latency_tariff"],
        plan["config"],
        expected_source_sha256=digest(macro_realization.source_manifest()),
        public_input=public_input,
    )
    for name, identity in observed["artifact_sha256s"].items():
        if sha(reads.raw(directory, name)) != identity:
            raise ValueError("Observed terminal bytes changed")
    state, initial = _project(trajectory["steps"][0], plan["action_budget_seconds"])
    checks = {
        "operation_id": expected["original_operation_id"],
        "initial_public_state_sha256": initial,
        "evaluator_sha256": plan["config"]["evaluator_sha256"],
        "rubric_sha256": plan["config"]["rubric_sha256"],
        "quality": observed["stages"]["execution"]["quality"],
        "actual_native_actions": SEQUENCES[macro],
        "delivery_sha256": observed["stages"]["execution"]["delivery_sha256"],
        "evaluation_sha256": observed["stages"]["execution"]["evaluation_sha256"],
    }
    if any(evidence.get(k) != v for k, v in checks.items()):
        raise ValueError("Pair summary differs from original completed macro")
    return result, state, initial, observed


def export(
    collection_root,
    *,
    expected_plan_sha256,
    context,
    expected_source_sha256,
    allow_fixtures=False,
):
    """Return rows, resolving evidence and a disposition for every planned pair.

    expected_plan_sha256 binds raw PLAN.json bytes (the collector's pair receipts
    separately bind its canonical JSON digest). Native producer drift, absent
    artifacts or incomplete macros yield UNKNOWN; invalid external pins reject.
    """
    require_context(context)
    if type(allow_fixtures) is not bool or source_sha256() != expected_source_sha256:
        raise ValueError("Converter source identity or fixture declaration differs")
    root, reads = Path(collection_root), _Reads()
    plan_raw = reads.raw(root, "PLAN.json")
    if sha(plan_raw) != expected_plan_sha256:
        raise ValueError("External raw collection plan pin differs")
    plan = validate_plan(common.strict_json(plan_raw))
    rows, dispositions, receipts = [], [], {}
    identities, reverse = {}, {}
    try:
        profiles, input_error = _inputs(plan, context), None
    except (OSError, ValueError, KeyError, TypeError) as error:
        profiles, input_error = None, type(error).__name__ + ": " + str(error)
    for pair in plan["pairs"]:
        disposition = {
            "pair_id": pair["pair_id"],
            "split": pair["split"],
            "source_id": pair["case"]["source_id"],
            "status": "UNKNOWN",
        }
        try:
            if input_error:
                raise ValueError(input_error)
            summary_raw = reads.raw(root, pair["pair_id"] + ".json")
            summary = common.strict_json(summary_raw)
            if type(summary) is not dict:
                raise ValueError("Original pair receipt must be an object")
            expected = {
                "schema": "ndu.real.native-macro-pair.v1",
                "pair_id": pair["pair_id"],
                "split": pair["split"],
                "source_group": pair["case"]["source_id"],
                "read_condition": pair["read_condition"],
                "plan_sha256": digest(plan),
            }
            if any(summary.get(k) != v for k, v in expected.items()):
                raise ValueError("Pair receipt differs from frozen collection plan")
            if summary["evidence_kind"] == "native_module_execution":
                _native_inventory(plan)
            elif summary["evidence_kind"] != "fixture" or not allow_fixtures:
                raise ValueError("Fixture evidence requires explicit test scope")
            if (
                pair["read_condition"] != "original"
                or summary["status"] != "completed"
                or summary["initial_public_state_matched"] is not True
                or set(summary["branches"]) != set(SEQUENCES)
            ):
                raise ValueError(
                    "Only matched completed original READ pairs are exportable"
                )
            admitted = {
                m: _branch(root, pair, m, summary, plan, profiles, reads)
                for m in SEQUENCES
            }
            if admitted["STOP"][2] != admitted["READ"][2] or digest(
                admitted["STOP"][1]
            ) != digest(admitted["READ"][1]):
                raise ValueError("Original initial public states differ")
            source_sha, registered = _source(
                plan, pair["case"], [v[0] for v in admitted.values()], reads
            )
            source_id = pair["case"]["source_id"]
            if (
                source_id in identities
                and identities[source_id] != source_sha
                or source_sha in reverse
                and reverse[source_sha] != source_id
            ):
                raise ValueError(
                    "Source alias conflicts with an already exported identity"
                )
            state = admitted["STOP"][1]
            local_receipts, branches = {}, {}
            for macro, (_, _, initial, observed) in admitted.items():
                receipt = {
                    "schema": "ndu.real.macro-training-admission.v1",
                    "plan_sha256": expected_plan_sha256,
                    "pair_receipt_sha256": sha(summary_raw),
                    "converter_sha256": expected_source_sha256,
                    "context_sha256": context_digest(context),
                    "source_id": source_id,
                    "source_sha256": source_sha,
                    "registered_source": registered,
                    "evidence_kind": summary["evidence_kind"],
                    "public_state_sha256": digest(state),
                    "realization": observed,
                }
                identity = digest(receipt)
                local_receipts[identity] = receipt
                branches[macro] = {
                    "status": "COMPLETED",
                    "quality": observed["stages"]["execution"]["quality"],
                    "cost": observed["costs"]["latency_cost"],
                    "full_cost_observed": False,
                    "evidence_sha256": identity,
                    "initial_public_state_sha256": initial,
                    "public_state_sha256": digest(state),
                    "actions": list(SEQUENCES[macro]),
                }
            read_stages = admitted["READ"][3]["stages"]
            labels = {
                "acquired": read_stages["observation"]["acquired"],
                "selected_used": read_stages["selection"]["selected_used"],
                "effect_occurred": None,
            }
            row = {
                "schema": "ndu.ctrl.macro-pair.v1",
                "source_id": source_id,
                "source_sha256": source_sha,
                "decision_id": digest(plan) + ":" + pair["pair_id"],
                "context_sha256": context_digest(context),
                "state": state,
                "branches": branches,
                "labels": labels,
                "label_receipts": {
                    k: branches["READ"]["evidence_sha256"]
                    if labels[k] is not None
                    else None
                    for k in LABELS
                },
            }
            _pairs([row], context)
            identities[source_id], reverse[source_sha] = source_sha, source_id
            rows.append(row)
            receipts.update(local_receipts)
            disposition.update(
                status="EXPORTED",
                decision_id=row["decision_id"],
                evidence_kind=summary["evidence_kind"],
            )
        except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
            disposition["reason"] = type(error).__name__ + ": " + str(error)
        dispositions.append(disposition)
    reads.check()
    if source_sha256() != expected_source_sha256:
        raise ValueError("Converter source changed during conversion")
    if input_error is None:
        _inputs(plan, context)
    return {
        "schema": "ndu.real.macro-training-export.v1",
        "rows": rows,
        "receipts": receipts,
        "planned": dispositions,
        "planned_pairs": len(plan["pairs"]),
        "exported_pairs": len(rows),
        "unknown_pairs": len(plan["pairs"]) - len(rows),
        "plan_sha256": expected_plan_sha256,
        "canonical_plan_sha256": digest(plan),
        "converter_source_sha256": expected_source_sha256,
        "context": context.to_wire(),
        "source_bindings": identities,
        "fixture_scope_enabled": allow_fixtures,
        "full_physical_cost_observed": False,
        "read_semantics": "original observation only; repeat/noise excluded from fitted READ",
        "wall_cost_scope": "original outer branch wall; excludes collector/control-plane",
        "native_owner_authenticated": False,
        "policy_efficacy_evaluated": False,
        "production_admission": False,
    }


def fit_rows(report, split, *, expected_export_sha256, context):
    """Admit a pinned complete plan before choosing either fitting partition.

    Even missing items in the other partition block this gate. Callers must not
    fit report["rows"] directly: that would silently drop planned UNKNOWN items.
    """
    require_context(context)
    if (
        type(report) is not dict
        or digest(report) != expected_export_sha256
        or report.get("schema") != "ndu.real.macro-training-export.v1"
        or report.get("context") != context.to_wire()
        or report.get("converter_source_sha256") != source_sha256()
        or split not in {"train", "calibration"}
    ):
        raise ValueError("Pinned export, source, context or fitting split differs")
    planned, rows = report["planned"], report["rows"]
    if (
        type(planned) is not list
        or not 1 <= len(planned) <= 256
        or type(rows) is not list
        or any(
            type(item) is not dict
            or item.get("status") not in {"EXPORTED", "UNKNOWN"}
            or item.get("split") not in {"train", "calibration"}
            or type(item.get("pair_id")) is not str
            or not item["pair_id"].isalnum()
            for item in planned
        )
    ):
        raise ValueError("Invalid explicit planned source inventory")
    counts = {
        "planned_pairs": len(planned),
        "exported_pairs": len(rows),
        "unknown_pairs": sum(item["status"] == "UNKNOWN" for item in planned),
    }
    if (
        any(type(report.get(k)) is not int or report[k] != v for k, v in counts.items())
        or counts["exported_pairs"] + counts["unknown_pairs"] != counts["planned_pairs"]
        or len({p["pair_id"] for p in planned}) != len(planned)
    ):
        raise ValueError("Export counts or planned identities differ")
    if counts["unknown_pairs"]:
        raise ValueError("Incomplete planned collection cannot supply fitting rows")
    _pairs(rows, context)
    by_id = {row["decision_id"]: row for row in rows}
    selected = [item for item in planned if item["split"] == split]
    if (
        not selected
        or len(by_id) != len(rows)
        or {item["decision_id"] for item in planned} != set(by_id)
    ):
        raise ValueError("Fitting partition or unique decision mapping differs")
    for item in planned:
        row = by_id[item["decision_id"]]
        if (
            item["decision_id"]
            != report["canonical_plan_sha256"] + ":" + item["pair_id"]
            or item["source_id"] != row["source_id"]
        ):
            raise ValueError("Planned source/decision differs from admitted row")
    bindings = {(row["source_id"], row["source_sha256"]) for row in rows}
    if (
        len(bindings) != len({p[0] for p in bindings})
        or len(bindings) != len({p[1] for p in bindings})
        or report["source_bindings"] != dict(bindings)
    ):
        raise ValueError("Exported physical source aliases or bindings differ")
    return _pairs([by_id[item["decision_id"]] for item in selected], context)
