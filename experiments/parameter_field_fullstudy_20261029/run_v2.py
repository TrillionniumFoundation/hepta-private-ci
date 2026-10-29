"""Explicit, registered operational overrides for unchanged A/B/W/R functions.

Only resource admission/persistence and provenance differ from the frozen v1
runners.  The process-local budget substitution is scoped and declared; the
original files, optimizers, guards, features, actions, labels and counts remain
byte-identical.  This is attempt02, never recovery of the lost attempt01 bytes.
"""

import argparse
from contextlib import contextmanager
import hashlib
import importlib
import json
from pathlib import Path
import resource
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL_A = ("2a5219147d38ebb6514059bd69e2d3489bf7d69d213cd01343455f63a08a53d2",
              "68b4ecc44cea5f5bc7478ea1008adb1ab81098c6",
              "2c02b5aff224f125826931f3ecf691b2a01391a719075db8a1bc9fb5f5dafd55")
KINDS = {"A": "training", "B": "training", "W": "diagnostic", "R": "reconstruction"}
CAPS = {"A": 39168, "B": 23040, "W": 2880, "R": 32256}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_files(freeze, source_root):
    source_root = Path(source_root).resolve()
    require(freeze.get("source_files"), "Empty executable source closure")
    for name, expected in freeze["source_files"].items():
        target = (source_root / name).resolve()
        require(not Path(name).is_absolute() and ".." not in Path(name).parts
                and target.is_relative_to(source_root) and file_hash(target) == expected,
                "Frozen source differs: " + name)
    for name, expected in freeze.get("artifacts", {}).items():
        require(file_hash(name) == expected, "Frozen artifact differs: " + name)


def validate_freeze(args, registration):
    freeze = json.loads(Path(args.freeze).read_text())
    require(args.phase in freeze["allowed_phases"] and freeze.get("attempt_id") == registration["attempt_id"] == "attempt02"
            and freeze.get("execution_kind") == KINDS[args.phase]
            and freeze.get("operational_amendment_sha256") == registration["_sha256"],
            "Run is not explicitly registered for this attempt, phase and amendment")
    commit = freeze.get("registered_commit", "")
    require(len(commit) == 40 and all(c in "0123456789abcdef" for c in commit), "Invalid registered commit")
    require(Path(args.root).resolve() == Path(registration["raw_root"]).resolve(), "Run root differs from registered persistent-host root")
    verify_files(freeze, ROOT)
    prefix = Path(__file__).resolve().parent.relative_to(ROOT)
    required = ["run_v2.py", "resource_v2.py", "resource_io_v2.py"]
    required += ["witness.py", "endpoints.py"] if args.phase == "W" else ["replay_terminals.py"] if args.phase == "R" else ["run.py"]
    require(all((prefix / name).as_posix() in freeze["source_files"] for name in required), "Operational/scientific entrypoint is not source-frozen")
    descriptor = freeze["scientific_parent"]
    require((descriptor["sha256"], descriptor["registered_commit"], descriptor["protocol_sha256"]) == ORIGINAL_A,
            "A/B/W/R scientific ancestor is not the pinned original A closure")
    require(file_hash(descriptor["path"]) == descriptor["sha256"], "Scientific-parent freeze bytes differ")
    parent = json.loads(Path(descriptor["path"]).read_text())
    require(parent["registered_commit"] == descriptor["registered_commit"]
            and parent["protocol_sha256"] == descriptor["protocol_sha256"]
            and "A" in parent["allowed_phases"], "Scientific-parent contents differ")
    verify_files(parent, descriptor["source_root"])
    require(all(freeze["source_files"].get(name) == expected for name, expected in parent["source_files"].items()),
            "Original scientific closure was changed or omitted")
    require(registration["original_protocol"]["sha256"] == ORIGINAL_A[2], "Operational amendment changes the scientific protocol")
    protocol_path = args.protocolR if args.phase == "R" else args.protocol
    require(protocol_path and file_hash(protocol_path) == freeze["protocol_sha256"], "Active protocol bytes differ from source freeze")
    if args.phase != "R":
        require(freeze["protocol_sha256"] == ORIGINAL_A[2], "A/B/W scientific protocol changed")
    else:
        protocol = json.loads(Path(protocol_path).read_text())
        require(protocol.get("source_stage_A_protocol_sha256") == ORIGINAL_A[2], "R reconstruction must bind unchanged A protocol")
    return freeze


def check_work(costs, phase, wall_start, cpu_start):
    require(time.monotonic() - wall_start <= 10800 and time.process_time() - cpu_start <= 7200,
            "Original per-run CPU/wall ceiling exhausted")
    require(costs.values.get("scheduled_gradient_microsteps", 0) <= CAPS[phase],
            "Original physical gradient ceiling exceeded")


def phase_budget_type(storage, expected_root, selected_phase):
    class OperationalBudget:
        def __init__(self, root, costs, phase):
            require(Path(root).resolve() == Path(expected_root).resolve() and phase == selected_phase,
                    "Budget scope differs from registered run")
            self.root, self.costs, self.phase = Path(root), costs, phase
            self.wall, self.cpu = time.monotonic(), time.process_time()

        def __call__(self, additional=0):
            storage.check(additional=additional)
            check_work(self.costs, self.phase, self.wall, self.cpu)
    return OperationalBudget


def replay_budget_type(original, storage, expected_root):
    class OperationalReplayBudget(original):
        def __init__(self, root, costs):
            require(Path(root).resolve() == Path(expected_root).resolve(), "R budget root differs")
            super().__init__(root, costs)

        def check(self, additional=0):
            storage.check(additional=additional)
            check_work(self.costs, "R", self.wall, self.cpu)
    return OperationalReplayBudget


