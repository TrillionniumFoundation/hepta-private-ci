"""Independent artifact reader: no model imports, trajectory, AD or optimizer calls.

Saved deterministic-delay packets require NEW numerical matrix integrals to
reconstruct waiting mass. These independent SciPy actions are counted explicitly;
zero model calls does not mean zero numerical work. Source and input hashes must
be frozen before the one-shot, separately costed worker is started.
"""

import argparse
import csv
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import sys
import time
import traceback
import zipfile


PROTOCOL_SHA = "9601216e77b3dc5b3b41f77d7df8f124b7ab176692b0a0b66f24773b95eec9e0"
SOURCE_COMMIT = "8fe7bc209803659cc3f4780be0940c5183ca6e9b"
FIELDS = ("active", "upper", "hits", "discounted_hits", "occupation", "value", "discount_factor")
PHASE_FIELDS = ("density", "hits", "discounted_hits", "occupation", "value", "discount_factor",
                "messages", "written", "initial_totals")
GLOBAL_FIELDS = ("messages", "written", "initial_totals")
ARMS, LENGTHS = ("flow", "flow_erlang4"), (10, 20, 40, 80)
THREAD_ENV = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
              "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def check_keys(value, expected, label):
    require(type(value) is dict and set(value) == set(expected), "key set: " + label)


def rational(value):
    require(type(value) is list and len(value) == 2
            and all(type(x) is int for x in value) and value[1] > 0, "rational clock")
    return Fraction(*value)


def tensor_paths(value, prefix=""):
    """Traverse every tensor; no producer serializer/deserializer is imported."""
    if type(value) is dict:
        for name, child in value.items():
            yield from tensor_paths(child, f"{prefix}/{name}")
    elif type(value) in (list, tuple):
        for i, child in enumerate(value):
            yield from tensor_paths(child, f"{prefix}/{i}")
    elif hasattr(value, "untyped_storage"):
        yield prefix, value


def ordered_tensors(record, arm):
    if arm == "flow":
        for i, cell in enumerate(record["cells"]):
            for name in FIELDS:
                yield f"/cells/{i}/{name}", cell[name]
            for j, packet in enumerate(cell["pending"]):
                names = ("mass", "reset") if packet["kind"] == "atom" else ("alpha", "generator", "output", "reset")
                for name in names:
                    yield f"/cells/{i}/pending/{j}/{name}", packet[name]
        names = GLOBAL_FIELDS
    else:
        names = PHASE_FIELDS
    for name in names:
        for i, tensor in enumerate(record[name]):
            yield f"/{name}/{i}", tensor


