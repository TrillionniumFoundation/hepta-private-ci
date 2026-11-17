"""Data, readiness, plan and candidate identity for the Qwen LoRA profile."""

import hashlib
from importlib import metadata
import math
from pathlib import Path
import time

from . import causal_probe_v3 as probe, data
from .circuit_receipts_v3 import business_evidence
from .coding_sft import file_hash


SCHEMA = "hepta.causal-lora-model.v3"
FAMILY = "hepta-qwen25-coder-lora-v3"
PLAN_SCHEMA = "hepta.causal-lora-plan.v3"


def sources():
    return {p.name: file_hash(p) for p in sorted(Path(__file__).parent.glob("*.py"))}


def admit(records, mode):
    if not records or mode not in ("final_answer", "trajectory"):
        raise ValueError("nonempty A records and an explicit SFT mode required")
    data.validate_records(records)
    if len({row["task_id"] for row in records}) != len(records):
        raise ValueError("one training record per task required")
    for row in records:
        if (
            row["split"] != "train"
            or row["authorization"]["training_allowed"] is not True
            or row["verified_outcome"]["success"] is not True
        ):
            raise ValueError("training requires authorized successful A only")
        if any(
            event["actor"] == "student" and event.get("trainable") is True
            for event in row["trajectory"]
        ):
            raise ValueError(
                "this profile masks student actions; use verified curator corrections"
            )


def readiness_witness(records, parent, readiness):
    """Require an actual successful A action by this exact parent, not a counter."""
    payload = {k: v for k, v in readiness.items() if k != "receipt_sha256"}
    if (
        readiness.get("schema") != "hepta.development-readiness.v3"
        or data.digest(payload) != readiness.get("receipt_sha256")
        or readiness.get("model_digest") != data.digest(parent)
    ):
        raise ValueError("bound parent development readiness receipt required")
    inputs = {r["task_id"]: r for r in records}
    for row in readiness.get("rows", []):
        if row.get("task_id") not in inputs:
            continue
        original = inputs[row["task_id"]]
        if any(row.get(key) != original[key] for key in ("source_id", "lineage_id")):
            continue
        for step in row.get("steps", []):
            verification, output = step.get("verification"), step.get("output", {})
            if (
                not verification
                or output.get("loaded_model_digest") != data.digest(parent)
                or verification.get("input_sha256")
                != hashlib.sha256(original["task"]["input"].encode()).hexdigest()
                or verification.get("parameters_sha256")
                != data.digest(original["task"]["verifier"]["parameters"])
            ):
                continue
            evidence = business_evidence(
                {
                    "semantic_receipt": verification,
                    "semantic_receipt_sha256": verification.get("receipt_sha256"),
                    "raw_answer": output.get("answer"),
                    "success": verification.get("success"),
                }
            )
            if evidence["business_success"] is True:
                return {
                    "task_id": row["task_id"],
                    "semantic_receipt_sha256": verification["receipt_sha256"],
                }
    raise ValueError(
        "parent has no recorded real business success on the supplied A tasks"
    )


def _settings(settings, parent):
    fixed = {
        "rank": 4,
        "lora_alpha": 8,
        "lora_dropout": 0.0,
        "target_modules": ["q_proj", "v_proj"],
        "seed": 1729,
        "optimizer": "AdamW",
        "optimizer_betas": [0.9, 0.999],
        "optimizer_eps": 1e-8,
        "weight_decay": 0.01,
        "max_grad_norm": 1.0,
        "gradient_checkpointing": True,
        "cuda_memory_fraction": 0.70,
    }
    if any(settings.get(k) != v for k, v in fixed.items()):
        raise ValueError("training profile constants changed")
    if type(settings.get("steps")) is not int or not 1 <= settings["steps"] <= 4096:
        raise ValueError("bounded integer training steps required")
    length, rate = settings.get("sequence_tokens"), settings.get("learning_rate")
    if type(length) is not int or not 16 <= length <= min(
        4096, parent["runtime"]["max_input_tokens"]
    ):
        raise ValueError("bounded complete-context sequence length required")
    if (
        type(rate) not in (int, float)
        or not math.isfinite(rate)
        or not 0 < rate <= 0.01
    ):
        raise ValueError("bounded finite learning rate required")
    if (
        not parent["runtime"]["device"].startswith("cuda:")
        or parent["runtime"]["dtype"] != "bfloat16"
    ):
        raise ValueError("training profile requires explicit CUDA bfloat16")


