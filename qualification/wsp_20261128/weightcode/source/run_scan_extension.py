"""Fixed, independently executed SCAN edit / BP matrix on the PUBLIC published split.

This does not discover the published program, provide a fresh holdout, or measure
HeptaTrader. All numerical model and optimizer implementations come from the
pinned upstream WeightCode checkout. This orchestration adds component ablations,
norm-matched random controls, paired accounting, and byte-exact rollback checks.
"""
from __future__ import annotations

import os
for _key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_key] = "4"

import dataclasses
import hashlib
import importlib.util
import json
import platform
import resource
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE / "WeightCode"
sys.path.insert(0, str(REPO))

import numpy as np
import torch
from weightcode.baselines.instance_io import load_instance
from weightcode.baselines.fit.runner import load_scan_evidence
from weightcode.baselines.fit.scanrefs import scan_generator, configs
from weightcode.common.identity import count_changed, params_sha256, save_params
from weightcode.data import scan as S
from weightcode.evalkit.metrics import rows_right
from weightcode.evalkit.patch_check import predict, validate_child
from weightcode.evalkit.scanskill import construction_masks, part_summary
from weightcode.examples.replay import session_limits
from weightcode.models.transformer import SeqTransformer
from weightcode.patch import apply_patch

torch.set_num_threads(4)
torch.set_num_interop_threads(1)
torch.use_deterministic_algorithms(True)
PROTOCOL_PATH = HERE / "scan_extension_protocol.json"
PROTOCOL = json.loads(PROTOCOL_PATH.read_text())
OUT = HERE / "scan_extension"
OUT.mkdir(exist_ok=True)
for _name in ("predictions", "selected", "arms"):
    (OUT / _name).mkdir(exist_ok=True)

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write_json(path: Path, obj) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)

def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()

START = time.monotonic()
STAGE = "setup"
COUNTERS = defaultdict(lambda: defaultdict(int))

def log(message: str) -> None:
    print(f"[{stamp()}] {message}", flush=True)

def snapshot_counters() -> dict:
    return {stage: dict(values) for stage, values in COUNTERS.items()}

def torch_forward_hook(module, args, output):
    if isinstance(module, SeqTransformer):
        n = int(args[0].shape[0])
        COUNTERS[STAGE]["torch_forward_calls"] += 1
        COUNTERS[STAGE]["torch_forward_rows"] += n
        if torch.is_grad_enabled() and output.requires_grad:
            COUNTERS[STAGE]["torch_grad_forward_calls"] += 1
            COUNTERS[STAGE]["torch_grad_forward_rows"] += n

