"""Train only from completed, host-observed receipt trajectories.

JSONL ``ndu.real.training-transition.v1/v2`` records carry the current candidate
features/metadata, actual successor observation, observed scores and duration,
and training-only field/box references. No oracle action or counterfactual score
is used. Only weights.pt, a plain tensor state_dict, is a deployment artifact.

--bootstrap creates a separately identified random collector, not a training
replicate. --content-only prepares a reusable, seed/core/data-bound content
checkpoint. --pretrained DIR admits that checkpoint for frozen shared-head fits
or independent controller-conditioned joint fits. Light backpropagates its
observed action-value loss into content. V2 NDU fits additionally differentiate
finite recursive utility through a frozen fitted reference and an exact
finite-action policy improvement objective. V1 retains explicit reset/auxiliary
compatibility. Persistent replay requires a complete checked v2 episode chain.
"""

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import sys
import time
import traceback
import uuid

from .metering import Meter, atomic_json, canonical_sha, file_sha
from .controllers import ControlPlan
from .objective import utility_profile
from .trajectory import (
    V2_SCHEMA,
    V2_FIELDS,
    validate_link,
    validate_chains,
    episode_groups,
    memory_replay_metadata,
)
from .fit_loop import train_epochs as _epochs, estimate_residuals as _residuals

SCHEMA = "ndu.real.training-transition.v1"
ACTION_NAMES = ("PREPARE_ROI", "READ_ROI", "WRITE_TEXT", "RENDER_IMAGE", "STOP")
FIELD_NAMES = ("company", "date", "address", "total")
CONTENT_PREFIXES = ("project.", "core.", "answer.", "box_delta.")
REQUIRED = {
    "schema",
    "record_id",
    "episode_id",
    "source_group",
    "split",
    "origin_run_id",
    "source_size",
    "candidate_features",
    "candidate_metadata",
    "public_metadata",
    "reference_field",
    "expected_text",
    "target_boxes",
    "action",
    "next_candidate_features",
    "next_public_metadata",
    "before_score",
    "after_score",
    "duration_seconds",
    "execution_status",
}
OPTIONAL = {
    "observation_sha256",
    "next_observation_sha256",
    "action_receipt_sha256",
    "behavior_controller",
    "behavior_weights_sha256",
    "terminal_reason",
}


@dataclass(frozen=True)
class FitConfig:
    content_epochs: int = 12
    fit_epochs: int = 12
    batch_size: int = 32
    content_lr: float = 0.003
    lr: float = 0.003
    latency_weight: float = 0.01
    max_wall_seconds: float = 600

    def __post_init__(self):
        for name in ("content_epochs", "fit_epochs"):
            if (
                type(getattr(self, name)) is not int
                or not 1 <= getattr(self, name) <= 200
            ):
                raise ValueError("Epoch count outside the bounded fit profile")
        if type(self.batch_size) is not int or not 1 <= self.batch_size <= 256:
            raise ValueError("Invalid training batch size")
        for name in ("content_lr", "lr"):
            if (
                not _number(getattr(self, name))
                or not 1e-6 <= getattr(self, name) <= 0.1
            ):
                raise ValueError("Learning rate outside the bounded fit profile")
        if not _number(self.latency_weight) or not 0 <= self.latency_weight <= 1:
            raise ValueError("Invalid observed-duration penalty")
        if not _number(self.max_wall_seconds) or not 1 <= self.max_wall_seconds <= 3600:
            raise ValueError("Invalid finite fit budget")


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _features(value):
    return (
        isinstance(value, list)
        and 1 <= len(value) <= 128
        and all(
            isinstance(row, list) and len(row) == 126 and all(_number(v) for v in row)
            for row in value
        )
    )


def _metadata(value):
    return (
        isinstance(value, list)
        and len(value) == 16
        and all(_number(v) and 0 <= v <= 1 for v in value)
        and value[10:12] == [0, 0]
    )


def _box(box, width, height):
    return (
        isinstance(box, list)
        and len(box) == 4
        and all(_number(v) for v in box)
        and 0 <= box[0] < box[2] <= width
        and 0 <= box[1] < box[3] <= height
    )


