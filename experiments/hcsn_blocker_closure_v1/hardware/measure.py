"""Seal selected validation inputs, then measure complete CPU/CUDA forwards."""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import random
import resource
import sys
import time
import traceback

import numpy as np

from .energy import NvmlEnergy, measure_energy


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def read(path):
    return json.loads(Path(path).read_bytes())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def source_map():
    from ..content.study import source_map as content_sources
    return dict(content_sources(), **{str(path.relative_to(ROOT)): digest(path)
        for path in sorted(HERE.glob("*.py"))+[HERE/"HARDWARE_DESIGN.json"]})


def child(root, name):
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Expected a bounded relative evidence path")
    result = root/path
    result.resolve().relative_to(root.resolve())
    if result.is_symlink():
        raise ValueError("Symlinked evidence is not accepted")
    return result


def tensor_hash(path):
    value = hashlib.sha256()
    with np.load(path, allow_pickle=False) as state:
        for key in sorted(state.files):
            array = state[key]
            if not np.isfinite(array).all():
                raise ValueError("Nonfinite checkpoint tensor")
            value.update(json.dumps([key, str(array.dtype), list(array.shape)]).encode())
            value.update(array.tobytes())
    return value.hexdigest()


def archive_members(index, expected_sha256):
    index = Path(index).resolve()
    if digest(index) != expected_sha256:
        raise ValueError("Externally pinned published archive index changed")
    descriptor, members = read(index), {}
    if descriptor["schema"] != "hcsn-bounded-member-index.v1":
        raise ValueError("Expected the published closure archive member index")
    for shard in descriptor["member_shards"]:
        path = child(index.parent, shard["path"])
        if path.stat().st_size != shard["bytes"] or digest(path) != shard["sha256"]:
            raise ValueError("Published member shard changed")
        rows = read(path)
        if len(rows) != shard["members"]:
            raise ValueError("Member shard count changed")
        for row in rows:
            child(index.parent, row["path"])
            if row["path"] in members:
                raise ValueError("Duplicate published archive member")
            members[row["path"]] = row
    if len(members) != descriptor["original_member_count"]:
        raise ValueError("Published archive member count changed")
    return members


def bind_case(run_root, protocol, task, arm, design):
    name = f"{task}__{arm}__seed{design['seed']}"
    relative = Path(design["stage"])/name
    result = read(child(run_root, relative/"RESULT.json"))
    selected = read(child(run_root, relative/"selection.json"))
    lock = read(run_root/"SELECTION_LOCK.json")
    expected = dict(stage=design["stage"], task=task, arm=arm, seed=design["seed"],
        learning_rate=lock["choices"][task][arm]["learning_rate"],
        updates=protocol["design"]["formal_updates"], id=name)
    if (result["status"] != "complete" or result["job"] != expected
            or result["protocol_sha256"] != digest(run_root/"PROTOCOL.json")
            or result["public_execution_commit"] != design["study_execution_seal"]):
        raise ValueError("Selected model identity differs from the predeclared case")
    if any(selected.get(key) != value for key, value in result["selected"].items()):
        raise ValueError("Result and durable checkpoint selection disagree")
    best = min(result["validations"], key=lambda row: (row["cross_entropy"], row["step"]))
    if (any(selected.get(key) != value for key, value in best.items())
            or result["updates"] != protocol["design"]["formal_updates"]):
        raise ValueError("Selected checkpoint was not the validation argmin")
    state = child(run_root, relative/"selected_state.npz")
    if digest(state) != selected["state_sha256"] or tensor_hash(state) != selected["tensor_hash"]:
        raise ValueError("Selected checkpoint byte/tensor identity changed")
    val = protocol["data"][task]["val"]
    validation = Path("data")/val["file"]
    if digest(child(run_root, validation)) != val["sha256"]:
        raise ValueError("Registered validation input changed")
    inputs = [relative/"RESULT.json", relative/"selection.json", relative/"selected_state.npz", validation]
    return dict(task=task, arm=arm, seed=design["seed"], checkpoint=(relative/"selected_state.npz").as_posix(),
        validation=validation.as_posix(), tensor_hash=selected["tensor_hash"],
        files={p.as_posix(): digest(child(run_root, p)) for p in inputs})


