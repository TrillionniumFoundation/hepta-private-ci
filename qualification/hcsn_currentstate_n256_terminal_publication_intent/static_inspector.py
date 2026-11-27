"""Static zero-execution inspection for the terminal publication bridge."""

import argparse
import ast
import hashlib
import json
from pathlib import Path


FORBIDDEN_IMPORTS = {"numpy", "scipy", "torch", "subprocess", "multiprocessing"}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inspect(source_path, request_path):
    source = Path(source_path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    if imports & FORBIDDEN_IMPORTS:
        raise ValueError("terminal bridge imports execution or numerical dependencies")
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    if names & {"exec", "eval", "compile", "open"}:
        raise ValueError("terminal bridge contains an execution or unbounded file primitive")

    request = json.loads(Path(request_path).read_text())
    if any(value is not None for value in request["future_originals"].values()):
        raise ValueError("source intent claims a future original")
    for field in ("execution_key", "terminal_publication_sha256"):
        if request[field] is not None:
            raise ValueError(f"source intent silently populated {field}")
    if request["numerical_execution_allowed"] is not False:
        raise ValueError("source intent enables numerical execution")
    if request["historical_negative_and_unknown_preserved"] is not True:
        raise ValueError("source intent erased historical RED/UNKNOWN")
    if request["largegrid_qualification"] is not False:
        raise ValueError("source intent grants qualification")
    if request["production_adoption"] is not False or request["all_closed"] is not False:
        raise ValueError("source intent grants adoption or closure")
    return {
        "schema": "hcsn-n256-terminal-publication-source-inspection-v1",
        "source_sha256": _sha(source_path),
        "request_sha256": _sha(request_path),
        "authentic_terminal_originals": 0,
        "authentic_publications": 0,
        "provider_calls": 0,
        "dynamic_runs": 0,
        "matrix_exponential_actions": 0,
        "oracle_calls": 0,
        "serializer_calls": 0,
        "torch_calls": 0,
        "optimizer_steps": 0,
        "largegrid_qualification": False,
        "all_closed": False,
        "status": "PASS_TERMINAL_PUBLICATION_SOURCE_HOLD",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--request", required=True)
    arguments = parser.parse_args()
    print(json.dumps(inspect(arguments.source, arguments.request), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