def validate_record(row):
    """Reject evaluation splits, malformed observations and fabricated labels."""
    additions = (
        V2_FIELDS if isinstance(row, dict) and row.get("schema") == V2_SCHEMA else set()
    )
    if (
        not isinstance(row, dict)
        or not (REQUIRED | additions) <= set(row)
        or set(row) - REQUIRED - OPTIONAL - additions
    ):
        raise ValueError("Training record has missing or unexpected fields")
    if row["schema"] not in {SCHEMA, V2_SCHEMA} or row["split"] != "train":
        raise ValueError("Only registered train observations may be fitted")
    for key in ("record_id", "episode_id", "source_group", "origin_run_id"):
        if not isinstance(row[key], str) or not 1 <= len(row[key]) <= 512:
            raise ValueError("Original observation identity is required")
    size = row["source_size"]
    if not isinstance(size, dict) or set(size) != {"width", "height"}:
        raise ValueError("Registered public source size is required")
    w, h = size["width"], size["height"]
    if (
        any(type(v) is not int or not 1 <= v <= 100000 for v in (w, h))
        or w * h > 16_000_000
    ):
        raise ValueError("Source image outside the registered codec bound")
    if not _features(row["candidate_features"]) or not _metadata(
        row["public_metadata"]
    ):
        raise ValueError("Invalid public feature or metadata tensor")
    candidates = row["candidate_metadata"]
    if not isinstance(candidates, list) or len(candidates) != len(
        row["candidate_features"]
    ):
        raise ValueError("Candidate metadata and feature rows differ")
    for candidate in candidates:
        if (
            not isinstance(candidate, dict)
            or set(candidate) != {"text", "bbox", "origin"}
            or not isinstance(candidate["text"], str)
            or len(candidate["text"]) > 8192
            or candidate["origin"]
            not in {"pixel_ocr", "registered_public_text", "no_recognized_text"}
            or not _box(candidate["bbox"], w, h)
        ):
            raise ValueError("Invalid observed candidate")
    field = row["reference_field"]
    if (
        field not in FIELD_NAMES
        or row["public_metadata"][:4] != [float(field == f) for f in FIELD_NAMES]
        or not isinstance(row["expected_text"], str)
        or not 1 <= len(row["expected_text"]) <= 8192
        or not isinstance(row["target_boxes"], list)
        or not 1 <= len(row["target_boxes"]) <= 128
        or not all(_box(b, w, h) for b in row["target_boxes"])
    ):
        raise ValueError("Invalid train-only reference supervision")
    if row["action"] not in ACTION_NAMES or row["execution_status"] not in {
        "completed",
        "failed",
    }:
        raise ValueError("Observed action or execution status is invalid")
    if row["action"] == "READ_ROI" and row["public_metadata"][8] != 1:
        raise ValueError("Region read was not legal in the current public state")
    for name in ("before_score", "after_score"):
        if (
            name == "after_score"
            and row[name] is None
            and row["execution_status"] == "failed"
        ):
            continue
        if not _number(row[name]) or not 0 <= row[name] <= 1:
            raise ValueError("Only observed finite rubric scores are accepted")
    if not _number(row["duration_seconds"]) or not 0 < row["duration_seconds"] <= 3600:
        raise ValueError("Observed action duration must be positive and bounded")
    following, meta = row["next_candidate_features"], row["next_public_metadata"]
    if row.get("terminal_reason") not in {None, "budget_stop", "actor_stop"}:
        raise ValueError("Invalid observed trajectory censoring reason")
    if following is None or meta is None:
        if not (
            following is None
            and meta is None
            and (
                row["action"] == "STOP"
                or row["execution_status"] == "failed"
                or row.get("terminal_reason") in {"budget_stop", "actor_stop"}
            )
        ):
            raise ValueError(
                "A completed nonterminal action needs its observed successor"
            )
    elif not _features(following) or not _metadata(meta):
        raise ValueError("Invalid actually observed successor")
    for name in OPTIONAL & set(row):
        value = row[name]
        if value is not None and (not isinstance(value, str) or len(value) > 512):
            raise ValueError("Invalid source provenance field")
        if (
            name.endswith("sha256")
            and value is not None
            and (len(value) != 64 or any(c not in "0123456789abcdef" for c in value))
        ):
            raise ValueError("Invalid original artifact digest")
    if additions:
        validate_link(row)
    return row


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate training JSON field")
        result[key] = value
    return result


