"""AST-limited recovery review and repeated old-validation /tmp execution."""

import argparse
import ast
from copy import deepcopy
import gzip
import io
import json
from pathlib import Path
import tempfile

import numpy as np

from ..field_bridge_20261027.run import setup
from ..v6.data import make_batch
from ..field_bridge_v2_20261027.learning import make_model
from ..field_bridge_v2_20261027.native_fast import NativeFastBridge
from ..field_bridge_v2_20261027.primary_common import P
from ..field_bridge_v2_20261027.primary_evaluate import deploy_batch
from ..field_bridge_v2_20261027.primary_media import MediaStore
from ..field_bridge_v2_20261027.primary_runtime import fit_controllers
from .primary_recovery_parity import file_sha, identity, complete_records, verify_one


def ast_review():
    here = Path(__file__).parent
    original_path = here.parent/"field_bridge_v2_20261027"/"primary_evaluate.py"
    recovery_path = here/"primary_io_recovery.py"
    original = {n.name: n for n in ast.parse(original_path.read_text()).body if isinstance(n, ast.FunctionDef)}
    recovered = {n.name: n for n in ast.parse(recovery_path.read_text()).body if isinstance(n, ast.FunctionDef)}
    expression = lambda code: ast.parse(code, mode="eval").body
    completion_additions = {
        "registered_recovery_commit": "args.recovery_commit", "recovery_source_sha256": "digest(__file__)"}
    analysis_additions = {"evaluation_subdirectory": "'eval_recovered'", "original_attempt": "'eval'",
        "recovery_source_sha256": "digest(__file__)", "registered_recovery_commit": "args.recovery_commit",
        "recovery_registration_sha256": "digest(root/'IO_RECOVERY_REGISTRATION.json')",
        "original_attempt_counts": "recovery['partial_attempt_counts']",
        "repeated_execution_interpretation": repr("Same frozen decisions and RNG after an I/O fault; one statistical grid, no extra independent replicate")}
    for name in ("evaluate", "analyze"):
        target = deepcopy(original[name])
        for node in list(ast.walk(target)):
            if isinstance(node, ast.Constant) and node.value == "eval":
                node.value = "eval_recovered"
            if isinstance(node, ast.Constant) and node.value == "Primary evidence changed":
                node.value = "Recovered primary evidence changed"
            if isinstance(node, ast.ImportFrom) and node.module == "primary_analyze":
                node.module, node.level = "field_bridge_v2_20261027.primary_analyze", 2
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "deploy_batch":
                    node.args[9] = expression('Path(tempfile.mkdtemp(prefix=f"hepta-primary-{seed}-",dir="/tmp"))')
                if node.func.id == "write_json":
                    additions = completion_additions if name == "evaluate" else analysis_additions
                    # analyze also writes RESULT.json; only completion dictionaries change.
                    if isinstance(node.args[1], ast.Dict):
                        position = ([key.value for key in node.args[1].keys].index("registered_pretest_commit")+1
                                    if name == "evaluate" else len(node.args[1].keys))
                        for key, value in additions.items():
                            node.args[1].keys.insert(position, ast.Constant(key))
                            node.args[1].values.insert(position, expression(value))
                            position += 1
        if name == "evaluate":
            target.body.insert(0, ast.parse("verify_recovery(args)").body[0])
        else:
            target.body.insert(2, ast.parse("recovery=verify_recovery(args)").body[0])
        assert ast.dump(target, include_attributes=False) == ast.dump(recovered[name], include_attributes=False), \
            "Recovery exceeds the explicitly allowed storage/provenance AST changes: "+name
    return {"frozen_evaluator_sha256": file_sha(original_path), "recovery_wrapper_sha256": file_sha(recovery_path),
            "verified_functions": ["evaluate", "analyze"], "method": "AST equality after an explicit storage/provenance-only edit whitelist"}


