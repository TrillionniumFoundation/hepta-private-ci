"""Identity, registration and fail-closed checks for a separate diagnosis."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


HERE = Path(__file__).resolve().parent
PORTFOLIO = HERE.parent.parent
REPOSITORY = PORTFOLIO.parent.parent
CASES = ("unset_before", "default", "avx2", "avx512", "unset_after")
FIELDS = ("text_fact", "relation", "image_fact", "crossmodal_disagreement", "pixel_mse")
SOURCE_NAMES = ("PROTOCOL.json", "run.py", "fixed_inputs_common.py", "fixed_inputs_snapshot.py",
                "fixed_inputs_score.py", "tests.py")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def identity(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "Input is not a regular nonsymlink file")
    return {"bytes": path.stat().st_size, "sha256": sha(path)}


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def registration(commit):
    require(re.fullmatch(r"[0-9a-f]{40}", commit), "A registered full commit is required")
    result = {}
    for filename in SOURCE_NAMES:
        path = HERE / filename
        name, raw = path.relative_to(REPOSITORY).as_posix(), path.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        row = subprocess.check_output(["git", "ls-tree", commit, "--", name], cwd=REPOSITORY,
                                      env={**os.environ, "GIT_NO_LAZY_FETCH": "1"}, text=True).strip()
        require(row == "100644 blob " + blob + "\t" + name, "Unregistered source: " + name)
        result[name] = {"sha256": hashlib.sha256(raw).hexdigest(), "git_blob": blob}
    return {"commit": commit, "files": result}


def verify_inputs(protocol, args):
    roots = {"repository": REPOSITORY, "run": args.run_root, "assets": args.assets,
             "runtime": Path(sys.prefix), "first_attempt": args.first_attempt,
             "workspace": args.run_root.parent}
    found = {}
    for name, item in protocol["inputs"].items():
        path = (roots[item["root"]] / item["path"]).resolve()
        require(path.is_relative_to(roots[item["root"]].resolve()), "Input escapes declared root")
        require(identity(path) == {k: item[k] for k in ("bytes", "sha256")}, "Input differs: " + name)
        found[name] = path
    freeze = read(found["scientific_source_freeze"])
    require(len(freeze["files"]) == 64, "Scientific dependency inventory differs")
    for name, expected in freeze["files"].items():
        require(sha(PORTFOLIO / name) == expected, "Frozen dependency differs: " + name)
    require(read(found["original_failed_audit"])["integrity_status"] == "FAIL", "Original FAIL changed")
    first = read(found["first_attempt_summary"])
    require(first["source_registration"]["commit"] == protocol["first_attempt"]["registered_commit"]
            and not first["execution_complete"] and not first["diagnostic_interpretable"]
            and first["scientific_status"] == "FAIL" and not first["admission"], "First failure changed")
    failed = read(found["first_default_result"])
    require(failed["status"] == "FAIL" and failed["error"] == "Reconstructed inputs changed"
            and failed["resources"] == {}, "First DEFAULT failure differs")
    historical = {row["path"]: row for row in read(found["historical_archive_integrity"])["members"]}
    for panel, target in protocol["historical_raw_identities"].items():
        require(target == historical["run/development/17/original-" + panel + ".npz"],
                "Historical raw target differs")
    require(set(protocol["historical_raw_identities"]) == {"task", "clean"}, "Missing historical target")
    require(protocol["cases"] == list(CASES) and protocol["seed"] == 17
            and protocol["source_roles"] == ["development_task", "development_clean"]
            and not protocol["new_holdout_access"] and not protocol["admission"], "Scope differs")
    require(sys.version_info[:3] == (3, 12, 14) and sys.flags.isolated and sys.dont_write_bytecode,
            "Pinned isolated Python with -B is required")
    return found, freeze


def imports_receipt(freeze, sources):
    allowed_new = {str((REPOSITORY / name).resolve()): row["sha256"]
                   for name, row in sources["files"].items() if name.endswith(".py")}
    result = {}
    for name, module in list(sys.modules.items()):
        location = getattr(module, "__file__", None)
        if not isinstance(location, (str, bytes)):
            continue
        path = Path(location).resolve()
        if name.startswith("experiments.") or path.is_relative_to(PORTFOLIO):
            require(path.is_relative_to(PORTFOLIO), "Research import escaped frozen portfolio")
            relative = path.relative_to(PORTFOLIO).as_posix()
            expected = freeze["files"].get(relative, allowed_new.get(str(path)))
            require(expected is not None and sha(path) == expected, "Unregistered research import: " + str(path))
            result[name] = {"path": str(path), "sha256": expected}
    require(not any("historical_dispatch_20261028" in row["path"] for row in result.values()),
            "First-attempt executable code was imported")
    return result


def array_identity(array):
    import numpy as np

    require(isinstance(array, np.ndarray) and array.dtype.kind in "fiub" and array.flags.c_contiguous,
            "Expected a contiguous numeric array")
    require(np.isfinite(array).all(), "Nonfinite array")
    return {"dtype": array.dtype.str, "shape": list(array.shape), "bytes": array.nbytes,
            "sha256": hashlib.sha256(array.tobytes(order="C")).hexdigest()}


def bitwise(left, right):
    return array_identity(left) == array_identity(right)


def compare(left, right):
    import numpy as np

    require(left.dtype == right.dtype and left.shape == right.shape, "Array type/shape differs")
    require(np.isfinite(left).all() and np.isfinite(right).all(), "Nonfinite diagnostic value")
    mask, delta = left != right, left - right
    return {"exact": bool(np.array_equal(left, right)), "bitwise_exact": bitwise(left, right),
            "shape": list(left.shape), "dtype": str(left.dtype), "different_values": int(mask.sum()),
            "max_abs_difference": float(np.abs(delta).max()), "mean_difference": float(delta.mean()),
            "indices": np.argwhere(mask).tolist(), "left": left[mask].tolist(),
            "right": right[mask].tolist(), "delta": delta[mask].tolist(),
            "convention": "left minus right", "tolerance": None}


def disk_record(path, remaining_bytes, reserve_bytes, stat=None, effective_uid=None):
    stat = os.statvfs(path) if stat is None else stat
    effective_uid = os.geteuid() if effective_uid is None else effective_uid
    free, available = stat.f_bfree * stat.f_frsize, stat.f_bavail * stat.f_frsize
    usable = free if effective_uid == 0 else available
    return {"path": str(path), "effective_uid": effective_uid, "f_bfree_bytes": free,
            "f_bavail_bytes": available, "allocatable_basis": "f_bfree" if effective_uid == 0 else "f_bavail",
            "allocatable_bytes": usable, "remaining_output_bound_bytes": remaining_bytes,
            "reserve_bytes": reserve_bytes, "required_bytes": remaining_bytes + reserve_bytes,
            "passed": usable >= remaining_bytes + reserve_bytes}


class LimitedCosts:
    """Reject the next accounted invocation before any corresponding model call."""

    def __init__(self, inner, limits):
        self.inner, self.limits = inner, limits

    def snapshot(self):
        return self.inner.snapshot()

    def check(self, suffix, amount, limit):
        current = sum(value for name, value in self.snapshot().items() if name.endswith(suffix))
        require(current + amount <= self.limits[limit], "Pre-call resource bound exceeded: " + limit)

    def forward(self, name, examples, action):
        require(name.endswith("_generator") and action == 0, "Unexpected generator invocation")
        self.check("generator_calls", 1, "generator_panel_calls")
        self.check("generator_examples", examples, "generator_examples")
        self.inner.forward(name, examples, action)

    def add(self, name, amount=1):
        require(name.endswith(("observer_calls", "observer_digit_examples")), "Unexpected inference resource")
        if name.endswith("observer_calls"):
            self.check("observer_calls", amount, "observer_calls")
        else:
            self.check("observer_digit_examples", amount, "observer_digit_examples")
        self.inner.add(name, amount)


def configuration_identity(model, observers):
    value = {"model_config": model.config, "modules": {}}
    for name, instance in {"model": model, **observers}.items():
        value["modules"][name] = {
            "tree": {key: {"class": type(module).__module__ + "." + type(module).__qualname__,
                           "extra_repr": module.extra_repr(), "training": module.training}
                     for key, module in instance.named_modules()},
            "requires_grad": {key: parameter.requires_grad for key, parameter in instance.named_parameters()}}
    return {"sha256": hashlib.sha256(canonical(value)).hexdigest(), "value": json.loads(canonical(value))}


def write_bounded_summary(directory, payload, maximum_metadata_bytes):
    """Premeasure UTF-8 bytes; preserve child evidence and write a compact FAIL on overflow."""
    directory = Path(directory)
    existing = sum(path.stat().st_size for path in directory.rglob("*") if path.is_file()
                   and path.relative_to(directory).parts[0] not in (*CASES, "input_snapshot"))

    def measured(value):
        value["metadata_storage"] = {"bound_bytes": maximum_metadata_bytes, "existing_metadata_bytes": existing,
            "summary_bytes": 0, "total_metadata_bytes": 0, "within_bound": False,
            "case_dirs_and_input_snapshot_excluded": True}
        for unused in range(10):
            raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
            record = value["metadata_storage"]
            if record["summary_bytes"] == len(raw):
                return raw
            record.update(summary_bytes=len(raw), total_metadata_bytes=existing + len(raw),
                          within_bound=existing + len(raw) <= maximum_metadata_bytes)
        raise ValueError("Summary byte measurement did not converge")

    full = measured(payload)
    fitted = existing + len(full) <= maximum_metadata_bytes
    if not fitted:
        compact = {key: payload.get(key) for key in ("source_registration", "observed_resources",
            "observed_sealed_case_totals", "actual_totals", "resource_accounting_complete",
            "unknown_resource_cases", "first_attempt_actual_totals", "scientific_status", "admission",
            "new_holdout_authorized", "historical_raw_file_recovered", "historical_gate_changed",
            "raw_upload_attempts", "selected_capability")}
        compact.update(execution_complete=False, diagnostic_interpretable=False,
            all_child_cases_completed=payload["execution_complete"], prior_error=payload.get("error"),
            error={"type": "MetadataStorageBoundError", "message": "Full summary exceeds registered metadata bound"},
            full_summary_not_written={"bytes": len(full), "sha256": hashlib.sha256(full).hexdigest()},
            preserved_evidence="All child RESULT/raw/components/forward-field files and input snapshots remain intact.",
            interpretation="Summary storage failed. No scientific/admission status is repaired; detailed comparisons remain in child RESULT files.",
            cases=[{key: item.get(key) for key in ("phase", "exit_code", "result_file", "stdout", "stderr",
                    "resource_accounting_complete", "registered_call_upper_bound")} for item in payload["cases"]],
            preparation={key: payload["preparation"].get(key) for key in
                         ("phase", "exit_code", "result_file", "resource_accounting_complete")}
                         if payload["preparation"] else None)
        chosen, raw = compact, measured(compact)
    else:
        chosen, raw = payload, full
    with (directory / "SUMMARY.json").open("xb") as stream:
        stream.write(raw)
    return {"full_summary_written": fitted, "metadata_bound_satisfied": chosen["metadata_storage"]["within_bound"],
            "summary": identity(directory / "SUMMARY.json")}


def setup_torch(protocol, case):
    import numpy as np
    import torch

    require(torch.__version__ == "2.8.0+cpu" and np.__version__ == "2.3.5", "Runtime version mismatch")
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    requested = None if case == "prepare" or case.startswith("unset_") else case
    capability = torch.backends.cpu.get_cpu_capability()
    require(os.environ.get("ATEN_CPU_CAPABILITY") == requested, "Dispatch environment differs")
    expected = ["AVX512"] if case == "prepare" else protocol["expected_capabilities"][case]
    require(capability in expected, "Requested capability not observed")
    require(all(os.environ.get(k) == v for k, v in protocol["fixed_environment"].items()), "Other CPU environment changed")
    return {"requested_capability": requested, "observed_capability": capability,
            "torch_build_configuration": torch.__config__.show()}


def execution_guard(phase, violations, counts, watch):
    def profile(frame, event, unused):
        if event != "call":
            return
        module, function = frame.f_globals.get("__name__", ""), frame.f_code.co_name
        prohibited = ((module.startswith("torch.optim.") and function in ("__init__", "step"))
            or (module.startswith("torch.autograd") and function in ("backward", "_engine_run_backward"))
            or (module.startswith("experiments.") and function in
                ("make_context", "make_model", "new_optimizer", "rollout", "update", "fit_observer")))
        if phase == "prepare":
            prohibited |= ((module.startswith("torch.nn.") and function == "__init__")
                or (module.startswith("experiments.") and function in ("load_assets", "model_from_config", "read_checkpoint")))
        else:
            prohibited |= module.startswith("experiments.") and function in ("panels", "make_batch", "load_corpus_roles")
        if prohibited:
            violations.append({"module": module, "function": function})
            raise RuntimeError("Diagnostic attempted a prohibited operation")
        instance = frame.f_locals.get("self")
        counter = None
        if instance is watch.get("model") and instance is not None:
            counter = {"encode": "generator_pipeline_started", "decode": "generator_decode_calls"}.get(function)
        if function == "forward" and any(instance is x for x in watch.get("observers", ())):
            counter = "observer_forward_calls"
        if counter is not None:
            current = counts.get(counter, 0)
            if current >= watch["call_limits"][counter]:
                violations.append({"module": module, "function": function, "reason": "pre-call budget"})
                raise RuntimeError("Independent pre-call model budget exceeded")
            counts[counter] = current + 1
    return profile