def load_records(path):
    import torch
    from ndu_real_materials.evaluator import canonical

    path = Path(path)
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size > 512 * 1024 * 1024
    ):
        raise ValueError("Training JSONL outside the bounded regular-file profile")
    rows, original_rows, ids, content_keys = [], [], set(), set()
    counts = Counter()
    groups, episodes, origins = set(), set(), set()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for number, raw in enumerate(stream, 1):
            if len(raw) > 2 * 1024 * 1024 or number > 10000 or not raw.strip():
                raise ValueError("Training JSONL exceeds its line/count bound")
            digest.update(raw)
            row = validate_record(json.loads(raw, object_pairs_hook=_strict_object))
            original_rows.append(row)
            if row["record_id"] in ids:
                raise ValueError("Duplicate original transition identity")
            ids.add(row["record_id"])
            groups.add(row["source_group"])
            episodes.add(row["episode_id"])
            origins.add(row["origin_run_id"])
            expected = canonical(row["expected_text"], row["reference_field"])
            if expected is None:
                raise ValueError(
                    "Reference is outside the independently fixed normalizer"
                )
            positives = [
                i
                for i, candidate in enumerate(row["candidate_metadata"])
                if canonical(candidate["text"], row["reference_field"]) == expected
            ]
            key = canonical_sha(
                [
                    row[k]
                    for k in (
                        "candidate_features",
                        "candidate_metadata",
                        "reference_field",
                        "expected_text",
                        "target_boxes",
                    )
                ]
            )
            first_content = key not in content_keys
            content_keys.add(key)
            scale = torch.tensor(
                [row["source_size"][k] for k in ("width", "height", "width", "height")]
            )
            packed = {
                k: row[k]
                for k in (
                    "record_id",
                    "before_score",
                    "after_score",
                    "duration_seconds",
                    "schema",
                    "origin_run_id",
                    "episode_id",
                )
            }
            if row["schema"] == V2_SCHEMA:
                packed.update({key: row[key] for key in V2_FIELDS})
            packed.update(
                features=torch.tensor(row["candidate_features"], dtype=torch.float32),
                meta=torch.tensor(row["public_metadata"], dtype=torch.float32),
                boxes=torch.tensor([c["bbox"] for c in row["candidate_metadata"]])
                / scale,
                targets=torch.tensor(row["target_boxes"]) / scale,
                positives=positives,
                action=ACTION_NAMES.index(row["action"]),
                first_content=first_content,
                next_features=None
                if row["next_candidate_features"] is None
                else torch.tensor(row["next_candidate_features"], dtype=torch.float32),
                next_meta=None
                if row["next_public_metadata"] is None
                else torch.tensor(row["next_public_metadata"], dtype=torch.float32),
            )
            rows.append(packed)
            counts["rows"] += 1
            counts["action:" + row["action"]] += 1
            counts["status:" + row["execution_status"]] += 1
            counts["exact_candidate_covered"] += bool(positives)
            counts["exact_candidate_missing"] += not positives
            counts["successor_observed"] += packed["next_features"] is not None
            counts["after_score_observed"] += row["after_score"] is not None
            if row.get("terminal_reason"):
                counts["terminal:" + row["terminal_reason"]] += 1
    chains = validate_chains(original_rows)
    return rows, {
        "sha256": digest.hexdigest(),
        "bytes": path.stat().st_size,
        "counts": dict(counts),
        "complete_v2_chains": chains,
        "legacy_v1_rows": sum(r["schema"] == SCHEMA for r in rows),
        "source_groups": len(groups),
        "episodes": len(episodes),
        "origin_run_ids": sorted(origins),
        "unique_content_states": len(content_keys),
        "record_ids_sha256": canonical_sha(sorted(ids)),
        "observed_collection_action_seconds": sum(r["duration_seconds"] for r in rows),
        "collection_cost_reused_not_charged_again_by_each_fit": True,
    }


def parameter_sha(model, *, content_only=False):
    digest = hashlib.sha256()
    for name, value in sorted(model.state_dict().items()):
        if content_only and not name.startswith(CONTENT_PREFIXES):
            continue
        tensor = value.detach().cpu().contiguous()
        digest.update(name.encode())
        digest.update(str((str(tensor.dtype), tuple(tensor.shape))).encode())
        digest.update(tensor.numpy().tobytes())
    return digest.hexdigest()


