"""One prospective readout realization; inert without separate root admission.

This file was prepared statically. It never invokes an old sensitivity gate,
computes a new parameter solve, exports a model, or treats a prior gate as passed.
"""
import argparse
import copy
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import signal
import stat
import sys
import time
import types

SCOPE = "v7-frozen-readout-two-archived-parent-observations-01"
ROOT = "/home/alex/pft-continuation-20261126-8a32"
CLAIM = ROOT + "/v7/readout_physical_01.CLAIM.json"
OUTPUT = ROOT + "/v7/readout_physical_execution_01"
PARENT = "0127a056c779930fc5ab27558e84aecbd242caa64951f21e47d7885465f0b86f"
STATE = "136026bde0867265b040f679e60fb991b131b6d8403127fa7b2a94237da5f907"
PROFILE = "4a8feafa490224f0ad14d318835f51d1147b8b6b93c7a56e9f9eb3ddc3d43d77"
BINDING = "3146e2c56757ff7c818670aa3a9c229b26271c7336d573b1692b91ac8e7a00e9"
REQUEST = "e6c8e04059737337d8cdde5db97d1358b2b3fcce908a1d5d7488fd309cddf07c"
PROPOSAL = "c3f8e003b73bdcf4d18e2101354313e4598771c505396af31ef437495deec3a7"
TASK = "295be5f5733e4ea076a1e46221ee52c2663c96dbfd15727d4bdb3ac4ffae921e"
MODEL_SOURCE = "aabc7a29ebfdaed592ebd4a16d7e4db927a6a88cb7247d4b334fd7299eab8576"
DELTAS = ["0x1.55e4446392bd2p-9", "-0x1.c6b313f74251bp-8"]
COORDINATES = [{"name": "readout.weight", "flat_index": 0, "shape": [2, 20]},
               {"name": "readout.bias", "flat_index": 0, "shape": [2]}]
BUDGET = {"model_load_attempts": 1, "parameter_edit_applications": 1,
          "candidate_forward_attempts": 1, "fresh_initial_states": 1,
          "parent_forward_calls": 0, "AD_calls": 0, "new_parameter_inverse_solves": 0,
          "optimizer_updates": 0, "candidate_exports": 0, "retries": 0,
          "old_gate_replays": 0, "wall_seconds": 55}
POPULATION_FIELDS = ("density", "boundary", "drift", "cost", "message")
CAP = 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON field")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError("nonfinite JSON literal: " + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


def read(path, expected=None, cap=CAP):
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= cap, "file size/type")
        raw = stream.read(cap + 1)
        after = os.fstat(stream.fileno())
    stamp = lambda x: (x.st_dev, x.st_ino, x.st_size, x.st_mtime_ns, x.st_ctime_ns)
    require(stamp(before) == stamp(after) and len(raw) == before.st_size, "file changed during read")
    require(expected is None or sha(raw) == expected, "file hash differs: " + str(path))
    return raw


def write_new(path, value):
    raw = canonical(value) + b"\n"
    require(len(raw) <= CAP, "record size bound")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    fsync_directory(Path(path).parent)
    require(read(path) == raw, "record readback differs")


def fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def timeout_handler(_signal, _frame):
    raise TimeoutError("prospective 55-second probe wall limit")


