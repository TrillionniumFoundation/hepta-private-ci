"""Fixed H2/H3 TRAIN collection, reusing frozen T11 artifacts; never qualification."""

import time

CPU_START = time.process_time_ns()
WALL_START = time.perf_counter_ns()

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import resource
import subprocess
import sys
import tarfile
import traceback
import zipfile


ROOT = Path(__file__).resolve().parents[2]
STAGE = ROOT / "training_diagnostics/dynamic-h2"
OUTPUT = ROOT / "runs/codex-cloud-dynamic-train-headroom-h2"
PATHS = ("NC-full", "NC-go", "NC-stop", "N-full")
SEEDS = (11, 23, 47)
ENVIRONMENT = "ccarenv_b64_Y2NhcmVudl8wOGNhYzlkMjdjYjg4MTkxOWJkMDY0MGIyMDBhYTA5OA"


def experiment_paths(experiment):
    if type(experiment) is not str or experiment not in ("h2", "h3"):
        raise ValueError("only fixed h2/h3 diagnostic identities are supported")
    if experiment == "h2":
        return STAGE, OUTPUT
    return ROOT / "training_diagnostics/dynamic-h3", ROOT / "runs/codex-cloud-dynamic-train-headroom-h3"


def dependency_imports(experiment):
    """The actual collect/smoke initialization; no data or model is constructed."""
    experiment_paths(experiment)
    sys.path.insert(0, str(ROOT))
    import numpy as np
    from independent.accounting import BudgetExceeded, WorkLedger
    from independent.data_v2 import dataset, manifest
    from independent.evaluation import _controller, measure, output_work
    from independent.inference import FrozenGenerator
    from independent.learning import CachedObjective
    from independent.native import NativeGenerator
    from model import JointModel
    ledger = WorkLedger("H2-TRAIN-RD-not-qualification" if experiment == "h2" else
                        "H3-TRAIN-RD-not-qualification", total_cap=4_000_000_000)
    return (np, BudgetExceeded, WorkLedger, dataset, manifest, _controller, measure,
            output_work, FrozenGenerator, CachedObjective, NativeGenerator, JointModel, ledger)


