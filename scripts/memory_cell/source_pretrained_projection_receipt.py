"""Bounded real pinned Qwen2.5-3B + PEFT source-only loss comparison.

Research-only implementation audit. It does not execute evaluation questions,
evaluate answer quality, certify citations, or select a production adapter.
"""

import argparse
import json
import math
from pathlib import Path
import resource
import time

import torch

from experience_memory import ExperienceReader, source_examples
from experience_write_trial import model_inputs, original_documents
from native import digest
from source_completion_loss import completion_loss
from source_write_schedule import prepare


def compare(sources, model_dir, output, *, source_sha, stage_sha, commit):
    if (
        len(commit) != 40
        or any(c not in "0123456789abcdef" for c in commit)
        or output.exists()
    ):
        raise ValueError("exact generating source and absent receipt path required")
    import peft
    import transformers

    if (
        transformers.__version__ != "4.57.1"
        or peft.__version__ != "0.17.1"
        or not torch.__version__.startswith("2.5.1")
    ):
        raise ValueError("unregistered model implementation or library version")
    stage, inventory = model_inputs(model_dir, stage_sha)
    if stage["tier"] != "qwen-3b":
        raise ValueError("only the pinned research Qwen2.5-3B tier is admitted")
    docs = original_documents(sources, source_sha)
    examples, unknown = source_examples(
        docs, revision=2, allowed_roots={d.root for d in docs}, revoked=set()
    )
    reader = ExperienceReader(
        model_dir / "reader", expected_inventory=inventory["inventory_digest"]
    )
    prepared, schedule = prepare(
        reader.tokenizer, examples, maximum_steps=128, token_ceiling=65536
    )
    # A source-only minimum-length example controls CPU memory; no test query
    # or answer labels are opened or used to choose this comparison input.
    scheduled = schedule["entries"]
    if not scheduled:
        raise ValueError("no scheduled source-writing example for pretrained parity")
    chosen = min(set(scheduled), key=lambda i: (len(prepared[i][0]), i))
    ids, labels = prepared[chosen]
    if len(ids) > 768:
        raise ValueError("no bounded original source-only example for CPU proof")
    model = reader.model
    if any(p.device.type != "cpu" for p in model.parameters()):
        raise ValueError("expected frozen CPU BF16 research reader before proof")
    parameters = {name: p for name, p in model.named_parameters() if p.requires_grad}
    if not parameters:
        raise ValueError("no trainable LoRA parameters")
    start_values = {name: p.detach().clone() for name, p in parameters.items()}
    base_digest = reader.base_digest
    model.train()
    runs = []
    for backend in ("full", "supervised_positions"):
        with torch.no_grad():
            for name, value in start_values.items():
                parameters[name].copy_(value)
        model.zero_grad(set_to_none=True)
        optimizer = torch.optim.AdamW(list(parameters.values()), lr=0.0002)
        start = time.perf_counter()
        loss, projection = completion_loss(model, ids, labels, backend=backend)
        loss.backward()
        grad_norm = torch.nn.utils.clip_grad_norm_(
            list(parameters.values()), 1.0, error_if_nonfinite=True
        )
        if not torch.isfinite(grad_norm):
            raise ValueError("nonfinite actual source gradient")
        gradients = {}
        for name, p in parameters.items():
            if p.grad is None or not torch.isfinite(p.grad).all():
                raise ValueError("missing or nonfinite actual LoRA gradient")
            gradients[name] = p.grad.detach().clone()
        optimizer.step()
        updated = {name: p.detach().clone() for name, p in parameters.items()}
        if any(not torch.isfinite(p).all() for p in parameters.values()):
            raise ValueError("nonfinite pretrained LoRA parameter")
        runs.append(
            dict(
                backend=backend,
                loss=float(loss.detach()),
                pre_clip_gradient_norm=float(grad_norm.detach()),
                projection=projection,
                seconds=time.perf_counter() - start,
                peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                gradients=gradients,
                updated=updated,
            )
        )
    first, second = runs
    if first["projection"]["input_tokens"] != second["projection"]["input_tokens"]:
        raise ValueError("source input exposure changed")
    if (
        first["projection"]["supervised_tokens"]
        != second["projection"]["supervised_tokens"]
    ):
        raise ValueError("source completion exposure changed")
    torch.testing.assert_close(
        torch.tensor(first["loss"]),
        torch.tensor(second["loss"]),
        rtol=0.001,
        atol=0.001,
    )
    max_grad_difference = 0.0
    max_update_difference = 0.0
    for name in start_values:
        a, b = first["gradients"][name], second["gradients"][name]
        torch.testing.assert_close(a, b, rtol=0.02, atol=0.002)
        max_grad_difference = max(
            max_grad_difference, float((a.float() - b.float()).abs().max())
        )
        a, b = first["updated"][name], second["updated"][name]
        torch.testing.assert_close(a, b, rtol=0.01, atol=0.001)
        max_update_difference = max(
            max_update_difference, float((a.float() - b.float()).abs().max())
        )
    if reader.base_digest != base_digest:
        raise ValueError("reader model identity changed")
    from pretrained import frozen_digest

    if frozen_digest(model) != base_digest:
        raise ValueError("frozen pretrained base changed")
    if not all(
        math.isfinite(x)
        for x in (
            max_grad_difference,
            max_update_difference,
            first["loss"],
            second["loss"],
        )
    ):
        raise ValueError("nonfinite comparison")
    report = dict(
        schema="hepta.source-only.pretrained-loss-parity.v2",
        generating_commit=commit,
        source_sha256=source_sha,
        source_document_digest=digest([d.identity for d in docs]),
        model_inventory_digest=reader.identity,
        model_revision=stage["revision"],
        model_repository=stage["repository"],
        model_profile=reader.profile,
        curriculum="single_hop",
        source_example_selected_from_write_schedule=True,
        source_example_schedule_visits=scheduled.count(chosen),
        dependency_versions=dict(
            torch=torch.__version__,
            transformers=transformers.__version__,
            peft=peft.__version__,
        ),
        source_supervision_sha256=digest(examples),
        source_example_index=chosen,
        source_example_id=examples[chosen]["query"]["identity"],
        writer_schedule_sha256=digest(schedule),
        source_unknown_facts=len(unknown),
        compared_input_tokens=len(ids),
        compared_supervised_tokens=sum(x != -100 for x in labels),
        full_loss=first["loss"],
        selected_loss=second["loss"],
        maximum_gradient_absolute_difference=max_grad_difference,
        maximum_updated_parameter_absolute_difference=max_update_difference,
        full_projection_positions=first["projection"]["actual_projection_positions"],
        selected_projection_positions=second["projection"][
            "actual_projection_positions"
        ],
        first_step_seconds=first["seconds"],
        second_step_seconds=second["seconds"],
        measured_peak_rss_kib=second["peak_rss_kib"],
        trainable_parameter_count=sum(p.numel() for p in parameters.values()),
        frozen_pretrained_base_unchanged=True,
        matched_optimization_step=True,
        original_task_plan_opened=False,
        new_answer_generations=0,
        significant_task_gain=None,
        independent_semantic_citation_precision=None,
        production_accepted=False,
    )
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(report, allow_nan=False), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", type=Path)
    parser.add_argument("model", type=Path)
    parser.add_argument("receipt", type=Path)
    for name in ("source-sha", "stage-sha", "source-commit"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    compare(
        args.sources,
        args.model,
        args.receipt,
        source_sha=args.source_sha,
        stage_sha=args.stage_sha,
        commit=args.source_commit,
    )
