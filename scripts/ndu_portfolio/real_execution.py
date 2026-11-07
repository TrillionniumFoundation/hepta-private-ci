"""Run the predictive controllers against real local text/image generators.

LocalModels/AdaptedLocalModels are the existing source-bound generator adapters.
They are supplied by the integrated decision_audit tree, never replaced by a
renderer here. This research trace is not a native owner journal or independent
semantic evaluation. Use the outer command meter for preemptive containment.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time
import uuid

import numpy as np
from PIL import Image
import torch

from .real_encoding import FrozenSmolEncoder, _public

from .real_controllers import (
    ACTIONS,
    Controller,
    Observation,
    Opportunity,
    PredictiveModel,
    digest,
    parameter_digest,
)


def _sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def load_predictor(path, expected_sha256):
    path = Path(path)
    if _sha(path) != expected_sha256:
        raise ValueError("predictor checkpoint differs from its external pin")
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    receipt = json.loads((path.parent / "fit.json").read_text())
    if (
        receipt["status"] != "completed"
        or receipt["attempt_id"] != checkpoint["fit"]["attempt_id"]
    ):
        raise ValueError("failed/incomplete fit cannot supply a deployment predictor")
    if any(receipt.get(key) != value for key, value in checkpoint["fit"].items()):
        raise ValueError(
            "terminal fit receipt rewrites checkpoint-bound training evidence"
        )
    if (
        receipt["claim_status"] != "HOLD"
        or receipt["wall_seconds"] > receipt["opportunity"]["fit_wall_seconds"]
    ):
        raise ValueError(
            "fit status or measured opportunity cannot qualify this checkpoint"
        )
    if receipt.get("critic_target") != (
        "conditional_exponential_moment"
        if checkpoint["config"]["gamma"]
        else "conditional_mean"
    ):
        raise ValueError("critic fitting objective is not bound to this risk profile")
    model = PredictiveModel(**checkpoint["config"])
    model.load_state_dict(checkpoint["state_dict"], strict=True)
    if parameter_digest(model) != receipt["model_digest"]:
        raise ValueError("predictor parameters differ from the physical fit")
    model.fit_receipt = receipt
    return model


def execute(
    public,
    backend,
    controller,
    encoder,
    output,
    *,
    binding,
    seed,
    horizon,
    cost_budget,
    wall_budget,
    cpu_tariff,
    wall_tariff,
    required_modalities,
    initial_actions=(),
    collect_transition_features=False,
):
    """Bounded real graph with immutable outputs, public-only control, full failures.

    Tariffs, initial delivery work and required modalities are caller-registered
    inputs. Raw usage remains available. No zero tariff is interpreted as free
    compute, and no generic JSON receipt authenticates native execution.
    """
    _public(public)
    if (
        type(horizon) is not int
        or not 1 <= horizon <= 32
        or type(seed) is not int
        or seed < 0
        or not required_modalities
        or set(required_modalities) - {"text", "image"}
        or any(a not in ACTIONS[:-1] for a in initial_actions)
        or len(initial_actions) >= horizon
    ):
        raise ValueError("invalid registered action/delivery profile")
    for value in (cost_budget, wall_budget, cpu_tariff, wall_tariff):
        if type(value) not in (int, float) or not np.isfinite(value) or value < 0:
            raise ValueError("finite nonnegative physical-cost profile required")
    if min(cost_budget, wall_budget) <= 0 or cpu_tariff + wall_tariff <= 0:
        raise ValueError(
            "declare positive budgets and an explicit nonzero cost conversion"
        )
    if controller.strategy == "initial" and not initial_actions:
        raise ValueError(
            "initial-delivery comparator needs registered actual initial delivery work"
        )
    if controller.decisions or set(initial_actions) - set(controller.allowed_actions):
        raise ValueError(
            "use a fresh per-episode controller and registered initial actions"
        )
    if type(collect_transition_features) is not bool:
        raise ValueError("feature collection role must be explicit")
    required_binding = {
        "task_id",
        "source_group",
        "episode_group",
        "fit_id",
        "native_request_id",
        "incumbent_checkpoint_digest",
    }
    owner_optional = {
        "incumbent_manifest_digest",
        "incumbent_payload_digest",
        "source_owner_checkpoint_digest",
        "source_run_id",
        "agent_id",
        "cell_id",
    }
    if (
        not required_binding <= set(binding)
        or set(binding) - required_binding - owner_optional
    ):
        raise ValueError("external owner binding fields differ")
    binding = {**{name: None for name in owner_optional}, **binding}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    begin = previous = (time.process_time(), time.perf_counter())
    report = {
        "run_id": uuid.uuid4().hex,
        "binding": dict(binding),
        "status": "started",
        "controller": controller.identity,
        "seed": seed,
        "horizon": horizon,
        "required_modalities": list(required_modalities),
        "initial_actions": list(initial_actions),
        "feature_collection_only": collect_transition_features,
        "cost_budget": cost_budget,
        "wall_budget": wall_budget,
        "tariffs": {"cpu_second": cpu_tariff, "wall_second": wall_tariff},
        "events": [],
        "observations": [],
        "artifacts": [],
        "selected": [],
        "native_owner_verified": False,
        "semantic_acceptance": "pending_independent_evaluation",
        "claim_status": "HOLD",
        "hard_deadline_guarantee": False,
        "synchronization_scope": "explicit_backend_barriers; implicit waits remain in their calling component",
    }
    _write(output / "episode.json", report)
    plan, version, text, picture, critique, history = (
        public["text"],
        0,
        None,
        None,
        "",
        [],
    )
    active, total_cost, action = {}, 0.0, "preflight"

    def event(category, status, detail=None):
        nonlocal previous, total_cost
        now = time.process_time(), time.perf_counter()
        cpu, wall = now[0] - previous[0], now[1] - previous[1]
        cost = cpu * cpu_tariff + wall * wall_tariff
        total_cost += cost
        row = {
            "attempt_id": uuid.uuid4().hex,
            "sequence": len(report["events"]),
            "action": action,
            "category": category,
            "status": status,
            "cpu_seconds": cpu,
            "wall_seconds": wall,
            "cost": cost,
            "detail": detail,
        }
        report["events"].append(row)
        previous = now
        with (output / "events.jsonl").open("a") as stream:
            stream.write(json.dumps(row, allow_nan=False) + "\n")
        return row

    def within_budget():
        if total_cost > cost_budget or time.perf_counter() - begin[1] > wall_budget:
            raise TimeoutError("registered episode opportunity exhausted")

    def synchronize():
        try:
            backend.synchronize()
        except (Exception, KeyboardInterrupt) as error:
            event("synchronization", "failed", {"type": type(error).__name__})
            raise
        event("synchronization", "completed")

    def keep(kind, path):
        item = {
            "kind": kind,
            "path": path.name,
            "sha256": _sha(path),
            "bytes": path.stat().st_size,
            "plan_version": version,
            "source_event": len(report["events"]),
        }
        report["artifacts"].append(item)
        if kind in ("text", "image"):
            active[kind] = item

    try:
        input_path = output / "public-input.png"
        Image.fromarray(public["image_rgb"]).save(input_path)
        report["public_input_digest"] = digest(
            {"text": public["text"], "image_sha256": _sha(input_path)}
        )
        _write(output / "backend.json", backend.identity())
        event("codec", "completed")
        for step in range(horizon):
            within_budget()
            if step < len(initial_actions):
                action = initial_actions[step]
            else:
                action = "encode_public"
                current = {
                    "plan": plan,
                    "text": text,
                    "image_rgb": picture,
                    "critique": critique,
                    "history": tuple(history),
                }
                encoded = collect_transition_features or controller.strategy not in (
                    "initial",
                    "tuned_fixed",
                )
                encoding = (
                    encoder(public, current)
                    if encoded
                    else (0.0,) * controller.model.config["encoding_width"]
                )
                encoding_digest = encoder.contract_digest() if encoded else None
                if (
                    encoded
                    and controller.model.fit_receipt is not None
                    and controller.model.config["encoding_digest"] != encoding_digest
                ):
                    raise ValueError(
                        "runtime encoder differs from the frozen predictor training contract"
                    )
                event(
                    "encoder",
                    "completed" if encoded else "not_required_for_fixed_policy",
                )
                if encoded:
                    synchronize()
                within_budget()
                observation = Observation(
                    encoding,
                    text is not None,
                    picture is not None,
                    max(0.0, cost_budget - total_cost),
                    max(0.0, wall_budget - (time.perf_counter() - begin[1])),
                    horizon - step,
                )
                report["observations"].append(
                    {
                        "step": step,
                        "event_cursor": len(report["events"]),
                        "public": asdict(observation),
                        "suitable_for_predictive_fitting": encoded,
                        "encoding_digest": encoding_digest,
                        "current_artifacts": {k: dict(v) for k, v in active.items()},
                    }
                )
                action = "controller"
                selected = controller.choose(observation)
                event("planning", "completed", controller.decisions[-1])
                within_budget()
                if selected not in observation.legal():
                    raise ValueError("controller selected an infeasible action")
                action = selected
            path = output / f"{step:02d}-{action}"
            if action == "stop":
                if set(required_modalities) <= set(active):
                    for item in active.values():
                        if (
                            item["plan_version"] != version
                            or _sha(output / item["path"]) != item["sha256"]
                        ):
                            raise ValueError(
                                "stale or mutated artifact cannot be selected"
                            )
                    report["selected"] = [active[k] for k in required_modalities]
                    report["status"] = "candidate_complete_pending_native_owner"
                else:
                    report["status"] = "abstained"
            elif action in ("perceive", "revise"):
                prompt = (
                    "Describe visible facts for the requested explanation. Request: "
                    + public["text"]
                    if action == "perceive"
                    else "Revise this shared plan using the public critique. Request: "
                    + public["text"]
                    + "\nPlan: "
                    + plan
                    + "\nCritique: "
                    + critique
                )
                plan = backend.describe(str(input_path), prompt)
                version += 1
                text = picture = None
                critique = ""
                active.clear()
                path = path.with_suffix(".txt")
                path.write_text(plan)
                keep("plan", path)
            elif action == "text":
                text = backend.describe(
                    str(input_path), public["text"] + "\nCurrent shared plan: " + plan
                )
                path = path.with_suffix(".txt")
                path.write_text(text)
                keep("text", path)
                critique = ""
            elif action in ("draft", "refine"):
                initial = (
                    output / active["image"]["path"]
                    if action == "refine" and "image" in active
                    else None
                )
                if action == "refine" and initial is None:
                    raise ValueError("refinement needs an actual current image")
                path = path.with_suffix(".png")
                backend.draw(
                    public["text"] + "\nShared plan: " + plan,
                    path,
                    seed + step,
                    initial_image=initial,
                )
                with Image.open(path) as generated:
                    picture = np.asarray(generated.convert("RGB")).copy()
                if picture.shape[0] * picture.shape[1] > 16000000:
                    raise ValueError("generated image exceeds declared bounds")
                keep("image", path)
                critique = ""
            elif action == "verify":
                if not {"text", "image"} <= set(active):
                    raise ValueError("public critique needs the actual current pair")
                critique = backend.describe(
                    str(output / active["image"]["path"]),
                    "Check this current image against the explanation and plan. Explanation: "
                    + text
                    + "\nPlan: "
                    + plan,
                )
                path = path.with_suffix(".txt")
                path.write_text(critique)
                keep("public_critique", path)
            if any(
                v is not None and (not isinstance(v, str) or len(v) > 8192)
                for v in (text, plan, critique)
            ):
                raise ValueError("generator returned invalid or unbounded text")
            category = (
                "critic"
                if action == "verify"
                else "shared"
                if action in ("perceive", "revise")
                else "decoder"
            )
            event(category, "completed")
            synchronize()
            history.append(action)
            within_budget()
            if action == "stop":
                break
        if report["status"] == "started":
            report["status"] = "horizon_exhausted"
    except (Exception, KeyboardInterrupt) as error:
        report.update(
            status="cancelled"
            if isinstance(error, KeyboardInterrupt)
            else "timeout"
            if isinstance(error, TimeoutError)
            else "failed",
            error={"type": type(error).__name__, "message": str(error)},
            selected=[],
        )
        event("failure", report["status"], report["error"])
    finally:
        report.update(
            history=history,
            total_cost=total_cost,
            cpu_seconds=sum(row["cpu_seconds"] for row in report["events"]),
            wall_seconds=sum(row["wall_seconds"] for row in report["events"]),
            unknown_costs=[
                "energy",
                "accelerator_charge",
                "external_acquisition_and_training",
                "independent_evaluation",
                "outer_process_and_final_write",
            ],
        )
        report["retained_files"] = [
            {"path": p.name, "sha256": _sha(p), "bytes": p.stat().st_size}
            for p in sorted(output.iterdir())
            if p.suffix in (".png", ".txt")
        ]
        report = json.loads(json.dumps(report, allow_nan=False))
        _write(output / "episode.json", report)
    return report


def main():
    parser = argparse.ArgumentParser()
    for name in (
        "models",
        "candidate_root",
        "candidate_manifest",
        "candidate_manifest_sha256",
        "candidate_history",
        "candidate_history_sha256",
        "candidate_id",
        "checkpoint",
        "checkpoint_sha256",
        "profile",
        "output",
    ):
        parser.add_argument("--" + name.replace("_", "-"), required=True)
    args = parser.parse_args()
    from ndu_semantic_state.source_pool import (
        admit_candidate_pool,
        load_candidate_public_case,
    )
    from experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit.local_models import (
        LocalModels,
    )

    admission = admit_candidate_pool(
        args.candidate_root,
        args.candidate_manifest,
        args.candidate_history,
        expected_history_sha256=args.candidate_history_sha256,
    )
    manifest_path = Path(args.candidate_root) / args.candidate_manifest
    if _sha(manifest_path) != args.candidate_manifest_sha256:
        raise ValueError("candidate manifest differs from its external pin")
    manifest = json.loads(manifest_path.read_text())
    case = next(row for row in manifest["cases"] if row["id"] == args.candidate_id)
    public = load_candidate_public_case(args.candidate_root, case)
    profile = json.loads(Path(args.profile).read_text())
    model = load_predictor(args.checkpoint, args.checkpoint_sha256)
    expected = {
        "task_id": case["id"],
        "source_group": case["source_group_id"],
        "episode_group": case["episode_group_id"],
        "fit_id": model.fit_receipt["attempt_id"],
    }
    if any(
        profile["execution"]["binding"].get(key) != value
        for key, value in expected.items()
    ):
        raise ValueError(
            "owner-side execution binding differs from candidate or physical fit"
        )
    controller = Controller(
        model,
        opportunity=Opportunity(**profile["opportunity"]),
        **profile["controller"],
    )
    backend = LocalModels(
        Path(args.models) / "vlm",
        Path(args.models) / "sd",
        threads=profile["threads"],
        device=profile.get("device", "cpu"),
        dtype=profile.get("dtype", "bfloat16"),
    )
    result = execute(
        public,
        backend,
        controller,
        FrozenSmolEncoder(backend),
        args.output,
        **profile["execution"],
    )
    _write(Path(args.output) / "candidate_admission.json", admission)
    print(
        json.dumps(
            {
                "status": result["status"],
                "claim_status": result["claim_status"],
                "run_id": result["run_id"],
            }
        )
    )
    return (
        0
        if result["status"] in ("candidate_complete_pending_native_owner", "abstained")
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
