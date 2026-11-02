"""TRAIN-only causal/class-target/initialization and joint-backward controls.

No validation or test split is loaded. One temporary optimizer update is an
interface control, separate from the frozen 36-fit formal training campaign.
"""

import argparse
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import torch
from torch.nn import functional

from experiments.hcsn_v13_followup_20261102.joint_core import data, model


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit(output):
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    checks, failures, tasks = 0, [], []
    source = {str(p): sha(p) for p in Path(model.__file__).parent.glob("*.py")}
    source[str(Path(__file__).resolve())] = sha(__file__)
    plan = {"scope": "TRAIN-only interface controls, no formal candidate fit or evaluation",
            "source_sha256": source, "split_policy": "Only train; no val/test loader calls",
            "initialization_seed": 13301, "temporary_optimizer_steps": 1,
            "torch": torch.__version__, "rtol": 1e-11, "atol": 1e-12}
    (output / "PLAN.json").write_text(json.dumps(plan, indent=2) + "\n")

    def check(ok, label):
        nonlocal checks
        checks += 1
        if not ok and len(failures) < 25:
            failures.append(label)

    for task, classes in (("async_av", 6), ("av_binding", 2)):
        raw = data.legacy_data(task, "train")
        x, y, objects, orders, identity = data.dataset(task, "train")
        norm = data.Normalization.fit(x.numpy())
        normalized = norm.apply(x)
        check(x.shape[1:] == (6, 55) and y.shape == x.shape[:2], "real class-target/row shape")
        check(torch.equal(y, y[:, :1].expand_as(y)), "same true recording target at each prefix")
        fixture = {k: v[:1].copy() if isinstance(v, np.ndarray) and len(v) == len(raw["ids"]) else v for k, v in raw.items()}
        changed = dict(fixture)
        changed["y"] = fixture["y"].copy()
        active = changed["y"] >= 0
        changed["y"][active] = (changed["y"][active]+1) % classes
        changed["ids"] = np.asarray(["masked-training-source"])
        with patch.object(data, "legacy_data", return_value=fixture):
            fx, fy, _, forders, _ = data.dataset(task, "train")
        with patch.object(data, "legacy_data", return_value=changed):
            altered, target, _, _, _ = data.dataset(task, "train")
        check(torch.equal(fx, altered) and not torch.equal(fy, target), "labels and IDs cannot enter accepted input rows")
        arrays = fixture["x"][0, fixture["valid"][0]]
        observed = fixture["observed"][0, fixture["valid"][0]]
        times = fixture["relative_times"][0, fixture["valid"][0]]
        kind = (arrays[:, 33] > arrays[:, 32]).astype(int)
        for sequence, order in zip(fx.numpy(), forders):
            levels, previous = {"audio": 0, "video": 0}, 0
            for row, modality in zip(sequence, order):
                levels[modality] += 1
                k = int(modality == "video"); level = levels[modality]
                visible = observed & (kind == k) & (arrays[:, 34+k] > 0) & (times <= level)
                fresh = visible & (times >= 0 if level == 1 else times > level-1)
                expected = arrays[fresh, :16].mean(0) if fresh.any() else np.zeros(16)
                check(np.array_equal(row[35:51], expected), "independent non-overlapping source-window features")
                current = max(levels.values())
                check(row[34] == current-previous and row[32:34].tolist() == [levels["audio"]/3, levels["video"]/3], "legal per-modality/global source clock")
                previous = current
        protected = [32, 33, 34, 51, 52, 53, 54]
        check(torch.equal(normalized[..., protected], x[..., protected]), "train normalizer preserves clocks and flags exactly")
        initial, sizes = [], {}
        for family in model.FAMILIES:
            torch.manual_seed(13301)
            network = model.Model(family, classes)
            sizes[family] = sum(p.numel() for p in network.parameters())
            if family in model.FAMILIES[:3]:
                initial.append({k: v.clone() for k, v in network.state_dict().items()})
            sample = normalized[:1]
            with torch.no_grad():
                full = network(sample)
                state, history = network.initial(sample[:, 0]), []
                for t in range(6):
                    state, _ = network.step(sample[:, t], state)
                    history.append(sample[:, t])
                    check(torch.equal(network.classify(history, state), full[:, t]), "actual incremental content/class readout equals unroll")
                    changed_future = sample.clone()
                    changed_future[:, t+1:, :32] += .123
                    changed_future[:, t+1:, 35:51] -= .173
                    check(torch.equal(network(changed_future)[:, :t+1], full[:, :t+1]), "future accepted contents cannot change earlier class logits")
        check(all(set(value) == set(initial[0]) and all(torch.equal(value[k], initial[0][k]) for k in value) for value in initial[1:]), "three HX/gate arms have identical initial tensors")
        torch.manual_seed(13301)
        joint = model.Model("hx_full", classes)
        optimizer = torch.optim.AdamW(joint.parameters(), lr=.003, weight_decay=.0001)
        before = joint.asset_drive.weight.detach().clone()
        prediction = joint(normalized[:64])
        loss = functional.cross_entropy(prediction.flatten(0, 1), y[:64].flatten())
        loss.backward()
        gradients = {name: float(parameter.grad.norm()) for name, parameter in joint.named_parameters() if parameter.grad is not None}
        for name in ("asset_drive.weight", "candidate.weight", "gate.weight", "reader.0.weight", "reader.2.weight"):
            check(name in gradients and np.isfinite(gradients[name]) and gradients[name] > 0, "real TRAIN CE has finite nonzero joint gradient: " + name)
        optimizer.step()
        change = float((joint.asset_drive.weight.detach()-before).norm())
        check(change > 0, "temporary actual optimizer step changes asset encoder")
        tasks.append({"task": task, "training_identity": identity, "parameter_counts": sizes,
                      "temporary_loss": float(loss.detach()), "gradient_norms": gradients,
                      "temporary_asset_weight_change_norm": change})
    check(all(sha(path) == expected for path, expected in source.items()), "all tested sources unchanged through controls")
    result = {"schema": "hcsn-v13-train-interface-review.v1", "checks": checks,
              "all_checks_passed": not failures, "failed_examples": failures, "tasks": tasks,
              "validation_or_test_loaded": False, "formal_fit": False,
              "scope": "Actual historical TRAIN rows and temporary class-CE joint update; no holdout quality or strong-reference qualification"}
    (output / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "tasks"}))
    return result["all_checks_passed"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if audit(args.out) else 1)
