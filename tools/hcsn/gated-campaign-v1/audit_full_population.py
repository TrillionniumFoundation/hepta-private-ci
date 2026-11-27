#!/usr/bin/env python3
"""Fixed full-budget B CUDA joint-grid diagnostic; no training or selection.

Launch with CUBLAS_WORKSPACE_CONFIG=:4096:8. An already imported Torch requires
a verified current-process wrapper profile. The final JSON is create-only;
its sibling .progress directory owns durable progress records.
This script never calls the original CPU three-grid audit.
"""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import io
import itertools
import json
import math
import os
from pathlib import Path
import platform
import signal
import sys
import tempfile
import time
import traceback
import uuid

PROTOCOL_SHA256 = "4983e126099ff69221e477012034058035463bd03f853f51cea1299de60fc1db"
IDENTITIES = tuple(itertools.product(("delayed_recall", "adding"),
                                    ("population_flux", "population_flux_no_recovery"), range(5)))
FACTORS, BATCHES = (1, 2, 4), {1: 64, 2: 8, 4: 8}
ENVIRONMENT_KEYS = ("CUBLAS_WORKSPACE_CONFIG", "CUDA_VISIBLE_DEVICES", "CUDA_DEVICE_ORDER",
                    "NVIDIA_TF32_OVERRIDE", "TORCH_ALLOW_TF32_CUBLAS_OVERRIDE",
                    "PYTORCH_CUDA_ALLOC_CONF", "PYTORCH_ALLOC_CONF", "CUDA_MODULE_LOADING",
                    "OMP_NUM_THREADS", "MKL_NUM_THREADS")


class Unavailable(RuntimeError):
    pass


class Invalidated(RuntimeError):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_hash(path):
    return digest(path.read_bytes())


def snapshot(root):
    return {p.relative_to(root).as_posix(): file_hash(p) for p in sorted(root.rglob("*.py"))}


def canonical(value):
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def torch_settings(torch):
    return dict(deterministic_algorithms=torch.are_deterministic_algorithms_enabled(),
                deterministic_warn_only=torch.is_deterministic_algorithms_warn_only_enabled(),
                float32_matmul_precision=torch.get_float32_matmul_precision(),
                cuda_matmul_allow_tf32=torch.backends.cuda.matmul.allow_tf32,
                cudnn_allow_tf32=torch.backends.cudnn.allow_tf32,
                cudnn_benchmark=torch.backends.cudnn.benchmark,
                cudnn_deterministic=torch.backends.cudnn.deterministic,
                default_dtype=str(torch.get_default_dtype()), cpu_threads=torch.get_num_threads(),
                cublas_workspace_config=os.environ.get("CUBLAS_WORKSPACE_CONFIG"))


def installed_distributions():
    return {d.metadata["Name"].lower().replace("_", "-"): d.version for d in metadata.distributions()}


def read_profile(path, protocol, files):
    raw = path.read_bytes()
    value = json.loads(raw)
    files[path.resolve()] = digest(raw)
    if (value.get("schema") != protocol["required_runtime_profile_schema"]
            or value.get("device") != "cuda:0" or value.get("allocator_fraction") != .5
            or canonical(value.get("flags")) != canonical(protocol["required_runtime_flags"])
            or not isinstance(value.get("installed_distributions"), dict)
            or canonical(value["installed_distributions"]) != value.get("distributions_sha256")
            or not value.get("gpu_uuid") or value.get("cuda_visible_devices") != value["gpu_uuid"]):
        raise Invalidated("runtime profile schema, flags, device or distribution hash mismatch")
    return value, digest(raw)


def atomic_json(path, value, *, replace=False):
    created, directory = [], path.parent
    while not directory.exists():
        created.append(directory)
        directory = directory.parent
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name+".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
        for directory in dict.fromkeys([path.parent, *(p.parent for p in created)]):
            descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class OutputOwner:
    def __init__(self, output):
        self.output = output.resolve()
        self.folder = self.output.with_name(self.output.name+".progress")
        self.token = uuid.uuid4().hex
        if self.output.exists():
            raise FileExistsError("final output already exists; use a new output path")
        atomic_json(self.folder/"claim.json", dict(owner=self.token, pid=os.getpid(),
                    output=str(self.output), started_utc=datetime.now(timezone.utc).isoformat()))

    def check(self):
        if json.loads((self.folder/"claim.json").read_text())["owner"] != self.token:
            raise Invalidated("output ownership changed")

    def progress(self, result):
        self.check()
        atomic_json(self.folder/"progress.json", result, replace=True)

    def checkpoint(self, index, row):
        self.check()
        path = self.folder/"checkpoints"/f"{index:02d}-{row['task']}-{row['model']}-{row['seed']}.json"
        atomic_json(path, row)
        return dict(path=str(path), sha256=file_hash(path))

    def finish(self, result):
        self.check()
        self.progress(result)
        atomic_json(self.output, result)


