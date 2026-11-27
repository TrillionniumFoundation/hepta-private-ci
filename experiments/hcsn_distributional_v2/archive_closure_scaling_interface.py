"""Targeted actual scaling producer/closure consumer contract check; stdlib only."""

import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import sys

from .archive_closure import ClosureAudit, PACKAGE, file_hash, read_json, require, write_new


def run(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    package = output / "synthetic_fixture/experiments/hcsn_distributional_v2"
    package.mkdir(parents=True)
    root = package.parents[1]
    snapshots = output / "source"
    snapshots.mkdir()
    protocol_path = PACKAGE / "SCALING001_PROTOCOL.json"
    protocol = read_json(protocol_path)
    source_before = file_hash(PACKAGE / "scaling_eval.py")
    spec = importlib.util.spec_from_file_location("actual_scaling_producer_contract", PACKAGE / "scaling_eval.py")
    producer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(producer)
    require("torch" not in sys.modules and "numpy" not in sys.modules, "Interface check unexpectedly imported a numerical runtime")
    actual = producer.cases()
    require(len(actual) == 30 and len({case["case_id"] for case in actual}) == 30, "Actual producer did not return 30 unique cases")
    registered = {case["case_id"]: case for case in protocol["cases"]}
    require({case["case_id"] for case in actual} == set(registered), "Registered cases differ from actual producer")
    require(all(all(registered[case["case_id"]][key] == value for key, value in case.items()) for case in actual),
            "Actual producer coordinates differ from its registration")
    require(set(producer.MODELS) == {"distribution_free_dual", "two_gates", "transformer"}, "Wrong scaling comparison models")
    for relative, expected in protocol["source_files_sha256"].items():
        original, destination = PACKAGE.parents[1] / relative, root / relative
        require(file_hash(original) == expected, "Registered producer source changed")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, destination)
    for name in ("evidence_bundle.py", "seal_bundle.py", "content_checkpoint_archives.py", "archive_closure.py"):
        shutil.copyfile(PACKAGE / name, package / name)
        shutil.copyfile(PACKAGE / name, snapshots / name)
    shutil.copyfile(PACKAGE / "scaling_eval.py", snapshots / "scaling_eval.py")
    shutil.copyfile(__file__, snapshots / "archive_closure_scaling_interface.py")
    shutil.copyfile(protocol_path, package / "SCALING001_PROTOCOL.json")
    digest = file_hash(protocol_path)
    study = package / "results/scaling001"
    rows = []
    for index, case in enumerate(protocol["cases"]):
        directory = study / "cases" / case["case_id"]
        directory.mkdir(parents=True)
        code = 1 if index == 0 else 0
        identity = dict(case_id=case["case_id"], protocol_sha256=digest,
                        source_files_sha256=protocol["source_files_sha256"], constructor=producer.constructor(case),
                        actual_counts=None if code else case["registered_counts"],
                        status="failed_before_identity" if code else "synthetic_fixture", synthetic_fixture=True)
        write_new(directory / "IDENTITY.json", identity)
        receipt = dict(case_id=case["case_id"], protocol_sha256=digest, source_files_sha256=protocol["source_files_sha256"],
                       returncode=code, synthetic_fixture=True)
        write_new(directory / "EXECUTION.json", receipt)
        write_new(directory / ("FAILURE.json" if code else "RESULT.json"), dict(synthetic_fixture=True))
        rows.append(dict(**{key: case[key] for key in ("case_id", "model", "batch", "length", "width", "depth")},
            protocol_sha256=digest, source_files_sha256=protocol["source_files_sha256"], returncode=code,
            receipt_path=str((directory / "EXECUTION.json").relative_to(package))))
    complete = study / "COMPLETE.json"
    write_new(complete, dict(schema="hcsn-v2-scaling-complete.v1", status="completed", expected_cases=30,
        completed_cases=30, successful_cases=29, failed_cases=1, all_cases_successful=False,
        protocol_sha256=digest, source_files_sha256=protocol["source_files_sha256"], records=rows, synthetic_fixture=True))
    write_new(study / "SUITE_EXECUTION.json", dict(returncode=0, protocol_sha256=digest,
        source_files_sha256=protocol["source_files_sha256"], complete_receipt_sha256=file_hash(complete),
        complete_child_cpu_seconds=0.0, synthetic_fixture=True))
    checked = ClosureAudit(package).audit_scaling()
    require(len(checked["cases"]) == 30 and checked["successful"] == 29 and checked["failed"] == 1,
            "Correct producer grid did not pass the scaling contract")
    original = (package / "SCALING001_PROTOCOL.json").read_bytes()
    wrong = json.loads(original)
    for case in wrong["cases"]:
        if case["model"] == "two_gates":
            case["model"] = "lif_snn"
            case["case_id"] = case["case_id"].replace("two_gates_", "lif_snn_", 1)
    (package / "SCALING001_PROTOCOL.json").write_text(json.dumps(wrong))
    rejection = None
    try:
        ClosureAudit(package).audit_scaling()
    except ValueError as error:
        require("30-configuration diagnostic grid" in str(error), "Wrong rejection for old consumer model assumption")
        rejection = str(error)
    finally:
        (package / "SCALING001_PROTOCOL.json").write_bytes(original)
    require(rejection is not None, "Old LIF scaling substitution was not rejected")
    require(file_hash(PACKAGE / "scaling_eval.py") == source_before, "Producer source changed during interface validation")
    result = dict(schema="hcsn-archive-closure-scaling-interface.v1", status="passed", synthetic_fixture_only=True,
        source_sha256={path.name: file_hash(path) for path in snapshots.glob("*.py")},
        actual_protocol_sha256=digest, producer_models=list(producer.MODELS), actual_registered_cases=len(actual),
        consumer_checked_cases=len(checked["cases"]), preserved_negative_case=True,
        former_lif_substitution_rejected=rejection, numeric_runtime_imported=False,
        formal_artifacts_modified=False, real_final_closure_executed=False,
        scope="Only the actual registered producer cases/constructor metadata and closure scaling consumer interface; seven-bundle end-to-end fixture was not rerun; no benchmark or content data executed")
    write_new(output / "RESULTS.json", result)
    print(json.dumps({key: result[key] for key in ("status", "producer_models", "actual_registered_cases", "real_final_closure_executed")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.output)
