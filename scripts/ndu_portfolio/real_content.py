"""Bounded real-image/VLM content-gradient qualification, not a benefit trial.

The disclosed image is development material. Frozen image/text embeddings feed
the pinned V3 core and named content slots. A real frozen language decoder keeps
its input gradient; target tokens enter only the separate loss. No native owner,
controller, independent evaluator, or adoption receipt is fabricated here.
"""

import argparse
from contextlib import contextmanager
import hashlib
import importlib.metadata
import json
from pathlib import Path
import resource
import time
import traceback


MODEL = "HuggingFaceTB/SmolVLM2-256M-Video-Instruct"
REVISION = "067788b187b95ebe7b2e040b3e4299e342e5b8fd"
WEIGHT_SHA256 = "dcc8f4c00d30d70bb3028a1bfc373e1b1972e25919f8788183cae4ae72431ce2"
MANIFEST_SHA256 = "432a086810f32ba90ef34dc210fcb2f0f56fe8b27595266725d1846b5dad0e6c"
IMAGE_SHA256 = "8b21ba78250f852ca5990063866b1ace6432521d0251bde7f8de783b22c99a6d"
CORE_SHA256 = "54c2e9724f6cb924582451bea907d671fe510963879117dd5f00cf4e95f1e978"
PROMPT = "Identify the insect shown on the flower. Reply with one English word."
TARGET = "bee"


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def verify_model(root):
    if file_sha(root / "MANIFEST.json") != MANIFEST_SHA256:
        raise ValueError("Acquisition manifest differs from the independently recorded pin")
    manifest = json.loads((root / "MANIFEST.json").read_text())
    if not manifest.get("complete") or (manifest["model"], manifest["revision"]) != (MODEL, REVISION):
        raise ValueError("Frozen model manifest identity differs")
    seen = set()
    for record in manifest["files"]:
        relative = Path(record["path"])
        path = root / relative
        if relative.is_absolute() or ".." in relative.parts or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Model record escapes its root")
        if record["path"] in seen or path.stat().st_size != record["size"] or file_sha(path) != record["sha256"]:
            raise ValueError("Model record differs from frozen bytes")
        seen.add(record["path"])
    weights = [row for row in manifest["files"] if row["path"] == "model.safetensors"]
    if len(weights) != 1 or weights[0]["sha256"] != WEIGHT_SHA256:
        raise ValueError("Required reviewed safetensors identity is absent")
    return {"model": MODEL, "revision": REVISION, "manifest_sha256": file_sha(root / "MANIFEST.json"),
            "weights_sha256": WEIGHT_SHA256, "verified_files": len(seen)}


def tensor_sha(tensor):
    value = tensor.detach().cpu().contiguous()
    h = hashlib.sha256(str((str(value.dtype), tuple(value.shape))).encode())
    h.update(value.numpy().tobytes())
    return h.hexdigest()


def parameter_sha(module):
    h = hashlib.sha256()
    for name, tensor in sorted(module.state_dict().items()):
        h.update(name.encode()); h.update(tensor_sha(tensor).encode())
    return h.hexdigest()


@contextmanager
def meter(records, name):
    cpu, wall = time.process_time(), time.perf_counter()
    row = {"stage": name, "status": "started"}
    records.append(row)
    try:
        yield
        row["status"] = "completed"
    except BaseException:
        row["status"] = "failed"
        raise
    finally:
        row.update(cpu_seconds=time.process_time() - cpu, wall_seconds=time.perf_counter() - wall)


