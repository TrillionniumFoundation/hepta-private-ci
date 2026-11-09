"""One fixed unsigned Joint text-training process; no owner/job authority.

Usage: python3 scripts/joint_generation_v4_text_worker.py --request ABS_JSON
       --predecessor ABS_HEPTAPK --output ABS_NEW_DIRECTORY

The caller supplies an existing immutable request and predecessor and retains
those originals. This process never replaces them. Output is create-only and
partial output is retained on failure. Only a complete marker plus the actual
observation and candidate bytes can describe a successful candidate operation.
Interpreter and Torch provenance, process isolation, authenticated job identity,
and hard cancellation remain obligations of the real host/provider.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time
import types


BOOTSTRAP_SOURCES = (
    "scripts/joint_text_training_contract.py",
    "scripts/joint_text_training_io.py",
    "scripts/joint_generation_v4_text_worker.py",
)
NAMESPACES = (
    "scripts",
    "experiments",
    "experiments.multimodal_output_portfolio",
    "experiments.multimodal_output_portfolio.joint_hepta_20261029",
)


def _bootstrap_bytes(path):
    """Small stdlib bootstrap; subsequent imports use these captured bytes."""
    if path.resolve(strict=True) != path:
        raise ValueError("bootstrap_physical_path")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > 262144:
        raise ValueError("bootstrap_regular_bound")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)

    def fields(value):
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
            value.st_nlink,
        )

    try:
        if fields(os.fstat(fd)) != fields(before):
            raise ValueError("bootstrap_open_race")
        data = bytearray()
        while len(data) <= 262144:
            part = os.read(fd, min(65536, 262145 - len(data)))
            if not part:
                break
            data.extend(part)
        if (
            len(data) != before.st_size
            or fields(os.fstat(fd)) != fields(before)
            or fields(path.lstat()) != fields(before)
        ):
            raise ValueError("bootstrap_read_race")
        return bytes(data)
    finally:
        os.close(fd)


def _module(name, path, raw):
    if name in sys.modules:
        raise ValueError("preloaded_repository_module")
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = name.rpartition(".")[0]
    module.__pinned_source_sha256__ = hashlib.sha256(raw).hexdigest()
    sys.modules[name] = module
    try:
        exec(compile(raw, str(path), "exec"), module.__dict__)
    except BaseException:
        del sys.modules[name]
        raise
    return module


def bootstrap():
    """Use only this worker's fixed repository modules, never request code."""
    source = Path(__file__).absolute()
    root = source.parent.parent
    captured = {name: _bootstrap_bytes(root / name) for name in BOOTSTRAP_SOURCES}
    for name in NAMESPACES:
        directory = root.joinpath(*name.split("."))
        try:
            (directory / "__init__.py").lstat()
        except FileNotFoundError:
            pass
        else:
            raise ValueError("unexpected_repository_initializer")
        if name in sys.modules:
            raise ValueError("preloaded_repository_namespace")
        namespace = types.ModuleType(name)
        namespace.__package__ = name
        namespace.__path__ = [str(directory)]
        sys.modules[name] = namespace
    contract = _module(
        "scripts.joint_text_training_contract",
        root / BOOTSTRAP_SOURCES[0],
        captured[BOOTSTRAP_SOURCES[0]],
    )
    io = _module(
        "scripts.joint_text_training_io",
        root / BOOTSTRAP_SOURCES[1],
        captured[BOOTSTRAP_SOURCES[1]],
    )
    # Namespace modules above point at fixed captured sources. Avoid ambient
    # repository/cwd entries shadowing installed external runtime dependencies.
    sys.path[:] = [
        entry
        for entry in sys.path
        if entry and not Path(entry).resolve().is_relative_to(root)
    ]
    return root, captured, contract, io


def load_computation(closure):
    paths = (
        (
            "experiments.multimodal_output_portfolio.joint_hepta_20261029.hepta_core",
            "experiments/multimodal_output_portfolio/joint_hepta_20261029/hepta_core.py",
        ),
        ("scripts.joint_generation_v4_io", "scripts/joint_generation_v4_io.py"),
        ("scripts.joint_generation_v4_model", "scripts/joint_generation_v4_model.py"),
        (
            "scripts.joint_text_training_compute",
            "scripts/joint_text_training_compute.py",
        ),
    )
    result = None
    for name, relative in paths:
        result = _module(name, closure.root / relative, closure.files[relative].raw)
    return result


def error_code(error, contract):
    if isinstance(error, contract.ContractError):
        return str(error)
    if isinstance(error, ModuleNotFoundError):
        return "runtime_dependency_unavailable"
    if isinstance(error, OSError):
        return "os_error_" + str(error.errno)
    if isinstance(error, (ValueError, TypeError)):
        return "packet_or_model_rejected"
    if isinstance(error, RuntimeError):
        return "numerical_runtime_error"
    if isinstance(error, KeyboardInterrupt):
        return "interrupted"
    return "worker_error"


def _input_closure(snapshots):
    if len(snapshots) != 2:
        return None
    try:
        for snapshot in snapshots:
            snapshot.check()
        return True
    except (OSError, ValueError):
        return False


def _source_closure(sources):
    if sources is None:
        return None
    try:
        sources.check()
        return True
    except (OSError, ValueError):
        return False