def parser_contract(directory):
    first = {"seed": 17, "value": .2, "wall_ns": 1, "decision": {"committed_monotonic_ns": 4, "action": "stop"},
             "decision_bytes_utf8": "original", "decision_sha256": "original"}
    second = {**first, "wall_ns": 9, "decision": {"committed_monotonic_ns": 8, "action": "stop"},
              "decision_bytes_utf8": "recovered", "decision_sha256": "recovered"}
    assert identity(first, row=True) == identity(second, row=True)
    assert identity(first, row=True) != identity({**second, "value": .3}, row=True)
    full = gzip.compress((json.dumps(first)+"\n").encode())
    old, new = directory/"synthetic-original.jsonl.gz", directory/"synthetic-recovered.jsonl.gz"
    old.write_bytes(full[:-8])
    new.write_bytes(gzip.compress((json.dumps(second)+"\n").encode()))
    result = verify_one(old, new, "rows", lambda row: row["seed"])
    assert result["exact_matches"] == 1 and not result["original"]["gzip_stream_complete"]
    new.write_bytes(gzip.compress((json.dumps({**second, "value": .3})+"\n").encode()))
    try:
        verify_one(old, new, "rows", lambda row: row["seed"])
    except ValueError:
        pass
    else:
        raise AssertionError("Scientific change accepted by recovery parity")
    return ["timing_only_changes_allowed", "scientific_value_change_rejected", "complete_rows_in_truncated_gzip_preserved"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", required=True)
    parser.add_argument("--native", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    ast_checks = ast_review()
    guards = parser_contract(args.out)
    corpus, observers, originals, _ = setup(args, audit=True)
    batch = make_batch(corpus, "validation", 8, 271027, offset=700, corruption="clean")
    model = make_model(originals[17], 17, P["recipe"])
    rng = np.random.default_rng(271031)
    def synthetic(n, role):
        x0, x1 = rng.random((n, 8)), rng.random((n, 8))
        returns = np.column_stack((x0[:, 0], x1[:, 1], x0[:, 2]+x1[:, 2], x1[:, 3], x0[:, 4]))*.2
        return dict(x0=x0, x1=x1, returns=returns, role=role)
    media, temporary_paths, cases = MediaStore(args.out/"media.zip"), [], {}
    with NativeFastBridge(args.native, P["native_library_sha256"]) as bridge:
        fitted = fit_controllers(synthetic(32, "train"), synthetic(16, "development"), bridge, "recovery-contract")
        for control in ("fixed", "native", "history", "reset"):
            runs = []
            for attempt in range(2):
                temporary = Path(tempfile.mkdtemp(prefix="hepta-primary-contract-", dir="/tmp"))
                temporary_paths.append(str(temporary))
                rows, native = io.StringIO(), io.StringIO()
                readout = None if control == "fixed" else fitted["models"]["native" if control == "reset" else control]
                count = deploy_batch(model, readout, control, 4, bridge, observers, batch, 17*100003,
                    dict(seed=17, arm="contract_"+control, split="validation", corruption="clean", batch_start=0, batch_seed=271027),
                    temporary, media, rows, native)
                assert count == 8 and not temporary.exists()
                runs.append(([json.loads(line) for line in rows.getvalue().splitlines()],
                             [json.loads(line) for line in native.getvalue().splitlines()]))
            assert [identity(r, row=True) for r in runs[0][0]] == [identity(r, row=True) for r in runs[1][0]]
            assert [identity(r) for r in runs[0][1]] == [identity(r) for r in runs[1][1]]
            cases[control] = {"rows_per_attempt": 8, "same_scientific_rows": True,
                              "same_complete_native_receipts": True, "native_receipts_per_attempt": len(runs[0][1])}
    storage = media.close()
    assert len(temporary_paths) == len(set(temporary_paths)) == 8
    result = {"schema": "hepta.field-bridge.v2.primary-io-recovery-contract.1", "passed": True,
        "ast_review": ast_checks, "parity_parser_guards": guards, "actual_repeated_old_validation": cases,
        "temporary_path_parent": "/tmp", "unique_temporary_paths": 8, "temporary_paths_removed": True,
        "old_validation_source_ids": batch.source_ids, "reserved_test_retention_loaded_or_scored": False,
        "original_partial_attempt_rows_or_outcomes_read": False, "media": storage,
        "script_sha256": file_sha(Path(__file__)),
        "parity_verifier_sha256": file_sha(Path(__file__).with_name("primary_recovery_parity.py"))}
    (args.out/"PRIMARY_IO_RECOVERY_CONTRACT.json").write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    print(json.dumps({"passed": True, "ast_functions": 2, "repeated_old_validation_rows": 64, "unique_tmp_directories": 8}))


if __name__ == "__main__":
    main()
