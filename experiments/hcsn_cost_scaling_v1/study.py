"""Registered small-scale CPU training and quality-conditioned timing.

Nothing in the frozen CONTENT002 protocol is changed. All experiments here
are explicitly post-baseline, exploratory and CPU-only. A quality comparison
requires the predeclared validation AND test gates, at each paired seed.
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import random
import resource
import shutil
import statistics
import subprocess
import sys
import time
import traceback


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = Path(__file__).resolve().parent
PARENT = ROOT / "experiments/hcsn_distributional_v2/CONTENT002_PROTOCOL.json"
MODELS = ("distribution_free_dual", "two_gates", "lif_snn", "transformer")
SCALES = ((16, 1), (32, 1), (64, 2))
TASKS = ("selective_copy", "mqar")
SEEDS = (9301, 9302, 9303)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temp.replace(path)


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def environment():
    import torch
    result = dict(python=sys.version, torch=torch.__version__, cpu_count=os.cpu_count(),
                  cuda_available=torch.cuda.is_available(), device="cpu",
                  gpu_memory_measured=False, energy_measured=False,
                  dedicated_host=False, wall_time_scope="shared host, contention uncontrolled")
    for name in ("cpu.max", "memory.max", "memory.current", "memory.events"):
        p = Path("/sys/fs/cgroup") / name
        if p.exists():
            result[name] = p.read_text().strip()
    return result


def factory(name, input_dim, output_dim, width=32, depth=1, seed=0):
    from experiments.hcsn_distributional_v2.model import MatchedClassifier, build_model
    if name == "lif_snn":
        return MatchedClassifier(name, input_dim, output_dim, width, depth, seed)
    return build_model(name, input_dim, output_dim, width, depth, seed)


def source_map():
    sources = dict(read(PARENT)["source_files_sha256"])
    for name in ("__init__.py", "study.py", "analyze.py"):
        path = PACKAGE / name
        sources[str(path.relative_to(ROOT))] = digest(path)
    return sources


def verify(protocol):
    p = read(protocol)
    for key in ("parent", "preflight"):
        if digest(ROOT / p[key]["path"]) != p[key]["sha256"]:
            raise RuntimeError("Registration dependency mismatch: " + key)
    for relative, expected in p["source_files_sha256"].items():
        if digest(ROOT / relative) != expected:
            raise RuntimeError("Source identity mismatch: " + relative)
    for item in p["data"].values():
        if digest(ROOT / item["path"]) != item["sha256"]:
            raise RuntimeError("Data identity mismatch: " + item["path"])
    return p


def preflight(output):
    started_cpu, started_wall = time.process_time(), time.perf_counter()
    import torch
    from torch.nn import functional as F
    from experiments.hcsn_free_boundary_v1 import training
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    parent = read(PARENT)
    sources = source_map()
    train = training.load_split(ROOT / parent["data"]["selective_copy"]["path"], "train")
    rows = []
    for width, depth in SCALES:
        reference = factory("distribution_free_dual", 64, 8, width, depth, SEEDS[0])
        reference_count = reference.counts()["backbone"]
        common = {name: value.clone() for name, value in reference.state_dict().items()
                  if name.startswith(("frontend.", "readout."))}
        del reference
        for name in MODELS:
            model = factory(name, 64, 8, width, depth, SEEDS[0])
            counts = model.counts()
            gap = abs(counts["backbone"] - reference_count) / reference_count
            if gap > .035:
                raise AssertionError("Backbone parameter gap exceeds 3.5%")
            if not all(torch.equal(value, model.state_dict()[key]) for key, value in common.items()):
                raise AssertionError("Common frontend/readout initialization changed")
            logits, aux = model(train["x"][:4], train["dt"][:4], return_sequence=True)
            loss = F.cross_entropy(logits.flatten(0, 1), train["y"][:4].flatten(), ignore_index=-100)
            loss.backward()
            gradients = training._gradient_summary(model)
            if not all(row["finite"] and row["l2"] > 0 for row in gradients.values()):
                raise AssertionError("Missing effective or finite training gradient")
            physical_gradients = {}
            if name == "lif_snn":
                for parameter_name, parameter in model.named_parameters():
                    if parameter_name.endswith(("log_rate", "raw_threshold")):
                        g = parameter.grad
                        if g is None or not bool(torch.isfinite(g).all()) or float(g.abs().max()) == 0:
                            raise AssertionError("LIF physical parameter lacks effective gradient")
                        physical_gradients[parameter_name] = float(g.abs().max())
            rows.append(dict(model=name, width=width, depth=depth, counts=counts,
                             relative_backbone_gap=gap, loss=float(loss.detach()),
                             gradients=gradients, lif_physical_gradient_max=physical_gradients,
                             common_initialization_identical=True))
            write(output / "PROGRESS.json", dict(rows=rows, source_files_sha256=sources))
            del model, logits, aux, loss
    write(output / "PREFLIGHT.json", dict(schema="hcsn-cost-scale-preflight.v1", passed=True,
          train_only=True, rows=rows, source_files_sha256=sources, environment=environment(),
          cpu_seconds=time.process_time()-started_cpu, wall_seconds=time.perf_counter()-started_wall))


def register(protocol, output, preflight_path):
    parent, preflight_record = read(PARENT), read(preflight_path)
    if not preflight_record["passed"] or preflight_record["source_files_sha256"] != source_map():
        raise RuntimeError("Preflight source identity mismatch")
    jobs = [dict(task=task, model=model, width=width, depth=depth, seed=seed)
            for task in TASKS for model in MODELS for width, depth in SCALES for seed in SEEDS]
    random.Random(2026103006).shuffle(jobs)
    p = dict(schema="hcsn-cpu-scale-protocol.v1", registered_utc=utc(),
        interpretation="Post-baseline exploratory extension on previously observed tasks; not fresh-test confirmation or LLM scale",
        source_files_sha256=source_map(), data={name: parent["data"][name] for name in TASKS},
        parent=dict(path=str(PARENT.relative_to(ROOT)), sha256=digest(PARENT)),
        preflight=dict(path=str(Path(preflight_path).resolve().relative_to(ROOT)), sha256=digest(preflight_path)),
        jobs=jobs, optimization=dict(training_cpu_seconds=20., learning_rates=[.001], batch_size=32,
            max_updates=65536, primary_cpu_checkpoints=[15., 20.], loss="task cross entropy only",
            selection="minimum validation CE at common CPU gates; fixed128 snapshot is not selection eligible",
            physical_channels_per_layer=8, grid_cells=8, refractory_phases=2,
            backbone_matching_tolerance=.035,
            matching_design_history="Initial train-only preflight failed inherited3percent gate: width16 Transformer nearest discrete architecture is3.08333percent larger. Retain power-of-two scales, freeze3.5percent cap and disclose all exact counts before heldout."),
        quality=dict(targets=[.5, .75, .9], operating_point="earliest primary CPU checkpoint reaching validation target",
            heldout_rule="all operating points fixed before loading test; both model test accuracies must reach the same target",
            paired_test_accuracy_tolerance=.02, aggregate_gate="all three paired seeds qualify; otherwise incomplete",
            failure="no interpolation, extrapolation, extra training or replacement seeds"),
        timing=dict(batches=[1, 32], warmups=1, repetitions=5, length=32,
            scope="complete full-sequence inference from predecoded in-memory features; includes boundary and analytic/grid computation",
            excludes="media decoding, accelerator transfer, cached autoregressive decoding; no energy or GPU claims",
            primary_cost="whole isolated worker wait4 CPU including imports, setup, validation, I/O, timing and heldout",
            memory="whole-process peak RSS, not model-only allocation"),
        execution=dict(workers=1, expected=len(jobs), nominal_training_cpu_seconds=20 * len(jobs),
            stop_policy="failure or STOP_REQUESTED stops new scheduling, active worker cost preserved"))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write(protocol, p)
    write(output / "REGISTRATION.json", dict(protocol_sha256=digest(protocol), registered_utc=p["registered_utc"]))
    print(json.dumps(p["execution"]), flush=True)


def benchmark(model, split, protocol):
    import torch
    model.eval()
    records = []
    for batch in protocol["timing"]["batches"]:
        x, dt = split["x"][:batch], split["dt"][:batch]
        if x.shape[0] != batch or x.shape[1] != protocol["timing"]["length"]:
            raise AssertionError("Timing input shape mismatch")
        measurements, hashes = [], []
        with torch.inference_mode():
            for repeat in range(protocol["timing"]["warmups"] + protocol["timing"]["repetitions"]):
                cpu, wall = time.process_time(), time.perf_counter()
                logits = model(x, dt, return_sequence=True, return_aux=False)
                item = dict(cpu_seconds=time.process_time() - cpu,
                            wall_seconds=time.perf_counter() - wall)
                if not bool(torch.isfinite(logits).all()):
                    raise FloatingPointError("Nonfinite benchmark logits")
                hashes.append(hashlib.sha256(logits.cpu().numpy().tobytes()).hexdigest())
                if repeat >= protocol["timing"]["warmups"]:
                    measurements.append(item)
        if len(set(hashes)) != 1:
            raise AssertionError("Evaluation was not deterministic")
        median_cpu = statistics.median(x["cpu_seconds"] for x in measurements)
        median_wall = statistics.median(x["wall_seconds"] for x in measurements)
        records.append(dict(batch=batch, length=x.shape[1], raw=measurements,
            median_cpu_seconds=median_cpu, median_wall_seconds=median_wall,
            sequences_per_cpu_second=batch / median_cpu, sequences_per_wall_second=batch / median_wall,
            tokens_per_cpu_second=batch * x.shape[1] / median_cpu, output_sha256=hashes[0]))
    return records


def worker(protocol, output, job_index):
    import torch
    from experiments.hcsn_free_boundary_v1 import training
    from experiments.hcsn_distributional_v2 import content_training
    from experiments.hcsn_distributional_v2.content_study import evaluate
    p = verify(protocol)
    job, output = p["jobs"][job_index], Path(output)
    content_training.build_model = factory
    training.evaluate = evaluate
    torch.set_num_threads(1)
    opt = p["optimization"]
    output.mkdir(parents=True, exist_ok=False)
    process_start, wall_start = time.process_time(), time.perf_counter()
    data_path = ROOT / p["data"][job["task"]]["path"]
    accesses = []
    write(output / "request.json", dict(job=job, optimization=opt, protocol_sha256=digest(protocol)))
    train = training.load_split(data_path, "train", accesses)
    val = training.load_split(data_path, "val", accesses)
    candidate = content_training.train_candidate(train, val, job["model"], job["seed"],
        opt["learning_rates"][0], output / "candidate", opt["training_cpu_seconds"],
        job["width"], job["depth"], opt["batch_size"], opt["max_updates"])
    candidate["directory"] = "candidate"
    selection = dict(rule="minimum validation CE among primary CPU gates only", completed_lr_candidates=1,
        selected_checkpoint_sha256=candidate["best"]["sha256"], selected_step=candidate["best"]["step"],
        selected_validation=candidate["best"]["validation"], selected_learning_rate=opt["learning_rates"][0],
        dataset_sha256=digest(data_path))
    write(output / "selection.json", selection)
    shutil.copyfile(output / "candidate" / candidate["best"]["weights"], output / "selected.npz")
    points = [c for c in candidate["checkpoints"] if c["primary_eligible"]]
    point_selection = []
    for target in p["quality"]["targets"]:
        eligible = [c for c in points if c["validation"]["accuracy"] >= target]
        point = min(eligible, key=lambda c: (c["training_cpu_seconds"], c["step"])) if eligible else None
        point_selection.append(dict(target=target, checkpoint=point))
    write(output / "QUALITY_SELECTION.json", dict(rule=p["quality"], points=point_selection,
          selection_sha256=digest(output / "selection.json"), no_quality_test_scores_used_for_selection=True))
    accesses.append(dict(event="selected_and_quality_operating_points_locked", utc=utc()))
    if digest(data_path) != p["data"][job["task"]]["sha256"]:
        raise RuntimeError("Data changed before heldout access")
    test = training.load_split(data_path, "test", accesses)
    model = factory(job["model"], train["x"].shape[-1], p["data"][job["task"]]["output_dim"],
                    job["width"], job["depth"], job["seed"])
    unique = {selection["selected_checkpoint_sha256"]: output / "selected.npz"}
    for row in point_selection:
        if row["checkpoint"]:
            c = row["checkpoint"]
            unique[c["sha256"]] = output / candidate["directory"] / c["weights"]
    evaluations = {}
    for sha, checkpoint in unique.items():
        if digest(checkpoint) != sha:
            raise RuntimeError("Checkpoint identity mismatch")
        training.load_weights(checkpoint, model)
        prediction_path = output / ("quality_" + sha[:16] + ".npz")
        metrics = evaluate(model, test, output_path=prediction_path)
        evaluations[sha] = dict(test=metrics, predictions=prediction_path.name,
            predictions_sha256=digest(prediction_path), timing=benchmark(model, test, p))
    training.load_weights(output / "selected.npz", model)
    ood = training.load_split(data_path, "ood", accesses)
    ood_metrics = evaluate(model, ood, output_path=output / "ood_predictions.npz") if ood else None
    verify(protocol)
    selected_metrics = evaluations[selection["selected_checkpoint_sha256"]]["test"]
    summary = dict(status="completed", request=dict(job=job, optimization=opt), candidates=[candidate],
        selection=selection, selected_model_config=model.config, counts=model.counts(),
        holdout=dict(test=selected_metrics, ood=ood_metrics), access_log=accesses,
        total_cpu_seconds=time.process_time()-process_start, total_wall_seconds=time.perf_counter()-wall_start,
        memory_measurement="whole process peak RSS; not isolated model allocation", energy_measured=False)
    write(output / "summary.json", summary)
    write(output / "COST.json", dict(schema="hcsn-trained-cpu-cost.v1", job=job,
        protocol_sha256=digest(protocol), quality_selection=point_selection, evaluations=evaluations,
        selected_checkpoint_sha256=selection["selected_checkpoint_sha256"],
        process_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        counts=model.counts(), environment=environment(), test_accesses=accesses))


def run(protocol, output):
    p, output = verify(protocol), Path(output)
    if read(output / "REGISTRATION.json")["protocol_sha256"] != digest(protocol):
        raise RuntimeError("Registration mismatch")
    (output / "runs").mkdir()
    (output / "logs").mkdir()
    records = []
    started, started_cpu = time.perf_counter(), time.process_time()
    env = dict(os.environ, OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
               NUMEXPR_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1")
    for i, job in enumerate(p["jobs"]):
        if (output / "STOP_REQUESTED.json").exists():
            break
        name = f"{job['task']}__{job['model']}__w{job['width']}d{job['depth']}__{job['seed']}"
        command = [sys.executable, "-m", "experiments.hcsn_cost_scaling_v1.study", "worker",
                   "--protocol", str(Path(protocol).resolve()), "--output", str((output / "runs" / name).resolve()),
                   "--job-index", str(i)]
        wall = time.perf_counter()
        with (output / "logs" / (name + ".log")).open("xb") as log:
            child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=env, cwd=ROOT)
            _, status, usage = os.wait4(child.pid, 0)
            code = os.waitstatus_to_exitcode(status)
            child.returncode = code
        record = dict(job=job, command=command, returncode=code, wall_seconds=time.perf_counter()-wall,
                      whole_worker_cpu_seconds=usage.ru_utime+usage.ru_stime,
                      peak_rss_bytes=usage.ru_maxrss*1024, directory="runs/"+name)
        records.append(record)
        write(output / "PROGRESS.json", dict(completed=len(records), expected=len(p["jobs"]), records=records))
        (output / "runs" / name).mkdir(parents=True, exist_ok=True)
        write(output / "runs" / name / "EXECUTION.json", record)
        print(json.dumps({k:v for k,v in record.items() if k not in ("command",)}), flush=True)
        if code:
            break
    complete = len(records) == len(p["jobs"]) and all(r["returncode"] == 0 for r in records)
    write(output / ("COMPLETE.json" if complete else "ABORTED.json"), dict(completed=complete,
          protocol_sha256=digest(protocol), records=records, expected=len(p["jobs"]),
          complete_child_cpu_seconds=sum(x["whole_worker_cpu_seconds"] for x in records),
          coordinator_cpu_seconds=time.process_time()-started_cpu,
          wall_seconds=time.perf_counter()-started, unstarted=p["jobs"][len(records):]))
    if not complete:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("preflight", "register", "run", "worker"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=PACKAGE / "PROTOCOL.json")
    parser.add_argument("--preflight", type=Path)
    parser.add_argument("--job-index", type=int)
    a = parser.parse_args()
    if a.action == "preflight":
        preflight(a.output)
    elif a.action == "register":
        register(a.protocol, a.output, a.preflight)
    elif a.action == "worker":
        try:
            worker(a.protocol, a.output, a.job_index)
        except Exception:
            a.output.mkdir(parents=True, exist_ok=True)
            write(a.output / "WORKER_FAILURE.json", dict(traceback=traceback.format_exc()))
            raise
    else:
        run(a.protocol, a.output)


if __name__ == "__main__":
    main()
