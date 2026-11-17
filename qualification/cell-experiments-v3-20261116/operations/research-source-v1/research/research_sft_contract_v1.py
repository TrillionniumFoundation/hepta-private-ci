"""Separate, unqualified authored-target research; never native admission."""

import copy
import hashlib
import importlib
import re
from importlib import metadata
from pathlib import Path
import sys
import time
from types import SimpleNamespace


PROFILE = "research.authored-sft.v1"
PLAN_SCHEMA = "hepta.research-authored-sft-plan.v1"
MODEL_SCHEMA = "hepta.research-authored-sft-model.v1"
FAMILY = "hepta-qwen25-coder-research-authored-sft-v1"
ADMISSION = "verified_authored_A_research_only"
PARENT03_RESULT_SHA = "33d0d5359edf547afa6d5de36a9db5f691b14a5eca4387c0ebcdd36b6d6f550d"
PARENT03_FREEZE_SHA = "02fa20ad7ce2d74d8631dd5a6ac1a2b8a5496a8632244fcdf4676eb1c21aad2c"
PARENT_MODEL_DIGEST = "f63def6407c72c0b6e19647f5879582ab8ed35e4f6207352be931a9f417b0ff6"
MODULES = (
    "research_sft_contract_v1.py", "research_sft_train_v1.py",
    "research_sft_execution_v1.py", "run_research_sft_v1.py",
)
HELPERS04 = {
    "qwen_development_io_v3.py": "4116cfc058cfbec9bdca4845e409d0c1c2071d9da9faa4b56f9d8aa6df5a2060",
    "qwen_development_inputs_v3.py": "6bd1b2d71857c5b541ca63ce815cbb05660b75284fc7065e5766e43d910fea20",
    "qwen_development_execution_v3.py": "b28824a766115de190946055225452743dc95482de53a3d872781a7922b77656",
    "run_qwen_development_v3.py": "1f8cbc7eb21cae9a1e82654b3234e839f7cbe6cfa055f40900d16a559d72bb20",
}
SCOPE = {
    "research_only": True, "protocol_changed_after_observed_failure": True,
    "scientific_confirmation_qualified": False, "native_cell_adoption": False,
    "proof_of_useful_work_eligible": False, "circuit_qualified": False,
    "new_C": False, "candidate_selected": None, "independent_selection": False,
    "independent_sample_increment": 0, "external_teacher_count_added": 0,
    "new_users": 0, "exposure": "old_exposed_development_only",
    "E3": "BLOCKED: no authenticated additional teachers",
    "E4": "BLOCKED: no trained circuit and matched ablation experiment",
    "E5": "BLOCKED: no independent source-growth cohorts",
    "E6": "BLOCKED: repeated exposed tasks; no independent selection, new C or adoption",
}
TRAINING = {
    "steps": 64, "sequence_tokens": 1536, "learning_rate": 0.0003,
    "rank": 4, "lora_alpha": 8, "lora_dropout": 0.0,
    "target_modules": ["q_proj", "v_proj"], "seed": 1729, "optimizer": "AdamW",
    "optimizer_betas": [0.9, 0.999], "optimizer_eps": 1e-8,
    "weight_decay": 0.01, "max_grad_norm": 1.0,
    "gradient_checkpointing": True, "cuda_memory_fraction": 0.70,
}
_bound = None


def bind_helpers(directory):
    """Verify immutable helper04 before importing it; never patch its globals."""
    global _bound
    directory = Path(directory)
    if not directory.is_absolute() or directory != directory.resolve() or not directory.is_dir():
        raise ValueError("absolute nonsymlink helper04 directory required")
    for name, expected in HELPERS04.items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("helper04 bytes changed: " + name)
        module = sys.modules.get(path.stem)
        if module is not None and Path(module.__file__).resolve() != path:
            raise ValueError("preloaded helper is not the frozen helper04")
    if _bound is not None and _bound.directory != directory:
        raise ValueError("research helper directory cannot change in a process")
    sys.path.insert(0, str(directory))
    loaded = [importlib.import_module(Path(name).stem) for name in HELPERS04]
    _bound = SimpleNamespace(directory=directory, io=loaded[0], inputs=loaded[1],
                             execution=loaded[2], runner=loaded[3])
    return _bound


def helpers():
    if _bound is None:
        raise ValueError("bind exact helper04 before research operations")
    return _bound


def scope_guard(value):
    io = helpers().io
    io.require(io.canonical({key: value.get(key) for key in SCOPE}) == io.canonical(SCOPE),
               "research scope changed")


def research_inventory():
    io = helpers().io
    directory = Path(__file__).resolve().parent
    return {name: io.file_hash(directory / name) for name in MODULES}