def run_worker(
    request_path, predecessor_path, output_path, root, captured, contract, io
):
    """Persist a success marker only after actual byte and source closure."""
    store = io.OutputStore(output_path)
    wall_start, cpu_start = time.monotonic_ns(), time.process_time_ns()
    stage, request_sha, sources = "request", None, None
    inputs = []
    try:
        original_request = io.read_snapshot(request_path, contract.MAX_JSON_BYTES)
        inputs.append(original_request)
        request_sha = contract.sha(original_request.raw)
        store.write(
            "started.json",
            contract.json_bytes(
                {
                    "schema": "hepta.joint-text-worker.started.v1",
                    "profile": contract.PROFILE,
                    "status": "started",
                    "request_sha256": request_sha,
                }
            ),
        )
        request = contract.validate_request(original_request.raw)
        wall_limit = (
            min(contract.MAX_WALL_MS, request["maximum_training_milliseconds"])
            * 1000000
        )

        def check_budget():
            contract.require(
                time.monotonic_ns() - wall_start <= wall_limit,
                "cooperative_wall_budget",
            )

        stage = "source"
        sources = io.SourceClosure(root)
        contract.require(
            sources.digest == request["execution_source_digest"],
            "execution_source_binding",
        )
        contract.require(
            all(sources.files[name].raw == raw for name, raw in captured.items()),
            "bootstrap_source_changed",
        )
        check_budget()
        stage = "predecessor"
        predecessor = io.read_snapshot(predecessor_path, contract.MAX_PACKET_BYTES)
        inputs.append(predecessor)
        contract.require(
            len(predecessor.raw) == request["predecessor_bytes"]
            and contract.sha(predecessor.raw) == request["predecessor_sha256"],
            "predecessor_binding",
        )
        check_budget()
        stage = "load_runtime"
        compute = load_computation(sources)
        check_budget()
        stage = "train"
        result = compute.train_candidate(request, predecessor.raw, check_budget)
        candidate = result["candidate_bytes"]
        stage = "candidate"
        store.write("candidate.heptapk", candidate)
        readback = store.read("candidate.heptapk")
        contract.require(readback == candidate, "candidate_readback")
        restored, inference = compute.load_predecessor(readback)
        contract.require(
            restored.export_weights(inference_profile=inference) == readback,
            "persisted_candidate_roundtrip",
        )
        check_budget()
        stage = "input_closure"
        contract.require(_input_closure(inputs) is True, "input_file_changed")
        contract.require(_source_closure(sources) is True, "source_file_changed")
        check_budget()
        observation = {
            "schema": contract.OBSERVATION_SCHEMA,
            "profile": contract.PROFILE,
            "status": "candidate",
            "authority": "DENY_ALL",
            "request_sha256": request_sha,
            "request_binding_digest": contract.request_binding_digest(request),
            "training_profile_digest": contract.PROFILE_DIGEST,
            "update_rule_digest": contract.update_rule_digest(request),
            "execution_source_digest": sources.digest,
            "execution_sources": sources.rows,
            "absent_source_paths": sources.absent,
            "predecessor": {
                "sha256": request["predecessor_sha256"],
                "bytes": len(predecessor.raw),
                "after_sha256": contract.sha(predecessor.raw),
                "roundtrip": True,
            },
            "candidate": {
                "sha256": contract.sha(candidate),
                "bytes": len(candidate),
                "roundtrip": True,
                "changed": candidate != predecessor.raw,
            },
            "training": result["training"],
            "runtime": result["runtime"],
            "cost": {
                "wall_nanoseconds": time.monotonic_ns() - wall_start,
                "cpu_nanoseconds": time.process_time_ns() - cpu_start,
                "scope": contract.COST_SCOPE,
                "physical_energy_joules": None,
                "full_history_cost": None,
            },
            "claims": {
                "content_loss_training": True,
                "ndu_training": False,
                "evaluation": False,
                "product_loading": False,
                "selection": False,
                "stage_advanced": False,
            },
            "input_files_unchanged": True,
            "source_files_unchanged": True,
        }
        stage = "observation"
        contract.validate_observation_fields(observation)
        observation_raw = contract.json_bytes(observation)
        contract.validate_observation(observation_raw, request)
        store.write("observation.json", observation_raw)
        store.verify_names(("started.json", "candidate.heptapk", "observation.json"))
        stage = "complete"
        store.write(
            "completed.json",
            contract.json_bytes(
                {
                    "schema": "hepta.joint-text-worker.completed.v1",
                    "profile": contract.PROFILE,
                    "status": "complete",
                    "request_sha256": request_sha,
                    "observation_sha256": contract.sha(observation_raw),
                    "candidate_sha256": contract.sha(candidate),
                }
            ),
        )
        store.verify_names(
            ("started.json", "candidate.heptapk", "observation.json", "completed.json")
        )
        return {"status": "candidate", "request_sha256": request_sha}, 0
    except BaseException as error:
        code = error_code(error, contract)
        failure = {
            "schema": "hepta.joint-text-worker.failed.v1",
            "profile": contract.PROFILE,
            "status": "failed",
            "stage": stage,
            "error_code": code,
            "request_sha256": request_sha,
            "input_files_unchanged": _input_closure(inputs),
            "source_files_unchanged": _source_closure(sources),
        }
        try:
            store.write("failed.json", contract.json_bytes(failure))
        except (OSError, ValueError):
            # Original/partial output remains. Missing or partial completion is
            # not successful; no replacement or alternate attempt is made.
            code = "failure_marker_not_durable"
        return {"status": "failed", "stage": stage, "error_code": code}, 1
    finally:
        store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
    parser.add_argument("--predecessor", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    try:
        root, captured, contract, io = bootstrap()
        result, code = run_worker(
            arguments.request,
            arguments.predecessor,
            arguments.output,
            root,
            captured,
            contract,
            io,
        )
    except BaseException:
        # Invalid output/bootstrap admission may prevent opening any record.
        # The caller must retain this process result; no successful marker is
        # fabricated in an existing or untrusted output directory.
        result, code = (
            {"status": "failed", "error_code": "worker_admission_rejected"},
            1,
        )
    print(json.dumps(result, separators=(",", ":")), flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