def inspect_state(record, arm, steps, np, torch, expm):
    require(record["batch_size"] == 1 and record["past_autograd_retained"] is False, "state metadata")
    paths = list(ordered_tensors(record, arm))
    all_paths = list(tensor_paths(record))
    require({p for p, _ in paths} == {p for p, _ in all_paths}, "unaccounted tensor")
    require(len(paths) == len(all_paths), "duplicate tensor paths")
    arrays, inventory = {}, []
    for path, tensor in paths:
        require(type(tensor) is torch.Tensor and tensor.dtype == torch.float64
                and tensor.device.type == "cpu" and not tensor.requires_grad, "tensor type: " + path)
        array = tensor.numpy()
        require(np.isfinite(array).all(), "nonfinite state: " + path)
        arrays[path] = array
        inventory.append({"path": path, "shape": list(array.shape), "coordinates": array.size,
                          "bytes": array.nbytes, "sha256": hashlib.sha256(array.tobytes()).hexdigest()})
    rows, actions, packet_count, dimensions = [], 0, 0, []
    epoch = Fraction(steps, 20)
    common_law_hashes = set()

    def shape(path, wanted):
        require(arrays[path].shape == wanted, "shape: " + path)
        return arrays[path]

    if arm == "flow":
        check_keys(record, ("schema", "past_autograd_retained", "batch_size", "cells", *GLOBAL_FIELDS), "flow")
        require(record["schema"] == "hcsn-causal-network-state-v1" and len(record["cells"]) == 2, "flow schema")
        require(all(len(record[name]) == 2 for name in GLOBAL_FIELDS), "flow global layers")
        for i, cell in enumerate(record["cells"]):
            check_keys(cell, (*FIELDS, "time", "pending"), "cell")
            require(rational(cell["time"]) == epoch, "cell clock")
            prefix = f"/cells/{i}"
            active, upper = shape(prefix+"/active", (9, 4)), shape(prefix+"/upper", (9,))
            for name in FIELDS[2:]:
                shape(prefix+"/"+name, () if name == "discount_factor" else (9,))
            waiting = np.zeros(9)
            per_packet = []
            for j, packet in enumerate(cell["pending"]):
                packet_count += 1
                pp = prefix+f"/pending/{j}"
                reset = shape(pp+"/reset", (4,))
                if packet["kind"] == "atom":
                    check_keys(packet, ("kind", "time", "mass", "reset"), "atom")
                    mass = shape(pp+"/mass", (9,))
                    release = rational(packet["time"])
                    contribution = mass if release > epoch else np.zeros(9)
                else:
                    require(packet["kind"] == "flux", "packet kind")
                    check_keys(packet, ("kind", "start", "end", "alpha", "generator", "output", "reset"), "flux")
                    start, end = rational(packet["start"]), rational(packet["end"])
                    require(start < end, "flux interval")
                    generator = arrays[pp+"/generator"]
                    d = generator.shape[0]
                    shape(pp+"/generator", (d, d))
                    alpha, output = shape(pp+"/alpha", (9, d)), shape(pp+"/output", (d,))
                    dimensions.append(d)
                    # A pure integral of the already saved flux, with no state
                    # advancement, model object or producer matrix action.
                    lower = max(start, epoch)
                    contribution = np.zeros(9)
                    if lower < end:
                        augmented = np.zeros((d+1, d+1))
                        augmented[:d, :d], augmented[:d, d] = generator, output
                        integral = expm(augmented*float(end-start))[:d, d]
                        actions += 1
                        if lower > start:
                            integral = integral-expm(augmented*float(lower-start))[:d, d]
                            actions += 1
                        contribution = alpha @ integral
                    common_law_hashes.add(hashlib.sha256(generator[:5, :5].tobytes()
                                                         + output[:4].tobytes()+reset.tobytes()).hexdigest())
                require(np.isfinite(contribution).all(), "nonfinite waiting integral")
                waiting += contribution
                per_packet.append(contribution.tolist())
            initial = shape(f"/initial_totals/{i}", (9,))
            written = shape(f"/written/{i}", (1, 8))
            shape(f"/messages/{i}", (1, 9))
            residual = active.sum(axis=1)+upper+waiting-initial-np.r_[0., written.ravel()]
            rows.append({"active_total": active.sum(axis=1).tolist(), "upper": upper.tolist(),
                         "waiting_total": waiting.tolist(), "pending_contributions": per_packet,
                         "initial_total": initial.tolist(), "written": written.ravel().tolist(),
                         "residual": residual.tolist(), "probability_min_active_upper": float(min(active[0].min(), upper[0]))})
    else:
        metadata = ("schema", "past_autograd_retained", "active_nodes", "stages", "batch_size", "content_size",
                    "message_mode", "physics_tensor_bytes", "operator_tensor_bytes", "law_digests", "time", "sample_interval")
        check_keys(record, (*PHASE_FIELDS, *metadata), "phase")
        require(record["schema"] == "hcsn-erlang-forward-state-v1" and record["active_nodes"] == 4
                and record["stages"] == 4 and record["content_size"] == 8 and record["message_mode"] == "full", "phase schema")
        require(rational(record["time"]) == epoch and rational(record["sample_interval"]) == Fraction(1, 20), "phase clocks")
        require(all(len(record[name]) == 2 for name in PHASE_FIELDS) and len(record["law_digests"]) == 2, "phase layers")
        require(record["physics_tensor_bytes"] == 560 and record["operator_tensor_bytes"] == 3168, "phase external bytes")
        common_law_hashes.update(record["law_digests"])
        for i in range(2):
            for name in PHASE_FIELDS:
                wanted = {"density": (9, 9), "discount_factor": (), "messages": (1, 9), "written": (1, 8)}.get(name, (9,))
                shape(f"/{name}/{i}", wanted)
            density, initial, written = arrays[f"/density/{i}"], arrays[f"/initial_totals/{i}"], arrays[f"/written/{i}"]
            residual = density.sum(axis=1)-initial-np.r_[0., written.ravel()]
            rows.append({"active_total": density[:, :4].sum(axis=1).tolist(),
                         "waiting_total": density[:, 4:8].sum(axis=1).tolist(), "upper": density[:, 8].tolist(),
                         "initial_total": initial.tolist(), "written": written.ravel().tolist(),
                         "residual": residual.tolist(), "probability_min_complete_density": float(density[0].min())})
    return {"inventory": inventory, "tensor_count": len(paths), "tensor_coordinates": sum(a.size for a in arrays.values()),
            "tensor_bytes": sum(a.nbytes for a in arrays.values()), "balance": rows,
            "balance_max_abs": max(abs(v) for row in rows for v in row["residual"]),
            "new_reference_matrix_integral_actions": actions, "pending_packets": packet_count,
            "pending_generator_dimensions": dimensions, "encoded_law_hashes": sorted(common_law_hashes)}, arrays