def preflight(args, protocol, frozen):
    def capture(path, expected, cap=CAP):
        raw = read(path, expected, cap)
        frozen[str(path)] = {"sha256": sha(raw), "bytes": len(raw)}
        return raw

    request = parse(capture(args.request, REQUEST))
    proposal = parse(capture(args.proposal, PROPOSAL))
    task = parse(capture(args.archived_input, TASK))
    require(proposal["request_sha256"] == REQUEST and proposal["binding"] == request["binding"]
            and proposal["coordinates"] == request["coordinates"] == COORDINATES
            and proposal["delta_binary64_hex"] == DELTAS, "frozen proposal binding")
    binding = request["binding"]
    require(binding["reference_candidate_sha256"] == PARENT
            and binding["reference_state_sha256"] == STATE
            and binding["source_binding_sha256"] == BINDING
            and binding["model_source_sha256"] == MODEL_SOURCE, "original parent/source required")
    require(request["observation"] == "final_logit_1_minus_logit_0"
            and [row["row_id"] for row in request["rows"]] == ["ai395", "pocket4"], "fixed observations")
    require(task["candidate_sha256"] == protocol["archived_input_identity"]["candidate_sha256"]
            and task["profile_sha256"] == protocol["archived_input_identity"]["profile_sha256"]
            and task["task_id"] == "actual-peer-aggregate-cold-only"
            and task["initial"] == {"kind": "margin", "margin": [0.59, 0.73]}, "old task source identity")
    manifest = parse(capture(ROOT + "/v4/PROFILE.json", PROFILE))
    require(manifest["checkpoint"]["sha256"] == PARENT and manifest["checkpoint"]["bytes"] == 9605
            and manifest["format"] == "actual_p2p_v2_full", "original checkpoint authority")
    materials = Path("/home/alex")
    checkpoint = manifest["checkpoint"]
    capture(materials / checkpoint["path"], PARENT, 32 * CAP)
    provenance = parse(capture(materials / manifest["capsule"]["provenance"]["path"],
                               manifest["capsule"]["provenance"]["sha256"]))
    physical = provenance["research_source_hashes"]
    require(1 <= len(physical) <= 64
            and physical["qualification/hcsn_smallnet_20261124/model.py"] == MODEL_SOURCE,
            "complete original model source closure")
    for name, expected in physical.items():
        parts = PurePosixPath(name)
        require(not parts.is_absolute() and parts.as_posix() == name
                and ".." not in parts.parts, "physical source path")
        capture(materials / manifest["capsule"]["root"] / "src" / name, expected)
    sources = {}
    for pin in protocol["current_source_pins"]:
        sources[pin["name"]] = (pin["path"], capture(pin["path"], pin["sha256"]))
    return request, proposal, task, sources


def import_loader(sources):
    require(not any(name in sys.modules for name in
                    ("torch", "numpy", "common", "optimized", "profile_io", "source_binding", "small_hcsn_profile")),
            "fresh process required")
    for name in ("profile_io", "source_binding", "small_hcsn_profile"):
        path, raw = sources["native_profile_v4/" + name + ".py"]
        module = types.ModuleType(name)
        module.__file__ = path
        sys.modules[name] = module
        exec(compile(raw, path, "exec"), module.__dict__)
    return sys.modules["small_hcsn_profile"]


def array_digest(tensor):
    # Same byte convention as first_order._array_digest; no old gate import.
    array = tensor.detach().cpu().numpy().astype("<f8", copy=False)
    return sha(str((array.dtype.str, array.shape)).encode() + array.tobytes(order="C"))


def inputs(torch, model, task):
    # Reviewed identical _inputs conversion, with stricter fixed scope shapes.
    reference = model.input_drive.weight
    require(reference.dtype == torch.float64 and reference.device.type == "cpu", "CPU FP64 model")
    x = torch.as_tensor(task["x"], dtype=reference.dtype, device=reference.device)
    margin = torch.as_tensor(task["initial"]["margin"], dtype=reference.dtype, device=reference.device)
    if margin.ndim == 1:
        margin = margin[:, None]
    require(tuple(x.shape) == (4, 2, 6) and tuple(margin.shape) == (2, 1)
            and not x.requires_grad and not margin.requires_grad
            and bool(torch.isfinite(x).all() and torch.isfinite(margin).all()), "fixed finite inputs")
    return x, margin


def changed_elements(torch, before, after):
    require(set(before) == set(after), "state tensor roster changed")
    changed = []
    for name, old in before.items():
        new = after[name]
        require(old.shape == new.shape and old.dtype == new.dtype and old.device == new.device
                and bool(torch.isfinite(new).all()), "state tensor contract changed: " + name)
        a = old.contiguous().reshape(-1).view(torch.uint8).reshape(old.numel(), old.element_size())
        b = new.detach().contiguous().reshape(-1).view(torch.uint8).reshape(new.numel(), new.element_size())
        for index in (a != b).any(dim=1).nonzero(as_tuple=False).flatten().tolist():
            changed.append({"name": name, "flat_index": index})
    return sorted(changed, key=lambda item: (item["name"], item["flat_index"]))


