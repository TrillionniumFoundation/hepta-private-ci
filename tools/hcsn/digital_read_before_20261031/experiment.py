"""Complete-cohort native confirmation, admitted only after remote model freeze."""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import time

import numpy as np

from .data import cohort
from .deploy import Policy, run_python
from .metrics import episode_metrics, summarize
from .task import ContentAdapter, fixed_action, legal, save, sha, successor

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def json_gzip(path, value):
    payload = json.dumps(value, separators=(",", ":"), sort_keys=True, allow_nan=False).encode()+b"\n"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:
        f.write(gzip.compress(payload, compresslevel=9, mtime=0))
    return dict(path=str(path), sha256=sha(path), bytes=path.stat().st_size,
                uncompressed_bytes=len(payload), uncompressed_sha256=hashlib.sha256(payload).hexdigest())


def load_frozen_models(freeze, cache):
    models = {}
    for record in freeze["models"]:
        encoded = (REPO/record["path"]).read_bytes()
        if hashlib.sha256(encoded).hexdigest() != record["sha256"]:
            raise ValueError("encoded checkpoint hash mismatch")
        raw = gzip.decompress(encoded)
        if hashlib.sha256(raw).hexdigest() != record["model_sha256"]:
            raise ValueError("model content hash mismatch")
        artifact = json.loads(raw)
        key = (artifact["fit"], artifact["family"])
        if key in models:
            raise ValueError("duplicate frozen model")
        destination = cache/f"{key[0]}_{key[1]}.json"
        with destination.open("xb") as f:
            f.write(raw)
        models[key] = (destination, artifact)
    return models


def _same_state(actual, expected):
    a, b = dict(actual), dict(expected)
    for key in ("elapsed", "charges"):
        if abs(a.pop(key)-b.pop(key)) > 2e-12:
            raise AssertionError("native/Python task clock or fee mismatch")
    if a != b:
        raise AssertionError("native/Python complete task state mismatch")


def normalize_native(result, policy, public, controller, external_wall, external_cpu):
    if not result["actual_native"] or result["production_activation"]:
        raise AssertionError("unexpected native execution identity")
    rows, maximum_score_error = [], 0.
    for receipt in result["receipts"]:
        if receipt["forced_control"]:
            raise AssertionError("forced qualification action in formal confirmation")
        before, after = receipt["before"], receipt["after"]
        index = receipt["cell_before"]["index"]
        scores = policy.predict(public, before, index)
        error = max(np.max(np.abs(np.asarray(scores["q"])-receipt["q"])), abs(scores["belief"]-receipt["belief"]))
        maximum_score_error = max(maximum_score_error, float(error))
        if error > 5e-12:
            raise AssertionError("native/Python frozen score mismatch")
        mask = legal(public, before)
        action = (fixed_action(before, mask, scores["belief"]) if controller == "fixed" else
                  int(np.argmax(np.where(mask, scores["q"], -np.inf))))
        if action != receipt["action"]:
            raise AssertionError("native/Python selected action mismatch")
        _same_state(after, successor(public, before, action, receipt["completion"]))
        rng = int(receipt["cell_before"]["rng_hex"], 16)
        event = dict(event=False, recovery=False, probability=0., sampled=False)
        new_index, new_rng = index, rng
        if action not in (0, 4, 5):
            new_index, new_rng, event = policy.advance(public, before, index, rng)
        if new_index != receipt["cell_after"]["index"] or new_rng != int(receipt["cell_after"]["rng_hex"], 16):
            raise AssertionError("native/Python hard cell/RNG successor mismatch")
        draw = receipt["draw"]
        if event["sampled"] != (draw is not None):
            raise AssertionError("native draw count mismatch")
        if draw is not None and (event["event"] != draw["event"] or abs(event["probability"]-draw["probability_of_event"]) > 1e-12):
            raise AssertionError("native event contract mismatch")
        rows.append(dict(before=before, after=after, action=action, q=receipt["q"],
                         belief=receipt["belief"], event=event, completion=receipt["completion"],
                         content=receipt["content"], native_receipt=receipt))
    _same_state(result["after"]["task"], rows[-1]["after"])
    return dict(schema="digital-read-before-episode-v1", backend="native",
                decisions=rows, final_state=result["after"]["task"],
                wall_seconds=external_wall, cpu_seconds=external_cpu,
                native_wall_seconds=result["wall_nanos"]/1e9, native_cpu_seconds=result["cpu_nanos"]/1e9,
                persistence_bytes=result["persistence_bytes"], maximum_python_score_error=maximum_score_error,
                acknowledged_sha256=result["acknowledged_sha256"], source_digest=result["source_digest"])


def native_episode(binary, content_model, model_path, artifact, public_path, controller, snapshot, seed):
    public = json.loads(public_path.read_text())
    command = [str(binary), "--public", str(public_path), "--content-model", str(content_model),
               "--policy", str(model_path), "--controller", controller, "--snapshot", str(snapshot),
               "--seed", str(seed), "--steps", "7"]
    cpu0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    wall0 = time.perf_counter()
    process = subprocess.run(command, capture_output=True, text=True, timeout=60)
    wall = time.perf_counter()-wall0
    cpu1 = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = cpu1.ru_utime+cpu1.ru_stime-cpu0.ru_utime-cpu0.ru_stime
    if process.returncode != 0:
        save(snapshot.with_suffix(".FAILED.json"), dict(command=command, returncode=process.returncode,
                                                     stdout=process.stdout, stderr=process.stderr))
        raise RuntimeError("native formal episode failed; raw failure retained")
    output = json.loads(process.stdout)
    episode = normalize_native(output, Policy(artifact), public, controller, wall, cpu)
    episode["command"] = command
    episode["native_output"] = output
    return episode


