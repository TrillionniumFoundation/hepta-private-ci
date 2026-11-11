"""Registered colour-card base/adaptation study, without control admission.

The same fixed graph and native-compatible codec serve training and decoding.
All unsuccessful capability outcomes and completed training updates are kept.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import torch

from scripts.joint_generation_v4_io import PROFILES
from scripts.joint_generation_v4_model import JointGeneratorV4
from .frozen_generator import (
    FIXED_GRAPH,
    KERNELS,
    PRIVATE_PREFIXES,
    deliver,
    forward_graph,
    private_training_parameters,
    shared_digest,
)
from .generator_training import colour_card
from .native import encode_input, load_generator
from .semantic_eval import (
    MAX_IMAGE_MSE,
    MIN_COLOUR_MARGIN,
    PROMPT,
    SEMANTIC_PROFILE,
    assess,
    expected_caption,
)


BASE_VISUAL_WARMUP_UPDATES = 300


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _save(path, value):
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    path.write_bytes(raw)
    return _sha(raw)


class BaseCapabilityError(RuntimeError):
    """The trained base cannot start adaptation or open future observations."""


def _fit(model, seeds, *, private, deadline, trace_path, visual_warmup_steps=0):
    if (
        type(visual_warmup_steps) is not int
        or visual_warmup_steps < 0
        or (private and visual_warmup_steps)
    ):
        raise ValueError("Visual warmup is only available while training the base")
    started, cpu_started = time.perf_counter(), time.process_time()
    if private:
        parameters = private_training_parameters(model)
    else:
        for name, parameter in model.named_parameters():
            parameter.requires_grad_(
                not name.startswith(("actor.", "critic.", "delivery_critic."))
            )
        parameters = [p for p in model.parameters() if p.requires_grad]
    # Dense masks align input gradients. Scale Adam's matrix step to a width
    # reference, so aggregate preactivation changes do not grow with fan-in.
    groups, learning_rates = [], {}
    for name, parameter in model.named_parameters():
        if parameter.requires_grad:
            fan_in = parameter.shape[-1] if parameter.ndim >= 2 else model.width
            rate = 0.002 * min(1.0, model.width / fan_in)
            groups.append({"params": [parameter], "lr": rate})
            learning_rates[name] = rate
    optimizer = torch.optim.Adam(groups)
    records = []
    trace_path.write_text("", encoding="utf-8")
    for step, seed in enumerate(seeds):
        if time.perf_counter() >= deadline:
            raise TimeoutError("Registered training wall budget exhausted")
        _, source = colour_card(seed)
        public = encode_input(PROMPT, source)
        with torch.no_grad():
            preactivation = model.image_encoder[0](
                torch.cat(
                    (public["image"].flatten(1), public["image_mask"].flatten(1)), -1
                )
            )
        state = forward_graph(model, public)
        image_loss = (
            (model.outputs(state)["image"].sigmoid() - public["image"].flatten(1))
            .square()
            .mean()
        )
        caption_loss = padding_loss = None
        loss = 5.0 * image_loss
        visual_only = step < visual_warmup_steps
        if not visual_only:
            caption = expected_caption(source) + "\n"
            # Native commits 128 scalars: supervise the entire delivered output,
            # without letting padding dominate the meaningful caption objective.
            caption_loss, following = model.text_loss(state, caption)
            padding_loss, _ = model.text_loss(following, " " * (128 - len(caption)))
            loss = loss + caption_loss + 0.1 * padding_loss
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        if private and any(
            parameter.grad is not None
            for name, parameter in model.named_parameters()
            if not name.startswith(PRIVATE_PREFIXES)
        ):
            raise AssertionError("Frozen shared parameter received a gradient")
        torch.nn.utils.clip_grad_norm_(parameters, 5.0)
        optimizer.step()
        record = dict(
            step=step,
            phase="visual-warmup" if visual_only else "joint-content",
            source_seed=seed,
            source_sha256=_sha(source),
            caption_nll=None if caption_loss is None else float(caption_loss.detach()),
            padding_nll=None if padding_loss is None else float(padding_loss.detach()),
            image_mse=float(image_loss.detach()),
            image_encoder_max_abs=float(preactivation.abs().max()),
            image_encoder_saturated_fraction=float(
                (preactivation.abs() > 10).double().mean()
            ),
        )
        records.append(record)
        with trace_path.open("a", encoding="utf-8") as trace:
            trace.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
        if time.perf_counter() >= deadline:
            raise TimeoutError(
                "Completed update exceeded registered training wall budget"
            )
    model.eval()
    completed = time.perf_counter()
    if completed >= deadline:
        raise TimeoutError("Training finalization exceeded registered wall budget")
    return {
        "steps": len(records),
        "visual_warmup_steps": min(len(records), visual_warmup_steps),
        "private_only": private,
        "trainable_parameters": sum(p.numel() for p in parameters),
        "parameter_learning_rates": learning_rates,
        "wall_seconds": completed - started,
        "cpu_seconds": time.process_time() - cpu_started,
        "losses": records,
    }


def _evaluate(model, seeds, folder):
    folder.mkdir()
    started, rows = time.perf_counter(), []
    for seed in seeds:
        _, source = colour_card(seed)
        result = deliver(model, encode_input(PROMPT, source))
        row = assess(source, result["text"], result["image"])
        row.update(
            source_seed=seed,
            text=result["text"],
            image_sha256=_sha(result["image"]),
            framed_sha256=result["framed_sha256"],
        )
        (folder / f"{seed}.source.ppm").write_bytes(source)
        (folder / f"{seed}.output.ppm").write_bytes(result["image"])
        (folder / f"{seed}.output.txt").write_text(result["text"], encoding="utf-8")
        rows.append(row)
    result = {
        "sources": len(rows),
        "text_correct": sum(row["text_correct"] for row in rows),
        "image_correct": sum(row["image_correct"] for row in rows),
        "both_correct": sum(row["both_correct"] for row in rows),
        "all_passed": all(row["both_correct"] for row in rows),
        "wall_seconds": time.perf_counter() - started,
        "rows": rows,
    }
    _save(folder / "results.json", result)
    return result


def run_frozen_study(
    output,
    *,
    seed=41,
    base_steps=1800,
    adapter_steps=100,
    future_sources=24,
    kernel="dual",
    max_training_seconds=600.0,
):
    """Train, freeze, adapt and evaluate one preregistered content candidate."""
    for value, low, high in (
        (seed, 0, 2**31 - 1),
        (base_steps, 1, 4096),
        (adapter_steps, 1, 4096),
        (future_sources, 3, 256),
    ):
        if type(value) is not int or not low <= value <= high:
            raise ValueError("Study seed/step/source bounds")
    if (
        kernel not in KERNELS
        or type(max_training_seconds) not in (int, float)
        or not 1 <= max_training_seconds <= 3600
    ):
        raise ValueError("Unsupported kernel or training wall budget")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    deadline = started + max_training_seconds
    offset = seed * 1_000_000
    registration = {
        "schema": "hepta.bimodal.frozen-content.registration.v1",
        "seed": seed,
        "kernel": kernel,
        "fixed_graph": list(FIXED_GRAPH),
        "codec": dict(PROFILES),
        "semantic_profile": SEMANTIC_PROFILE,
        "minimum_source_colour_margin": MIN_COLOUR_MARGIN,
        "maximum_image_mse": MAX_IMAGE_MSE,
        "required_both_correct_fraction": 1.0,
        "private_prefixes": list(PRIVATE_PREFIXES),
        "prompt": PROMPT,
        "base_training_seeds": list(range(offset, offset + base_steps)),
        "adapter_training_seeds": list(
            range(offset + 10_000, offset + 10_000 + adapter_steps)
        ),
        "base_calibration_seeds": list(range(offset + 50_000, offset + 50_012)),
        "future_seeds": list(range(offset + 70_000, offset + 70_000 + future_sources)),
        "max_training_seconds": max_training_seconds,
        "loss": "caption_nll + 0.1 * padding_nll + 5.0 * image_mse",
        "curriculum": {
            "profile": "observed-image-first-v1",
            "base_visual_warmup_updates": min(BASE_VISUAL_WARMUP_UPDATES, base_steps),
            "base_joint_updates": max(0, base_steps - BASE_VISUAL_WARMUP_UPDATES),
            "private_joint_updates": adapter_steps,
            "visual_objective": "5.0 * image_mse",
            "total_base_updates": base_steps,
        },
        "optimizer": {
            "name": "Adam",
            "learning_rate": 0.002,
            "gradient_clip": 5.0,
            "matrix_rule": "learning_rate * min(1, model.width / fan_in)",
        },
    }
    registration_sha = _save(output / "registration.json", registration)
    report = {
        "schema": "hepta.bimodal.frozen-content.study.v1",
        "registration_sha256": registration_sha,
        "registration": registration,
        "status": "started",
        "bounded_content_passed": False,
        "private_training_started": False,
        "future_materialized": False,
        "semantic_scope": "generated colour-card caption and image reconstruction only",
        "general_semantic_qualification": False,
        "dynamic_admitted": False,
        "production_update": "no-update",
        "ndu_net_gain": None,
        "energy_joules": None,
        "provider_money": None,
        "real_budget_comparison_complete": False,
    }
    previous_threads = torch.get_num_threads()
    try:
        torch.set_num_threads(1)
        with torch.random.fork_rng():
            torch.manual_seed(seed)
            model = JointGeneratorV4(
                width=32,
                depth=1,
                mode=kernel,
                allow_initial_stop=True,
                suppress_redundant_verify=True,
            )
        report["base_training"] = _fit(
            model,
            registration["base_training_seeds"],
            private=False,
            deadline=deadline,
            trace_path=output / "base-training.jsonl",
            # Establish an observed image condition before the byte decoder's
            # common caption prefix and padding can dominate the shared state.
            # This consumes the registered update count; it adds no updates.
            visual_warmup_steps=registration["curriculum"][
                "base_visual_warmup_updates"
            ],
        )
        baseline = model.export_weights()
        (output / "baseline.heptapk").write_bytes(baseline)
        report["baseline_sha256"] = _sha(baseline)
        report["base_calibration"] = _evaluate(
            model, registration["base_calibration_seeds"], output / "base-calibration"
        )
        report["effective_shared_base"] = report["base_calibration"]["all_passed"]
        if not report["effective_shared_base"]:
            raise BaseCapabilityError(
                "Shared base failed decoded calibration; private adaptation and "
                "future evaluation are forbidden"
            )
        frozen_before = shared_digest(model)
        report["private_training_started"] = True
        report["adapter_training"] = _fit(
            model,
            registration["adapter_training_seeds"],
            private=True,
            deadline=deadline,
            trace_path=output / "adapter-training.jsonl",
        )
        candidate = model.export_weights()
        (output / "candidate.heptapk").write_bytes(candidate)
        report["candidate_sha256"] = _sha(candidate)
        report["shared_before_sha256"] = frozen_before
        report["shared_after_sha256"] = shared_digest(model)
        if report["shared_after_sha256"] != frozen_before:
            raise AssertionError("Private training changed frozen shared weights")
        report["shared_weights_unchanged"] = True
        before = load_generator(baseline).state_dict()
        report["changed_parameters"] = [
            name
            for name, value in model.state_dict().items()
            if not torch.equal(before[name], value)
        ]
        if not report["changed_parameters"] or any(
            not name.startswith(PRIVATE_PREFIXES)
            for name in report["changed_parameters"]
        ):
            raise AssertionError(
                "Private update did not satisfy its parameter ownership"
            )
        report["shared_gradients_absent"] = all(
            parameter.grad is None and not parameter.requires_grad
            for name, parameter in model.named_parameters()
            if not name.startswith(PRIVATE_PREFIXES)
        )
        freeze = {
            key: report[key]
            for key in (
                "registration_sha256",
                "baseline_sha256",
                "candidate_sha256",
                "shared_before_sha256",
            )
        }
        report["candidate_freeze_sha256"] = _save(
            output / "candidate-freeze.json", freeze
        )
        # Future input bytes and decoded outcomes materialize only after freeze.
        report["future_materialized"] = True
        report["baseline_future"] = _evaluate(
            load_generator(baseline),
            registration["future_seeds"],
            output / "baseline-future",
        )
        cold = load_generator(candidate)
        report["candidate_future"] = _evaluate(
            cold, registration["future_seeds"], output / "candidate-future"
        )
        report["cold_checkpoint_roundtrip"] = cold.export_weights() == candidate
        _, source = colour_card(registration["future_seeds"][0])
        public = encode_input(PROMPT, source)
        report["cold_delivery_exact"] = deliver(model, public) == deliver(cold, public)
        report["bounded_content_passed"] = bool(
            report["effective_shared_base"]
            and report["candidate_future"]["all_passed"]
            and report["cold_checkpoint_roundtrip"]
            and report["cold_delivery_exact"]
        )
        report["status"] = "completed"
    except BaseException as error:
        report.update(
            status="failed", error_type=type(error).__name__, error=str(error)
        )
        raise
    finally:
        torch.set_num_threads(previous_threads)
        report["wall_seconds"] = time.perf_counter() - started
        _save(output / "report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=41)
    parser.add_argument("--base-steps", type=int, default=1800)
    parser.add_argument("--adapter-steps", type=int, default=100)
    parser.add_argument("--future-sources", type=int, default=24)
    parser.add_argument("--kernel", choices=KERNELS, default="dual")
    parser.add_argument("--max-training-seconds", type=float, default=600.0)
    outcome = run_frozen_study(**vars(parser.parse_args()))
    print(
        json.dumps(
            {
                key: outcome[key]
                for key in ("status", "bounded_content_passed", "production_update")
            }
        )
    )