def bridge_class():
    import torch
    from torch import nn
    from experiments.multimodal_output_portfolio.joint_hepta_20261029 import hepta_core
    if file_sha(hepta_core.__file__) != CORE_SHA256:
        raise ValueError("V3 Hepta core differs from its reviewed source")
    HeptaCore = hepta_core.HeptaCore
    from ndu_semantic_state.state import EMPTY_SHA256, actor_binding, from_public_encodings
    from ndu_semantic_state.torch_adapter import features_torch

    class ContentBridge(nn.Module):
        def __init__(self, channels, width, mode):
            super().__init__()
            self.text = nn.Linear(channels, width)
            self.image = nn.Linear(channels, width)
            self.fusion = nn.Linear(2 * width, width)
            self.core = HeptaCore(width, depth=1, mode=mode, boundary_mode="direct")
            self.text_update = nn.Linear(2 * width, width)
            self.image_update = nn.Linear(2 * width, width)
            self.condition = nn.Linear(3 * width + 20, channels, bias=False)
            self.step_calls = 0

        def forward(self, text, image, steps):
            slots = {"text": self.text(text).tanh(), "image": self.image(image).tanh()}
            shared = self.fusion(torch.cat((slots["text"], slots["image"]), -1)).tanh()
            state = self.core.initial_state(len(shared), content=shared)
            for _ in range(steps):
                shared, state, _ = self.core.step(shared, state, 0.5)
                shared = shared.tanh()
                slots = {name: value + 0.25 * getattr(self, name + "_update")(
                    torch.cat((value, shared), -1)).tanh() for name, value in slots.items()}
                self.step_calls += 1
            slot_metadata = {"available": [True], "progress": [steps / 3], "preparation": ["ready"],
                "version": [steps + 1], "committed_prefix": [{"sha256": EMPTY_SHA256, "byte_count": 0, "content_version": 0}]}
            snapshot = from_public_encodings(shared.detach().cpu().numpy(),
                {name: value.detach().cpu().numpy() for name, value in slots.items()},
                {"slots": {name: dict(slot_metadata) for name in slots},
                 "remaining_budget": [3 - steps], "elapsed_seconds": [steps * 0.5]},
                representation="joint_content_latent")
            features = features_torch(shared, slots, snapshot, actor_binding(snapshot))
            return 0.05 * self.condition(features), {"text": slots["text"], "image": slots["image"],
                "shared": shared, "features": features, "binding": actor_binding(snapshot)}

    return ContentBridge