def register(run_root, output, protocol_sha256, preflight, archive_index, archive_index_sha256):
    run_root, output = Path(run_root).resolve(), Path(output).resolve()
    output.relative_to(HERE)
    proof, design = read(preflight), read(HERE/"HARDWARE_DESIGN.json")
    if not proof["passed"] or proof["source_sha256"] != source_map():
        raise ValueError("Source-identical passing synthetic hardware preflight required")
    if digest(run_root/"PROTOCOL.json") != protocol_sha256:
        raise ValueError("Externally pinned study protocol SHA256 does not match")
    protocol = read(run_root/"PROTOCOL.json")
    from ..content.study import source_map as content_sources
    if (protocol["status"] != "registered" or protocol["source_sha256"] != content_sources()
            or protocol["design"] != read(HERE.parent/"content/DESIGN.json")
            or protocol["public_execution_commit"] != design["study_execution_seal"]):
        raise ValueError("Frozen content source, design or execution seal changed")
    if digest(child(ROOT, protocol["preflight"]["file"])) != protocol["preflight"]["sha256"]:
        raise ValueError("Original content preflight receipt changed")
    if read(run_root/"SELECTION_LOCK.json")["protocol_sha256"] != protocol_sha256:
        raise ValueError("Global learning-rate lock belongs to a different study")
    cases = [bind_case(run_root, protocol, task, arm, design)
             for task in design["tasks"] for arm in design["models"]]
    members = archive_members(archive_index, archive_index_sha256)
    needed = {name: digest(run_root/name) for name in ("PROTOCOL.json", "SELECTION_LOCK.json")}
    for case in cases:
        needed.update(case["files"])
    for name, identity in needed.items():
        archived = members[design["archive_content_prefix"]+"/"+name]
        if archived["sha256"] != identity or archived["bytes"] != child(run_root,name).stat().st_size:
            raise ValueError("Measurement input differs from the externally pinned publication: "+name)
    output.mkdir(parents=True, exist_ok=False)
    sealed = dict(schema="hcsn-blocker-hardware-protocol.v1", registered_utc=utc(), design=design,
        source_sha256=source_map(), content_root=str(run_root), study_protocol_sha256=protocol_sha256,
        selection_lock_sha256=digest(run_root/"SELECTION_LOCK.json"), cases=cases,
        archive_index=dict(path=str(Path(archive_index).resolve()), sha256=archive_index_sha256),
        preflight=dict(path=str(Path(preflight).resolve()), sha256=digest(preflight)),
        measurement_started=False, test_or_ood_arrays_loaded=False)
    write(output/"PROTOCOL.json", sealed)
    return dict(cases=len(cases), protocol_sha256=digest(output/"PROTOCOL.json"))


def verify(output):
    protocol = read(output/"PROTOCOL.json")
    if protocol["source_sha256"] != source_map() or protocol["design"] != read(HERE/"HARDWARE_DESIGN.json"):
        raise ValueError("Hardware source or design changed after registration")
    root = Path(protocol["content_root"])
    archive_members(protocol["archive_index"]["path"], protocol["archive_index"]["sha256"])
    if (digest(root/"PROTOCOL.json") != protocol["study_protocol_sha256"]
            or digest(root/"SELECTION_LOCK.json") != protocol["selection_lock_sha256"]
            or digest(protocol["preflight"]["path"]) != protocol["preflight"]["sha256"]):
        raise ValueError("Study protocol, learning-rate lock or hardware preflight changed")
    for case in protocol["cases"]:
        for path, identity in case["files"].items():
            if digest(child(root, path)) != identity:
                raise ValueError("Sealed measurement input changed: "+path)
    return protocol


