"""Check frozen dependencies before importing an unchanged media formal entrypoint."""

import argparse
import json
from pathlib import Path
import runpy
import sys
import time
import traceback

from .build import save, sha


BASE_MODULE = "experiments.multimodal_output_portfolio.next_20261025.media.repair.bridge_v2"


def verify(path, expected):
    if sha(path) != expected:
        raise ValueError("Dependency identity changed: " + str(path))


def validate(manifest_path, manifest_sha256):
    verify(manifest_path, manifest_sha256)
    manifest = json.loads(manifest_path.read_text())
    if manifest["schema"] != "hepta.next.media-dependency-continuity.v1":
        raise ValueError("Wrong dependency continuity schema")
    for mapping in (manifest["frozen_evidence_sha256"], manifest["frozen_guard_sha256"]):
        for path, expected in mapping.items():
            verify(path, expected)
    for row in manifest["source_closure"]:
        verify(row["path"], row["sha256"])
    protocol = json.loads(Path(manifest["qualification_protocol"]).read_text())
    for path, expected in protocol["frozen_candidate_sha256"].items():
        verify(path, expected)
    return manifest


def invoke(module, arguments):
    previous = sys.argv
    sys.argv = [module, *arguments]
    try:
        runpy.run_module(module, run_name="__main__")
    finally:
        sys.argv = previous


def pins_for(manifest, manifest_path):
    pins = {row["path"]: row["sha256"] for row in manifest["source_closure"]}
    pins.update(manifest["frozen_evidence_sha256"])
    pins.update(manifest["frozen_guard_sha256"])
    pins[str(manifest_path.resolve())] = sha(manifest_path)
    return pins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--receipt", required=True, type=Path)
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("check")
    freezing = commands.add_parser("freeze")
    for name in ("development", "qualification", "allocation", "base-output", "output"):
        freezing.add_argument("--" + name, required=True, type=Path)
    evaluation = commands.add_parser("evaluate")
    evaluation.add_argument("--protocol", required=True, type=Path)
    evaluation.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.receipt.exists():
        raise ValueError("Never overwrite a guard receipt")
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    started = time.time_ns()
    state = {"schema": "hepta.next.media-dependency-guard.v1", "operation": args.operation,
             "manifest": str(args.manifest.resolve()), "manifest_sha256": args.manifest_sha256,
             "started_unix_ns": started, "candidate_module_imported": False}
    try:
        manifest = validate(args.manifest, args.manifest_sha256)
        pins = pins_for(manifest, args.manifest)
        state["pre_import_dependencies_verified"] = True
        if args.operation == "freeze":
            if args.output.exists() or args.base_output.exists():
                raise ValueError("Never overwrite a confirmation protocol")
            if args.qualification.resolve() != Path(manifest["qualification_output"]) / "summary.json":
                raise ValueError("Actual qualification result does not belong to the bound execution")
            process_receipt = Path(manifest["qualification_process_receipt"])
            completed = json.loads(process_receipt.read_text())
            if completed["returncode"] != 0 or completed["ended_unix_ns"] < manifest["qualification_child_start_unix_ns"]:
                raise ValueError("Qualification child has not completed successfully")
            args.base_output.parent.mkdir(parents=True, exist_ok=True)
            state["candidate_module_imported"] = True
            invoke(BASE_MODULE + ".freeze", ["--development", str(args.development), "--qualification", str(args.qualification),
                    "--allocation", str(args.allocation), "--output", str(args.base_output)])
            validate(args.manifest, args.manifest_sha256)
            original = json.loads(args.base_output.read_text())
            pins[str(args.base_output.resolve())] = sha(args.base_output)
            pins[str(process_receipt)] = sha(process_receipt)
            for path, expected in pins.items():
                if path in original["frozen_candidate_sha256"] and original["frozen_candidate_sha256"][path] != expected:
                    raise ValueError("Original confirmation and continuity pins disagree")
            result = dict(original)
            result["frozen_candidate_sha256"] = dict(original["frozen_candidate_sha256"], **pins)
            result["dependency_continuity"] = {"manifest": str(args.manifest.resolve()), "sha256": args.manifest_sha256,
                    "base_protocol": str(args.base_output.resolve()), "base_protocol_sha256": sha(args.base_output),
                    "original_numeric_and_scientific_fields_unchanged": True,
                    "guard_module": __spec__.name, "registered_unix_ns": time.time_ns()}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            save(args.output, result)
            state["final_protocol_sha256"] = sha(args.output)
        elif args.operation == "evaluate":
            protocol = json.loads(args.protocol.read_text())
            continuity = protocol["dependency_continuity"]
            if continuity["sha256"] != args.manifest_sha256 or Path(continuity["manifest"]).resolve() != args.manifest.resolve():
                raise ValueError("Formal protocol binds a different continuity manifest")
            for path, expected in pins.items():
                if protocol["frozen_candidate_sha256"].get(path) != expected:
                    raise ValueError("Formal protocol omits a continuity dependency")
            for path, expected in protocol["frozen_candidate_sha256"].items():
                verify(path, expected)
            arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
            flags = [value for value in arguments if value.startswith("--")]
            if len(flags) != len(set(flags)) or any(value in flags for value in ("--protocol", "--phase")):
                raise ValueError("Duplicate or overridden formal phase/protocol argument")
            state["candidate_module_imported"] = True
            state["protocol_sha256"] = sha(args.protocol)
            invoke(BASE_MODULE + ".evaluate", [*arguments, "--phase", "confirmation", "--protocol", str(args.protocol)])
        validate(args.manifest, args.manifest_sha256)
        state["post_execution_dependencies_verified"] = True
        state["status"] = "passed"
    except BaseException as error:
        state["status"] = "rejected"
        state["error"] = repr(error)
        state["traceback"] = traceback.format_exc()
        raise
    finally:
        state["ended_unix_ns"] = time.time_ns()
        save(args.receipt, state)
    print(json.dumps({"status": state["status"], "operation": args.operation, "receipt_sha256": sha(args.receipt)}))


if __name__ == "__main__":
    main()
