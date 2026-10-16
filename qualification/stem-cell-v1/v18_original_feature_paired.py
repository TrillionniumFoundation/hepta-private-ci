"""Source-pinned original mmBERT 384D Feature -> five physical Head controls.

No encoder forward, independent blind custody, future utility or production effect.
Requires V14's create-only, SHA-frozen prepared source; private logits stay local.
"""
import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import torch
from safetensors.numpy import load as load_tensors
from torch import nn
from torch.nn import functional as F

INPUT_SHA = "d029f906565946216126db39e4ca3f4f14d7ab5a3c297ec2a62639ccdfbf604a"
FEATURE_SHA = "e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490"
ARCHIVE_SHA = "0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7"
DATA_SHA = "50335a2214756c7a9e09fee9ac9ed27ab855ea98635bb0fab0998144165ffb2c"
MODEL_REVISION = "abc32620dd4f6ab06f5fbe905dc25f310618e09f"
SCHEMA = "hepta.stem.v18.original-feature-investment.v1"
SEEDS = (41, 47, 53)
ARMS = ("no_change", "linear", "gated_residual", "continued_single", "split_router")


def check(ok, detail):
    if not ok:
        raise ValueError(detail)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def original_inputs(folder):
    folder = Path(folder)
    check(not folder.is_symlink(), "unsafe prepared folder")
    raw = (folder / "input.json").read_bytes()
    features = (folder / "features.safetensors").read_bytes()
    check(digest(raw) == INPUT_SHA and digest(features) == FEATURE_SHA,
          "original mmBERT feature/roster bytes required")
    p = json.loads(raw)
    check(p["production_authorized"] is False and p["archive_sha256"] == ARCHIVE_SHA
          and p["dataset_sha256"] == DATA_SHA and p["feature_sha256"] == FEATURE_SHA,
          "unmatched research-only source")
    roster, groups, labels = p["roster"], p["partitions"], p["labels"]
    check([len(groups[k]) for k in ("train", "calibration", "holdout")] == [64, 32, 32]
          and sorted(sum(groups.values(), [])) == list(range(128))
          and set(labels) == {str(i) for i in groups["train"] + groups["calibration"]}
          and len(roster) == 128, "heldout labels or missing cases")
    arr = load_tensors(features)
    check(set(arr) == {"features"}, "only original model tensor")
    x = arr["features"]
    check(x.shape == (128, 384) and x.dtype == np.float32 and np.isfinite(x).all(),
          "finite original FP32 Feature Snapshot")
    for split, idx in groups.items():
        check(all(roster[i]["split"] == split for i in idx), "source split drift")
    train = x[groups["train"]]
    x = (x - train.mean(0)) / np.maximum(train.std(0), np.float32(0.1))
    check(np.isfinite(x).all(), "nonfinite normalized feature")
    return torch.tensor(x.copy()), groups, labels


class OutputResidual(nn.Module):
    def __init__(self, mode):
        super().__init__()
        self.mode = mode
        shape = (2, 384, 4) if mode == "split_router" else (384, 4)
        self.delta = nn.Parameter(torch.zeros(shape))
        self.bias = nn.Parameter(torch.zeros((2, 4) if mode == "split_router" else (4,)))
        if mode == "gated_residual":
            self.gate = nn.Parameter(torch.zeros(384))
            self.gate_bias = nn.Parameter(torch.zeros(()))

    def forward(self, x, route=None):
        if self.mode == "split_router":
            check(route is not None and route.shape == (len(x),), "typed split route required")
            out = torch.einsum("bd,bdc->bc", x, self.delta[route]) + self.bias[route]
        else:
            out = x @ self.delta + self.bias
        if self.mode == "gated_residual":
            out = out * torch.sigmoid(x @ self.gate + self.gate_bias)[:, None]
        return out


def centers_from_train(x):
    # Unsupervised TRAIN-only eight-iteration two-centroid routing; no CAL labels.
    c = torch.stack((x[0], x[1])).clone()
    for _ in range(8):
        selected = (x[:, None, :] - c[None, :, :]).square().sum(-1).argmin(-1)
        for i in range(2):
            group = x[selected == i]
            if len(group):
                c[i] = group.mean(0)
    return c


def metric(logits, y):
    p = F.softmax(logits, -1)
    return {"accuracy": round((p.argmax(-1) == y).float().mean().item(), 8),
            "multiclass_brier": round((p - F.one_hot(y, 4)).square().sum(-1).mean().item(), 8)}


