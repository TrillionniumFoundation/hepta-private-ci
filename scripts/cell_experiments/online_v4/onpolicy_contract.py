"""Separate warm-start research identities; original admission remains unchanged."""

import copy
import importlib
from importlib import metadata
from pathlib import Path
import re

from .. import causal_probe_v3 as probe, data
from ..coding_sft import file_hash

MODEL_SCHEMA = "hepta.current-policy-sft-model.v1"
PLAN_SCHEMA = "hepta.current-policy-sft-plan.v1"
PROFILE = "research.current-policy-sft.v1"
SCOPE = {
    "research_only": True, "native_cell_adoption": False,
    "scientific_confirmation_qualified": False, "proof_of_useful_work_eligible": False,
    "circuit_qualified": False, "new_C": False, "candidate_selected": None,
    "independent_selection": False, "independent_sample_increment": 0,
    "external_teacher_count_added": 0, "new_users": 0,
    "exposure": "old_exposed_development_only",
}


def legacy():
    module = importlib.import_module("research_sft_contract_v1")
    module.helpers()
    return module


def sources():
    return {"online_v4": {p.name: file_hash(p) for p in sorted(Path(__file__).parent.glob("*.py"))},
            "legacy": legacy().sources()}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_model(manifest, root):
    """Validate native bases, old research artifacts, or this distinct new schema."""
    old = legacy()
    if manifest.get("schema") == probe.SCHEMA:
        return probe.verify_model(manifest, root)
    if manifest.get("schema") == old.MODEL_SCHEMA:
        return old.verify_model(manifest, root)
    require(manifest.get("schema") == MODEL_SCHEMA and manifest.get("profile") == PROFILE,
            "unsupported current-policy candidate")
    require(all(manifest.get(k) == v for k, v in SCOPE.items()), "candidate scope changed")
    require(manifest.get("source_inventory") == sources(), "current-policy source changed")
    base = manifest["base_manifest"]
    require(probe.verify_model(base, root) == manifest.get("base_model_digest")
            and manifest.get("model_id") == probe.MODEL_ID
            and manifest.get("runtime") == base["runtime"]
            and manifest.get("backend_versions") == base["backend_versions"]
            and manifest.get("peft_version") == metadata.version("peft"),
            "base, runtime, or backend identity changed")
    require(manifest.get("training_settings") == old.TRAINING
            and manifest.get("optimizer_initialization") == "fresh_AdamW_each_round"
            and manifest.get("retention") == "latest_round_only",
            "training or retention profile changed")
    for key in ("previous_model_digest", "parameter_before", "parameter_after", "training_plan_digest"):
        require(isinstance(manifest.get(key), str)
                and re.fullmatch(r"[0-9a-f]{64}", manifest[key]) is not None,
                "missing candidate hash: " + key)
    adapter = probe._base(root, manifest["adapter_directory"])
    files = probe._inventory(adapter)
    names = {row["path"] for row in files}
    require(files == manifest.get("adapter_files")
            and {"adapter_config.json", "adapter_model.safetensors"} <= names
            and names <= {"adapter_config.json", "adapter_model.safetensors", "README.md"},
            "adapter files changed")
    config = probe._json(adapter / "adapter_config.json")
    expected = {"peft_type": "LORA", "task_type": "CAUSAL_LM", "r": 4, "lora_alpha": 8,
                "lora_dropout": 0.0, "bias": "none", "inference_mode": True}
    require(all(config.get(k) == v for k, v in expected.items())
            and set(config.get("target_modules", [])) == {"q_proj", "v_proj"},
            "LoRA configuration changed")
    return data.digest(manifest)


def training_binding(manifest, root):
    """Bind the previous actual training record before trusting its tensor hash."""
    verify_model(manifest, root)
    if manifest.get("schema") == probe.SCHEMA:
        return None
    directory = probe._base(root, manifest["adapter_directory"])
    path = directory.parent / "TRAINING.json"
    require(path.is_file() and not path.is_symlink(), "previous training record missing")
    value = probe._json(path)
    key = "candidate_model_digest" if manifest["schema"] == MODEL_SCHEMA else "research_model_digest"
    require(value.get("status") == "COMPLETE" and value.get(key) == data.digest(manifest)
            and value.get("steps") == legacy().TRAINING["steps"],
            "previous training is not bound to this candidate")
    after = value.get("parameter_after")
    require(isinstance(after, str) and re.fullmatch(r"[0-9a-f]{64}", after) is not None,
            "previous tensor hash missing")
    if manifest["schema"] == MODEL_SCHEMA:
        require(after == manifest.get("parameter_after"), "previous tensor identities differ")
    return {"path": path.relative_to(root).as_posix(), "sha256": file_hash(path),
            "bytes": path.stat().st_size, "parameter_after": after,
            "candidate_model_digest": data.digest(manifest)}


def make_plan(records, initial, root, context, *, operation_id, round_index, mode):
    require(mode in {"teacher", "shadow", "controlled"}, "explicit collection mode required")
    require(type(round_index) is int and 0 <= round_index < 4, "round index outside bound")
    require(isinstance(operation_id, str) and 0 < len(operation_id.encode()) <= 256,
            "bounded operation identity required")
    old = legacy()
    base = initial if initial.get("schema") == probe.SCHEMA else initial["base_manifest"]
    require(base == context["parent"], "warm-start base differs from fixed baseline")
    return {
        "schema": PLAN_SCHEMA, "profile": PROFILE, "operation_id": operation_id,
        "round_index": round_index, "collection_mode": mode,
        "previous_model_digest": verify_model(initial, root),
        "previous_training": training_binding(initial, root),
        "base_model_digest": data.digest(base), "records_digest": data.digest(records),
        "reference_admission": old.reference_admission(records, context, "trajectory"),
        "training": copy.deepcopy(old.TRAINING), "source_inventory": sources(),
        "retention": "latest_round_only", "optimizer_initialization": "fresh_AdamW_each_round",
        "student_actions_trainable": False, **SCOPE,
    }


def validate_plan(records, initial, root, context, plan):
    expected = make_plan(records, initial, root, context,
                         operation_id=plan.get("operation_id"),
                         round_index=plan.get("round_index"), mode=plan.get("collection_mode"))
    require(plan == expected, "warm-start plan, source, previous model or records changed")