def supervised_terms(row, logits, delta):
    import torch
    from torch.nn import functional as F

    # Marginal cross-entropy over all exact correct candidates; never invent an
    # answer index when real OCR omitted the reference.
    ce = (
        -torch.logsumexp(logits.log_softmax(0)[row["positives"]], 0)
        if row["positives"]
        else logits.sum() * 0
    )
    difference = (
        row["boxes"][:, None, :] + delta[:, None, :] - row["targets"][None, :, :]
    )
    distances = (
        F.smooth_l1_loss(difference, torch.zeros_like(difference), reduction="none")
        .mean(-1)
        .min(-1)
        .values
    )
    box = (logits.softmax(0) * distances).sum()
    return ce, box


def control_terms(model, row, state, following, *, regime, controller, latency_weight):
    import torch
    from torch.nn import functional as F

    world_connected = regime == "joint" and controller in {
        "ndu",
        "ndu_policy",
        "voi",
        "mpc",
    }
    light_connected = regime == "joint" and controller == "light"
    x = state if world_connected else state.detach()
    utility = F.mse_loss(
        model.utility_head(x).sigmoid().squeeze(), x.new_tensor(row["before_score"])
    )
    if following is not None and row["after_score"] is not None:
        nx = following if world_connected else following.detach()
        utility = (
            utility
            + F.mse_loss(
                model.utility_head(nx).sigmoid().squeeze(),
                nx.new_tensor(row["after_score"]),
            )
        ) / 2
    prediction, duration = model.predict_transition(
        x[None], torch.tensor([row["action"]])
    )
    transition = (
        prediction.sum() * 0
        if following is None
        else F.mse_loss(prediction[0], following.detach())
    )
    duration_loss = F.smooth_l1_loss(
        duration.log1p().squeeze(), x.new_tensor(row["duration_seconds"]).log1p()
    )
    lx = state if light_connected else state.detach()
    values = model.light_head(lx)
    # Current observed utility supplies a terminal STOP anchor. No unobserved
    # continuation is called a best action, and no future score enters actors.
    light = F.mse_loss(values[-1], lx.new_tensor(row["before_score"]))
    if row["after_score"] is not None:
        target = row["after_score"] - latency_weight * row["duration_seconds"]
        light = (light + F.mse_loss(values[row["action"]], lx.new_tensor(target))) / 2
    total = utility + transition + duration_loss + light
    connected = (
        utility + transition + duration_loss
        if world_connected
        else light
        if light_connected
        else None
    )
    return (
        total,
        connected,
        {
            "utility": utility,
            "transition": transition,
            "duration": duration_loss,
            "light": light,
        },
    )


def _source_pins():
    root = Path(__file__).resolve().parents[2]
    paths = [
        Path(__file__),
        *[
            Path(__file__).with_name(n + ".py")
            for n in (
                "neural",
                "ocr",
                "controllers",
                "metering",
                "span_meter",
                "objective",
                "trajectory",
                "recursive_objective",
                "fit_loop",
            )
        ],
        Path(__file__).with_name("finite_entropic_golden.json"),
        root / "scripts/ndu_real_materials/evaluator.py",
        root
        / "experiments/multimodal_output_portfolio/joint_hepta_20261029/hepta_core.py",
    ]
    return {str(p.relative_to(root)): file_sha(p) for p in paths}


def _save_weights(model, path):
    import torch

    with Path(path).open("xb") as stream:
        torch.save(model.state_dict(), stream)
        stream.flush()
        os.fsync(stream.fileno())
    return file_sha(path)


