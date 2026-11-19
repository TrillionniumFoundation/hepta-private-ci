"""Registered CPU implementation scaling on random inputs and random weights.

Prepare performs constructor checks and one small synthetic optimizer preflight.
The full 30-case suite requires completed, audited main and LIF studies. Every
case is a separate single-threaded process; failures remain in the final table.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import resource
import shutil
import statistics
import subprocess
import sys
import time
import traceback


PACKAGE = Path(__file__).resolve().parent
ROOT = PACKAGE.parents[1]
MODELS = ("distribution_free_dual", "two_gates", "transformer")
INPUT_SEED, MODEL_SEED = 743001, 743002


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def read(path):
    return json.loads(Path(path).read_bytes())


def relative(path):
    return str(Path(path).resolve().relative_to(ROOT))


def utc():
    return datetime.now(timezone.utc).isoformat()


def source_mapping():
    paths = [PACKAGE / name for name in ("scaling_eval.py", "runtime_eval.py", "model.py", "distribution_kernel.py")]
    for directory in ("hcsn_free_boundary_v1", "continuous_spiking_network"):
        paths += sorted((ROOT / "experiments" / directory).glob("*.py"))
    return {relative(path): sha(path) for path in paths}


def verify(mapping):
    for path, expected in mapping.items():
        if sha(ROOT / path) != expected:
            raise ValueError("Frozen dependency changed: " + path)


def cases():
    dimensions = [(length, 32, 1, "length") for length in (16, 32, 64, 128, 256, 512)]
    dimensions += [(64, width, depth, "width_depth") for width, depth in ((32, 2), (32, 4), (64, 1), (64, 2))]
    return [dict(case_id=f"{model}_b1_t{length}_w{width}_d{depth}", model=model,
                 batch=1, length=length, width=width, depth=depth, panel=panel)
            for length, width, depth, panel in dimensions for model in MODELS]


def constructor(case):
    return dict(name=case["model"], input_dim=64, output_dim=10,
                width=case["width"], depth=case["depth"], seed=MODEL_SEED)


GATES = [
    ("results/content002/COMPLETE.json", dict(status="completed", expected=176, completed=176, failures=0)),
    ("results/content002/SCHEDULER_EXECUTION.json", dict(returncode=0)),
    ("results/content_analysis002/ANALYSIS.json", dict(expected=176, valid=176, invalid=0)),
    ("results/content_analysis002/EXECUTION.json", dict(returncode=0)),
    ("results/lif_supplement001/COMPLETE.json", dict(status="completed", expected=18, completed=18, failures=0)),
    ("results/lif_analysis001/ANALYSIS.json", dict(status="passed", expected_pairs=18, valid_pairs=18)),
    ("results/lif_cost_receipts001/RECEIPTS.json", dict(schema="hcsn-lif-cost-receipts.v1", status="completed")),
]


def gate_bindings():
    bindings = []
    for path, expected in GATES:
        absolute = PACKAGE / path
        if not absolute.exists():
            raise RuntimeError("Scaling is not authorized to start yet; missing audited gate: " + path)
        data = read(absolute)
        selected = {key: data.get(key) for key in expected}
        if selected != expected:
            raise RuntimeError("Scaling prerequisite failed: " + path)
        # Quality values/predictions in analysis artifacts are neither selected nor used.
        bindings.append(dict(path=relative(absolute), sha256=sha(absolute), required_metadata=selected))
    return bindings


def launch(arguments, directory, wall_limit=None):
    command = [sys.executable, "-m", "experiments.hcsn_distributional_v2.scaling_eval", *arguments]
    environment = os.environ.copy()
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        environment[key] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    started = time.monotonic()
    timed_out = False
    with (directory / "process.log").open("xb") as log:
        child = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)
        while True:
            pid, status, usage = os.wait4(child.pid, os.WNOHANG)
            if pid:
                child.returncode = os.waitstatus_to_exitcode(status)
                break
            if wall_limit is not None and time.monotonic() - started > wall_limit and not timed_out:
                child.kill()
                timed_out = True
            time.sleep(.05)
    return dict(command=command, returncode=child.returncode, complete_child_cpu_seconds=usage.ru_utime + usage.ru_stime,
        child_user_cpu_seconds=usage.ru_utime, child_system_cpu_seconds=usage.ru_stime,
        wall_seconds=time.monotonic() - started, peak_rss_kib_linux=usage.ru_maxrss,
        wall_limit_reached=timed_out, signal=(-child.returncode if child.returncode < 0 else None),
        process_log_sha256=sha(directory / "process.log"),
        measurement="Linux wait4 for the complete child process tree, including startup/imports/setup/exit; body timers are nested")


def runtime():
    import numpy as np
    import torch
    from torch.nn import functional as F
    from .runtime_eval import build_model
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    return np, torch, F, build_model


def array_record(array):
    return dict(shape=list(array.shape), dtype=str(array.dtype), bytes=array.nbytes,
                sha256=hashlib.sha256(array.tobytes(order="C")).hexdigest())


def benchmark(directory, case, sources, protocol_sha, repeats, imported=None):
    np, torch, F, build_model = imported if imported is not None else runtime()
    generator = torch.Generator().manual_seed(INPUT_SEED)
    full_x = torch.randn(1, 512, 64, generator=generator, dtype=torch.float32)
    full_dt = .2 + torch.rand(1, 512, generator=generator, dtype=torch.float32)
    full_labels = torch.randint(10, (1, 512), generator=generator)
    length = case["length"]
    inputs, durations, labels = full_x[:, :length].clone(), full_dt[:, :length].clone(), full_labels[:, :length].clone()
    arrays = dict(x=inputs.numpy(), dt=durations.numpy(), labels=labels.numpy())
    np.savez(directory / "INPUTS.npz", **arrays)
    model = build_model(**constructor(case))
    counts = model.counts()
    if "registered_counts" in case and counts != case["registered_counts"]:
        raise ValueError("Actual parameter counts changed from constructor preflight")
    if "registered_model_config" in case and model.config != case["registered_model_config"]:
        raise ValueError("Actual full model configuration changed from constructor preflight")
    initial = {key: value.detach().cpu().numpy().copy() for key, value in model.state_dict().items()}
    np.savez(directory / "INITIAL.npz", **initial)
    identity = dict(schema="hcsn-v2-scaling-case-identity.v1", case_id=case["case_id"], status="constructed",
        constructor=constructor(case), full_model_config=model.config, actual_counts=counts,
        protocol_sha256=protocol_sha, source_files_sha256=sources, input_seed=INPUT_SEED,
        input_arrays={name: array_record(value) for name, value in arrays.items()},
        inputs_sha256=sha(directory / "INPUTS.npz"), initial_sha256=sha(directory / "INITIAL.npz"),
        initial_arrays={name: array_record(value) for name, value in initial.items()},
        device="cpu", dtype="float32", torch_version=torch.__version__, numpy_version=np.__version__,
        python_version=platform.python_version(), visible_logical_cpus=os.cpu_count(),
        torch_threads=torch.get_num_threads(), torch_interop_threads=torch.get_num_interop_threads())
    write(directory / "IDENTITY.json", identity)
    optimizer = torch.optim.Adam(model.parameters(), lr=.001)
    records = []

    def execute(training, phase, index):
        model.train(training)
        rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        cpu, wall = time.process_time(), time.monotonic()
        if training:
            optimizer.zero_grad(set_to_none=True)
            logits = model(inputs, durations, return_sequence=True, return_aux=False)
            loss = F.cross_entropy(logits.flatten(0, 1), labels.flatten())
            if not bool(torch.isfinite(loss)) or not bool(torch.isfinite(logits).all()):
                raise FloatingPointError("Nonfinite synthetic training output/loss")
            loss.backward()
            if any(p.grad is not None and not bool(torch.isfinite(p.grad).all()) for p in model.parameters()):
                raise FloatingPointError("Nonfinite gradient")
            gradient_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 2., error_if_nonfinite=True)
            optimizer.step()
            if any(not bool(torch.isfinite(p).all()) for p in model.parameters()):
                raise FloatingPointError("Nonfinite updated parameter")
            if any(isinstance(v, torch.Tensor) and not bool(torch.isfinite(v).all())
                   for state in optimizer.state.values() for v in state.values()):
                raise FloatingPointError("Nonfinite Adam state")
        else:
            with torch.inference_mode():
                logits = model(inputs, durations, return_sequence=True, return_aux=False)
            if not bool(torch.isfinite(logits).all()):
                raise FloatingPointError("Nonfinite inference output")
        if tuple(logits.shape) != (1, length, 10):
            raise ValueError("Unexpected full-sequence output shape")
        row = dict(phase=phase, repetition=index, operation="optimizer_step" if training else "forward",
            cpu_seconds=time.process_time() - cpu, wall_seconds=time.monotonic() - wall,
            process_peak_rss_kib_before=rss_before,
            process_peak_rss_kib_after=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            finite_checks_passed=True)
        if training:
            row.update(loss=float(loss.detach()), gradient_norm_before_clip=float(gradient_norm))
        records.append(row)
        write(directory / f"MEASURE_{len(records):02d}.json", row)
        return row

    warmup = [execute(False, "warmup", 0), execute(True, "warmup", 0)]
    forward = [execute(False, "measured", index) for index in range(repeats)]
    updates = [execute(True, "measured", index) for index in range(repeats)]
    parameter_changes = sum(not np.array_equal(initial[key], value.detach().cpu().numpy())
                            for key, value in model.state_dict().items())
    adam_steps = sorted({int(state["step"]) for state in optimizer.state.values()})
    if parameter_changes == 0 or adam_steps != [repeats + 1]:
        raise ValueError("The supposedly complete optimizer steps did not update the model")
    verify(sources)
    result = dict(schema="hcsn-v2-scaling-case.v1", status="completed", **case,
        protocol_sha256=protocol_sha, source_files_sha256=sources, actual_counts=counts,
        identity_sha256=sha(directory / "IDENTITY.json"), warmup=warmup, forward=forward, optimizer_step=updates,
        forward_cpu_median=statistics.median(row["cpu_seconds"] for row in forward),
        forward_wall_median=statistics.median(row["wall_seconds"] for row in forward),
        optimizer_cpu_median=statistics.median(row["cpu_seconds"] for row in updates),
        optimizer_wall_median=statistics.median(row["wall_seconds"] for row in updates),
        peak_process_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        changed_state_tensors=parameter_changes, completed_adam_steps=adam_steps,
        initialization_and_input_generation_outside_body_timers=True,
        scope="Random-weight synthetic full-sequence CPU diagnostic; no content dataset, quality, GPU or energy inference")
    write(directory / "RESULT.json", result)
    return result


def preflight(directory):
    request = read(directory / "REQUEST.json")
    verify(request["source_files_sha256"])
    imported = runtime()
    np, torch, _, build_model = imported
    configurations = cases()
    if len(configurations) != 30 or len({case["case_id"] for case in configurations}) != 30:
        raise AssertionError("The exact 30 configurations are not unique")
    profiles = []
    for case in configurations:
        model = build_model(**constructor(case))
        counts = model.counts()
        if counts["total"] != sum(p.numel() for p in model.parameters() if p.requires_grad):
            raise AssertionError("Constructor parameter count mismatch")
        if counts["total"] != counts["frontend"] + counts["backbone"] + counts["readout"]:
            raise AssertionError("Parameter groups do not cover the instantiated model")
        profiles.append(dict(**case, registered_counts=counts, registered_model_config=model.config))
        del model
    small = directory / "small_case"
    small.mkdir()
    result = benchmark(small, profiles[0], request["source_files_sha256"], None, repeats=1, imported=imported)
    verify(request["source_files_sha256"])
    write(directory / "RESULTS.json", dict(schema="hcsn-v2-scaling-preflight.v1", status="passed",
        expected_cases=30, constructor_profiles=profiles, small_case_id=profiles[0]["case_id"],
        small_case_result_sha256=sha(small / "RESULT.json"), small_case_optimizer_steps=result["completed_adam_steps"],
        source_files_sha256=request["source_files_sha256"], self_cpu_seconds_through_cutoff=time.process_time(),
        no_heldout_data=True, no_content_training=True, scope="30 constructor/count checks and exactly one small random-input preflight"))


def prepare(output, preflight_output, protocol_path):
    if output.exists() or preflight_output.exists() or protocol_path.exists():
        raise FileExistsError("Preparation requires new study, preflight and protocol paths")
    preflight_output.mkdir(parents=True)
    mapping = source_mapping()
    write(preflight_output / "REQUEST.json", dict(source_files_sha256=mapping, expected_cases=30, created_utc=utc()))
    failure = None
    try:
        execution = launch(["_preflight", "--output", str(preflight_output)], preflight_output, wall_limit=180)
        write(preflight_output / "EXECUTION.json", execution)
        if execution["returncode"] != 0:
            raise RuntimeError("Small synthetic preflight failed; evidence is retained")
        result = read(preflight_output / "RESULTS.json")
        if result["status"] != "passed" or len(result["constructor_profiles"]) != 30:
            raise RuntimeError("Constructor/preflight contract did not pass")
        protocol = dict(schema="hcsn-v2-scaling-protocol.v1", study_id="scaling001", registered_utc=utc(),
            cases=result["constructor_profiles"], expected_cases=30, source_files_sha256=mapping,
            preflight=dict(path=relative(preflight_output), results_sha256=sha(preflight_output / "RESULTS.json"),
                           execution_sha256=sha(preflight_output / "EXECUTION.json")),
            randomness=dict(input_seed=INPUT_SEED, model_seed=MODEL_SEED, maximum_length=512,
                            inputs="One shared master random sequence; each T is its prefix, identical across models/width/depth"),
            measurement=dict(device="cpu", dtype="float32", batch=1, input_features=64, classes=10,
                workers=1, thread_count=1, warmup_forward=1, warmup_optimizer_step=1,
                measured_forward=3, measured_optimizer_step=3,
                order="warmup forward, warmup optimizer, three forwards, three optimizer steps",
                loss="mean cross-entropy on random labels at every sequence position",
                optimizer="Adam", learning_rate=.001, gradient_clip_norm=2.,
                optimizer_scope="zero_grad, forward, loss, backward, gradient finite check, clipping, Adam step, parameter/optimizer-state finite checks",
                inference_scope="full-sequence inference_mode forward plus output finite/shape checks; fresh state each call",
                peak_rss_scope="whole-worker Linux wait4 high-water RSS; operation snapshots are cumulative process peaks",
                startup_scope="Full worker wait4 includes imports, matching configuration search, inputs, warmup, measurements, checks, serialization and exit; nested body costs are not added",
                worker_cpu_limit_seconds=300, worker_wall_limit_seconds=600,
                failures="Preserve partial measurements, nonzero/signal/timeout receipt and explicit FAILURE; attempt all registered configurations"),
            run_after=[dict(path=relative(PACKAGE / path), required_metadata=fields) for path, fields in GATES],
            limitations=["30 CPU implementation points with random weights/labels; no content quality comparison",
                "Actual parameters and chosen internal widths reported; no imposed 3% parameter-equivalence claim",
                "No GPU, energy, foundation-model, multi-device or equal-quality extrapolation",
                "Three repeats are descriptive; no fitted asymptotic scaling law"],
            content_protocols_unchanged=True, content_data_or_checkpoints_used=False)
        verify(mapping)
        write(protocol_path, protocol)
        output.mkdir(parents=True)
        snapshot = output / "source"
        for path in mapping:
            target = snapshot / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / path, target)
        shutil.copyfile(protocol_path, snapshot / protocol_path.name)
        write(output / "REGISTRATION.json", dict(schema="hcsn-v2-scaling-registration.v1", status="registered_not_run",
            protocol_path=relative(protocol_path), protocol_sha256=sha(protocol_path), expected_cases=30,
            source_files_sha256=mapping, preflight=protocol["preflight"], registered_utc=protocol["registered_utc"]))
    except BaseException as error:
        failure = dict(type=type(error).__name__, message=str(error), traceback=traceback.format_exc())
        raise
    finally:
        write(preflight_output / "PREPARE_EXECUTION.json", dict(status="failed" if failure else "completed",
            failure=failure, coordinator_whole_self_cpu_seconds_through_cutoff=time.process_time(),
            scope="Preparation supervisor self CPU including registration; preflight complete child is separate, not included"))


def registered(protocol_path, output):
    protocol, registration = read(protocol_path), read(output / "REGISTRATION.json")
    if (protocol["schema"] != "hcsn-v2-scaling-protocol.v1" or sha(protocol_path) != registration["protocol_sha256"] or
            protocol["source_files_sha256"] != registration["source_files_sha256"] or
            protocol["expected_cases"] != 30 or len(protocol["cases"]) != 30 or
            [{key: item[key] for key in cases()[0]} for item in protocol["cases"]] != cases()):
        raise ValueError("Scaling registration differs from the frozen 30-case contract")
    verify(protocol["source_files_sha256"])
    return protocol


def case_worker(protocol_path, output, case_id):
    protocol = registered(protocol_path, output)
    authorization = read(output / "RUN_AUTHORIZATION.json")
    if authorization["protocol_sha256"] != sha(protocol_path) or authorization["gates"] != gate_bindings():
        raise ValueError("Full scaling workers require unchanged audited prerequisite gates")
    case = next(item for item in protocol["cases"] if item["case_id"] == case_id)
    directory = output / "cases" / case_id
    limit = protocol["measurement"]["worker_cpu_limit_seconds"]
    resource.setrlimit(resource.RLIMIT_CPU, (limit, limit + 5))
    try:
        benchmark(directory, case, protocol["source_files_sha256"], sha(protocol_path), repeats=3)
    except BaseException as error:
        write(directory / "FAILURE.json", dict(case_id=case_id, type=type(error).__name__, message=str(error),
            traceback=traceback.format_exc(), protocol_sha256=sha(protocol_path),
            source_files_sha256=protocol["source_files_sha256"], partial_measurement_files=sorted(p.name for p in directory.glob("MEASURE_*.json"))))
        raise


def summary_report(output, protocol, records):
    rows = []
    for record in records:
        directory = ROOT / record["receipt_path"]
        directory = directory.parent
        result_path = directory / "RESULT.json"
        result = read(result_path) if record["returncode"] == 0 and result_path.exists() else None
        identity = read(directory / "IDENTITY.json")
        case = next(item for item in protocol["cases"] if item["case_id"] == record["case_id"])
        rows.append(dict(**{key: case[key] for key in cases()[0]}, returncode=record["returncode"],
            actual_counts=identity["actual_counts"],
            registered_counts=case["registered_counts"],
            forward_cpu_median=result["forward_cpu_median"] if result else None,
            optimizer_cpu_median=result["optimizer_cpu_median"] if result else None,
            forward_wall_median=result["forward_wall_median"] if result else None,
            optimizer_wall_median=result["optimizer_wall_median"] if result else None,
            worker_cpu_seconds=record["complete_child_cpu_seconds"], worker_wall_seconds=record["wall_seconds"],
            worker_peak_rss_kib=record["peak_rss_kib_linux"], receipt_sha256=sha(directory / "EXECUTION.json"),
            result_sha256=sha(result_path) if result else None))
    length_changes = []
    for model in MODELS:
        selected = [row for row in rows if row["model"] == model and row["panel"] == "length"]
        base = next(row for row in selected if row["length"] == 16)
        for row in selected:
            valid = row["returncode"] == base["returncode"] == 0
            length_changes.append(dict(model=model, length=row["length"], length_ratio_to_16=row["length"] / 16,
                forward_cpu_ratio_to_16=row["forward_cpu_median"] / base["forward_cpu_median"] if valid else None,
                optimizer_cpu_ratio_to_16=row["optimizer_cpu_median"] / base["optimizer_cpu_median"] if valid else None))
    write(output / "SUMMARY.json", dict(schema="hcsn-v2-scaling-summary.v1", rows=rows,
        measured_fixed_width_depth_changes=length_changes, interpretation="Descriptive measured CPU ratios only; no quality/GPU/energy/asymptotic claim"))
    lines = ["# CPU implementation scale diagnostic", "", "Random weights and one shared synthetic input sequence; B=1, input64, output10, CPU float32. Each process performs one forward and one Adam warmup, then three forwards and three complete optimizer steps. All successful and failed configurations remain below.", "",
        "Body CPU/wall includes all declared numerical checks. Full worker wait4 additionally includes imports, parameter-matching constructor work, input/weight serialization, warmup and exit. These scopes are nested. RSS is the whole-process high-water mark, not isolated activation memory.", "",
        "| Model | T | Width | Depth | Actual total parameters | Forward CPU median (s) | Adam CPU median (s) | Forward wall median (s) | Adam wall median (s) | Full worker CPU (s) | Peak RSS (KiB) | Exit |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in rows:
        values = [row[key] for key in ("forward_cpu_median", "optimizer_cpu_median", "forward_wall_median", "optimizer_wall_median")]
        formatted = ["failed" if value is None else f"{value:.6f}" for value in values]
        count = row["actual_counts"]["total"] if row["actual_counts"] else "not observed"
        lines.append(f"| {row['model']} | {row['length']} | {row['width']} | {row['depth']} | {count} | " + " | ".join(formatted) + f" | {row['worker_cpu_seconds']:.6f} | {row['worker_peak_rss_kib']} | {row['returncode']} |")
    lines += ["", "## Measured T changes at width32/depth1", "", "| Model | T | T/16 | Forward CPU / T16 | Adam CPU / T16 |", "| --- | ---: | ---: | ---: | ---: |"]
    for row in length_changes:
        ratios = ["failed" if row[key] is None else f"{row[key]:.4f}" for key in ("forward_cpu_ratio_to_16", "optimizer_cpu_ratio_to_16")]
        lines.append(f"| {row['model']} | {row['length']} | {row['length_ratio_to_16']:g} | " + " | ".join(ratios) + " |")
    lines += ["", "Actual full counts, chosen internal baseline widths and physical configuration are retained in each IDENTITY/RESULT and the registration. No 3% parameter-equivalence assumption is imposed on this panel. The experiment does not estimate content quality, equal-quality training throughput, GPU behavior, energy, foundation-model feasibility or an asymptotic scaling exponent. It measures these 30 CPU configurations only.", ""]
    (output / "REPORT.md").write_text("\n".join(lines))


def suite(protocol_path, output):
    protocol = registered(protocol_path, output)
    authorization = read(output / "RUN_AUTHORIZATION.json")
    if authorization["gates"] != gate_bindings():
        raise ValueError("Audited prerequisite gate identity changed")
    records = []
    (output / "cases").mkdir()
    for case in protocol["cases"]:
        verify(protocol["source_files_sha256"])
        directory = output / "cases" / case["case_id"]
        directory.mkdir()
        execution = launch(["_case", "--protocol", str(protocol_path), "--output", str(output), "--case-id", case["case_id"]],
                           directory, wall_limit=protocol["measurement"]["worker_wall_limit_seconds"])
        execution.update(case_id=case["case_id"], model=case["model"], batch=1, length=case["length"],
            width=case["width"], depth=case["depth"], protocol_sha256=sha(protocol_path),
            source_files_sha256=protocol["source_files_sha256"], receipt_path=relative(directory / "EXECUTION.json"))
        if execution["returncode"] == 0 and not (directory / "RESULT.json").exists():
            raise RuntimeError("Successful worker has no result")
        if execution["returncode"] != 0:
            for leaf in ("FAILURE.json", "IDENTITY.json"):
                path = directory / leaf
                if path.exists():
                    try:
                        read(path)
                    except (ValueError, UnicodeError):
                        path.rename(directory / (leaf + ".incomplete"))
        if execution["returncode"] != 0 and not (directory / "FAILURE.json").exists():
            write(directory / "FAILURE.json", dict(case_id=case["case_id"], type="worker_exit_or_resource_limit",
                returncode=execution["returncode"], wall_limit_reached=execution["wall_limit_reached"], signal=execution["signal"],
                protocol_sha256=sha(protocol_path), source_files_sha256=protocol["source_files_sha256"],
                partial_measurement_files=sorted(p.name for p in directory.glob("MEASURE_*.json"))))
        if not (directory / "IDENTITY.json").exists():
            write(directory / "IDENTITY.json", dict(schema="hcsn-v2-scaling-case-identity.v1", case_id=case["case_id"],
                status="failed_before_identity", actual_counts=None, constructor=constructor(case),
                protocol_sha256=sha(protocol_path), source_files_sha256=protocol["source_files_sha256"]))
        write(directory / "EXECUTION.json", execution)
        records.append(execution)
        print(json.dumps(dict(completed_cases=len(records), expected_cases=30, case_id=case["case_id"], returncode=execution["returncode"])), flush=True)
    verify(protocol["source_files_sha256"])
    summary_report(output, protocol, records)
    failed = sum(record["returncode"] != 0 for record in records)
    write(output / "COMPLETE.json", dict(schema="hcsn-v2-scaling-complete.v1", status="completed",
        expected_cases=30, completed_cases=len(records), successful_cases=len(records)-failed, failed_cases=failed,
        all_cases_successful=failed == 0, records=records, protocol_sha256=sha(protocol_path),
        source_files_sha256=protocol["source_files_sha256"], complete_worker_cpu_seconds=math.fsum(r["complete_child_cpu_seconds"] for r in records),
        coordinator_self_cpu_seconds_through_cutoff=time.process_time(), summary_sha256=sha(output / "SUMMARY.json"),
        report_sha256=sha(output / "REPORT.md"), completed_utc=utc(),
        scope="All 30 cases attempted and receipted; status completed denotes coverage, while individual failures remain explicit. Worker totals are nested in SUITE_EXECUTION."))


def run(protocol_path, output, run_after):
    if run_after != "audited-main-and-lif":
        raise ValueError("Use --run-after audited-main-and-lif; formal suite cannot bypass completion gates")
    protocol = registered(protocol_path, output)
    gates = gate_bindings()
    write(output / "RUN_AUTHORIZATION.json", dict(protocol_sha256=sha(protocol_path), source_files_sha256=protocol["source_files_sha256"],
        gates=gates, started_utc=utc(), content_quality_values_used=False))
    execution = launch(["_suite", "--protocol", str(protocol_path), "--output", str(output)], output)
    execution.update(schema="hcsn-v2-scaling-suite-execution.v1", protocol_sha256=sha(protocol_path),
        source_files_sha256=protocol["source_files_sha256"],
        complete_receipt_sha256=sha(output / "COMPLETE.json") if (output / "COMPLETE.json").exists() else None,
        supervisor_self_cpu_seconds_through_cutoff=time.process_time(),
        accounting="Complete suite child CPU includes coordinator, all workers, report and exit; worker/self/body sums inside that child are nested. Only this supervisor's self CPU is separate.")
    write(output / "SUITE_EXECUTION.json", execution)
    if execution["returncode"]:
        raise SystemExit(execution["returncode"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "_preflight", "_suite", "_case"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=PACKAGE / "SCALING001_PROTOCOL.json")
    parser.add_argument("--preflight-output", type=Path)
    parser.add_argument("--run-after", choices=("audited-main-and-lif",))
    parser.add_argument("--case-id")
    args = parser.parse_args()
    output, protocol = args.output.resolve(), args.protocol.resolve()
    if args.action == "prepare":
        if args.preflight_output is None:
            raise ValueError("Preparation requires a new --preflight-output directory")
        prepare(output, args.preflight_output.resolve(), protocol)
    elif args.action == "run":
        run(protocol, output, args.run_after)
    elif args.action == "_preflight":
        preflight(output)
    elif args.action == "_suite":
        suite(protocol, output)
    else:
        case_worker(protocol, output, args.case_id)


if __name__ == "__main__":
    main()