def sources():
    from cell_experiments import causal_training_contract_v3 as original
    return {"research": research_inventory(),
            "helpers04": dict(HELPERS04), "core64": original.sources()}


def baseline(context):
    """A genuine zero remains zero; baseline completeness is still required."""
    from cell_experiments import data
    h, parent = helpers(), context["parent"]
    operation = context["parent_operation"]
    h.io.verify_receipt(operation)
    h.io.require(operation.get("schema") == "hepta.qwen-readiness-operation-result.v3"
                 and operation.get("status") == "COMPLETE"
                 and operation.get("new_C") is False and operation.get("training_started") is False
                 and operation.get("model_digest") == data.digest(parent),
                 "complete bound parent03 baseline required")
    gate = h.inputs.bound_readiness(context["records"], parent, context["readiness"],
                                    context["generation_digest"])
    h.io.require(gate == context["gate"]
                 and type(operation.get("successful_A_tasks")) is int
                 and operation["successful_A_tasks"] == gate["successful_A_tasks"],
                 "baseline observations or true A count changed")
    return gate


def reference_admission(records, context, mode):
    """Bind each authorized A target to actual original/control evidence."""
    from cell_experiments import data, causal_training_contract_v3 as original
    h = helpers()
    gate = baseline(context)
    original.admit(records, mode)
    a = context["records"][:6]
    h.io.require(len(records) == len(a) == 6
                 and tuple(row["task_id"] for row in records) == tuple(row["task_id"] for row in a),
                 "all six original A tasks in their fixed order are required")
    references = []
    for row, old in zip(records, a):
        h.io.require(row["task"] == old["task"] and row["final_answer"] == old["final_answer"]
                     and all(row[key] == old[key] for key in
                             ("task_id", "source_id", "lineage_id", "split", "authorization", "exposure")),
                     "research A target, authorization or task identity changed")
        for record in (old, row):
            receipt = record["protocol_reference_receipt"]
            h.io.require(h.inputs.semantic(record, record["final_answer"], receipt)["business_success"] is True
                         and record["verified_outcome"]["receipt_sha256"] == receipt["receipt_sha256"],
                         "each authored A target needs bound real original/control evidence")
        references.append({
            "record_id": row["record_id"], "task_id": row["task_id"],
            "source_id": row["source_id"], "lineage_id": row["lineage_id"],
            "input_sha256": hashlib.sha256(row["task"]["input"].encode()).hexdigest(),
            "target_sha256": hashlib.sha256(row["final_answer"].encode()).hexdigest(),
            "reference_receipt_sha256": row["protocol_reference_receipt"]["receipt_sha256"],
        })
    return h.io.sealed({
        "schema": "hepta.research-reference-admission.v1", "policy": ADMISSION,
        "parent_model_digest": data.digest(context["parent"]),
        "parent_operation_digest": data.digest(context["parent_operation"]),
        "baseline_readiness_digest": data.digest(context["readiness"]),
        "parent_successful_A_tasks": gate["successful_A_tasks"],
        "records_digest": data.digest(records), "references": references, **SCOPE})


def load_context(root, source, directory):
    h = helpers()
    directory = Path(directory)
    h.io.require(directory == h.io.WORKSPACE_ROOT / "probe-qwen-parent-03",
                 "research requires the complete actual parent03 operation")
    h.io.read(directory / "RESULT.json", PARENT03_RESULT_SHA)
    h.io.read(directory / "FREEZE.json", PARENT03_FREEZE_SHA)
    context = h.inputs.load_inputs(root, source, directory)
    h.io.require(h.io.digest(context["parent"]) == PARENT_MODEL_DIGEST,
                 "actual parent03 model identity changed")
    context["parent_operation"] = h.io.read(directory / "RESULT.json",
                                           context["readiness_inventory"]["RESULT.json"])
    context["parent_operation_sha256"] = context["readiness_inventory"]["RESULT.json"]
    context["research_admission"] = reference_admission(context["records"][:6], context, "trajectory")
    # Helper04 leaves these empty when A=0. This distinct protocol admits the
    # verified authored examples without changing the true baseline observations.
    context["retrieval_panels"], context["retrieval_bindings"] = h.inputs.retrieval_panels(
        context["records"][:6], context["panels"])
    return context


