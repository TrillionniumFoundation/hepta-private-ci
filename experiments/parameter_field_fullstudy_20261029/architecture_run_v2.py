"""Attempt02 C training: unchanged scientific main, explicit operational store.

Imports Torch only after registered memory admission. The new training freeze
is the actual checkpoint ancestor and retains the complete original scientific
source closure. This is a fresh fixed-design attempt, not lost-state recovery.
"""

import argparse
import importlib
import json
from pathlib import Path
import resource
import sys
import time

from .run_v2 import ROOT, ensure_loaded_closure, file_hash, require, scoped_runner, verify_files


def validate_freeze(args, registration):
    from .endpoint_v2 import parent_freeze
    freeze = json.loads(Path(args.freeze).read_text())
    descriptor = {"path": str(Path(args.freeze).resolve()), "sha256": file_hash(args.freeze),
                  "registered_commit": freeze["registered_commit"], "protocol_sha256": freeze["protocol_sha256"],
                  "source_root": str(ROOT)}
    parent_freeze("C", descriptor, registration)
    require(Path(args.root).resolve() == Path(registration["raw_root"]).resolve(), "C run root differs from attempt02 registration")
    require(file_hash(args.protocol) == freeze["protocol_sha256"], "C scientific protocol bytes differ")
    verify_files(freeze, ROOT)
    prefix = Path(__file__).resolve().parent.relative_to(ROOT)
    required = ("architecture_run_v2.py", "architecture_run.py", "architecture_store.py", "endpoint_v2.py",
                "resource_v2.py", "resource_io_v2.py", "run_v2.py")
    require(all((prefix / name).as_posix() in freeze["source_files"] for name in required), "C operational dependency closure is not frozen")
    return freeze


def store_type(original, storage):
    class RegisteredEvidenceStore(original):
        def __init__(self, root, work, raw_root=None):
            require(raw_root is not None and Path(raw_root).resolve() == storage.root, "C storage root differs from registration")
            require(Path(root).resolve() == storage.root / "stage_C", "C stage directory differs")
            super().__init__(root, work, raw_root=raw_root, cap_bytes=350 * 1024 ** 2,
                             global_cap_bytes=storage.cap, reserve_bytes=storage.reserve,
                             cpu_limit=43200, wall_limit=21600, microstep_limit=57536)

        def check(self, additional=0, failure_record=False):
            with storage.writer_lock():
                storage.check(additional=additional, c_training=True, check_memory=not failure_record)
                return super().check(additional=additional, failure_record=failure_record)
    return RegisteredEvidenceStore


def execute(args):
    require(args.execute, "Explicit attempt02 C training execution is required")
    from .resource_v2 import StorageBudget, load_registration, training_slot
    from .resource_io_v2 import guarded_writes
    registration = load_registration(args.amendment, args.amendment_sha256)
    freeze = validate_freeze(args, registration)
    root = Path(args.root).resolve()
    require(root.is_dir(), "Registered raw root must already exist")
    storage = StorageBudget(root, registration)
    provenance = {"schema": "hepta.fullstudy.training-operation.2", "attempt_id": "attempt02", "phase": "C", "seed": None,
                  "execution_kind": "training", "operational_amendment_sha256": registration["_sha256"],
                  "source_freeze_sha256": file_hash(args.freeze), "registered_commit": freeze["registered_commit"],
                  "scientific_parent": freeze["scientific_parent"], "scientific_protocol_sha256": freeze["protocol_sha256"],
                  "override_scope": "Scoped EvidenceStore resource limits and guarded persistence; original scientific main unchanged.",
                  "original_1GiB_2GiB_reserve_contract_completed": False,
                  "attempt01_raw_recovered": False, "scientific_source_bytes_unchanged": True}
    operations = root / "operations"
    with training_slot(root, registration), guarded_writes(storage):
        storage.check()
        operations.mkdir(exist_ok=True)
        storage.write_json(operations / "C-all.START.json", {**provenance, "complete": False, "started_unix": time.time()})
        try:
            core = importlib.import_module(__package__ + ".architecture_run")
            ensure_loaded_closure(freeze)
            argv = ["--assets", args.assets, "--root", args.root, "--reference-root", args.reference_root,
                    "--freeze", args.freeze, "--protocol", args.protocol, "--execute"]
            with scoped_runner(core, "EvidenceStore", store_type(core.EvidenceStore, storage), argv):
                core.main()
            target = root / "stage_C/COMPLETE.json"
            result = json.loads(target.read_text())
            require(result.get("complete") is True and result.get("training_complete") is True
                    and result["binding"]["source_freeze_sha256"] == file_hash(args.freeze)
                    and result["binding"]["registered_commit"] == freeze["registered_commit"], "Original C runner did not seal this attempt")
            storage.check(c_training=True)
            receipt = {**provenance, "complete": True, "completed_unix": time.time(),
                       "process_peak_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024,
                       "scientific_complete": {"path": target.relative_to(root).as_posix(), "bytes": target.stat().st_size,
                                               "sha256": file_hash(target)}, "post_execution_storage_check": True}
            storage.write_json(operations / "C-all.COMPLETE.json", receipt)
            print(json.dumps({"operational_complete": True, "phase": "C"}), flush=True)
            return receipt
        except BaseException as error:
            failed = {**provenance, "complete": False, "error_type": type(error).__name__, "message": str(error),
                      "partial_evidence_preserved": True}
            try:
                storage.write_json(operations / "C-all.FAILED.json", failed)
            except (OSError, ValueError, RuntimeError):
                print(json.dumps(failed), flush=True)
            raise


def main():
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser()
    for name in ("assets", "root", "reference-root", "freeze", "protocol", "amendment", "amendment-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--execute", action="store_true")
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