HOOK = torch.nn.modules.module.register_module_forward_hook(torch_forward_hook)
COMMIT = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
assert COMMIT == PROTOCOL["source_commit"]
MANIFEST = {
    "started_at": stamp(), "protocol": PROTOCOL,
    "protocol_file_sha256": digest(PROTOCOL_PATH), "runner_sha256": digest(Path(__file__)),
    "source_commit": COMMIT, "python": sys.version, "numpy": np.__version__, "torch": torch.__version__,
    "platform": platform.platform(), "torch_threads": torch.get_num_threads(),
    "environment_threads": {k: os.environ[k] for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")},
    "interpretation": "Published heldout reexecution; no claim of fresh independent test or Hepta endpoint improvement.",
    "cost_definition": "Rows are sample-forward counts, not FLOPs. Gradient forward rows are also counted in all torch forward rows; backward ~2x forward is an approximate separate conversion. Exact-hash prediction caches reduce actual executed checks; logical candidate check counts remain eight.",
}
if (OUT / "manifest.json").exists():
    raise RuntimeError("Refuse to overwrite an existing matrix. Audit any incomplete run before resuming.")
write_json(OUT / "manifest.json", MANIFEST)
log("Frozen protocol and implementation hashes recorded; starting fixed matrix")

DOWNLOADS = REPO / "reproduction_scan" / "downloads"
instance = load_instance(DOWNLOADS / "hf" / "weights" / "instances" / PROTOCOL["instance"])
BASE = instance.params
BASE_SHA = instance.params_sha256
assert BASE_SHA == PROTOCOL["base_params_sha256"]
raw_forward = instance.forward

def counted_forward(params, x):
    COUNTERS[STAGE]["numpy_forward_calls"] += 1
    COUNTERS[STAGE]["numpy_forward_rows"] += int(len(x))
    return raw_forward(params, x)

instance = dataclasses.replace(instance, forward=counted_forward)
evidence = load_scan_evidence(instance)
assert len(evidence.x) == 65
built = S.build_condition_splits(DOWNLOADS / "scan", "addprim_jump")
S.check_disjoint(built)
for split, key in (("V_check", "vcheck_content_sha256"), ("old_check", "oldcheck_content_sha256"),
                   ("V_select", "vselect_content_sha256"), ("old_select", "oldselect_content_sha256")):
    assert params_sha256(built.private[split]) == instance.private[key], split
assert params_sha256(built.sealed) == PROTOCOL["data"]["final_hash"]
new_mask = built.sealed["part"] == S.PART_NEW
old_mask = built.sealed["part"] == S.PART_OLD
assert (int(new_mask.sum()), int(old_mask.sum())) == (2568, 1000)
SPLITS = {
    "check_new": built.private["V_check"], "check_old": built.private["old_check"],
    "final_new": {k: v[new_mask] for k, v in built.sealed.items()},
    "final_old": {k: v[old_mask] for k, v in built.sealed.items()},
}
SESSION = DOWNLOADS / "hf" / "records" / "sessions" / "s9be29c2c302e4daa"
PROGRAM = SESSION / "final" / "centroid_meanrow_floor.py"
assert digest(PROGRAM) == PROTOCOL["program_sha256"]
REPLAY = REPO / "reproduction_scan" / "runs" / "20261128T103750.741015Z"
patch_dir = REPLAY / "replay" / "patch"
patch = json.loads((patch_dir / "derived_patch.json").read_text())
edit_start = time.monotonic()
published = apply_patch(BASE, patch, patch_dir, session_limits(SESSION), BASE_SHA).child
patch_apply_wall_s = time.monotonic() - edit_start
assert params_sha256(published) == PROTOCOL["published_child_sha256"]
assert count_changed(BASE, published) == 257
save_params(OUT / "selected" / "full_published_edit.npz", published)

# Audit known unlabeled input probes without running the published program again.
spec = importlib.util.spec_from_file_location("published_scan_program", PROGRAM)
published_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(published_module)
grammar = published_module._commands()
jump_probes = [c for c in grammar if "jump" in c.split() and c != "jump"][::8]
old_probes = [c for c in grammar if "jump" not in c.split()]
prim = ["walk", "look", "run"]
reference_probes = []
for command in jump_probes:
    words = command.split()
    substitute = next(p for p in prim if p not in words)
    reference_probes.append(" ".join(substitute if w == "jump" else w for w in words))
all_probe_commands = set(jump_probes + old_probes + reference_probes + S.decode(evidence.x[1:]))
program_cost = json.loads((REPLAY / "replay" / "run" / "out" / "result.json").read_text())
published_run = json.loads((SESSION / "run.json").read_text())
program_audit = {
    "published_program_update_wall_seconds": program_cost["update_s"],
    "our_official_reexecute_plus_final_evaluation_shell_wall_seconds": 144.679,
    "patch_reapply_wall_seconds": patch_apply_wall_s,
    "program_forward_rows_from_static_audit": 64 + 2 * len(jump_probes) + len(old_probes),
    "jump_probe_rows": len(jump_probes), "old_grammar_probe_rows": len(old_probes),
    "unlabelled_probe_overlap_with_final": {
        name: sum(c in all_probe_commands for c in S.decode(SPLITS[name]["x"]))
        for name in ("final_new", "final_old")
    },
    "overlap_interpretation": "Final labels were not passed to the published update. The fixed known grammar lets it probe some final new inputs and all old inputs unlabeled. This is not a claim of completely unobserved input holdout.",
    "published_run_top_level_keys": list(published_run),
}
for key in ("timing", "cost", "usage", "duration_s", "wall_s", "created_at", "finished_at", "editor", "model"):
    if key in published_run:
        program_audit["author_record_" + key] = published_run[key]
write_json(OUT / "program_audit.json", program_audit)

PRED_CACHE = {}
CACHE_ACCOUNTING = {"hits": 0, "misses": 0}

def preds(params, split: str):
    sha = params_sha256(params)
    key = (sha, split)
    if key in PRED_CACHE:
        CACHE_ACCOUNTING["hits"] += 1
        return PRED_CACHE[key], True
    CACHE_ACCOUNTING["misses"] += 1
    answer = predict(counted_forward, params, SPLITS[split]["x"], batch_size=1024)
    PRED_CACHE[key] = answer
    np.savez_compressed(OUT / "predictions" / f"{sha}_{split}.npz", pred=answer)
    return answer, False

def bootstrap_delta(base_right, child_right):
    # Multinomial counts are exactly the bootstrap distribution of a mean of
    # paired differences in {-1,0,1}; no independence approximation is needed.
    differences = child_right.astype(np.int8) - base_right.astype(np.int8)
    counts = np.bincount(differences + 1, minlength=3)
    draws = np.random.default_rng(20261128).multinomial(len(differences), counts / len(differences), size=2000)
    means = 100.0 * (draws[:, 2] - draws[:, 0]) / len(differences)
    return [float(v) for v in np.percentile(means, [2.5, 97.5])]

def assess(params, split_prefix: str):
    results = {}
    for part in ("new", "old"):
        split = f"{split_prefix}_{part}"
        before, _ = preds(BASE, split)
        after, reused = preds(params, split)
        y = SPLITS[split]["y"]
        results[part] = part_summary(y, before, after)
        results[part]["paired_delta_95pct_bootstrap_pp"] = bootstrap_delta(rows_right(y, before), rows_right(y, after))
        results[part]["prediction_cache_hit"] = reused
        if split_prefix == "final" and part == "new":
            results["new_by_construction"] = {
                name: part_summary(y[mask], before[mask], after[mask]) if mask.any() else {"n": 0}
                for name, mask in construction_masks(SPLITS[split]["x"]).items()
            }
    results["new_score"] = results["new"]["fixed"] - results["new"]["broken"]
    results["old_score"] = results["old"]["fixed"] - results["old"]["broken"]
    results["joint_score"] = results["new_score"] + results["old_score"]
    results["joint_points"] = 100.0 * (results["new"]["delta"] + results["old"]["delta"])
    return results

def rollback_audit(child):
    # Restore the stored bytes; subtraction of a rounded float32 delta is not a rollback.
    restored = {k: np.array(v, copy=True) for k, v in child.items()}
    for key, value in BASE.items():
        restored[key][...] = value
    sha = params_sha256(restored)
    assert sha == BASE_SHA
    assert params_sha256(BASE) == BASE_SHA
    return {"restored_sha256": sha, "exact": True}

def save_arm(name, params, kind, extra):
    global STAGE
    STAGE = name + "/final"
    validated = validate_child(BASE, params)
    before = time.monotonic()
    result = assess(validated, "final")
    elapsed = time.monotonic() - before
    record = {
        "name": name, "kind": kind, "params_sha256": params_sha256(validated),
        "n_changed": count_changed(BASE, validated), "final": result,
        "final_wall_seconds": elapsed, "rollback": rollback_audit(validated), **extra,
    }
    write_json(OUT / "arms" / f"{name}.json", record)
    log(f"{name}: final new {100*result['new']['em_child']:.3f}%, old {100*result['old']['em_child']:.3f}%, changed {record['n_changed']}")
    return record

RECORDS = []
for arm in PROTOCOL["ablation_arms"]:
    child = {k: np.array(published[k] if k in arm["groups"] else v, copy=True) for k, v in BASE.items()}
    RECORDS.append(save_arm(arm["name"], child, "component_ablation", {"groups": arm["groups"]}))

for seed in PROTOCOL["random_controls"]["seeds"]:
    rng = np.random.default_rng(seed)
    child = {k: np.array(v, copy=True) for k, v in BASE.items()}
    norms = {}
    for key in sorted(BASE):
        delta = published[key].astype(np.float64) - BASE[key].astype(np.float64)
        mask = delta != 0
        if mask.any():
            drawn = rng.normal(size=int(mask.sum()))
            drawn *= np.linalg.norm(delta[mask]) / np.linalg.norm(drawn)
            child[key][mask] = (BASE[key][mask].astype(np.float64) + drawn).astype(np.float32)
            actual = child[key].astype(np.float64) - BASE[key].astype(np.float64)
            norms[key] = {"published_delta_l2": float(np.linalg.norm(delta)), "random_actual_l2": float(np.linalg.norm(actual))}
            assert np.all(child[key][~mask] == BASE[key][~mask])
    RECORDS.append(save_arm(f"random_support_norm_seed{seed}", child, "random_matched_edit", {"seed": seed, "norms": norms}))

write_json(OUT / "partial_summary.json", {"completed_arms": RECORDS, "counters": snapshot_counters(), "cache": CACHE_ACCOUNTING})

for method in PROTOCOL["gradient_baselines"]["methods"]:
    for seed in PROTOCOL["gradient_baselines"]["seeds"]:
        name = f"{method}_seed{seed}"
        STAGE = name + "/fit"
        log(f"{name}: fitting fixed upstream eight candidates on 65 rows")
        fit_start = time.monotonic()
        candidates, fit_info = scan_generator(instance, method, seed, device="cpu")(evidence)
        fit_wall = time.monotonic() - fit_start
        assert len(candidates) == PROTOCOL["gradient_baselines"]["external_checks_per_method_per_seed"]
        expected_lrs = PROTOCOL["gradient_baselines"]["lora_learning_rates" if method == "lora_r4" else "full_and_head_learning_rates"]
        expected_configs = [{"lr": lr, "steps": steps} for lr in expected_lrs for steps in PROTOCOL["gradient_baselines"]["step_checkpoints"]]
        assert [c.config for c in candidates] == expected_configs == configs(method)
        selected = None
        best_score = 0
        checks = []
        check_start = time.monotonic()
        for candidate in candidates:
            STAGE = name + "/check"
            validate_child(BASE, candidate.child)
            check = assess(candidate.child, "check")
            qualifies = check["old_score"] >= -5 and check["joint_score"] > best_score
            checks.append({"slot": candidate.slot, "config": candidate.config, "notes": candidate.notes,
                           "params_sha256": params_sha256(candidate.child), "n_changed": count_changed(BASE, candidate.child),
                           "check": check, "selected_at_this_point": qualifies})
            if qualifies:
                selected = candidate
                best_score = check["joint_score"]
            log(f"{name} check {candidate.slot}: new score {check['new_score']}, old score {check['old_score']}, eligible {check['old_score'] >= -5}")
        check_wall = time.monotonic() - check_start
        selected_params = BASE if selected is None else selected.child
        save_params(OUT / "selected" / f"{name}.npz", selected_params)
        selection = {"slot": None if selected is None else selected.slot,
                     "config": None if selected is None else selected.config, "check_score": best_score,
                     "selection_inputs": "Only V_check and old_check; no final split results used"}
        # Record the selected hash and check decision BEFORE touching its final predictions.
        write_json(OUT / "arms" / f"{name}_selection.json", {"selection": selection,
                   "selected_sha256": params_sha256(selected_params), "checks": checks,
                   "fit_info": fit_info, "fit_wall_seconds": fit_wall, "check_wall_seconds": check_wall})
        record = save_arm(name, selected_params, "gradient_baseline", {
            "method": method, "seed": seed, "selection": selection, "logical_external_checks": len(checks),
            "fit_info": fit_info, "fit_wall_seconds": fit_wall, "check_wall_seconds": check_wall,
            "training_steps_total": 2 * 300, "fit_rows": len(evidence.x),
            "selection_record": str(OUT / "arms" / f"{name}_selection.json"),
        })
        RECORDS.append(record)
        write_json(OUT / "partial_summary.json", {"completed_arms": RECORDS, "counters": snapshot_counters(), "cache": CACHE_ACCOUNTING})
        del candidates

HOOK.remove()
SUMMARY = {
    "schema": "hepta.wsp.scan_external_replication.v1", "started_at": MANIFEST["started_at"], "finished_at": stamp(),
    "protocol_sha256": MANIFEST["protocol_file_sha256"], "runner_sha256": MANIFEST["runner_sha256"],
    "source_commit": COMMIT, "base_params_sha256": BASE_SHA, "published_child_sha256": params_sha256(published),
    "total_wall_seconds": time.monotonic() - START,
    "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    "records": RECORDS, "counters": snapshot_counters(), "cache_accounting": CACHE_ACCOUNTING,
    "program_audit": program_audit, "scope": PROTOCOL["data"]["scope"],
    "information_asymmetry": PROTOCOL["data"]["information_asymmetry"],
    "all_rollbacks_exact": all(r["rollback"]["exact"] for r in RECORDS),
}
write_json(OUT / "summary.json", SUMMARY)
log(f"Completed {len(RECORDS)} fixed arms in {SUMMARY['total_wall_seconds']:.1f}s; all rollbacks byte-exact")
