"""Build honest development test-completion records from reviewed repo fixtures."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import time

from . import data, repo_execution


def write_new(path, value):
    raw = data.canonical(value) + b"\n"
    with Path(path).open("xb") as stream:
        stream.write(raw)
    return hashlib.sha256(raw).hexdigest()


def _reference(record, answer, output, phase):
    result = data.verify_answer(record, answer)
    with (output / "REFERENCE_ATTEMPTS.jsonl").open("ab") as stream:
        stream.write(data.canonical({"phase": phase, "receipt": result}) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    return result


def _observed(result):
    actual = result["result"]
    measured = actual.get("result") or {}
    return data.canonical(
        {
            "success": result["success"],
            "executed": actual["executed"],
            "assertions": actual.get("assertions", 0),
            "original_passed": measured.get("original_passed", False),
            "controls_rejected": actual["controls_rejected"],
            "control_count": measured.get("control_count", 0),
            "receipt_sha256": result["receipt_sha256"],
            "next_attempt_resets_template": True,
            "full_repository_integration": False,
        }
    ).decode()


def build(panel, output):
    """Execute authored reference assertions; never invent external agent traces."""
    if panel not in ("open", "confirmation", "warmup", "diagnostic-c", "diagnostic-d"):
        raise ValueError("unknown task panel")
    specs = json.loads((repo_execution.FIXTURES / f"specs-{panel}.json").read_bytes())
    if panel == "confirmation":
        # Custodian-only preparation validates reference contracts before student
        # selection. It grants no candidate evaluation access or independent role.
        repo_execution._CONFIRMATION = {"custodian_reference_preparation": True}
        repo_execution.load_catalog("confirmation")
    elif panel in ("diagnostic-c", "diagnostic-d"):
        repo_execution.load_catalog("diagnostic")
    else:
        repo_execution.load_catalog()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write_new(
        output / "STARTED.json", {"panel": panel, "started_at_ns": time.time_ns()}
    )
    records, receipts, partial_receipts = [], [], []
    observed = time.time_ns() // 1_000_000_000
    for spec in specs:
        fixture = repo_execution._CATALOG[spec["fixture_id"]]
        source = fixture["source"]
        answer = data.canonical(
            {
                "edits": [
                    {
                        "path": "test_contract.py",
                        "old": "    pass",
                        "new": spec["assertions"],
                    }
                ]
            }
        ).decode()
        verifier = {
            "name": "repo_patch",
            "version": "1",
            "parameters": {
                "fixture_id": fixture["fixture_id"],
                "fixture_sha256": data.digest(fixture),
            },
        }
        initial = {
            "phase": "before_edit",
            "assertion_count": 0,
            "business_contract_covered": False,
            "test_source": repo_execution.TEMPLATE,
        }
        record = {
            "schema": data.SCHEMA,
            "record_id": spec["fixture_id"],
            "task_id": "test-completion:" + spec["fixture_id"],
            "lineage_id": "curated-requirement:" + spec["fixture_id"],
            "family_id": spec["family"],
            "project_id": source["repository"],
            "source_id": source["repository"] + ":" + source["path"],
            "source": {
                k: source[k] for k in ("repository", "path", "revision", "sha256")
            },
            "split": spec["split"],
            "origin_kind": "curated_development",
            "exposure": "development",
            "observed_at": observed,
            "available_at": observed,
            "authorization": {
                "training_allowed": spec["split"] == "train",
                "evaluation_allowed": True,
                "rights_basis": "User requested repository audit and E1-E6 coding experiments; pinned Hepta Apache-2.0 and Chain MIT source notices are retained with the fixtures; tests are newly authored.",
                "scope": "Owned isolated function-contract test experiment; no full repository build or public user provenance.",
            },
            "task": {
                "input": spec["input"],
                "domain": spec["domain"],
                "verifier": verifier,
                "messages": [
                    {"role": "user", "content": spec["input"]},
                    {"role": "tool", "content": data.canonical(initial).decode()},
                ],
            },
            "task_domain": spec["domain"],
            "teacher_id": None,
            "final_answer": answer,
            "trajectory": [],
        }
        assertions = spec["assertions"].splitlines()
        if len(assertions) > 1:
            partial = data.canonical(
                {
                    "edits": [
                        {
                            "path": "test_contract.py",
                            "old": "    pass",
                            "new": assertions[0],
                        }
                    ]
                }
            ).decode()
            intermediate = _reference(record, partial, output, "first_assertion_probe")
            partial_receipts.append(intermediate)
            actual = intermediate["result"].get("result") or {}
            if actual.get("original_passed") and not intermediate["success"]:
                record["trajectory"].extend(
                    [
                        {
                            "index": 0,
                            "actor": "curator",
                            "kind": "action",
                            "content": partial,
                            "executed": False,
                        },
                        {
                            "index": 1,
                            "actor": "environment",
                            "kind": "observation",
                            "content": _observed(intermediate),
                            "executed": False,
                        },
                    ]
                )
        record["trajectory"].append(
            {
                "index": len(record["trajectory"]),
                "actor": "curator",
                "kind": "action",
                "content": answer,
                "executed": False,
            }
        )
        result = _reference(record, answer, output, "complete_reference")
        if not result["success"]:
            write_new(
                output / "FAILED.json",
                {"record_id": spec["fixture_id"], "result": result},
            )
            raise ValueError(
                "reference patch failed actual business tests: "
                + spec["fixture_id"]
                + ":"
                + json.dumps(result)
            )
        record["trajectory"].append(
            {
                "index": len(record["trajectory"]),
                "actor": "environment",
                "kind": "observation",
                "content": _observed(result),
                "executed": False,
            }
        )
        record["informative_action_count"] = sum(
            event["kind"] == "action" for event in record["trajectory"]
        )
        record["trajectory_single_action"] = record["informative_action_count"] == 1
        record["attempt_semantics"] = (
            "Each bounded edit is applied to a fresh original test template. Failed-control feedback contains counts, never a reference patch or expected output."
        )
        record["verified_outcome"] = {
            "success": True,
            "receipt_sha256": result["receipt_sha256"],
            "verifier_name": "repo_patch",
            "verifier_version": "1",
        }
        data.validate_record(record)
        records.append(record)
        receipts.append(result)
    admission = data.validate_records(records)
    raw = b"".join(data.canonical(record) + b"\n" for record in records)
    (output / "records.jsonl").write_bytes(raw)
    write_new(
        output / "REFERENCE_EXECUTION.json",
        {
            "records": receipts,
            "first_assertion_probes": partial_receipts,
            "authored_references_executed": len(receipts),
            "external_agent_trajectories": 0,
            "model_teacher_calls": 0,
            "fixture_reference_calls_are_independent_samples": False,
            "all_reference_attempts": len(receipts) + len(partial_receipts),
        },
    )
    write_new(output / "ADMISSION.json", admission)
    write_new(
        output / "META.json",
        {
            "schema": "hepta.repo-test-panel.v1",
            "panel": panel,
            "records": len(records),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "counts": admission["counts"],
            "independent_users_verified": 0,
            "origin": "Newly curated test-completion requirements on pinned repository functions",
            "historical_external_agent_run": False,
            "future_generalization_evidence": False,
            "full_repository_integration": False,
            "task_metadata": [
                {
                    **{
                        k: r[k]
                        for k in (
                            "task_id",
                            "source_id",
                            "family_id",
                            "lineage_id",
                            "project_id",
                            "observed_at",
                            "available_at",
                            "task_domain",
                        )
                    },
                    "task_digest": data.digest(r),
                    "record_id": r["record_id"],
                    "split": r["split"],
                    "informative_action_count": r["informative_action_count"],
                    "trajectory_single_action": r["trajectory_single_action"],
                }
                for r in records
            ],
        },
    )
    return {
        "path": str(output),
        "records": len(records),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--panel",
        choices=("open", "confirmation", "warmup", "diagnostic-c", "diagnostic-d"),
        required=True,
    )
    parser.add_argument("--output", required=True)
    options = parser.parse_args()
    print(json.dumps(build(options.panel, options.output), sort_keys=True))