def capability(torch):
    cuda = dict(available=bool(torch.cuda.is_available()), build_version=torch.version.cuda, devices=[])
    if cuda["available"]:
        for index in range(torch.cuda.device_count()):
            p = torch.cuda.get_device_properties(index)
            cuda["devices"].append(dict(index=index, name=p.name, uuid=str(getattr(p, "uuid", None)),
                memory_bytes=p.total_memory, compute_capability=[p.major, p.minor]))
    return dict(torch=torch.__version__, numpy=np.__version__, python=sys.version, cuda=cuda,
        host_cpu_count=os.cpu_count(), affinity=sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
        cgroup={name: (Path('/sys/fs/cgroup')/name).read_text() if (Path('/sys/fs/cgroup')/name).exists() else None
                for name in ("cpu.max", "cpu.stat", "memory.max", "memory.current")})


def timing(model, x, dt, device, scope, design):
    import torch
    sync = (lambda: torch.cuda.synchronize(device)) if device.type == "cuda" else (lambda: None)
    resident_x, resident_dt = x.to(device), dt.to(device)

    def invoke():
        a, b = (resident_x, resident_dt) if scope == "resident" else (x.to(device, copy=True), dt.to(device, copy=True))
        output = model(a, b, return_sequence=True, return_aux=False)
        return output if scope == "resident" else output.to("cpu", copy=True)

    wall, host_cpu, events = [], [], []
    with torch.inference_mode():
        for _ in range(design["warmup"]):
            invoke()
        sync()
        for _ in range(design["repetitions"]):
            start_event = torch.cuda.Event(enable_timing=True) if device.type == "cuda" else None
            end_event = torch.cuda.Event(enable_timing=True) if device.type == "cuda" else None
            sync()
            tick, cpu = time.perf_counter(), time.process_time()
            if start_event is not None:
                start_event.record(torch.cuda.current_stream(device))
            result = invoke()
            if end_event is not None:
                end_event.record(torch.cuda.current_stream(device))
            sync()
            wall.append(time.perf_counter()-tick)
            host_cpu.append(time.process_time()-cpu)
            if start_event is not None:
                events.append(start_event.elapsed_time(end_event)/1000.)
        output = result.detach().cpu().numpy()
    if not np.isfinite(output).all() or not all(value > 0 for value in wall):
        raise ValueError("Nonfinite output or nonpositive measured latency")
    return dict(wall_seconds=wall, host_cpu_seconds=host_cpu, cuda_event_seconds=events or None,
        wall_quantiles_seconds=dict(zip(("p05", "p50", "p95"), np.quantile(wall, [.05,.5,.95]).tolist())),
        examples_per_second=len(x)*len(wall)/sum(wall),
        input_steps_per_second=len(x)*x.shape[1]*len(wall)/sum(wall)), output, invoke, sync


