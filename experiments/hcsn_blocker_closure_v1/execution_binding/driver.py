"""Bind one preselected trained checkpoint to real streaming/native execution."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import resource
import shutil
import statistics
import subprocess
import sys
import time

import numpy as np
import torch

from experiments.hcsn_blocker_closure_v1.content.models import build
from experiments.hcsn_blocker_closure_v1.content.study import source_map, state_hash
from experiments.hcsn_blocker_closure_v1.execution_binding.state_io import numeric_state, read_state
from experiments.hcsn_blocker_closure_v1.runtime.hardware import hardware_inventory
from experiments.hcsn_free_boundary_v1.native_bridge import MANIFEST, NativeSession, Signals, UPSTREAM


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).parent
MODULE = "experiments.hcsn_blocker_closure_v1.execution_binding.driver"
SEED = 881101
JOB_ID = "selective_copy__value_jg__seed881101"
OBJECTIVE = dict(name="trained-content-value-route-engineering-v1",
                 purpose="Streaming recovery and causal native routing of actual trained J-G",
                 task_optimality_claim=False, task_utility_claim=False)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def load_json(path):
    return json.loads(Path(path).read_bytes())


def state_digest(state):
    digest = hashlib.sha256()
    for name, array in sorted(numeric_state(state).items()):
        digest.update(json.dumps([name, str(array.dtype), list(array.shape)]).encode())
        digest.update(array.tobytes())
    return digest.hexdigest()


def child(command, log):
    start = time.perf_counter()
    env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
               PYTHONDONTWRITEBYTECODE="1")
    with Path(log).open("xb") as stream:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
        _, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    return dict(command=command, exit_code=process.returncode,
                child_and_reaped_descendant_cpu_seconds=usage.ru_utime+usage.ru_stime,
                wall_seconds=time.perf_counter()-start, peak_rss_kib=usage.ru_maxrss,
                nested_scope="Contained in enclosing worker wait4; do not add scopes")


def verify_contract(output):
    contract = load_json(output/"BINDING.json")
    for path, expected in contract["files"].items():
        if sha(output/path) != expected:
            raise ValueError("Binding input changed: "+path)
    for path, expected in contract["sources"].items():
        if sha(ROOT/path) != expected:
            raise ValueError("Binding source changed: "+path)
    return contract


def model_from(output):
    contract = verify_contract(output)
    model = build("value_jg", input_dim=64, output_dim=8, width=32, depth=1, seed=SEED).eval()
    with np.load(output/"weights.npz", allow_pickle=False) as archive:
        model.load_state_dict({k: torch.from_numpy(np.array(archive[k], copy=True)) for k in archive.files})
    if state_hash(model.state_dict()) != contract["selected"]["tensor_hash"]:
        raise ValueError("Checkpoint tensor identity changed")
    return model


def inputs(output, length):
    with np.load(output/"train_episode.npz", allow_pickle=False) as archive:
        x, dt = archive["x"], archive["dt"]
        repeats = math.ceil(length/x.shape[1])
        return (torch.from_numpy(np.tile(x, (1, repeats, 1))[:, :length].copy()),
                torch.from_numpy(np.tile(dt, (1, repeats))[:, :length].copy()))


def verify_study_contract(study, expected_commit, expected_protocol_sha256):
    """Expected digests come from the independently verified hosted publication."""
    if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
        raise ValueError("An independently pinned training commit is required")
    if (not re.fullmatch(r"[0-9a-f]{64}", expected_protocol_sha256)
            or sha(study/"PROTOCOL.json") != expected_protocol_sha256):
        raise ValueError("Registered study protocol does not match the external pin")
    protocol = load_json(study/"PROTOCOL.json")
    if (protocol["schema"] != "hcsn-blocker-content-protocol.v1" or protocol["status"] != "registered"
            or protocol["public_execution_commit"] != expected_commit
            or protocol["design"] != load_json(HERE.parent/"content/DESIGN.json")
            or protocol["source_sha256"] != source_map()):
        raise ValueError("Unexpected source study contract")
    preflight = ROOT/protocol["preflight"]["file"]
    if sha(preflight) != protocol["preflight"]["sha256"]:
        raise ValueError("Registered source preflight changed")
    proof = load_json(preflight)
    if proof.get("passed") is not True or proof.get("source_sha256") != protocol["source_sha256"]:
        raise ValueError("Registered source preflight is not complete")
    return protocol


def prepare(study, output, binary, expected_commit, expected_protocol_sha256, expected_checkpoint_sha256):
    design = load_json(HERE/"PROTOCOL.json")
    protocol = verify_study_contract(study, expected_commit, expected_protocol_sha256)
    directory = study/"fixed"/JOB_ID
    job, selected = load_json(directory/"job.json"), load_json(directory/"selection.json")
    expected_job = dict(stage="fixed", task="selective_copy", arm="value_jg", seed=SEED,
                        id=JOB_ID, updates=protocol["design"]["formal_updates"])
    if any(job[k] != v for k, v in expected_job.items()):
        raise ValueError("This is not the preselected trained worker")
    if ([job["updates"]//2, job["updates"]] != design["selection"]["allowed_validation_steps"]
            or not re.fullmatch(r"[0-9a-f]{64}", expected_checkpoint_sha256)
            or sha(directory/"selected_state.npz") != expected_checkpoint_sha256):
        raise ValueError("Checkpoint does not match the external pin or validation schedule")
    validations = []
    for step in design["selection"]["allowed_validation_steps"]:
        path = directory/f"validation_{step:06d}.npz"
        with np.load(path, allow_pickle=False) as archive:
            logits, labels = archive["logits"].astype(np.float64), archive["labels"].astype(np.int64)
        shifted = logits-logits.max(1, keepdims=True)
        ce = float((np.log(np.exp(shifted).sum(1))-shifted[np.arange(len(labels)), labels]).mean())
        validations.append(dict(step=step, cross_entropy=ce, file=path.name, sha256=sha(path)))
    best = min(validations, key=lambda row: (row["cross_entropy"], row["step"]))
    if (selected["step"] != best["step"] or abs(selected["cross_entropy"]-best["cross_entropy"]) > 2e-12
            or selected["sha256"] != best["sha256"] or sha(directory/"selected_state.npz") != selected["state_sha256"]):
        raise ValueError("Validation-selected checkpoint provenance failed")
    source = dict(protocol["source_sha256"])
    for path in list(HERE.glob("*.py"))+[HERE/"PROTOCOL.json"]:
        source[str(path.relative_to(ROOT))] = sha(path)
    for name in ("native_bridge.py", "restore_native.py", "native_vendor/adapter.py", "native_vendor/MANIFEST.json"):
        path = ROOT/"experiments/hcsn_free_boundary_v1"/name
        source[str(path.relative_to(ROOT))] = sha(path)
    path = HERE.parent/"runtime/hardware.py"
    source[str(path.relative_to(ROOT))] = sha(path)
    for path, expected in source.items():
        if sha(ROOT/path) != expected:
            raise ValueError("Registered source mismatch: "+path)
    data_row = protocol["data"]["selective_copy"]["train"]
    train_path = study/"data"/data_row["file"]
    if sha(train_path) != data_row["sha256"]:
        raise ValueError("Training input source changed")
    with np.load(train_path, allow_pickle=False) as archive:
        np.savez_compressed(output/"train_episode.npz", x=archive["x"][:1], dt=archive["dt"][:1])
    shutil.copyfile(directory/"selected_state.npz", output/"weights.npz")
    if sha(binary) != MANIFEST["binary_sha256"]:
        raise ValueError("Native executable identity mismatch")
    contract = dict(schema="hcsn-trained-checkpoint-binding.v1", design=design, selected=selected, job=job,
        public_execution_commit=protocol.get("public_execution_commit"), study_protocol_sha256=sha(study/"PROTOCOL.json"),
        job_sha256=sha(directory/"job.json"), selection_sha256=sha(directory/"selection.json"),
        validations=validations, trained_checkpoint_sha256=sha(output/"weights.npz"),
        training_input_sha256=data_row["sha256"], sources=source,
        files={name: sha(output/name) for name in ("weights.npz", "train_episode.npz")},
        binary=str(binary.resolve()), binary_sha256=sha(binary), formal_test_outcomes_accessed=False)
    contract["external_pins"] = dict(public_execution_commit=expected_commit,
        study_protocol_sha256=expected_protocol_sha256, checkpoint_sha256=expected_checkpoint_sha256,
        origin="CLI values from independently verified hosted publication; never chosen by task outcomes")
    write(output/"BINDING.json", contract)
    hardware = hardware_inventory()
    hardware.update(torch_version=torch.__version__, torch_cuda_build=torch.version.cuda,
                    torch_cuda_available=torch.cuda.is_available(), torch_cuda_device_count=torch.cuda.device_count())
    write(output/"HARDWARE.json", hardware)
    return contract


def stream(output):
    target = output/"stream"
    target.mkdir()
    model, (x, dt) = model_from(output), inputs(output, 128)
    state, logits, sizes, records, masses = None, [], [], [], []
    with torch.inference_mode():
        full = model(x, dt, return_sequence=True, return_aux=False)
        for index in range(128):
            value, state, aux = model.step(x[:, index], dt[:, index], state)
            logits.append(value)
            sizes.append(sum(v.nbytes for v in numeric_state(state).values()))
            masses.append(float((state["layers"][0]["probability"].double().sum(-1)-1).abs().max()))
            records.append(dict(index=index, state_sha256=state_digest(state), logits=value.tolist(),
                J=float(aux["policy_J"].mean()), G=float(aux["policy_G"].mean()),
                value_difference=float((aux["policy_J"]-aux["policy_G"]).mean())))
            if index == 36:
                np.savez_compressed(target/"mid_state.npz", **numeric_state(state))
                middle_refractory = float(state["layers"][0]["probability"][..., 8:].sum(-1).max())
    streaming = torch.stack(logits, 1)
    np.savez_compressed(target/"expected_logits.npz", logits=streaming[:, 37:].numpy())
    np.savez_compressed(target/"expected_state.npz", **numeric_state(state))
    write(target/"RESUME_INPUT.json", dict(state_sha256=sha(target/"mid_state.npz"), cut=37, length=128))
    cost = child([sys.executable, "-m", MODULE, "resume", "--output", str(output)], target/"resume.log")
    write(target/"RESUME_COST.json", cost)
    if cost["exit_code"]:
        raise RuntimeError("Fresh interpreter recovery failed")
    with np.load(target/"resumed_logits.npz") as a:
        equal_logits = np.array_equal(a["logits"], streaming[:, 37:].numpy())
    expected = numeric_state(state)
    with np.load(target/"resumed_state.npz") as a:
        equal_state = set(a.files) == set(expected) and all(np.array_equal(a[k], expected[k]) for k in expected)
    result = dict(length=128, cut=37, batch=1, suffix_logits_bitwise_equal=equal_logits,
        suffix_state_bitwise_equal=equal_state, batch_stream_max_abs_logit_error=float((full-streaming).abs().max()),
        batch_stream_argmax_disagreements=int((full.argmax(-1) != streaming.argmax(-1)).sum()),
        state_bytes_min=min(sizes), state_bytes_max=max(sizes), midpoint_refractory_mass=middle_refractory,
        maximum_probability_mass_defect=max(masses), resume_execution=cost)
    write(target/"RESULT.json", result)
    write(target/"TRAINING_PANEL.json", records[:32])
    if not (equal_logits and equal_state and result["batch_stream_max_abs_logit_error"] <= 1e-4
            and result["batch_stream_argmax_disagreements"] == 0 and min(sizes) == max(sizes) and middle_refractory > 0):
        raise AssertionError("Trained streaming recovery contract failed")
    return result


def resume(output):
    model, (x, dt) = model_from(output), inputs(output, 128)
    target = output/"stream"
    contract = load_json(target/"RESUME_INPUT.json")
    if sha(target/"mid_state.npz") != contract["state_sha256"]:
        raise ValueError("Resume state changed")
    state, logits = read_state(target/"mid_state.npz", 1), []
    with torch.inference_mode():
        for index in range(contract["cut"], contract["length"]):
            value, state, _ = model.step(x[:, index], dt[:, index], state)
            logits.append(value)
    np.savez_compressed(target/"resumed_logits.npz", logits=torch.stack(logits, 1).numpy())
    np.savez_compressed(target/"resumed_state.npz", **numeric_state(state))


class BindingSession(NativeSession):
    """Inherited actual IPC/retry/STOP guards with an honest engineering profile."""

    def __init__(self, root, binary, model_digest, case, resume=False):
        self.root, self.case, self.seed, self.policy = Path(root), case, SEED, "continuation_only"
        kernel = dict(width=5, top_k=1, temporal_decay_q24=0, activity_decay_q24=0,
                      target_activity_q24=0, threshold_rate_q24=0, threshold_min_q24=0,
                      threshold_max_q24=0, eligibility_decay_q24=0)
        self.profile = UPSTREAM.make_profile(["trained_policy_value_message"],
            [[1, 0, 0, 0], [-1, 0, 0, 0], [0, .1, 0, 0], [0, 0, .1, 0], [0, 0, 0, .1]],
            [-.05, .05, -4, -4, -4], [[1, -1, 0, 0, 0], [0]*5, [0]*5], [0, -8, 0],
            source_model_digest=model_digest, objective_digest=UPSTREAM.digest(OBJECTIVE),
            arm_id="trained-value-engineering", kernel=kernel, maximum_ticks=512)
        path, self.profile_digest = UPSTREAM.save_profile(self.root/"profiles", self.profile)
        self.bridge = UPSTREAM.NativeBridge(binary, self.root, expected_binary_sha256=MANIFEST["binary_sha256"])
        identity = self.bridge.identity
        if (identity["owner_authority"] != "DENY_ALL" or identity["source_commit"] != MANIFEST["native_base_commit"]
                or identity["source_manifest_digest"] != MANIFEST["source_manifest_sha256"]):
            self.bridge.close()
            raise ValueError("Native source identity mismatch")
        self.bridge.load_profile(path, self.profile_digest)
        self.open_receipt = self.bridge.open(case, SEED, self.profile_digest, resume=resume)
        self.terminal, self.events = bool(self.open_receipt["status"]["terminal"]), []


def native_episode(output, root, start, stop, state=None, restore=False):
    contract, model = verify_contract(output), model_from(output)
    x, dt = inputs(output, 12)
    session = BindingSession(root, contract["binary"], contract["trained_checkpoint_sha256"],
                             "trained-content-stream-v1", restore)
    rows, calls = [], 0

    def read(index):
        nonlocal state, calls
        if session.terminal:
            raise RuntimeError("No neural read after native STOP")
        with torch.inference_mode():
            logits, state, aux = model.step(x[:, index], dt[:, index], state)
        calls += 1
        budget = 1. if index+1 < 6 else -1.
        value = float(torch.tanh((aux["policy_J"]-aux["policy_G"]).mean()))
        signals = Signals(.6*budget+.2*value, float(torch.tanh(aux["margin"].mean())),
                          float(aux["refractory_mass"].mean()), float(-torch.expm1(-aux["activity"].mean())))
        row = session.tick(signals, context=dict(read=index+1, engineering_budget=budget))
        row.update(logits=logits.tolist(), read=index+1, state_sha256=state_digest(state))
        return row

    try:
        for index in range(start, stop):
            if session.terminal:
                break
            rows.append(read(index))
        retry = session.verify_retry()
        terminal = session.verify_terminal() if session.terminal else None
        rejected = False
        calls_before_probe = calls
        if session.terminal:
            try:
                read(0)
            except RuntimeError as error:
                rejected = str(error) == "No neural read after native STOP"
        result = dict(events=rows, calls=calls, retry=retry, terminal_guard=terminal,
                      terminal=session.terminal, post_STOP_neural_read_rejected=rejected,
                      post_STOP_neural_calls=calls-calls_before_probe, risk_field="refractory probability, not first-event risk")
    finally:
        cost = session.close()
    result["native_cost"] = cost
    return result, state


def native_check(output):
    target = output/"native"
    target.mkdir()
    full, full_state = native_episode(output, target/"full", 0, 12)
    prefix, mid = native_episode(output, target/"resumed", 0, 3)
    np.savez_compressed(target/"mid_state.npz", **numeric_state(mid))
    write(target/"RESUME_INPUT.json", dict(state_sha256=sha(target/"mid_state.npz")))
    cost = child([sys.executable, "-m", MODULE, "native-resume", "--output", str(output)], target/"resume.log")
    write(target/"RESUME_COST.json", cost)
    if cost["exit_code"]:
        raise RuntimeError("Fresh-interpreter native recovery failed")
    suffix = load_json(target/"SUFFIX.json")
    joined = prefix["events"]+suffix["events"]
    actions = [row["native"]["effective_action"] for row in full["events"]]
    semantic_fields = ("effective_action", "checkpoint_before", "checkpoint_after", "input_feature_digest",
        "event_digest", "profile_sha256", "owner_authority", "seed", "step", "terminal", "activation_q24",
        "eligibility_q24", "readout")
    def semantic(row):
        return {**{key: row[key] for key in ("signals", "context", "logits", "read", "state_sha256")},
                "native": {key: row["native"][key] for key in semantic_fields}}
    exact_rows = [semantic(row) for row in full["events"]] == [semantic(row) for row in joined]
    expected = numeric_state(full_state)
    with np.load(target/"resumed_state.npz") as a:
        exact_state = set(a.files) == set(expected) and all(np.array_equal(a[k], expected[k]) for k in expected)
    result = dict(full=full, prefix=prefix, suffix=suffix, expected_actions=["keep"]*5+["stop"],
                  actual_actions=actions, semantic_event_rows_equal=exact_rows, native_equal_fields=semantic_fields,
                  neural_state_bitwise_equal=exact_state, actual_native_processes=3, resume_execution=cost, objective=OBJECTIVE)
    write(target/"RESULT.json", result)
    if not (actions == ["keep"]*5+["stop"] and exact_rows and exact_state
            and full["terminal_guard"]["passed"] and suffix["terminal_guard"]["passed"]
            and full["post_STOP_neural_read_rejected"] and suffix["post_STOP_neural_read_rejected"]
            and full["post_STOP_neural_calls"] == suffix["post_STOP_neural_calls"] == 0
            and all(row["native_cost"]["exit_code"] == 0 for row in (full, prefix, suffix))):
        raise AssertionError("Native trained-model recovery failed")
    return result


def native_resume(output):
    target = output/"native"
    if sha(target/"mid_state.npz") != load_json(target/"RESUME_INPUT.json")["state_sha256"]:
        raise ValueError("Native resume state changed")
    result, state = native_episode(output, target/"resumed", 3, 12,
                                   read_state(target/"mid_state.npz", 1), True)
    write(target/"SUFFIX.json", result)
    np.savez_compressed(target/"resumed_state.npz", **numeric_state(state))


def causal(output):
    target = output/"causal"
    target.mkdir()
    contract, records = verify_contract(output), load_json(output/"stream/TRAINING_PANEL.json")
    low = min(range(len(records)), key=lambda i: records[i]["value_difference"])
    high = max(range(len(records)), key=lambda i: records[i]["value_difference"])
    lo, hi = records[low]["value_difference"], records[high]["value_difference"]
    threshold = (lo+hi)/2
    message = lambda value: .05+.9*math.tanh(value-threshold)
    gaps = [UPSTREAM.quantize(.05)-UPSTREAM.quantize(message(lo)),
            UPSTREAM.quantize(message(hi))-UPSTREAM.quantize(.05)]
    write(target/"CALIBRATION.json", dict(low=low, high=high, low_value=lo, high_value=hi,
        threshold=threshold, q24_gaps=gaps, source="first unlabeled training episode; no quality selection"))
    if min(gaps) < 16:
        raise AssertionError("Training panel did not produce resolvable causal messages")
    x, dt = inputs(output, 32)
    rows = []
    for name, index, sent, expected in [("natural_low", low, lo, "stop"), ("natural_high", high, hi, "keep"),
        ("high_state_low_message", high, lo, "stop"), ("low_state_high_message", low, hi, "keep")]:
        model, state = model_from(output), None
        with torch.inference_mode():
            for step in range(index+1):
                logits, state, aux = model.step(x[:, step], dt[:, step], state)
        actual = float((aux["policy_J"]-aux["policy_G"]).mean())
        if (state_digest(state) != records[index]["state_sha256"] or actual != records[index]["value_difference"]
                or logits.tolist() != records[index]["logits"]):
            raise AssertionError("Trained state replay changed")
        if name in ("natural_low", "natural_high"):
            np.savez_compressed(target/(name+"_state.npz"), **numeric_state(state))
        session = BindingSession(target/name, contract["binary"], contract["trained_checkpoint_sha256"], "trained-content-causal-v1")
        try:
            session.tick(Signals(.75, 0., 0., 0.), context=dict(kind="identical_prefix", external_budget=0., read_fee=0.))
            prefix = dict(session.bridge.current)
            event = session.tick(Signals(message(sent), 0., 0., 0.), context=dict(kind="value_swap", threshold=threshold,
                external_budget=0., read_fee=0.))
            retry, terminal = session.verify_retry(), session.verify_terminal() if session.terminal else None
            row = dict(case=name, neural_index=index, actual_value=actual, actual_J=float(aux["policy_J"].mean()),
                       actual_G=float(aux["policy_G"].mean()), sent_value=sent, state_sha256=state_digest(state),
                       prefix=prefix, event=event, expected_action=expected, actual_action=event["native"]["effective_action"],
                       retry=retry, terminal_guard=terminal)
        finally:
            cost = session.close()
        row["native_cost"] = cost
        rows.append(row)
        write(target/(name+".json"), row)
    passed = (all(row["actual_action"] == row["expected_action"] and row["native_cost"]["exit_code"] == 0 for row in rows)
              and all(row["prefix"] == rows[0]["prefix"] for row in rows))
    result = dict(passed=passed, cases=rows, actual_native_processes=4, threshold=threshold,
                  scope="Causal engineering route; calibration is not useful classification stopping")
    write(target/"RESULT.json", result)
    if not passed:
        raise AssertionError("Trained value-message causal route failed")
    return result


def scale(output, length):
    model, (x, dt) = model_from(output), inputs(output, length)
    cpu, wall = [], []
    with torch.inference_mode():
        model(x, dt, return_sequence=True, return_aux=False)
        for _ in range(3):
            c, t = time.process_time(), time.perf_counter()
            batch = model(x, dt, return_sequence=True, return_aux=False)
            cpu.append(time.process_time()-c)
            wall.append(time.perf_counter()-t)
        state, logits, sizes, reads = None, [], [], []
        c, t = time.process_time(), time.perf_counter()
        for index in range(length):
            tick = time.perf_counter()
            value, state, _ = model.step(x[:, index], dt[:, index], state)
            reads.append(time.perf_counter()-tick)
            logits.append(value)
            sizes.append(sum(v.nbytes for v in numeric_state(state).values()))
        stream_cpu, stream_wall = time.process_time()-c, time.perf_counter()-t
    streaming = torch.stack(logits, 1)
    result = dict(length=length, batch=1, batch_warmup=1, batch_repetitions=3,
        batch_cpu_seconds=cpu, batch_wall_seconds=wall, batch_median_wall_seconds=statistics.median(wall),
        stream_cpu_seconds=stream_cpu, stream_wall_seconds=stream_wall,
        stream_read_p50_seconds=float(np.quantile(reads, .5)), stream_read_p95_seconds=float(np.quantile(reads, .95)),
        state_bytes_min=min(sizes), state_bytes_max=max(sizes), weight_tensor_bytes=sum(p.numel()*p.element_size() for p in model.parameters()),
        state_scope="Elapsed/content/probability/boundary only; full-batch temporaries, inputs, outputs, weights and BPTT excluded",
        batch_stream_max_abs_logit_error=float((batch-streaming).abs().max()),
        argmax_disagreements=int((batch.argmax(-1) != streaming.argmax(-1)).sum()),
        process_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        finite_logits=bool(torch.isfinite(batch).all() and torch.isfinite(streaming).all()))
    write(output/f"scale_{length:04d}.json", result)
    if not (result["finite_logits"] and min(sizes) == max(sizes) and result["argmax_disagreements"] == 0
            and result["batch_stream_max_abs_logit_error"] <= 1e-4):
        raise AssertionError("Scale inference contract failed")
    return result


def run(study, output, binary, expected_commit, expected_protocol_sha256, expected_checkpoint_sha256):
    contract = prepare(study, output, binary, expected_commit, expected_protocol_sha256, expected_checkpoint_sha256)
    summary = dict(stream=stream(output), native=native_check(output), causal=causal(output), scaling=[])
    for length in (32, 128, 512):
        cost = child([sys.executable, "-m", MODULE, "scale", "--output", str(output), "--length", str(length)], output/f"scale_{length:04d}.log")
        write(output/f"scale_{length:04d}_COST.json", cost)
        if cost["exit_code"]:
            raise RuntimeError("Scale child failed; retained logs")
        summary["scaling"].append(dict(result=load_json(output/f"scale_{length:04d}.json"), complete_worker=cost))
    verify_contract(output)
    state_sizes = {row["result"][key] for row in summary["scaling"] for key in ("state_bytes_min", "state_bytes_max")}
    if len(state_sizes) != 1:
        raise AssertionError("Persistent neural state grew across sequence lengths")
    summary.update(schema="hcsn-trained-execution-binding-result.v1", passed=True,
        checkpoint_sha256=contract["trained_checkpoint_sha256"], selected_step=contract["selected"]["step"],
        public_training_execution_commit=contract["public_execution_commit"],
        actual_native_processes=7, source_unchanged=True, formal_test_outcomes_accessed=False,
        persistent_state_bytes_across_lengths=next(iter(state_sizes)),
        nonclaims=contract["design"]["nonclaims"], outer_complete_worker_cost="WHOLE_WORKER_COST.json")
    write(output/"RESULT.json", summary)
    print(json.dumps(dict(passed=True, checkpoint_sha256=summary["checkpoint_sha256"],
                         selected_step=summary["selected_step"], native_processes=7)), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "resume", "native-resume", "scale"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--study", type=Path)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--expected-study-commit")
    parser.add_argument("--expected-study-protocol-sha256")
    parser.add_argument("--expected-checkpoint-sha256")
    parser.add_argument("--length", type=int)
    args = parser.parse_args()
    torch.set_num_threads(1)
    if args.command == "run":
        if not all((args.study, args.binary, args.expected_study_commit,
                    args.expected_study_protocol_sha256, args.expected_checkpoint_sha256)):
            parser.error("run requires study, binary and all three independently verified evidence pins")
        run(args.study.resolve(), args.output.resolve(), args.binary.resolve(), args.expected_study_commit,
            args.expected_study_protocol_sha256, args.expected_checkpoint_sha256)
    elif args.command == "resume":
        resume(args.output.resolve())
    elif args.command == "native-resume":
        native_resume(args.output.resolve())
    else:
        scale(args.output.resolve(), args.length)
