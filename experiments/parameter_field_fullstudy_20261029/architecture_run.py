"""Frozen stage C: train all parameters, fit paired heads, seal 32 endpoints.

This runner never opens a qualification/final endpoint role. The separate
endpoint barrier must bind its completed seal before any new outcome scoring.
"""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np
import torch

from experiments.multimodal_output_portfolio.field_bridge_v3_20261027.assets import load_assets
from experiments.multimodal_output_portfolio.v6.neural import parameter_hash
from .architecture import REFERENCE_COMMIT, matched_pair
from .architecture_bank import build_instance, fit_architecture, read_row, replay_registered_row
from .architecture_features import measure
from .architecture_kernel import ArchitecturePlan, Context, Work
from .architecture_state import capture, digest
from .architecture_store import EvidenceStore
from .architecture_training import load_generator_checkpoint, warmup
from .heads import choose
from .run import verify_freeze
from .sources import load_training_roles


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def runtime_identity():
    return {"python": platform.python_version(), "platform": platform.platform(),
            "torch": str(torch.__version__), "numpy": str(np.__version__),
            "device": "cpu", "dtype": "float32", "threads": torch.get_num_threads(),
            "interop_threads": torch.get_num_interop_threads(),
            "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
            "mkldnn_enabled": torch.backends.mkldnn.enabled}


def evaluate_path(context, model, optimizer, warm_record, head, policy, store, binding):
    plan = context.plan
    context.work.phase = "evaluation"
    context.restore(model, optimizer, warm_record["state"])
    before_work = context.work.snapshot()
    trace, states = [], []
    for decision, clock in enumerate(range(0, plan.steps, plan.macro_steps)):
        store.check()
        before = digest(context.snapshot(model, optimizer))
        if policy == "field":
            feature, unused, feature_receipt = measure(context, model, optimizer, clock, plan.evaluation_schedule)
            action, choice = choose(head, feature, baseline=plan.baseline)
            context.work.add("head_decisions")
            feature = feature.tolist()
        else:
            action, feature, feature_receipt = plan.baseline, None, None
            choice = {"chosen_action": action, "override": False, "certificate": False}
        receipt = context.block(model, optimizer, clock, action, plan.evaluation_schedule)
        state = context.snapshot(model, optimizer)
        states.append(digest(state))
        trace.append({"decision": decision, "before": before, "field": feature,
                      "feature_receipt": feature_receipt, "choice": choice, "transaction": receipt})
    terminal = capture(model, optimizer)
    name = f"endpoints/{model.config['mode']}-seed-{context.seed}-{policy}"
    metadata = {
        "schema": "hepta.fullstudy.C.endpoint.1", "seed": context.seed,
        "mode": model.config["mode"], "policy": policy, "config": model.config,
        "plan_sha256": digest(plan.to_dict()), "binding": binding,
        "warmstart_state_sha256": warm_record["state_sha256"],
        "context_sha256": context.identity, "clock": plan.steps,
        "parameter_sha256": parameter_hash(model), "schedule": plan.evaluation_schedule,
        "work_before": before_work, "work_after": context.work.snapshot(),
    }
    checkpoint = store.checkpoint(name + ".pt.gz", terminal, metadata)
    result = {"seed": context.seed, "mode": model.config["mode"], "policy": policy,
              "checkpoint": checkpoint, "metadata": metadata, "state_sha256": digest(terminal),
              "decision_state_sha256": states, "trace": trace,
              "overrides": sum(item["choice"]["override"] for item in trace),
              "accepted_overrides": sum(item["choice"]["override"] and item["transaction"]["accepted"]
                                        for item in trace)}
    store.json_gzip(name + ".trace.json.gz", result)
    return result