def difference(reference, approximation, np):
    delta = approximation-reference
    absolute, ref_inf = float(np.abs(delta).max()), float(np.abs(reference).max())
    l2, ref_l2 = float(np.linalg.norm(delta.ravel())), float(np.linalg.norm(reference.ravel()))
    return {"coordinates_not_independent_samples": reference.size, "max_abs": absolute,
            "mean_abs": float(np.abs(delta).mean()), "rmse": float(np.sqrt(np.mean(delta*delta))), "l2_abs": l2,
            "flow_linf_denominator": ref_inf, "flow_l2_denominator": ref_l2,
            "relative_linf": absolute/ref_inf if ref_inf else None,
            "relative_l2": l2/ref_l2 if ref_l2 else None,
            "zero_denominator_returns_null": True}


def worker(args):
    import numpy as np
    import scipy
    from scipy.linalg import expm
    import torch

    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    started, cpu = time.perf_counter(), time.process_time()
    raw, repo, out = Path(args.raw), Path(args.repo), Path(args.output)
    frozen = json.loads(Path(args.freeze).read_text())
    require(sha(Path(__file__)) == frozen["reader_sha256"], "reader source changed")
    require(sorted(os.sched_getaffinity(0)) == [8] and all(os.environ.get(k) == "1" for k in THREAD_ENV), "reader resources")
    protocol_path = repo/"qualification/hcsn_network/PROTOCOL.json"
    require(sha(protocol_path) == PROTOCOL_SHA, "protocol hash")
    protocol = json.loads(protocol_path.read_text())
    require(frozen["protocol_sha256"] == PROTOCOL_SHA and frozen["source_commit"] == SOURCE_COMMIT, "freeze identity")
    for relative, entry in frozen["inputs"].items():
        p = raw/relative
        require(p.stat().st_size == entry["bytes"] and sha(p) == entry["sha256"], "input changed: " + relative)
    for relative, wanted in protocol["sources"].items():
        require(sha(repo/relative) == wanted, "source changed: " + relative)
    request = json.loads((raw/"REQUEST.json").read_text())
    require(request["source_commit"] == SOURCE_COMMIT and request["protocol_sha256"] == PROTOCOL_SHA
            and request["profile"] == protocol["numerical_profile"], "raw request")
    complete = json.loads((raw/"COMPLETE.json").read_text())
    require(complete["children"] == 8 and complete["failures"] == 0, "profile completion")
    aggregate_costs = json.loads((raw/"COSTS.json").read_text())
    costs = {row["directory"]: {k: v for k, v in row.items() if k != "directory"} for row in aggregate_costs}
    expected_cases = {f"{arm}-T{steps}" for steps in LENGTHS for arm in ARMS}
    require(set(costs) == expected_cases and len(aggregate_costs) == 8, "cost roster")
    require({p.name for p in (raw/"outputs").iterdir()} == expected_cases, "output roster")
    cases, gradients, table, plot_rows = {}, {}, [], []
    for steps in LENGTHS:
        for arm in ARMS:
            name = f"{arm}-T{steps}"
            directory, process = raw/"outputs"/name, raw/"processes"/name
            result = json.loads((directory/"RESULT.json").read_text())
            cost = json.loads((process/"COST.json").read_text())
            require(cost == costs[name] and cost["exit_code"] == 0 and not cost["deadline_kill_sent"], "cost/completion: "+name)
            require(json.loads((process/"process/stdout").read_text()) == result, "stdout/result: "+name)
            require((process/"process/stdout").stat().st_size == cost["stdout_bytes"], "stdout bytes: "+name)
            require((process/"process/stderr").stat().st_size == cost["stderr_bytes"] == 0, "stderr: "+name)
            command = json.loads((process/"process/REQUEST.json").read_text())
            require(command["cpu"] == 2 and cost["cpu_affinity"] == [2] and command["address_space_bytes"] == 2**32
                    and command["wall_deadline_seconds"] == 120, "profile resources: "+name)
            require(command["command"] == [sys.executable, "-m", "qualification.hcsn_network.profile_dynamics",
                    "--arm", arm, "--steps", str(steps), "--protocol", str(protocol_path), "--output", str(directory)],
                    "profile command: "+name)
            require(result["arm"] == arm and result["steps"] == steps and result["horizon"] == steps/20
                    and (result["batch"], result["content_channels"], result["layers"], result["spatial_nodes"]) == (1, 8, 2, 4)
                    and result["optimizer_calls"] == 0, "case metadata: "+name)
            record = torch.load(directory/"state.pt", map_location="cpu", weights_only=True)
            state, state_arrays = inspect_state(record, arm, steps, np, torch, expm)
            with np.load(directory/"RAW.npz", allow_pickle=False) as data:
                keys = {f"state_{i:03}" for i in range(state["tensor_count"])} | {"logits", "parameter_gradient", "input_gradient"}
                require(set(data.files) == keys and len(data.files) == len(keys), "RAW keys: "+name)
                for i, inventory in enumerate(state["inventory"]):
                    a, b = data[f"state_{i:03}"], state_arrays[inventory["path"]]
                    require(a.dtype == b.dtype and a.shape == b.shape and a.tobytes() == b.tobytes(), "state bitwise: "+name)
                gradients[name] = {key: data[key].copy() for key in ("logits", "parameter_gradient", "input_gradient")}
            for key, wanted in (("logits", (1, 10)), ("parameter_gradient", (259,)), ("input_gradient", (1, steps, 2))):
                a = gradients[name][key]
                require(a.shape == wanted and a.dtype == np.float64 and np.isfinite(a).all(), "observable shape/finite: "+name+key)
            with zipfile.ZipFile(directory/"state.pt") as archive:
                storage_bytes = sum(z.file_size for z in archive.infolist() if "/data/" in z.filename)
            require(state["tensor_bytes"] == result["logical_state_bytes"] == storage_bytes, "payload bytes: "+name)
            require((directory/"state.pt").stat().st_size == result["serialized_state_bytes"], "serialized bytes: "+name)
            require(result["physics_tensor_bytes"] == 560
                    and result["transition_view_bytes"] == (3168 if arm == "flow_erlang4" else None), "physics/operator bytes: "+name)
            state.update({"result": result, "full_process_cost": cost, "tensor_payload_matches_RAW_bitwise": True,
                          "serialized_storage_payload_bytes": storage_bytes,
                          "reported_balance_difference": state["balance_max_abs"]-result["balance_max_abs"],
                          "independent_balance_within_original_gate": state["balance_max_abs"] <= 2e-9})
            cases[name] = state
            table.append({"case": name, "steps": steps, "horizon": steps/20, "logical_state_bytes": state["tensor_bytes"],
                          "serialized_state_bytes": result["serialized_state_bytes"],
                          "autograd_saved_payload_bytes_with_repeats": result["autograd_saved_payload_bytes_with_repeats"],
                          "profile_full_process_wall_seconds": cost["wall_seconds"], "profile_full_process_cpu_seconds": cost["cpu_seconds"],
                          "profile_full_process_peak_rss_kib": cost["maxrss_kib"],
                          "forward_including_conservation_wall_seconds": result["forward_and_conservation_wall_seconds"],
                          "backward_wall_seconds": result["backward_wall_seconds"], "independent_balance_max_abs": state["balance_max_abs"]})
    comparisons = {}
    for steps in LENGTHS:
        ref, approx = gradients[f"flow-T{steps}"], gradients[f"flow_erlang4-T{steps}"]
        comparisons[str(steps)] = {key: difference(ref[key], approx[key], np) for key in ref}
        for key, row in comparisons[str(steps)].items():
            plot_rows.append({"steps": steps, "observable": key, **row})
    for relative, entry in frozen["inputs"].items():
        require(sha(raw/relative) == entry["sha256"], "input changed during reading: "+relative)
    for relative, wanted in protocol["sources"].items():
        require(sha(repo/relative) == wanted, "source changed during reading: "+relative)
    report = {"schema": "hcsn-network-length-independent-read-v1", "reader_freeze": frozen,
              "status": "PASS" if all(c["independent_balance_within_original_gate"] for c in cases.values()) else "FAIL",
              "status_scope": "artifact completeness, tensor/shape/byte custody and finite-grid balance only; no approximation accuracy gate",
              "profile_source_commit": SOURCE_COMMIT, "protocol_sha256": PROTOCOL_SHA,
              "runtime": {"numpy": np.__version__, "scipy": scipy.__version__, "torch": torch.__version__},
              "cases": cases, "comparisons_erlang_minus_flow": comparisons,
              "normalization": {"relative_linf": "max(abs(Erlang-flow))/max(abs(flow))",
                                "relative_l2": "norm(Erlang-flow,2)/norm(flow,2)", "floor": None},
              "same_weight_evidence": {"model_seed": 101, "input_seed": 123,
                  "source_reasoning": "Both arms run the same FlowClassifier constructor and float64 conversion after torch.manual_seed(101); the arm branch changes forward dynamics, not initialization. Inputs come from a distinct generator seeded 123 and slice the same generated [1,80,2] prefix. No optimizer calls occur.",
                  "saved_parameter_values_or_hash": False, "saved_input_values_or_hash": False,
                  "direct_bitwise_same_weights_or_inputs_verified": False,
                  "conclusion": "Matched initialization and input-prefix provenance is supported by frozen source plus successful process records; original parameter/input bytes were not retained, so direct artifact equality cannot be established."},
              "limitations": ["One model seed and one synthetic input sequence; coordinate/tensor counts are not independent samples.",
                  "Erlang4 changes the waiting-time law; these differences are model-approximation deviations, not floating-point solver error.",
                  "T10/T20/T40/T80 are longer prefixes at fixed dt=1/20, not a time-refinement or continuum study.",
                  "state.pt contains complete dynamic forward state only, not model weights, supplied physics, optimizer, or the past AD graph.",
                  "Saved-tensor payload counts hook traffic with repeats; it is not peak live tensor allocation or peak process memory.",
                  "Physics/operator view bytes and logical state payload count views/repeats, not unique allocated storage in the executed model.",
                  "Profile body forward includes conservation reads; its exact_forward_exponentials counter is captured before separate balance integrals, so excludes those actions.",
                  "Profile full-process costs include imports/checks/serialization; no repeated timings or speedup significance are inferred."],
              "model_forward_calls": 0, "model_backward_calls": 0, "optimizer_calls": 0, "new_trajectories": 0,
              "new_reference_matrix_integral_actions": sum(c["new_reference_matrix_integral_actions"] for c in cases.values()),
              "all_closed": False}
    report["reader_body_cost"] = {"wall_seconds": time.perf_counter()-started, "cpu_seconds": time.process_time()-cpu,
        "scope": "After NumPy/SciPy/Torch imports and thread setup, through source/input checks and all tensor/numerical reading; excludes result/CSV writing. Full process measured by parent wait4 in COST.json."}
    write_json(out/"REVIEW.json", report)
    for filename, rows in (("state_and_cost.csv", table), ("approximation_differences.csv", plot_rows)):
        with (out/filename).open("x", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print(json.dumps({"status": report["status"], "cases": len(cases),
                      "new_reference_matrix_integral_actions": report["new_reference_matrix_integral_actions"],
                      "body_cost": report["reader_body_cost"]}), flush=True)
    return 0 if report["status"] == "PASS" else 1


def main():
    parser = argparse.ArgumentParser()
    for name in ("raw", "repo", "freeze", "output"):
        parser.add_argument("--"+name, required=True)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    if args.worker:
        try:
            return worker(args)
        except Exception:
            traceback.print_exc()
            return 1
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    frozen = json.loads(Path(args.freeze).read_text())
    require(sha(Path(__file__)) == frozen["reader_sha256"], "reader differs from pre-execution freeze")
    command = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--worker"]
    write_json(out/"REQUEST.json", {"command": command, "reader_sha256": frozen["reader_sha256"],
        "cpu_affinity": [8], "numerical_threads": 1, "address_space_bytes": 2**32,
        "cpu_soft_hard_seconds": [60, 65], "wall_deadline_seconds": 90,
        "identity": "hcsn-network-length-independent-read-20261119-d741-attempt001"})
    started = time.perf_counter()
    pid = os.fork()
    if pid == 0:
        try:
            os.sched_setaffinity(0, {8})
            resource.setrlimit(resource.RLIMIT_AS, (2**32, 2**32))
            resource.setrlimit(resource.RLIMIT_CPU, (60, 65))
            for filename, fd in (("stdout", 1), ("stderr", 2)):
                handle = os.open(out/filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
                os.dup2(handle, fd)
                os.close(handle)
            env = os.environ.copy()
            env.update({name: "1" for name in THREAD_ENV})
            os.execve(sys.executable, command, env)
        except Exception:
            traceback.print_exc()
            os._exit(1)
    killed = False
    while True:
        observed, status, usage = os.wait4(pid, os.WNOHANG)
        if observed:
            break
        if time.perf_counter()-started > 90 and not killed:
            os.kill(pid, signal.SIGKILL)
            killed = True
        time.sleep(.02)
    code = os.waitstatus_to_exitcode(status)
    write_json(out/"COST.json", {"exit_code": code, "wall_seconds": time.perf_counter()-started,
        "cpu_user_seconds": usage.ru_utime, "cpu_system_seconds": usage.ru_stime,
        "cpu_seconds": usage.ru_utime+usage.ru_stime, "maxrss_kib": usage.ru_maxrss,
        "deadline_kill_sent": killed, "cpu_affinity": [8],
        "scope": "Fresh reader subprocess from immediately before fork to wait4 return, including interpreter startup, numerical imports, artifact checks, independent matrix integrals, result/CSV writes and shutdown; RSS is full-process Linux ru_maxrss, not tensor allocator."})
    print((out/"stdout").read_text(), end="")
    if code:
        print((out/"stderr").read_text(), file=sys.stderr, end="")
    return code if code >= 0 else 128-code


if __name__ == "__main__":
    raise SystemExit(main())
