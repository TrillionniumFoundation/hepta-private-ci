"""One bounded Colab provider window; original scientific sources stay unchanged."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import stat
import subprocess
import sys
import time
import traceback
import zipfile
import zlib


CONTROL_FILES = {"cloud_batch.py", "native_owner.py", "capsule_contract.py", "finalize_mechanism.py", "__init__.py", "test_colab_execution.py", "fixed_kernel_provider.py", "test_fixed_kernel_provider.py"}
PUBLISHED_REF = "refs/heads/codex/hcsn-mechanisms-s81-colab-v4-20261107"
OPERATION_WAIT_SECONDS = 520
OPERATION_DRAIN_SECONDS = 20
EXPORT_RESERVE_SECONDS = 180
MINIMUM_REMAINING_SECONDS = OPERATION_WAIT_SECONDS + OPERATION_DRAIN_SECONDS + EXPORT_RESERVE_SECONDS
assert MINIMUM_REMAINING_SECONDS == 720


class OwnerHalt(RuntimeError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def file_sha(path):
    return hashlib.sha256(regular_bytes(path)).hexdigest()


def regular_bytes(path, maximum=268435456):
    path = Path(path)
    before = path.lstat()
    version = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > maximum:
        raise OwnerHalt("Unsafe or oversized pinned file: " + str(path))
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        if version(os.fstat(stream.fileno())) != version(before):
            raise OwnerHalt("Pinned file changed before read")
        data = stream.read(maximum + 1)
    if len(data) != before.st_size or version(path.lstat()) != version(before):
        raise OwnerHalt("Pinned file changed during read")
    return data


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def read_json(path):
    def pairs(items):
        output = {}
        for key, value in items:
            if key in output:
                raise OwnerHalt("Duplicate JSON key")
            output[key] = value
        return output
    def reject(value):
        raise OwnerHalt("Nonfinite JSON: " + value)
    return json.loads(regular_bytes(path), object_pairs_hook=pairs, parse_constant=reject)


def now():
    return datetime.now(timezone.utc).isoformat()


def remaining_budget(admission_epoch, started_monotonic, initial_age, current_monotonic=None):
    """Count native admission/queue age once, then use monotonic elapsed time."""
    current = time.monotonic() if current_monotonic is None else current_monotonic
    return 3000.0 - initial_age - (current - started_monotonic)




def verify_static(config, source, plan_path, bundle):
    if file_sha(plan_path) != config["plan_sha256"]:
        raise OwnerHalt("Frozen plan bytes changed")
    if file_sha(bundle) != config["identity"]["bundle_sha256"] or file_sha(bundle.with_suffix(".json")) != config["identity"]["bundle_metadata_sha256"]:
        raise OwnerHalt("Frozen operator bundle bytes changed")
    for name, expected in config["identity"]["source_pins"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or file_sha(source / relative) != expected:
            raise OwnerHalt("Frozen scientific source bytes changed: " + name)
    if config.get("source_pins") != config["identity"]["source_pins"]:
        raise OwnerHalt("Native and cloud scientific source maps differ")
    controls = config.get("control_pins", {})
    if set(controls) != CONTROL_FILES:
        raise OwnerHalt("Missing control source pins")
    for name, expected in controls.items():
        if file_sha(Path(config["control_root"]) / name) != expected:
            raise OwnerHalt("Frozen control source bytes changed: " + name)


def gpu_counters():
    rows = []
    try:
        import pynvml
        pynvml.nvmlInit()
        for index in range(pynvml.nvmlDeviceGetCount()):
            handle = pynvml.nvmlDeviceGetHandleByIndex(index)
            row = dict(index=index, uuid=str(pynvml.nvmlDeviceGetUUID(handle)))
            try:
                row["millijoules"] = int(pynvml.nvmlDeviceGetTotalEnergyConsumption(handle))
            except Exception as error:
                row.update(millijoules=None, error_type=type(error).__name__)
            rows.append(row)
    except Exception as error:
        return dict(available=False, devices=rows, error_type=type(error).__name__)
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass
    return dict(available=bool(rows) and all(row["millijoules"] is not None for row in rows), devices=rows)


def gpu_delta(before, after):
    previous = {row["uuid"]: row for row in before["devices"]}
    result = []
    for row in after["devices"]:
        old = previous.get(row["uuid"])
        valid = old is not None and old["millijoules"] is not None and row["millijoules"] is not None and row["millijoules"] >= old["millijoules"]
        result.append(dict(index=row["index"], uuid=row["uuid"], device_interval_joules=(row["millijoules"] - old["millijoules"]) / 1000 if valid else None))
    return result


def proc_identity(pid):
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
        fields = raw[raw.rfind(")") + 2:].split()
        return dict(pid=pid, state=fields[0], parent_pid=int(fields[1]), start_ticks=int(fields[19]),
                    command=Path(f"/proc/{pid}/cmdline").read_bytes())
    except (FileNotFoundError, ProcessLookupError):
        return None


def terminate_owned_operation(process, attempt, deadline):
    """The qualified supervisor normally drains its worker in 480+10 seconds."""
    proof = dict(outer_pid=process.pid, worker=None, worker_children_stopped=attempt is None)
    worker_path = attempt / "worker-process.json" if attempt is not None else None
    if worker_path is not None and worker_path.is_file():
        pid = read_json(worker_path).get("pid")
        worker = proc_identity(pid) if isinstance(pid, int) else None
        if worker is not None:
            expected_job = str(attempt / "job.json").encode()
            if worker["parent_pid"] != process.pid or expected_job not in worker["command"] or b"qualification.hcsn_regenerative.mechanism_worker" not in worker["command"] or os.getpgid(pid) != pid:
                raise OwnerHalt("Cannot prove timed-out nested worker ownership; no arbitrary signal sent")
            proof["worker"] = {key: value for key, value in worker.items() if key != "command"}
            os.killpg(pid, signal.SIGTERM)
            graceful_deadline = min(deadline, time.monotonic() + 5)
            while time.monotonic() < graceful_deadline and proc_identity(pid) is not None:
                time.sleep(min(.1, max(0., graceful_deadline-time.monotonic())))
            current = proc_identity(pid)
            if current is not None and current["start_ticks"] == worker["start_ticks"]:
                os.killpg(pid, signal.SIGKILL)
            kill_deadline = min(deadline, time.monotonic() + 5)
            while time.monotonic() < kill_deadline:
                current = proc_identity(pid)
                if current is None or current["start_ticks"] != worker["start_ticks"] or current["state"] == "Z":
                    proof["worker_children_stopped"] = True
                    break
                time.sleep(min(.1, max(0., kill_deadline-time.monotonic())))
        else:
            proof["worker_children_stopped"] = True
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=max(0., min(5., deadline-time.monotonic())))
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=max(0., min(5., deadline-time.monotonic())))
    proof["outer_returncode"] = process.returncode
    return proof


def run_process(argv, cwd, env, logs, label, timeout, attempt=None):
    stdout, stderr = logs / (label + ".stdout.log"), logs / (label + ".stderr.log")
    start = time.monotonic()
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    row = dict(label=label, argv=argv, started_utc=now(), timeout_seconds=timeout, timed_out=False,
               worker_children_stopped=False)
    with stdout.open("xb") as out, stderr.open("xb") as err:
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdout=out, stderr=err, start_new_session=True)
        try:
            process.wait(timeout=timeout)
            # A runner exit is not itself proof that its separate-session worker
            # stopped. The qualified supervisor must have written its wait result.
            row["worker_children_stopped"] = attempt is None
            if attempt is not None and (attempt / "process-completion.json").is_file():
                completion = read_json(attempt / "process-completion.json")
                row["worker_children_stopped"] = type(completion.get("returncode")) is int
                if (attempt / "worker-process.json").is_file():
                    worker = proc_identity(read_json(attempt / "worker-process.json").get("pid"))
                    if worker is not None and worker["state"] != "Z" and str(attempt / "job.json").encode() in worker["command"]:
                        row["worker_children_stopped"] = False
        except subprocess.TimeoutExpired:
            row["timed_out"] = True
            drain_started = time.monotonic()
            drain_deadline = drain_started + OPERATION_DRAIN_SECONDS
            try:
                row["termination_proof"] = terminate_owned_operation(process, attempt, drain_deadline)
                row["worker_children_stopped"] = row["termination_proof"]["worker_children_stopped"]
            except Exception as error:
                row["termination_error"] = dict(type=type(error).__name__, message=str(error))
                # This is our Popen child/session; an unproved nested worker is
                # never signalled by an inferred PID and prevents all new jobs.
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    try:
                        process.wait(timeout=max(0., drain_deadline-time.monotonic()))
                    except subprocess.TimeoutExpired:
                        pass
            row["control_drain_seconds"] = time.monotonic()-drain_started
            row["control_drain_budget_seconds"] = OPERATION_DRAIN_SECONDS
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    row.update(returncode=process.returncode, finished_utc=now(), wall_seconds=time.monotonic()-start,
               child_user_cpu_seconds=after.ru_utime-usage.ru_utime,
               child_system_cpu_seconds=after.ru_stime-usage.ru_stime, children_peak_rss_kib=after.ru_maxrss,
               stdout_sha256=file_sha(stdout), stderr_sha256=file_sha(stderr))
    return row


def guard_terminal(attempt, fit, identity, phase):
    terminal_path, process_path = attempt / "terminal.json", attempt / "process-completion.json"
    if not terminal_path.is_file() or not process_path.is_file():
        raise OwnerHalt("Claimed operation lacks terminal/process completion; UNKNOWN, no replay")
    terminal, process = read_json(terminal_path), read_json(process_path)
    if terminal.get("identity") != identity or terminal.get("fit") != fit or terminal.get("phase") != phase:
        raise OwnerHalt("Terminal identity/roster/phase mismatch")
    status = terminal.get("status")
    if status not in ("COMPLETED", "FAILED", "TIMEOUT"):
        raise OwnerHalt("UNKNOWN or unsupported terminal; no replay")
    if type(process.get("returncode")) is not int or type(process.get("timed_out")) is not bool:
        raise OwnerHalt("Process completion does not prove a stopped worker")
    if status == "COMPLETED" and (process.get("returncode") != 0 or process.get("timed_out")):
        raise OwnerHalt("Terminal and supervisor completion disagree")
    if status == "FAILED" and (process.get("returncode") != 2 or process.get("timed_out")):
        raise OwnerHalt("Failed terminal and supervisor completion disagree")
    error = terminal.get("error", {})
    message = str(error.get("message", "")).lower()
    if any(word in message for word in ("environment", "gpu mismatch", "source drift", "source pin", "identity", "checkpoint", "selection", "bundle", "frozen", "plan mismatch", "roster")):
        raise OwnerHalt("Guard/integrity failure cannot be treated as an ordinary training failure")
    if status == "TIMEOUT" and not process.get("timed_out"):
        if not (error.get("type") == "TimeoutError" and process.get("returncode") == 2 and terminal.get("frozen_environment_check", {}).get("matched") is True):
            raise OwnerHalt("Timeout status lacks a supervisor or explicit stopped-worker timeout receipt")
    if status in ("COMPLETED", "FAILED"):
        if terminal.get("frozen_environment_check", {}).get("matched") is not True:
            raise OwnerHalt("Worker did not establish the frozen environment before the outcome")
    if status == "COMPLETED" and terminal.get("source_and_input_pins_unchanged_at_completion") is not True:
        raise OwnerHalt("Completed worker did not attest unchanged source and inputs")
    if phase == "fit" and status == "COMPLETED":
        if terminal.get("optimizer_updates_completed") != 400 or terminal.get("validation") is None:
            raise OwnerHalt("Completed fit lacks all registered updates and validation")
        if file_sha(attempt / "checkpoint.pt") != terminal.get("checkpoint_sha256"):
            raise OwnerHalt("Completed checkpoint missing or corrupt")
    return terminal


def build_payload(batch_config, source_root, plan_path, control_root, *, asset_module, asset_output, remote_root):
    """Prepare immutable inputs offline; stage/execute are separate native intents."""
    config = json.loads(canonical(batch_config))
    if (config.get("formal_training_start_authorized") is not True
            or re.fullmatch(r"[0-9a-f]{40}", config.get("published_plan_commit", "")) is None
            or config.get("published_plan_ref") != PUBLISHED_REF):
        raise OwnerHalt("Verified Colab publication authorization is required")
    if re.fullmatch(r"[A-Za-z0-9_-]{1,80}", config.get("request_id", "")) is None or config.get("phase") not in ("fit", "selection", "evaluation"):
        raise OwnerHalt("Invalid unique Colab request or phase")
    source_root, plan_path, control_root = Path(source_root), Path(plan_path), Path(control_root)
    if file_sha(plan_path) != config["plan_sha256"]:
        raise OwnerHalt("Plan bytes differ before preparation")
    plan = read_json(plan_path)
    if config["source_pins"] != plan["source_pins"] or config["identity"]["source_pins"] != plan["source_pins"] or set(config["control_pins"]) != CONTROL_FILES:
        raise OwnerHalt("Source/control maps differ")
    relative_control = "qualification/hcsn_regenerative/colab_execution_v4"
    files = {}
    for name, expected in sorted(config["source_pins"].items()):
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or path.as_posix() != name or file_sha(source_root / path) != expected:
            raise OwnerHalt("Unsafe or changed research source")
        files["source/" + name] = source_root / path
    for name, expected in config["control_pins"].items():
        if file_sha(control_root / name) != expected or config["source_pins"].get(relative_control + "/" + name) != expected:
            raise OwnerHalt("Control is not exactly in the published source map")
    if (source_root / config["plan_relative_path"]).resolve() != plan_path.resolve():
        raise OwnerHalt("Plan path differs")
    files["source/" + config["plan_relative_path"]] = plan_path
    for key, target, expected in (("bundle_path", "operators-s81.npz", config["identity"]["bundle_sha256"]),
                                  ("metadata_path", "operators-s81.json", config["identity"]["bundle_metadata_sha256"])):
        source = Path(config["qualified_input"][key])
        if file_sha(source) != expected:
            raise OwnerHalt("Qualified bundle bytes changed")
        files["inputs/" + target] = source
    previous = config.get("prior_capsule")
    if previous:
        for key, target, expected in (("native_archive_path", "prior-study-capsule.tar.gz", previous["archive_sha256"]),
                                      ("native_manifest_path", "prior-capsule-manifest.json", previous["manifest_sha256"])):
            source = Path(previous[key])
            if file_sha(source) != expected:
                raise OwnerHalt("Complete prior native capsule changed")
            files["inputs/" + target] = source
    output = Path(asset_output)
    output.mkdir(parents=True, exist_ok=False)
    destination = "materialized-" + config["request_id"]
    config.update(source_root=destination + "/source", control_root=destination + "/source/" + relative_control,
                  temporary_root=destination + "/state", inputs_root=destination + "/inputs")
    config_path = output / "batch-config.json"
    config_path.write_bytes(canonical(config))
    files["batch-config.json"] = config_path
    entrypoint = output / "bootstrap_entry.py"
    entrypoint.write_text("import json,sys,time\nfrom pathlib import Path\n"
        "root=Path(__file__).resolve().parent\nc=json.loads((root/'batch-config.json').read_text())\n"
        "c.update(source_root=str(root/'source'),control_root=str(root/'source/qualification/hcsn_regenerative/colab_execution_v4'),temporary_root=str(root/'state'),inputs_root=str(root/'inputs'))\n"
        "Path(c['temporary_root']).mkdir(exist_ok=False)\n"
        "sys.dont_write_bytecode=True\nsys.path[:0]=[c['control_root'],c['source_root']]\n"
        "c['bootstrap_timing']={'started_monotonic':time.monotonic(),'started_epoch_unix':time.time(),'unpack_complete_monotonic':time.monotonic()}\n"
        "from cloud_batch import run_batch\nraise SystemExit(run_batch(c))\n")
    files["bootstrap_entry.py"] = entrypoint
    prepared = asset_module.prepare_archive(files, output / "assets", config["request_id"], remote_root,
                                            max_archive_bytes=config["provider_binding"]["max_artifact_bytes"])
    manifest = regular_bytes(prepared["manifest_path"])
    if hashlib.sha256(manifest).hexdigest() != prepared["manifest_sha256"]:
        raise OwnerHalt("Prepared asset manifest changed")
    # The shared transport owns the exact bounded materializer launcher API.
    launcher = asset_module.make_launcher(manifest, prepared["manifest_sha256"], destination, "bootstrap_entry.py",
                                          regular_bytes(source_root / "qualification/hcsn_regenerative/colab_qualification_v4/asset_transport.py"),
                                          transport_logical="source/qualification/hcsn_regenerative/colab_qualification_v4/asset_transport.py")
    source_text = launcher if isinstance(launcher, str) else launcher["source_text"]
    raw = source_text.encode()
    if not 0 < len(raw) <= 262144:
        raise OwnerHalt("Colab code limit exceeded; no truncation")
    return dict(source_text=source_text, code_sha256=hashlib.sha256(raw).hexdigest(), code_bytes=len(raw),
                request_id=config["request_id"], prepared_assets=prepared, cloud_config=config)




def phase_dispatch(config, group, known, study, plan, identity, validate_lock):
    """Enforce the fit/selection/test barrier before any child is started."""
    if any(row["status"] == "UNKNOWN" for row in known.values()):
        raise OwnerHalt("Prior UNKNOWN attempt prevents further dispatch")
    phase = config["phase"]
    if phase == "fit":
        expected = [fit["fit_id"] for fit in group if known[fit["fit_id"]]["status"] == "UNSTARTED"]
        if (study / "blocks" / config["group_id"] / "selection-lock.json").exists():
            raise OwnerHalt("Fit phase cannot resume after selection")
    else:
        if any(row["status"] not in ("COMPLETED", "FAILED", "TIMEOUT") for row in known.values()):
            raise OwnerHalt("All twenty fits require explicit non-UNKNOWN terminals before selection/evaluation")
        for fit in group:
            guard_terminal(study / "attempts" / fit["fit_id"], fit, identity, "fit")
        if phase == "selection":
            if (study / "blocks" / config["group_id"] / "selection-lock.json").exists():
                raise OwnerHalt("Selection has already been claimed; no replay")
            expected = []
        else:
            lock, lock_sha = validate_lock(study, plan, group, identity)
            if config.get("verified_selection_lock_sha256") != lock_sha:
                raise OwnerHalt("Evaluation lock was not bound by the previous native readback")
            selected = {row["fit_id"] for row in lock["selected"].values()}
            expected = [fit["fit_id"] for fit in group if fit["fit_id"] in selected and not (study / "evaluations" / fit["fit_id"]).exists()]
    planned_fits = expected if phase == "fit" else []
    planned_evaluations = expected if phase == "evaluation" else []
    if config["planned_fit_ids"] != planned_fits or config["planned_evaluation_ids"] != planned_evaluations:
        raise OwnerHalt("Native planned dispatch lists are not the complete ordered remaining phase")
    return [None] if phase == "selection" else expected


def run_batch(config, *, work_root=None):
    from capsule_contract import create_capsule, restore_capsule, validate_transition
    if (config.get("formal_training_start_authorized") is not True
            or not re.fullmatch(r"[0-9a-f]{40}", config.get("published_plan_commit", ""))
            or config.get("published_plan_ref") != PUBLISHED_REF):
        raise OwnerHalt("A verified published plan and explicit owner start binding are required")
    if config.get("phase") not in ("fit", "selection", "evaluation"):
        raise OwnerHalt("Unsupported provider phase")
    # Production output is exactly the original Colab runner work directory.
    # The explicit work_root remains a local test seam only.
    work, source = Path.cwd() if work_root is None else Path(work_root), Path(config["source_root"])
    plan_path = source / config["plan_relative_path"]
    temp = Path(config["temporary_root"])
    logs = temp / "control-logs"; logs.mkdir(exist_ok=False)
    study, inputs = temp / "study", Path(config["inputs_root"])
    if not inputs.is_dir():
        raise OwnerHalt("Verified immutable inputs are missing")
    started, usage_start = time.monotonic(), resource.getrusage(resource.RUSAGE_CHILDREN)
    age = time.time() - config["admission_epoch_unix"]
    if age < -5:
        raise OwnerHalt("Native/cloud clocks disagree; provider time budget cannot be established")
    age = max(0., age)
    env = dict(os.environ, OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
               CUBLAS_WORKSPACE_CONFIG=":4096:8", PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1")
    gpu_start = gpu_counters()
    report = dict(schema="hcsn-mechanism-colab-batch-v4", request_id=config["request_id"],
        identity=config["identity"], published_plan_commit=config["published_plan_commit"],
        published_plan_ref=config["published_plan_ref"], plan_sha256=config["plan_sha256"],
        source_pins=config["source_pins"], control_pins=config["control_pins"],
        group_id=config["group_id"], phase=config["phase"], planned_fit_ids=config["planned_fit_ids"],
        planned_evaluation_ids=config["planned_evaluation_ids"], qualified_input=config["qualified_input"],
        prior_capsule=config.get("prior_capsule"),
        native_ever_claimed_fit_ids=config["ever_claimed_fit_ids"],
        native_ever_claimed_evaluation_ids=config["ever_claimed_evaluation_ids"],
        started_utc=now(), initial_native_to_cloud_age_seconds=age, operations=[], halt_owner=False,
        status="RUNNING", final_state_attested=False, formal_fits_newly_started=0,
        completed_operation_ids=[], source_unchanged=False, environment_verified=False, worker_children_stopped=True,
        full_physical_energy_joules=None, monetary_cost=None, gpu_energy_start=gpu_start,
        input_bindings={}, local_scope="One group only; group-local runner progress is not the 160-fit global ledger")
    prior, plan, roster, group, bundle = None, None, None, None, None
    try:
        request_raw = regular_bytes(work.parent / "request.json")
        request = json.loads(request_raw)
        expected_provider = config["provider_binding"]
        if any(request.get(k) != expected_provider[k] for k in ("endpoint", "kernel_id", "session_id")):
            raise OwnerHalt("Actual Colab request identity differs")
        if work != Path(expected_provider["remote_root"]) / request["job_id"] / "work":
            raise OwnerHalt("Actual Colab work directory differs")
        report["colab_request"] = request
        report["colab_request_sha256"] = hashlib.sha256(request_raw).hexdigest()
        report["provider_binding"] = expected_provider
        bundle = inputs / "operators-s81.npz"
        if file_sha(bundle) != config["identity"]["bundle_sha256"] or file_sha(bundle.with_suffix(".json")) != config["identity"]["bundle_metadata_sha256"]:
            raise OwnerHalt("Staged qualified operator bytes differ")
        report["input_bindings"]["bundle_sha256"] = file_sha(bundle)
        report["input_bindings"]["bundle_metadata_sha256"] = file_sha(bundle.with_suffix(".json"))
        sys.path.insert(0, str(source))
        from qualification.hcsn_regenerative.mechanism_contract import load_contract
        from qualification.hcsn_regenerative.mechanism_training import read_attempt, validate_selection_lock
        verify_static(config, source, plan_path, bundle)
        plan, metadata, _, roster, identity = load_contract(bundle, plan_path)
        if identity != config["identity"]:
            raise OwnerHalt("Loaded contract differs from the native owner identity")
        group = [fit for fit in roster if fit["group_id"] == config["group_id"]]
        group_ids = [fit["fit_id"] for fit in group]
        if len(group) != 20 or group_ids != config["expected_group_fit_ids"]:
            raise OwnerHalt("Provider group differs from the registered ordered twenty fits")
        policy = plan["runtime_feasibility_policy"]
        if policy["provider"] != "colab" or policy["cloud_job_max_seconds"] != 3000 or policy["minimum_remaining_before_operation_seconds"] != 720 or plan["max_fit_wall_seconds"] != 480:
            raise OwnerHalt("Frozen provider/fit budget mismatch")
        previous = config.get("prior_capsule")
        if previous:
            archive_path, manifest_path = inputs / "prior-study-capsule.tar.gz", inputs / "prior-capsule-manifest.json"
            if archive_path.stat().st_size != previous["archive_bytes"] or file_sha(archive_path) != previous["archive_sha256"] or file_sha(manifest_path) != previous["manifest_sha256"]:
                raise OwnerHalt("Complete staged parent capsule differs")
            prior = restore_capsule(archive_path, manifest_path, study, identity, config["group_id"], group_ids,
                                    config["ever_claimed_fit_ids"], config["ever_claimed_evaluation_ids"])
            report["input_bindings"]["prior_capsule"] = previous
        else:
            if config["ever_claimed_fit_ids"] or config["ever_claimed_evaluation_ids"]:
                raise OwnerHalt("Native cumulative claims exist without their complete prior capsule")
            study.mkdir()
            write_json(study / "study.json", dict(created_at=now(), identity=identity, plan=plan,
                ordered_fit_roster=roster, owner_rule="One native owner; sequential provider windows and immutable group snapshots"))
        guard_output = logs / "environment.json"
        guard_code = (
            "import json,sys;from pathlib import Path;"
            "from qualification.hcsn_regenerative.mechanism_contract import load_contract,validate_execution_environment;"
            "from qualification.hcsn_regenerative.mechanism_worker import configure_torch;"
            "from qualification.hcsn_regenerative.mechanism_model import environment;"
            "p,m,a,r,i=load_contract(sys.argv[1],sys.argv[2]);t=configure_torch('cuda');t.cuda.set_device(0);"
            "e=environment('cuda');v=validate_execution_environment(p,e,m);"
            "Path(sys.argv[3]).write_text(json.dumps(dict(environment=e,check=v),sort_keys=True)+'\\n')")
        preflight = run_process([sys.executable, "-B", "-c", guard_code, str(bundle), str(plan_path), str(guard_output)], source, env, logs, "environment-preflight", 120)
        report["environment_preflight"] = preflight
        report["worker_children_stopped"] = preflight["worker_children_stopped"]
        if preflight["returncode"] != 0 or preflight["timed_out"] or not guard_output.is_file():
            raise OwnerHalt("Actual execution environment preflight failed before any new claim")
        report["observed_environment"] = read_json(guard_output)
        if report["observed_environment"].get("check", {}).get("matched") is not True:
            raise OwnerHalt("Actual environment guard did not affirm the frozen binding")
        report["environment_verified"] = True
        known = {fit["fit_id"]: read_attempt(study, fit, identity) for fit in group}
        operations = phase_dispatch(config, group, known, study, plan, identity, validate_selection_lock)
        for fit_id in operations:
            remaining = remaining_budget(config["admission_epoch_unix"], started, age)
            if remaining < MINIMUM_REMAINING_SECONDS:
                report["window_exhausted_before_claim"] = True
                break
            verify_static(config, source, plan_path, bundle)
            fit = next((row for row in group if row["fit_id"] == fit_id), None)
            if config["phase"] == "fit":
                if read_attempt(study, fit, identity)["status"] != "UNSTARTED":
                    raise OwnerHalt("Fit was already claimed; no replay")
                flag, value, attempt = "--fit-ids", fit_id, study / "attempts" / fit_id
            elif config["phase"] == "selection":
                flag, value, attempt = "--select-group", config["group_id"], None
            else:
                flag, value, attempt = "--evaluate-fit", fit_id, study / "evaluations" / fit_id
                if attempt.exists():
                    raise OwnerHalt("Evaluation was already claimed; no replay")
            label = config["phase"] + "-" + (fit_id or config["group_id"])
            argv = [sys.executable, "-B", "-m", "qualification.hcsn_regenerative.mechanism_training", "--bundle", str(bundle),
                    "--plan", str(plan_path), "--output", str(study), "--device", "cuda", flag, value]
            report["worker_children_stopped"] = False
            operation = run_process(argv, source, env, logs, label, OPERATION_WAIT_SECONDS, attempt)
            report["worker_children_stopped"] = operation["worker_children_stopped"]
            operation.update(fit_id=fit_id, phase=config["phase"], remaining_before_claim_seconds=remaining)
            report["operations"].append(operation)
            verify_static(config, source, plan_path, bundle)
            if operation["timed_out"] or not operation["worker_children_stopped"]:
                raise OwnerHalt("Outer operation watchdog fired; actual fit status remains UNKNOWN until reconciled")
            if config["phase"] == "selection":
                if operation["returncode"] != 0:
                    raise OwnerHalt("Selection operation failed")
                lock, lock_sha = validate_selection_lock(study, plan, group, identity)
                report["selection_lock_sha256"] = lock_sha
                report["selected_fit_ids"] = [fit["fit_id"] for fit in group if fit["fit_id"] in {row["fit_id"] for row in lock["selected"].values()}]
            else:
                phase = "fit" if config["phase"] == "fit" else "selected_test"
                terminal = guard_terminal(attempt, fit, identity, phase)
                operation["terminal_status"] = terminal["status"]
                if operation["returncode"] != (0 if terminal["status"] == "COMPLETED" else 2):
                    raise OwnerHalt("Runner return code and terminal outcome disagree")
            report["completed_operation_ids"].append(label)
            print(json.dumps(dict(request_id=config["request_id"], operation=label,
                                 terminal_status=operation.get("terminal_status", "selection_locked"))), flush=True)
        verify_static(config, source, plan_path, bundle)
        report["source_unchanged"] = True
        report["status"] = "EXPORTED"
        report["final_state_attested"] = True
    except Exception as error:
        status = "UNKNOWN" if "unknown" in str(error).lower() or not report["worker_children_stopped"] else "BLOCKED"
        report.update(status=status, halt_owner=True, error=dict(type=type(error).__name__, message=str(error), traceback=traceback.format_exc()))
    finally:
        # Claims are physical directories, not just successfully returned calls.
        # A failure after mkdir must remain visible in the cost/attempt ledger.
        fit_dirs = study / "attempts"
        if fit_dirs.is_dir():
            current_claims = {path.name for path in fit_dirs.iterdir() if path.is_dir()}
            report["formal_fits_newly_started"] = len(current_claims - set(config["ever_claimed_fit_ids"]))
            report["newly_claimed_fit_ids_observed"] = sorted(current_claims - set(config["ever_claimed_fit_ids"]))
            report["formal_fit_counter_scope"] = "Exclusive attempt-directory claims, including incomplete or unknown workers; not completed training"
        if study.is_dir() and (study / "study.json").is_file() and group is not None:
            try:
                capsule = create_capsule(study, work / "study-capsule.tar.gz", work / "capsule-manifest.json", config["identity"],
                    config["group_id"], config["expected_group_fit_ids"], prior_manifest=prior)
                if prior is not None:
                    validate_transition(prior, capsule, config["ever_claimed_fit_ids"], config["ever_claimed_evaluation_ids"])
                report["capsule_verified"] = True
                report["capsule_manifest_sha256"] = file_sha(work / "capsule-manifest.json")
                report["capsule"] = dict(archive_name="study-capsule.tar.gz", manifest_name="capsule-manifest.json",
                    archive_sha256=capsule["archive"]["sha256"], archive_bytes=capsule["archive"]["bytes"],
                    manifest_sha256=report["capsule_manifest_sha256"])
                report["claimed_fit_ids"] = capsule["claimed_fit_ids"]
                report["claimed_evaluation_ids"] = capsule["claimed_evaluation_ids"]
                report["group_training_status"] = {fit["fit_id"]: read_attempt(study, fit, config["identity"])["status"] for fit in group}
                if report["final_state_attested"]:
                    report["unclaimed_remaining_planned_fit_ids"] = [fit_id for fit_id in config["planned_fit_ids"] if fit_id not in capsule["claimed_fit_ids"]]
                    report["unclaimed_remaining_planned_evaluation_ids"] = [fit_id for fit_id in config["planned_evaluation_ids"] if fit_id not in capsule["claimed_evaluation_ids"]]
            except Exception as error:
                report.update(halt_owner=True, status="BLOCKED", final_state_attested=False, capsule_verified=False,
                              capsule_error=dict(type=type(error).__name__, message=str(error)))
        else:
            report["capsule_verified"] = False
            report["final_state_attested"] = False
        if bundle is not None:
            try:
                verify_static(config, source, plan_path, bundle)
                report["source_unchanged"] = True
            except Exception as error:
                report.update(status="BLOCKED", halt_owner=True, source_unchanged=False, final_state_attested=False,
                              final_static_guard_error=dict(type=type(error).__name__, message=str(error)))
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        gpu_end = gpu_counters()
        report.update(finished_utc=now(), wall_seconds=time.monotonic()-started,
            child_user_cpu_seconds=after.ru_utime-usage_start.ru_utime,
            child_system_cpu_seconds=after.ru_stime-usage_start.ru_stime, children_peak_rss_kib=after.ru_maxrss,
            gpu_energy_end=gpu_end, gpu_device_intervals=gpu_delta(gpu_start, gpu_end))
        report["costs"] = dict(run_batch_measured_wall_seconds=report["wall_seconds"],
            child_user_cpu_seconds=report["child_user_cpu_seconds"], child_system_cpu_seconds=report["child_system_cpu_seconds"],
            children_peak_rss_kib=report["children_peak_rss_kib"], gpu_device_intervals=report["gpu_device_intervals"],
            full_physical_energy_joules=None, monetary_cost=None,
            scope="Measured run_batch interval through complete capsule assembly, after bootstrap unpack and before control-logs.zip/artifact-manifest serialization. Worker and per-operation durations are nested. Device counters include idle and other device activity. Bootstrap/finalization scope is separately reported in outer-timing.json; native upload, queue, provider startup/finalization and full physical energy are not inferred.")
        report["process_exit_semantics"] = "Exit zero means evidence export completed, including BLOCKED/UNKNOWN. Only EXPORTED plus all source, environment, capsule and stopped-worker evidence admits continuation. Provider COMPLETE alone gives no fit credit."
        report["operation_budget"] = dict(minimum_remaining_seconds=MINIMUM_REMAINING_SECONDS,
            fit_timeout_seconds=480, outer_operation_wait_seconds=OPERATION_WAIT_SECONDS,
            maximum_control_drain_seconds=OPERATION_DRAIN_SECONDS, export_reserve_seconds=EXPORT_RESERVE_SECONDS)
        write_json(work / "execution.json", report)
        finalization_started = time.monotonic()
        with zipfile.ZipFile(work / "control-logs.zip", "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(logs.rglob("*")):
                if path.is_file():
                    archive.write(path, str(path.relative_to(logs)))
        def artifact_manifest():
            outputs = [path for path in sorted(work.iterdir()) if path.is_file() and path.name != "artifact-manifest.json"]
            write_json(work / "artifact-manifest.json", dict(schema="hepta-artifact-manifest-v1", request_id=config["request_id"],
                files=[dict(path=path.name, bytes=path.stat().st_size, sha256=file_sha(path)) for path in outputs]))
        artifact_manifest()
        bootstrap = config.get("bootstrap_timing", {})
        outer_end = time.monotonic()
        write_json(work / "outer-timing.json", dict(schema="hcsn-provider-export-timing-v1", request_id=config["request_id"],
            bootstrap_timer_wall_seconds=outer_end-bootstrap["started_monotonic"] if "started_monotonic" in bootstrap else None,
            bootstrap_to_run_batch_seconds=started-bootstrap["started_monotonic"] if "started_monotonic" in bootstrap else None,
            final_logs_and_initial_manifest_wall_seconds=outer_end-finalization_started,
            run_batch_measured_wall_seconds=report["wall_seconds"], provider_wall_seconds=None, full_physical_energy_joules=None,
            timer_scope="Bootstrap timer begins after bootstrap stdlib imports and ends after control-logs.zip plus initial artifact manifest. Excludes this timing receipt and final manifest rewrite. Native provider created/observed-terminal interval is distinct; no sum of nested scopes."))
        artifact_manifest()
        print(json.dumps(dict(status=report["status"], halt_owner=report["halt_owner"], final_state_attested=report["final_state_attested"],
                              formal_fits_newly_started=report["formal_fits_newly_started"])), flush=True)
    # Colab can retain artifacts for every explicit terminal. Exit zero still
    # establishes serialization only: BLOCKED/UNKNOWN never admits a new batch.
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    return run_batch(read_json(args.config))


if __name__ == "__main__":
    raise SystemExit(main())