def run_one(x, groups, labels, seed, private):
    torch.manual_seed(seed)
    tx, cx, hx = (x[groups[s]] for s in ("train", "calibration", "holdout"))
    ty, cy = (torch.tensor([labels[str(i)] for i in groups[s]], dtype=torch.long)
              for s in ("train", "calibration"))
    rand = torch.Generator().manual_seed(seed + 1000)
    schedule = [torch.randint(0, 64, (16,), generator=rand) for _ in range(160)]
    parent = nn.Linear(384, 4)
    with torch.no_grad():
        parent.weight.zero_()
        parent.bias.zero_()
    started = time.process_time_ns()
    optimizer = torch.optim.Adam(parent.parameters(), lr=0.01)
    for indices in schedule[:80]:
        optimizer.zero_grad(set_to_none=True)
        F.cross_entropy(parent(tx[indices]), ty[indices]).backward()
        optimizer.step()
    base_ns = time.process_time_ns() - started
    pw, pb = parent.weight.detach().clone(), parent.bias.detach().clone()
    frozen = lambda z: F.linear(z, pw, pb)
    base_cal = frozen(cx)
    result = {"seed": seed, "base_train_steps": 80, "extra_train_steps": 80,
              "base_train_cpu_ns": base_ns, "arms": {}}
    for arm in ARMS:
        started = time.process_time_ns()
        params = []
        if arm == "no_change":
            apply = frozen
        elif arm == "continued_single":
            head = nn.Linear(384, 4)
            with torch.no_grad():
                head.weight.copy_(pw)
                head.bias.copy_(pb)
            params = list(head.parameters())
            apply = head
        else:
            head = OutputResidual(arm)
            params = list(head.parameters())
            if arm == "split_router":
                centers = centers_from_train(tx)
                route = lambda z: (z[:, None, :] - centers[None, :, :]).square().sum(-1).argmin(-1)
                apply = lambda z: frozen(z) + head(z, route(z))
            else:
                apply = lambda z: frozen(z) + head(z)
        equal = None if arm == "no_change" else torch.equal(apply(cx), base_cal)
        check(equal is not False, "changed no-change output before learning")
        if params:
            optimizer = torch.optim.Adam(params, lr=0.01 if arm == "continued_single" else 0.004)
            for indices in schedule[80:]:
                optimizer.zero_grad(set_to_none=True)
                F.cross_entropy(apply(tx[indices]), ty[indices]).backward()
                optimizer.step()
        cpu = time.process_time_ns() - started
        ts = time.process_time_ns()
        with torch.no_grad():
            logits = {"train": apply(tx), "calibration": apply(cx), "blind": apply(hx)}
            check(all(bool(torch.isfinite(t).all()) for t in logits.values()), "nonfinite physical output")
            raw = {k: v.numpy().astype("<f4") for k, v in logits.items()}
            hashes = {k: digest(v.tobytes()) for k, v in raw.items()}
            private.append({"seed": seed, "arm": arm,
                            "logits": {k: v.tolist() for k, v in raw.items()}})
            scores = {"train_fit": metric(logits["train"], ty),
                      "historical_calibration": metric(logits["calibration"], cy)}
        result["arms"][arm] = {"metrics": scores, "logit_sha256": hashes,
            "extra_training_cpu_ns": cpu if params else 0,
            "inference_cpu_ns": time.process_time_ns() - ts,
            "train_steps": 80 if arm == "no_change" else 160,
            "owned_extra_params": sum(t.numel() for t in params),
            "initial_equals_nochange": equal, "research_authorized": False}
    return result


def run(folder):
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    x, groups, labels = original_inputs(folder)
    private = []
    experiments = [run_one(x, groups, labels, s, private) for s in SEEDS]
    return ({"schema": SCHEMA, "original_archive_sha256": ARCHIVE_SHA,
        "original_model_revision": MODEL_REVISION,
        "original_cached_feature_file_sha256": FEATURE_SHA,
        "original_dataset_sha256": DATA_SHA,
        "original_genuine_pretrained_feature": True, "new_pretrained_encoder_forwards": 0,
        "source_family_count_for_future": 0, "future_window_count": 0,
        "independent_original_source_attestation": False,
        "holdout_labels_used_for_training_or_scoring": False,
        "independent_blind_label_custody": False,
        "calibration_previously_exposed": True,
        "train_cases": 64, "historical_calibration_cases": 32,
        "blind_unscored_cases": 32,
        "same_train_schedule_across_arms": True,
        "same_total_train_steps_across_learning_arms": True,
        "full_lifecycle_cost_qualified": False, "target_host_performance_qualified": False,
        "model_selection_authorized": False, "cell_split_authorized": False,
        "final_use_authorized": False,
        "decision": "DENY_ALL_HISTORICAL_CALIBRATION_ONLY", "seeds": experiments},
        {"source_sha256": ARCHIVE_SHA, "records": private, "research_only": True})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inputs", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--private-logits", type=Path, required=True)
    a = p.parse_args()
    check(not a.output.exists() and not a.private_logits.exists(), "create-only original evidence")
    result, private = run(a.inputs)
    with a.output.open("x") as out:
        json.dump(result, out, sort_keys=True, indent=2, allow_nan=False)
    with a.private_logits.open("x") as out:
        json.dump(private, out, sort_keys=True, allow_nan=False)
    print("V18 original feature physical Head proof:", result["decision"])
    for seed in result["seeds"]:
        print(seed["seed"], [(a, seed["arms"][a]["metrics"]["historical_calibration"])
                              for a in ARMS])


if __name__ == "__main__":
    main()