def execute(corpus, observer, reference_root, plan, store, binding):
    """Inputs are already verified by main; never substitute pre-existing random readouts."""
    warmstarts, heads, banks, paths, audits = [], {}, {}, [], []
    active_context = active_model = active_optimizer = None
    try:
        for role, seeds in (("development", plan.development_seeds), ("evaluation", plan.evaluation_seeds)):
            for seed in seeds:
                store.check()
                pair = matched_pair(reference_root=reference_root, seed=seed, hidden=plan.hidden,
                                    noise_scale=plan.noise_scale)
                paired = []
                for mode in ("ordinary", "dual"):
                    result = warmup(pair[mode], corpus, plan, seed, store, binding, role)
                    warmstarts.append(result)
                    paired.append(result)
                    print(json.dumps({"stage": "C_warmup", "seed": seed, "mode": mode,
                                      "role": role, "complete": True}), flush=True)
                if (paired[0]["initial_parameter_sha256"] != paired[1]["initial_parameter_sha256"]
                        or paired[0]["metadata"]["paired_tape_sha256"] != paired[1]["metadata"]["paired_tape_sha256"]):
                    raise AssertionError("Architecture pair initialization or warm-up tapes differ")
        store.json_gzip("WARMSTARTS.json.gz", {"complete": True, "warmstarts": warmstarts})
        for mode in ("ordinary", "dual"):
            rows = []
            for seed in plan.development_seeds:
                entry = next(item for item in warmstarts if item["seed"] == seed and item["mode"] == mode)
                model, optimizer, record = load_generator_checkpoint(store.root / entry["checkpoint"]["path"], reference_root, plan)
                store.work.phase = "bank_setup"
                context = Context(model, corpus, observer, seed, plan, store.work, store.check)
                active_context, active_model, active_optimizer = context, model, optimizer
                destination = f"bank/{mode}-seed-{seed}"
                rows.extend(build_instance(context, model, optimizer, record["state"], store, destination))
                print(json.dumps({"stage": "C_bank", "seed": seed, "mode": mode, "complete": True}), flush=True)
            banks[mode] = rows
        # Reload every audit model, optimizer and teacher from a persisted warmstart.
        for mode in ("ordinary", "dual"):
            for seed in plan.development_seeds:
                entry = next(item for item in warmstarts if item["seed"] == seed and item["mode"] == mode)
                model, optimizer, record = load_generator_checkpoint(store.root / entry["checkpoint"]["path"], reference_root, plan)
                store.work.phase = "replay_audit"
                context = Context(model, corpus, observer, seed, plan, store.work, store.check)
                active_context, active_model, active_optimizer = context, model, optimizer
                target = next(row for row in banks[mode] if row["seed"] == seed and row["schedule"] == 7000
                              and row["prefix"] == "balanced" and row["decision"] == 2)
                row_path = store.root / target["artifact"]["path"]
                if file_hash(row_path) != target["artifact"]["sha256"]:
                    raise ValueError("Persisted replay target changed")
                audits.append(replay_registered_row(context, model, optimizer, record["state"],
                                                     read_row(row_path), store, f"audit/{mode}-seed-{seed}.json.gz"))
        for mode in ("ordinary", "dual"):
            store.work.phase = "head_fitting"
            heads[mode], unused = fit_architecture(banks[mode], plan, store, "heads/" + mode)
            store.work.add("head_fits")
        for seed in plan.evaluation_seeds:
            for mode in ("ordinary", "dual"):
                entry = next(item for item in warmstarts if item["seed"] == seed and item["mode"] == mode)
                model, optimizer, record = load_generator_checkpoint(store.root / entry["checkpoint"]["path"], reference_root, plan)
                store.work.phase = "evaluation_setup"
                context = Context(model, corpus, observer, seed, plan, store.work, store.check)
                active_context, active_model, active_optimizer = context, model, optimizer
                baseline = None
                for policy in ("baseline", "field"):
                    result = evaluate_path(context, model, optimizer, record, heads[mode], policy, store, binding)
                    if policy == "baseline":
                        baseline = result
                    first = next((i for i, (left, right) in enumerate(zip(result["decision_state_sha256"],
                                  baseline["decision_state_sha256"], strict=True)) if left != right), None)
                    result["first_legal_divergence_decision"] = first
                    result["first_legal_divergence_clock"] = None if first is None else (first + 1) * plan.macro_steps
                    paths.append(result)
                    print(json.dumps({"stage": "C_endpoint_sealed", "seed": seed, "mode": mode,
                                      "policy": policy, "overrides": result["overrides"]}), flush=True)
        expected_counts = {"warmup.scheduled_gradient_microsteps": 8000,
                           "bank.scheduled_gradient_microsteps": 46080,
                           "evaluation.scheduled_gradient_microsteps": 3072,
                           "replay_audit.scheduled_gradient_microsteps": 384}
        if any(store.work.values.get(key) != value for key, value in expected_counts.items()):
            raise AssertionError("C physical gradient counts differ from the frozen design")
        if len(warmstarts) != 20 or len(paths) != 32 or len(audits) != 4:
            raise AssertionError("C complete inventory differs from the frozen design")
        store.check()
        inventory = [{key: path[key] for key in ("seed", "mode", "policy", "checkpoint", "state_sha256",
                     "overrides", "accepted_overrides", "first_legal_divergence_decision",
                     "first_legal_divergence_clock")} for path in paths]
        result = {"schema": "hepta.fullstudy.C.complete-seal.1", "complete": True,
                  "training_complete": True, "new_endpoint_roles_opened": [], "plan": plan.to_dict(),
                  "binding": binding, "warmstarts": warmstarts, "paths": inventory,
                  "audit_count": len(audits), "work": store.work.snapshot(),
                  "process_cpu_seconds_total": time.process_time(),
                  "literal_tensor_checkpoints": 52, "branch_tensor_archive": False,
                  "physical_gradient_microsteps": 57536, "scientific_gradient_microsteps": 57152,
                  "replay_gradient_microsteps": 384, "artifacts": list(store.artifacts),
                  "raw_bytes_before_seal": store.sizes()[0], "certificate": False}
        store.json("COMPLETE.json", result)
        return result
    except BaseException as error:
        failure = {"complete": False, "error_type": type(error).__name__, "message": str(error),
                   "work": store.work.snapshot(), "completed_warmstarts": len(warmstarts),
                   "completed_endpoints": len(paths), "partial_evidence_preserved": True,
                   "new_endpoint_roles_opened": []}
        try:
            if active_model is not None:
                partial = active_context.last_failure or {"state": capture(active_model, active_optimizer),
                                                          "metadata": {"failure_stage": store.work.phase}}
                failure["failed_state"] = store.checkpoint("FAILED_STATE.pt.gz", partial["state"],
                                                           partial["metadata"], failure_record=True)
            store.json("FAILED.json", failure, failure_record=True)
        except BaseException as preservation_error:
            failure["additional_failure_preservation_blocked"] = str(preservation_error)
        print(json.dumps(failure, sort_keys=True), flush=True)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--reference-root", required=True)
    parser.add_argument("--freeze", required=True)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    freeze = verify_freeze(args.freeze, "C")
    protocol = json.loads(Path(args.protocol).read_text())
    if not args.execute or not protocol.get("execution_ready") or file_hash(args.protocol) != freeze["protocol_sha256"]:
        raise ValueError("C requires explicit execution and a source-bound frozen execution-ready protocol")
    mapping = protocol["stage_C"]["execution_plan"]
    if set(mapping) != set(ArchitecturePlan.__dataclass_fields__):
        raise ValueError("Every C execution choice must be explicit in the frozen protocol")
    plan = ArchitecturePlan.from_mapping(mapping)
    if plan != ArchitecturePlan():
        raise ValueError("C execution plan differs from the registered fixed design")
    torch.set_num_threads(plan.threads)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    work = Work()
    store = EvidenceStore(Path(args.root) / "stage_C", work, raw_root=args.root)
    store.check()
    unused, observers, asset_identity = load_assets(args.assets, [], ["reward"])
    corpus = load_training_roles(args.assets, "C", [plan.gradient_role, plan.rehearsal_role,
                                                   plan.probe_role, plan.guard_role])
    binding = {"registered_commit": freeze["registered_commit"], "source_freeze_sha256": file_hash(args.freeze),
               "protocol_sha256": file_hash(args.protocol), "runtime": runtime_identity(),
               "assets": asset_identity, "training_source_manifest": corpus.manifest,
               "hcsn_reference_commit": REFERENCE_COMMIT}
    store.json("INPUT_BINDING.json", {"binding": binding, "plan": plan.to_dict()})
    execute(corpus, observers["reward"], args.reference_root, plan, store, binding)


if __name__ == "__main__":
    main()
