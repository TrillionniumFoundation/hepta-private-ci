"""One inactive-by-default, fixed-stencil check of an already accepted parent.

This entry point neither retries the original parent nor solves/exports a step.
The pinned V4 fixture, AD implementation and FD gate are reused unchanged.
"""
import argparse
import copy
from dataclasses import asdict
import hashlib
import importlib
import json
import math
from pathlib import Path
import resource
import signal
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parent.parent
ENTRY = "sensitivity_v5/verify_accepted_point.py"
SOURCES = {
    "native_profile_v4/profile_io.py": "3c6d4d0d6ad478460e3b422bfb22220406080c48a5ef1d33e2cb3479e43e738f",
    "native_profile_v4/source_binding.py": "72f29914e87a5c35d1e33c41267da7057a739a077047513b11d8dcf48c2a42a3",
    "native_profile_v4/small_hcsn_profile.py": "a1c28b0a8a05d52d6394dde21381fb791bdcff8f10909947f50afc84d13cfd5a",
    "sensitivity_v4/first_order.py": "eecdf0a2f6aabbdbc65b79ed44c96b5badbd406c51252d89643260a923b5a55f",
    "sensitivity_v4/verify_first_order.py": "8506d27e0a5740901e0bdb40da17478de009d41629125d0888ba81ece01c374d",
}
RECEIPTS = {
    "failed": "15fbd987921708767c8143185c0a98a5caeb50e9984b4a88bc629fbf81af4105",
    "accepted": "8fff2a2525bb5ba411532e28fee28d549c491372add6feb2b58a9399d89a446e",
    "cold": "2e2cee24f0371ca53f148865f1f0f388ef69e4ae4dffb6fc2d8b205afb96c161",
}
PARENT = {
    "profile_sha256": "1ff30beb31a7033d1c9a6666dc76de9b2f9e93ac5d8467feafcef6db18dce17e",
    "checkpoint_sha256": "87ed31e17899f4ae18cbad3ea7a9b7af05cf42662da4ffd94a1c2c83cde9ef88",
    "checkpoint_bytes": 9855,
    "state_sha256": "9630e1de513658155e8c0c7c6cff13a3954cf49db3534ed3051c49fa035ac66c",
    "source_binding_sha256": "3146e2c56757ff7c818670aa3a9c229b26271c7336d573b1692b91ac8e7a00e9",
    "constructor": "plain_linear", "format": "research_candidate_v1",
}
COORDINATES = [{"name": name, "flat_index": index, "scale": 1.0} for name, index in (
    ("raw_cost", 4), ("input_drive.weight", 0), ("input_mark.weight", 0),
    ("recurrent.weight", 96), ("readout.weight", 0), ("readout.bias", 0))]
FIXED = {
    "runtime": {"python": "3.14.4", "numpy": "2.5.5", "torch": "2.15.0+cpu",
                "device": "cpu", "threads": 1, "interop_threads": 1},
    "coordinates": COORDINATES,
    "coordinate_sha256": "7950b64cfed821e58e7dd3dee08c656edaa74f80493aa24166133129e668768f",
    "input_sha256": "012e6e7c0c52b2f639ba6cca41f3197391c7b08e8804ed6c6d92941bd0374a93",
    "initial_margin_sha256": "0a497c985158f5df5b0564153450d13370bacae293ddc9d59fd204ce8697c52b",
    "fd": {"h": 1e-5, "half_h": 5e-6, "atol": 1e-7, "rtol": 3e-5,
           "gap_floor_multiplier": 4, "gap_shrink_factor": 0.75},
    "budget": {"candidate_loads": 1, "physical_forward_calls": 26,
               "scalar_output_vjp_calls": 2, "training_matrix_runs": 0,
               "quadratic_solves": 0, "training_updates": 0, "candidate_exports": 0,
               "retries": 0, "wall_seconds": 120, "cpu_seconds": 120},
    "stop": "one fixed candidate and stencil; any failure or inconclusive row ends this protocol",
}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def bootstrap(args):
    # Verify the stdlib-only input reader before importing it or any framework.
    for name, expected in SOURCES.items():
        require(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected,
                "frozen dependency changed: " + name)
    require(not any(name in sys.modules for name in (
        "profile_io", "source_binding", "small_hcsn_profile", "first_order", "verify_first_order",
        "numpy", "torch")), "new process required")
    sys.path[:0] = [str(ROOT / "native_profile_v4"), str(ROOT / "sensitivity_v4")]
    io = importlib.import_module("profile_io")
    protocol = io.parse(io.read_named(args.protocol, args.protocol_sha256, 65536))
    require(protocol["schema"] == "hepta.smallhcsn.accepted-point-sensitivity-protocol.v1"
            and protocol["ready_for_execution"] is True, "inactive or unsupported protocol")
    require(protocol["parent"] == PARENT and protocol["fixed"] == FIXED
            and protocol["receipt_sha256"] == RECEIPTS, "fixed experiment differs")
    require(set(protocol["source_sha256"]) == set(SOURCES) | {ENTRY}, "source roster differs")
    for name, expected in protocol["source_sha256"].items():
        require(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected,
                "protocol source pin differs: " + name)
    require({k: protocol["source_sha256"][k] for k in SOURCES} == SOURCES,
            "numerical source versions differ")
    return io, protocol


