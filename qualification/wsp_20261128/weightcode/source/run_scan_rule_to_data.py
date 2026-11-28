"""Execute two author-fixed grammar-to-data references with bounded CPU memory.

See scan_rule_to_data_protocol.json. Microbatch accumulation changes floating point
reduction order only; it is not minibatch SGD and uses the upstream architecture.
"""
from __future__ import annotations
import os
for _key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_key] = "4"
import hashlib
import importlib.util
import json
import resource
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE / "WeightCode"
sys.path.insert(0, str(REPO))
PROTOCOL_PATH = HERE / "scan_rule_to_data_protocol.json"
PROTOCOL = json.loads(PROTOCOL_PATH.read_text())
OUT = HERE / "scan_rule_to_data"
OUT.mkdir(exist_ok=False)

def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def save(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    tmp.replace(path)

def log(message):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {message}", flush=True)

save(OUT / "protocol_seal.json", {"protocol": PROTOCOL, "protocol_sha256": sha_file(PROTOCOL_PATH),
     "script_sha256": sha_file(__file__), "sealed_unix": time.time(), "results_observed": False})
log("Protocol sealed; waiting for the prior four-thread matrix to finish")
wait_start = time.monotonic()
while not (HERE / "scan_extension" / "summary.json").is_file():
    if time.monotonic() - wait_start > 7200:
        save(OUT / "blocked.json", {"reason": "Prior CPU matrix did not finish within two hours; did not oversubscribe CPU"})
        raise TimeoutError("previous matrix incomplete")
    time.sleep(5)

import numpy as np
import torch
import torch.nn.functional as F
from weightcode.baselines.instance_io import load_instance
from weightcode.baselines.fit.runner import load_scan_evidence
from weightcode.baselines.fit import scanrefs as R
from weightcode.baselines.fit import seqgrad as SG
from weightcode.common.identity import params_sha256, save_params, load_params, count_changed
from weightcode.data import scan as S
from weightcode.evalkit.patch_check import predict
from weightcode.evalkit.scanskill import part_summary
from weightcode.models import transformer as T
torch.set_num_threads(4)
torch.set_num_interop_threads(1)
torch.use_deterministic_algorithms(True)
START = time.monotonic()
CPU_START = time.process_time()
COUNTERS = {"gradient_steps": 0, "gradient_rows": 0, "gradient_microbatches": 0,
            "numpy_forward_rows": 0, "dense_parity_gradient_rows": 0, "torch_parity_forward_rows": 0}
download = REPO / "reproduction_scan" / "downloads"
inst = load_instance(download / "hf" / "weights" / "instances" / PROTOCOL["instance"])
BASE = inst.params
assert inst.params_sha256 == PROTOCOL["base_sha256"]
evidence = load_scan_evidence(inst)
COUNTERS["numpy_forward_rows"] += len(evidence.x)
generated = R.rulegen_fit_set("addprim_jump", "mixed")
assert generated["record"]["commands_sha256"] == PROTOCOL["data"]["grammar_fit_commands_sha256"]
official_check = R.check_rows_against_official(download / "scan" / S.ALL_FILE, generated["commands"], generated["y"])
assert official_check["mismatches"] == 0
x_np = np.concatenate((generated["x"], evidence.x))
y_np = np.concatenate((generated["y"], evidence.y))
assert len(x_np) == 4065
x_t = torch.from_numpy(np.ascontiguousarray(x_np, dtype=np.int64))
y_t = torch.from_numpy(np.ascontiguousarray(y_np, dtype=np.int64))
valid_tokens = int((y_t != S.IGNORE).sum())
built = S.build_condition_splits(download / "scan", "addprim_jump")
assert params_sha256(built.sealed) == PROTOCOL["data"]["final_sha256"]
S.check_disjoint(built)
parts = {
    "check_new": built.private["V_check"], "check_old": built.private["old_check"],
    "final_new": {k: v[built.sealed["part"] == S.PART_NEW] for k, v in built.sealed.items()},
    "final_old": {k: v[built.sealed["part"] == S.PART_OLD] for k, v in built.sealed.items()},
}
program_path = download / "hf" / "records" / "sessions" / "s9be29c2c302e4daa" / "final" / "centroid_meanrow_floor.py"
sp = importlib.util.spec_from_file_location("published_program_for_probe_audit", program_path)
module = importlib.util.module_from_spec(sp)
sp.loader.exec_module(module)
commands = module._commands()
jump_inputs = [c for c in commands if "jump" in c.split() and c != "jump"][::8]
old_inputs = [c for c in commands if "jump" not in c.split()]
reference_inputs = []
for c in jump_inputs:
    words = c.split()
    p = next(p for p in ("walk", "look", "run") if p not in words)
    reference_inputs.append(" ".join(p if w == "jump" else w for w in words))
program_inputs = set(jump_inputs + old_inputs + reference_inputs + S.decode(evidence.x[1:]))
fit_inputs = set(S.decode(x_np))
final_new_commands = S.decode(parts["final_new"]["x"])
COMMON_UNPROBED = np.array([c not in program_inputs and c not in fit_inputs for c in final_new_commands])
UNFITTED = {name: np.array([c not in fit_inputs for c in S.decode(data["x"])]) for name, data in parts.items()}
save(OUT / "data_audit_before_fit.json", {"grammar_record": generated["record"], "official_label_check": official_check,
     "fit_rows": len(x_np), "valid_tokens": valid_tokens, "fit_arrays_sha256": params_sha256({"x":x_np,"y":y_np}),
     "overlap": {name: {"total": len(data["x"]), "in_fit": int((~UNFITTED[name]).sum())} for name, data in parts.items()},
     "final_new_neither_fitted_nor_WSP_probed": int(COMMON_UNPROBED.sum()),
     "subset_mask_sha256": hashlib.sha256(COMMON_UNPROBED.tobytes()).hexdigest()})

def deadline():
    if time.monotonic() - START > 10800:
        raise TimeoutError("predeclared three-hour total wall cap")

def summed_loss(model, x, y, denom):
    logits = model(x)
    return F.cross_entropy(logits.reshape(-1, logits.shape[-1]), y.reshape(-1), ignore_index=S.IGNORE, reduction="sum") / denom

def accumulated_grad(model, x, y, microbatch, category):
    model.zero_grad(set_to_none=True)
    denominator = int((y != S.IGNORE).sum())
    loss_sum = 0.
    for start in range(0, len(x), microbatch):
        deadline()
        loss = summed_loss(model, x[start:start+microbatch], y[start:start+microbatch], denominator)
        loss.backward()
        loss_sum += float(loss.detach())
        COUNTERS["gradient_rows"] += min(microbatch, len(x)-start)
        COUNTERS["gradient_microbatches"] += 1
    return loss_sum

# Required deployment and numerical-accumulation parity BEFORE any reference fit.
probe_model = SG.rebuild(BASE)
parity_max, parity_bound = SG.seq_parity(probe_model, BASE, inst.forward, evidence.x)
COUNTERS["numpy_forward_rows"] += len(evidence.x)
COUNTERS["torch_parity_forward_rows"] += len(evidence.x)
probe_x = torch.from_numpy(np.ascontiguousarray(evidence.x))
probe_y = torch.from_numpy(np.ascontiguousarray(evidence.y))
probe_model.zero_grad(set_to_none=True)
dense_loss = SG.token_loss(probe_model, probe_x, probe_y)
dense_loss.backward()
COUNTERS["dense_parity_gradient_rows"] += len(probe_x)
dense_grads = {k: p.grad.detach().clone() for k, p in probe_model.named_parameters()}
acc_loss = accumulated_grad(probe_model, probe_x, probe_y, 17, "parity")
gradient_max_abs, gradient_max_rel = 0., 0.
for name, param in probe_model.named_parameters():
    diff = (param.grad - dense_grads[name]).abs()
    gradient_max_abs = max(gradient_max_abs, float(diff.max()))
    meaningful = dense_grads[name].abs() > 1e-3
    if meaningful.any():
        gradient_max_rel = max(gradient_max_rel, float((diff[meaningful] / dense_grads[name].abs()[meaningful]).max()))
assert abs(acc_loss-float(dense_loss.detach())) < 1e-4
assert gradient_max_abs <= 1e-4 and gradient_max_rel <= 1e-3, (gradient_max_abs, gradient_max_rel)
save(OUT / "parity_before_fit.json", {"torch_numpy_logit_max_abs":parity_max,"bound":parity_bound,
     "dense_loss":float(dense_loss.detach()),"accumulated_loss":acc_loss,
     "gradient_max_abs":gradient_max_abs,"gradient_max_rel_for_abs_gt_1e-3":gradient_max_rel})
del probe_model, dense_grads

PRED_CACHE = {}
def predictions(params, split):
    key = (params_sha256(params), split)
    if key in PRED_CACHE:
        return PRED_CACHE[key]
    previous = HERE / "scan_extension" / "predictions" / f"{key[0]}_{split}.npz"
    if previous.exists():
        with np.load(previous, allow_pickle=False) as archive:
            pred = archive["pred"]
    else:
        pred = predict(inst.forward, params, parts[split]["x"], 1024)
        COUNTERS["numpy_forward_rows"] += len(parts[split]["x"])
    PRED_CACHE[key] = pred
    return pred

def reading(params, split):
    pred = predictions(params, split)
    base_pred = predictions(BASE, split)
    y = parts[split]["y"]
    result = part_summary(y, base_pred, pred)
    mask = UNFITTED[split]
    result["not_in_generated_fit"] = part_summary(y[mask], base_pred[mask], pred[mask]) if mask.any() else {"n": 0}
    if split == "final_new":
        mask = COMMON_UNPROBED
        result["neither_fitted_nor_WSP_probed"] = part_summary(y[mask], base_pred[mask], pred[mask]) if mask.any() else {"n": 0}
    return result

RESULTS = []
try:
    for arm in PROTOCOL["arms"]:
        arm_path = OUT / arm["name"]
        arm_path.mkdir()
        torch.manual_seed(arm["seed"])
        model = SG.rebuild(BASE)
        named = dict(model.named_parameters())
        fit_start, fit_cpu = time.monotonic(), time.process_time()
        before_counts = dict(COUNTERS)
        mask = None
        if arm["method"] == "sparse19_sal":
            log(f"{arm['name']}: computing fixed base saliency on all 4065 rows")
            saliency_loss = accumulated_grad(model, x_t, y_t, 128, "saliency")
            raw_mask = R.top_fraction({k:p.grad.detach().numpy() for k,p in named.items()}, sorted(named))
            mask = {k:torch.from_numpy(v.astype(np.float32)) for k,v in raw_mask.items()}
            save(arm_path / "mask.json", {"saliency_loss":saliency_loss,
                 "mask_sha256":params_sha256(raw_mask),"entries":sum(int(m.sum()) for m in raw_mask.values())})
        optimizer = torch.optim.Adam(list(model.parameters()), lr=arm["lr"], betas=(.9,.999), eps=1e-8,
                                     weight_decay=0., foreach=False)
        curve = []
        log(f"{arm['name']}: fixed lr {arm['lr']}, {arm['steps']} full-batch updates")
        for step in range(1, arm["steps"]+1):
            loss = accumulated_grad(model, x_t, y_t, 128, "training")
            if mask is not None:
                for k,p in named.items():
                    p.grad.mul_(mask[k])
            optimizer.step()
            COUNTERS["gradient_steps"] += 1
            if step % 10 == 0 or step == 1:
                curve.append({"step":step,"loss_before_update":loss,"elapsed_wall":time.monotonic()-fit_start})
                save(arm_path / "progress.json", {"fixed_arm":arm,"curve":curve,"counters":dict(COUNTERS)})
                log(f"{arm['name']} step {step}/{arm['steps']}, token CE {loss:.6f}, fit {time.monotonic()-fit_start:.1f}s")
            if step % 50 == 0:
                save_params(arm_path / f"step{step}.npz", T.export_seq_params(model))
        child = T.export_seq_params(model)
        if mask is not None:
            for k,v in raw_mask.items():
                assert np.array_equal(BASE[k][~v], child[k][~v])
        fit_wall, fit_cpu = time.monotonic()-fit_start, time.process_time()-fit_cpu
        child_sha = save_params(arm_path / "fixed_candidate.npz", child)
        n_changed = count_changed(BASE, child)
        save(arm_path / "candidate_seal_before_readouts.json", {"arm":arm,"params_sha256":child_sha,
             "n_changed":n_changed,"fit_wall_seconds":fit_wall,"fit_cpu_seconds":fit_cpu,
             "fit_counter_delta":{k:COUNTERS[k]-before_counts[k] for k in COUNTERS}})
        read_start = time.monotonic()
        readout = {name:reading(child,name) for name in ("check_new","check_old","final_new","final_old")}
        result = {"arm":arm,"params_sha256":child_sha,"n_changed":n_changed,"readout":readout,
                  "fit_wall_seconds":fit_wall,"fit_cpu_seconds":fit_cpu,"readout_wall_seconds":time.monotonic()-read_start,
                  "exact_published_reference_hash":child_sha==arm.get("fixed_reference_child_sha256"),
                  "hash_interpretation":"Gradient accumulation and CPU float order may differ from original GPU; exact match is observed only if hashes actually match."}
        save(arm_path / "result.json",result)
        RESULTS.append(result)
        log(f"{arm['name']} final new {100*readout['final_new']['em_child']:.4f}%, old {100*readout['final_old']['em_child']:.4f}%, changed {n_changed}")
        del model,optimizer,named,child
    published = load_params(HERE / "scan_extension" / "selected" / "full_published_edit.npz")
    wsp_readout = {name:reading(published,name) for name in ("final_new","final_old")}
    save(OUT / "summary.json", {"protocol_sha256":sha_file(PROTOCOL_PATH),"script_sha256":sha_file(__file__),
         "results":RESULTS,"wsp_on_same_subsets":wsp_readout,"counters":dict(COUNTERS),
         "wall_seconds_excluding_queue":time.monotonic()-START,"cpu_seconds":time.process_time()-CPU_START,
         "max_rss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
         "interpretation":PROTOCOL["interpretation"]})
    log("Both fixed grammar-to-data references completed")
except Exception as error:
    save(OUT / "failure.json", {"type":type(error).__name__,"message":str(error),"partial_results":RESULTS,
         "counters":dict(COUNTERS),"elapsed_wall":time.monotonic()-START})
    raise