def guard(context, checkpoint=None, *, all_checkpoints=False):
    if snapshot(context["root"]) != context["source"]:
        raise Invalidated("research source changed during diagnostic")
    for path, expected in context["files"].items():
        if file_hash(path) != expected:
            raise Invalidated(f"input/source/profile changed during diagnostic: {path.name}")
    if {key: os.environ.get(key) for key in ENVIRONMENT_KEYS} != context["environment"]:
        raise Invalidated("runtime environment changed during diagnostic")
    if "torch" in context:
        try:
            if (torch_settings(context["torch"]) != context["torch_settings"]
                    or context["torch"].cuda.memory.get_per_process_memory_fraction(context["device"]) != .5):
                raise Invalidated("Torch settings or allocator cap changed during diagnostic")
        except Exception as exc:
            raise Invalidated(f"runtime profile could not be reverified: {exc}") from exc
    identities = context["weights"] if all_checkpoints else (() if checkpoint is None else (checkpoint,))
    for identity in identities:
        path, expected = context["weights"][identity]
        if file_hash(path) != expected:
            raise Invalidated(f"checkpoint changed during diagnostic: {identity}")


def prepare(args, result):
    protocol_path = Path(__file__).resolve().with_name("PROTOCOL.json")
    if file_hash(protocol_path) != PROTOCOL_SHA256:
        raise Invalidated("diagnostic protocol differs from its frozen hash")
    protocol = json.loads(protocol_path.read_text())
    root = args.repo_root.resolve()/"qualification"/"hcsn"
    source = snapshot(root)
    if canonical(source) != protocol["candidate_canonical_source_map_sha256"]:
        raise Invalidated("source map differs from the frozen execution candidate")
    config_paths = (root/"configs/full.json", root/"configs/full-rematerialized.json")
    if [file_hash(p) for p in config_paths] != [protocol["original_full_config_sha256"], protocol["package_remat_config_sha256"]]:
        raise Invalidated("original or derived full config bytes differ from frozen pins")
    original = json.loads(config_paths[0].read_text())
    execution_config_hash = file_hash(args.execution_config)
    config = json.loads(args.execution_config.read_text())
    steps = config.get("population_checkpoint_steps")
    if (type(steps) is not int or steps not in (0, 1)
            or config != dict(original, population_checkpoint_steps=steps, cuda_memory_fraction=.5)
            or canonical(config) != protocol["allowed_execution_config_canonical_sha256_by_policy"][str(steps)]):
        raise ValueError("derived config changed original full fields or execution policy")
    raw = args.benchmark.read_bytes()
    report = json.loads(raw)
    if (report.get("schema_version") != 2 or report.get("config") != config
            or report.get("source_files_sha256") != source
            or report.get("source_sha256") != protocol["candidate_benchmark_source_sha256"]):
        raise Invalidated("benchmark config/source differs from the frozen candidate")
    expected = set(itertools.product(config["tasks"], config["models"], config["seeds"]))
    runs = {}
    for run in report["runs"]:
        identity = tuple(run[k] for k in ("task", "model", "seed"))
        if type(run["seed"]) is not int or identity not in expected or identity in runs:
            raise ValueError("duplicate, unregistered or invalid benchmark identity")
        if run["status"] not in {"completed", "failed", "unavailable"}:
            raise ValueError("benchmark contains a nonterminal run identity")
        runs[identity] = run
    if len(runs) != 170 or set(runs) != expected:
        raise ValueError("benchmark must retain all original 170 identities")
    accounting = dict(requested=170, unique_records=170,
                      **{s: sum(r["status"] == s for r in runs.values()) for s in ("completed", "failed", "unavailable")})
    if report.get("accounting") != accounting:
        raise ValueError("benchmark accounting differs from its full identity matrix")
    if report.get("hardware", {}).get("device") != "cuda:0":
        raise ValueError("benchmark must declare original CUDA device cuda:0")
    environment = {key: os.environ.get(key) for key in ENVIRONMENT_KEYS}
    if environment["CUBLAS_WORKSPACE_CONFIG"] != ":4096:8":
        raise ValueError("CUBLAS_WORKSPACE_CONFIG must be :4096:8 before any Torch import")
    files = {Path(__file__).resolve(): result["diagnostic_script_sha256"], protocol_path: PROTOCOL_SHA256,
             args.benchmark.resolve(): digest(raw), args.execution_config.resolve(): execution_config_hash,
             **{p: file_hash(p) for p in config_paths}}
    profile_hash, link_hash, link, profile = None, None, None, None
    if args.runtime_profile:
        profile, profile_hash = read_profile(args.runtime_profile, protocol, files)
    if args.benchmark_runtime_manifest:
        link_hash = file_hash(args.benchmark_runtime_manifest)
        files[args.benchmark_runtime_manifest.resolve()] = link_hash
        link = json.loads(args.benchmark_runtime_manifest.read_text())
        if (profile_hash is None or link.get("benchmark_sha256") != digest(raw)
                or link.get("runtime_profile_sha256") != profile_hash):
            raise Invalidated("runtime manifest does not link this benchmark and profile")
        for key, expected_value in (("execution_config_sha256", execution_config_hash),
                                    ("source_sha256", report["source_sha256"]),
                                    ("source_map_sha256", canonical(source)),
                                    ("software", report.get("software"))):
            if key in link and link[key] != expected_value:
                raise Invalidated(f"runtime manifest {key} differs from the selected input")
    launch, launch_hash, entry_hash = None, None, None
    if bool(args.launch_runtime_profile) != bool(args.launch_runtime_entry):
        raise ValueError("launch runtime profile and entry file must be supplied together")
    if result["torch_preimported"] and args.launch_runtime_profile is None:
        raise Invalidated("preimported Torch requires a current-process wrapper profile and entry file")
    if args.launch_runtime_profile:
        launch, launch_hash = read_profile(args.launch_runtime_profile, protocol, files)
        entry_hash = file_hash(args.launch_runtime_entry)
        files[args.launch_runtime_entry.resolve()] = entry_hash
        arguments = launch.get("arguments")
        arguments = arguments[1:] if isinstance(arguments, list) and arguments[:1] == ["--"] else arguments
        if (launch.get("entry_sha256") != entry_hash or type(launch.get("pid")) is not int
                or launch["pid"] != os.getpid()
                or launch.get("launch_environment_validated_before_torch_import") is not True
                or launch.get("torch_preimported_before_entry") is not False
                or launch.get("target_module") is not None
                or launch.get("target_script_sha256") != result["diagnostic_script_sha256"]
                or Path(launch.get("target_script") or "").resolve() != Path(__file__).resolve()
                or arguments != sys.argv[1:]):
            raise Invalidated("launch profile does not bind this process, wrapper, script and exact arguments")
        if environment["CUDA_VISIBLE_DEVICES"] != launch["gpu_uuid"]:
            raise Invalidated("launch GPU selection differs from the current environment")
    sys.path.insert(0, str(args.repo_root.resolve()))
    from qualification.hcsn import attempts, benchmark, execution
    for module in (attempts, benchmark, execution):
        if Path(module.__file__).resolve().parent != root:
            raise Invalidated("helper imported outside the frozen candidate")
    datasets = {}
    for task in config["tasks"]:
        splits = [benchmark.make_dataset(task, config[key], config["length"], config["data_seed"]+i)
                  for i, key in enumerate(("train_count", "validation_count", "test_count"))]
        hashes = [digest(x.tobytes()+y.tobytes()) for x, y in splits]
        if hashes != report["datasets"][task]["split_sha256"]:
            raise ValueError("original train/validation/test input byte hashes differ")
        datasets[task] = splits[2]
    context = dict(root=root, source=source, files=files, report=report, config=config, runs=runs,
                   protocol=protocol, environment=environment, runtime_link=link,
                   runtime_profile=profile, launch_runtime_profile=launch,
                   datasets=datasets, weights={}, attempts=attempts, benchmark=benchmark, execution=execution)
    for row in result["records"]:
        identity = tuple(row[k] for k in ("task", "model", "seed"))
        run = runs[identity]
        row["benchmark_status"] = run["status"]
        if run["status"] != "completed":
            row.update(status="unavailable", reason=run.get("reason", "original B training did not complete"))
            continue
        try:
            path = attempts.resolve_weights(args.benchmark.with_suffix(".runs"), run)
            if file_hash(path) != run["best_checkpoint_sha256"]:
                raise ValueError("checkpoint hash mismatch before Torch import")
            context["weights"][identity] = (path, run["best_checkpoint_sha256"])
            row.update(checkpoint_relative=run["best_checkpoint_relative"], checkpoint_sha256=run["best_checkpoint_sha256"])
        except Exception as exc:
            row.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
    result.update(protocol=protocol, benchmark_sha256=digest(raw), benchmark_purpose=report.get("purpose"),
                  source_files_sha256=source, source_map_sha256=canonical(source), config=config,
                  original_accounting=accounting, original_attempt_accounting=report.get("attempt_accounting"),
                  completed_b_runs=sum(runs[i]["status"] == "completed" for i in IDENTITIES),
                  runtime_environment=environment, runtime_profile_sha256=profile_hash,
                  benchmark_runtime_manifest_sha256=link_hash, runtime_profile_link_verified=link is not None,
                  launch_runtime_profile_sha256=launch_hash, launch_runtime_entry_sha256=entry_hash,
                  launch_runtime_binding_verified=launch is not None,
                  preimport_environment_evidence=("current-process wrapper assertion; entry bytes are separately bound by the supervisor manifest"
                       if launch is not None else "audit observed environment before its own Torch import"),
                  execution_config_sha256=execution_config_hash,
                  execution_config_link_verified=None if link is None or "execution_config_sha256" not in link else True,
                  verified_checkpoint_count=len(context["weights"]),
                  input_validation_completed=True)
    guard(context)
    return context


