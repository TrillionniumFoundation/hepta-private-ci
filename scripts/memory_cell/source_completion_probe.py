"""Bounded full/preselected-loss probe on the actual pinned pretrained reader.

Two original source-schedule examples, two independent optimizer states and one
resident frozen base. This is implementation conformance, not a trained memory
candidate or task benchmark. No task plan, labels file or output decoder is used.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import time

import torch

from bundle_trial import write
from experience_memory import ExperienceReader, STEPS, TOKEN_CEILING, source_examples
from experience_write_trial import exact_source, model_inputs, original_documents
from native import digest
from source_completion_loss import completion_loss
from source_write_schedule import prepare


def probe(sources, model_dir, output, *, source_sha, stage_sha):
    output.mkdir()
    source = exact_source()
    documents = original_documents(sources, source_sha)
    stage, inventory = model_inputs(model_dir, stage_sha)
    if stage["tier"] != "qwen-3b":
        raise ValueError("probe requires the existing exact Qwen-3B tier")
    started = time.perf_counter()
    reader = ExperienceReader(
        model_dir / "reader", expected_inventory=inventory["inventory_digest"]
    )
    examples, _ = source_examples(
        documents, revision=2, allowed_roots={d.root for d in documents}, revoked=set()
    )
    prepared, schedule = prepare(
        reader.tokenizer, examples, maximum_steps=STEPS, token_ceiling=TOKEN_CEILING
    )
    indices = schedule["entries"][:2]
    if len(indices) != 2:
        raise ValueError("two complete scheduled source examples required")
    plan = dict(
        schema="hepta.pretrained-completion-probe.v1",
        source_commit=source,
        model_staging=stage,
        reader_identity=reader.identity,
        source_sha256=source_sha,
        original_schedule_sha256=digest(schedule),
        indices=indices,
        examples_digest=digest([prepared[i] for i in indices]),
        paired_updates=2,
        total_optimizer_steps=4,
        seed=2718,
        loss_atol=0.002,
        gradient_atol=0.00002,
        gradient_rtol=0.002,
        parameter_atol=0.00002,
        optimizer="AdamW lr=0.0002; clip_norm=1",
        input_tokens_per_backend=sum(len(prepared[i][0]) for i in indices),
        initialization_and_prepare_seconds=time.perf_counter() - started,
        task_inputs_consumed=False,
        production_accepted=False,
    )
    write(output / "plan.json", plan)
    params = {name: p for name, p in reader.model.named_parameters() if p.requires_grad}
    initial = {name: p.detach().clone() for name, p in params.items()}
    states = {
        b: {n: p.clone() for n, p in initial.items()}
        for b in ("full", "supervised_positions")
    }
    optimizers = {
        b: torch.optim.AdamW(list(params.values()), lr=0.0002) for b in states
    }
    records, comparisons = [], []
    reader.model.train()
    try:
        with (output / "raw.jsonl").open("x") as journal:
            for step, index in enumerate(indices):
                ids, labels = prepared[index]
                order = (
                    ("full", "supervised_positions")
                    if step == 0
                    else ("supervised_positions", "full")
                )
                grads, losses = {}, {}
                for backend in order:
                    with torch.no_grad():
                        for name, p in params.items():
                            p.copy_(states[backend][name])
                    optimizer = optimizers[backend]
                    optimizer.zero_grad(set_to_none=True)
                    tick = time.perf_counter()
                    loss, receipt = completion_loss(
                        reader.model, ids, labels, backend=backend
                    )
                    loss.backward()
                    grads[backend] = {
                        n: p.grad.detach().clone() for n, p in params.items()
                    }
                    losses[backend] = float(loss.detach())
                    torch.nn.utils.clip_grad_norm_(
                        list(params.values()), 1.0, error_if_nonfinite=True
                    )
                    optimizer.step()
                    elapsed = time.perf_counter() - tick
                    if any(not torch.isfinite(p).all() for p in params.values()):
                        raise ValueError("nonfinite pretrained update")
                    states[backend] = {n: p.detach().clone() for n, p in params.items()}
                    row = dict(
                        step=step,
                        example_index=index,
                        backend=backend,
                        loss=losses[backend],
                        update_seconds=elapsed,
                        computation=receipt,
                    )
                    records.append(row)
                    journal.write(json.dumps(row, allow_nan=False) + "\n")
                    journal.flush()
                    print(json.dumps(row, allow_nan=False), flush=True)
                maximum_grad = maximum_parameter = 0.0
                for name in params:
                    a, b = grads["full"][name], grads["supervised_positions"][name]
                    torch.testing.assert_close(
                        a, b, rtol=plan["gradient_rtol"], atol=plan["gradient_atol"]
                    )
                    maximum_grad = max(
                        maximum_grad, float((a.float() - b.float()).abs().max())
                    )
                    a, b = states["full"][name], states["supervised_positions"][name]
                    torch.testing.assert_close(
                        a, b, rtol=0, atol=plan["parameter_atol"]
                    )
                    maximum_parameter = max(
                        maximum_parameter, float((a.float() - b.float()).abs().max())
                    )
                difference = abs(losses["full"] - losses["supervised_positions"])
                if not math.isfinite(difference) or difference > plan["loss_atol"]:
                    raise ValueError("pretrained loss mismatch")
                comparisons.append(
                    dict(
                        step=step,
                        loss_abs=difference,
                        gradient_max_abs=maximum_grad,
                        parameter_max_abs=maximum_parameter,
                    )
                )
        delta = {
            b: sum(
                float((p.float() - initial[n].float()).square().sum())
                for n, p in state.items()
            )
            for b, state in states.items()
        }
        if any(not math.isfinite(v) or v <= 0 for v in delta.values()):
            raise ValueError("pretrained optimizer did not update parameters")
        reader.verify_frozen()
        report = dict(
            plan=plan,
            records=records,
            comparisons=comparisons,
            adapter_delta_squared_norm=delta,
            trainable_parameters=sum(p.numel() for p in params.values()),
            pretrained_weights=True,
            actual_optimizer_steps=len(records),
            base_unchanged=True,
            helper_sha256=hashlib.sha256(
                Path(__file__).with_name("source_completion_loss.py").read_bytes()
            ).hexdigest(),
            all_planned_pairs_completed=True,
            equivalence_only=True,
            full_write_completed=False,
            task_quality_evaluated=False,
            production_accepted=False,
        )
        write(output / "report.json", report)
        return report
    finally:
        reader.model.eval()
        with torch.no_grad():
            for name, p in params.items():
                p.copy_(initial[name])
                p.grad = None
                p.requires_grad_(False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sources", "model", "output"):
        parser.add_argument(name, type=Path)
    for name in ("source-sha", "stage-sha"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    probe(
        args.sources,
        args.model,
        args.output,
        source_sha=args.source_sha,
        stage_sha=args.stage_sha,
    )
