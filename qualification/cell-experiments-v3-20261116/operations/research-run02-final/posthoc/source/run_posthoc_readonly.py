"""Explicit posthoc readout. Preserve the original CLI, rules, artifacts and qualification scope."""
import argparse
import hashlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

WORKSPACE = Path("/dev/shm/hepta-cell-experiments-v3-20261116-0c078a")
FIX = WORKSPACE / "operations/research02-diagnostic-order-fix-01"
OUTPUT = WORKSPACE / "research-diagnostic-posthoc-02"
MANIFEST = FIX / "POSTHOC_RUN_MANIFEST.json"
BLOCKED = frozenset(("torch", "transformers", "peft"))
PATHS = {
    "original_source": "research-diagnostic-v1-source-02/qwen_research_diagnostic_v1.py",
    "original_rules": "research-diagnostic-v1-source-02/QWEN_RESEARCH_DIAGNOSTIC_FREEZE_02.json",
    "operation_freeze": "research-sft-02/FREEZE.json",
    "recorded_inputs": "research-sft-02/INPUTS.json",
    "original_diagnostic": "research-diagnostic-02/DIAGNOSTIC.json",
    "candidate_source": "operations/research02-diagnostic-order-fix-01/qwen_research_diagnostic_v1_order_fixed.py",
    "patch": "operations/research02-diagnostic-order-fix-01/ORDER_FIX.diff",
    "runner": "operations/research02-diagnostic-order-fix-01/run_posthoc_readonly.py",
    "fix_manifest": "operations/research02-diagnostic-order-fix-01/POSTHOC_FIX_MANIFEST.json",
    "regression": "operations/research02-diagnostic-order-fix-01/REGRESSION.json",
}
PINS = {
    "original_source": "28d82e170ab0720fb6b453275a80b4bf1eebc1e987ed1ae3bd935bb00a77a071",
    "original_rules": "f50ced9146611fc07c4638a35f204e94f1ebf0b5e6c4ab70ac9667095135c1bc",
    "operation_freeze": "50a6ad4c3e8088100cc84a047f0556b92294eb3e44dc644e62e2976137c2770a",
    "recorded_inputs": "691945696e7dad9ee0f3023617edf5ca0f787850c16f2623c08d14bc6cfbeaf3",
    "original_diagnostic": "662f575d3f01705fb13cb6e168ad5d7069a8ddcc81e484f0c515b63afd65236b",
    "candidate_source": "ce0b68cd98673bf15f170d1da7c42670f65320ba5c9d3cacc2f1c28696273821",
    "patch": "29c614601ac0e63d2c2d64bd0c99d817d41bdda065ae3982a1052d28dec819ad",
    "fix_manifest": "3373b6677feacba7206a0b5b545c2dc4cd743b9be12d5e23cdf22e2b1ceed7bd",
    "regression": "2e531b414b72382e7afb265179088158142d0de287caba0a69d54e42dfbef62e",
}
QUALIFICATION = {
    "scientific_confirmation_qualified": False, "native_cell_adoption": False,
    "proof_of_useful_work_eligible": False, "circuit_qualified": False,
    "new_C": False, "candidate_selected": None,
    "independent_sample_increment": 0, "external_teacher_count_added": 0, "new_users": 0,
}


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate manifest key")
            result[key] = value
        return result
    def nonfinite(value):
        raise ValueError("nonfinite manifest value")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


def bound_bytes(path, expected):
    require(path == path.resolve() and path.is_file() and not path.is_symlink(), "regular bound file required")
    require(path.is_relative_to(WORKSPACE), "bound file escaped workspace")
    require(not any(p in ("C", "confirmation") or ".sealed." in p or p.startswith("catalog-C") for p in path.parts),
            "forbidden evidence path")
    raw = path.read_bytes()
    require(sha(raw) == expected, "bound bytes changed: " + str(path))
    return raw


class RejectModelImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in BLOCKED:
            raise ImportError("model import forbidden in posthoc readout: " + fullname)
        return None