def make_plan(records, context, mode, operation_id):
    from cell_experiments import data, causal_training_contract_v3 as original
    h = helpers()
    h.io.require(isinstance(operation_id, str) and 1 <= len(operation_id.encode()) <= 256,
                 "bounded research operation identity required")
    original._settings(TRAINING, context["parent"])
    return {
        "schema": PLAN_SCHEMA, "profile": PROFILE, "operation_id": operation_id,
        "created_at_ns": time.time_ns(), "admission_policy": ADMISSION,
        "parent_model_digest": data.digest(context["parent"]),
        "records_digest": data.digest(records), "mode": mode,
        "training_source_ids": sorted({row["source_id"] for row in records}),
        "baseline_readiness_digest": data.digest(context["readiness"]),
        "reference_admission": reference_admission(records, context, mode),
        "source_inventory": sources(), "training": copy.deepcopy(TRAINING),
        "backend_versions": {**context["parent"]["backend_versions"], "peft": metadata.version("peft")},
        "schedule": "record=step%record_count; turn=(step//record_count)%turn_count",
        "loss": "original causal_train_v3.selected_token_loss; unchanged causal objective",
        **SCOPE}


def validate_plan(records, context, plan):
    from cell_experiments import data, causal_probe_v3 as probe, causal_training_contract_v3 as original
    io = helpers().io
    scope_guard(plan)
    io.require(plan.get("schema") == PLAN_SCHEMA and plan.get("profile") == PROFILE
                and plan.get("admission_policy") == ADMISSION
                and plan.get("records_digest") == data.digest(records)
                and plan.get("parent_model_digest") == data.digest(context["parent"])
                and plan.get("baseline_readiness_digest") == data.digest(context["readiness"])
                and plan.get("training_source_ids") == sorted({row["source_id"] for row in records})
                and plan.get("reference_admission") == reference_admission(records, context, plan.get("mode")),
                "research plan data, baseline or reference admission changed")
    io.require(plan.get("training") == TRAINING and plan.get("source_inventory") == sources()
                and plan.get("backend_versions") == {**probe._versions(), "peft": metadata.version("peft")},
                "research training budget, source or backend changed")
    original._settings(plan["training"], context["parent"])


def verify_model(manifest, root):
    """Research adapters are intentionally rejected by the native schema."""
    from cell_experiments import data, causal_probe_v3 as probe
    io = helpers().io
    scope_guard(manifest)
    io.require((manifest.get("schema"), manifest.get("family"), manifest.get("model_id"))
                == (MODEL_SCHEMA, FAMILY, probe.MODEL_ID), "unsupported research model identity")
    io.require(manifest.get("profile") == PROFILE and manifest.get("admission_policy") == ADMISSION
                and manifest.get("research_source_inventory") == sources(),
                "research model contract or source changed")
    parent = manifest["base_manifest"]
    io.require(probe.verify_model(parent, root) == manifest.get("parent_model_digest")
                and manifest.get("runtime") == parent["runtime"]
                and manifest.get("backend_versions") == parent["backend_versions"]
                and manifest.get("peft_version") == metadata.version("peft"),
                "research base, generation or backend differs")
    adapter = probe._base(root, manifest["adapter_directory"])
    files = probe._inventory(adapter)
    names = {row["path"] for row in files}
    io.require(files == manifest.get("adapter_files")
                and {"adapter_config.json", "adapter_model.safetensors"} <= names
                and names <= {"adapter_config.json", "adapter_model.safetensors", "README.md"},
                "complete immutable research adapter files required")
    config = probe._json(adapter / "adapter_config.json")
    expected = {"peft_type": "LORA", "task_type": "CAUSAL_LM", "r": 4, "lora_alpha": 8,
                "lora_dropout": 0.0, "bias": "none", "inference_mode": True}
    io.require(all(config.get(key) == value for key, value in expected.items())
                and set(config.get("target_modules", [])) == {"q_proj", "v_proj"},
                "research adapter differs from the frozen LoRA profile")
    return data.digest(manifest)


def recheck_reference(record, directory):
    """One actual reference call, with durable intent and partial-failure cost."""
    from cell_experiments import data
    h, directory = helpers(), Path(directory)
    before = h.io.usage()
    h.io.write_new(directory / "REFERENCE_REQUEST.json", {
        "record_id": record["record_id"], "record_digest": data.digest(record),
        "answer_sha256": hashlib.sha256(record["final_answer"].encode()).hexdigest(),
        "started_at_ns": time.time_ns(), "automatic_retry": False, **SCOPE})
    try:
        receipt = data.verify_answer(record, record["final_answer"])
        h.io.write_new(directory / "REFERENCE.json", receipt)
        h.io.require(h.inputs.semantic(record, record["final_answer"], receipt)["business_success"] is True,
                     "actual authored A reference recheck failed")
        h.io.write_new(directory / "REFERENCE_MEASUREMENT.json", h.io.sealed({
            "status": "COMPLETE", "cost": h.io.cost(before),
            "reference_sha256": h.io.file_hash(directory / "REFERENCE.json"), **SCOPE}))
        return receipt
    except BaseException as error:
        h.io.write_new(directory / "REFERENCE_FAILED.json", h.io.sealed({
            "status": "FAILED_PRESERVED", "error": repr(error), "cost": h.io.cost(before),
            "automatic_retry": False, "reference_calls": None, **SCOPE}))
        raise


