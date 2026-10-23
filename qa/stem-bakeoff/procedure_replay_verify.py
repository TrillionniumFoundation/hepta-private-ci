"""Read-only artifact audit; reobserve retained output bytes, never rerun a selector.

Written after the frozen experiment. This verifies archive consistency and
accounting, not independent provenance or a new heldout qualification run.
"""

import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path
import tempfile

import numpy as np

from procedure_replay_contracts import sha
from procedure_replay_data import make_cases
from procedure_replay_observer import observe
from procedure_replay_probe import require_plan, write_json


MAX_MEMBER_BYTES = 16 * 1024 * 1024
MAX_EXPANDED_BYTES = 16 * 1024 * 1024


def archive_member(root, name):
    """Return a bounded regular file beneath the evidence root, without symlinks."""
    root = Path(root).resolve(strict=True)
    if type(name) is not str or not name or "\\" in name:
        raise ValueError("invalid archive member name")
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("archive member escaped evidence root")
    path = root / relative
    if not path.is_file() or path.stat().st_size > MAX_MEMBER_BYTES:
        raise ValueError("archive member missing or over byte budget")
    current = path
    while current != root:
        if current.is_symlink():
            raise ValueError("symlink archive member or ancestor")
        current = current.parent
    if not path.resolve(strict=True).is_relative_to(root):
        raise ValueError("archive member escaped evidence root")
    return path


def read_rows(path):
    with gzip.open(path, "rb") as stream:
        raw = stream.read(MAX_EXPANDED_BYTES + 1)
    if len(raw) > MAX_EXPANDED_BYTES:
        raise ValueError("expanded evidence exceeds byte budget")
    return [json.loads(line) for line in raw.splitlines()]


def verify(target, expected_plan_sha256):
    # This historical auditor still contains assertions. Optimized Python
    # must refuse verification rather than disable the audit and claim passed.
    if not __debug__:
        raise ValueError("optimized Python disables required archive audit assertions")
    target = Path(target).resolve(strict=True)
    plan = require_plan(target, expected_plan_sha256)
    result = json.loads(archive_member(target, "result.json").read_bytes())
    inventory = json.loads(archive_member(target, "inventory.json").read_bytes())
    for row in inventory:
        raw = archive_member(target, row["path"]).read_bytes()
        assert len(raw) == row["bytes"] and sha(raw) == row["sha256"], row["path"]
    snapshot = read_rows(archive_member(target, "source_snapshot.jsonl.gz"))
    assert {row["path"]: sha(row["utf8"].encode()) for row in snapshot} == plan["source_code_sha256"]
    assert all(row["sha256"] == sha(row["utf8"].encode()) for row in snapshot)
    encoder = json.loads(archive_member(target, "encoder_manifest.json").read_bytes())
    with np.load(archive_member(target, "pooled_features.npz"), allow_pickle=False) as archive:
        assert archive.files == ["pooled"]
        features = archive["pooled"]
        assert list(features.shape) == encoder["shape"] == [192, 384]
        assert features.dtype == np.float32 and np.isfinite(features).all()
        assert sha(features.tobytes()) == encoder["feature_bytes_sha256"]
    assert sha(archive_member(target, "pooled_features.npz").read_bytes()) == encoder["npz_sha256"]
    assert sum(row["model_forward_calls"] for row in encoder["receipts"]) == 24
    assert sum(row["batch_size"] for row in encoder["receipts"]) == 192
    cases = {case.query.query_id: case for case in make_cases()}
    files = [archive_member(target, "replay_attempts.jsonl.gz"),
             archive_member(target, "bm25_evaluation.jsonl.gz")]
    files += [archive_member(target, f"{arm}-{policy}.jsonl.gz") for arm in result["arms"]
              for policy in ("forced", "confidence_0.7")]
    totals, summaries = Counter(), {}
    for path in files:
        rows = read_rows(archive_member(target, path.name))
        observed = Counter()
        groups = defaultdict(Counter)
        keys = set()
        for row in rows:
            case = cases[row["query_id"]]
            key = (row["query_id"], row["choice"] if path.name == "replay_attempts.jsonl.gz" else None)
            assert key not in keys
            keys.add(key)
            assert row["input_family"] == case.query.input_family
            assert row["template_family"] == case.query.template_family
            assert row["split"] == case.query.split
            group = groups[(case.query.split, case.goal)]
            group["rows"] += 1
            if row.get("abstained", False):
                assert row["choice"] is None and row["execution"]["execution_calls"] == 0
                assert not row["observation"]["success"]
                observed["abstentions"] += 1
                group["abstentions"] += 1
                continue
            assert row["execution"]["execution_calls"] == 1
            with tempfile.TemporaryDirectory(prefix="hepta-procedure-archive-audit-") as directory:
                source, output = Path(directory) / "data.json", Path(directory) / "output.json"
                source.write_bytes(case.input_bytes)
                if row["observation"]["output_exists"]:
                    output.write_bytes(row["observation"]["output_utf8"].encode())
                actual = observe(case.goal, source, output, case.query.input_sha256)
                assert actual == row["observation"], (path.name, row["query_id"])
            success = int(actual["success"])
            observed["execution_calls"] += 1
            observed["successes"] += success
            observed["failed_executions"] += 1 - success
            observed["execution_errors"] += row["execution"]["execution_error"] is not None
            group["successes"] += success
            group["failed_executions"] += 1 - success
        totals.update(observed)
        summaries[path.name] = {"rows": len(rows), **observed,
            "by_split_contract": {split + "/" + goal: dict(value)
                                  for (split, goal), value in sorted(groups.items())}}
    assert totals["execution_calls"] == result["file_execution_accounting"]["total_actual_file_executions"]
    assert summaries["replay_attempts.jsonl.gz"]["execution_calls"] == 768
    assert summaries["bm25_evaluation.jsonl.gz"]["execution_calls"] == 96
    for arm, report in result["arms"].items():
        for policy, expected in report["evaluation"].items():
            actual = summaries[f"{arm}-{policy}.jsonl.gz"]["by_split_contract"]
            for split in ("development", "heldout"):
                successes = sum(value.get("successes", 0) for key, value in actual.items()
                                if key.startswith(split + "/"))
                assert successes == expected[split]["successes"]
        if arm.startswith("head_seed_"):
            assert report["training"]["optimizer_steps"] == 200 and report["reload_bit_exact"]
            assert report["training"]["changed_parameter_names"] == ["task_head.weight", "task_head.bias"]
            assert all(row["use_rejected"] for row in report["withdrawal"])
            assert [row["actual_head_module_calls"] for row in report["withdrawal"]] == [0, 0, 0, 1]
    return {"schema": "hepta.procedure-replay-archive-audit.v1", "status": "passed",
        "plan_sha256": expected_plan_sha256, "result_sha256": sha(archive_member(target, "result.json").read_bytes()),
        "auditor_sha256": sha(Path(__file__).read_bytes()), "inventory_files_verified": len(inventory),
        "source_closure_members_verified": len(snapshot), "totals": dict(totals), "files": summaries,
        "fresh_selector_encoder_or_procedure_executions": 0,
        "boundary": "Reopened retained output bytes and recomputed the frozen observer criterion; "
                    "this is archive consistency, not an independent execution provenance signer."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--expected-plan-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    audited = verify(args.evidence, args.expected_plan_sha256)
    write_json(args.output, audited)
    print(json.dumps({key: value for key, value in audited.items() if key != "files"}, indent=2))
