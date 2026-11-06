#!/usr/bin/env python3
"""Verify a fixed CI API observation and publication identities; no native execution."""
import argparse
import collections
import hashlib
import json
from pathlib import Path


def identity(data):
    return {
        "bytes": len(data),
        "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def read_json(root, name):
    return json.loads((root / name).read_bytes())


def unpack(value):
    if "raw" in value:
        value = value["raw"]
    assert not value.get("isError", False)
    structured = value["structuredContent"]
    return json.loads(structured["content"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    root = parser.parse_args().root
    manifest = read_json(root, "original-manifest.json")
    assert len(manifest["files"]) == 14
    assert len({item["path"] for item in manifest["files"]}) == 14
    for item in manifest["files"]:
        relative = Path(item["path"])
        assert not relative.is_absolute() and ".." not in relative.parts
        assert identity((root / relative).read_bytes()) == {key: item[key] for key in ("bytes", "git_blob", "sha256")}

    summary = read_json(root, "SUMMARY.json")
    head = "17c6b903a5d5d470b72035f95bb6e087291d7e04"
    tree = "25020dc30888fa3ffa6f6e8d1073d91edded1756"
    merge = "26cfdcaa70cbd2daecd165137e3b84d2ad1a7284"
    base = "63652be658ebed8d3052eb789b951793384fd5e4"
    parent = "840e8b5dbffca017753cdf87482ce325938f313c"
    assert summary["current_product_head"] == head
    assert summary["current_product_tree"] == tree
    assert summary["current_product_merge"] == merge
    assert summary["target_base"] == base
    assert summary["whole_candidate_qualified"] is False
    assert summary["old_840_results_transferred"] is False
    assert summary["native_case_counts_accepted_for_this_head"] is None
    assert summary["all_blockers_closed"] is False
    assert summary["manual_CI_operations"] == []
    assert summary["private_capacity_query"] is False

    head_response = read_json(root, "runs-full.original.json")
    jobs_response = read_json(root, "blocking-jobs-full.original.json")
    runs = unpack(head_response)
    jobs = unpack(jobs_response)
    assert runs["total_count"] == len(runs["workflow_runs"]) == 18
    assert len({run["id"] for run in runs["workflow_runs"]}) == 18
    assert all(run["head_sha"] == head and run["event"] == "pull_request" and run["run_attempt"] == 1 for run in runs["workflow_runs"])
    projection = [{key: run[key] for key in ("id", "name", "status", "conclusion", "head_sha", "run_attempt")} for run in runs["workflow_runs"]]
    counts = dict(sorted(collections.Counter(run["conclusion"] if run["status"] == "completed" else run["status"] for run in runs["workflow_runs"]).items()))
    assert projection == summary["runs"]
    assert counts == summary["run_status_counts"] == {"pending": 3, "queued": 12, "skipped": 2, "success": 1}
    assert summary["run_count"] == 18
    blocking = next(run for run in runs["workflow_runs"] if run["id"] == 42201989815)
    assert blocking["name"] == "blocking-ci" and blocking["status"] == "pending"
    assert jobs["total_count"] == len(jobs["jobs"]) == summary["blocking_jobs_count"] == 0
    assert summary["blocking_jobs"] == [] and summary["blocking_job_status_counts"] == {}
    assert head_response["capture_completed_before_utc"] == "2026-11-06T10:29:19Z"
    assert jobs_response["capture_completed_before_utc"] == summary["latest_observation_utc"] == "2026-11-06T10:30:14Z"

    commit = unpack(read_json(root, "authority/commit.actual.original.json"))
    merged = unpack(read_json(root, "authority/merge.actual.original.json"))
    ref = unpack(read_json(root, "authority/ref.after.original.json"))
    pr = unpack(read_json(root, "authority/pr.after.original.json"))
    publication = read_json(root, "authority/publication-verified.json")
    assert commit["sha"] == head and commit["tree"]["sha"] == tree
    assert [item["sha"] for item in commit["parents"]] == [parent]
    assert merged["sha"] == merge and merged["tree"]["sha"] == tree
    assert [item["sha"] for item in merged["parents"]] == [base, head]
    assert ref["object"]["sha"] == head
    assert ref["ref"] == "refs/heads/" + publication["branch"]
    assert pr["number"] == 4936 and pr["head"]["sha"] == head and pr["base"]["sha"] == base
    assert pr["merge_commit_sha"] == merge and pr["draft"] is True
    assert pr["changed_files"] == 1566 and pr["commits"] == 107
    assert publication["head"] == head and publication["tree"] == tree
    assert publication["merge_commit"] == merge and publication["merge_ordered_parents"] == [base, head]
    for item in summary["API_observation_files"] + summary["publication_source_files"]:
        assert identity((root / item["path"]).read_bytes()) == {key: item[key] for key in ("bytes", "git_blob", "sha256")}

    receipt = read_json(root, "SUMMARY.actual.receipt.json")
    assert receipt["full_GET_original"]["structuredContent"]["content"].encode() == (root / "SUMMARY.json").read_bytes()
    assert receipt["git_blob_sha"] == identity((root / "SUMMARY.json").read_bytes())["git_blob"]

    later_runs = unpack(read_json(root, "root-next-cut/17-head-runs-first.original.json"))
    later_jobs = unpack(read_json(root, "root-next-cut/17-blocking-jobs-first.original.json"))
    later_summary = read_json(root, "root-next-cut/17-head-runs-first.summary.json")
    later_review = read_json(root, "root-next-cut/CI-REVIEW.json")
    assert later_runs["total_count"] == len(later_runs["workflow_runs"]) == 18
    assert len({run["id"] for run in later_runs["workflow_runs"]}) == 18
    assert {run["id"] for run in later_runs["workflow_runs"]} == {run["id"] for run in runs["workflow_runs"]}
    assert all(run["head_sha"] == head and run["event"] == "pull_request" and run["run_attempt"] == 1 for run in later_runs["workflow_runs"])
    later_counts = dict(sorted(collections.Counter(run["conclusion"] if run["status"] == "completed" else run["status"] for run in later_runs["workflow_runs"]).items()))
    later_projection = [
        {"id": run["id"], "name": run["name"], "path": run["path"], "status": run["status"], "conclusion": run["conclusion"], "attempt": run["run_attempt"], "created_at": run["created_at"], "updated_at": run["updated_at"], "url": run["html_url"]}
        for run in later_runs["workflow_runs"]
    ]
    assert later_summary["runs"] == later_projection
    assert later_summary["head"] == head and later_summary["total_count"] == 18
    assert later_summary["original_fetch_completed_before_UTC"] == "2026-11-06 10:31:19 UTC"
    assert later_counts == later_summary["status_counts"] == {"in_progress": 1, "pending": 3, "queued": 11, "skipped": 2, "success": 1}
    assert later_review["run_list"] == later_summary
    assert later_jobs["total_count"] == len(later_jobs["jobs"]) == later_review["blocking"]["complete_job_count"] == 0
    assert later_review["blocking"]["jobs"] == [] and later_review["blocking"]["status_counts"] == {}
    assert later_review["blocking"]["run"] == 42201989815
    assert later_review["latest_observation_utc"] == later_review["blocking"]["observed_utc"] == "2026-11-06 10:32:44 UTC"
    assert later_review["current_product_head"] == head and later_review["current_product_tree"] == tree and later_review["actual_PR_merge"] == merge
    assert later_review["non_atomic"] is True
    assert later_review["whole_candidate_qualified"] is False
    assert later_review["required_original_CI_all_success"] is False
    assert later_review["original_platform_test_acceptance_inferred_from_run_summary"] is False
    assert later_review["manual_CI_dispatch_rerun_cancel"] is False
    assert later_review["private_capacity_query"] is False and later_review["B16_replay"] is False
    print(json.dumps({
        "schema": "hepta-fixed-CI-observation-offline-verification-v1",
        "original_files_checked": manifest["files"],
        "current_product_head": head,
        "current_product_tree": tree,
        "current_product_merge": merge,
        "latest_observation_utc": later_review["latest_observation_utc"],
        "separate_non_atomic_observations": [
            {"run_list_observed_before_utc": head_response["capture_completed_before_utc"], "blocking_jobs_observed_before_utc": summary["latest_observation_utc"], "complete_head_runs": 18, "run_status_counts": counts, "complete_blocking_jobs": 0},
            {"run_list_observed_before_utc": later_summary["original_fetch_completed_before_UTC"], "blocking_jobs_observed_before_utc": later_review["latest_observation_utc"], "complete_head_runs": 18, "run_status_counts": later_counts, "complete_blocking_jobs": 0},
        ],
        "observations_merged_as_one_denominator": False,
        "publication_HEAD_ref_PR_merge_checked": True,
        "actual_job_checkout_inferred": False,
        "native_case_counts_accepted": None,
        "whole_candidate_qualified": False,
        "old_source_results_transferred": False,
        "native_or_network_invocation": False,
    }, ensure_ascii=False, indent=2) + "\n", end="")


if __name__ == "__main__":
    main()