def diagnostic_guard(path, expected_sha):
    io = helpers().io
    path = Path(path)
    io.workspace_guard(io.WORKSPACE_ROOT, path)
    io.require(isinstance(expected_sha, str) and re.fullmatch(r"[0-9a-f]{64}", expected_sha),
                "exact diagnostic file hash required")
    value = io.read(path, expected_sha)
    expected = {
        "schema": "hepta.research-sft-diagnostic-freeze.v1", "status": "FROZEN_PRE_FIT",
        "research_only": True, "new_C": False, "scientific_confirmation_qualified": False,
        "native_cell_adoption": False, "proof_of_useful_work_eligible": False,
        "circuit_qualified": False, "candidate_selected": None,
        "fixed_slots": ["final_answer", "trajectory", "controlled_correction"],
        "separate_arm": "shadow_correction", "rule_version": "research-diagnostic-v1",
        "rules": {"first_last_separate": True, "zero_baseline_retention": None,
                  "failed_slot_replacement": False, "missing_evidence": "unavailable",
                  "partial_cost": "unknown_totals_with_measured_subtotals",
                  "panel_cost_scope": "actual_panel_only_excludes_load_close",
                  "cost_scopes_additive": False, "union_not_routing": True,
                  "new_independent_samples": 0, "new_teachers": 0, "new_users": 0},
    }
    required_rules = expected.pop("rules")
    io.require(io.canonical({key: value.get(key) for key in expected}) == io.canonical(expected)
                and isinstance(value.get("rules"), dict)
                and io.canonical({key: value["rules"].get(key) for key in required_rules})
                == io.canonical(required_rules),
                "diagnostic rules must be fixed before any fit")
    source = value.get("diagnostic_source", {})
    io.require(source.get("filename") == "qwen_research_diagnostic_v1.py"
                and isinstance(source.get("sha256"), str)
                and re.fullmatch(r"[0-9a-f]{64}", source["sha256"]),
                "bound diagnostic source required")
    io.require(io.file_hash(path.parent / source["filename"]) == source["sha256"],
                "diagnostic source bytes changed")
    return value


def guard(freeze):
    h, io = helpers(), helpers().io
    scope_guard(freeze)
    io.require(freeze.get("schema") == "hepta.research-sft-freeze.v1"
                and freeze.get("profile") == PROFILE and freeze.get("admission_policy") == ADMISSION
                and freeze.get("status") == "REFERENCE_ADMITTED",
                "explicit separate research freeze required")
    io.require(freeze["runtime_root"] == str(io.RUNTIME_ROOT)
                and freeze["workspace_root"] == freeze["artifact_root"] == str(io.WORKSPACE_ROOT)
                and freeze["helper_directory"] == str(h.directory),
                "research workspace/runtime/helper binding changed")
    io.workspace_guard(io.WORKSPACE_ROOT, h.directory, Path(__file__).parent,
                       freeze["source"], freeze["readiness_directory"], freeze["output"], freeze["inputs_path"])
    io.require(Path(freeze["readiness_directory"]) == io.WORKSPACE_ROOT / "probe-qwen-parent-03",
                "complete parent03 must remain the research baseline")
    io.require(freeze["schedule"] == h.runner.schedule()
                and freeze["fitting_modes"] == io.FIT_MODES
                and freeze.get("fit_plans_must_precede_all_fits") is True
                and freeze.get("baseline_result_sha256") == PARENT03_RESULT_SHA
                and freeze.get("baseline_freeze_sha256") == PARENT03_FREEZE_SHA
                and freeze.get("parent_digest") == PARENT_MODEL_DIGEST,
                "research schedule or complete parent03 binding changed")
    io.require(freeze["budget"] == io.BUDGET and freeze["helper_inventory"] == HELPERS04
                and h.io.helper_inventory() == HELPERS04
                and freeze["research_inventory"] == research_inventory(),
                "research budget or executable source changed")
    source_manifest = io.read(io.WORKSPACE_ROOT / "operations/QWEN_SOURCE_02.json", io.SOURCE_MANIFEST_SHA)
    io.require(freeze["source_inventory"] == source_manifest["files"],
                "research source must remain exact source119")
    diagnostic_guard(freeze["diagnostic_freeze"]["path"], freeze["diagnostic_freeze"]["sha256"])
    io.verify_inventory(freeze["source"], freeze["source_inventory"], exact=True)
    io.verify_inventory(freeze["readiness_directory"], freeze["readiness_inventory"])
    io.runtime_guard(io.RUNTIME_ROOT, freeze["runtime"])