def setup_runtime(context, result):
    result["torch_import_attempted"] = True
    try:
        import torch
    except ImportError as exc:
        raise Unavailable(f"PyTorch unavailable: {exc}") from exc
    software = {}
    for package in ("numpy", "scipy", "torch", "ncps", "mamba-ssm", "triton", "causal-conv1d", "nvidia-ml-py"):
        try:
            software[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            software[package] = None
    result.update(software=software, python=sys.version, platform=platform.platform(),
                  torch_version=torch.__version__, cuda_runtime=torch.version.cuda)
    if not result["torch_preimported"]:
        torch.set_num_threads(2)
        torch.use_deterministic_algorithms(True, warn_only=True)
        torch.set_float32_matmul_precision("highest")
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True
    from qualification.hcsn import audit_population, baselines
    for module in (audit_population, baselines):
        if Path(module.__file__).resolve().parent != context["root"]:
            raise Invalidated("tensor helper imported outside the frozen candidate")
    device = torch.device("cuda:0")
    hardware = context["execution"].configure_cuda(torch, device, .5)
    result["hardware"] = hardware
    if hardware["setup_error"] or hardware["uuid"] is None or hardware["memory_fraction_readback"] != .5:
        raise Unavailable(hardware["setup_error"] or "actual CUDA UUID or requested allocator-cap readback is unavailable")
    report = context["report"]
    training_hardware = report["hardware"].get("cuda_execution", {})
    for key in ("uuid", "compute_capability", "total_memory_bytes"):
        if hardware[key] != training_hardware.get(key):
            raise Unavailable(f"actual CUDA {key} differs from original benchmark hardware")
    if training_hardware.get("driver_version") is not None and hardware["driver_version"] != training_hardware["driver_version"]:
        raise Unavailable("actual GPU driver differs from the recorded original driver")
    if (software != report.get("software") or torch.__version__ != report["hardware"].get("torch")
            or torch.version.cuda != report["hardware"].get("cuda_runtime")):
        raise Unavailable("runtime versions differ from the immutable benchmark; no cross-runtime fallback")
    settings = torch_settings(torch)
    result["torch_settings"] = settings
    if canonical(settings) != canonical(context["protocol"]["required_runtime_flags"]):
        raise Unavailable("actual Torch flags differ from the preregistered runtime profile")
    if context["environment"]["CUDA_VISIBLE_DEVICES"] != hardware["uuid"]:
        raise Unavailable("current CUDA_VISIBLE_DEVICES does not select the verified physical UUID")
    distributions = installed_distributions()
    result.update(installed_distributions=distributions, distributions_sha256=canonical(distributions))
    for key in ("runtime_profile", "launch_runtime_profile"):
        profile = context[key]
        if profile is None:
            continue
        expected = dict(gpu_uuid=hardware["uuid"], driver_version=hardware["driver_version"],
                        cuda_runtime=torch.version.cuda, torch=torch.__version__, python=sys.version,
                        flags=settings, installed_distributions=distributions,
                        distributions_sha256=canonical(distributions), allocator_fraction=.5,
                        cuda_visible_devices=context["environment"]["CUDA_VISIBLE_DEVICES"])
        if any(profile.get(name) != value for name, value in expected.items()):
            raise Unavailable(f"actual runtime differs from immutable {key}")
        result[key+"_actual_verified"] = True
    expected_settings = (context["runtime_link"] or {}).get("torch_settings")
    if expected_settings is not None and expected_settings != settings:
        raise Unavailable("actual Torch settings differ from benchmark runtime manifest")
    result["torch_settings_match_runtime_manifest"] = None if expected_settings is None else True
    if torch.get_default_dtype() != torch.float32:
        raise Unavailable("the registered audit requires the original FP32 default dtype")
    context.update(torch=torch, device=device, trace=audit_population.trace, baselines=baselines,
                   torch_settings=settings)
    result["cuda_runtime_verified"] = True


def load_checkpoint(context, identity, row):
    torch, config = context["torch"], context["config"]
    run = context["runs"][identity]
    path, expected_hash = context["weights"][identity]
    raw = path.read_bytes()
    if digest(raw) != expected_hash:
        raise Invalidated("checkpoint changed before loading")
    saved = torch.load(io.BytesIO(raw), map_location="cpu", weights_only=True)
    if any(saved[field] != run[field] for field in ("task", "model", "seed")) or saved["config"] != config:
        raise ValueError("checkpoint identity or full config mismatch")
    if (saved["best_validation_mse"] != run["best_validation_mse"] or saved["training_steps_completed"] != 400
            or run.get("training_status") != "completed" or run.get("training_steps_completed") != 400
            or run.get("training_examples_seen") != 25600 or run.get("training_tokens_seen") != 1638400):
        raise ValueError("checkpoint validation selection or full training budget mismatch")
    for name in ("best_validation_mse", "test_mse"):
        if type(run[name]) not in (int, float) or not math.isfinite(run[name]) or run[name] < 0:
            raise ValueError(f"invalid original {name}")
    torch.manual_seed(run["seed"])
    torch.cuda.manual_seed_all(run["seed"])
    encoder = context["baselines"].make_encoder(run["model"], 2, 64, dt=.1,
                                               population_checkpoint_steps=config["population_checkpoint_steps"])
    readout = torch.nn.Linear(64, 1)
    implementation = context["execution"].implementation_record(encoder)
    if (run.get("implementation") != implementation or run.get("encoder_class") != implementation["encoder_class"]
            or run.get("execution_policy") != context["execution"].execution_policy(config)):
        raise ValueError("original implementation does not match the declared execution policy")
    state = {**{"encoder."+k: v for k, v in encoder.state_dict().items()},
             **{"readout."+k: v for k, v in readout.state_dict().items()}}
    if set(saved["state_dict"]) != set(state):
        raise ValueError("checkpoint state keys differ from the actual encoder/readout")
    for key, value in state.items():
        loaded = saved["state_dict"][key]
        if loaded.shape != value.shape or loaded.dtype != value.dtype or not bool(torch.isfinite(loaded).all()):
            raise ValueError(f"checkpoint shape/dtype/finiteness mismatch: {key}")
    encoder.load_state_dict({k.removeprefix("encoder."): v for k, v in saved["state_dict"].items() if k.startswith("encoder.")}, strict=True)
    readout.load_state_dict({k.removeprefix("readout."): v for k, v in saved["state_dict"].items() if k.startswith("readout.")}, strict=True)
    cfg = encoder.population.config
    grid = dict(asdict(cfg), refractory_steps=cfg.refractory_steps, effective_refractory_time=cfg.effective_refractory)
    if run["population_discretization"] != grid:
        raise ValueError("checkpoint population discretization differs from original receipt")
    encoder.to(context["device"]).eval()
    readout.to(context["device"]).eval()
    row.update(implementation=implementation, population_discretization=grid, original_gpu_test_mse=run["test_mse"],
               original_best_validation_mse=run["best_validation_mse"], checkpoint_identity_verified=True)
    return encoder, readout


def run_grid(context, identity, row, grid, encoder, readout, reference, previous, progress):
    torch, device = context["torch"], context["device"]
    factor, batch = grid["factor"], grid["diagnostic_batch_size"]
    x, y = context["datasets"][row["task"]]
    keep = factor in (1, 2)
    current = None
    sums = dict(hidden_original=0., prediction_original=0., hidden_previous=0., prediction_previous=0.)
    hidden_hash, prediction_hash = hashlib.sha256(), hashlib.sha256()
    grid.update(status="running", trace_examples_submitted=0, trace_examples_completed=0,
                encoder_replay_examples_submitted=0, mse_blocks_completed=0, samples_completed=0,
                maximum_mass_error=0., maximum_escape=0., minimum_mass=1.,
                maximum_absolute_helper_prediction_layout_difference=0.)
    began, meter, energy_started, reset_completed = time.perf_counter(), None, False, False
    try:
        guard(context, identity)
        torch.cuda.synchronize(device)
        torch.cuda.reset_peak_memory_stats(device)
        reset_completed = True
        grid.update(resident_allocated_bytes=torch.cuda.memory_allocated(device), resident_reserved_bytes=torch.cuda.memory_reserved(device))
        meter = context["benchmark"].EnergyCounter(str(device))
        meter.start()
        energy_started = True
        if keep:
            current = (torch.empty((1024, 64, 64), dtype=torch.float32, device="cpu"),
                       torch.empty((1024, 1), dtype=torch.float32, device="cpu"))
        total = torch.zeros((), device=device, dtype=torch.float32)
        for offset in range(0, 1024, 64):
            parts = []
            for start in range(offset, offset+64, batch):
                inputs = torch.from_numpy(x[start:start+batch]).to(device)
                grid["trace_examples_submitted"] += batch
                helper_prediction, hidden, values = context["trace"](encoder, readout, inputs, factor)
                with torch.no_grad():
                    prediction = readout(hidden[:, -1])
                if (prediction.shape != (batch, 1) or hidden.shape != (batch, 64, 64)
                        or not bool(torch.isfinite(prediction).all()) or not bool(torch.isfinite(hidden).all())
                        or not bool(torch.isfinite(helper_prediction).all())):
                    raise FloatingPointError("nonfinite or malformed diagnostic output")
                grid["maximum_absolute_helper_prediction_layout_difference"] = max(
                    grid["maximum_absolute_helper_prediction_layout_difference"],
                    float((prediction-helper_prediction).abs().max()))
                if factor == 1:
                    grid["encoder_replay_examples_submitted"] += batch
                    with torch.no_grad():
                        actual = encoder(inputs, dt=.1)
                        actual_prediction = readout(actual[:, -1])
                    if actual.stride() != hidden.stride():
                        raise ValueError("factor-one sampled trace layout differs from original encoder")
                    torch.testing.assert_close(hidden, actual, rtol=0, atol=0)
                    torch.testing.assert_close(prediction, actual_prediction, rtol=0, atol=0)
                    del actual, actual_prediction
                if not math.isclose(values["effective_refractory"], .3, rel_tol=0, abs_tol=1e-12):
                    raise ValueError("effective refractory duration changed")
                if any(not math.isfinite(values[k]) for k in ("maximum_mass_error", "maximum_escape", "minimum_mass")):
                    raise FloatingPointError("nonfinite mass/escape diagnostic")
                if "config" in grid and grid["config"] != values["config"]:
                    raise ValueError("grid configuration changed between batches")
                grid.update(config=values["config"], effective_refractory=values["effective_refractory"],
                            maximum_mass_error=max(grid["maximum_mass_error"], values["maximum_mass_error"]),
                            maximum_escape=max(grid["maximum_escape"], values["maximum_escape"]),
                            minimum_mass=min(grid["minimum_mass"], values["minimum_mass"]))
                cpu_hidden, cpu_prediction = hidden.cpu(), prediction.cpu()
                hidden_hash.update(cpu_hidden.contiguous().numpy().tobytes())
                prediction_hash.update(cpu_prediction.contiguous().numpy().tobytes())
                if current is not None:
                    current[0][start:start+batch].copy_(cpu_hidden)
                    current[1][start:start+batch].copy_(cpu_prediction)
                if factor != 1:
                    for label, stored in (("original", reference), ("previous", previous)):
                        sums["hidden_"+label] += float((cpu_hidden.double()-stored[0][start:start+batch].double()).square().sum())
                        sums["prediction_"+label] += float((cpu_prediction.double()-stored[1][start:start+batch].double()).square().sum())
                parts.append(prediction)
                grid["trace_examples_completed"] += batch
                del hidden, inputs, cpu_hidden, cpu_prediction, helper_prediction
            prediction_block = torch.cat(parts, dim=0)
            targets = torch.from_numpy(y[offset:offset+64]).to(device)
            total = total+(prediction_block-targets).square().sum()
            grid["mse_blocks_completed"] += 1
            grid["samples_completed"] = offset+64
            del parts, prediction_block, targets
            progress()
        mse = float(total/y.size)
        if not math.isfinite(mse):
            raise FloatingPointError("nonfinite diagnostic MSE")
        if factor == 1 and mse != row["original_gpu_test_mse"]:
            raise ValueError("factor-one GPU test MSE differs exactly from the original GPU receipt")
        grid.update(test_mse=mse, hidden_trace_sha256=hidden_hash.hexdigest(), final_prediction_sha256=prediction_hash.hexdigest(),
                    hidden_trace_rms_change_from_original=math.sqrt(sums["hidden_original"]/(1024*64*64)),
                    final_prediction_rms_change_from_original=math.sqrt(sums["prediction_original"]/1024),
                    hidden_trace_rms_change_from_previous=math.sqrt(sums["hidden_previous"]/(1024*64*64)),
                    final_prediction_rms_change_from_previous=math.sqrt(sums["prediction_previous"]/1024),
                    status="completed")
        guard(context, identity)
    except BaseException as exc:
        grid.update(status="interrupted" if isinstance(exc, (InterruptedError, KeyboardInterrupt)) else "failed",
                    reason=f"{type(exc).__name__}: {exc}", oom=isinstance(exc, torch.cuda.OutOfMemoryError))
        raise
    finally:
        if meter is not None:
            grid["energy"] = context["execution"].close_energy_interval(meter, torch, device, started=energy_started)
        else:
            grid["energy"] = dict(joules_by_physical_counter=None, interval_complete=False,
                                  missing_reason="grid did not reach physical-counter measurement")
            try:
                torch.cuda.synchronize(device)
                grid["energy"]["terminal_cuda_synchronized"] = True
            except Exception as exc:
                grid["energy"].update(terminal_cuda_synchronized=False,
                                       terminal_cuda_sync_error=f"{type(exc).__name__}: {exc}")
        grid["energy"]["scope"] = "observed diagnostic grid wall interval; device/package, not process attribution"
        grid["gpu_physical_energy_counter_measured"] = any(k.startswith("nvml_") for k in (grid["energy"].get("joules_by_physical_counter") or {}))
        grid.update(context["execution"].training_memory_peak(torch, device, reset_completed=reset_completed))
        grid["peak_gpu_scope"] = ("absolute allocator peak since this grid reset; includes resident model and retained allocator cache"
                                  if reset_completed else "current grid reset unavailable; no prior peak reused")
        grid["diagnostic_wall_seconds"] = time.perf_counter()-began
        if grid["status"] == "completed" and not grid["energy"].get("interval_complete", False):
            grid.update(status="failed", reason="terminal CUDA synchronization did not complete")
        grid["peak_gpu_interval_complete"] = grid["status"] == "completed" and grid["peak_gpu_measurement_status"] == "measured"
        progress()
    if grid["status"] != "completed":
        raise RuntimeError(grid["reason"])
    return current


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--execution-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime-profile", type=Path)
    parser.add_argument("--benchmark-runtime-manifest", type=Path)
    parser.add_argument("--launch-runtime-profile", type=Path)
    parser.add_argument("--launch-runtime-entry", type=Path)
    args = parser.parse_args()
    try:
        owner = OutputOwner(args.output)
    except FileExistsError as exc:
        parser.error(str(exc))
    began, context, fatal = time.perf_counter(), None, None
    result = dict(schema_version=1, status="running", requested_b_runs=20, completed_b_runs=0,
                  original_matrix_denominator=170, counts_toward_170_runs=False, training_steps_performed=0,
                  research_convergence_qualified=None, posthoc_threshold=None, checkpoint_selection_performed=False,
                  diagnostic_script_sha256=file_hash(Path(__file__).resolve()), protocol_sha256=PROTOCOL_SHA256,
                  benchmark=str(args.benchmark.resolve()), repo_root=str(args.repo_root.resolve()),
                  execution_config=str(args.execution_config.resolve()),
                  device="cuda:0", cuda_memory_fraction=.5, input_validation_completed=False, cuda_runtime_verified=False,
                  torch_import_attempted=False, torch_preimported="torch" in sys.modules,
                  phase="input_validation", records=[], hardware=None, software=None,
                  microbatch_scope="refined inference only, batch 8 fixed before results; may change floating-point GEMM behavior",
                  mse_scope="FP32 GPU predictions reassembled in original 64-sample blocks, original sum/accumulate order",
                  trace_scope="original 64 input times; external inputs held over substeps; original recurrent drive updates",
                  prediction_scope="readout of the sampled trace's final time slice; same layout as original benchmark",
                  rms_scope="CPU FP64 squared differences accumulated in original sample order; descriptive only",
                  timing_scope="grid time includes trace, exact replay, CPU transfer/RMS, grouped MSE and progress I/O",
                  energy_unmetered_phases=["runtime initialization", "checkpoint loading", "between-grid provenance checks", "final publication"],
                  started_utc=datetime.now(timezone.utc).isoformat())
    for task, model, seed in IDENTITIES:
        result["records"].append(dict(task=task, model=model, seed=seed, status="pending", grids=[
            dict(factor=f, diagnostic_batch_size=BATCHES[f], status="pending") for f in FACTORS]))
    owner.progress(result)
    def interrupted(signum, frame):
        raise InterruptedError(f"received signal {signum}")
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        context = prepare(args, result)
        owner.progress(result)
        if any(r["status"] == "pending" for r in result["records"]):
            result["phase"] = "cuda_setup"
            setup_runtime(context, result)
            owner.progress(result)
        for index, row in enumerate(result["records"]):
            identity = tuple(row[k] for k in ("task", "model", "seed"))
            if row["status"] == "pending":
                guard(context, identity)
                row.update(status="running", phase="checkpoint_loading")
                result.update(phase="checkpoint", current_identity=list(identity))
                owner.progress(result)
                checkpoint_began = time.perf_counter()
                try:
                    encoder, readout = load_checkpoint(context, identity, row)
                    row["checkpoint_load_wall_seconds"] = time.perf_counter()-checkpoint_began
                    reference, previous = None, None
                    for grid in row["grids"]:
                        row["phase"] = f"factor_{grid['factor']}"
                        current = run_grid(context, identity, row, grid, encoder, readout, reference, previous,
                                           lambda: owner.progress(result))
                        if grid["factor"] == 1:
                            reference = current
                        previous = current
                    row.update(status="audited", factor_one_forward_exact=True, factor_one_gpu_mse_exact=True,
                               test_split_sha256=context["report"]["datasets"][row["task"]]["split_sha256"][2])
                    guard(context, identity)
                    del encoder, readout, reference, previous, current
                except BaseException as exc:
                    row.update(status="interrupted" if isinstance(exc, (InterruptedError, KeyboardInterrupt)) else "failed",
                               reason=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
                    if (isinstance(exc, (Invalidated, InterruptedError, KeyboardInterrupt, MemoryError,
                                         context["torch"].cuda.OutOfMemoryError))
                            or any(g.get("energy", {}).get("terminal_cuda_synchronized") is False for g in row["grids"])):
                        raise
                finally:
                    row["diagnostic_wall_seconds"] = time.perf_counter()-checkpoint_began
            for grid in row["grids"]:
                if grid["status"] == "pending":
                    grid.update(status="unavailable", reason="checkpoint did not reach this preregistered grid")
            row["progress_receipt"] = owner.checkpoint(index, row)
            owner.progress(result)
            print(json.dumps({k: row[k] for k in ("task", "model", "seed", "status")}), flush=True)
        guard(context, all_checkpoints=True)
        result["source_inputs_and_checkpoints_unchanged"] = True
    except BaseException as exc:
        fatal = exc
        result.update(reason=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    finally:
        for index, row in enumerate(result["records"]):
            if row["status"] in {"pending", "running"}:
                row.update(status="unavailable", reason="diagnostic stopped before this checkpoint completed")
            for grid in row["grids"]:
                if grid["status"] in {"pending", "running"}:
                    grid.update(status="unavailable", reason="diagnostic did not complete this grid")
            if "progress_receipt" not in row:
                row["progress_receipt"] = owner.checkpoint(index, row)
        if context is not None:
            try:
                guard(context, all_checkpoints=True)
                result["source_inputs_and_checkpoints_unchanged"] = True
            except Exception as exc:
                fatal = exc
                result.update(source_inputs_and_checkpoints_unchanged=False, reason=f"{type(exc).__name__}: {exc}")
        result.update(audited_b_runs=sum(r["status"] == "audited" for r in result["records"]),
                      failed_b_audits=sum(r["status"] == "failed" for r in result["records"]),
                      unavailable_b_audits=sum(r["status"] == "unavailable" for r in result["records"]),
                      interrupted_b_audits=sum(r["status"] == "interrupted" for r in result["records"]))
        result["status"] = ("invalidated" if isinstance(fatal, Invalidated) else
                            "interrupted" if isinstance(fatal, (InterruptedError, KeyboardInterrupt)) else
                            "unavailable" if isinstance(fatal, Unavailable) else "failed" if fatal or result["failed_b_audits"] else
                            "completed" if result["audited_b_runs"] == 20 else "partial" if result["audited_b_runs"] else "unavailable")
        result["accepted_b_audits"] = 0 if result["status"] == "invalidated" else result["audited_b_runs"]
        result.update(phase="finished", finished_utc=datetime.now(timezone.utc).isoformat(),
                      diagnostic_wall_seconds=time.perf_counter()-began)
        owner.finish(result)
        print(json.dumps(dict(output=str(owner.output), status=result["status"], audited=result["audited_b_runs"], requested=20)))
    return 0 if result["status"] == "completed" else 2 if result["status"] in {"unavailable", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