def run(args):
    config = FitConfig(
        args.content_epochs,
        args.fit_epochs,
        args.batch_size,
        args.content_lr,
        args.lr,
        args.latency_weight,
        args.max_wall_seconds,
    )
    output = Path(args.output)
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    identity = args.run_id or "fit-" + uuid.uuid4().hex
    meter = Meter(identity, journal_path=output / "training.meter.jsonl")
    stage = "bootstrap" if args.bootstrap else "content" if args.content_only else "fit"
    report = {
        "schema": "ndu.real.training-receipt.v1",
        "run_id": identity,
        "runtime_job_id": args.runtime_job_id,
        "status": "STARTED",
        "stage": stage,
        "core": args.core,
        "regime": args.regime,
        "controller": args.controller,
        "seed": args.seed,
        "config": asdict(config),
        "source_pins": _source_pins(),
        "training_replicate": stage == "fit" and args.replicate_role == "fit",
        "replicate_role": "collector" if stage == "bootstrap" else args.replicate_role,
        "independent_replicate_unit": "training seed; cores/controllers/LR candidates are paired, not additional repeats",
        "episode_seeds_are_independent_fits": False,
        "threads": 1,
        "gpu_used": False,
        "labels_exported_to_actor": False,
        "deployment_artifact": "weights.pt",
        "scientific_admission": "HOLD",
        "learning_disposition": "not_decided_by_trainer",
    }
    report["optimizer_profile"] = {
        "content_lr": config.content_lr,
        "auxiliary_lr": config.lr,
        "clip": "separate content and auxiliary L2 norms at 1; no unused-head clipping into content",
    }
    atomic_json(output / "started.json", report)
    model = None
    code = 1
    try:
        if not 0 <= args.seed < 2**32 or (
            args.regime == "joint" and args.controller == "shared"
        ):
            raise ValueError("Invalid seed or shared joint controller")
        if args.control_plan:
            control = json.loads(args.control_plan.read_text())
            plan = ControlPlan(**control["control"])
            report["control_plan_sha256"] = file_sha(args.control_plan)
        else:
            plan = ControlPlan(
                latency_weight=config.latency_weight,
                memory_mode=args.memory_mode or "reset",
            )
        if (
            plan.latency_weight != config.latency_weight
            or args.memory_mode is not None
            and plan.memory_mode != args.memory_mode
        ):
            raise ValueError("Training and deployment control profiles differ")
        report.update(
            memory_mode=plan.memory_mode,
            control=asdict(plan),
            utility_profile=utility_profile(plan),
            utility_profile_sha256=canonical_sha(utility_profile(plan)),
            control_profile_sha256=canonical_sha(asdict(plan)),
        )
        with meter.stage(
            "sync", "load pinned training runtime and initialize independent weights"
        ):
            import torch
            from .neural import ReceiptPortfolioModel

            torch.set_num_threads(1)
            if torch.get_num_interop_threads() != 1:
                torch.set_num_interop_threads(1)
            torch.use_deterministic_algorithms(True)
            torch.manual_seed(args.seed)
            model = ReceiptPortfolioModel(args.core).float()
            report["torch_version"] = torch.__version__
            report["initial_parameter_sha256"] = parameter_sha(model)
            report["initial_content_sha256"] = parameter_sha(model, content_only=True)
            report["parameter_count"] = sum(p.numel() for p in model.parameters())
            report["content_parameter_count"] = sum(
                p.numel() for p in model.content_parameters()
            )
            report["auxiliary_parameter_count"] = (
                report["parameter_count"] - report["content_parameter_count"]
            )
        if stage != "bootstrap":
            deadline = time.perf_counter() + config.max_wall_seconds
            with meter.stage("encoder", "admit train-only actual observation records"):
                rows, report["records"] = load_records(args.records)
                if (
                    args.expected_records_sha256
                    and report["records"]["sha256"] != args.expected_records_sha256
                ):
                    raise ValueError(
                        "Actual records differ from the precommitted file digest"
                    )
                if not rows:
                    raise ValueError("No eligible real training records")
                v2_rows = [row for row in rows if row["schema"] == V2_SCHEMA]
                if any(
                    row["utility_profile_sha256"] != report["utility_profile_sha256"]
                    for row in v2_rows
                ):
                    raise ValueError("Collected and fitted utility profiles differ")
                rubrics = {row["rubric_sha256"] for row in v2_rows}
                if len(rubrics) > 1:
                    raise ValueError("Training mixes independent rubric revisions")
                report["rubric_sha256"] = next(iter(rubrics), None)
                report["behavior_control_profile_sha256"] = sorted(
                    {row["behavior_control_profile_sha256"] for row in v2_rows}
                )
                episode_groups(rows, plan.memory_mode)
                report.update(memory_replay_metadata(rows, plan.memory_mode))
            if args.pretrained:
                with meter.stage(
                    "sync", "admit shared content checkpoint and its original receipt"
                ):
                    base = Path(args.pretrained)
                    previous = json.loads((base / "receipt.json").read_text())
                    expected = (
                        previous.get("status") == "CONTENT_PRETRAINED"
                        and previous.get("stage") == "content"
                        and previous.get("seed") == args.seed
                        and previous.get("core") == args.core
                        and previous.get("records", {}).get("sha256")
                        == report["records"]["sha256"]
                        and previous.get("source_pins") == report["source_pins"]
                        and previous.get("memory_mode") == plan.memory_mode
                        and previous.get("utility_profile_sha256")
                        == report["utility_profile_sha256"]
                        and all(
                            previous["config"][k] == asdict(config)[k]
                            for k in ("content_epochs", "content_lr", "batch_size")
                        )
                    )
                    if not expected or file_sha(base / "weights.pt") != previous.get(
                        "weights_sha256"
                    ):
                        raise ValueError(
                            "Shared content seed/core/data/source/budget binding differs"
                        )
                    model.load_state_dict(
                        torch.load(
                            base / "weights.pt", map_location="cpu", weights_only=True
                        ),
                        strict=True,
                    )
                    if parameter_sha(model) != previous["final_parameter_sha256"]:
                        raise ValueError("Shared content parameter bytes differ")
                    report["reused_content"] = {
                        "receipt_sha256": file_sha(base / "receipt.json"),
                        "run_id": previous["run_id"],
                        "cost_in_original_receipt": True,
                    }
            else:
                report["content_training"] = _epochs(
                    model,
                    rows,
                    config,
                    phase="content",
                    seed=args.seed,
                    regime=args.regime,
                    controller=args.controller,
                    meter=meter,
                    output=output,
                    deadline=deadline,
                    plan=plan,
                )
            report["pretrained_content_sha256"] = parameter_sha(
                model, content_only=True
            )
            report["prefit_parameter_sha256"] = parameter_sha(model)
            if stage == "fit":
                if not any(r["next_features"] is not None for r in rows):
                    raise ValueError(
                        "Observed transition coverage is insufficient for a fit"
                    )
                if args.regime == "frozen":
                    for p in model.content_parameters():
                        p.requires_grad_(False)
                        p.grad = None
                report["fit_training"] = _epochs(
                    model,
                    rows,
                    config,
                    phase="fit",
                    seed=args.seed,
                    regime=args.regime,
                    controller=args.controller,
                    meter=meter,
                    output=output,
                    deadline=deadline,
                    plan=plan,
                )
                with meter.stage(
                    "critic", "fit residual scale from actual training successors"
                ):
                    report["residual_estimate"] = _residuals(
                        model, rows, deadline, plan=plan
                    )
                report["joint_content_gradient_source"] = (
                    "none: content frozen"
                    if args.regime == "frozen"
                    else "frozen reference recursive utility and exact frozen-Q policy improvement plus observed auxiliary losses"
                    if report["fit_training"]["recursive_objective_applied"]
                    else "observed light action values"
                    if args.controller == "light"
                    else "observed utility and transition/duration"
                    if args.controller in {"ndu", "voi", "mpc"}
                    else "none: fixed controller; supervised content and detached common auxiliary heads"
                )
                report["common_auxiliary_heads_trained"] = [
                    "utility",
                    "transition",
                    "duration",
                    "light",
                ]
                report["combined_objective"] = (
                    "exact-candidate CE + 4*normalized-box SmoothL1 + utility MSE + transition MSE + log-duration SmoothL1 + observed-light MSE"
                )
                if report["fit_training"]["recursive_objective_applied"]:
                    report["combined_objective"] += (
                        " + frozen-reference negative recursive V0 + negative exact policy expectation; unit weights"
                    )
        report["final_parameter_sha256"] = parameter_sha(model)
        report["final_content_sha256"] = parameter_sha(model, content_only=True)
        if (
            stage == "fit"
            and args.regime == "frozen"
            and report["final_content_sha256"] != report["pretrained_content_sha256"]
        ):
            raise ValueError("Frozen content changed during controller training")
        if (
            stage == "fit"
            and args.regime == "joint"
            and report["final_content_sha256"] == report["pretrained_content_sha256"]
        ):
            raise ValueError("Joint fit changed no actual content parameter bytes")
        with meter.stage(
            "sync", "save weights-only deployment checkpoint and verify exact reload"
        ):
            report["weights_sha256"] = _save_weights(
                model, output / "candidate-weights.pt"
            )
            restored = ReceiptPortfolioModel(args.core).float()
            restored.load_state_dict(
                torch.load(
                    output / "candidate-weights.pt",
                    map_location="cpu",
                    weights_only=True,
                ),
                strict=True,
            )
            if parameter_sha(restored) != report["final_parameter_sha256"]:
                raise ValueError("Saved checkpoint parameter replay differs")
            report["checkpoint_parameter_replay_exact"] = True
        if _source_pins() != report["source_pins"] or (
            stage != "bootstrap"
            and file_sha(args.records) != report["records"]["sha256"]
        ):
            raise ValueError(
                "Frozen source or original records changed during training"
            )
        if (
            args.control_plan
            and file_sha(args.control_plan) != report["control_plan_sha256"]
        ):
            raise ValueError("Control plan changed during training")
        if stage != "bootstrap" and time.perf_counter() > deadline:
            raise TimeoutError(
                "Original finite fit budget exhausted before checkpoint publication"
            )
        report["deployment_profile_sha256"] = atomic_json(
            output / "deployment-profile.json",
            {
                "schema": "ndu.real.deployment-profile.v1",
                "weights_sha256": report["weights_sha256"],
                "core": args.core,
                "memory_mode": plan.memory_mode,
                "utility_profile_sha256": report["utility_profile_sha256"],
                "control_profile_sha256": report["control_profile_sha256"],
                "rubric_sha256": report.get("rubric_sha256"),
                "recursive_policy_trained": report.get("fit_training", {}).get(
                    "recursive_objective_applied", False
                ),
            },
        )
        os.link(output / "candidate-weights.pt", output / "weights.pt")
        (output / "candidate-weights.pt").unlink()
        report["status"] = {
            "bootstrap": "BOOTSTRAP_READY_NOT_A_FIT",
            "content": "CONTENT_PRETRAINED",
            "fit": "FITTED_NOT_ADOPTED",
        }[stage]
        code = 0
    except BaseException as error:
        report["status"] = "FAILED"
        report["error"] = {"type": type(error).__name__, "message": str(error)}
        (output / "traceback.txt").write_text(traceback.format_exc())
        if model is not None:
            report["failed_weights_sha256"] = _save_weights(
                model, output / "failed-weights.pt"
            )
    finally:
        report["meter"] = meter.finish(
            "FAILED" if report["status"] == "FAILED" else "SUCCEEDED"
        )
        report["max_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (
            1 if sys.platform == "darwin" else 1024
        )
        report["cost_scope"] = (
            "Meter excludes interpreter startup and final receipt serialization; outer supervisor owns the full child envelope. Collection/acquisition/prior fits remain separately charged."
        )
        atomic_json(output / "receipt.json", report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "output": str(output),
                "run_id": identity,
                "weights_sha256": report.get("weights_sha256"),
                "exit_code": code,
            }
        )
    )
    return code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path)
    parser.add_argument("--expected-records-sha256")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--core", choices=("ordinary", "hepta"), required=True)
    parser.add_argument("--regime", choices=("frozen", "joint"), default="frozen")
    parser.add_argument(
        "--controller",
        choices=("shared", "light", "ndu", "ndu_policy", "voi", "mpc", "tuned_fixed"),
        default="shared",
    )
    parser.add_argument("--control-plan", type=Path)
    parser.add_argument("--memory-mode", choices=("reset", "persistent"))
    stage = parser.add_mutually_exclusive_group()
    stage.add_argument("--bootstrap", action="store_true")
    stage.add_argument("--content-only", action="store_true")
    parser.add_argument("--pretrained", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--runtime-job-id")
    parser.add_argument("--replicate-role", choices=("fit", "collector"), default="fit")
    for name, kind, default in (
        ("content-epochs", int, 12),
        ("fit-epochs", int, 12),
        ("batch-size", int, 32),
        ("content-lr", float, 0.003),
        ("lr", float, 0.003),
        ("latency-weight", float, 0.01),
        ("max-wall-seconds", float, 600),
    ):
        parser.add_argument("--" + name, type=kind, default=default)
    args = parser.parse_args(argv)
    if (not args.bootstrap and args.records is None) or (
        (args.bootstrap or args.content_only) and args.pretrained
    ):
        parser.error("Fit/content need --records; only a fit can reuse --pretrained")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
