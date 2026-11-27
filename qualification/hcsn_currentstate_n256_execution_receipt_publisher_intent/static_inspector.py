"""Static fail-closed inspection for the execution-receipt publisher source."""

import argparse
import ast
import hashlib
import json
from pathlib import Path


FORBIDDEN_IMPORTS = {"numpy", "scipy", "torch", "subprocess", "multiprocessing"}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inspect(publisher_path, request_path):
    source = Path(publisher_path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(publisher_path))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    if imports & FORBIDDEN_IMPORTS:
        raise ValueError("publisher imports numerical or execution dependencies")
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    if names & {"exec", "eval", "compile", "open"}:
        raise ValueError("publisher contains an execution or unbounded file primitive")

    request = json.loads(Path(request_path).read_text())
    if request["numerical_execution_allowed"] is not False:
        raise ValueError("numerical execution enabled")
    if request["execution_key"] is not None:
        raise ValueError("source intent contains an execution key")
    if request["execution_receipt_output_sha256"] is not None:
        raise ValueError("source intent claims an output")
    unresolved = (
        *request["required_external_originals"].values(),
        *request["required_process_facts"].values(),
    )
    if any(value is not None for value in unresolved):
        raise ValueError("source intent claims an external original or process fact")
    if request["historical_negative_and_unknown_preserved"] is not True:
        raise ValueError("historical RED/UNKNOWN erased")
    if request["largegrid_qualification"] is not False:
        raise ValueError("source intent grants qualification")
    if request["production_adoption"] is not False or request["all_closed"] is not False:
        raise ValueError("source intent grants adoption or closure")
    return {
        "schema": "hcsn-n256-execution-receipt-publisher-source-inspection-v1",
        "publisher_sha256": _sha(publisher_path),
        "request_sha256": _sha(request_path),
        "external_originals_present": 0,
        "process_facts_present": 0,
        "authentic_receipts_published": 0,
        "dynamic_runs": 0,
        "matrix_exponential_actions": 0,
        "oracle_calls": 0,
        "provider_calls": 0,
        "serializer_calls": 0,
        "torch_calls": 0,
        "optimizer_steps": 0,
        "largegrid_qualification": False,
        "all_closed": False,
        "status": "PASS_EXECUTION_RECEIPT_PUBLISHER_SOURCE_HOLD",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--publisher", required=True)
    parser.add_argument("--request", required=True)
    arguments = parser.parse_args()
    print(json.dumps(inspect(arguments.publisher, arguments.request), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