def provenance(args, io, result):
    paths = {key: getattr(args, key + "_result") for key in RECEIPTS}
    evidence = {key: io.parse(io.read_named(paths[key], digest, 1024 * 1024))
                for key, digest in RECEIPTS.items()}
    failed, accepted, cold = (evidence[key] for key in ("failed", "accepted", "cold"))
    require(failed["status"] == "FAILED" and failed["finite_difference"]["passed"] is False,
            "original failed gate was not preserved")
    require([{key: row[key] for key in ("name", "flat_index", "scale")}
             for row in failed["finite_difference"]["rows"]] == COORDINATES,
            "original coordinate roster differs")
    require(accepted["status"] == "COMPLETED_SINGLE_TRIAL" and accepted["decision"] == "ACCEPTED"
            and accepted["original_failed_result_sha256"] == RECEIPTS["failed"]
            and accepted["original_smooth_status"] == "FAILED"
            and accepted["classical_jacobian_admitted"] is False, "accepted lineage differs")
    export = accepted["candidate_export"]
    require(export["artifact"]["sha256"] == PARENT["checkpoint_sha256"]
            and export["artifact"]["bytes"] == PARENT["checkpoint_bytes"]
            and export["model_state_sha256"] == PARENT["state_sha256"], "accepted candidate differs")
    require(cold["status"] == "PASSED_BOUNDED_ENGINEERING"
            and cold["candidate_sha256"] == PARENT["checkpoint_sha256"]
            and cold["candidate_state_sha256"] == PARENT["state_sha256"]
            and cold["candidate_profile"]["sha256"] == PARENT["profile_sha256"]
            and cold["source_binding_sha256"] == PARENT["source_binding_sha256"]
            and cold["receipt_sha256"]["RESULT.json"] == RECEIPTS["accepted"]
            and cold["candidate_config"] == accepted["parent"]["config"] == failed["parent"]["config"],
            "cold candidate identity differs")
    result["lineage"] = {"receipt_sha256": RECEIPTS, "original_parent": failed["parent"],
                         "original_smooth_status": "FAILED", "original_failure_modified": False}
    return evidence, paths


def equal(left, right, torch):
    if isinstance(left, torch.Tensor):
        return isinstance(right, torch.Tensor) and bool(torch.equal(left, right))
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return set(left) == set(right) and all(equal(left[k], right[k], torch) for k in left)
    if isinstance(left, (tuple, list)):
        return len(left) == len(right) and all(equal(a, b, torch) for a, b in zip(left, right))
    if isinstance(left, float) and math.isnan(left):
        return math.isnan(right)
    return bool(left == right)