def startup_smoke(experiment):
    dependencies = dependency_imports(experiment)
    ledger = dependencies[-1]
    return {"schema": "hepta.headroom-startup-smoke.v1", "experiment_id": experiment,
            "outcome": "completed", "arm": ledger.arm, "operator_cap": ledger.total_cap,
            "known_consumed_units": ledger.consumed_units, "dataset_constructions": 0,
            "model_loads": 0, "service_calls": 0, "START_consumed": False,
            "worker_cpu_ns": cpu() - CPU_START, "worker_wall_ns": time.perf_counter_ns() - WALL_START}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cpu():
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return time.process_time_ns() + round((children.ru_utime + children.ru_stime) * 1e9)


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value, *, exclusive=True):
    with Path(path).open("x" if exclusive else "w", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
        stream.write("\n")


def local(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ValueError("nonlocal frozen artifact path")
    result = ROOT / path
    if result.is_symlink() or not result.resolve().is_relative_to(ROOT):
        raise ValueError("nonlocal frozen artifact")
    return result


def identity(path):
    return {"file": str(Path(path).relative_to(ROOT)), "sha256": sha(path), "bytes": Path(path).stat().st_size}


def verify_protected(frozen):
    protected = frozen["protected_sha256"]
    if not isinstance(protected, dict) or not protected:
        raise ValueError("previous formal-evidence protection inventory required")
    if (ROOT / "independent/efficient-r2-test-opened.json").exists():
        raise ValueError("r2 formal data must remain sealed")
    for name, expected in protected.items():
        if sha(local(name)) != expected:
            raise ValueError("protected previous evidence changed: " + name)


def source_guard(freeze_path, *, experiment="h2"):
    stage, output = experiment_paths(experiment)
    if Path(freeze_path).resolve() != stage / f"frozen-{experiment}.json":
        raise ValueError(f"fixed {experiment.upper()} freeze path required")
    frozen, protocol = read(freeze_path), read(stage / "protocol.json")
    if frozen.get("experiment_id", "h2") != experiment:
        raise ValueError("frozen diagnostic identity changed")
    if frozen["environment_id"] != ENVIRONMENT:
        raise ValueError(f"{experiment.upper()} requires the original selected Codex cloud environment identity")
    if (protocol["schema"] != f"hepta.TRAIN-headroom-{experiment}.protocol.v1"
            or protocol["diagnostic_id"] != f"dynamic-train-headroom-{experiment}"
            or protocol["qualification"] is not False
            or protocol["model_seeds"] != list(SEEDS)
            or protocol["output"] != str(output.relative_to(ROOT))
            or protocol["start_marker"] != str((stage / "START.json").relative_to(ROOT))
            or protocol["budgets"]["cpu_seconds"] != 30.0
            or protocol["budgets"]["operator_units"] != 4_000_000_000
            or protocol["budgets"]["artifact_bytes"] != 32 * 1024**2
            or protocol["dataset"]["split"] != "train"
            or protocol["dataset"]["rows"] != 3072
            or protocol["dataset"]["profile"]["seeds"]["train"] != 130101
            or protocol["service"]["paths"] != list(PATHS)
            or protocol["service"]["calls"] != 36
            or protocol["service"]["repeats"] != 3
            or protocol["service"]["rows_per_call"] != 3072
            or protocol["service"]["sample_seed_formula"] != "seed + 1009 * repeat"
            or protocol["service"]["batch_size"] != 64
            or protocol["service"]["output_codec_profile"] != "rowwise-png-v1"
            or protocol["content_check"]["absolute_tolerance"] != 1e-12
            or protocol["content_check"]["relative_tolerance"] != 0.0):
        raise ValueError(f"fixed {experiment.upper()} TRAIN collection scope changed")
    paths = list(ROOT.glob("*.py")) + list((ROOT / "independent").glob("*.py"))
    paths += list((ROOT / "independent").glob("*.c"))
    sources = {str(path.relative_to(ROOT)): sha(path) for path in sorted(paths)}
    if (frozen["sources"] != sources or frozen["protocol_sha256"] != sha(stage / "protocol.json")
            or frozen["script_sha256"] != sha(__file__)
            or frozen["analysis_sha256"] != sha(Path(__file__).with_name("analyze.py"))):
        raise ValueError(f"frozen {experiment.upper()} runtime/protocol/script identity changed")
    bound = {**sources, str((stage / "protocol.json").relative_to(ROOT)): frozen["protocol_sha256"],
             str(Path(__file__).resolve().relative_to(ROOT)): frozen["script_sha256"],
             str(Path(__file__).with_name("analyze.py").resolve().relative_to(ROOT)): frozen["analysis_sha256"],
             str((stage / "PROTOCOL.md").relative_to(ROOT)): sha(stage / "PROTOCOL.md")}
    for name, expected in bound.items():
        committed = subprocess.check_output(["git", "show", frozen["source_commit"]
            + ":qualification/joint-generation/" + name], cwd=ROOT)
        if hashlib.sha256(committed).hexdigest() != expected:
            raise ValueError(f"commit all frozen {experiment.upper()} bytes first: " + name)
    for name, expected in protocol["dataset"]["source_hashes"].items():
        if sources.get(name) != expected:
            raise ValueError("original Q1 TRAIN construction source changed: " + name)
    for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        if os.environ.get(key) != "1":
            raise ValueError("fixed single-thread runtime required: " + key)
    verify_protected(frozen)
    return frozen, protocol


def safe_restore(protocol, out):
    """Restore only exact regular members; never tar.extract or read VAL scores."""
    archive_spec = protocol["archive"]
    archive, index_path = local(archive_spec["path"]), local(archive_spec["original_files_path"])
    if sha(archive) != archive_spec["sha256"] or sha(index_path) != archive_spec["original_files_sha256"]:
        raise ValueError("T11 archive or original inventory changed")
    index = read(index_path)["files"]
    wanted = {row["member"]: row["sha256"] for row in protocol["models"] + protocol["controllers"]}
    wanted[protocol["native_library"]["archive_member"]] = protocol["native_library"]["sha256"]
    selection_name = archive_spec["selection_member"]
    wanted[selection_name] = archive_spec["selection_sha256"]
    if len(wanted) != 11:
        raise ValueError("exact six models, three heads, one library and selection required")
    restored = {}
    with tarfile.open(archive, "r:gz") as source:
        names = source.getnames()
        for name, expected in wanted.items():
            member_path = PurePosixPath(name)
            if member_path.is_absolute() or ".." in member_path.parts or names.count(name) != 1:
                raise ValueError("unsafe or ambiguous T11 archive member")
            member = source.getmember(name)
            if (not member.isfile() or member.size != index[name]["bytes"]
                    or index[name]["sha256"] != expected or member.size > 16 * 1024**2):
                raise ValueError("T11 member geometry or hash declaration changed")
            payload = source.extractfile(member).read()
            if hashlib.sha256(payload).hexdigest() != expected:
                raise ValueError("T11 member bytes changed: " + name)
            if name == selection_name:
                selected = json.loads(payload)
            else:
                path = out / "reused-t11" / member_path
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as stream:
                    stream.write(payload)
                restored[name] = path
    for row in protocol["models"]:
        matches = [value for value in selected["selected"] if value["seed"] == row["seed"]
                   and value["system"] == ("ndu_control" if row["role"] == "NC" else "ndu")]
        if len(matches) != 1 or any(matches[0][key] != row[field] for key, field in (
                ("model_file", "member"), ("model_sha256", "sha256"),
                ("model_digest", "model_digest"), ("updates", "updates"))):
            raise ValueError("frozen selected T11 model identity changed")
    for row in protocol["controllers"]:
        match = next(value for value in selected["selected"]
                     if value["seed"] == row["seed"] and value["system"] == "ndu_control")
        if match["controller_file"] != row["member"] or match["controller_sha256"] != row["sha256"]:
            raise ValueError("frozen selected T11 controller changed")
    if any(selected["system_cost"][system]["cpu_seconds"] != protocol["cost"][key]
           for system, key in (("ndu_control", "historical_NC_build_cpu_seconds"),
                               ("ndu", "historical_N_build_cpu_seconds"))):
        raise ValueError("historical complete build cost changed")
    if selected["common"]["reference_full_cpu_ns"] != protocol["cost"]["reference_full_cpu_ns"]:
        raise ValueError("historical TRAIN CPU reference changed")
    # Persist only identity and complete build-cost evidence, never validation results.
    write(out / "T11-binding.json", {"models": protocol["models"], "controllers": protocol["controllers"],
        "archive": archive_spec, "reference_full_cpu_ns": selected["common"]["reference_full_cpu_ns"],
        "complete_build_cpu_seconds": {role: selected["system_cost"][system]["cpu_seconds"]
            for role, system in (("NC", "ndu_control"), ("N", "ndu"))}})
    return restored


def call_order():
    for repeat in range(3):
        for index, seed in enumerate(SEEDS):
            shift = (repeat + index) % len(PATHS)
            for path in PATHS[shift:] + PATHS[:shift]:
                yield repeat, seed, path, seed + 1009 * repeat


def accounting_summary(ledger, attempted_calls):
    """Keep unsettled service reservations separate from known actual charges."""
    known = 0 if ledger is None else ledger.consumed_units
    unsettled = [row for row in attempted_calls if row["accounting_status"] != "known_actual"]
    upper = sum(row["reserved_operator_units"] for row in unsettled)
    return {"accounting_complete": not unsettled, "known_consumed_units": known,
            "unsettled_reserved_operator_units_upper_bound": upper,
            "possible_consumed_units_interval": {"lower_inclusive": known, "upper_inclusive": known + upper},
            "unsettled_accounting_scope": "Known charges <= actual total including interrupted services <= known charges plus unsettled prescribed-path reservations. Reservations are upper bounds only, never actual charges or budget credits; failure is terminal."}


def collect(freeze_path, *, experiment="h2"):
    stage, output_root = experiment_paths(experiment)
    frozen, protocol = source_guard(freeze_path, experiment=experiment)
    if output_root.exists():
        raise ValueError(f"fixed {experiment.upper()} output already exists; no repeat or output alias")
    start = {"schema": f"hepta.dynamic-train-headroom-{experiment}-start.v1", "protocol_sha256": sha(stage / "protocol.json"),
        "freeze_sha256": sha(freeze_path), "script_sha256": sha(__file__), "source_commit": frozen["source_commit"],
        "argv": sys.argv, "started_unix_ns": time.time_ns(), "output": str(output_root), "qualification": False,
        "environment_id": ENVIRONMENT, "cwd": str(ROOT), "experiment_id": experiment}
    write(stage / "START.json", start)
    result = {"schema": f"hepta.dynamic-train-headroom-{experiment}.v1", "qualification": False, "experiment_id": experiment,
        "prior_H2_failure": protocol.get("prior_H2_failure"),
        "prior_cost_policy": "H2 startup failure costs remain separately retained; H3 has a fresh unchanged30s/4B cap, without refund or erased research cost.",
        "protocol_sha256": start["protocol_sha256"], "freeze_sha256": start["freeze_sha256"],
        "script_sha256": start["script_sha256"], "source_commit": frozen["source_commit"],
        "environment_id": ENVIRONMENT, "cwd": str(ROOT), "thread_environment": {key: os.environ.get(key)
            for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")},
        "execution_commit": None, "phases": [], "service_calls": [], "attempted_calls": [],
        "inputs": {}, "formal_data_accessed": False}
    ledger = None

    def limits():
        if cpu() - CPU_START > 30_000_000_000:
            raise RuntimeError(f"complete {experiment.upper()} R&D CPU cap exceeded")
        size = sum(path.stat().st_size for path in output_root.rglob("*") if path.is_file())
        size += sum(path.stat().st_size for path in (stage / "START.json", stage / "PARTIAL.json") if path.is_file())
        if size > 32 * 1024**2:
            raise RuntimeError(f"{experiment.upper()} retained-artifact cap exceeded")

    @contextmanager
    def phase(name, **fields):
        limits()
        before_cpu, before_wall = cpu(), time.perf_counter_ns()
        before_units = 0 if ledger is None else ledger.consumed_units
        try:
            yield
        finally:
            result["phases"].append({"phase": name, **fields, "cpu_ns": cpu() - before_cpu,
                "wall_ns": time.perf_counter_ns() - before_wall,
                "declared_units": (0 if ledger is None else ledger.consumed_units) - before_units})
            if sys.exc_info()[0] is None:
                limits()

    try:
        output_root.mkdir()
        write(output_root / "START.json", start)
        result["execution_commit"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        with phase("dependency_imports"):
            (np, BudgetExceeded, WorkLedger, dataset, manifest, _controller, measure, output_work,
             FrozenGenerator, CachedObjective, NativeGenerator, JointModel, ledger) = dependency_imports(experiment)
        with phase("verify_and_restore_artifacts"):
            restored = safe_restore(protocol, output_root)
            q1_files = {local(protocol["q1"][name + "_path"]): protocol["q1"][name + "_sha256"]
                        for name in ("diagnostic", "predictions", "protocol")}
            if any(sha(path) != expected for path, expected in q1_files.items()):
                raise ValueError("original Q1 artifacts changed")
            result["inputs"] = {str(path.relative_to(ROOT)): identity(path) for path in
                [*q1_files, local(protocol["archive"]["path"]), local(protocol["archive"]["original_files_path"])]}
            with zipfile.ZipFile(local(protocol["q1"]["predictions_path"])) as archive:
                if sum(row.file_size for row in archive.infolist()) > 2 * 1024**2:
                    raise ValueError("Q1 arrays exceed original bounded inventory")
            keys = ["source_ids", "input_hashes"] + [f"s{seed}_{kind}" for seed in SEEDS for kind in ("full", "low", "delta")]
            with np.load(local(protocol["q1"]["predictions_path"]), allow_pickle=False) as archive:
                q1 = {key: archive[key].copy() for key in keys}
        with phase("reconstruct_and_persist_TRAIN_once"):
            train = dataset("train", protocol["dataset"]["profile"])
            if (manifest(train) != protocol["dataset"]["manifest"]
                    or np.asarray(train["source_ids"], dtype="S76").tobytes() != q1["source_ids"].tobytes()
                    or np.asarray(train["input_hashes"], dtype="S64").tobytes() != q1["input_hashes"].tobytes()):
                raise ValueError("Q1 TRAIN row inputs or physical-source identities changed")
            np.savez_compressed(output_root / "train.npz", **{key: train[key] for key in
                ("full", "low", "labels", "source_scenes", "commands")})
            write(output_root / "train-metadata.json", {"manifest": manifest(train),
                **{key: train[key] for key in ("source_ids", "input_hashes", "groups", "sources")},
                "profile": protocol["dataset"]["profile"]})
            ledger.record("train_persistence", reconstructed_train_rows=3072,
                retained_tensor_bytes=sum(train[key].nbytes for key in ("full", "low", "labels", "source_scenes", "commands")))
        with phase("load_fixed_models_and_heads"):
            models = {(row["role"], row["seed"]): JointModel.load(restored[row["member"]]) for row in protocol["models"]}
            heads = {row["seed"]: _controller(restored[row["member"]]) for row in protocol["controllers"]}
            for row in protocol["models"]:
                model = models[row["role"], row["seed"]]
                if model.digest() != row["model_digest"] or model.dimensions != (202, 12, 192, 32):
                    raise ValueError("T11 model digest or fixed geometry changed")
            forced = {(seed, path): heads[seed].with_bounds(np.array([value, value]))
                      for seed in SEEDS for path, value in (("NC-go", 1.), ("NC-stop", 0.))}
        library = restored[protocol["native_library"]["archive_member"]]
        runtime = {"runtime_backend": "native", "native_library": str(library), "runtime_batch_size": 64,
            "output_codec_profile": "rowwise-png-v1", "compute_price": protocol["cost"]["compute_price"],
            "service_horizon": protocol["cost"]["service_horizon"], "inference_cap_full_equivalents": 2., "decision_price": .5}
        with phase("content_raw_value_checks"):
            values, checks = {}, []
            for seed in SEEDS:
                for role in ("NC", "N"):
                    model = models[role, seed]
                    gen = NativeGenerator(model, library_path=library, ledger=ledger, stage="content_probe", prepare_low=False)
                    observer = CachedObjective("A", model, ledger=ledger, stage="content_probe")
                    pf, qf = gen.forward_full(train["full"], ledger, "content_probe")
                    full = observer.utility_values(pf, qf, train["labels"], ledger=ledger, stage="content_probe")
                    values[f"s{seed}_{role}_full"] = full
                    if role == "NC":
                        pl, ql = gen.forward_low(train["full"], ledger, "content_probe")
                        low = observer.utility_values(pl, ql, train["labels"], ledger=ledger, stage="content_probe")
                        ledger.charge_kernel("content_probe", "raw_gain_difference", scalar_ops=len(full))
                        delta = full - low
                        values.update({f"s{seed}_NC_low": low, f"s{seed}_NC_delta": delta})
                        errors = {kind: float(np.max(np.abs(value - q1[f"s{seed}_{kind}"])))
                                  for kind, value in (("full", full), ("low", low), ("delta", delta))}
                        ledger.charge_kernel("content_probe", "Q1_raw_value_check", scalar_ops=6*len(full), compare_ops=3*len(full))
                        if any(not np.isfinite(value) or value > 1e-12 for value in errors.values()):
                            raise ValueError("NC native/raw TRAIN value mismatch against Q1: " + str(errors))
                        checks.append({"seed": seed, "max_absolute_difference": errors, "relative_tolerance": 0., "absolute_tolerance": 1e-12})
            np.savez_compressed(output_root / "content-values.npz", **values)
            write(output_root / "content-checks.json", {"seeds": checks, "ledger": ledger.snapshot()})
        (output_root / "reports").mkdir()
        for repeat, seed, path, sample_seed in call_order():
            with phase("complete_service", repeat=repeat, seed=seed, path=path, sampling_seed=sample_seed):
                model = models["N" if path == "N-full" else "NC", seed]
                head = forced.get((seed, path))
                mode = "continuation" if head is not None else "full"
                # Admission is reservation-only; charge exactly the measured receipt below.
                quote = WorkLedger("service-reservation")
                gen = FrozenGenerator(model, prepare_low=False)
                if path != "NC-stop":
                    quote.charge_kernel("reserve", "full", **gen.full_work(3072))
                if head is not None:
                    quote.charge_kernel("reserve", "low", **gen.low_work(3072))
                    quote.charge_kernel("reserve", "critic", **gen.critic_work(3072, head))
                    quote.charge_kernel("reserve", "prepare", **gen.prepare_work())
                quote.decoder("reserve", rows=3072, pixels=192)
                quote.charge_kernel("reserve", "outputs", **{key: 3072*value for key, value in output_work().items()})
                if quote.consumed_units > ledger.remaining_units:
                    raise BudgetExceeded(f"{experiment.upper()} complete service cannot fit remaining actual-work cap")
                attempted = {"repeat": repeat, "seed": seed, "path": path, "sampling_seed": sample_seed,
                             "status": "attempted; measurement outcome unknown",
                             "reserved_operator_units": quote.consumed_units,
                             "known_units_before": ledger.consumed_units, "accounting_status": "unsettled"}
                result["attempted_calls"].append(attempted)
                report = measure(model, head, mode, train, runtime,
                    protocol["cost"]["reference_full_cpu_ns"], seed=sample_seed, observe=False)
                attempted["status"] = "measured; persistence pending"
                record = {"repeat": repeat, "seed": seed, "path": path, "sampling_seed": sample_seed}
                report[f"{experiment.upper()}_call_identity"] = record
                output = output_root / "reports" / f"service-r{repeat}-s{seed}-{path}.json"
                write(output, report)
                attempted.update(status="persisted; accounting and law validation pending",
                                 file=str(output.relative_to(output_root)))
                actual = sum(report["per_row_cost"]["work_units"]) + report["cost"]["prepare"]["consumed_units"]
                totals = dict(report["cost"]["operator_totals"])
                for key, value in report["cost"]["prepare"]["totals"].items():
                    totals[key] = totals.get(key, 0) + value
                totals.pop("consumed_units", None)
                ledger.record("service_collection", units=actual, **totals, **{experiment + "_service_calls": 1})
                attempted.update(accounting_status="known_actual", actual_units=actual)
                expected_forwards = 6144 if path == "NC-go" else 3072
                if actual != quote.consumed_units or report["model_forwards"] != expected_forwards or report["budget_violations"]:
                    raise ValueError("forced service law or complete actual work receipt changed")
                attempted["status"] = "completed and persisted"
                result["service_calls"].append({**record, "file": str(output.relative_to(output_root)),
                    "sha256": sha(output), "bytes": output.stat().st_size, "work_units": actual,
                    "service_cpu_ns": report["cost"]["cpu_ns"], "prepare_cpu_ns": report["cost"]["prepare_cpu_ns"]})
        with phase("final_identity_verification"):
            if len(result["service_calls"]) != 36 or ledger.totals.get(experiment + "_service_calls") != 36:
                raise ValueError(f"{experiment.upper()} did not retain exactly36 complete service calls")
            for name, row in result["inputs"].items():
                if sha(local(name)) != row["sha256"]:
                    raise ValueError("immutable source evidence changed")
            source_guard(freeze_path, experiment=experiment)
        result["outcome"] = "completed"
    except BaseException as error:
        if "values" in locals() and values and not (output_root / "content-values.npz").exists():
            try:
                np.savez_compressed(output_root / "content-values.npz", **values)
            except Exception as retention_error:
                error.add_note("partial raw-value retention also failed: " + repr(retention_error))
        result.update(outcome="failed", error_type=type(error).__name__, error=str(error), traceback=traceback.format_exc())
        if isinstance(error, SystemExit) and error.code in (None, 0):
            error.add_note(f"{experiment.upper()} incomplete SystemExit converted to nonzero exit1; original request retained above")
            error.code = 1
        raise
    finally:
        original = sys.exc_info()[1]
        protected_error = None
        try:
            verify_protected(frozen)
            result["protected_evidence_verified_at_exit"] = True
        except Exception as protection:
            protected_error = protection
            result["protected_evidence_verified_at_exit"] = False
            result["protected_evidence_error"] = repr(protection)
            if original is not None:
                original.add_note(f"{experiment.upper()} previous-evidence protection also failed: " + repr(protection))
            else:
                result.update(outcome="failed", error_type=type(protection).__name__, error=str(protection),
                              traceback=traceback.format_exc())
        try:
            result.update(**accounting_summary(ledger, result["attempted_calls"]),
                ledger=None if ledger is None else ledger.snapshot(), worker_cpu_ns=cpu()-CPU_START,
                worker_wall_ns=time.perf_counter_ns()-WALL_START,
                cost_boundary="Entire R&D worker from before dependency imports to this receipt; actual inference, observers, data, hashing and I/O included. Final receipt/manifest serialization is additionally retained by the outer complete-process launcher, never a budget credit; no qualification or hardware-FLOP claim.")
            if output_root.is_dir():
                write(output_root / "diagnostic.json", result)
                files = {str(path.relative_to(output_root)): {"sha256": sha(path), "bytes": path.stat().st_size}
                         for path in sorted(output_root.rglob("*")) if path.is_file()}
                write(output_root / "manifest.json", {"schema": "hepta.retained-artifacts.sha256.v1", "files": files})
            if result["outcome"] == "failed":
                write(stage / "PARTIAL.json", result)
            limits()
        except Exception as persistence:
            if original is not None:
                original.add_note(f"{experiment.upper()} terminal persistence also failed: " + repr(persistence))
                try:
                    if not (stage / "PARTIAL.json").exists():
                        write(stage / "PARTIAL.json", result)
                except Exception as fallback:
                    original.add_note(f"{experiment.upper()} stage failure retention also failed: " + repr(fallback))
            else:
                result.update(outcome="failed", error_type=type(persistence).__name__, error=str(persistence),
                              worker_cpu_ns=cpu()-CPU_START, worker_wall_ns=time.perf_counter_ns()-WALL_START)
                try:
                    write(stage / "PARTIAL.json", result)
                    if output_root.is_dir():
                        write(output_root / "diagnostic.json", result, exclusive=False)
                        files = {str(path.relative_to(output_root)): {"sha256": sha(path), "bytes": path.stat().st_size}
                                 for path in sorted(output_root.rglob("*")) if path.is_file() and path.name != "manifest.json"}
                        write(output_root / "manifest.json", {"schema": "hepta.retained-artifacts.sha256.v1", "files": files}, exclusive=False)
                except Exception as fallback:
                    persistence.add_note(f"{experiment.upper()} stage/diagnostic failure retention also failed: " + repr(fallback))
                raise
        if protected_error is not None and original is None:
            raise protected_error
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", choices=("h2", "h3"), default="h2")
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--startup-smoke", action="store_true")
    args = parser.parse_args()
    if args.startup_smoke:
        if args.freeze is not None:
            parser.error("startup smoke neither reads nor consumes a freeze")
        print(json.dumps(startup_smoke(args.experiment), sort_keys=True))
    else:
        stage, _ = experiment_paths(args.experiment)
        result = collect(args.freeze or stage / f"frozen-{args.experiment}.json", experiment=args.experiment)
        print(json.dumps({"experiment_id": args.experiment, "outcome": result["outcome"],
                          "service_calls": len(result["service_calls"])}))
