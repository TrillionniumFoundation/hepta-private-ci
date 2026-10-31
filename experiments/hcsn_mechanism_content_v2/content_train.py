"""Immutable content-worker records; validation selection precedes heldout access."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import resource
import sys
import time
import traceback

import numpy as np
import torch
from torch.nn import functional as F

from .content import ContentModel, GROUPS, parameter_hash
from .data import load_data, tensor_batch


def cpu_seconds():
    return time.process_time()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def create_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def append_json(path, value):
    with Path(path).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()


def snapshot(model):
    return {name: value.detach().clone() for name, value in model.state_dict().items()}


def group_gradients(model):
    result = {}
    for key, entries in model.parameter_groups().items():
        squared = sum(float(parameter.grad.detach().square().sum())
                      for _, parameter in entries if parameter.grad is not None)
        result[key] = math.sqrt(squared)
    return result


def changes(model, initial):
    result = {}
    for key, entries in model.parameter_groups().items():
        records = []
        for name, parameter in entries:
            delta = float((parameter.detach() - initial[name]).abs().max())
            records.append(dict(name=name, elements=parameter.numel(), trainable=parameter.requires_grad,
                                changed=not torch.equal(parameter.detach(), initial[name]), max_abs_change=delta))
        result[key] = dict(parameters=records, elements=sum(row["elements"] for row in records),
            changed_tensors=sum(row["changed"] for row in records),
            max_abs_change=max((row["max_abs_change"] for row in records), default=0),
            all_frozen_unchanged=all(not row["changed"] for row in records if not row["trainable"]))
    return result


def evaluate(model, values, batch_size, *, disable_adapter=False):
    logits_rows, labels, ids, positions, times, groups, event_counts = [], [], [], [], [], [], []
    batch_wall, batch_cpu, batch_samples, batch_queries = [], [], [], []
    source_columns = {key: [] for key in ("audio_source_ids", "video_source_ids", "pair_group_ids", "donor_group_ids") if key in values}
    began_cpu, began_wall = cpu_seconds(), time.perf_counter()
    model.eval()
    with torch.no_grad():
        for start in range(0, len(values["x"]), batch_size):
            tick_cpu, tick_wall = cpu_seconds(), time.perf_counter()
            indices = np.arange(start, min(start + batch_size, len(values["x"])))
            batch = tensor_batch(values, indices)
            logits = model(batch["x"], batch["dt"], batch["observed"], batch["valid"],
                           disable_adapter=disable_adapter)
            row, position = torch.where(batch["y"] >= 0)
            if not len(row):
                raise ValueError("Evaluation batch has no labeled query")
            logits_rows.append(logits[row, position].numpy())
            labels.append(batch["y"][row, position].numpy())
            outer = indices[row.numpy()]
            ids.extend(values["ids"][outer].astype(str).tolist())
            positions.extend(position.tolist())
            relative = np.cumsum(values["dt"][outer], axis=1)
            clock = values.get("timestamps", None)
            times.extend((clock[outer, position.numpy()] if clock is not None
                          else relative[np.arange(len(outer)), position.numpy()]).tolist())
            groups.extend(values.get("group_ids", values["ids"])[outer].astype(str).tolist())
            event_counts.extend(values["observed"][outer].cumsum(1)[
                np.arange(len(outer)), position.numpy()].tolist())
            for key in source_columns:
                source_columns[key].extend(values[key][outer].astype(str).tolist())
            batch_wall.append(time.perf_counter() - tick_wall)
            batch_cpu.append(cpu_seconds() - tick_cpu)
            batch_samples.append(len(indices))
            batch_queries.append(len(row))
    loop_cpu, loop_wall = cpu_seconds() - began_cpu, time.perf_counter() - began_wall
    logits = np.concatenate(logits_rows)
    target = np.concatenate(labels)
    tensor = torch.from_numpy(logits)
    probabilities = tensor.softmax(-1).numpy()
    metrics = dict(accuracy=float((logits.argmax(-1) == target).mean()),
        ce=float(F.cross_entropy(tensor, torch.from_numpy(target))), queries=len(target),
        samples=len(values["x"]), array_sha256=values["metadata"]["array_sha256"],
        inference_cost=dict(prepared_input_batch_loop_cpu_seconds=loop_cpu,
            prepared_input_batch_loop_wall_seconds=loop_wall,
            per_batch_wall_seconds=batch_wall, per_batch_cpu_seconds=batch_cpu,
            per_batch_samples=batch_samples, per_batch_queries=batch_queries,
            samples_per_second=len(values["x"]) / loop_wall, queries_per_second=len(target) / loop_wall,
            scope="tensor_batch + whole-sequence forward + labeled readout/ID extraction; no data loading, codec or incremental KV cache",
            inclusive="per_batch timing is contained in batch_loop; all are contained in worker body cost"))
    raw = dict(logits=logits, probabilities=probabilities, labels=target,
        sample_ids=np.asarray(ids), group_ids=np.asarray(groups), position=np.asarray(positions),
        readout_time=np.asarray(times), observed_event_count=np.asarray(event_counts),
        input_array_sha256=np.asarray(values["metadata"]["array_sha256"]))
    raw.update({key: np.asarray(column) for key, column in source_columns.items()})
    return metrics, raw


def run(job, output, *, allow_test=False):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    began_cpu, began_wall = cpu_seconds(), time.perf_counter()
    create_json(output / "job.json", job)
    (output / "access.jsonl").touch(exist_ok=False)
    (output / "trace.jsonl").touch(exist_ok=False)
    try:
        torch.set_num_threads(1)
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            pass
        torch.manual_seed(job["seed"])
        rng = np.random.default_rng(job["seed"] + 7109)
        config = {key: job[key] for key in ("task", "family", "seed")}
        config.update({key: job.get(key, default) for key, default in
                       (("width", 32), ("depth", 2), ("physical", 1))})
        model = ContentModel(**config)
        pretrained = job.get("pretrained")
        donor_hash = None
        if pretrained:
            donor_hash = file_hash(pretrained)
            if not job.get("pretrained_sha256") or donor_hash != job["pretrained_sha256"]:
                raise ValueError("An exact matching pretrained checkpoint SHA is required")
            donor = torch.load(pretrained, map_location="cpu", weights_only=False)
            model.load_shared(donor)
        if job.get("content_mode", "joint") == "frozen_shared" and not pretrained:
            raise ValueError("Frozen shared content requires a source-identified common checkpoint")
        if job.get("content_mode", "joint") not in ("joint", "frozen_shared"):
            raise ValueError("Unknown content training mode")
        model.freeze(shared=job.get("content_mode") == "frozen_shared",
                     groups=job.get("freeze_groups", []))
        initial = {name: parameter.detach().clone() for name, parameter in model.named_parameters()}
        initial_hash, common_initial = parameter_hash(model), parameter_hash(model.common)
        with (output / "initial_parameters.pt").open("xb") as stream:
            torch.save(dict(config=model.config, parameters=initial,
                requires_grad={name: parameter.requires_grad for name, parameter in model.named_parameters()},
                groups={key: [name for name, _ in entries] for key, entries in model.parameter_groups().items()},
                model_sha256=initial_hash, common_sha256=common_initial), stream)
        initial_file_hash = file_hash(output / "initial_parameters.pt")
        trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
        if not trainable:
            raise ValueError("This training job has no trainable parameters")
        optimizer = torch.optim.Adam(trainable, lr=job.get("learning_rate", .003))
        source_root = Path(__file__).resolve().parents[2]
        source_identity = {}
        for module_name, module in sorted(sys.modules.items()):
            module_path = getattr(module, "__file__", None)
            if module_name.startswith("experiments.") and module_path and str(module_path).endswith(".py"):
                resolved = Path(module_path).resolve()
                source_identity[str(resolved.relative_to(source_root))] = file_hash(resolved)
        for filename in ("content.py", "data.py", "binding_data.py", "content_train.py", "content_tests.py"):
            resolved = Path(__file__).resolve().with_name(filename)
            source_identity[str(resolved.relative_to(source_root))] = file_hash(resolved)
        create_json(output / "source_identity.json", source_identity)
        data_load_costs = []

        def acquire(split, length=None, diagnostic=None):
            append_json(output / "access.jsonl", dict(event="open_data", split=split,
                length=length, diagnostic=diagnostic, after_selection=(output / "selection.json").exists(),
                body_cpu=cpu_seconds() - began_cpu, allowed_heldout=allow_test))
            tick_cpu, tick_wall = cpu_seconds(), time.perf_counter()
            values = load_data(job, split, length=length, diagnostic=diagnostic, allow_heldout=allow_test)
            data_load_costs.append(dict(split=split, length=length, diagnostic=diagnostic,
                cpu_seconds=cpu_seconds() - tick_cpu, wall_seconds=time.perf_counter() - tick_wall,
                input_array_sha256=values["metadata"]["array_sha256"]))
            return values

        training, validation = acquire("train"), acquire("val")
        create_json(output / "data_sources.json", dict(train=training["metadata"],
            validation=validation["metadata"], train_ids=training["ids"].astype(str).tolist(),
            validation_ids=validation["ids"].astype(str).tolist()))
        audiovisual = job["task"] in ("async_av", "av_binding")
        batch_size = job.get("batch_size", 6 if audiovisual else 16)
        eval_batch = job.get("eval_batch_size", batch_size)
        before_metrics, _ = evaluate(model, validation, eval_batch)
        initial_allowed = job.get("allow_initial_selection", True)
        best_ce, best_step = before_metrics["ce"] if initial_allowed else math.inf, 0
        best_state, best_optimizer = snapshot(model), optimizer.state_dict()
        best_torch_rng, best_numpy_rng = torch.get_rng_state().clone(), rng.bit_generator.state
        validation_records = [dict(step=0, **before_metrics)]
        steps = job.get("max_updates", job.get("updates", 128))
        budget = job.get("budget_cpu_seconds")
        if not isinstance(steps, int) or steps <= 0 or (budget is not None and budget <= 0):
            raise ValueError("Positive training budget required")
        loop_cpu = cpu_seconds()
        update_cpu, validation_cpu = 0.0, 0.0
        clipped = 0
        gradient_max = {key: 0.0 for key in GROUPS}
        gradient_nonzero = {key: 0 for key in GROUPS}
        stop_reason = "max_updates"
        for step in range(1, steps + 1):
            model.train()
            selected = rng.integers(0, len(training["x"]), size=batch_size)
            batch = tensor_batch(training, selected)
            tick = cpu_seconds()
            optimizer.zero_grad(set_to_none=True)
            logits = model(batch["x"], batch["dt"], batch["observed"], batch["valid"])
            loss = F.cross_entropy(logits.flatten(0, 1), batch["y"].flatten(), ignore_index=-100)
            if not bool(torch.isfinite(loss)):
                raise FloatingPointError("Nonfinite training loss")
            loss.backward()
            norms = group_gradients(model)
            if not all(math.isfinite(value) for value in norms.values()):
                raise FloatingPointError("Nonfinite parameter gradient")
            total_norm = float(torch.nn.utils.clip_grad_norm_(trainable, job.get("clip_grad_norm", 1.0)))
            clipped += int(total_norm > job.get("clip_grad_norm", 1.0))
            optimizer.step()
            update_cpu += cpu_seconds() - tick
            for key, norm in norms.items():
                gradient_max[key] = max(gradient_max[key], norm)
                gradient_nonzero[key] += int(norm > 0)
            append_json(output / "trace.jsonl", dict(step=step, loss=float(loss.detach()),
                gradient_norm=total_norm, group_gradient_norm=norms,
                training_cpu=cpu_seconds() - loop_cpu, selected_indices=selected.tolist()))
            last = step == steps or (budget is not None and cpu_seconds() - loop_cpu >= budget)
            if step % job.get("validate_every", 32) == 0 or last:
                tick = cpu_seconds()
                metrics, _ = evaluate(model, validation, eval_batch)
                validation_cpu += cpu_seconds() - tick
                validation_records.append(dict(step=step, **metrics))
                if metrics["ce"] < best_ce:
                    best_ce, best_step, best_state = metrics["ce"], step, snapshot(model)
                    # Serialize later; deep-copy mutable optimizer tensors now.
                    import copy
                    best_optimizer = copy.deepcopy(optimizer.state_dict())
                    best_torch_rng = torch.get_rng_state().clone()
                    best_numpy_rng = copy.deepcopy(rng.bit_generator.state)
            if budget is not None and cpu_seconds() - loop_cpu >= budget:
                stop_reason = "cpu_budget"
                break
        training_cpu = cpu_seconds() - loop_cpu
        final_changes, final_common_hash = changes(model, initial), parameter_hash(model.common)
        common_frozen = job.get("content_mode") == "frozen_shared"
        if common_frozen and final_common_hash != common_initial:
            raise AssertionError("Frozen shared content changed")
        if any(not result["all_frozen_unchanged"] for result in final_changes.values()):
            raise AssertionError("A frozen parameter tensor changed")

        def checkpoint(path, selected_step, optimizer_state, torch_rng, numpy_rng):
            state = snapshot(model)
            payload = dict(schema="hcsn-content-v2.checkpoint", config=model.config, job=job,
                model_state=state, common_state={name: value.detach().clone() for name, value in model.common.state_dict().items()},
                common_sha256=parameter_hash(model.common), model_sha256=parameter_hash(model),
                optimizer_state=optimizer_state, torch_rng=torch_rng,
                numpy_rng=numpy_rng, step=selected_step,
                inherited_common_checkpoint_sha256=donor_hash)
            with path.open("xb") as stream:
                torch.save(payload, stream)
            return file_hash(path)

        final_hash = checkpoint(output / "final.pt", step, optimizer.state_dict(),
                                torch.get_rng_state(), rng.bit_generator.state)
        model.load_state_dict(best_state)
        selected_hash = checkpoint(output / "selected.pt", best_step, best_optimizer,
                                   best_torch_rng, best_numpy_rng)
        selected_changes = changes(model, initial)
        create_json(output / "selection.json", dict(rule="minimum validation CE, first tie",
            selected_step=best_step, initial_allowed=initial_allowed, best_validation_ce=best_ce,
            selected_checkpoint_sha256=selected_hash, final_checkpoint_sha256=final_hash,
            validation_records=validation_records, heldout_opened_before_selection=False))
        profile, _ = evaluate(model, validation, 1)
        request_times = profile["inference_cost"]["per_batch_wall_seconds"]
        create_json(output / "inference_profile_validation.json", dict(
            selected_checkpoint_sha256=selected_hash,
            input_array_sha256=validation["metadata"]["array_sha256"],
            request_ids=validation["ids"].astype(str).tolist(),
            batch_size=1, repeats=1, warmup="prior validation/training; no additional warmup",
            mean_wall_seconds=float(np.mean(request_times)),
            mean_cpu_seconds=float(np.mean(profile["inference_cost"]["per_batch_cpu_seconds"])),
            p50_wall_seconds=float(np.quantile(request_times, .5)),
            p95_wall_seconds=float(np.quantile(request_times, .95)),
            quantile_method="linear", **profile["inference_cost"],
            limitation="prepared-feature whole-sequence requests; not realtime sensor/codec/network latency"))
        results = {}
        evaluation_plan = [("val", job.get("length", 32), None)]
        if allow_test:
            lengths = [job.get("length", 32)] if audiovisual else job.get("eval_lengths", [32, 64, 128])
            evaluation_plan += [("test", length, None) for length in lengths]
            if job.get("diagnostics", True):
                diagnostics = ["content_shuffle", "missing_audio", "missing_video"] if audiovisual else ["content_shuffle"] + (["query_permute"] if job["task"] == "mqar" else [])
                if job["task"] == "async_av":
                    diagnostics.append("modality_mismatch")
                if job["task"] == "av_binding":
                    diagnostics.append("metadata_only")
                evaluation_plan += [("test", lengths[0], item) for item in diagnostics]
        for split, length, diagnostic in evaluation_plan:
            values = validation if split == "val" else acquire(split, length, diagnostic)
            label = f"{split}_length{length}_{diagnostic or 'normal'}"
            metrics, raw = evaluate(model, values, eval_batch)
            raw.update(checkpoint_sha256=np.asarray(selected_hash), model_sha256=np.asarray(parameter_hash(model)))
            with (output / ("predictions_" + label + ".npz")).open("xb") as stream:
                np.savez_compressed(stream, **raw)
            results[label] = dict(**metrics, data=values["metadata"])
            if allow_test and split == "test" and diagnostic is None and length == job.get("length", 32) and model.adapter is not None:
                metrics_disabled, disabled = evaluate(model, values, eval_batch, disable_adapter=True)
                disabled.update(checkpoint_sha256=np.asarray(selected_hash), model_sha256=np.asarray(parameter_hash(model)))
                with (output / ("predictions_" + label + "_adapter_disabled.npz")).open("xb") as stream:
                    np.savez_compressed(stream, **disabled)
                results[label + "_adapter_disabled"] = metrics_disabled
        create_json(output / "data_preparation_costs.json", dict(records=data_load_costs,
            scope="raw NPZ loading, feature preparation/compression or synthetic generation; no media decode", 
            inclusive="contained in worker body cost, excluded from prepared-input inference timing"))
        summary = dict(schema="hcsn-content-v2.summary", completed=True, job=job,
            selected_step=best_step, final_step=step, stop_reason=stop_reason,
            initialization_model_sha256=initial_hash, shared_initial_sha256=common_initial,
            initial_parameters_sha256=initial_file_hash,
            shared_final_sha256=final_common_hash, shared_selected_sha256=parameter_hash(model.common),
            pretrained_checkpoint_sha256=donor_hash, selected_checkpoint_sha256=selected_hash,
            shared_donor_selected_step=donor["step"] if pretrained else None,
            shared_donor_trained=bool(donor["step"] > 0) if pretrained else None,
            final_checkpoint_sha256=final_hash, model_parameter_sha256=parameter_hash(model),
            total_parameters=sum(p.numel() for p in model.parameters()),
            trainable_parameters=sum(p.numel() for p in model.parameters() if p.requires_grad),
            shared_parameters=sum(p.numel() for p in model.common.parameters()),
            final_group_changes=final_changes, selected_group_changes=selected_changes,
            gradient_max=gradient_max, gradient_nonzero_steps=gradient_nonzero, clipped_steps=clipped,
            results=results, heldout_access=allow_test,
            costs=dict(body_cpu_seconds=cpu_seconds() - began_cpu, body_wall_seconds=time.perf_counter() - began_wall,
                training_budget_cpu_seconds=training_cpu, optimizer_steps_cpu=update_cpu,
                validation_inside_training_cpu=validation_cpu, max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                data_preparation_cpu_seconds=sum(item["cpu_seconds"] for item in data_load_costs),
                data_preparation_wall_seconds=sum(item["wall_seconds"] for item in data_load_costs),
                validation_single_request_profile="inference_profile_validation.json",
                budget_overshoot_seconds=max(0, training_cpu - budget) if budget is not None else None,
                budget_scope="optimizer minibatches, trace writes and scheduled validation; may overshoot by one batch/validation",
                inclusive="optimizer_steps and scheduled validation are within training_budget; training, preparation, post-selection inference and serialization are within body",
                whole_worker_external_meter_required=True, energy_joules=None, gpu_used=False),
            runtime=dict(python=platform.python_version(), torch=torch.__version__, numpy=np.__version__,
                         threads=torch.get_num_threads()),
            scope="shared learned causal content/SDPA; finite-grid analytic adapter; no foundation-model or energy claim")
        create_json(output / "summary.json", summary)
        return summary
    except Exception as error:
        create_json(output / "FAILED.json", dict(error=repr(error), traceback=traceback.format_exc(),
            body_cpu_seconds=cpu_seconds() - began_cpu, body_wall_seconds=time.perf_counter() - began_wall))
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-test", action="store_true")
    args = parser.parse_args()
    result = run(json.loads(args.job.read_text()), args.output, allow_test=args.allow_test)
    print(json.dumps(dict(completed=True, selected_step=result["selected_step"], costs=result["costs"])))


if __name__ == "__main__":
    main()

