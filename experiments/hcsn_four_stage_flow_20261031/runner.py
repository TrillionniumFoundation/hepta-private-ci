"""Frozen, budgeted CPU study with separate training and confirmation phases.

Fixed final-step checkpoint, no test-based selection. All arms receive the same
per-step episodes. A fit failure is retained and does not erase other results.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import resource
import time
import traceback

import numpy as np
import torch
from torch.nn import functional as F

from . import dynamic_data, synthetic_data
from .av_data import MODALITY_SLICES, mask_modalities
from .models import ARMS, ContentModel


HERE = Path(__file__).resolve().parent
TASKS = ("dynamics", "mqar", "selective", "binding", "avt")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def source_hashes():
    paths = [HERE / name for name in ("runner.py", "models.py", "marked_flow.py", "av_data.py",
                                       "synthetic_data.py", "dynamic_data.py")]
    paths += [HERE.parent / "hcsn_distributional_v2/distribution_kernel.py"]
    return {str(p.relative_to(HERE.parent.parent)): digest(p) for p in sorted(paths)}


def freeze(out, steps):
    protocol = dict(schema="hcsn-four-stage.run.v1", frozen_utc=datetime.now(timezone.utc).isoformat(),
        source_hashes=source_hashes(), arms=list(ARMS), tasks=list(TASKS), seeds=[17, 29, 43],
        steps=steps, batch_size=24, evaluation_episodes=512, learning_rate=.003,
        optimizer="AdamW", weight_decay=.0001, gradient_norm_clip=1.,
        selection="Final step only; no per-arm hyperparameter search or early stopping",
        execution="Train every selected fit, freeze checkpoint hashes, then evaluate without training",
        data_seeds="Synthetic train=100000+seed*10000+step; dev=71001; test=81001; separate split namespaces",
        metrics=["weighted accuracy", "cross entropy", "all queries correct", "paired per-episode predictions"],
        inference="Three seeds are independent fits; episodes or actors are clustered, not token IID",
        gates=dict(operator="All fixed numerical tolerances pass",
                   resampling="Max observed-logit error <= 1e-4 in float32",
                   content="MQAR/selective/binding all-query correctness must improve, not majority shortcuts",
                   adoption="No adoption claim unless quality and complete deployment cost improve",
                   avt="Two-modality Bayes oracle=5/6; >chance alone does not establish trimodal binding"),
        cost=dict(training="all fixed steps, failures, evaluation and data preparation retained",
                  inference="CPU complete sequence, 3 warmups, 9 measured repeats; shared host",
                  energy="Unmeasured; CPU seconds are not joules", gpu="Unavailable in this run",
                  acquisition="Existing CREMA-D files reused; historical acquisition cost unknown",
                  frontend="Fixed causal-prefix features, no pretrained encoder; offline decode measured separately"),
        limits=["Single recurrent core, no deep boundary-communicating model",
                "Finite CTMC, not full He-Xiong equity or an optimal stopping proof",
                "J/G are readout features, not independently established dual force channels",
                "Matched information and steps, measured but unequal parameters and compute",
                "Intervention ablations are sensitivity, not retrained causal necessity tests",
                "Two-sentence AVT is not foundation-model validation"],
        runtime=dict(python=platform.python_version(), torch=torch.__version__, numpy=np.__version__,
                     device="cpu", threads=1, platform=platform.platform(),
                     cuda_available=torch.cuda.is_available()))
    save_json(Path(out) / "PROTOCOL.json", protocol)


def tensors(arrays, indices=None):
    result = {}
    for key in ("x", "dt", "observed", "y", "sample_weight"):
        value = arrays[key] if indices is None else arrays[key][indices]
        result[key] = torch.from_numpy(np.ascontiguousarray(value))
    return result


def synthetic(task, n, seed, split, stress="base"):
    generator = dynamic_data if task == "dynamics" else synthetic_data
    return generator.batch(task, n, seed, split, stress)


class AVData:
    def __init__(self, path, candidate_freeze_sha256=None):
        self.path, self.cache, self.raw_cache, self.identities = Path(path), {}, {}, {}
        self.candidate_freeze_sha256 = candidate_freeze_sha256
        self.plan_sha256 = digest(self.path / "PLAN.json")
        plan = json.loads((self.path / "PLAN.json").read_text())
        if plan["contract"]["source_sha256"] != digest(HERE / "av_data.py"):
            raise ValueError("Prepared AV data used a different frozen adapter")
        continuous = self._read("train")["x"][..., :128]
        self.mean = continuous.mean((0, 1))
        self.std = np.maximum(continuous.std((0, 1)), .05)

    def _read(self, split):
        if split in self.raw_cache:
            return self.raw_cache[split]
        data_path, receipt_path = self.path / f"{split}.npz", self.path / f"{split}.json"
        receipt = json.loads(receipt_path.read_text())
        actual = digest(data_path)
        if receipt["sha256"] != actual or receipt["plan_sha256"] != self.plan_sha256:
            raise ValueError(f"Prepared AV identity mismatch for {split}")
        if split == "test" and (not self.candidate_freeze_sha256 or
                receipt.get("candidate_freeze_sha256") != self.candidate_freeze_sha256):
            raise ValueError("AV confirmation data does not reference this checkpoint freeze")
        with np.load(data_path, allow_pickle=False) as file:
            data = {key: file[key] for key in file.files}
        self.identities[split] = dict(plan_sha256=self.plan_sha256, npz_sha256=actual,
            receipt_sha256=digest(receipt_path), candidate_freeze_sha256=receipt.get("candidate_freeze_sha256"))
        self.raw_cache[split] = data
        return data

    def get(self, split, stress="base"):
        key = (split, stress)
        if key in self.cache:
            return self.cache[key]
        source = "validation" if split == "dev" else split
        data = self._read(source)
        x = data["x"].copy()
        x[..., :128] = (x[..., :128] - self.mean) / self.std
        if stress.startswith("no_"):
            x = mask_modalities(x, [stress[3:]])
        n, t, _ = x.shape
        y = np.full((n, t), -100, np.int64)
        y[:, -1] = data["y"]
        weights = np.zeros((n, t), np.float32)
        weights[:, -1] = data["sample_weight"]
        result = dict(x=x, dt=data["dt"].astype(np.float32), observed=np.ones((n, t), bool),
                      y=y, sample_weight=weights, actor=data["actor"], sample_id=data["sample_id"])
        self.cache[key] = result
        return result


def score(logits, data):
    y, weight = data["y"], data["sample_weight"]
    valid = y >= 0
    predictions = logits.argmax(-1)
    correct = (predictions == y) & valid
    safe_y = np.maximum(y, 0)
    log_probability = logits - np.logaddexp.reduce(logits, axis=-1, keepdims=True)
    ce = -np.take_along_axis(log_probability, safe_y[..., None], axis=-1)[..., 0]
    result = dict(accuracy=float((correct * weight).sum() / weight.sum()),
                  cross_entropy=float((ce * weight).sum() / weight.sum()),
                  all_queries_correct=float((correct | ~valid).all(-1).mean()),
                  query_count=int(valid.sum()), episodes=len(y))
    if "target_available" in data:
        for name, select in (("visible_target", data["target_available"] & valid),
                             ("missing_target", ~data["target_available"] & valid)):
            result[name + "_accuracy"] = float(correct[select].mean()) if select.any() else None
    return result


def predict(model, data, batch_size=64):
    outputs = []
    with torch.no_grad():
        for start in range(0, len(data["x"]), batch_size):
            b = tensors(data, slice(start, start + batch_size))
            outputs.append(model(b["x"], b["dt"], b["observed"]).numpy())
    return np.concatenate(outputs)


def new_model(task, arm):
    classes, input_dim = (2, 143) if task == "avt" else ((4, 24) if task == "dynamics" else (8, 24))
    return ContentModel(arm, input_dim, classes)


def training_record(out, key, protocol_sha256, frozen_commit):
    destination = Path(out) / key
    record = json.loads((destination / "training.json").read_text())
    if (record["status"] != "trained" or record["protocol_sha256"] != protocol_sha256
            or record["frozen_commit"] != frozen_commit
            or record["checkpoint_sha256"] != digest(destination / "checkpoint.pt")
            or record["training_curve_sha256"] != digest(destination / "training_curve.npy")
            or record["loss_log_sha256"] != digest(destination / "losses.jsonl")):
        raise ValueError(f"Training artifact identity mismatch: {key}")
    return record


def train_fit(task, arm, seed, out, protocol, av, frozen_commit):
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    destination = Path(out) / f"{task}__{arm}__{seed}"
    protocol_sha256 = digest(Path(out) / "PROTOCOL.json")
    if (destination / "training.json").exists():
        return training_record(out, destination.name, protocol_sha256, frozen_commit)
    destination.mkdir(parents=True, exist_ok=False)
    torch.manual_seed(seed)
    model = new_model(task, arm)
    optimizer = torch.optim.AdamW(model.parameters(), lr=protocol["learning_rate"],
                                 weight_decay=protocol["weight_decay"])
    losses = []
    train = av.get("train") if task == "avt" else None
    with (destination / "losses.jsonl").open("x", buffering=1) as stream:
        for step in range(protocol["steps"]):
            data_seed = 100000 + seed * 10000 + step
            if train is not None:
                indices = np.random.default_rng(data_seed).integers(len(train["x"]), size=protocol["batch_size"])
                b = tensors(train, indices)
            else:
                b = tensors(synthetic(task, protocol["batch_size"], data_seed, "train"))
            optimizer.zero_grad(set_to_none=True)
            logits = model(b["x"], b["dt"], b["observed"])
            token_loss = F.cross_entropy(logits.flatten(0, 1), b["y"].flatten(),
                                        reduction="none", ignore_index=-100).reshape(b["y"].shape)
            loss = (token_loss * b["sample_weight"]).sum() / b["sample_weight"].sum()
            if not bool(torch.isfinite(loss)):
                raise ArithmeticError("Nonfinite training loss")
            loss.backward()
            gradient_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), protocol["gradient_norm_clip"],
                                                          error_if_nonfinite=True)
            optimizer.step()
            row = [step, float(loss.detach()), float(gradient_norm)]
            losses.append(row)
            stream.write(json.dumps(row, allow_nan=False) + "\n")
    checkpoint = destination / "checkpoint.pt"
    data_identities = {"train": av.identities["train"]} if task == "avt" else {}
    torch.save(dict(model=model.state_dict(), optimizer=optimizer.state_dict(),
                    arm=arm, task=task, seed=seed, protocol_sha256=protocol_sha256,
                    frozen_commit=frozen_commit, data_identities=data_identities), checkpoint)
    np.save(destination / "training_curve.npy", np.asarray(losses))
    train_cost = dict(wall_seconds=time.perf_counter() - start_wall,
                      cpu_seconds=time.process_time() - start_cpu,
                      examples=protocol["steps"] * protocol["batch_size"],
                      scope="Model/optimizer construction, training, loss logging and final artifact serialization")
    record = dict(task=task, arm=arm, seed=seed, frozen_commit=frozen_commit,
        protocol_sha256=protocol_sha256, checkpoint_sha256=digest(checkpoint),
        training_curve_sha256=digest(destination / "training_curve.npy"),
        loss_log_sha256=digest(destination / "losses.jsonl"), training=train_cost,
        data_identities=data_identities, shape=model.resource_shape(b["x"].shape[1]),
        final_training_loss=losses[-1][1], status="trained")
    save_json(destination / "training.json", record)
    print(json.dumps(dict(phase="train", task=task, arm=arm, seed=seed,
                          seconds=train_cost["wall_seconds"])), flush=True)
    return record


def evaluate_fit(task, arm, seed, out, protocol, av, frozen_commit, candidate, candidate_sha256):
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    destination = Path(out) / f"{task}__{arm}__{seed}"
    protocol_sha256 = digest(Path(out) / "PROTOCOL.json")
    trained = training_record(out, destination.name, protocol_sha256, frozen_commit)
    checkpoint = destination / "checkpoint.pt"
    frozen = candidate["checkpoints"][destination.name]
    if (frozen["checkpoint_sha256"] != digest(checkpoint)
            or frozen["training_receipt_sha256"] != digest(destination / "training.json")):
        raise ValueError("Checkpoint changed after the candidate freeze")
    if (destination / "result.json").exists():
        existing = json.loads((destination / "result.json").read_text())
        if (existing["candidate_freeze_sha256"] != candidate_sha256
                or existing["checkpoint_sha256"] != frozen["checkpoint_sha256"]
                or existing["predictions_sha256"] != digest(destination / "predictions.npz")):
            raise ValueError("Existing evaluation artifact identity mismatch")
        return existing
    if (destination / "predictions.npz").exists():
        raise FileExistsError("Partial evaluation retained; do not overwrite its predictions")
    saved = torch.load(checkpoint, map_location="cpu", weights_only=True)
    if (saved["protocol_sha256"] != protocol_sha256 or saved["frozen_commit"] != frozen_commit
            or (saved["task"], saved["arm"], saved["seed"]) != (task, arm, seed)):
        raise ValueError("Checkpoint payload does not match the frozen candidate")
    if task == "avt" and saved["data_identities"]["train"] != av.identities["train"]:
        raise ValueError("AV training data changed before evaluation")
    model = new_model(task, arm)
    model.load_state_dict(saved["model"], strict=True)
    model.eval()
    evaluations, raw, base_test = {}, {}, None
    for split in ("dev", "test"):
        conditions = ["base"] if split == "dev" else (
            ["base", "no_audio", "no_video", "no_text"] if task == "avt" else
            (["base", "irregular", "missing", "resample"] if task == "dynamics" else
             ["base", "long_delay", "irregular", "missing", "resample"]))
        for stress in conditions:
            data = av.get(split, stress) if task == "avt" else synthetic(
                task, protocol["evaluation_episodes"], 71001 if split == "dev" else 81001, split, stress)
            logits = predict(model, data)
            name = f"{split}__{stress}"
            evaluations[name] = score(logits, data)
            raw[name + "__logits"], raw[name + "__y"] = logits, data["y"]
            raw[name + "__weight"] = data["sample_weight"]
            if "target_available" in data:
                raw[name + "__target_available"] = data["target_available"]
            if "actor" in data:
                raw[name + "__actor"] = data["actor"]
                raw[name + "__sample_id"] = data["sample_id"]
            if name == "test__base":
                base_test = data
            if stress == "resample":
                evaluations[name]["observed_logit_max_difference"] = float(np.max(
                    np.abs(logits[:, 1::2] - raw["test__base__logits"])))
    if task == "dynamics":
        logits, labels = raw["test__base__logits"], base_test["y"]
        correct = logits.argmax(-1) == labels
        evaluations["recovery"] = dict(first_after_jump=float(correct[:, 9].mean()),
                                        later_after_jump=float(correct[:, [11, 13, 15]].mean()),
                                        forcing_only=float((np.digitize(base_test["x"][..., 2], [-.5, 0., .5])
                                                            == labels)[labels >= 0].mean()))
    if arm == "flow":
        for intervention in ("no_marks", "factorized_content"):
            model.intervention = intervention
            logits = predict(model, base_test)
            evaluations["sensitivity__" + intervention] = score(logits, base_test)
            raw["sensitivity__" + intervention + "__logits"] = logits
        model.intervention = None
    with (destination / "predictions.npz").open("xb") as stream:
        np.savez_compressed(stream, **raw)
    timed = tensors(base_test, slice(0, min(24, len(base_test["x"]))))
    with torch.no_grad():
        for _ in range(3):
            model(timed["x"], timed["dt"], timed["observed"])
        latencies = []
        for _ in range(9):
            tick = time.perf_counter()
            model(timed["x"], timed["dt"], timed["observed"])
            latencies.append(time.perf_counter() - tick)
    inference = dict(batch_size=len(timed["x"]), sequence_length=timed["x"].shape[1],
                     wall_seconds=latencies, median_seconds=float(np.median(latencies)),
                     episodes_per_second=len(timed["x"]) / float(np.median(latencies)),
                     energy_joules=None, dedicated_hardware=False, device="cpu",
                     scope="Prepared-feature complete-sequence forward; raw media preparation is separate")
    evaluation_cost = dict(wall_seconds=time.perf_counter() - start_wall,
                           cpu_seconds=time.process_time() - start_cpu,
                           scope="Checkpoint verification/loading, model construction, evaluation, artifacts and timing repeats")
    result = dict(task=task, arm=arm, seed=seed, frozen_commit=frozen_commit,
        protocol_sha256=protocol_sha256, checkpoint_sha256=digest(checkpoint),
        candidate_freeze_sha256=candidate_sha256,
        predictions_sha256=digest(destination / "predictions.npz"), training=trained["training"],
        evaluation=evaluation_cost, data_identities=dict(av.identities) if task == "avt" else {},
        evaluations=evaluations, inference=inference, shape=model.resource_shape(timed["x"].shape[1]),
        total_fit_wall_seconds=trained["training"]["wall_seconds"] + evaluation_cost["wall_seconds"],
        total_fit_cpu_seconds=trained["training"]["cpu_seconds"] + evaluation_cost["cpu_seconds"],
        process_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        peak_rss_scope="Cumulative maximum of this evaluation process, not an isolated per-fit peak",
        final_training_loss=trained["final_training_loss"], status="completed")
    save_json(destination / "result.json", result)
    print(json.dumps(dict(phase="evaluate", task=task, arm=arm, seed=seed, accuracy=evaluations["test__base"]["accuracy"],
                          seconds=result["total_fit_wall_seconds"])), flush=True)
    return result


def freeze_checkpoints(out, tasks, arms, seeds, protocol, frozen_commit):
    if protocol["source_hashes"] != source_hashes():
        raise ValueError("Source drift during training; checkpoint freeze refused")
    protocol_sha256 = digest(Path(out) / "PROTOCOL.json")
    records = {}
    for task in tasks:
        for seed in seeds:
            for arm in arms:
                key = f"{task}__{arm}__{seed}"
                record = training_record(out, key, protocol_sha256, frozen_commit)
                records[key] = dict(task=task, arm=arm, seed=seed,
                    checkpoint_sha256=record["checkpoint_sha256"],
                    training_receipt_sha256=digest(Path(out) / key / "training.json"))
    contract = dict(schema="hcsn-four-stage.checkpoint-freeze.v1", frozen_commit=frozen_commit,
                    protocol_sha256=protocol_sha256, tasks=list(tasks), arms=list(arms),
                    seeds=list(seeds), checkpoints=records,
                    selection="All specified final-step checkpoints; no evaluation-based selection")
    path = Path(out) / ("CHECKPOINT_FREEZE__" + "_".join(tasks) + ".json")
    if path.exists():
        previous = json.loads(path.read_text())
        previous.pop("frozen_utc", None)
        if previous != contract:
            raise FileExistsError("Different checkpoint freeze already exists; preserve it")
    else:
        save_json(path, dict(frozen_utc=datetime.now(timezone.utc).isoformat(), **contract))
    return path


def read_candidate(path, out, tasks, arms, seeds, frozen_commit):
    candidate = json.loads(Path(path).read_text())
    protocol_sha256 = digest(Path(out) / "PROTOCOL.json")
    if (candidate.get("schema") != "hcsn-four-stage.checkpoint-freeze.v1"
            or candidate.get("protocol_sha256") != protocol_sha256
            or candidate.get("frozen_commit") != frozen_commit):
        raise ValueError("Candidate freeze is not for this protocol and source commit")
    # Verify every selected checkpoint before any dev or confirmation load.
    for task in tasks:
        for seed in seeds:
            for arm in arms:
                key = f"{task}__{arm}__{seed}"
                frozen = candidate["checkpoints"][key]
                record = training_record(out, key, protocol_sha256, frozen_commit)
                if (frozen["checkpoint_sha256"] != record["checkpoint_sha256"]
                        or frozen["training_receipt_sha256"] != digest(Path(out) / key / "training.json")):
                    raise ValueError(f"Candidate checkpoint changed: {key}")
    return candidate, digest(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--phase", choices=("train", "evaluate"), default="train")
    parser.add_argument("--candidate-freeze", type=Path)
    parser.add_argument("--steps", type=int, default=600)
    parser.add_argument("--tasks", nargs="+", choices=TASKS, default=list(TASKS))
    parser.add_argument("--arms", nargs="+", choices=ARMS, default=list(ARMS))
    parser.add_argument("--seeds", nargs="+", type=int)
    parser.add_argument("--av-data", type=Path)
    parser.add_argument("--frozen-commit")
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    if args.steps <= 0:
        parser.error("The frozen step budget must be positive")
    if args.freeze:
        freeze(args.out, args.steps)
        return
    protocol = json.loads((args.out / "PROTOCOL.json").read_text())
    if protocol["source_hashes"] != source_hashes():
        raise ValueError("Source drift after freeze; retain old campaign and freeze a new campaign")
    if not args.frozen_commit or len(args.frozen_commit) != 40:
        raise ValueError("An actual pre-execution commit is required")
    if "avt" in args.tasks and not args.av_data:
        raise ValueError("AVT requires prepared, identity-checked data")
    seeds = args.seeds or protocol["seeds"]
    for selected, registered in ((args.tasks, protocol["tasks"]),
                                 (args.arms, protocol["arms"]), (seeds, protocol["seeds"])):
        if len(selected) != len(set(selected)) or not set(selected).issubset(registered):
            raise ValueError("Selected fits must be a unique subset of the frozen protocol")
    phase_wall, phase_cpu = time.perf_counter(), time.process_time()
    candidate, candidate_sha256 = None, None
    if args.phase == "evaluate":
        if args.candidate_freeze is None:
            raise ValueError("Evaluation requires a real --candidate-freeze checkpoint artifact")
        candidate, candidate_sha256 = read_candidate(args.candidate_freeze, args.out,
            args.tasks, args.arms, seeds, args.frozen_commit)
    elif args.candidate_freeze is not None:
        raise ValueError("Training does not accept a confirmation candidate artifact")
    av = AVData(args.av_data, candidate_sha256) if args.av_data else None
    attempts, failures = [], []
    for task in args.tasks:
        for seed in seeds:
            for arm in args.arms:
                attempt_wall, attempt_cpu = time.perf_counter(), time.process_time()
                key = f"{task}__{arm}__{seed}"
                completed_file = "training.json" if args.phase == "train" else "result.json"
                reused = (args.out / key / completed_file).exists()
                try:
                    if args.phase == "train":
                        train_fit(task, arm, seed, args.out, protocol, av, args.frozen_commit)
                    else:
                        evaluate_fit(task, arm, seed, args.out, protocol, av, args.frozen_commit,
                                     candidate, candidate_sha256)
                    attempts.append(dict(fit=key, status="verified_existing" if reused else "completed",
                        wall_seconds=time.perf_counter() - attempt_wall,
                        cpu_seconds=time.process_time() - attempt_cpu))
                except Exception:
                    failure = dict(phase=args.phase, task=task, arm=arm, seed=seed, traceback=traceback.format_exc(),
                                   utc=datetime.now(timezone.utc).isoformat(),
                                   wall_seconds=time.perf_counter() - attempt_wall,
                                   cpu_seconds=time.process_time() - attempt_cpu)
                    failure_dir = args.out / "failures"
                    failure_dir.mkdir(exist_ok=True)
                    save_json(failure_dir / f"{task}__{arm}__{seed}__{time.time_ns()}.json", failure)
                    failures.append(failure)
                    print(json.dumps(failure), flush=True)
    checkpoint_manifest = None
    if args.phase == "train" and not failures:
        checkpoint_manifest = freeze_checkpoints(args.out, args.tasks, args.arms, seeds,
                                                protocol, args.frozen_commit)
    receipt = dict(phase=args.phase, utc=datetime.now(timezone.utc).isoformat(),
        protocol_sha256=digest(args.out / "PROTOCOL.json"), frozen_commit=args.frozen_commit,
        selected_fits=len(args.tasks) * len(args.arms) * len(seeds),
        completed=len(attempts), failed=len(failures), attempts=attempts, failures=failures,
        checkpoint_freeze=str(checkpoint_manifest) if checkpoint_manifest else None,
        candidate_freeze_sha256=candidate_sha256,
        wall_seconds=time.perf_counter() - phase_wall,
        cpu_seconds=time.process_time() - phase_cpu,
        cost_scope="Phase body including data verification/setup and all attempts; nested fit costs are not additive",
        energy_joules=None)
    save_json(args.out / "phase_receipts" / f"{args.phase}__{time.time_ns()}.json", receipt)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