def make_plan(
    records,
    parent,
    readiness,
    *,
    mode,
    operation_id,
    steps=64,
    sequence_tokens=1536,
    learning_rate=0.0003,
):
    admit(records, mode)
    if not isinstance(operation_id, str) or not 1 <= len(operation_id.encode()) <= 256:
        raise ValueError("bounded operation identity required")
    settings = {
        "steps": steps,
        "sequence_tokens": sequence_tokens,
        "learning_rate": learning_rate,
        "rank": 4,
        "lora_alpha": 8,
        "lora_dropout": 0.0,
        "target_modules": ["q_proj", "v_proj"],
        "seed": 1729,
        "optimizer": "AdamW",
        "optimizer_betas": [0.9, 0.999],
        "optimizer_eps": 1e-8,
        "weight_decay": 0.01,
        "max_grad_norm": 1.0,
        "gradient_checkpointing": True,
        "cuda_memory_fraction": 0.70,
    }
    _settings(settings, parent)
    return {
        "schema": PLAN_SCHEMA,
        "operation_id": operation_id,
        "created_at_ns": time.time_ns(),
        "parent_model_digest": data.digest(parent),
        "records_digest": data.digest(records),
        "training_source_ids": sorted({r["source_id"] for r in records}),
        "mode": mode,
        "readiness_digest": data.digest(readiness),
        "readiness_witness": readiness_witness(records, parent, readiness),
        "source_inventory": sources(),
        "training": settings,
        "backend_versions": {
            **parent["backend_versions"],
            "peft": metadata.version("peft"),
        },
        "schedule": "record=step%record_count; turn=(step//record_count)%turn_count",
        "loss": "mean next-token cross entropy at labels[1:] != -100; full causal context retained",
        "independent_sample_increment": 0,
        "external_teacher_count_added": 0,
        "scientific_confirmation_qualified": False,
        "native_cell_adoption": False,
    }


def validate_plan(records, parent, readiness, plan):
    admit(records, plan.get("mode"))
    if (
        plan.get("schema") != PLAN_SCHEMA
        or plan.get("records_digest") != data.digest(records)
        or plan.get("parent_model_digest") != data.digest(parent)
    ):
        raise ValueError("training data or parent differs from frozen plan")
    if plan.get("source_inventory") != sources() or plan.get(
        "training_source_ids"
    ) != sorted({r["source_id"] for r in records}):
        raise ValueError("training source inventory differs from frozen plan")
    if plan.get("readiness_digest") != data.digest(readiness) or plan.get(
        "readiness_witness"
    ) != readiness_witness(records, parent, readiness):
        raise ValueError("readiness differs from frozen plan")
    if plan.get("backend_versions") != {
        **probe._versions(),
        "peft": metadata.version("peft"),
    }:
        raise ValueError("training backend versions differ from plan")
    _settings(plan["training"], parent)


def verify_candidate(manifest, root):
    if (manifest.get("schema"), manifest.get("family"), manifest.get("model_id")) != (
        SCHEMA,
        FAMILY,
        probe.MODEL_ID,
    ):
        raise ValueError("unsupported candidate model identity")
    parent = manifest["base_manifest"]
    if (
        probe.verify_model(parent, root) != manifest.get("parent_model_digest")
        or manifest.get("runtime") != parent["runtime"]
        or manifest.get("backend_versions") != parent["backend_versions"]
    ):
        raise ValueError("candidate base or generation policy differs")
    if manifest.get("peft_version") != metadata.version("peft"):
        raise ValueError("candidate PEFT backend changed")
    adapter = probe._base(root, manifest["adapter_directory"])
    files = probe._inventory(adapter)
    names = {row["path"] for row in files}
    if (
        files != manifest.get("adapter_files")
        or not {"adapter_config.json", "adapter_model.safetensors"} <= names
        or not names
        <= {"adapter_config.json", "adapter_model.safetensors", "README.md"}
    ):
        raise ValueError("complete immutable standalone adapter files required")
    config = probe._json(adapter / "adapter_config.json")
    expected = {
        "peft_type": "LORA",
        "task_type": "CAUSAL_LM",
        "r": 4,
        "lora_alpha": 8,
        "lora_dropout": 0.0,
        "bias": "none",
        "inference_mode": True,
    }
    if any(config.get(k) != v for k, v in expected.items()) or set(
        config.get("target_modules", [])
    ) != {"q_proj", "v_proj"}:
        raise ValueError("adapter architecture differs from frozen LoRA profile")
    return data.digest(manifest)
