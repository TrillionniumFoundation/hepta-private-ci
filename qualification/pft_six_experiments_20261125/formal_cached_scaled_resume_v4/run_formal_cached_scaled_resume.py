"""One registered formal cached_scaled cold-resume check; never fit or edit.

Static candidate only until the operator explicitly executes this file in the
pinned original runtime. The parent loads once and advances 12 steps. Exactly
two fresh child processes reuse the original numeric runner for 5 and 7 steps.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import signal
import stat
import sys
import time

ROOT = Path(__file__).resolve().parent
CASE_ID = "n8-s2101-value_risk-full-learned-m64-lr1e-05"
CANDIDATE = "2eeda94ea29a02119b8d7b73b2f1c355e9a052a802a5867ca5092782adc44513"
PROTOCOL = "aad9b709d3ee6a32597487f5ae1eb2c1fc490f74d05320c4d32349fe7f09e7b8"
PYTHON = "/home/alex/pft-six-actual-hcsn-20261125/venv/bin/python"
READOUT = ("readout.mean", "readout.scale", "readout.linear.weight", "readout.linear.bias")
STATE = ("density", "boundary", "drift", "cost", "message")
RTOL, ATOL = 1e-11, 1e-12
CAP = 16 * 1024 * 1024
HELPERS = ("profile_io", "source_binding", "small_hcsn_profile",
           "numeric_runner", "bounded_process")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def capture(path, cap=CAP):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= cap,
                "bounded regular input required")
        raw = stream.read(cap + 1)
        after = os.fstat(stream.fileno())
    def stamp(item):
        return (item.st_dev, item.st_ino, item.st_size,
                item.st_mtime_ns, item.st_ctime_ns)

    require(stamp(before) == stamp(after) and len(raw) == before.st_size,
            "input changed while captured")
    return raw


def bootstrap(expected):
    raw = capture(ROOT / "REGISTRATION.json", 1024 * 1024)
    require(len(expected) == 64 and hashlib.sha256(raw).hexdigest() == expected,
            "operator registration pin differs")
    registration = json.loads(raw)
    require(registration["case_id"] == CASE_ID, "different registered case")
    for pin in registration["source_pins"]:
        path = Path(pin["path"])
        require(not path.is_absolute() and ".." not in path.parts,
                "nonlocal source pin")
        data = capture(ROOT / path)
        require(len(data) == pin["bytes"]
                and hashlib.sha256(data).hexdigest() == pin["sha256"],
                "harness/helper source differs: " + str(path))
    require(all(name not in sys.modules for name in HELPERS),
            "fresh harness process required")
    sys.path.insert(0, str(ROOT / "source" / "native_profile_v4"))
    import profile_io
    import small_hcsn_profile
    import numeric_runner
    import bounded_process
    registration = profile_io.parse(raw)
    return registration, profile_io, small_hcsn_profile, numeric_runner, bounded_process


def limit_hit(number, _frame):
    raise TimeoutError("registered process limit reached: " + str(number))


def set_limits(child):
    require(platform.system() == "Linux", "registered runtime is Linux")
    signal.signal(signal.SIGALRM, limit_hit)
    signal.signal(signal.SIGXCPU, limit_hit)
    # Parent 55 + two children 46 = 147 hard CPU seconds in the process tree.
    # Soft limits permit retained failure/cleanup before those hard limits.
    soft, hard = (45, 46) if child else (50, 55)
    _, old_hard = resource.getrlimit(resource.RLIMIT_CPU)
    if old_hard != resource.RLIM_INFINITY:
        hard = min(hard, old_hard)
    soft = min(soft, hard)
    resource.setrlimit(resource.RLIMIT_CPU, (soft, hard))
    # The parent reserves up to five seconds for the existing group cleanup.
    signal.setitimer(signal.ITIMER_REAL, 50 if child else 175)
    sys.dont_write_bytecode = True
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"


def cpu_seconds():
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime


def preflight(registration, io, material_root):
    require(sys.executable == PYTHON and platform.python_version() == "3.14.4",
            "exact registered Python executable/version required")
    require(registration["runtime"]["python_executable"] == PYTHON,
            "registration interpreter differs")
    profile_raw = io.read_pin(ROOT, registration["profile"], 1024 * 1024)
    manifest = io.parse(profile_raw)
    require(manifest["format"] == "actual_hcsn_v2_selected"
            and manifest["origin"] == {"protocol_sha256": PROTOCOL,
                                       "coordinate_candidate_sha256": None}
            and manifest["checkpoint"]["sha256"] == CANDIDATE
            and manifest["checkpoint"]["bytes"] == 33078,
            "formal manifest is not the registered complete selected checkpoint")
    require(manifest["runtime"] == registration["runtime"]["numerical"],
            "registered numerical runtime differs")
    for pin in registration["material_pins"]:
        io.read_pin(material_root, pin, CAP)
    protocol = io.parse(io.read_pin(material_root, registration["protocol"], 1024 * 1024))
    require(protocol["cases"].count(registration["case"]) == 1,
            "formal protocol does not contain exactly the registered case")
    stimulus = io.parse(io.read_pin(ROOT, registration["stimulus"], 1024 * 1024))
    require(set(stimulus) == {"schema", "x", "margin"}
            and stimulus["schema"] == "hepta.formal-cached-scaled.stimulus.v1"
            and len(stimulus["x"]) == 12 and stimulus["margin"] == [0.55, 0.72],
            "fixed label-free stimulus differs")
    return manifest, stimulus


def make_task(numeric, profile_sha, x, initial):
    task = {"schema": numeric.TASK_SCHEMA, "task_id": CASE_ID,
            "profile_sha256": profile_sha, "candidate_sha256": CANDIDATE,
            "x": x, "initial": initial}
    require(numeric.validate_task(task) == 2, "fixed two-trajectory task required")
    return task


def child_run(args, registration, io, numeric, stimulus):
    raw = io.read_named(args.task, args.task_sha256, 1024 * 1024)
    task = io.parse(raw)
    expected_x = stimulus["x"][:5] if args.mode == "first" else stimulus["x"][5:]
    require(task["x"] == expected_x and task["task_id"] == CASE_ID,
            "cold task is outside its fixed segment")
    require(task["candidate_sha256"] == CANDIDATE
            and task["profile_sha256"] == registration["profile"]["sha256"],
            "cold task profile/candidate differs")
    if args.mode == "first":
        require(task["initial"] == {"kind": "margin", "margin": stimulus["margin"]},
                "first segment initial margin differs")
    else:
        require(task["initial"].get("kind") == "resume",
                "second segment must deserialize the saved five-tensor state")
    started = time.monotonic()
    result_pin = numeric.run(
        ROOT / registration["profile"]["path"], registration["profile"]["sha256"],
        args.material_root, args.task, args.task_sha256, args.state_root, args.output)
    result = io.parse(io.read_pin(args.output, result_pin, CAP), CAP)
    expected_steps = (0, 5) if args.mode == "first" else (5, 12)
    require((result["start_step"], result["end_step"]) == expected_steps,
            "cold segment clock differs")
    return {"pid": os.getpid(), "mode": args.mode, "result": result_pin,
            "wall_s": time.monotonic() - started, "cpu_s": cpu_seconds(),
            "model_load_calls": 1, "forward_calls": 1,
            "batched_solver_ticks": 5 if args.mode == "first" else 7}


def invoke(args, registration, io, numeric, bounded, stimulus, output, mode,
           initial, state_root):
    x = stimulus["x"][:5] if mode == "first" else stimulus["x"][5:]
    task = make_task(numeric, registration["profile"]["sha256"], x, initial)
    task_pin = io.write_new(output / (mode + "-task.json"),
                            io.canonical(task) + b"\n", 1024 * 1024)
    child_output = output / mode
    command = [sys.executable, "-B", str(ROOT / "run_formal_cached_scaled_resume.py"),
               "--registration-sha256", args.registration_sha256,
               "--material-root", str(Path(args.material_root).absolute()),
               "--mode", mode, "--task", str(output / task_pin["path"]),
               "--task-sha256", task_pin["sha256"], "--state-root", str(state_root),
               "--output", str(child_output)]
    child = io.parse(bounded.run_child(command), 32768)
    require(child["mode"] == mode and child["pid"] != os.getpid()
            and child["model_load_calls"] == 1 and child["forward_calls"] == 1,
            "fresh cold invocation identity differs")
    result = io.parse(io.read_pin(child_output, child["result"], CAP), CAP)
    require(result["task_sha256"] == task_pin["sha256"], "cold task receipt differs")
    io.write_new(output / (mode + "-process.json"),
                 io.canonical({"command": command, **child}) + b"\n", 65536)
    return child_output, result, child


def parent_run(args, registration, io, profiles, numeric, bounded,
               manifest, stimulus, output):
    torch_profile = profiles.load_profile(
        ROOT / registration["profile"]["path"], registration["profile"]["sha256"],
        args.material_root)
    profile, torch = torch_profile, torch_profile.torch
    require(profile.constructor == "cached_scaled"
            and type(profile.model).__name__ == "CachedSmallHCSN"
            and type(profile.model.readout).__name__ == "ScaledReadout",
            "formal scaled constructor required")
    require(profile.config["neurons"] == 8 and profile.config["input_size"] == 6
            and profile.config["feature_bank"] == "value_risk"
            and profile.config["message_mode"] == "full"
            and profile.config["precision"] == "float64"
            and profile.config["backend"] == "dense"
            and profile.model.recurrent.weight.requires_grad,
            "formal N8/full/learned model config differs")
    require(type(profile.config["slow_every"]) is int
            and profile.config["slow_every"] == 2
            and profile.model.feature_dim == 20,
            "split must lie inside a frozen control epoch")
    require(tuple(profiles.STATE_FIELDS) == STATE, "five-state contract differs")
    state_dict = profile.model.state_dict()
    require(set(name for name in state_dict if name.startswith("readout.")) == set(READOUT),
            "all four ScaledReadout entries required")
    buffers = dict(profile.model.named_buffers())
    require("readout.mean" in buffers and "readout.scale" in buffers
            and bool((buffers["readout.scale"] > 0).all()),
            "positive saved readout buffers required")
    before = {name: state_dict[name].detach().clone() for name in READOUT}
    head_digest = profiles.tensor_state_sha256(before)
    config_digest = io.sha(io.canonical(profile.config))
    identity = {"profile_sha256": profile.profile_sha256,
                "candidate_sha256": profile.candidate_sha256,
                "model_state_sha256": profile.model_state_sha256,
                "source_binding_sha256": profile.source_binding_sha256}
    require(identity["candidate_sha256"] == CANDIDATE, "different candidate loaded")
    x = torch.tensor(stimulus["x"], dtype=torch.float64, device="cpu")
    margin = torch.tensor(stimulus["margin"], dtype=torch.float64)[:, None]
    with torch.no_grad():
        initial = profile.initial_state(2, margin)
        initial_state_pin = profile.save_state(initial, output / "initial-population.pt")
        logits, features, final = profile.forward(x, initial)
    require(final.step == 12, "complete trajectory did not end at step 12")
    complete_state_pin = profile.save_state(final, output / "complete-population.pt")
    first_dir, first, first_process = invoke(
        args, registration, io, numeric, bounded, stimulus, output, "first",
        {"kind": "margin", "margin": stimulus["margin"]}, output)
    first_state = profile.load_state(first["population"], first_dir)
    require(first_state.step == 5 and first_state.config == profile.model.config,
            "first serialized complete state differs")
    second_dir, second, second_process = invoke(
        args, registration, io, numeric, bounded, stimulus, output, "second",
        {"kind": "resume", "artifact": first["population"]}, first_dir)
    require(len({os.getpid(), first_process["pid"], second_process["pid"]}) == 3,
            "three distinct model processes required")
    for result, start, end in ((first, 0, 5), (second, 5, 12)):
        require(all(result[key] == value for key, value in identity.items())
                and result["start_step"] == start and result["end_step"] == end
                and result["diagnostics_scope"] == "this_call_only"
                and result["production_adoption"] is False
                and result["real_cross_user_acceptance"] is False,
                "cold result identity/clock/scope differs")
    restored = profile.load_state(second["population"], second_dir)
    baseline = profile.load_state(complete_state_pin, output)
    require(restored.step == baseline.step == final.step == 12
            and restored.config == baseline.config == final.config,
            "full final config or step differs")
    comparisons = {}
    pairs = {"logits": (torch.tensor(first["logits"] + second["logits"],
                                     dtype=torch.float64), logits),
             "features": (torch.tensor(first["features"] + second["features"],
                                       dtype=torch.float64), features)}
    pairs.update({name: (getattr(restored, name), getattr(final, name)) for name in STATE})
    for name, (actual, expected) in pairs.items():
        torch.testing.assert_close(actual, expected, rtol=RTOL, atol=ATOL)
        delta = (actual - expected).abs()
        comparisons[name] = {"shape": list(expected.shape),
                             "max_absolute_error": float(delta.max()),
                             "max_tolerance_ratio": float(
                                 (delta / (ATOL + RTOL * expected.abs())).max())}
    for name in STATE:
        require(torch.equal(getattr(baseline, name), getattr(final, name)),
                "baseline serialized tensor changed")
    after = profile.model.state_dict()
    for name in READOUT:
        require(torch.equal(before[name], after[name]), "readout parameter/buffer changed")
    profile.require_frozen()
    require(profile.current_state_sha256() == identity["model_state_sha256"],
            "complete model changed")
    complete = {**identity, "config": profile.config, "config_sha256": config_digest,
                "runtime": manifest["runtime"], "logits": logits.tolist(),
                "features": features.tolist(),
                "readout": {name: before[name].tolist() for name in READOUT},
                "readout_state_sha256": head_digest, "population": complete_state_pin}
    complete_pin = io.write_new(output / "complete.json",
                                io.canonical(complete) + b"\n", CAP)
    return {"schema": "hepta.formal-cached-scaled.cold-resume.v1",
            "status": "PASS", "case_id": CASE_ID, **identity,
            "constructor": profile.constructor, "feature_dim": profile.model.feature_dim,
            "config": profile.config,
            "config_sha256": config_digest, "runtime": manifest["runtime"],
            "readout_state_sha256": head_digest, "readout_unchanged": True,
            "readout_binding_across_processes": "identical full model tensor digest",
            "comparisons": comparisons, "rtol": RTOL, "atol": ATOL,
            "split_steps": [12, 5, 7], "batch": 2, "model_load_calls": 3,
            "forward_calls": 3, "batched_solver_ticks": 24, "trajectory_ticks": 48,
            "gradient_steps": 0, "seed_searches": 0, "cold_processes": 2,
            "dynamic_state_deserializations": 4,
            "initial_population": initial_state_pin,
            "complete_result": complete_pin,
            "first_result": {**first_process["result"],
                             "path": "first/" + first_process["result"]["path"]},
            "second_result": {**second_process["result"],
                              "path": "second/" + second_process["result"]["path"]},
            "profile_manifest_sha256": registration["profile"]["sha256"],
            "registration_sha256": args.registration_sha256,
            "production_adoption": False, "real_cross_user_acceptance": False,
            "scientific_qualification_transferred": False}


def main():
    started = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registration-sha256", required=True)
    parser.add_argument("--material-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--mode", choices=("parent", "first", "second"), default="parent")
    parser.add_argument("--task")
    parser.add_argument("--task-sha256")
    parser.add_argument("--state-root")
    args = parser.parse_args()
    output = None
    io = None
    try:
        set_limits(args.mode != "parent")
        registration, io, profiles, numeric, bounded = bootstrap(args.registration_sha256)
        manifest, stimulus = preflight(registration, io, args.material_root)
        if args.mode != "parent":
            require(args.task and args.task_sha256 and args.state_root,
                    "complete child invocation required")
            result = child_run(args, registration, io, numeric, stimulus)
            print(io.canonical(result).decode())
            return 0
        require(args.task is None and args.task_sha256 is None and args.state_root is None,
                "parent cannot accept alternative tasks or initial states")
        proposed_output = Path(args.output).absolute()
        proposed_output.mkdir(mode=0o700, parents=False, exist_ok=False)
        output = proposed_output
        io.write_new(output / "START.json", io.canonical({
            "registration_sha256": args.registration_sha256, "pid": os.getpid(),
            "case_id": CASE_ID, "wall_limit_s": 180, "cpu_limit_s": 150,
            "status": "STARTED_NO_RESULT"}) + b"\n", 4096)
        result = parent_run(args, registration, io, profiles, numeric, bounded,
                            manifest, stimulus, output)
        result["wall_s"] = time.monotonic() - started
        result["cpu_s"] = cpu_seconds()
        require(result["wall_s"] <= 180 and result["cpu_s"] <= 150,
                "total registered allowance exceeded")
        pin = io.write_new(output / "RESULT.json", io.canonical(result) + b"\n", CAP)
        print(io.canonical(pin).decode())
        return 0
    except BaseException as error:
        failure = {"schema": "hepta.formal-cached-scaled.cold-resume-failure.v1",
                   "status": "FAIL", "case_id": CASE_ID,
                   "error_type": type(error).__name__, "error": str(error)[:8192],
                   "wall_s": time.monotonic() - started, "cpu_s": cpu_seconds(),
                   "registration_sha256": args.registration_sha256}
        if output is not None and io is not None:
            try:
                io.write_new(output / "FAILURE.json", io.canonical(failure) + b"\n", 32768)
            except (OSError, ValueError):
                pass
        print(json.dumps(failure, sort_keys=True, allow_nan=False), file=sys.stderr)
        return 1
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


if __name__ == "__main__":
    raise SystemExit(main())
