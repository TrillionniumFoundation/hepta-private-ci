"""Source-bound audiovisual tuning, paired training, and complete worker costs."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
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

import numpy as np

from ..content import study as common
from .metrics import evaluation_arrays, retrieval_ranks, derangement


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MODULE = "experiments.hcsn_blocker_closure_v1.av.study"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_map():
    paths = list(HERE.glob("*.py"))+[HERE/"AV_DESIGN.json", HERE/"COHORT_PLAN.json"]
    paths.append(ROOT/"experiments/hcsn_real_av_v1/data.py")
    return dict(common.source_map(), **{str(path.relative_to(ROOT)): digest(path) for path in sorted(paths)})


def write(path, value):
    common.write(path, value)


def read(path):
    return common.read(path)


def durable(path):
    with Path(path).open("rb") as stream:
        os.fsync(stream.fileno())
    directory = os.open(str(Path(path).parent), os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def register(output, dataset, data_commit, data_transport_path, preflight):
    output, dataset = Path(output).resolve(), Path(dataset).resolve()
    output.relative_to(HERE.parent)
    design = read(HERE/"AV_DESIGN.json")
    declared_binding = design["data_binding"]
    if data_commit != declared_binding["commit"] or data_transport_path != declared_binding["transport_path"]:
        raise ValueError("Data execution evidence differs from the immutable predeclared cohort")
    if len(data_commit) != 40 or any(letter not in "0123456789abcdef" for letter in data_commit):
        raise ValueError("An immutable data evidence commit is required")
    transport_path = Path(data_transport_path)
    if transport_path.is_absolute() or ".." in transport_path.parts or transport_path.name != "TRANSPORT.json":
        raise ValueError("A repository-relative committed transport manifest is required")
    locator = data_commit+":"+transport_path.as_posix()
    transport_bytes = subprocess.check_output(["git", "show", locator], cwd=ROOT)
    git_blob = subprocess.check_output(["git", "rev-parse", locator], cwd=ROOT, text=True).strip()
    actual_blob = hashlib.sha1(b"blob "+str(len(transport_bytes)).encode()+b"\0"+transport_bytes).hexdigest()
    if actual_blob != git_blob:
        raise ValueError("Committed transport blob identity mismatch")
    if git_blob != declared_binding["transport_git_blob_sha1"]:
        raise ValueError("Transport Git blob differs from the registered acquisition")
    transport = json.loads(transport_bytes)
    if transport.get("schema") != "hcsn-blocker-av-transport.v1":
        raise ValueError("Unexpected committed data transport contract")
    if (transport["execution_seal"] != declared_binding["acquisition_execution_seal"]
            or digest(dataset) != declared_binding["dataset_sha256"]):
        raise ValueError("Acquisition execution seal or tensor manifest changed")
    expected_files = {row["path"]: row for row in transport["files"]}
    if len(expected_files) != len(transport["files"]) or dataset.name != "DATASET.json":
        raise ValueError("Duplicate transport file or wrong dataset manifest")
    actual_files = {path.name for path in dataset.parent.iterdir() if path.is_file()}
    if actual_files != set(expected_files):
        raise ValueError("Restored data contains missing or unlisted files")
    for filename, row in expected_files.items():
        if Path(filename).name != filename:
            raise ValueError("Unsafe data transport filename")
        path = dataset.parent/filename
        if path.is_symlink() or path.stat().st_size != row["bytes"] or digest(path) != row["sha256"]:
            raise ValueError("Restored data does not match the immutable committed transport: "+filename)
    proof, plan = read(preflight), read(HERE/"COHORT_PLAN.json")
    if proof.get("passed") is not True or proof.get("source_sha256") != source_map():
        raise ValueError("Passing source-identical synthetic-only AV preflight required")
    inputs = read(dataset)
    if inputs.get("schema") != "hcsn-real-av-tensors-v1" or inputs.get("shape_per_modality") != [32, 128]:
        raise ValueError("Unexpected audiovisual dataset contract")
    if digest(dataset.parent/"COHORT_PLAN.json") != digest(HERE/"COHORT_PLAN.json"):
        raise ValueError("Dataset was not prepared from the sealed fresh cohort")
    manifest = read(dataset.parent/"MANIFEST.json")
    if (inputs["manifest_sha256"] != digest(dataset.parent/"MANIFEST.json")
            or manifest["cohort_plan_sha256"] != digest(HERE/"COHORT_PLAN.json")
            or manifest["commit"] != plan["upstream_commit"]
            or manifest.get("previously_seen_actors") != 0):
        raise ValueError("Data identity or new-actor provenance mismatch")
    for field, filename in (("normalization_sha256", "normalization.npz"),
                            ("decode_receipt_sha256", "DECODE.json")):
        if inputs[field] != digest(dataset.parent/filename):
            raise ValueError("Decoder or normalization identity mismatch")
    if inputs["decoder_sha256"] != digest(ROOT/"experiments/hcsn_real_av_v1/data.py"):
        raise ValueError("The sealed low-level decoder changed")
    for split, row in inputs["splits"].items():
        if split not in design["cohort"]["examples"] or row["examples"] != design["cohort"]["examples"][split]:
            raise ValueError("Registered example count changed")
        if set(row["actors"]) != set(plan["splits"][split]):
            raise ValueError("Registered actor identities changed")
        if Path(row["path"]).name != row["path"] or digest(dataset.parent/row["path"]) != row["sha256"]:
            raise ValueError("Invalid data filename or bytes")
    if set(inputs["splits"]) != {"train", "validation", "test"}:
        raise ValueError("All three registered splits are required")
    audit = read(dataset.parent/"DATA_AUDIT.json")
    if audit.get("passed") is not True or audit.get("dt_override") is not None:
        raise ValueError("Real elapsed-time data audit required")
    output.mkdir(parents=True, exist_ok=False)
    (output/"DATA_TRANSPORT_MANIFEST.json").write_bytes(transport_bytes)
    destination = output/"data"
    destination.mkdir()
    copied = []
    for path in sorted(dataset.parent.iterdir()):
        if path.is_file():
            if path.is_symlink():
                raise ValueError("Symlinked input evidence is not accepted")
            shutil.copyfile(path, destination/path.name)
            copied.append(dict(file=path.name, bytes=path.stat().st_size, sha256=digest(path)))
    protocol = dict(schema="hcsn-blocker-av-protocol.v1", status="registered", created_utc=common.utc(),
        design=design, source_sha256=source_map(), dataset=inputs, input_files=copied,
        dataset_sha256=digest(dataset), data_evidence_commit=data_commit,
        data_evidence_binding=dict(commit=data_commit, transport_path=transport_path.as_posix(),
            transport_git_blob_sha1=git_blob, transport_sha256=hashlib.sha256(transport_bytes).hexdigest(),
            acquisition_execution_seal=transport["execution_seal"], acquisition_run_id=transport["run_id"],
            binding_commands=[["git", "show", locator], ["git", "rev-parse", locator]]),
        public_execution_commit=os.environ.get("GITHUB_SHA"),
        preflight=dict(file=str(Path(preflight).resolve().relative_to(ROOT)), sha256=digest(preflight)),
        raw_test_bytes_hashed_and_copied=True, test_arrays_loaded=False,
        copied_data_scope="Integrity and byte preservation only; no model outcomes exist at registration")
    write(output/"PROTOCOL.json", protocol)
    jobs = [dict(stage="development", arm=arm, seed=design["development_seed"], learning_rate=lr,
                 updates=design["development_updates"], id=f"{arm}__lr{lr:g}")
            for arm in design["models"] for lr in design["learning_rates"]]
    write(output/"jobs_development.json", jobs)
    return dict(protocol_sha256=digest(output/"PROTOCOL.json"), jobs=len(jobs), test_arrays_loaded=False)


def verify(output):
    output = Path(output)
    protocol = read(output/"PROTOCOL.json")
    if protocol["status"] != "registered" or protocol["design"] != read(HERE/"AV_DESIGN.json"):
        raise ValueError("Registered design changed")
    if protocol["source_sha256"] != source_map():
        raise ValueError("Registered source changed")
    if digest(ROOT/protocol["preflight"]["file"]) != protocol["preflight"]["sha256"]:
        raise ValueError("Preflight evidence changed")
    if protocol["public_execution_commit"] is not None and protocol["public_execution_commit"] != os.environ.get("GITHUB_SHA"):
        raise ValueError("Public execution seal changed")
    transport_bytes = (output/"DATA_TRANSPORT_MANIFEST.json").read_bytes()
    binding = protocol["data_evidence_binding"]
    if hashlib.sha256(transport_bytes).hexdigest() != binding["transport_sha256"]:
        raise ValueError("Committed data transport receipt changed")
    if hashlib.sha1(b"blob "+str(len(transport_bytes)).encode()+b"\0"+transport_bytes).hexdigest() != binding["transport_git_blob_sha1"]:
        raise ValueError("Retained data transport Git blob changed")
    transport_files = {row["path"]: row for row in json.loads(transport_bytes)["files"]}
    if set(transport_files) != {row["file"] for row in protocol["input_files"]}:
        raise ValueError("Protocol file list differs from the committed data transport")
    for row in protocol["input_files"]:
        path = output/"data"/row["file"]
        evidence = transport_files[row["file"]]
        if (path.stat().st_size != row["bytes"] or digest(path) != row["sha256"]
                or evidence["bytes"] != row["bytes"] or evidence["sha256"] != row["sha256"]):
            raise ValueError("Dataset or decoder evidence changed")
    return protocol


def load_split(output, protocol, split, job_dir):
    import torch

    if split == "test":
        selected = read(job_dir/"selection.json")
        if selected["state_sha256"] != digest(job_dir/"selected_state.npz"):
            raise ValueError("Heldout access requires the durable selected checkpoint")
        if not (output/"SELECTION_LOCK.json").exists():
            raise ValueError("All model learning rates must be locked before heldout access")
    row = protocol["dataset"]["splits"][split]
    path = output/"data"/row["path"]
    if digest(path) != row["sha256"]:
        raise ValueError("Split checksum changed")
    with (job_dir/"access.jsonl").open("a") as stream:
        stream.write(json.dumps(dict(split=split, utc=common.utc(), sha256=row["sha256"],
                                    durable_selection_exists=(job_dir/"selection.json").exists()))+"\n")
        stream.flush()
        os.fsync(stream.fileno())
    with np.load(path, allow_pickle=False) as saved:
        values = {key: np.array(saved[key], copy=True) for key in saved.files}
    if set(values) != {"audio", "video", "dt", "y", "actor", "clip"}:
        raise ValueError("Unexpected audiovisual tensor fields")
    expected = (row["examples"], 32, 128)
    if values["audio"].shape != expected or values["video"].shape != expected or values["dt"].shape != expected[:2]:
        raise ValueError("Unexpected real audiovisual tensor shapes")
    if not np.isfinite(values["dt"]).all() or not (values["dt"] > 0).all() or np.ptp(values["dt"]) == 0:
        raise ValueError("Stored elapsed durations must be positive and nonconstant")
    if set(values["actor"].tolist()) != set(row["actors"]) or len(np.unique(values["clip"])) != row["examples"]:
        raise ValueError("Actor or recording identity changed")
    for name in ("audio", "video", "dt", "y"):
        values[name] = torch.from_numpy(values[name])
    return values


def evaluate(model, arrays, destination, batch_size, split):
    import torch

    cpu, wall = time.process_time(), time.perf_counter()
    parts = {}
    model.eval()
    with torch.no_grad():
        for begin in range(0, len(arrays["y"]), batch_size):
            end = begin+batch_size
            result = model(arrays["audio"][begin:end], arrays["video"][begin:end],
                           arrays["dt"][begin:end], return_aux=False)
            for key, value in result.items():
                parts.setdefault(key, []).append(value.cpu().numpy())
    outputs = {key: np.concatenate(value) for key, value in parts.items()}
    saved, result = evaluation_arrays(outputs, arrays["y"].numpy(), arrays["actor"], arrays["clip"], split)
    np.savez_compressed(destination, **saved)
    result.update(file=destination.name, sha256=digest(destination),
                  cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall,
                  scope="Both encoders, shared head, all calibration/retrieval/shuffle metrics and raw evidence serialization")
    return result


def worker(output, job):
    import torch
    from .model import PairedEncoder, common_state, objective

    output = Path(output).resolve()
    protocol = verify(output)
    design = protocol["design"]
    if job not in read(output/("jobs_"+job["stage"]+".json")):
        raise ValueError("Worker specification is not a registered job")
    if job["stage"] != "development" and not (output/"SELECTION_LOCK.json").exists():
        raise ValueError("Learning-rate choices must be fixed before formal training")
    job_dir = output/job["stage"]/job["id"]
    job_dir.mkdir(parents=True, exist_ok=False)
    write(job_dir/"job.json", job)
    started, wall_start = common.utc(), time.perf_counter()
    trajectory, validations, best, step = [], [], None, 0
    training_cpu, training_wall, batches = 0., 0., hashlib.sha256()
    try:
        torch.set_num_threads(1)
        torch.manual_seed(job["seed"])
        train = load_split(output, protocol, "train", job_dir)
        validation = load_split(output, protocol, "validation", job_dir)
        model = PairedEncoder(job["arm"], job["seed"], design)
        initial = {key: value.detach().clone() for key, value in model.named_parameters()}
        initial_hash = common.state_hash(model.state_dict())
        shared_hash = common.state_hash(common_state(model))
        optimizer = torch.optim.Adam(model.parameters(), lr=job["learning_rate"], weight_decay=0)
        generator = torch.Generator().manual_seed(job["seed"]+design["initialization"]["batch_seed_offset"])
        midpoint_seen = False
        while True:
            model.train()
            cpu, wall = time.process_time(), time.perf_counter()
            indices = torch.randint(len(train["y"]), (design["batch_size"],), generator=generator)
            batches.update(indices.numpy().tobytes())
            optimizer.zero_grad(set_to_none=True)
            outputs, aux = model(train["audio"][indices], train["video"][indices], train["dt"][indices])
            loss, components = objective(outputs, train["y"][indices], design["objective"]["temperature"])
            if not bool(torch.isfinite(loss)):
                raise FloatingPointError("Nonfinite audiovisual objective")
            loss.backward()
            gradients = common.group_measurements(model, initial, gradient=True)
            torch.nn.utils.clip_grad_norm_(model.parameters(), design["optimizer"]["gradient_clip_norm"])
            optimizer.step()
            physical = {key: common.physical_audit(value) for key, value in aux.items()}
            step += 1
            training_cpu += time.process_time()-cpu
            training_wall += time.perf_counter()-wall
            trajectory.append(dict(step=step, loss=float(loss.detach()), components=components,
                training_cpu_seconds=training_cpu, gradient_groups=gradients, physical=physical))
            equal_cpu = job["stage"] == "equal_cpu"
            finished = training_cpu >= design["equal_cpu_seconds"] if equal_cpu else step >= job["updates"]
            midpoint = training_cpu >= design["equal_cpu_seconds"]/2 if equal_cpu else step >= job["updates"]//2
            if (midpoint and not midpoint_seen) or finished:
                midpoint_seen = True
                result = evaluate(model, validation, job_dir/f"validation_{step:06d}.npz", design["batch_size"], "validation")
                result.update(step=step, training_cpu_seconds=training_cpu)
                validations.append(result)
                score = result["classification"]["fused"]["cross_entropy"]
                if best is None or (score, step) < (best["cross_entropy"], best["step"]):
                    common.save_state(model, job_dir/"selected_state.npz")
                    best = dict(step=step, cross_entropy=score, validation_file=result["file"],
                        validation_sha256=result["sha256"], tensor_hash=common.state_hash(model.state_dict()),
                        state_sha256=digest(job_dir/"selected_state.npz"))
            if step % 16 == 0 or finished:
                write(job_dir/"trajectory.json", trajectory)
            if finished:
                break
        final_updates = common.group_measurements(model, initial)
        modality_updates = {modality: common.group_measurements(getattr(model, modality), {
            name.removeprefix(modality+"."): value for name, value in initial.items()
            if name.startswith(modality+".")}) for modality in ("audio", "video")}
        final_hash = common.state_hash(model.state_dict())
        common.save_state(model, job_dir/"final_state.npz")
        durable(job_dir/"selected_state.npz")
        write(job_dir/"selection.json", dict(best, locked_utc=common.utc(),
            rule="Minimum FP64 fused validation CE; earlier update on exact tie"))
        durable(job_dir/"selection.json")
        with np.load(job_dir/"selected_state.npz", allow_pickle=False) as saved:
            model.load_state_dict({key: torch.from_numpy(np.array(saved[key], copy=True)) for key in saved.files})
        if common.state_hash(model.state_dict()) != best["tensor_hash"]:
            raise ValueError("Checkpoint identity changed at reload")
        test_result = None
        if job["stage"] != "development":
            test = load_split(output, protocol, "test", job_dir)
            test_result = evaluate(model, test, job_dir/"test.npz", design["batch_size"], "test")
        model.eval()
        inputs = [validation[key][:design["batch_size"]] for key in ("audio", "video", "dt")]
        inference = []
        with torch.no_grad():
            model(*inputs, return_aux=False)
            for _ in range(5):
                cpu, wall = time.process_time(), time.perf_counter()
                model(*inputs, return_aux=False)
                inference.append(dict(cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall))
        report = dict(schema="hcsn-blocker-av-worker.v1", status="complete", job=job,
            public_execution_commit=os.environ.get("GITHUB_SHA"), data_evidence_commit=protocol["data_evidence_commit"],
            protocol_sha256=digest(output/"PROTOCOL.json"), initial_tensor_hash=initial_hash,
            common_initial_hash=shared_hash, final_tensor_hash=final_hash,
            final_state_sha256=digest(job_dir/"final_state.npz"), selected=best,
            final_update_groups=final_updates, selected_update_groups=common.group_measurements(model, initial),
            final_modality_update_groups=modality_updates,
            selected_modality_update_groups={modality: common.group_measurements(getattr(model, modality), {
                name.removeprefix(modality+"."): value for name, value in initial.items()
                if name.startswith(modality+".")}) for modality in ("audio", "video")},
            batch_stream_sha256=batches.hexdigest(), validations=validations, test=test_result,
            config=model.config, counts=model.counts(), updates=step,
            training_cpu_seconds=training_cpu, training_wall_seconds=training_wall,
            training_cpu_budget_overrun_seconds=training_cpu-design["equal_cpu_seconds"] if equal_cpu else None,
            complete_process_cpu_seconds=time.process_time(), wall_since_worker_entry=time.perf_counter()-wall_start,
            peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform == "darwin" else 1024),
            cost_scope="RUN wait4/launch receipts include imports, initialization, data, training, evaluation, serialization and exit; contained clocks are not added again",
            inference=dict(batch=design["batch_size"], length=design["sequence_length"], warmup=1, repetitions=5,
                samples=inference, median_cpu_seconds=statistics.median(row["cpu_seconds"] for row in inference),
                median_wall_seconds=statistics.median(row["wall_seconds"] for row in inference),
                scope="Both selected modality encoders and shared head, in-memory; no media decode or process startup"),
            dt_override=None, started_utc=started, completed_utc=common.utc(), energy_joules=None)
        write(job_dir/"RESULT.json", report)
    except Exception as error:
        write(job_dir/"trajectory.json", trajectory)
        write(job_dir/"FAILURE.json", dict(status="failed", job=job, error=repr(error), traceback=traceback.format_exc(),
            updates=step, training_cpu_seconds=training_cpu, complete_process_cpu_seconds=time.process_time(),
            wall_since_worker_entry=time.perf_counter()-wall_start))
        raise
    return dict(id=job["id"], status="complete", updates=step)


def lock(output):
    output = Path(output).resolve()
    protocol = verify(output)
    if (output/"SELECTION_LOCK.json").exists():
        raise FileExistsError("Audiovisual tuning choices already locked")
    design, choices = protocol["design"], {}
    for arm in design["models"]:
        candidates = []
        for job in read(output/"jobs_development.json"):
            if job["arm"] == arm:
                path = output/"development"/job["id"]/"RESULT.json"
                result = read(path)
                if result["status"] != "complete" or result["job"] != job or result["test"] is not None:
                    raise ValueError("Development worker failed or accessed heldout evaluation")
                candidates.append((result, path))
        result, path = min(candidates, key=lambda pair: (pair[0]["selected"]["cross_entropy"],
            pair[0]["selected"]["step"], pair[0]["job"]["learning_rate"]))
        choices[arm] = dict(learning_rate=result["job"]["learning_rate"],
            development_cross_entropy=result["selected"]["cross_entropy"],
            result_file=str(path.relative_to(output)), result_sha256=digest(path))
    write(output/"SELECTION_LOCK.json", dict(choices=choices, locked_utc=common.utc(),
        protocol_sha256=digest(output/"PROTOCOL.json")))
    durable(output/"SELECTION_LOCK.json")
    for stage in ("fixed", "equal_cpu"):
        jobs = [dict(stage=stage, arm=arm, seed=seed, learning_rate=choices[arm]["learning_rate"],
            updates=design["formal_updates"], id=f"{arm}__seed{seed}")
            for arm in design["models"] for seed in design["formal_seeds"]]
        write(output/("jobs_"+stage+".json"), jobs)
    return dict(fixed_jobs=40, equal_cpu_jobs=40, choices=choices)


def run(output, stage, workers):
    output = Path(output).resolve()
    protocol = verify(output)
    if stage == "equal_cpu" and not protocol["design"]["equal_cpu_enabled"]:
        raise ValueError("Equal CPU stage was not registered")
    jobs = read(output/("jobs_"+stage+".json"))
    ledger, logs = output/("RUN_"+stage+".json"), output/"logs"/stage
    if ledger.exists() or logs.exists():
        raise FileExistsError("An attempt already exists; no silent retry")
    if stage != "development" and not (output/"SELECTION_LOCK.json").exists():
        raise ValueError("Learning-rate lock required")
    random.Random(882771+("development", "fixed", "equal_cpu").index(stage)).shuffle(jobs)
    logs.mkdir(parents=True)
    cpu, wall, rows = time.process_time(), time.perf_counter(), []

    def execute(job):
        spec = logs/(job["id"]+".json")
        write(spec, job)
        started = time.perf_counter()
        with (logs/(job["id"]+".log")).open("wb") as stream:
            process = subprocess.Popen([sys.executable, "-m", MODULE, "worker", "--output", str(output),
                "--job", str(spec)], cwd=ROOT, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT)
            _, status, usage = os.wait4(process.pid, 0)
            process.returncode = os.waitstatus_to_exitcode(status)
        return dict(id=job["id"], job=job, exit_code=process.returncode,
            child_cpu_seconds=usage.ru_utime+usage.ru_stime, wall_seconds=time.perf_counter()-started,
            maxrss_bytes=usage.ru_maxrss*(1 if sys.platform == "darwin" else 1024))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(execute, job) for job in jobs]
        for future in as_completed(futures):
            rows.append(future.result())
            write(ledger, dict(stage=stage, complete=False, jobs=rows,
                coordinator_cpu_seconds=time.process_time(), coordinator_queue_cpu_seconds=time.process_time()-cpu,
                wall_seconds=time.perf_counter()-wall))
            print(json.dumps(dict(done=len(rows), total=len(jobs), **rows[-1])), flush=True)
    report = dict(stage=stage, complete=True, jobs=rows, failed=sum(row["exit_code"] != 0 for row in rows),
        child_cpu_seconds=sum(row["child_cpu_seconds"] for row in rows), coordinator_cpu_seconds=time.process_time(),
        coordinator_queue_cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall)
    write(ledger, report)
    return {key: value for key, value in report.items() if key != "jobs"}


def preflight(destination):
    import torch
    from .model import PairedEncoder, common_state, objective

    destination = Path(destination)
    if destination.exists():
        raise FileExistsError("Keep every preflight attempt")
    torch.set_num_threads(1)
    design, sources = read(HERE/"AV_DESIGN.json"), source_map()
    rng = torch.Generator().manual_seed(882007)
    audio = torch.randn(16, 32, 128, generator=rng)
    video = torch.randn(16, 32, 128, generator=rng)
    dt = .2+1.2*torch.rand(16, 32, generator=rng)
    labels = torch.arange(16) % 6
    rows, checks = [], []
    try:
        for arm in design["models"]:
            model = PairedEncoder(arm, 882009, design)
            initial = {name: value.detach().clone() for name, value in model.named_parameters()}
            optimizer = torch.optim.Adam(model.parameters(), lr=.001)
            common_hash = common.state_hash(common_state(model))
            cpu, wall = time.process_time(), time.perf_counter()
            optimizer.zero_grad(set_to_none=True)
            outputs, aux = model(audio, video, dt)
            loss, components = objective(outputs, labels)
            if not bool(torch.isfinite(loss)):
                raise FloatingPointError("Synthetic preflight loss is nonfinite")
            loss.backward()
            gradients = common.group_measurements(model, initial, gradient=True)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 2.)
            optimizer.step()
            elapsed_cpu, elapsed_wall = time.process_time()-cpu, time.perf_counter()-wall
            changes = common.group_measurements(model, initial)
            physical = {key: common.physical_audit(value) for key, value in aux.items()}
            rows.append(dict(arm=arm, common_initial_hash=common_hash, counts=model.counts(),
                full_B16_T32_update_cpu_seconds=elapsed_cpu, update_wall_seconds=elapsed_wall,
                loss=float(loss.detach()), components=components, gradient_groups=gradients,
                update_groups=changes, physical=physical))
            checks.append(dict(name=arm+"_all_owned_groups_update", passed=all(row["nonzero"] > 0 for row in changes.values())))
            if arm == "value_jg":
                checks.append(dict(name="five_physical_content_groups_have_gradients", passed=all(
                    gradients[name]["nonzero"] > 0 for name in ("content", "dynamics", "boundary", "reset", "refractory"))))
                for modality in ("audio", "video"):
                    elapsed = aux[modality]["state"]["elapsed"]
                    checks.append(dict(name=modality+"_retains_real_elapsed_duration", passed=bool(torch.equal(elapsed, dt.cumsum(1)[:, -1]))))
            converted = {key: value.detach().numpy() for key, value in outputs.items()}
            _, diagnostic = evaluation_arrays(converted, labels.numpy(), np.repeat(np.arange(4), 4).astype(str),
                                               np.array([f"synthetic-{i}" for i in range(16)]), "synthetic")
            checks.append(dict(name=arm+"_retrieval_calibration_pairing_finite", passed=all(
                np.isfinite(row["cross_entropy"]) for row in diagnostic["classification"].values())))
        counts = [row["counts"]["backbone"] for row in rows]
        checks.append(dict(name="matched_active_backbones_within_3percent", passed=(max(counts)-min(counts))/max(counts) <= .03))
        checks.append(dict(name="common_frontend_projection_head_identity", passed=len({row["common_initial_hash"] for row in rows}) == 1))
        unit = np.eye(8)
        actors = np.repeat(np.arange(2), 4)
        ranks, _ = retrieval_ranks(unit, unit, actors)
        checks.append(dict(name="identity_embeddings_rank_first", passed=all(np.all(rank == 1) for rank in ranks.values())))
        ties, _ = retrieval_ranks(np.zeros((8, 4)), np.zeros((8, 4)), actors)
        checks.append(dict(name="exact_retrieval_ties_follow_frozen_index", passed=np.array_equal(ties["audio_to_video_whole"], np.arange(1, 9))))
        shuffle = derangement(8, 882903, actors)
        checks.append(dict(name="within_actor_derangement", passed=bool(np.all(shuffle != np.arange(8)) and np.array_equal(actors, actors[shuffle]))))
        checks.append(dict(name="source_identity_unchanged", passed=sources == source_map()))
        passed = all(row["passed"] for row in checks)
        report = dict(schema="hcsn-av-synthetic-preflight.v1", passed=passed, checks=checks, models=rows,
            source_sha256=sources, real_data_loaded=False, previous_test_data_loaded=False,
            cost_prediction="One synthetic full-batch update per model, includes first-use overhead. Real training/validation can cost more. This is not a performance benchmark.",
            process_cpu_seconds=time.process_time(), peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
        write(destination, report)
        if not passed:
            raise AssertionError("AV synthetic preflight failed")
        return dict(passed=passed, checks=len(checks), models=rows)
    except Exception as error:
        if not destination.exists():
            write(destination, dict(schema="hcsn-av-synthetic-preflight.v1", passed=False,
                models=rows, checks=checks, source_sha256=sources, real_data_loaded=False,
                error=repr(error), traceback=traceback.format_exc(), process_cpu_seconds=time.process_time()))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "register", "worker", "run", "lock", "analyze"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--data-commit")
    parser.add_argument("--data-transport-path")
    parser.add_argument("--preflight", type=Path)
    parser.add_argument("--job", type=Path)
    parser.add_argument("--stage", choices=("development", "fixed", "equal_cpu"))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.command == "register":
        result = register(args.output, args.dataset, args.data_commit, args.data_transport_path, args.preflight)
    elif args.command == "preflight":
        result = preflight(args.output)
    elif args.command == "worker":
        result = worker(args.output, read(args.job))
    elif args.command == "lock":
        result = lock(args.output)
    elif args.command == "run":
        result = run(args.output, args.stage, args.workers)
    else:
        from .analysis import analyze

        result = analyze(args.output)
    print(json.dumps(result, sort_keys=True), flush=True)
    if args.command == "run" and result["failed"] or args.command == "analyze" and not result["complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