def run(output):
    import torch
    from ..content.models import build
    output = Path(output).resolve()
    protocol = verify(output)
    design, root = protocol["design"], Path(protocol["content_root"])
    torch.set_num_threads(design["cpu_threads"])
    if torch.__version__.split("+")[0] != "2.8.0":
        raise ValueError("This harness requires PyTorch2.8.0 CPU or CUDA build")
    if torch.cuda.is_available():
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.backends.cudnn.benchmark = False
    caps = capability(torch)
    write(output/"RUN_STARTED.json", dict(utc=utc(), protocol_sha256=digest(output/"PROTOCOL.json"), capabilities=caps))
    start, cpu = time.perf_counter(), time.process_time()
    jobs = [(case, batch, backend) for case in protocol["cases"] for batch in design["batches"] for backend in design["backends"]]
    random.Random(design["order_seed"]).shuffle(jobs)
    rows = []
    try:
        for number, (case, batch, backend) in enumerate(jobs):
            row = dict(task=case["task"], arm=case["arm"], batch=batch, length=design["length"], backend=backend)
            counter = None
            try:
                if backend.startswith("cuda") and not caps["cuda"]["available"]:
                    row.update(status="unavailable", reason="CUDA unavailable in this runtime", energy=dict(joules=None))
                else:
                    tick, setup_cpu = time.perf_counter(), time.process_time()
                    with np.load(child(root, case["validation"]), allow_pickle=False) as saved:
                        x = torch.from_numpy(np.array(saved["x"][:batch], copy=True))
                        dt = torch.from_numpy(np.array(saved["dt"][:batch], copy=True))
                    if (tuple(x.shape) != (batch, design["length"], design["input_dim"])
                            or tuple(dt.shape) != (batch, design["length"]) or not bool(torch.isfinite(x).all())
                            or not bool(torch.isfinite(dt).all()) or not bool((dt > 0).all())):
                        raise ValueError("Validation-only full-sequence input contract failed")
                    model = build(case["arm"], width=32, depth=1, seed=case["seed"])
                    with np.load(child(root, case["checkpoint"]), allow_pickle=False) as state:
                        model.load_state_dict({key: torch.from_numpy(np.array(state[key], copy=True)) for key in state.files})
                    model.eval()
                    with torch.inference_mode():
                        reference = model(x, dt, return_sequence=True, return_aux=False).numpy()
                    device = torch.device(backend)
                    model.to(device)
                    if device.type == "cuda":
                        torch.cuda.synchronize(device)
                    row.update(setup_wall_seconds=time.perf_counter()-tick, setup_cpu_seconds=time.process_time()-setup_cpu,
                        setup_scope="Validation read, model construction, checkpoint load, CPU reference, device weight transfer")
                    for scope in ("resident", "host_end_to_end"):
                        measured, actual, invoke, sync = timing(model, x, dt, device, scope, design)
                        if not np.allclose(actual, reference, **design["forward_tolerance"]):
                            raise ValueError("Backend output differs from the exact selected CPU model")
                        measured["maximum_absolute_cpu_reference_error"] = float(np.max(np.abs(actual-reference)))
                        row[scope] = measured
                        if scope == "resident" and device.type == "cuda":
                            counter = NvmlEnergy(getattr(torch.cuda.get_device_properties(device), "uuid", None))
                            with torch.inference_mode():
                                row["energy"] = measure_energy(counter, invoke, sync, design["energy"], batch)
                    row.setdefault("energy", dict(joules=None, reason="CPU energy counter is outside this harness scope"))
                    row["status"] = "complete"
                    del model
            except Exception:
                row.update(status="failed", traceback=traceback.format_exc())
            finally:
                if counter is not None:
                    counter.close()
            rows.append(row)
            write(output/f"case_{number:03d}.json", row)
            print(json.dumps({key:row[key] for key in ("task","arm","batch","backend","status")}), flush=True)
    finally:
        failures = sum(row["status"] == "failed" for row in rows)
        result = dict(schema="hcsn-blocker-hardware-results.v1", complete=len(rows)==len(jobs) and failures==0,
            protocol_sha256=digest(output/"PROTOCOL.json"), cases=rows, failures=failures,
            unavailable=sum(row["status"] == "unavailable" for row in rows), capabilities=caps,
            cuda_executed=any(row["status"]=="complete" and row["backend"].startswith("cuda") for row in rows),
            actual_energy_counter_cases=sum(row.get("energy",{}).get("joules") is not None for row in rows),
            measured_body_cpu_seconds=time.process_time()-cpu, measured_body_wall_seconds=time.perf_counter()-start,
            peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=="darwin" else 1024),
            cost_scope="Body clocks exclude Python imports and integrity verification; setup and repeated inference clocks are contained. External process wait4 is required for whole-command cost.",
            test_or_ood_arrays_loaded=False, hardware_advantage_claim=False)
        write(output/"RESULTS.json", result)
    return {key:value for key,value in result.items() if key not in ("cases","capabilities")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("register","run"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--study-protocol-sha256")
    parser.add_argument("--preflight", type=Path)
    parser.add_argument("--archive-index", type=Path)
    parser.add_argument("--archive-index-sha256")
    args = parser.parse_args()
    result = register(args.run_root,args.output,args.study_protocol_sha256,args.preflight,args.archive_index,args.archive_index_sha256) if args.command=="register" else run(args.output)
    print(json.dumps(result, sort_keys=True))
    if result.get("complete") is False:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