def physical(api, loaded, request, task, protocol, result):
    torch, model, counts = loaded.torch, loaded.model, result["counts"]
    loaded.require_frozen()
    require(loaded.candidate_sha256 == PARENT and loaded.model_state_sha256 == STATE
            and loaded.profile_sha256 == PROFILE and loaded.source_binding_sha256 == BINDING
            and loaded.constructor == "plain_linear" and loaded.config == protocol["model_config"],
            "loaded parent, config or source differs")
    parameters = dict(model.named_parameters())
    require(sum(p.numel() for p in parameters.values()) == 306
            and sum(p.numel() for p in parameters.values() if p.requires_grad) == 298
            and all(p.grad is None for p in parameters.values()), "fresh parent parameter contract")
    before = {name: value.detach().clone() for name, value in model.state_dict().items()}
    flags = {name: p.requires_grad for name, p in parameters.items()}
    modes = {name: module.training for name, module in model.named_modules()}
    config = model.config
    diagnostics = copy.deepcopy(model.last_diagnostics)
    edited = None
    body = {name: value for name, value in before.items() if name not in ("readout.weight", "readout.bias")}
    result.update(parent_state_sha256=api.tensor_state_sha256(before),
                  frozen_body_and_buffers_sha256=api.tensor_state_sha256(body))
    require(result["parent_state_sha256"] == STATE, "complete parent state guard")
    try:
        with torch.no_grad():
            planned = []
            for coordinate, delta in zip(COORDINATES, DELTAS):
                parameter = parameters[coordinate["name"]]
                require(list(parameter.shape) == coordinate["shape"] and parameter.dtype == torch.float64,
                        "readout coordinate shape/dtype")
                value = parameter.detach().reshape(-1)[0].clone()
                value.add_(float.fromhex(delta))
                require(bool(torch.isfinite(value)), "nonfinite proposed parameter addition")
                planned.append(value)
            counts["parameter_edit_applications"] += 1
            write_new(Path(OUTPUT) / "EDIT_ATTEMPT.json", {"scope": SCOPE, "counts": counts,
                      "parent_state_sha256": STATE, "coordinates": COORDINATES, "delta_binary64_hex": DELTAS,
                      "planned_parameter_hex": [float(value).hex() for value in planned]})
            for coordinate, value in zip(COORDINATES, planned):
                counts["parameter_coordinate_writes"] += 1
                parameters[coordinate["name"]].reshape(-1)[0].copy_(value)
            current = model.state_dict()
            changed = changed_elements(torch, before, current)
            expected = sorted(({"name": c["name"], "flat_index": 0} for c in COORDINATES),
                              key=lambda item: item["name"])
            require(changed == expected, "exactly the two declared parameter elements must change")
            edited = api.tensor_state_sha256(current)
            result.update(edited_state_sha256=edited, changed_elements=changed, all_other_elements_unchanged=True,
                          coordinate_values=[{"name": c["name"], "before_hex": float(before[c["name"]].reshape(-1)[0]).hex(),
                            "after_hex": float(v).hex(), "requested_delta_hex": d,
                            "effective_delta_hex": (float(v) - float(before[c["name"]].reshape(-1)[0])).hex()}
                            for c, v, d in zip(COORDINATES, planned, DELTAS)])
            x, margin = inputs(torch, model, task)
            require(array_digest(x) == request["binding"]["input_sha256"]
                    and array_digest(margin) == request["binding"]["initial_margin_sha256"], "fixed input array hashes")
            envelope = {"schema": "hepta.frozen-readout.physical-input.v1", "scope": SCOPE,
                        "parent_checkpoint_sha256": PARENT, "edited_memory_state_sha256": edited,
                        "request_sha256": REQUEST, "proposal_sha256": PROPOSAL,
                        "archived_payload_source_sha256": TASK, "input_sha256": array_digest(x),
                        "initial_margin_sha256": array_digest(margin), "shape": [4, 2, 6],
                        "row_ids": [row["row_id"] for row in request["rows"]]}
            result.update(input_binding=envelope, input_binding_sha256=sha(canonical(envelope)))
            counts["fresh_initial_states"] += 1
            initial = model.initial_state(2, margin)
            loaded.check_population(initial)
            require(initial.step == 0, "fresh clock zero required")
            result["initial_population_tensor_sha256"] = api.tensor_state_sha256(
                {key: getattr(initial, key) for key in POPULATION_FIELDS})
            require(api.tensor_state_sha256(model.state_dict()) == edited, "state changed before forward")
            counts["candidate_forward_attempts"] += 1
            write_new(Path(OUTPUT) / "FORWARD_ATTEMPT.json", {"scope": SCOPE, "counts": counts,
                      "edited_state_sha256": edited, "input_binding_sha256": result["input_binding_sha256"],
                      "initial_population_tensor_sha256": result["initial_population_tensor_sha256"]})
            logits, features, final = model(x, state=initial, return_features=True)
            counts["candidate_forward_completions"] += 1
            loaded.check_population(final)
            require(tuple(logits.shape) == (4, 2, 2) and tuple(features.shape) == (4, 2, 20)
                    and final.step == 4 and not logits.requires_grad and not features.requires_grad,
                    "physical output shape, clock or autograd contract")
            margins = logits[-1, :, 1] - logits[-1, :, 0]
            result["observed_margin_hex"] = [float(value).hex() for value in margins]
            result["observed_feature0_hex"] = [float(value).hex() for value in features[-1, :, 0]]
            require(bool(torch.isfinite(logits).all() and torch.isfinite(features).all()
                         and torch.isfinite(margins).all()), "nonfinite physical output")
            rows = []
            for i, row in enumerate(request["rows"]):
                actual, feature = float(margins[i]), float(features[-1, i, 0])
                target, retained = float.fromhex(row["target_margin_hex"]), float.fromhex(row["feature0_hex"])
                require(math.isfinite(target) and math.isfinite(retained), "nonfinite frozen observation")
                rows.append({**row, "actual_margin": actual, "actual_margin_hex": actual.hex(),
                             "endpoint_residual": actual - target, "endpoint_abs_error": abs(actual - target),
                             "actual_feature0": feature, "feature_abs_error": abs(feature - retained)})
            result.update(rows=rows, max_abs_endpoint_error=max(row["endpoint_abs_error"] for row in rows),
                          max_abs_feature_error=max(row["feature_abs_error"] for row in rows),
                          final_population_tensor_sha256=api.tensor_state_sha256(
                              {key: getattr(final, key) for key in POPULATION_FIELDS}),
                          physical_diagnostics=copy.deepcopy(model.last_diagnostics))
            require(api.tensor_state_sha256(model.state_dict()) == edited
                    and asdict(model.config) == protocol["model_config"]
                    and array_digest(x) == envelope["input_sha256"]
                    and array_digest(margin) == envelope["initial_margin_sha256"], "physical call mutated frozen state/inputs")
            result["edited_state_unchanged_by_forward"] = True
            result["status"] = ("PASSED_FIXED_ENDPOINT_REALIZATION" if result["max_abs_endpoint_error"] <= 1e-9
                                and result["max_abs_feature_error"] <= 1e-12 else "REJECTED_FIXED_TOLERANCE")
    except Exception as error:
        result["physical_exception"] = {"type": type(error).__name__, "message": str(error)[:4096]}
        raise
    finally:
        invariants_ok = False
        try:
            checks = {"edited_tensors_unchanged": edited is None or api.tensor_state_sha256(model.state_dict()) == edited,
                      "config_unchanged": model.config == config,
                      "trainability_unchanged": {name: p.requires_grad for name, p in model.named_parameters()} == flags,
                      "module_modes_unchanged": {name: module.training for name, module in model.named_modules()} == modes,
                      "gradients_unchanged": all(p.grad is None for p in parameters.values()),
                      "parameter_objects_unchanged": all(dict(model.named_parameters()).get(name) is p
                                                         for name, p in parameters.items())}
            result["pre_restoration_invariants"] = checks
            invariants_ok = all(checks.values())
        except Exception as error:
            result["pre_restoration_error"] = str(error)[:4096]
        finally:
            # Memory rollback only: no checkpoint load, candidate construction,
            # model call or export. Retain every pre-rollback failure in result.
            with torch.no_grad():
                current = model.state_dict()
                require(set(current) == set(before), "cannot restore a changed tensor roster")
                for name, value in current.items():
                    value.copy_(before[name])
                for name, parameter in model.named_parameters():
                    parameter.requires_grad_(flags[name])
                    parameter.grad = None
            for name, module in model.named_modules():
                module.training = modes[name]
            model.config = config
            model.last_diagnostics = diagnostics
        loaded.require_frozen()
        require(all(dict(model.named_parameters()).get(name) is p for name, p in parameters.items())
                and {name: module.training for name, module in model.named_modules()} == modes,
                "parent parameter objects or module modes not restored")
        result["restored_parent_state_sha256"] = api.tensor_state_sha256(model.state_dict())
        require(result["restored_parent_state_sha256"] == STATE, "parent memory restoration differs")
        result["parent_memory_restored"] = True
        if not invariants_ok:
            result["status"] = "FAILED_FROZEN_INVARIANT_BEFORE_RESTORATION"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("protocol", "protocol-sha256", "admission", "admission-sha256", "request", "proposal", "archived-input"):
        parser.add_argument("--" + flag, required=True)
    args = parser.parse_args()
    protocol_raw, admission_raw = read(args.protocol, args.protocol_sha256), read(args.admission, args.admission_sha256)
    protocol, admission = parse(protocol_raw), parse(admission_raw)
    source_sha = sha(read(__file__))
    require(protocol["schema"] == "hepta.frozen-readout.physical-probe-protocol.v1"
            and protocol["status"] == "INACTIVE_WITHOUT_SEPARATE_ROOT_ADMISSION" and protocol["scope"] == SCOPE
            and protocol["claim_path"] == CLAIM and protocol["output_directory"] == OUTPUT
            and protocol["proposed_budget"] == BUDGET
            and protocol["endpoint_absolute_tolerance"] == 1e-9
            and protocol["feature_absolute_tolerance"] == 1e-12
            and protocol["relative_tolerance"] == 0, "fixed inactive protocol contract")
    require(admission["schema"] == "hepta.frozen-readout.physical-probe-root-admission.v1"
            and admission["status"] == "ROOT_ADMITTED" and admission["admitted_by"] == "root"
            and admission["scope"] == SCOPE and admission["protocol_sha256"] == args.protocol_sha256
            and admission["probe_source_sha256"] == source_sha and admission["registered_budget"] == BUDGET,
            "separate matching root admission required")
    counts = {key: 0 for key in BUDGET if key != "wall_seconds"}
    counts.update(model_load_completions=0, candidate_forward_completions=0, parameter_coordinate_writes=0)
    result = {"schema": "hepta.frozen-readout.physical-probe-result.v1", "scope": SCOPE,
              "status": "INCOMPLETE", "protocol_sha256": args.protocol_sha256,
              "root_admission_sha256": args.admission_sha256, "probe_source_sha256": source_sha,
              "counts": counts, "candidate_exported": False, "production_adoption": False,
              "old_gate_replayed_or_repaired": False, "new_independent_task_evidence": False,
              "model_internal_operations": protocol["model_internal_operations"]}
    # One fixed durable claim across output paths/CLI invocations; never removed.
    write_new(CLAIM, {**result, "status": "ATTEMPT_CLAIMED_BEFORE_IMPORT"})
    start = time.monotonic()
    frozen = {str(Path(__file__)): {"sha256": source_sha, "bytes": len(read(__file__))},
              args.protocol: {"sha256": args.protocol_sha256, "bytes": len(protocol_raw)},
              args.admission: {"sha256": args.admission_sha256, "bytes": len(admission_raw)}}
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(BUDGET["wall_seconds"])
    try:
        Path(OUTPUT).mkdir(mode=0o700, exist_ok=False)
        fsync_directory(Path(OUTPUT).parent)
        require(sys.dont_write_bytecode and sys.flags.isolated == 1
                and platform.python_version() == protocol["runtime"]["python"]
                and sys.executable == protocol["interpreter"], "pinned -B interpreter required")
        for name, value in protocol["environment"].items():
            require(os.environ.get(name) == value, "pinned environment differs: " + name)
        request, _proposal, task, sources = preflight(args, protocol, frozen)
        api = import_loader(sources)
        counts["model_load_attempts"] += 1
        write_new(Path(OUTPUT) / "LOAD_ATTEMPT.json", {"scope": SCOPE, "counts": counts,
                  "profile_sha256": PROFILE, "parent_checkpoint_sha256": PARENT,
                  "protocol_sha256": args.protocol_sha256, "root_admission_sha256": args.admission_sha256})
        loaded = api.load_profile(ROOT + "/v4/PROFILE.json", PROFILE, "/home/alex")
        counts["model_load_completions"] += 1
        runtime = {"python": platform.python_version(), "numpy": sys.modules["numpy"].__version__,
                   "torch": str(loaded.torch.__version__), "device": "cpu",
                   "threads": loaded.torch.get_num_threads(), "interop_threads": loaded.torch.get_num_interop_threads()}
        require(runtime == protocol["runtime"], "actual runtime differs")
        result["runtime"] = runtime
        physical(api, loaded, request, task, protocol, result)
        require(loaded.torch.get_num_threads() == 1 and loaded.torch.get_num_interop_threads() == 1,
                "runtime thread settings changed")
    except Exception as error:
        result.update(status="FAILED_EXCEPTION", exception_type=type(error).__name__, exception=str(error)[:4096])
    finally:
        signal.alarm(0)
        try:
            for path, pin in frozen.items():
                require(len(read(path, pin["sha256"], max(CAP, pin["bytes"]))) == pin["bytes"], "retained byte count differs")
            result["all_retained_sources_inputs_checkpoint_unchanged"] = True
        except Exception as error:
            result.update(status="FAILED_RETAINED_IDENTITY", retained_identity_error=str(error)[:4096])
        result.update(retained_file_pins=frozen, wall_seconds=time.monotonic() - start)
        # If killed before this seal, the durable claim means INCOMPLETE, never retry.
        write_new(Path(OUTPUT) / "RESULT.json", result)
    return 0 if result["status"] == "PASSED_FIXED_ENDPOINT_REALIZATION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