@contextmanager
def scoped_runner(module, attribute, replacement, argv):
    original, old_argv = getattr(module, attribute), sys.argv
    setattr(module, attribute, replacement)
    sys.argv = [module.__name__, *argv]
    try:
        yield
    finally:
        setattr(module, attribute, original)
        sys.argv = old_argv


def ensure_loaded_closure(freeze):
    for module in tuple(sys.modules.values()):
        filename = getattr(module, "__file__", None)
        if not filename:
            continue
        path = Path(filename).resolve()
        if path.suffix == ".py" and path.is_relative_to(ROOT):
            relative = path.relative_to(ROOT).as_posix()
            require(freeze["source_files"].get(relative) == file_hash(path), "Loaded repository dependency absent from freeze: " + relative)


def original_call(args, storage):
    common = ["--assets", args.assets, "--root", args.root, "--freeze", args.freeze]
    if args.phase in ("A", "B"):
        module = importlib.import_module(__package__ + ".run")
        return module, "Budget", phase_budget_type(storage, args.root, args.phase), common + ["--phase", args.phase, "--seed", str(args.seed)]
    if args.phase == "W":
        module = importlib.import_module(__package__ + ".witness")
        return module, "EndpointBudget", phase_budget_type(storage, args.root, "W"), common + ["--protocol", args.protocol]
    module = importlib.import_module(__package__ + ".replay_terminals")
    return module, "ReplayBudget", replay_budget_type(module.ReplayBudget, storage, args.root), common + ["--protocolR", args.protocolR, "--seed", str(args.seed)]


def process_peak_rss_bytes():
    """Linux ru_maxrss is KiB and covers the full worker lifetime to this point."""
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


def completion_path(root, phase, seed):
    stage = Path(root) / ("stage_" + phase)
    return stage / "COMPLETE.json" if phase == "W" else stage / ("seed-" + str(seed)) / "COMPLETE.json"


def execute(args):
    require(args.execute, "Explicit registered operational execution is required")
    require((args.phase == "W" and args.seed is None) or (args.phase != "W" and args.seed in (17, 29, 43)), "Phase/seed inventory differs")
    from .resource_v2 import StorageBudget, load_registration, training_slot, whole_phase_lock
    from .resource_io_v2 import guarded_writes
    registration = load_registration(args.amendment, args.amendment_sha256)
    freeze = validate_freeze(args, registration)
    root = Path(args.root).resolve()
    require(root.is_dir(), "Registered raw root must already exist")
    storage = StorageBudget(root, registration)
    token = args.phase + ("-all" if args.phase == "W" else "-seed-" + str(args.seed))
    operations = root / "operations"
    lock = training_slot(root, registration) if args.phase in ("A", "B", "R") else whole_phase_lock(root)
    provenance = {"schema": "hepta.fullstudy.training-operation.2" if args.phase in ("A", "B") else "hepta.fullstudy.operational-run.2", "attempt_id": "attempt02", "phase": args.phase,
                  "seed": args.seed, "execution_kind": KINDS[args.phase], "operational_amendment_sha256": registration["_sha256"],
                  "controller_group": "training" if args.phase in ("A", "B") else "reconstruction" if args.phase == "R" else "witness_singleton",
                  "source_freeze_sha256": file_hash(args.freeze), "registered_commit": freeze["registered_commit"],
                  "scientific_parent": freeze["scientific_parent"], "scientific_protocol_sha256": ORIGINAL_A[2],
                  "entrypoint_protocol_sha256": freeze["protocol_sha256"],
                  "override_scope": "Registered resource admission and persistence only; process-local budget substitution is explicit and scoped.",
                  "original_1GiB_2GiB_reserve_contract_completed": False,
                  "attempt01_raw_recovered": False, "scientific_source_bytes_unchanged": True}
    with lock:
        with guarded_writes(storage):
            storage.check()
            operations.mkdir(exist_ok=True)
            storage.write_json(operations / (token + ".START.json"), {**provenance, "complete": False, "started_unix": time.time()})
            try:
                module, attribute, replacement, argv = original_call(args, storage)
                ensure_loaded_closure(freeze)
                with scoped_runner(module, attribute, replacement, argv):
                    module.main()
                target = completion_path(root, args.phase, args.seed)
                result = json.loads(target.read_text())
                require(result.get("complete") is True and result["source_freeze_sha256"] == file_hash(args.freeze)
                        and result["registered_commit"] == freeze["registered_commit"], "Original runner did not seal this registered attempt")
                storage.check()
                receipt = {**provenance, "complete": True, "completed_unix": time.time(),
                           "scientific_complete": {"path": target.relative_to(root).as_posix(), "bytes": target.stat().st_size, "sha256": file_hash(target)},
                           "post_execution_storage_check": True, "process_peak_rss_bytes": process_peak_rss_bytes()}
                storage.write_json(operations / (token + ".COMPLETE.json"), receipt)
                print(json.dumps({"operational_complete": True, "phase": args.phase, "seed": args.seed}), flush=True)
                return receipt
            except BaseException as error:
                failure = {**provenance, "complete": False, "error_type": type(error).__name__, "message": str(error), "partial_evidence_preserved": True}
                try:
                    storage.write_json(operations / (token + ".FAILED.json"), failure)
                except (OSError, ValueError, RuntimeError):
                    print(json.dumps(failure), flush=True)
                raise


def main():
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True, choices=list(KINDS))
    for name in ("assets", "root", "freeze", "amendment", "amendment-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--seed", type=int, choices=[17, 29, 43])
    parser.add_argument("--protocol", default=str(Path(__file__).with_name("PROTOCOL.json")))
    parser.add_argument("--protocolR")
    parser.add_argument("--execute", action="store_true")
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