def confirm(binary, runs, training, model_freeze_path, confirmation_commit):
    """Caller records a verified remote model commit before this creates worlds."""
    if len(confirmation_commit) != 40 or set(confirmation_commit)-set("0123456789abcdef"):
        raise ValueError("published model freeze commit required")
    protocol = json.loads((HERE/"protocol.json").read_text())
    freeze = json.loads(Path(model_freeze_path).read_text())
    for relative, digest in freeze["source_sha256"].items():
        if sha(REPO/relative) != digest:
            raise ValueError(("confirmation source changed", relative))
    runs, training = Path(runs).resolve(), Path(training).resolve()
    runs.mkdir(parents=True, exist_ok=False)
    save(runs/"STARTED.json", dict(started_at=datetime.now(timezone.utc).isoformat(),
                                 published_model_commit=confirmation_commit,
                                 model_freeze_sha256=sha(model_freeze_path),
                                 binary_sha256=sha(binary), confirmation_worlds_preexisting=False))
    cache = runs/"models"
    cache.mkdir()
    models = load_frozen_models(freeze, cache)
    if set(models) != {(fit, family) for fit in protocol["fits"] for family in protocol["families"]}:
        raise ValueError("complete 25-model freeze required")
    content_model = REPO/"tools/hcsn/round9_20261031/native/fixtures/fullhx.json"
    adapter = ContentAdapter()
    results, cohort_identities = [], []
    for fit in protocol["fits"]:
        data_path = training/f"fit_{fit}"/"data"/f"fit_{fit}_data.json"
        data = json.loads(data_path.read_text())
        if sha(data_path) != freeze["training_data_sha256"][str(fit)]:
            raise ValueError("TRAIN-calibration/data identity changed")
        confusion = np.asarray(data["confusion"])
        for split_index, split in enumerate(("iid", "ood")):
            generated = cohort(runs/"worlds", split, fit, protocol[f"{split}_worlds"], protocol)
            cohort_identities.append(generated)
            save(runs/f"cohort_{fit}_{split}.json", generated)
            for family in protocol["families"]+[protocol["reference_family"]]:
                for controller in protocol["controllers"]:
                    records = []
                    for index, world in enumerate(generated["records"]):
                        folder = Path(world["folder"])
                        public_path = folder/"public.json"
                        public = json.loads(public_path.read_text())
                        seed = 830000000 + fit*100000 + split_index*10000+index
                        if family == protocol["reference_family"]:
                            episode = run_python(public, folder, adapter, None, controller, seed, confusion)
                        else:
                            model_path, artifact = models[(fit, family)]
                            snapshots = runs/"snapshots"/f"{fit}_{split}_{family}_{controller}"
                            snapshots.mkdir(parents=True, exist_ok=True)
                            episode = native_episode(binary, content_model, model_path, artifact, public_path,
                                                     controller, snapshots/f"{index}.json", seed)
                        label = json.loads((folder/"evaluator.json").read_text())["label"]
                        metrics = episode_metrics(public, episode, label, confusion)
                        if family != protocol["reference_family"]:
                            metrics.update(native_wall_seconds=episode["native_wall_seconds"],
                                           native_cpu_seconds=episode["native_cpu_seconds"],
                                           persistence_bytes=episode["persistence_bytes"],
                                           maximum_python_score_error=episode["maximum_python_score_error"],
                                           content_calls=sum(r["native_receipt"]["actual_content_calls"] for r in episode["decisions"]))
                        row = dict(fit=fit, split=split, family=family, controller=controller,
                                   world=world["id"], seed=seed, forced=False, metrics=metrics)
                        results.append(row)
                        records.append(dict(**row, episode=episode))
                    json_gzip(runs/"raw"/f"{fit}_{split}_{family}_{controller}.json.gz", records)
                    print(json.dumps(dict(stage="confirmation", fit=fit, split=split, family=family,
                                          controller=controller, episodes=len(records), mean_utility=float(np.mean([r["metrics"]["utility"] for r in records])))), flush=True)
    summary = summarize(results, protocol)
    summary.update(published_model_commit=confirmation_commit, binary_sha256=sha(binary),
                   content_setup=adapter.setup, cohort_count=len(cohort_identities))
    save(runs/"RESULTS.json", results)
    save(runs/"SUMMARY.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--training", type=Path, required=True)
    parser.add_argument("--model-freeze", type=Path, default=HERE/"MODEL_FREEZE.json")
    parser.add_argument("--published-model-commit", required=True)
    args = parser.parse_args()
    confirm(args.binary.resolve(), args.runs, args.training, args.model_freeze, args.published_model_commit)


if __name__ == "__main__":
    main()
