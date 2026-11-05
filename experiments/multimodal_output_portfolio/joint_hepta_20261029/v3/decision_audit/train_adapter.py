"""Real VLM output-head adaptation, separate from controllers and efficacy claims.

The frozen visual/language backbone still runs on every training image. A
rank-limited FP32 neural residual changes output logits; this is not prompt
search or image-generator training. Only processor-aligned assistant tokens
receive supervised loss. Costs include full before/after parameter hashing.
A passed visual-input intervention gate is required before a four-arm study;
this engineering trainer alone cannot establish that gate or training benefit.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import re
import time

import torch
from torch import nn
from torch.nn import functional as F

from .dual_runtime import digest_file, write_json
from .local_models import LocalModels


SCHEMA = "hepta.real-vlm-output-adapter.v1"


def tensor_hash(value):
    array = value.detach().cpu().contiguous().view(torch.uint8).reshape(-1).numpy()
    h = hashlib.sha256(str((tuple(value.shape), str(value.dtype))).encode())
    h.update(memoryview(array))
    return h.hexdigest()


def parameter_hashes(module):
    return {name: tensor_hash(value) for name, value in module.named_parameters()}


def fingerprint(hashes):
    return hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()


class OutputAdapter(nn.Module):
    """Add a neural residual to the output head without changing tied embeddings."""

    def __init__(self, width, vocabulary, rank=4, seed=17):
        super().__init__()
        if type(rank) is not int or not 1 <= rank <= 32:
            raise ValueError("Adapter rank must be an integer in [1,32]")
        self.config = {"width": width, "vocabulary": vocabulary, "rank": rank, "seed": seed}
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            self.down = nn.Linear(width, rank, bias=False, dtype=torch.float32)
            self.up = nn.Linear(rank, vocabulary, bias=False, dtype=torch.float32)
            nn.init.normal_(self.down.weight, std=0.02)
            nn.init.zeros_(self.up.weight)

    def forward(self, hidden):
        return self.up(self.down(hidden.detach().float())) / self.config["rank"]

    def attach(self, model):
        if any(p.requires_grad or p.device.type != "cpu" for p in model.parameters()):
            raise ValueError("The entire CPU backbone must be frozen before attaching")
        head = model.get_output_embeddings()
        if head is None or tuple(head.weight.shape) != (self.config["vocabulary"], self.config["width"]):
            raise ValueError("Output-head shape differs from adapter")
        if any(getattr(h, "hepta_adapter", False) for h in head._forward_hooks.values()):
            raise ValueError("An output adapter is already attached")

        def hook(module, inputs, output):
            return output.float() + self(inputs[0])

        hook.hepta_adapter = True
        return head.register_forward_hook(hook)


def save_adapter(adapter, path, base_hash, metadata):
    from safetensors.torch import save_file
    config = {**metadata, "schema": SCHEMA, "base_parameter_sha256": base_hash, **adapter.config}
    save_file(adapter.state_dict(), str(path), metadata={"hepta": json.dumps(config, sort_keys=True)})
    return digest_file(path)


def load_adapter(model, path, expected_sha256):
    """Verify the exact checkpoint and frozen backbone, attach an inference hook."""
    from safetensors import safe_open
    from safetensors.torch import load_file
    if digest_file(path) != expected_sha256:
        raise ValueError("Adapter file digest mismatch")
    with safe_open(str(path), framework="pt", device="cpu") as reader:
        config = json.loads(reader.metadata()["hepta"])
    if config["schema"] != SCHEMA or config["base_parameter_sha256"] != fingerprint(parameter_hashes(model)):
        raise ValueError("Adapter belongs to a different backbone")
    adapter = OutputAdapter(**{k: config[k] for k in ("width", "vocabulary", "rank", "seed")})
    adapter.load_state_dict(load_file(str(path)), strict=True)
    if not all(bool(torch.isfinite(p).all()) for p in adapter.parameters()):
        raise ValueError("Nonfinite adapter parameter")
    adapter.eval().requires_grad_(False)
    return adapter, adapter.attach(model)


def prepare_inputs(processor, row, max_answer_tokens=96):
    """Verify actual processor token-prefix alignment; never count characters."""
    from PIL import Image
    if digest_file(row["image_path"]) != row["image_sha256"]:
        raise ValueError("Training image changed since the frozen manifest")
    with Image.open(row["image_path"]) as raw:
        if raw.width * raw.height > 16_000_000:
            raise ValueError("Training image exceeds the pixel bound")
        image = raw.convert("RGB"); image.thumbnail((512, 512))
    user = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": row["instruction"]}]}]
    answer = {"role": "assistant", "content": [{"type": "text", "text": row["target"]}]}
    prefix = processor.apply_chat_template(user, tokenize=False, add_generation_prompt=True)
    full = processor.apply_chat_template(user + [answer], tokenize=False, add_generation_prompt=False)
    prefix_ids = processor(text=prefix, images=[image], return_tensors="pt")["input_ids"]
    inputs = processor(text=full, images=[image], return_tensors="pt")
    ids = inputs["input_ids"]; length = prefix_ids.shape[1]
    if ids.shape[0] != 1 or ids.shape[1] <= length or not torch.equal(ids[:, :length], prefix_ids):
        raise ValueError("Processor assistant-prefix token alignment failed")
    labels = ids.clone(); labels[:, :length] = -100
    labels[inputs["attention_mask"] == 0] = -100
    count = int((labels != -100).sum())
    if not 1 <= count <= max_answer_tokens:
        raise ValueError("Assistant target is empty or exceeds the token limit; no truncation")
    inputs = {k: v.to(torch.bfloat16) if v.is_floating_point() else v for k, v in inputs.items()}
    return inputs, labels, {"prefix_tokens": length, "answer_tokens": count}


def read_examples(manifest, expected_sha256):
    path = Path(manifest)
    if digest_file(path) != expected_sha256:
        raise ValueError("Training manifest digest mismatch")
    data = json.loads(path.read_text())
    if data.get("schema") != "hepta.real-adapter-training-data.v1" or data.get("role") != "training_only":
        raise ValueError("An explicit training-only manifest is required")
    rows = data["examples"]
    if not rows or len({r["source_id"] for r in rows}) != len(rows) or len({r["image_sha256"] for r in rows}) != len(rows):
        raise ValueError("One distinct source/image per row; repeated exposures are training steps")
    result = []
    for row in rows:
        if (not isinstance(row["source_id"], str) or not row["source_id"]
                or any(not isinstance(row[k], str) or not 1 <= len(row[k]) <= 4096 for k in ("instruction", "target"))):
            raise ValueError("Invalid source, instruction or target")
        image_path = (path.parent / row["image_path"]).resolve()
        if digest_file(image_path) != row["image_sha256"]:
            raise ValueError("Input bytes differ from the training source manifest")
        result.append({**row, "image_path": str(image_path)})
    return result


def train(models, manifest, output, source_sha, manifest_sha256, *, seed=17, rank=4,
          steps=4, learning_rate=0.001, max_answer_tokens=96, threads=2,
          cpu_budget=600.0, wall_budget=600.0):
    """Supervise an adapter; return explicit incomplete/failed records on failure.

    Budgets are checked at operation boundaries, not preemptive guarantees.
    The separate cost receipt covers the training, hashing, checkpoint and
    report writes; its own final journal/receipt write remains outer overhead.
    """
    started = previous = (time.process_time(), time.perf_counter())
    out = Path(output); out.mkdir(parents=True, exist_ok=False)
    events, updates, rows, order = [], [], [], []
    backend = adapter = handle = None
    before, after, adapter_before = {}, {}, {}
    status, error, checkpoint, changed_values = "failed", None, None, None
    initial_adapter_hash = reload_probe = checkpoint_artifact = None

    def record(kind, detail=None):
        nonlocal previous
        now = time.process_time(), time.perf_counter()
        event = {"id": len(events), "kind": kind, "cpu_seconds": now[0] - previous[0],
                 "wall_seconds": now[1] - previous[1], "detail": detail}
        events.append(event); previous = now
        with (out / "events.jsonl").open("a") as stream:
            stream.write(json.dumps(event, allow_nan=False) + "\n")

    def budget():
        if time.process_time() - started[0] > cpu_budget or time.perf_counter() - started[1] > wall_budget:
            raise TimeoutError("Training resource allowance exceeded at an operation boundary")

    try:
        if (not re.fullmatch(r"[0-9a-f]{40}", source_sha) or type(seed) is not int or not 0 <= seed < 2**63
                or type(steps) is not int or not 1 <= steps <= 10000
                or type(max_answer_tokens) is not int or not 1 <= max_answer_tokens <= 512
                or any(type(x) not in (float, int) or not math.isfinite(x) or x <= 0 for x in (learning_rate, cpu_budget, wall_budget))):
            raise ValueError("Invalid source identity, seed, training steps or resource allowance")
        rows = read_examples(manifest, manifest_sha256)
        rng = random.Random(seed)
        while len(order) < steps:
            cycle = list(range(len(rows))); rng.shuffle(cycle); order.extend(cycle)
        order = order[:steps]
        record("data_admission", {"declared_sources": len(rows), "planned_source_ids": [rows[i]["source_id"] for i in order]})
        budget()
        backend = LocalModels(Path(models) / "vlm", Path(models) / "sd", threads)
        backend._activate("vlm"); record("load_frozen_vlm", backend.identity())
        before = parameter_hashes(backend.model); record("full_base_parameter_hash_before")
        budget()
        vocabulary, width = backend.model.get_output_embeddings().weight.shape
        adapter = OutputAdapter(width, vocabulary, rank, seed)
        adapter_before = {n: p.detach().clone() for n, p in adapter.named_parameters()}
        initial_adapter_hash = fingerprint(parameter_hashes(adapter))
        handle = adapter.attach(backend.model)
        optimizer = torch.optim.Adam(adapter.parameters(), lr=learning_rate)
        for index, row_index in enumerate(order):
            budget(); row = rows[row_index]
            record("update_started", {"index": index, "source_id": row["source_id"]})
            inputs, labels, alignment = prepare_inputs(backend.processor, row, max_answer_tokens)
            logits = backend.model(**inputs, use_cache=False, return_dict=True).logits
            loss = F.cross_entropy(logits[:, :-1].reshape(-1, vocabulary), labels[:, 1:].reshape(-1), ignore_index=-100)
            if not bool(torch.isfinite(loss)):
                raise ValueError("Nonfinite supervised loss")
            optimizer.zero_grad(set_to_none=True); loss.backward()
            norm = torch.nn.utils.clip_grad_norm_(adapter.parameters(), 1.0, error_if_nonfinite=True)
            optimizer.step()
            if not all(bool(torch.isfinite(p).all()) for p in adapter.parameters()):
                raise ValueError("Nonfinite updated adapter parameter")
            updates.append({"index": index, "source_id": row["source_id"], "loss": float(loss.detach()),
                            "gradient_norm_before_clipping": float(norm), **alignment})
            record("update_completed", updates[-1]); del logits, loss, inputs
            budget()
        status = "completed"
    except (Exception, KeyboardInterrupt) as exc:
        status = "cancelled" if isinstance(exc, KeyboardInterrupt) else "timeout" if isinstance(exc, TimeoutError) else "failed"
        error = {"type": type(exc).__name__, "message": str(exc)}
        record("failure", error)
    try:
        if before:
            after = parameter_hashes(backend.model); record("full_base_parameter_hash_after")
            if before != after or any(p.requires_grad or p.grad is not None for p in backend.model.parameters()):
                raise ValueError("Frozen backbone changed or accumulated gradients")
        if adapter is not None:
            changed_values = sum(int((p.detach() != adapter_before[n]).sum()) for n, p in adapter.named_parameters())
            if status == "completed":
                if not changed_values:
                    raise ValueError("No generator adapter parameter changed")
                budget()
                path = out / "adapter.safetensors"
                sha = save_adapter(adapter, path, fingerprint(before),
                                   {"source_sha": source_sha, "manifest_sha256": manifest_sha256,
                                    "objective": "supervised_assistant_token_cross_entropy", "steps": len(updates)})
                checkpoint_artifact = checkpoint = {"path": path.name, "sha256": sha}
                record("save_adapter", checkpoint)
                budget()
                probe_inputs, _, _ = prepare_inputs(backend.processor, rows[order[-1]], max_answer_tokens)
                adapter.eval().requires_grad_(False)
                with torch.inference_mode():
                    expected = backend.model(**probe_inputs, use_cache=False, return_dict=True).logits
                handle.remove(); handle = None
                reloaded, handle = load_adapter(backend.model, path, sha)
                with torch.inference_mode():
                    actual = backend.model(**probe_inputs, use_cache=False, return_dict=True).logits
                reload_probe = {"equal": torch.equal(expected, actual),
                                "max_abs_diff": float((expected - actual).abs().max()),
                                "before_sha256": tensor_hash(expected), "after_sha256": tensor_hash(actual),
                                "input_ids_sha256": tensor_hash(probe_inputs["input_ids"]),
                                "source_id": rows[order[-1]]["source_id"],
                                "scope": "same_training_input_teacher_forced_logits_not_new_evaluation"}
                record("reload_and_same_input_forward_probe", reload_probe)
                if not reload_probe["equal"]:
                    raise ValueError("Saved/reloaded adapter changed actual inference logits")
                budget()
    except (Exception, KeyboardInterrupt) as exc:
        status = "cancelled" if isinstance(exc, KeyboardInterrupt) else "timeout" if isinstance(exc, TimeoutError) else "failed"
        error = {"type": type(exc).__name__, "message": str(exc)}; record("audit_or_save_failure", error)
        checkpoint = None
    finally:
        if handle is not None:
            handle.remove()
    final_adapter_hash = runtime_source_hash = None
    try:
        final_adapter_hash = fingerprint(parameter_hashes(adapter)) if adapter is not None else None
        runtime_source_hash = digest_file(__file__)
        report = {"schema": SCHEMA, "status": status, "error": error, "checkpoint": checkpoint,
                  "checkpoint_artifact": checkpoint_artifact, "source_sha": source_sha,
                  "runtime_source_sha256": runtime_source_hash, "reload_probe": reload_probe,
                  "manifest_sha256": manifest_sha256, "seed": seed, "rank": rank,
                  "planned_updates": len(order), "completed_updates": len(updates), "updates": updates,
                  "declared_source_count": len(rows), "observed_training_source_count": len({u["source_id"] for u in updates}),
                  "base_parameter_hashes_before": before, "base_parameter_hashes_after": after,
                  "base_changed_parameter_tensors": sum(before.get(k) != after.get(k) for k in set(before) | set(after)) if before and after else None,
                  "adapter_sha256_before": initial_adapter_hash, "adapter_sha256_after": final_adapter_hash,
                  "adapter_changed_parameter_values": changed_values,
                  "adapter_changed_parameter_tensors": sum(bool((p.detach() != adapter_before[n]).any()) for n, p in adapter.named_parameters()) if adapter_before else 0,
                  "adapter_parameter_count": sum(p.numel() for p in adapter.parameters()) if adapter is not None else 0,
                  "learning_rate": learning_rate, "gradient_clip_norm": 1.0,
                  "budgets": {"cpu_seconds": cpu_budget, "wall_seconds": wall_budget, "preemptive": False},
                  "scope": "local_text_decoder_adapter_training_only", "four_arm_efficacy_established": False,
                  "image_generator_updated": False, "visual_conditioning_verified": False,
                  "cost_receipt": "cost_receipt.json", "repeated_steps_are_independent_sources": False}
        record("final_audit_and_report_construction")
        budget()
        write_json(out / "report.json", report); record("report_write")
        budget()
    except (Exception, KeyboardInterrupt) as exc:
        final_error = {"type": type(exc).__name__, "message": str(exc)}
        if status == "completed" or error is None:
            status = "cancelled" if isinstance(exc, KeyboardInterrupt) else "timeout" if isinstance(exc, TimeoutError) else "failed"
            error = final_error
        checkpoint = None
        record("finalization_failure", final_error)
        # Minimal known fields also survive malformed/nonfinite configuration.
        report = {"schema": SCHEMA, "status": status, "error": error, "finalization_error": final_error,
                  "checkpoint": None, "checkpoint_artifact": checkpoint_artifact,
                  "source_sha": str(source_sha), "manifest_sha256": str(manifest_sha256),
                  "runtime_source_sha256": runtime_source_hash, "reload_probe": reload_probe,
                  "planned_updates": len(order), "completed_updates": len(updates), "updates": updates,
                  "declared_source_count": len(rows), "observed_training_source_count": len({u["source_id"] for u in updates}),
                  "base_parameter_hashes_before": before, "base_parameter_hashes_after": after,
                  "adapter_sha256_before": initial_adapter_hash, "adapter_sha256_after": final_adapter_hash,
                  "adapter_changed_parameter_values": changed_values, "cost_receipt": "cost_receipt.json",
                  "requested_cpu_budget": repr(cpu_budget), "requested_wall_budget": repr(wall_budget),
                  "four_arm_efficacy_established": False, "visual_conditioning_verified": False}
        write_json(out / "report.json", report); record("failure_report_write")
    write_json(out / "cost_receipt.json", {"events": events, "status": status, "qualified_checkpoint": checkpoint,
               "cpu_seconds": math.fsum(e["cpu_seconds"] for e in events),
               "wall_seconds": math.fsum(e["wall_seconds"] for e in events),
               "scope": "exclusive_function_intervals_through_report_write_including_model_hashes",
               "unknown_outer_costs": ["final_meter_journal_and_cost_receipt_write", "external_process_startup"],
               "training_cost_is_not_inference_cost": True})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("models", "manifest", "output", "source-sha", "manifest-sha256"):
        parser.add_argument("--" + name, required=True)
    for name, default in (("seed", 17), ("rank", 4), ("steps", 4), ("threads", 2), ("max-answer-tokens", 96)):
        parser.add_argument("--" + name, type=int, default=default)
    for name, default in (("learning-rate", .001), ("cpu-budget", 600.), ("wall-budget", 600.)):
        parser.add_argument("--" + name, type=float, default=default)
    result = train(**vars(parser.parse_args()))
    print(json.dumps({k: result[k] for k in ("status", "checkpoint", "completed_updates", "adapter_changed_parameter_values")}, indent=2))
    if result["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
