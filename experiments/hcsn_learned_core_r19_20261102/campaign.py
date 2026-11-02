"""Independent model/control training, frozen selection, then untouched test worlds."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
import torch
from tools.hcsn.addressed_decision_r15_20261101.law import Law
from .models import ContentNetwork, KINDS, rollout
from .statistics import contrast, holm
from .task import dataset

HERE = Path(__file__).resolve().parent
THRESHOLDS = (-1., .05, .10, .20, 1000.)
CONTROLS = ("light", "value")


def save(path, value):
    raw = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode()
    if path.suffix == ".gz":
        raw = gzip.compress(raw, mtime=0)
    with path.open("xb") as stream:
        stream.write(raw)


def tensor_data(data, indices=None):
    result = {}
    for name, array in data.items():
        if name in ("owner_ids", "seeds", "aliases"):
            continue
        value = array if indices is None else array[indices]
        result[name] = torch.from_numpy(value).float() if name == "fees" else torch.from_numpy(value).long()
    return result


def evaluate(model, data, control, threshold):
    started = time.process_time()
    with torch.no_grad():
        _, answer, read, p, details = rollout(model, tensor_data(data), control, threshold)
    target, fee = data["targets"], data["fees"]
    answers, actions, probabilities = answer.numpy(), read.numpy(), p.numpy()
    correct = answers == target
    utility = correct - actions * fee
    ce = -np.log(probabilities[np.arange(len(target))[:, None], np.arange(target.shape[1]), target]).mean()
    return dict(utility=float(utility.mean()), accuracy=float(correct.mean()), ce=float(ce),
                brier=float(np.mean(np.sum((probabilities - np.eye(4)[target]) ** 2, axis=-1))),
                reads=int(actions.sum()), fees=float((actions * fee).sum()),
                cpu_seconds=time.process_time() - started), dict(answer=answers.tolist(),
                read=actions.tolist(), probabilities=probabilities.tolist(), targets=target.tolist(),
                fees=fee.tolist(), owner_ids=data["owner_ids"].tolist(),
                prior=details["prior"].numpy().tolist(),
                predicted_read_value=details["read_value"].numpy().tolist(),
                hypothetical_answers=details["hypothetical_answers"].numpy().tolist())


def verify():
    freeze = json.loads((HERE / "SOURCE_FREEZE.json").read_text())
    for name, sha in freeze["files"].items():
        if hashlib.sha256((HERE / name).read_bytes()).hexdigest() != sha:
            raise ValueError(f"Source mismatch: {name}")
    for relative, sha in freeze["dependencies"].items():
        if hashlib.sha256((HERE.parents[1] / relative).read_bytes()).hexdigest() != sha:
            raise ValueError(f"Dependency mismatch: {relative}")
    receipt = json.loads((HERE / "PUBLICATION.json").read_text())
    if (receipt.get("readback_verified") is not True or
            receipt.get("source_freeze_sha256") != hashlib.sha256((HERE / "SOURCE_FREEZE.json").read_bytes()).hexdigest()):
        raise ValueError("Verified remote source freeze is required")
    return freeze, receipt


def worker(output, stage):
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    freeze, receipt = verify()
    cpu, wall = time.process_time(), time.perf_counter()
    if stage == "confirm":
        return confirm(output, protocol, freeze, receipt, cpu, wall)
    output.mkdir(parents=True, exist_ok=False)
    train, train_id = dataset(protocol["namespaces"]["train"], protocol["train_worlds"], "iid")
    val, val_id = dataset(protocol["namespaces"]["validation"], protocol["validation_worlds"], "iid")
    save(output / "OPEN_TRAIN_VAL.json", dict(train=train_id, validation=val_id, publication=receipt))
    # Raw offline collection is common; every potential READ is purchased before
    # model fitting. Targets and unchosen potential tokens never enter policies.
    np.savez_compressed(output / "TRAIN_DATA.npz", **train)
    np.savez_compressed(output / "VALIDATION_DATA.npz", **val)
    training, selections, checkpoint_sha = [], {}, {}
    for fit in protocol["fits"]:
        for control_index, control in enumerate(CONTROLS):
            for kind in KINDS:
                started = time.process_time()
                # Independent fitting jobs; identical analytic/HMM initialization
                # is deliberate for the explicit same-family realization check.
                torch.manual_seed(fit * 2 + control_index)
                model = ContentNetwork(kind, Law())
                optimizer = torch.optim.Adam(model.parameters(), lr=protocol["learning_rate"])
                rng = np.random.default_rng(fit * 2 + control_index)
                losses, visited = [], np.zeros(64, dtype=np.int64)
                initial_scale = float(model.log_scale.detach().exp()) if hasattr(model, "log_scale") else None
                for step in range(protocol["updates"]):
                    indices = rng.integers(len(train["initial"]), size=protocol["batch_size"])
                    batch = tensor_data(train, indices)
                    exploration = None
                    if control == "light" or step < protocol["warmup_updates"]:
                        exploration = torch.from_numpy(rng.random(batch["fees"].shape) < .5)
                    optimizer.zero_grad(set_to_none=True)
                    loss, _, actions, _, _ = rollout(model, batch, control, .025, True, exploration)
                    if not bool(torch.isfinite(loss)):
                        raise FloatingPointError("Nonfinite training objective")
                    loss.backward()
                    optimizer.step()
                    losses.append(float(loss.detach()))
                    codes = (actions.numpy() * (1 << np.arange(6))).sum(1)
                    visited += np.bincount(codes, minlength=64)
                scores = []
                for threshold in THRESHOLDS if control == "light" else (0.,):
                    score, _ = evaluate(model, val, control, threshold)
                    scores.append(dict(threshold=threshold, **score))
                chosen = max(range(len(scores)), key=lambda i: (scores[i]["utility"], -scores[i]["ce"], -i))
                name = f"{fit}_{control}_{kind}"
                path = output / f"weights_{name}.pt"
                torch.save(model.state_dict(), path)
                sha = hashlib.sha256(path.read_bytes()).hexdigest()
                checkpoint_sha[name] = sha
                selections[name] = dict(threshold=scores[chosen]["threshold"], validation=scores[chosen])
                training.append(dict(name=name, fit=fit, control=control, core=kind,
                    parameters=sum(p.numel() for p in model.parameters()), updates=protocol["updates"],
                    losses=losses, visited_read_histories=visited.tolist(), validation_candidates=scores,
                    scale_before=initial_scale,
                    scale_after=float(model.log_scale.detach().exp()) if hasattr(model, "log_scale") else None,
                    checkpoint_sha256=sha, cpu_seconds=time.process_time() - started))
                save(output / f"training_{name}.json", training[-1])
    ordinary = {}
    for fit in protocol["fits"]:
        for control in CONTROLS:
            pool = ("hmm", "gru", "ssm", "cache")
            ordinary[f"{fit}_{control}"] = max(pool, key=lambda k: (
                selections[f"{fit}_{control}_{k}"]["validation"]["utility"],
                -selections[f"{fit}_{control}_{k}"]["validation"]["ce"], -pool.index(k)))
    save(output / "SELECTION_FREEZE.json", dict(selections=selections, ordinary=ordinary,
         checkpoints=checkpoint_sha, all_training_complete_before_test=True))
    save(output / "PREPARED.json", dict(train_id=train_id, val_id=val_id,
        offline_collection_reads=int(train["fees"].size),
        offline_collection_logical_fees=float(train["fees"].sum()),
        internal_cpu_seconds=time.process_time() - cpu, wall_seconds=time.perf_counter() - wall,
        independent_fits=len(training)))
    print(json.dumps(dict(prepare_complete=True, independent_fits=len(training),
        selection_freeze_sha256=hashlib.sha256((output / "SELECTION_FREEZE.json").read_bytes()).hexdigest())))


def confirm(prepared, protocol, freeze, receipt, cpu, wall):
    selected_path = prepared / "SELECTION_FREEZE.json"
    publication = json.loads((prepared / "POSTTRAIN_PUBLICATION.json").read_text())
    if (publication.get("readback_verified") is not True or
            publication.get("selection_freeze_sha256") != hashlib.sha256(selected_path.read_bytes()).hexdigest()):
        raise ValueError("Prepared choices must be remotely frozen before test worlds open")
    choices = json.loads(selected_path.read_text())
    selections, ordinary = choices["selections"], choices["ordinary"]
    for name, sha in choices["checkpoints"].items():
        if hashlib.sha256((prepared / f"weights_{name}.pt").read_bytes()).hexdigest() != sha:
            raise ValueError(f"Prepared checkpoint mismatch: {name}")
    prepared_meta = json.loads((prepared / "PREPARED.json").read_text())
    output = prepared / "confirmation_01"
    output.mkdir(exist_ok=False)
    results, raw_same_family, factorized = {}, [], []
    test_ids = {}
    for domain, count, queries in (("iid", protocol["test_worlds"], 6),
                                   ("ood", protocol["test_worlds"], 6),
                                   ("long", protocol["long_worlds"], 24)):
        test, identity = dataset(protocol["namespaces"][domain], count, "ood" if domain == "ood" else "iid", queries)
        test_ids[domain] = identity
        np.savez_compressed(output / f"TEST_DATA_{domain}.npz", **test)
        rows, traces = [], {}
        for fit in protocol["fits"]:
            for control in CONTROLS:
                for kind in KINDS:
                    name = f"{fit}_{control}_{kind}"
                    model = ContentNetwork(kind, Law())
                    model.load_state_dict(torch.load(prepared / f"weights_{name}.pt", weights_only=True))
                    score, raw = evaluate(model, test, control, selections[name]["threshold"])
                    rows.append(dict(name=name, fit=fit, control=control, core=kind, **score))
                    save(output / f"raw_{domain}_{name}.json.gz", raw)
                    traces[name] = raw
                    if kind == "analytic":
                        model.intervention = "factorized"
                        altered, _ = evaluate(model, test, control, selections[name]["threshold"])
                        factorized.append(dict(domain=domain, name=name, **altered))
                a, h = traces[f"{fit}_{control}_analytic"], traces[f"{fit}_{control}_hmm"]
                raw_same_family.append(dict(domain=domain, fit=fit, control=control, exact_equal=a == h))
        results[domain] = rows
    effects = {}
    for domain in ("iid", "ood", "long"):
        cells = {letter: [] for letter in "ABCD"}
        for fit in protocol["fits"]:
            get = {(r["control"], r["core"]): r["utility"] for r in results[domain] if r["fit"] == fit}
            cells["A"].append(get["light", ordinary[f"{fit}_light"]])
            cells["B"].append(get["value", ordinary[f"{fit}_value"]])
            cells["C"].append(get["light", "analytic"])
            cells["D"].append(get["value", "analytic"])
        effects[domain] = dict(cells=cells, **{name: contrast(np.asarray(cells[a]) - cells[b])
            for name, a, b in (("B-A", "B", "A"), ("D-C", "D", "C"),
                               ("C-A", "C", "A"), ("D-B", "D", "B"))})
        effects[domain]["interaction"] = contrast((np.asarray(cells["D"]) - cells["C"])
                                                 - (np.asarray(cells["B"]) - cells["A"]))
    primary = holm([effects[d]["D-B"] for d in ("iid", "ood")])
    passed = all(r["mean"] >= .01 and r["lower"] > 0 and r["holm_p"] < .05 for r in primary)
    verify()
    save(output / "SUMMARY.json", dict(source_freeze=freeze, publication=receipt, test_ids=test_ids,
         results=results, effects=effects, ordinary=ordinary, selections=selections,
         same_family_checks=raw_same_family, same_weights_factorized_execution=factorized,
         actual_core_gain_gate_passed=passed,
         full_learned_belief_content_integration=True, independent_four_cell_training=True,
         offline_collection_reads=prepared_meta["offline_collection_reads"],
         offline_collection_logical_fees=prepared_meta["offline_collection_logical_fees"],
         internal_cpu_seconds=time.process_time() - cpu, wall_seconds=time.perf_counter() - wall,
         production_activation=False))
    print(json.dumps(dict(core_gate_passed=passed, effects={d: effects[d]["D-B"] for d in effects},
                          same_family_all_equal=all(r["exact_equal"] for r in raw_same_family))))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stage", choices=("prepare", "confirm"), required=True)
    a = parser.parse_args()
    if a.worker:
        worker(a.output, a.stage)
    else:
        started = time.perf_counter()
        meter_path = a.output.with_name(a.output.name + "_" + a.stage)
        with meter_path.with_suffix(".stdout").open("x") as stdout, meter_path.with_suffix(".stderr").open("x") as stderr:
            child = subprocess.Popen([sys.executable, "-m", __package__ + ".campaign", "--worker",
                                      "--output", str(a.output), "--stage", a.stage], stdout=stdout, stderr=stderr)
            _, status, usage = os.wait4(child.pid, 0)
            child.returncode = os.waitstatus_to_exitcode(status)
        save(meter_path.with_suffix(".process.json"), dict(exit_code=child.returncode,
            cpu_seconds=usage.ru_utime + usage.ru_stime, wall_seconds=time.perf_counter() - started,
            max_rss_linux_kib=usage.ru_maxrss, scope="Whole interpreter, imports, data collection, all candidates, validation, checkpoints, test, ablations and output; parent/audit/developer costs separate"))
        raise SystemExit(child.returncode)