def check_point(profile, first, fixture_module, cold, result):
    model, torch = profile.model, profile.torch
    fingerprint = importlib.import_module("small_hcsn_profile").tensor_state_sha256
    profile.require_frozen()
    state = {k: v.detach().clone() for k, v in model.state_dict().items()}
    parameters = dict(model.named_parameters())
    flags = {k: p.requires_grad for k, p in parameters.items()}
    grads = {k: (p.grad, None if p.grad is None else p.grad.detach().clone()) for k, p in parameters.items()}
    modes = [(module, module.training) for module in model.modules()]
    config, diagnostics = copy.deepcopy(model.config), copy.deepcopy(model.last_diagnostics)
    result["parent_trainability"] = {"requires_grad": flags,
        "sha256": hashlib.sha256(json.dumps(flags, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
    counts, observed = result["counts"], {"ad_output_requires_grad": None}

    def before_forward(_model, _args):
        require(counts["physical_forward_calls"] < 26, "forward budget exhausted")
        counts["physical_forward_calls"] += 1

    def after_forward(_model, _args, output):
        counts["completed_physical_forwards"] += 1
        if counts["physical_forward_calls"] == 1:
            observed["ad_output_requires_grad"] = bool(output[0].requires_grad)

    hooks = []
    try:
        hooks.append(model.register_forward_pre_hook(before_forward))
        hooks.append(model.register_forward_hook(after_forward))
        require([c.record() for c in fixture_module.COORDINATES] == COORDINATES,
                "pinned fixture coordinate identity differs")
        x, margin = fixture_module.fixture()
        result["raw_cost_4"] = float(parameters["raw_cost"].reshape(-1)[4].detach())
        counts["scalar_output_vjp_calls"] = None  # Unknown if an exception interrupts the two-row loop.
        lin = first.linearize_fresh(model, x, margin, fixture_module.COORDINATES,
                                    state_fingerprint=fingerprint)
        counts["scalar_output_vjp_calls"] = 2 if observed["ad_output_requires_grad"] else 0
        require(observed["ad_output_requires_grad"] is True, "disconnected AD output")
        result["linearization"] = {**lin.metadata, "base_output": lin.base_output.tolist(),
                                   "jacobian": lin.jacobian.tolist()}
        for key in ("coordinate_sha256", "input_sha256", "initial_margin_sha256"):
            require(lin.metadata[key] == FIXED[key], "fixed observation identity differs: " + key)
        require(lin.metadata["parent_state_sha256"] == PARENT["state_sha256"]
                and lin.metadata["observation_count"] == 2 and lin.metadata["shared_coordinate_count"] == 6,
                "parent or observation dimensions differ")
        require(lin.base_output.tolist() == cold["cold_margins"], "fixed parent differs from cold result")
        result["finite_difference"] = first.controlled_finite_difference(
            model, x, margin, lin, state_fingerprint=fingerprint,
            h=1e-5, atol=1e-7, rtol=3e-5)
        require(result["finite_difference"]["physical_forward_calls"] == 25
                and counts["physical_forward_calls"] == counts["completed_physical_forwards"] == 26,
                "source-derived physical budget differs")
        require(result["finite_difference"]["passed"], "fixed new-point gate unresolved or failed; stop")
    finally:
        for hook in hooks:
            hook.remove()
        invariant = {
            "state_unchanged_before_cleanup": fingerprint(model.state_dict()) == PARENT["state_sha256"],
            "trainability_unchanged_before_cleanup": flags == {k: p.requires_grad for k, p in parameters.items()},
            "gradients_unchanged_before_cleanup": all(equal(p.grad, grads[k][1], torch) for k, p in parameters.items()),
            "config_unchanged_before_cleanup": asdict(model.config) == asdict(config),
            "modes_unchanged_before_cleanup": all(module.training == mode for module, mode in modes),
        }
        with torch.no_grad():
            model.load_state_dict(state, strict=True)
            for name, parameter in parameters.items():
                parameter.requires_grad_(flags[name])
                original, value = grads[name]
                if original is not None:
                    original.copy_(value)
                parameter.grad = original
        model.config, model.last_diagnostics = config, diagnostics
        for module, mode in modes:
            module.training = mode
        profile.require_frozen()
        invariant["state_restored"] = fingerprint(model.state_dict()) == PARENT["state_sha256"]
        invariant["trainability_restored"] = flags == {k: p.requires_grad for k, p in parameters.items()}
        invariant["gradients_restored"] = all(equal(p.grad, grads[k][1], torch) for k, p in parameters.items())
        invariant["diagnostics_restored"] = equal(model.last_diagnostics, diagnostics, torch)
        result["restoration"] = invariant
        require(all(invariant.values()), "parent mutation or restoration failure; stop")


def execute(args, io, protocol, result):
    evidence, paths = provenance(args, io, result)
    modules = {name: importlib.import_module(name) for name in (
        "small_hcsn_profile", "source_binding", "first_order", "verify_first_order")}
    for name, module in modules.items():
        directory = "sensitivity_v4" if name in ("first_order", "verify_first_order") else "native_profile_v4"
        require(Path(module.__file__).resolve() == (ROOT / directory / (name + ".py")).resolve(),
                "dependency import location differs")
    require(modules["source_binding"].RUNTIME == FIXED["runtime"], "numerical runtime pin differs")
    manifest = io.parse(io.read_named(args.profile, PARENT["profile_sha256"], 1024 * 1024))
    require(manifest["format"] == PARENT["format"] and manifest["runtime"] == FIXED["runtime"],
            "candidate format or runtime differs")
    require(manifest["checkpoint"]["sha256"] == PARENT["checkpoint_sha256"]
            and manifest["checkpoint"]["bytes"] == PARENT["checkpoint_bytes"], "full checkpoint identity differs")
    result["counts"]["candidate_loads"] += 1
    profile = modules["small_hcsn_profile"].load_profile(args.profile, PARENT["profile_sha256"], args.material_root)
    result["parent"] = {**PARENT, "config": profile.config}
    require(profile.candidate_sha256 == PARENT["checkpoint_sha256"]
            and profile.model_state_sha256 == PARENT["state_sha256"]
            and profile.source_binding_sha256 == PARENT["source_binding_sha256"]
            and profile.constructor == PARENT["constructor"]
            and profile.config == evidence["cold"]["candidate_config"], "loaded complete parent differs")
    try:
        check_point(profile, modules["first_order"], modules["verify_first_order"], evidence["cold"], result)
    finally:
        io.read_pin(args.material_root, manifest["checkpoint"], 32 * 1024 * 1024)
        io.read_named(args.profile, PARENT["profile_sha256"], 1024 * 1024)
        for key, path in paths.items():
            io.read_named(path, RECEIPTS[key], 1024 * 1024)
        result["retained_inputs_unchanged"] = True


def main():
    parser = argparse.ArgumentParser()
    for name in ("protocol", "protocol-sha256", "profile", "material-root", "failed-result",
                 "accepted-result", "cold-result", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    io, protocol = bootstrap(args)
    out = Path(args.output)
    out.mkdir(parents=False, exist_ok=False)
    result = {"schema": "hepta.smallhcsn.accepted-point-sensitivity-result.v1", "status": "FAILED",
        "protocol_sha256": args.protocol_sha256, "source_sha256": protocol["source_sha256"],
        "original_smooth_status": "FAILED", "original_failure_modified": False,
        "classical_differentiability_proved": False, "global_smoothness_claim": False,
        "natural_task_benefit_claim": False, "production_adoption": False,
        "new_point_fixed_stencil_passed": False, "runtime": FIXED["runtime"],
        "source_derived_budget": FIXED["budget"], "test_retuning": False,
        "counts": {"candidate_loads": 0, "physical_forward_calls": 0, "completed_physical_forwards": 0,
                   "scalar_output_vjp_calls": 0, "scalar_output_vjp_upper_bound": 2,
                   "training_matrix_runs": 0, "quadratic_solves": 0, "training_updates": 0,
                   "candidate_exports": 0, "retries": 0}}
    start, cpu = time.monotonic(), time.process_time()
    def timeout(_signum, _frame):
        raise TimeoutError("fixed wall or CPU budget exhausted; stop")
    signal.signal(signal.SIGALRM, timeout)
    signal.signal(signal.SIGXCPU, timeout)
    resource.setrlimit(resource.RLIMIT_CPU, (120, 121))
    signal.alarm(120)
    try:
        execute(args, io, protocol, result)
        result.update(status="PASSED_FIXED_NEW_POINT_STENCIL", new_point_fixed_stencil_passed=True)
    except Exception as error:
        result["error"] = str(error)
        result["traceback"] = traceback.format_exc(limit=12)
    finally:
        signal.alarm(0)
        result.update(wall_s=time.monotonic() - start, cpu_s=time.process_time() - cpu)
        io.write_new(out / "RESULT.json", io.canonical(result) + b"\n", 1024 * 1024)
    print(json.dumps({"status": result["status"], "output": str(out / "RESULT.json")}, sort_keys=True))
    return 0 if result["status"] == "PASSED_FIXED_NEW_POINT_STENCIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
