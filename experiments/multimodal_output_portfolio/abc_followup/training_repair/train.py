"""Train two matched success constraints against an actually stronger baseline."""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

import torch

from ...abc_recovery.base_recovery import file_sha, write_json
from ...abc_next.settings import CACHE, MANIFEST, observers
from ...v6.data import Observation, Target
from ...v6.neural import parameter_hash
from ...v7.data import make_batch
from ...v7.snapshot import Snapshot
from ...v7.sources import load_roles
from ..training.objective import DualState, objective
from ..training.train import fixed_run, persisted_scores
from .protocol import verify


def fit_one(spec, corpus, observer, seed, arm, directory):
    directory.mkdir(parents=True, exist_ok=False)
    raw = directory / "raw"
    raw.mkdir()
    baselines = spec["baselines"][str(seed)]
    warm = Snapshot.load(baselines["warm"]["path"], expected_file_sha256=baselines["warm"]["sha256"])
    strong = Snapshot.load(baselines["mean"]["path"], expected_file_sha256=baselines["mean"]["sha256"])
    if (strong.metadata["arm"], strong.metadata["seed"], strong.metadata["training_steps"],
            strong.metadata["training_source_role"]) != ("mean", seed, 400, "train"):
        raise ValueError("The constraint reference is not the matched trained mean model")
    model = deepcopy(warm._model).train().requires_grad_(True)
    optimizer = torch.optim.Adam(model.parameters(), lr=spec["learning_rate"])
    dual = DualState(spec["dual_initial"][arm])
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    chain, schedule = hashlib.sha256(), hashlib.sha256()
    history = []
    conditions, scenarios = spec["conditions"], spec["scenarios"]
    with (directory / "steps.jsonl").open("x") as stream:
        for step in range(spec["steps"]):
            batch_seed = 202610260000 + seed * 1000003 + step
            candidate_seed = 202610270000 + seed * 1000033 + step
            reference_seed = 202610280000 + seed * 1000037 + step
            batch = make_batch(corpus, "train", conditions, batch_seed)
            observation = Observation(*(x.repeat_interleave(scenarios, 0) for x in
                (batch.observation.pixels, batch.observation.mask, batch.observation.text_tokens)))
            target = Target(*(x.repeat_interleave(scenarios, 0) for x in
                (batch.target.pixels, batch.target.text_tokens, batch.target.labels)))
            candidate = fixed_run(model, observation, candidate_seed)
            with torch.inference_mode():
                reference = fixed_run(strong._model, observation, reference_seed)
            measured, media_sha = persisted_scores(raw / f"step-{step:04d}.npz", candidate,
                                                    reference, observer, target)
            utility, success = measured[0]
            reference_success = measured[1][1]
            auxiliary = model.loss(model.decode(candidate.state, teacher_tokens=target.text_tokens), target)["joint"].mean()
            loss, stats = objective(candidate.terminal_log_probability.reshape(conditions, scenarios),
                utility.reshape(conditions, scenarios), success.reshape(conditions, scenarios),
                auxiliary, arm="risk_success", dual=dual, gamma=spec["gamma"],
                auxiliary_weight=spec["auxiliary_weight"])
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            norm = float(torch.nn.utils.clip_grad_norm_(model.parameters(), 5.))
            optimizer.step()
            gap = float(reference_success.float().mean() - success.float().mean())
            dual = dual.advance(gap, rate=spec["dual_rate"], cap=spec["dual_cap"])
            row = {"step": step + 1, "source_ids": batch.source_ids, "batch_seed": batch_seed,
                "candidate_seed": candidate_seed, "reference_seed": reference_seed,
                "media_sha256": media_sha, "reference_success": float(reference_success.float().mean()),
                "failure_gap": gap, "dual_after_step": dual.value, "gradient_norm_before_clip": norm, **stats}
            encoded = json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
            stream.write(encoded + "\n")
            chain.update(encoded.encode() + b"\n")
            schedule.update(json.dumps({"step": step, "source_ids": batch.source_ids,
                "batch_seed": batch_seed, "candidate_seed": candidate_seed, "reference_seed": reference_seed},
                sort_keys=True, separators=(",", ":")).encode() + b"\n")
            history.append({k: v for k, v in row.items() if k not in ("source_ids", "media_sha256")})
            if (step + 1) % 100 == 0 or step + 1 == spec["steps"]:
                stream.flush()
                print(json.dumps({"seed": seed, "arm": arm, "step": step + 1,
                    "dual": dual.value, "candidate_success": stats["success"],
                    "reference_success": row["reference_success"]}), flush=True)
    metadata = {"schema": "hepta.abc4.reference-repair-model.v1", "arm": arm, "seed": seed,
        "training_steps": spec["steps"], "source_role": "train", "warm_sha256": baselines["warm"]["sha256"],
        "constraint_reference_sha256": baselines["mean"]["sha256"],
        "training_schedule_sha256": schedule.hexdigest(), "step_chain_sha256": chain.hexdigest(),
        "dual_initial": spec["dual_initial"][arm], "dual_final": dual.value}
    snapshot = Snapshot(model, metadata)
    saved_sha = snapshot.save(directory / "model.pt")
    with (directory / "optimizer-final.pt").open("xb") as stream:
        torch.save({"optimizer": optimizer.state_dict(), "dual": dual.value, "model_sha256": saved_sha}, stream)
    warm.verify_integrity()
    strong.verify_integrity()
    record = {**metadata, "status": "completed", "model_path": str(directory / "model.pt"),
        "model_file_sha256": saved_sha, "model_parameter_sha256": snapshot.parameter_sha256,
        "candidate_rows": conditions * scenarios * spec["steps"],
        "reference_rows": conditions * scenarios * spec["steps"],
        "physical_media_reopened_before_scoring": True,
        "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
        "final_50_steps": history[-50:], "population_constraint_certificate": False}
    write_json(directory / "result.json", record)
    return {k: v for k, v in record.items() if k != "final_50_steps"}


def run(protocol_path):
    spec = json.loads(protocol_path.read_text())
    verify(spec)
    root = Path(spec["output"])
    root.mkdir(parents=True, exist_ok=False)
    write_json(root / "registration.json", {"unix_ns": time.time_ns(),
        "protocol_sha256": file_sha(protocol_path), "source_sha256": spec["source_sha256"]})
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    entries = []
    try:
        torch.set_num_threads(spec["threads"])
        torch.use_deterministic_algorithms(True)
        corpus = load_roles(CACHE, MANIFEST, roles=("train",))
        observer = observers()["primary"]
        before = parameter_hash(observer)
        for seed in spec["seeds"]:
            for arm in spec["arms"]:
                entries.append(fit_one(spec, corpus, observer, seed, arm,
                    root / f"seed-{seed}" / arm))
        verify(spec)
        if before != parameter_hash(observer):
            raise ValueError("Frozen training observer changed")
        for seed in spec["seeds"]:
            if len({r["training_schedule_sha256"] for r in entries if r["seed"] == seed}) != 1:
                raise ValueError("Repair treatments did not share their train/draw schedule")
        write_json(root / "result.json", {"schema": "hepta.abc4.reference-repair-training-result.v1",
            "status": "completed", "protocol_sha256": file_sha(protocol_path), "models": entries,
            "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
            "new_holdout_opened": False})
    except BaseException as error:
        write_json(root / "failure.json", {"error": repr(error), "completed_models": entries})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    run(parser.parse_args().protocol)
