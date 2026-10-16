"""V16 genuine mmBERT feature specialization and counterfactual experiment.

Research-only: all data/model identities are pinned to V14/V15. CAL labels are
read only for post-training evaluation, blind labels are never opened. A tested
candidate is NOT a production model or an admitted CellSplit.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import time
import os

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from safetensors.torch import load as load_torch, save as save_torch

import stem_counterfactual_split_v14 as v14
import stem_stable_router_v15 as v15

SCHEMA = "hepta.stem.specialization.v16.research"
V15_SOURCE_SHA256 = "7a998eebeab237b20c004f4cb4ef19adc48ad3e03ddb778658373049745decdd"
SEEDS = (41, 47, 53)
STEPS = 80
BATCH = 16
LEARNING_RATE = 0.1
CAPACITY = 4352
NAMES = ("frozen", "continued", "wide", "centroid", "task", "constant0", "constant1",
         "loss_gate", "loss_gate_swapped", "loss_gate_shuffled", "expected_gate",
         "expected_gate_swapped", "expected_gate_soft", "joint_hard",
         "joint_swapped", "joint_soft", "extra_continued")
PROTOCOL = {
    "schema": SCHEMA, "seeds": list(SEEDS), "steps_per_extra_fit": STEPS,
    "minibatch": BATCH, "learning_rate": LEARNING_RATE,
    "gate_source": "final frozen V15 experts TRAIN-only", "trained_arm_exposure": "1280 TRAIN example positions",
    "expected_gate_balance_coefficient": 0.02,
    "joint_rule": "soft expected per-expert cross entropy plus balance penalty",
    "joint_training_executes_both_experts": True, "selected_head_hard_inference": True,
    "soft_profiles_execute_both_experts": True,
    "source_only": "original 64 TRAIN + original 32 CALIBRATION, no blind labels",
    "calibration_is_prospective": False, "new_pretrained_encoder_forwards": 0,
    "production_authorized": False,
}


def require(cond, why):
    if not cond:
        raise ValueError(why)


def checked_bytes(path, expected, limit=1_000_000):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= limit,
            "missing/linked/oversized model material")
    value = path.read_bytes()
    require(v14.sha(value) == expected, "model/source digest mismatch")
    return value


def load_typed(directory, name, census):
    require(name in census and set(census[name]) == {"sha256", "scalars"}, "missing model census")
    raw = checked_bytes(Path(directory) / (name + ".safetensors"), census[name]["sha256"])
    state = load_torch(raw)
    require(sum(v.numel() for v in state.values()) == census[name]["scalars"]
            and all(v.dtype == torch.float32 and v.device.type == "cpu"
                    and bool(torch.isfinite(v).all()) for v in state.values()), "model tensor mismatch")
    return state


def open_v15(inputs, trained):
    inputs, trained = Path(inputs), Path(trained)
    require(not trained.is_symlink() and trained.is_dir(), "V15 model directory required")
    require(v14.sha(Path(v15.__file__).read_bytes()) == V15_SOURCE_SHA256, "V15 source changed")
    require((inputs / "input.json").is_file(), "missing original V14 input")
    x, meta = v15.read_inputs(inputs)
    report = v14.read_json(trained / "sealed.json")
    require(report["schema"] == v15.SCHEMA and report["producer_sha256"] == V15_SOURCE_SHA256
            and report["archive_sha256"] == v14.ARCHIVE_SHA
            and report["feature_sha256"] == v14.FEATURE_SHA
            and report["input_sha256"] == v14.INPUT_SHA and report["held_labels_read"] is False
            and report["held_scores"] is None and report["production_authorized"] is False
            and report["prospective_efficacy_verified"] is False and report["new_encoder_forwards"] == 0
            and set(report["seeds"]) == {"41", "47", "53"}, "V15 research source or scope changed")
    # All 58 persisted model files are bound to a completed, immutable V15 seal.
    require(len(report["models"]) == 58 and
            {p.name for p in trained.iterdir()} == {f"{k}.safetensors" for k in report["models"]} | {"sealed.json"},
            "incomplete or extra V15 research files")
    for name in report["models"]:
        load_typed(trained, name, report["models"])
    return x, meta, report


def make_split(state):
    model = v14.Split(nn.Linear(384, 4), state["centers"])
    model.load_state_dict(state, strict=True)
    return model.eval().requires_grad_(False)


def make_gate(state=None):
    model = nn.Linear(384, 1)
    if state is not None:
        model.load_state_dict(state, strict=True)
    else:
        nn.init.zeros_(model.weight)
        nn.init.zeros_(model.bias)
    return model


def fixed_scores(split, features):
    with torch.no_grad():
        return torch.stack([head(features) for head in split.heads], 1)


def per_expert_nll(logits, labels):
    require(tuple(logits.shape) == (len(labels), 2, 4), "two expert logits expected")
    return -logits.log_softmax(-1).gather(-1, labels[:, None, None].expand(-1, 2, 1)).squeeze(-1)


def gate_routes(gate, features):
    return (gate(features).reshape(-1) > 0).long()


def hard_head(split, features, routes):
    return split(features, routes)


def soft_head(split, gate, features):
    scores = torch.stack([head(features) for head in split.heads], 1)
    weights = gate(features).sigmoid().reshape(-1, 1)
    return (1 - weights) * scores[:, 0] + weights * scores[:, 1]


def make_schedule(seed):
    rng = np.random.default_rng(seed ^ 0x1616)
    return rng.integers(0, 64, (STEPS, BATCH)).tolist()


def fit_new_gate(gate, z, y, split, schedule, *, objective):
    v14.checked_features(z)
    require(objective in ("loss_target", "expected_nll"), "unknown TRAIN-only gate objective")
    with torch.no_grad():
        nll = per_expert_nll(fixed_scores(split, z), y)
        labels = (nll[:, 1] < nll[:, 0]).long()
    optimizer = torch.optim.SGD(gate.parameters(), lr=LEARNING_RATE)
    begin_cpu, begin_wall = time.process_time_ns(), time.perf_counter_ns()
    with torch.enable_grad():
        for selection in schedule:
            ix = torch.tensor(selection, dtype=torch.long)
            optimizer.zero_grad(set_to_none=True)
            out = gate(z[ix]).reshape(-1)
            if objective == "loss_target":
                loss = F.binary_cross_entropy_with_logits(out, labels[ix].float())
            else:
                weights = out.sigmoid()
                loss = ((1 - weights) * nll[ix, 0] + weights * nll[ix, 1]).mean()
                loss = loss + PROTOCOL["expected_gate_balance_coefficient"] * (weights.mean() - .5).square()
            require(bool(torch.isfinite(loss)), "nonfinite gate loss")
            loss.backward()
            optimizer.step()
    return {"objective": objective, "optimizer_steps": len(schedule), "examples": sum(len(s) for s in schedule),
            "source_train_rows": 64,
            "source_train_target_counts": torch.bincount(labels, minlength=2).tolist(),
            "scheduled_sha256": v14.sha(np.asarray(schedule, dtype="<i8").tobytes()),
            "cpu_ns": time.process_time_ns() - begin_cpu,
            "wall_ns": time.perf_counter_ns() - begin_wall,
            "experts_trained": False, "train_symmetric_expert_forwards": 0}


def train_joint(split, gate, z, y, schedule):
    split.train().requires_grad_(True)
    gate.train().requires_grad_(True)
    optimizer = torch.optim.SGD(list(split.heads.parameters()) + list(gate.parameters()), lr=LEARNING_RATE)
    begin_cpu, begin_wall = time.process_time_ns(), time.perf_counter_ns()
    for selection in schedule:
        ix = torch.tensor(selection, dtype=torch.long)
        optimizer.zero_grad(set_to_none=True)
        scores = torch.stack([head(z[ix]) for head in split.heads], 1)
        nll = per_expert_nll(scores, y[ix])
        weights = gate(z[ix]).reshape(-1).sigmoid()
        loss = ((1 - weights) * nll[:, 0] + weights * nll[:, 1]).mean()
        loss = loss + PROTOCOL["expected_gate_balance_coefficient"] * (weights.mean() - .5).square()
        require(bool(torch.isfinite(loss)), "nonfinite joint loss")
        loss.backward()
        optimizer.step()
    split.eval().requires_grad_(False)
    gate.eval().requires_grad_(False)
    return {"objective": "joint_soft_expected_nll", "optimizer_steps": len(schedule),
            "examples": sum(len(s) for s in schedule), "source_train_rows": 64,
            "scheduled_sha256": v14.sha(np.asarray(schedule, dtype="<i8").tobytes()),
            "cpu_ns": time.process_time_ns() - begin_cpu, "wall_ns": time.perf_counter_ns() - begin_wall,
            "experts_trained": True, "train_symmetric_expert_forwards": 2 * sum(len(s) for s in schedule)}


def train_extra_continue(model, z, y, schedule):
    model.requires_grad_(True)
    optimizer = torch.optim.SGD(model.parameters(), lr=LEARNING_RATE)
    begin_cpu, begin_wall = time.process_time_ns(), time.perf_counter_ns()
    for selection in schedule:
        ix = torch.tensor(selection, dtype=torch.long)
        optimizer.zero_grad(set_to_none=True)
        loss = F.cross_entropy(model(z[ix]), y[ix])
        require(bool(torch.isfinite(loss)), "nonfinite unsplit loss")
        loss.backward()
        optimizer.step()
    model.eval().requires_grad_(False)
    return {"objective": "matched_extra_updates_unsplit", "optimizer_steps": len(schedule),
            "examples": sum(len(s) for s in schedule), "source_train_rows": 64,
            "scheduled_sha256": v14.sha(np.asarray(schedule, dtype="<i8").tobytes()),
            "cpu_ns": time.process_time_ns() - begin_cpu, "wall_ns": time.perf_counter_ns() - begin_wall,
            "experts_trained": True, "train_symmetric_expert_forwards": 0}


def predictions(z, split, task, loss_gate, expected_gate, joint, joint_gate, extra,
                continued, wide, parent, seed):
    with torch.no_grad():
        centroid = v14.assign(z, split.centers)
        task_r = gate_routes(task, z)
        loss_r = gate_routes(loss_gate, z)
        expected_r = gate_routes(expected_gate, z)
        joint_r = gate_routes(joint_gate, z)
        perm = torch.from_numpy(np.random.default_rng(seed ^ 0x1616).permutation(len(z)))
        # Candidate probabilities are computed using the same final unchanged experts.
        scores = {
            "frozen": parent(z), "continued": continued(z), "wide": wide(z),
            "centroid": hard_head(split, z, centroid), "task": hard_head(split, z, task_r),
            "constant0": hard_head(split, z, torch.zeros(len(z), dtype=torch.long)),
            "constant1": hard_head(split, z, torch.ones(len(z), dtype=torch.long)),
            "loss_gate": hard_head(split, z, loss_r),
            "loss_gate_swapped": hard_head(split, z, 1 - loss_r),
            "loss_gate_shuffled": hard_head(split, z, loss_r[perm]),
            "expected_gate": hard_head(split, z, expected_r),
            "expected_gate_swapped": hard_head(split, z, 1 - expected_r),
            "expected_gate_soft": soft_head(split, expected_gate, z),
            "joint_hard": hard_head(joint, z, joint_r),
            "joint_swapped": hard_head(joint, z, 1 - joint_r),
            "joint_soft": soft_head(joint, joint_gate, z),
            "extra_continued": extra(z),
        }
        routes = {"centroid": centroid, "task": task_r, "loss_gate": loss_r,
                  "expected_gate": expected_r, "joint_hard": joint_r,
                  "loss_gate_shuffled": loss_r[perm]}
        return ({k: v.softmax(-1).tolist() for k, v in scores.items()},
                {k: v.tolist() for k, v in routes.items()})


def brier(probs, y):
    return v14.brier(torch.tensor(probs), y)


def choose(scores, old_fit):
    """No-change / continuation mandatory; calibrated before any blind scoring."""
    options = ("frozen", "continued", "wide", "centroid", "task", "loss_gate",
               "expected_gate", "joint_hard", "extra_continued")
    require(all(k in scores and k in old_fit for k in options), "incomplete research candidate census")
    baseline = scores["frozen"]
    eligible = ["frozen"] + [k for k in options[1:]
               if baseline - scores[k] > .01 and old_fit[k] - old_fit["frozen"] <= .01]
    # Candidate whole-life work is unequal; do not rank on imaginary equal cost.
    win = min(eligible, key=lambda k: (scores[k], options.index(k)))
    if win not in ("frozen", "continued", "extra_continued") and scores["continued"] - scores[win] <= .01:
        win = min([k for k in eligible if k in ("frozen", "continued", "extra_continued")],
                  key=lambda k: (scores[k], options.index(k)))
    return win


def run(inputs, trained, output):
    output = Path(output)
    require(not output.exists() and output.parent.is_dir() and not output.parent.is_symlink(),
            "create-only destination in a real directory required")
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    x, meta, seal = open_v15(inputs, trained)
    p = meta["partitions"]
    tx, cx, hx = (x[p[k]] for k in ("train", "calibration", "holdout"))
    y = torch.tensor([meta["labels"][str(i)] for i in p["train"]], dtype=torch.long)
    cy = torch.tensor([meta["labels"][str(i)] for i in p["calibration"]], dtype=torch.long)
    mean = load_typed(trained, "normalizer", seal["models"])["mean"]
    tz, cz, hz = (v15.normalized(a, mean) for a in (tx, cx, hx))
    record = {"schema": SCHEMA, "protocol": PROTOCOL, "protocol_sha256": v14.sha(v14.canonical(PROTOCOL)),
              "source_sha256": v14.sha(Path(__file__).read_bytes()),
              "v15_sha256": V15_SOURCE_SHA256, "v15_seal_sha256": v14.sha((Path(trained)/"sealed.json").read_bytes()),
              "input_sha256": v14.INPUT_SHA, "archive_sha256": v14.ARCHIVE_SHA,
              "feature_sha256": v14.FEATURE_SHA, "new_encoder_forwards": 0,
              "model_files": {}, "seeds": {}, "held_labels_read": False, "held_scores": None,
              "prospective_efficacy_verified": False, "production_authorized": False,
              "independent_future_utility": None, "independent_negative_transfer": None,
              "target_host_4096_qualified": False}
    output.mkdir(mode=0o700)
    def store(name, module):
        state = {k:v.detach().contiguous() for k,v in module.state_dict().items()}
        raw = save_torch(state)
        v14.write_new(output/(name+".safetensors"), raw)
        record["model_files"][name] = {"sha256":v14.sha(raw), "state_scalars":sum(v.numel() for v in state.values())}
    for seed in SEEDS:
        prefix = str(seed)
        v15slot = lambda suffix:load_typed(trained, prefix + '-' + suffix, seal["models"])
        split = make_split(v15slot("centroid"))
        parent = nn.Linear(384, 4);parent.load_state_dict(v15slot("frozen"));parent.eval().requires_grad_(False)
        continued = nn.Linear(384,4);continued.load_state_dict(v15slot("continued"));continued.eval().requires_grad_(False)
        wide = v15.Wide(parent, seed);wide.load_state_dict(v15slot("wide"));wide.eval().requires_grad_(False)
        task = make_gate(v15slot("gate"));task.eval().requires_grad_(False)
        old_hashes = {a:v14.parameter_sha(obj) for a,obj in (("split",split),("parent",parent),("continued",continued),("wide",wide),("task",task))}
        schedule = make_schedule(seed)
        loss_gate = make_gate()
        work_loss = fit_new_gate(loss_gate, tz, y, split, schedule, objective="loss_target")
        expected_gate = make_gate()
        work_expected = fit_new_gate(expected_gate, tz, y, split, schedule, objective="expected_nll")
        joint = copy.deepcopy(split)
        joint_gate = make_gate()
        work_joint = train_joint(joint, joint_gate, tz, y, schedule)
        extra = copy.deepcopy(continued)
        work_extra = train_extra_continue(extra, tz, y, schedule)
        for a,obj in (("split",split),("parent",parent),("continued",continued),("wide",wide),("task",task)):
            require(v14.parameter_sha(obj)==old_hashes[a], "frozen original V15 model mutated")
        for a,obj in (("loss_gate",loss_gate),("expected_gate",expected_gate),
                      ("joint",joint),("joint_gate",joint_gate),("extra_continued",extra)):
            store(prefix+'-'+a,obj)
        cal_pred, cal_routes = predictions(cz,split,task,loss_gate,expected_gate,joint,joint_gate,extra,continued,wide,parent,seed)
        old_pred,_ = predictions(tz[:32],split,task,loss_gate,expected_gate,joint,joint_gate,extra,continued,wide,parent,seed)
        blind_pred, blind_routes = predictions(hz,split,task,loss_gate,expected_gate,joint,joint_gate,extra,continued,wide,parent,seed)
        scores = {k:{"correct": int((torch.tensor(v).argmax(-1)==cy).sum()),"brier":brier(v,cy)}
                  for k,v in cal_pred.items()}
        oldfit = {k:brier(v,y[:32]) for k,v in old_pred.items()}
        best = per_expert_nll(fixed_scores(split,tz),y).argmin(-1)
        oof_labels = torch.tensor(seal["seeds"][prefix]["oof_targets"],dtype=torch.long)
        require(oof_labels.shape==(64,),"V15 OOF teacher target mismatch")
        diagnosis = {
            "train_optimal_head_counts":torch.bincount(best,minlength=2).tolist(),
            "v15_oof_preferred_head_counts":torch.bincount(oof_labels,minlength=2).tolist(),
            "v15_oof_vs_final_expert_direct_agreement":int((oof_labels==best).sum()),
            "v15_oof_vs_final_expert_flipped_agreement":int((1-oof_labels==best).sum()),
            "train_loss_gate_vs_final_optimal_agreement":int((gate_routes(loss_gate,tz)==best).sum()),
            "train_expected_gate_vs_final_optimal_agreement":int((gate_routes(expected_gate,tz)==best).sum()),
            "train_joint_gate_count":torch.bincount(gate_routes(joint_gate,tz),minlength=2).tolist(),
            "calibration_route_counts": {name:torch.bincount(torch.tensor(routes),minlength=2).tolist()
                                        for name,routes in cal_routes.items()},
        }
        best_score = choose({k:v["brier"] for k,v in scores.items()},oldfit)
        record["seeds"][prefix] = {"calibration":scores,"calibration_routes":cal_routes,
            "calibration_probabilities":cal_pred,"blind_routes":blind_routes,
            "blind_probabilities":blind_pred,"old_train_brier":oldfit,
            "selected_research_candidate":best_score,"diagnostics":diagnosis,
            "work":{"loss_gate":work_loss,"expected_gate":work_expected,
                    "joint":work_joint,"extra_continued":work_extra},
            "frozen_parent_and_v15_heads_unchanged":True}
    require(v14.sha((Path(inputs)/"input.json").read_bytes())==v14.INPUT_SHA,
            "admission input changed during training")
    require(v14.sha((Path(trained)/"sealed.json").read_bytes())==record["v15_seal_sha256"],
            "V15 source changed during training")
    v14.write_new(output/"sealed.json", v14.canonical(record))
    return record


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs",required=True)
    parser.add_argument("--v15",required=True)
    parser.add_argument("--output",required=True)
    a=parser.parse_args()
    run(a.inputs,a.v15,a.output)