def run(args, report):
    import torch
    from PIL import Image
    from torch.nn import functional as F
    from transformers import AutoModelForImageTextToText, AutoProcessor

    torch.set_num_threads(2)
    torch.manual_seed(17)
    records = report["metered_stages"]
    root, image_path, output = Path(args.model_dir), Path(args.image), Path(args.output)
    with meter(records, "identity_and_input_codec"):
        report["model"] = verify_model(root)
        if file_sha(image_path) != IMAGE_SHA256:
            raise ValueError("Disclosed development image identity differs")
        with Image.open(image_path) as source:
            picture = source.convert("RGB")
            report["input_image"] = {"sha256": IMAGE_SHA256, "original_size": list(picture.size)}
            picture.thumbnail((512, 512))
        picture.save(output / "input_preview.png")
    with meter(records, "frozen_model_load"):
        processor = AutoProcessor.from_pretrained(root, local_files_only=True, trust_remote_code=False)
        processor.image_processor.size = {"longest_edge": 512}
        processor.image_processor.do_image_splitting = False
        model = AutoModelForImageTextToText.from_pretrained(root, local_files_only=True,
            trust_remote_code=False, dtype=torch.float32, attn_implementation="eager", low_cpu_mem_usage=True)
        model.eval().requires_grad_(False)
    with meter(records, "real_text_image_encoder"):
        messages = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": PROMPT}]}]
        rendered = processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
        inputs = processor(text=rendered, images=[picture], return_tensors="pt")
        with torch.no_grad():
            embeddings = model.get_input_embeddings()(inputs["input_ids"])
            visual = model.model.get_image_features(inputs["pixel_values"], inputs.get("pixel_attention_mask"))
            fused = model.model.inputs_merger(input_ids=inputs["input_ids"], inputs_embeds=embeddings,
                image_hidden_states=visual).detach().clone()
        mask = inputs["input_ids"] != model.config.image_token_id
        text = embeddings[mask].mean(0, keepdim=True).detach().clone()
        image = visual.reshape(-1, visual.shape[-1]).mean(0, keepdim=True).detach().clone()
        target_ids = processor.tokenizer.encode(TARGET, add_special_tokens=False)
        if not target_ids:
            raise ValueError("Target has no token")
        target = torch.tensor([target_ids[0]], dtype=torch.long)
        report["public_input"] = {"prompt": PROMPT, "prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
            "text_embedding_sha256": tensor_sha(text), "image_embedding_sha256": tensor_sha(image),
            "fused_embedding_sha256": tensor_sha(fused), "fused_shape": list(fused.shape),
            "image_features_shape": list(visual.shape), "target_first_token": target_ids[0], "target_ids": target_ids,
            "target_text": TARGET, "target_used_only_in_loss": True}
    with meter(records, "initial_actual_text_decode"):
        with torch.no_grad():
            tokens = model.generate(inputs_embeds=fused, attention_mask=inputs["attention_mask"],
                max_new_tokens=8, do_sample=False)
        initial_text = processor.tokenizer.decode(tokens[0], skip_special_tokens=True).strip()
        (output / "initial_text.txt").write_text(initial_text + "\n")
        report["initial_delivery"] = {"text": initial_text, "sha256": file_sha(output / "initial_text.txt"),
            "new_token_limit": 8, "task_correctness_claim": False}
    factory = bridge_class()
    report["arms"] = []
    reference_weights = None
    for mode in ("ordinary", "dual"):
        torch.manual_seed(17)
        bridge = factory(fused.shape[-1], 16, mode).float()
        if reference_weights is None:
            reference_weights = {k: v.detach().clone() for k, v in bridge.state_dict().items()}
        else:
            bridge.load_state_dict(reference_weights, strict=True)
        before_hash = parameter_sha(bridge)
        count = sum(p.numel() for p in bridge.parameters())
        active = torch.zeros_like(fused); active[:, -1, :] = 1

        def loss_at(steps):
            delta, state = bridge(text, image, steps)
            logits = model(inputs_embeds=fused + active * delta[:, None, :],
                attention_mask=inputs["attention_mask"], use_cache=False, logits_to_keep=1).logits[:, -1].float()
            return F.cross_entropy(logits, target), logits, state

        with meter(records, mode + ".initial_and_frozen_replay"):
            with torch.no_grad():
                initial, _, _ = loss_at(0)
                frozen, frozen_logits, snapshot = loss_at(3)
                replay, replay_logits, _ = loss_at(3)
            if not torch.equal(frozen_logits, replay_logits) or parameter_sha(bridge) != before_hash:
                raise ValueError("Frozen content or deterministic replay changed")
        with meter(records, mode + ".real_decoder_backward_and_one_update"):
            optimizer = torch.optim.SGD(bridge.parameters(), lr=1e-4)
            optimizer.zero_grad(set_to_none=True)
            loss, _, state = loss_at(3)
            for name in ("shared", "text", "image"):
                state[name].retain_grad()
            loss.backward()
            gradients = {name: {"connected": p.grad is not None,
                "finite": p.grad is not None and bool(torch.isfinite(p.grad).all()),
                "norm": None if p.grad is None else float(p.grad.norm())}
                for name, p in bridge.named_parameters()}
            if not all(row["connected"] and row["finite"] for row in gradients.values()):
                raise ValueError("Disconnected or nonfinite content parameter gradient")
            core_norm = sum(row["norm"] for name, row in gradients.items() if name.startswith("core."))
            state_gradients = {name: None if state[name].grad is None else float(state[name].grad.norm())
                for name in ("shared", "text", "image")}
            if core_norm <= 0 or any(value is None or value <= 0 for value in state_gradients.values()):
                raise ValueError("Actual decoder loss did not reach core and both content slots")
            optimizer.step()
        with meter(records, mode + ".joint_checkpoint_readback"):
            with torch.no_grad():
                updated, updated_logits, _ = loss_at(3)
            after_hash = parameter_sha(bridge)
            if after_hash == before_hash:
                raise ValueError("The content update changed no parameter bytes")
            checkpoint = output / (mode + ".pt")
            torch.save(bridge.state_dict(), checkpoint)
            restored = factory(fused.shape[-1], 16, mode).float()
            restored.load_state_dict(torch.load(checkpoint, weights_only=True), strict=True)
            old_bridge = bridge; bridge = restored
            with torch.no_grad():
                reloaded, reloaded_logits, _ = loss_at(3)
            bridge = old_bridge
            if not torch.equal(updated_logits, reloaded_logits) or after_hash != parameter_sha(restored):
                raise ValueError("Saved content checkpoint does not replay exactly")
        report["arms"].append({"core": mode, "parameters": count, "initial_parameter_sha256": before_hash,
            "frozen_parameter_sha256": before_hash, "joint_parameter_sha256": after_hash,
            "bridge_zero_step_token_ce": float(initial), "frozen_token_ce": float(frozen), "joint_token_ce": float(updated),
            "frozen_unchanged": True, "joint_changed": before_hash != after_hash,
            "checkpoint_exact_replay": True, "checkpoint_sha256": file_sha(checkpoint),
            "gradients": gradients, "core_gradient_norm_sum": core_norm, "state_gradients": state_gradients,
            "state_binding": snapshot["binding"], "initial_stop_owner_check": "NOT_EXECUTED",
            "control_policy_executed": False, "old_ability_retention": "NOT_EVALUATED"})
        write_json(output / "progress.json", report)
    if len({row["parameters"] for row in report["arms"]}) != 1:
        raise ValueError("Core parameter budgets differ")
    if len({row["initial_parameter_sha256"] for row in report["arms"]}) != 1:
        raise ValueError("Core initial parameter bytes differ")
    report["frozen_backbone_gradients_absent"] = all(p.grad is None for p in model.parameters())
    if not report["frozen_backbone_gradients_absent"]:
        raise ValueError("Frozen decoder accumulated parameter gradients")
    with meter(records, "postrun_model_identity"):
        if verify_model(root) != report["model"] or file_sha(image_path) != IMAGE_SHA256:
            raise ValueError("Frozen input or model changed during qualification")
    report["status"] = "PASS_SCOPED_REAL_CONTENT_GRADIENT"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    report = {"schema": "hepta.real-text-image-content-qualification.v1", "status": "STARTED",
        "seed": 17, "threads": 2, "width": 16, "core_steps": 3, "joint_updates_per_core": 1,
        "dtype": "float32", "started_unix": time.time(), "metered_stages": [],
        "qualification_scope": "frozen_real_vlm_decoder_to_named_content_and_core_gradient",
        "uses_disclosed_development_image": True, "native_cell_owner_path_executed": False,
        "independent_semantic_evaluation": False, "confirmatory_gain_experiment": False,
        "full_controller_2x2_executed": False, "production_candidate_adopted": False,
        "loss_scope": "first_target_token_cross_entropy",
        "content_scope": "two_modality_named_pooled_latent_slots_not_full_token_or_spatial_addressing",
        "state_clock_and_budget": "logical_core_time_and_remaining_update_count_not_physical_resource_meters",
        "checkpoint_scope": "weights_only_same_process_recomputation", "cold_process_replay": False,
        "runtime_state_restored": False,
        "energy_joules": None, "tool_dispatch_and_transfer_cost": None,
        "deployment_net_benefit": None, "generalization": "NOT_EVALUATED",
        "versions": {name: importlib.metadata.version(name) for name in ("torch", "transformers", "numpy", "Pillow")}}
    write_json(output / "started.json", report)
    cpu, wall = time.process_time(), time.perf_counter()
    code = 0
    try:
        run(args, report)
    except BaseException as error:
        code = 1
        report["status"] = "FAILED"
        report["error"] = {"type": type(error).__name__, "message": str(error)}
        (output / "traceback.txt").write_text(traceback.format_exc())
    finally:
        report["run_cpu_seconds_through_report_preparation"] = time.process_time() - cpu
        report["run_wall_seconds_through_report_preparation"] = time.perf_counter() - wall
        report["max_rss_kib_linux"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        report["cost_scope"] = "Internal envelope excludes startup record and final report write/exit; supervisor measures whole child. Stages are nested, not additive to that envelope. Energy, tool dispatch, transfer and prior acquisition remain unknown."
        write_json(output / "terminal.json", report)
        print(json.dumps({"status": report["status"], "output": str(output), "exit_code": code}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