def deny_execution(event, args):
    if event == "subprocess.Popen" or event == "os.system" or event.startswith(("os.exec", "os.spawn", "os.posix_spawn")):
        raise PermissionError("child execution forbidden in read-only posthoc diagnostic")
    if event in ("socket.connect", "socket.connect_ex"):
        raise PermissionError("network execution forbidden in read-only posthoc diagnostic")
    if event == "open":
        path, mode, flags = args
        writing = (isinstance(mode, str) and any(x in mode for x in ("w", "a", "x", "+"))) or (
            isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
        if writing:
            require(isinstance(path, (str, bytes, os.PathLike)), "unbound writable descriptor rejected")
            target = Path(os.fsdecode(path)).absolute()
            require(target == target.resolve() and target.is_relative_to(OUTPUT), "write outside new output rejected")
    if event in ("os.remove", "os.rmdir", "os.rename", "os.mkdir", "os.chmod", "os.chown", "os.link", "os.symlink"):
        raise PermissionError("filesystem mutation forbidden after output admission")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args()
    require(sys.flags.isolated and sys.dont_write_bytecode, "launch with Python -I -B")
    require(Path(__file__).absolute() == FIX / "run_posthoc_readonly.py", "fixed runner path required")
    require(WORKSPACE == WORKSPACE.resolve() and FIX == FIX.resolve(), "fixed nonsymlink workspace required")
    require(not any(n.split(".")[0] in BLOCKED for n in sys.modules), "model module already loaded")
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    require(os.environ.get("CUDA_VISIBLE_DEVICES") == "", "CUDA visibility must be empty")
    sys.meta_path.insert(0, RejectModelImports())
    manifest = parse(bound_bytes(MANIFEST, args.manifest_sha256))
    require(manifest["schema"] == "hepta.diagnostic-order-posthoc-manifest.v1"
            and manifest["posthoc"] is True and manifest["status"] == "PREPARED_NOT_EXECUTED"
            and manifest["workspace"] == str(WORKSPACE)
            and manifest["output"] == str(OUTPUT)
            and set(manifest["bindings"]) == set(PATHS), "posthoc manifest identity differs")
    for key, relative in PATHS.items():
        item = manifest["bindings"][key]
        require(item["path"] == relative, "unexpected binding path")
        if key in PINS:
            require(item["sha256"] == PINS[key], "unexpected fixed evidence identity")
        bound_bytes(WORKSPACE / relative, item["sha256"])
    for key, expected in QUALIFICATION.items():
        actual = manifest.get(key)
        require(actual is expected if expected is None or type(expected) is bool
                else type(actual) is type(expected) and actual == expected, "manifest qualification differs")
    require(not OUTPUT.exists(), "new output already exists; no overwrite or automatic retry")
    OUTPUT.mkdir(exist_ok=False)
    sys.addaudithook(deny_execution)
    started = time.time_ns()
    module = None
    reader = None
    try:
        spec = importlib.util.spec_from_file_location("hepta_explicit_posthoc_order_fix", WORKSPACE / PATHS["candidate_source"])
        require(spec is not None and spec.loader is not None, "candidate loader missing")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        require(module.WORKSPACE == WORKSPACE, "candidate workspace differs")
        reader = module.Reader(WORKSPACE)
        reader.hash(MANIFEST, args.manifest_sha256)
        for key, relative in PATHS.items():
            reader.hash(WORKSPACE / relative, manifest["bindings"][key]["sha256"])
        rules = reader.read(WORKSPACE / PATHS["original_rules"], PINS["original_rules"])
        # These are the genuine original rules and source identity, not a relabelled new freeze.
        module.validate_rules(rules, PINS["original_source"])
        freeze = module.sealed(reader.read(WORKSPACE / PATHS["operation_freeze"], PINS["operation_freeze"]))
        original = module.sealed(reader.read(WORKSPACE / PATHS["original_diagnostic"], PINS["original_diagnostic"]))
        reader.read(WORKSPACE / PATHS["recorded_inputs"], PINS["recorded_inputs"])
        require(freeze["output"] == str(WORKSPACE / "research-sft-02")
                and freeze["inputs_path"] == str(WORKSPACE / PATHS["recorded_inputs"])
                and freeze["inputs_sha256"] == PINS["recorded_inputs"]
                and freeze["schema"] == "hepta.research-sft-freeze.v1"
                and freeze["status"] == "REFERENCE_ADMITTED"
                and freeze["diagnostic_freeze"] == {
                    "path": str(WORKSPACE / PATHS["original_rules"]), "sha256": PINS["original_rules"]},
                "original operation binding differs")
        require(original["freeze_digest"] == module.digest(freeze)
                and original["diagnostic_source_sha256"] == PINS["original_source"]
                and original["diagnostic_freeze_sha256"] == PINS["original_rules"],
                "original diagnostic binding differs")
        result = module.diagnose(reader, freeze, WORKSPACE / "research-sft-02")
        require(not any(n.split(".")[0] in BLOCKED for n in sys.modules), "model module imported")
        module.scope(result)
        inventory = reader.recheck()
        binding = {"schema": "hepta.research-diagnostic-read-inventory.v1", "files": inventory,
                   "file_count": len(inventory), "scope": "posthoc exact selected reads and rehash; no new tasks or atomic snapshot claim"}
        module.write_new(OUTPUT / "INPUT_BINDINGS.json", binding)
        result.update(diagnostic_freeze_sha256=PINS["original_rules"],
                      diagnostic_source_sha256=PINS["candidate_source"],
                      original_diagnostic_sha256=PINS["original_diagnostic"],
                      original_diagnostic_source_sha256=PINS["original_source"],
                      posthoc=True, posthoc_manifest_sha256=args.manifest_sha256,
                      input_bindings_digest=module.digest(binding), completed_at_ns=time.time_ns())
        module.write_new(OUTPUT / "DIAGNOSTIC.json", {**result, "receipt_sha256": module.digest(result)})
        receipt = {"schema": "hepta.diagnostic-order-posthoc-receipt.v1", "status": "POSTHOC_READOUT_COMPLETE_UNQUALIFIED",
                   "posthoc": True, "manifest_sha256": args.manifest_sha256,
                   "input_bindings_sha256": sha((OUTPUT / "INPUT_BINDINGS.json").read_bytes()),
                   "diagnostic_sha256": sha((OUTPUT / "DIAGNOSTIC.json").read_bytes()),
                   "original_diagnostic_sha256": PINS["original_diagnostic"],
                   "original_rules_source_sha256": PINS["original_source"],
                   "derived_source_sha256": PINS["candidate_source"], "patch_sha256": PINS["patch"],
                   "original_rules_modified": False, "original_output_overwritten": False,
                   "diagnostic_model_calls": 0, "diagnostic_verifier_calls": 0, "new_independent_observations": 0,
                   "started_at_ns": started, "completed_at_ns": time.time_ns(), **QUALIFICATION}
        module.write_new(OUTPUT / "POSTHOC_RECEIPT.json", {**receipt, "receipt_sha256": module.digest(receipt)})
        print(json.dumps({"status": receipt["status"], "output": str(OUTPUT),
                          "posthoc_receipt_sha256": sha((OUTPUT / "POSTHOC_RECEIPT.json").read_bytes())}), flush=True)
    except BaseException as error:
        failure = {"schema": "hepta.diagnostic-order-posthoc-failure.v1", "status": "POSTHOC_FAILED_PRESERVED",
                   "error": repr(error), "manifest_sha256": args.manifest_sha256,
                   "read_files": reader.observed if reader else {}, "automatic_retry": False, **QUALIFICATION}
        with (OUTPUT / "FAILED.json").open("xb") as stream:
            stream.write(json.dumps(failure, sort_keys=True, separators=(",", ":")).encode() + b"\n")
        raise


if __name__ == "__main__":
    main()
