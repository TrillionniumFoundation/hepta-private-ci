"""Read-only audit of the retained MEM7 campaign; never rerun its actors."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


SOURCE = "9385535e683b97058fedeee490c6ff921652f793"
INTEGRITY_SOURCE = "32a19ec3b1894c3afc41eb978edaefb213d9eeed"


def require(value, code):
    if not value:
        raise ValueError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    return json.loads(path.read_bytes())


def verify_pin(root, pin):
    relative = Path(pin["path"])
    require(not relative.is_absolute() and ".." not in relative.parts, "unsafe_path")
    path = root / relative
    require(path.is_file() and not path.is_symlink(), "missing_regular_file")
    require(path.resolve().is_relative_to(root.resolve()), "path_escape")
    raw = path.read_bytes()
    require(len(raw) == pin["bytes"] and sha(raw) == pin["sha256"], "pin_mismatch")
    return raw


def audit(root, repository, snapshot_index):
    snapshot = read_json(snapshot_index)
    require(snapshot["source_execution_commit"] == SOURCE, "snapshot_source")
    roster = snapshot["files"]
    require(len(roster) == len({p["path"] for p in roster}) == 156, "snapshot_roster")
    actual = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
    require(actual == {p["path"] for p in roster}, "snapshot_inventory")
    for pin in roster:
        verify_pin(root, pin)
    original_index = read_json(root / "EVIDENCE_INDEX.json")
    require(original_index["execution_source"] == SOURCE, "original_index_source")
    require(len(original_index["entries"]) == 154, "original_index_count")
    for pin in original_index["entries"]:
        verify_pin(root, pin)

    campaign = root / "revocation"
    plan = read_json(campaign / "PLAN.json")
    report = read_json(campaign / "REPORT.json")
    require(plan["source_commit"] == SOURCE, "plan_source")
    source_files = {}
    for pin in plan["source_pins"]:
        raw = subprocess.check_output(
            ["git", "show", f"{SOURCE}:{pin['path']}"], cwd=repository
        )
        require(
            len(raw) == pin["bytes"] and sha(raw) == pin["sha256"], "git_source_pin"
        )
        verify_pin(repository, pin)
        source_files[pin["path"]] = pin["sha256"]
    require(len(source_files) == 5, "source_file_count")
    sys.path.insert(0, str(repository / "scripts"))
    from ndu_real_runtime.episodic_memory import digest
    from ndu_real_runtime.episodic_receipt import verify_read_receipt

    verify_pin(campaign, report["plan"])
    require(
        [row["scenario"] for row in report["rows"]] == plan["scenarios"],
        "scenario_roster",
    )
    require(len(report["rows"]) == 14, "scenario_count")
    readers, results = set(), {}
    for row in report["rows"]:
        name = row["scenario"]
        request = json.loads(verify_pin(campaign, row["request"]))["argv"]
        process = read_json(campaign / f"{name}.process.json")
        require(process == row["process"], "process_report_mismatch")
        require(process["argv"][1:3] == ["-B", "-m"], "reader_launch_shape")
        require(process["argv"][3:] == request, "reader_request_mismatch")
        require(process["returncode"] == 0, "reader_exit")
        require(verify_pin(campaign, process["stderr"]) == b"", "reader_stderr")
        result = json.loads(verify_pin(campaign, process["stdout"]))
        require(verify_read_receipt(result), "read_receipt_inconsistent")
        require(row["receipt"] == result["receipt"], "report_receipt_mismatch")
        args = {}
        require(request[0] == "ndu_real_runtime.episodic_retrieval", "reader_module")
        require((len(request) - 1) % 2 == 0, "request_option_pairs")
        for key, value in zip(request[1::2], request[2::2]):
            args.setdefault(key, []).append(value)
        require(
            all(len(v) == 1 for k, v in args.items() if k != "--source"),
            "duplicate_option",
        )
        expected = {
            "session_id": args["--session"][0],
            "mode": args["--mode"][0],
            "strategy": args["--strategy"][0],
            "source_ids": sorted(args["--source"]),
            "query_sha256": digest(
                {"query": args["--query"][0], "key": args["--key"][0]}
            ),
            "limit": int(args["--limit"][0]),
            "max_context_bytes": int(args["--max-context-bytes"][0]),
            "replay_seed": int(args["--seed"][0]),
        }
        require(
            all(result["receipt"][k] == v for k, v in expected.items()),
            "request_receipt_binding",
        )
        require(row["passed"] and row["request_bound"], "original_scenario_not_passed")
        require(
            sorted(result["receipt"]["delivered_ids"]) == sorted(row["expected_ids"]),
            "delivered_ids",
        )
        readers.add(process["pid"])
        results[name] = result
    require(len(readers) == 14, "reader_process_identity_count")

    mutations, writers = {}, set()
    require(
        [m["phase"] for m in report["mutations"]] == ["learn", "update", "revoke"],
        "mutation_order",
    )
    for mutation in report["mutations"]:
        phase = mutation["phase"]
        process = read_json(campaign / f"{phase}.process.json")
        require(
            all(mutation[k] == v for k, v in process.items()),
            "mutation_process_binding",
        )
        require(
            process["returncode"] == 0 and mutation["writer_exited_before_readers"],
            "writer_exit_record",
        )
        require(verify_pin(campaign, process["stderr"]) == b"", "writer_stderr")
        verify_pin(campaign, process["stdout"])
        response = json.loads(verify_pin(campaign, mutation["response"]))
        require(
            response["pid"] == process["pid"] and response["phase"] == phase,
            "mutation_response_binding",
        )
        mutations[phase] = response
        writers.add(process["pid"])
    require(
        len(writers) == 3 and not writers & readers, "writer_reader_identity_collision"
    )
    updated = mutations["update"]["records"]
    affected = {record["record_id"] for record in updated.values()}
    require(len(affected) == 3, "updated_chain_count")
    require(
        updated["route"]["dependencies"] == [updated["fact"]["record_id"]],
        "route_dependency",
    )
    require(
        updated["summary"]["dependencies"] == [updated["route"]["record_id"]],
        "summary_dependency",
    )
    revoke = mutations["revoke"]["operation"]
    require(
        revoke["status"] == "revoked" and set(revoke["affected_ids"]) == affected,
        "revocation_scope",
    )
    contact = mutations["learn"]["records"]["contact"]["record_id"]
    require(
        set(results["snapshot_active_chain"]["receipt"]["delivered_ids"])
        == affected | {contact},
        "pre_revoke_active_chain",
    )
    before = results["snapshot_current_fact"]["receipt"]["view_receipt"]
    after = results["revoked_snapshot_fact"]["receipt"]["view_receipt"]
    snapshot_body = read_json(campaign / "after-update.json")
    require(
        digest(snapshot_body["body"]) == snapshot_body["sha256"], "snapshot_body_digest"
    )
    require(
        before["snapshot_sha256"]
        == after["snapshot_sha256"]
        == snapshot_body["sha256"],
        "same_snapshot",
    )
    require(
        before["authority_id"]
        == after["authority_id"]
        == snapshot_body["body"]["authority_id"],
        "same_authority",
    )
    require(
        after["authority_generation"] == before["authority_generation"] + 1,
        "generation_increment",
    )
    require(
        before["snapshot_rejections"] == 0 and after["snapshot_rejections"] == 3,
        "snapshot_revocation_rejections",
    )
    require(results["revoked_snapshot_fact"]["records"] == [], "revoked_fact_delivered")
    require(
        results["revoked_live_fact"]["records"] == [], "revoked_live_fact_delivered"
    )
    for name in (
        "revoked_snapshot_bm25",
        "revoked_snapshot_uniform",
        "revoked_snapshot_icl",
        "unrelated_snapshot_fact",
        "unrelated_live_fact",
    ):
        require(
            results[name]["receipt"]["delivered_ids"] == [contact],
            "unrelated_contact_retention",
        )

    validation, tests = root / "validation", []
    for filename, source, count in (
        ("integrity-tests-bound.json", INTEGRITY_SOURCE, 23),
        ("campaign-tests-bound.json", SOURCE, 24),
    ):
        record = read_json(validation / filename)
        require(
            record["source_sha"] == record["tested_sha"] == source,
            "test_source_binding",
        )
        require(
            record["before"] == record["after"] and not record["before"]["dirty"],
            "test_clean_identity",
        )
        require(record["before"]["commit"] == source, "test_checkout_identity")
        tree = subprocess.check_output(
            ["git", "rev-parse", f"{source}^{{tree}}"], cwd=repository, text=True
        ).strip()
        require(record["before"]["tree"] == tree, "test_git_tree")
        raw = verify_pin(
            validation,
            {
                "path": record["log_file"],
                "bytes": record["log_bytes"],
                "sha256": record["log_sha256"],
            },
        )
        names = re.findall(rb"^(test_\w+) \(([^\n)]+)\)", raw, re.M)
        require(len(names) == len(set(names)) == count, "test_log_name_count")
        require(
            len(re.findall(rb" \.\.\. ok$", raw, re.M)) == count, "test_log_ok_count"
        )
        require(
            re.search(
                rb"\nRan " + str(count).encode() + rb" tests in [\d.]+s\n\nOK\n", raw
            )
            is not None,
            "test_log_summary",
        )
        require(
            record["observed_passed_tests"] == count
            and record["observed_failed_tests"] == 0
            and record["status"] == "passed",
            "test_receipt_counts",
        )
        require(
            not record["timed_out"]
            and not record["output_limit_exceeded"]
            and record["returncode"] == record["exit_code"] == 0,
            "test_terminal",
        )
        tests.append(
            {"source_sha": source, "passed": count, "log_sha256": record["log_sha256"]}
        )
    execution = read_json(validation / "campaign-execution.json")
    require(
        execution["before"] == execution["after"] and not execution["before"]["dirty"],
        "campaign_clean_identity",
    )
    require(
        execution["before"]["head"] == SOURCE and execution["returncode"] == 0,
        "campaign_execution_identity",
    )
    for stream in ("stdout", "stderr"):
        require(
            sha((validation / f"campaign.{stream}.txt").read_bytes())
            == execution[f"{stream}_sha256"],
            "campaign_stream_digest",
        )
    return {
        "schema": "hepta.mem7.retained-readback.v1",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS_RETAINED_EVIDENCE_CONSISTENCY",
        "execution_source_sha": SOURCE,
        "snapshot_index_sha256": sha(snapshot_index.read_bytes()),
        "verified_files": len(roster),
        "verified_bytes": sum(p["bytes"] for p in roster),
        "original_index_entries": len(original_index["entries"]),
        "source_files_verified_against_git": source_files,
        "historical_tests": tests,
        "historical_campaign_scenarios": len(results),
        "historical_reader_process_ids": len(readers),
        "historical_writer_process_ids": len(writers),
        "narrow_revocation_attribution_gap": "CLOSED_FOR_RETAINED_SAME_AUTHORITY_SYNTHETIC_CAMPAIGN",
        "new_model_calls": 0,
        "new_actor_episodes": 0,
        "new_independent_real_tasks": 0,
        "trusted_execution_authenticated": False,
        "ordinary_product_entry_qualified": False,
        "common_p0_candidate_qualified": False,
        "full_owner_cold_recovery": False,
        "complete_physical_cost_measured": False,
        "scientific_acceptance": "HOLD",
        "adoption_action": "NoUpdate",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--snapshot-index", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            audit(args.root, args.repository, args.snapshot_index),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
