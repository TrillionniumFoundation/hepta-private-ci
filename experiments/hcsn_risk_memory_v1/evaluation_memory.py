"""Label-free evaluation-shape memory check using only repeated train inputs."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .train_equivalence import ROOT, PACKAGE, UPSTREAM, GIB, sha, verify, write, memory, utc


def worker(output, task, arm):
    import numpy as np
    import torch
    from experiments.hcsn_free_boundary_v1 import training
    from .model import build_model

    torch.set_num_threads(1)
    output.mkdir(parents=True, exist_ok=False)
    protocol = json.loads(UPSTREAM.read_bytes())
    source = ROOT / protocol["data"][task]["path"]
    # Intentionally do not call load_split: no label array is accessed here.
    with np.load(source, allow_pickle=False) as archive:
        x = torch.from_numpy(np.array(archive["train_x"], copy=True)).float()
        dt = torch.from_numpy(np.array(archive["train_dt"], copy=True)).float()
    model = build_model(arm, x.shape[-1], protocol["data"][task]["output_dim"], seed=9401)
    prior = PACKAGE / "results/train_preflight001/runs" / f"{task}__{arm}__9401__backward_vector/raw_arrays.npz"
    with np.load(prior, allow_pickle=False) as archive:
        state = {name.removeprefix("state3::"): torch.from_numpy(np.array(archive[name], copy=True))
                 for name in archive.files if name.startswith("state3::")}
    model.load_state_dict(state, strict=True)
    model.eval()
    cases, arrays = [], {}
    with torch.no_grad():
        for label, repeats, batches in (("validation_shape", 1, 2), ("ood_shape", 2, 4)):
            retained = []
            for index in range(batches):
                indices = torch.arange(index * 128, (index + 1) * 128) % x.shape[0]
                inputs = x[indices].repeat(1, repeats, 1)
                duration = dt[indices].repeat(1, repeats)
                started = time.process_time()
                logits, aux = model(inputs, duration, return_sequence=True)
                cpu = time.process_time() - started
                if not bool(torch.isfinite(logits).all()):
                    raise FloatingPointError("Nonfinite label-free logits")
                max_mass = max(float((layer["flow_mass"] - 1).abs().max()) for layer in aux["layers"])
                if max_mass > 1e-6:
                    raise FloatingPointError("Label-free probability mass error")
                retained.append(logits.numpy())
                arrays[f"{label}_{index}_logits"] = logits.numpy().copy()
                cases.append(dict(shape=label, batch=index, x_shape=list(inputs.shape),
                    forward_cpu_seconds=cpu, maximum_mass_error=max_mass,
                    maximum_absolute_logit=float(logits.abs().max()),
                    process_peak_rss_bytes=training._peak_rss_bytes()))
            all_logits = np.concatenate(retained)
            arrays[label + "_concatenated_logits"] = all_logits
    raw = output / "raw_label_free_logits.npz"
    np.savez_compressed(raw, **arrays)
    write(output / "RESULT.json", dict(status="completed", task=task, model=arm, seed=9401,
        input_arrays_loaded=["train_x", "train_dt"], label_arrays_loaded=[], heldout_arrays_loaded=[],
        parameter_source=str(prior.relative_to(ROOT)), parameter_source_sha256=sha(prior),
        parameter_update=3, cases=cases, raw_sha256=sha(raw),
        process_peak_rss_bytes=training._peak_rss_bytes(),
        scope="train inputs repeated to actual B128/T32 validation and B128/T64 OOD shapes; not heldout evaluation"))


def run(output):
    upstream = json.loads(UPSTREAM.read_bytes())
    verify(upstream)
    train_result = PACKAGE / "results/train_preflight001/RESULTS.json"
    prior = json.loads(train_result.read_bytes())
    if not prior["passed"]:
        raise RuntimeError("Training preflight must pass")
    sources = dict(prior["source_files_sha256"])
    sources[str(Path(__file__).relative_to(ROOT))] = sha(Path(__file__))
    jobs = [dict(task=task, model=arm) for task in ("selective_copy", "mqar") for arm in upstream["models"]]
    registration = dict(schema="hcsn-risk-label-free-evaluation-memory.v1", registered_utc=utc(),
        source_files_sha256=sources, data=upstream["data"], jobs=jobs,
        prior_three_update_train_preflight_sha256=sha(train_result),
        inputs="only train_x and train_dt; no labels, validation, test or OOD arrays loaded",
        parameter_state="new profile state_dict after the already recorded third train-only Adam update",
        validation_shape=dict(batch_size=128, length=32, batches=2),
        ood_shape=dict(batch_size=128, length=64, batches=4, repeat_training_length=2),
        source_of_shapes="frozen datasets.synthetic call in datasets.py; frozen content_study.evaluate batch_size128",
        peak_rss_acceptance_bytes=int(1.1 * GIB), workers=1,
        launch_required_headroom_bytes=int(1.3 * GIB) + 2 * GIB,
        cost="complete isolated wait4 CPU and RSS; raw logits retained; no predictive-quality measure")
    verify(registration)
    output.mkdir(parents=True, exist_ok=False)
    write(output / "REGISTRATION.json", registration)
    (output / "evaluation_memory_snapshot.py").write_bytes(Path(__file__).read_bytes())
    (output / "runs").mkdir()
    (output / "process_logs").mkdir()
    records = []
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    for job in jobs:
        while True:
            before = memory()
            if before["estimated_headroom_bytes"] >= registration["launch_required_headroom_bytes"]:
                break
            write(output / "WAITING_FOR_MEMORY.json", before)
            time.sleep(10)
        name = job["task"] + "__" + job["model"]
        folder, log = output / "runs" / name, output / "process_logs" / (name + ".log")
        command = [sys.executable, "-m", "experiments.hcsn_risk_memory_v1.evaluation_memory", "worker",
                   "--output", str(folder), "--task", job["task"], "--model", job["model"]]
        launched = time.perf_counter()
        with log.open("x") as stream:
            process = subprocess.Popen(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
            got, status, usage = os.wait4(process.pid, 0)
            if got != process.pid:
                raise RuntimeError("Unexpected child")
            code = os.waitstatus_to_exitcode(status)
            process.returncode = code
        after = memory()
        receipt = dict(job=job, command=command, returncode=code, stdout_sha256=sha(log),
            child_user_cpu_seconds=usage.ru_utime, child_system_cpu_seconds=usage.ru_stime,
            child_total_cpu_seconds=usage.ru_utime + usage.ru_stime,
            child_peak_rss_kib_linux=usage.ru_maxrss, wall_seconds=time.perf_counter() - launched,
            resources_before=before, resources_after=after)
        records.append(receipt)
        write(output / "PROGRESS.json", dict(records=records, expected=len(jobs)))
        folder.mkdir(exist_ok=True)
        write(folder / "EXECUTION.json", receipt)
        print(json.dumps(dict(completed=len(records), expected=len(jobs), job=job,
                              returncode=code, peak_rss_kib=usage.ru_maxrss)), flush=True)
        if code != 0 or before["events"]["oom_kill"] != after["events"]["oom_kill"]:
            write(output / "ABORTED.json", dict(records=records, expected=len(jobs), unstarted=jobs[len(records):]))
            raise RuntimeError("Label-free shape preflight aborted")
    verify(registration)
    passed = all(row["child_peak_rss_kib_linux"] * 1024 <= registration["peak_rss_acceptance_bytes"] for row in records)
    result = dict(schema="hcsn-risk-label-free-evaluation-memory-results.v1", passed=passed,
        records=records, expected=len(jobs), completed=len(records),
        maximum_child_peak_rss_bytes=max(row["child_peak_rss_kib_linux"] * 1024 for row in records),
        acceptance_bytes=registration["peak_rss_acceptance_bytes"],
        complete_child_cpu_seconds=sum(row["child_total_cpu_seconds"] for row in records),
        coordinator_cpu_seconds=time.process_time() - start_cpu, wall_seconds=time.perf_counter() - start_wall,
        registration_sha256=sha(output / "REGISTRATION.json"), labels_loaded=False, heldout_loaded=False,
        source_files_sha256=sources)
    write(output / "RESULTS.json", result)
    if not passed:
        raise RuntimeError("1.1 GiB evaluation-shape memory goal failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "worker"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task")
    parser.add_argument("--model")
    args = parser.parse_args()
    if args.action == "run":
        run(args.output.resolve())
    else:
        worker(args.output.resolve(), args.task, args.model)
