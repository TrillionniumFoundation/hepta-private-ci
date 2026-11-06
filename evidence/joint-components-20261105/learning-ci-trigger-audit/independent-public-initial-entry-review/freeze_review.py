#!/usr/bin/env python3
"""Assemble an exact-source static review; never execute the reviewed modules."""
from pathlib import Path
import ast
import hashlib
import json
import re
import yaml

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parents[2]
SOURCE = "6db78eca53a5acdda0d96873d3f4cd65863426f0"
TREE = "e91f5994017fc5d2cfe58d405a20ee6ad9376772"
REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
PATHS = [
    ".github/workflows/hepta-public-initial-v2.yml",
    "codex-rs/hepta-infer-worker-host/src/smollm_public_initial_loop_tests.rs",
    "scripts/hepta_smollm_observed_execution_v1.py",
    "scripts/hepta_smollm_three_rounds_v2.py",
    "scripts/hepta_smollm_descendant_v2.py",
    "scripts/hepta_smollm_answer_eos_research_v3.py",
]


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def facts(path):
    data = path.read_bytes()
    return {"path": str(path.relative_to(ROOT)), "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


inventory = []
text = {}
for ordinal, path in enumerate(PATHS):
    rpc = ROOT / f"h3-source-{ordinal}.raw.json"
    response = json.loads(rpc.read_bytes())
    assert not response.get("isError", False)
    value = response["structuredContent"]
    assert value["encoding"] == "utf-8"
    assert f"/blob/{SOURCE}/" in value["display_url"]
    data = value["content"].encode("utf-8")
    blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    assert blob == value["sha"]
    inherited = WORKSPACE / "w1/neural-study-trigger-audit/source" / path
    assert inherited.read_bytes() == data
    local = ROOT / "source" / path
    local.parent.mkdir(parents=True, exist_ok=True)
    if local.exists():
        assert local.read_bytes() == data
    else:
        local.write_bytes(data)
    if path.endswith(".py"):
        ast.parse(data, filename=path)
    text[path] = data.decode()
    inventory.append({"path": path, "source_ref": SOURCE, "git_blob": blob,
                      "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                      "raw_response": facts(rpc), "local_file": facts(local),
                      "exact_h2_bytes_unchanged": True, "url": value["display_url"]})
save(ROOT / "exact-h3-six-source-binding.json", inventory)

workflow = yaml.load(text[PATHS[0]], Loader=yaml.BaseLoader)
assert set(workflow["on"]) == {"pull_request", "workflow_dispatch"}
job = workflow["jobs"]["cold-ordinary-three-rounds"]
assert job["timeout-minutes"] == "360"
assert not job.get("if") and not job.get("environment")
assert "codex-rs/hepta-agentd/**" in workflow["on"]["pull_request"]["paths"]
steps = {step["id"]: step for step in job["steps"] if "id" in step}
for term in ('schema="hepta-smollm-neural-native-check-v2"',
             'runtime_snapshot=os.environ["HEPTA_PUBLIC_INITIAL_RUNTIME_SNAPSHOT"]',
             'runtime_snapshot_sha256=hashlib.sha256('):
    assert term in steps["materials"]["run"]
gates = []
for key, timeout, minimum in [
    ("ordinary", 900, 2), ("proposal_rounds", 11100, 1),
    ("descendants", 9000, 0), ("answer_eos_research", 1800, 0),
]:
    step = steps[key]
    assert int(re.search(r"--timeout-seconds (\d+)", step["run"])[1]) == timeout
    assert int(re.search(r"--minimum-tests (\d+)", step["run"])[1]) == minimum
    gates.append({"id": key, "if": step["if"], "timeout_seconds": timeout,
                  "minimum_tests": minimum, "run": step["run"]})
assert 'for round in 1..=3' in text[PATHS[1]]
assert 'rounds.run(args)' in text[PATHS[2]]
assert 'trainer.run(' in text[PATHS[3]] and 'operation="train"' in text[PATHS[3]]
assert 'output.mkdir(mode=0o700, parents=False, exist_ok=False)' in text[PATHS[3]]
assert 'for number in range(1, 4)' in text[PATHS[4]]
assert 'candidate_training_lineage=[]' in text[PATHS[4]]
assert 'proposal_training_lineage=[]' in text[PATHS[5]]

review = {
    "schema": "hepta-public-initial-h3-independent-static-review-v1",
    "reviewer": "pq_recovery", "repository": REPOSITORY,
    "source_commit": SOURCE, "source_tree": TREE,
    "conclusion": "Reachable new real training and evaluation after current prerequisites pass; the first neural-study-v1 missing-input rejection does not protect this workflow.",
    "source_identity": {"exact_h3_independently_fetched_files": 6,
                        "git_blob_and_raw_sha256_verified": True,
                        "all_six_equal_preexisting_exact_h2_copies": True,
                        "inventory": "exact-h3-six-source-binding.json"},
    "trigger": {"events": workflow["on"], "runner": job["runs-on"],
                "job_timeout_minutes": 360, "job_if": job.get("if"),
                "job_environment": job.get("environment"),
                "draft_exclusion_in_workflow": False,
                "platform_approval_rules_audited": False,
                "changed_h3_agentd_paths_match": True,
                "concurrency": workflow["concurrency"]},
    "paired_source": {key: job["env"][key] for key in (
        "HEPTA_PAIRED_EXECUTION_PROFILE", "CHAIN_SHA", "RESEARCH_CHAIN_SHA",
        "OBSERVATION_CHAIN_SHA", "HEPTA_PUBLIC_INITIAL_ROUND_RUNNER",
        "HEPTA_PUBLIC_INITIAL_EXECUTION_PROFILE")},
    "input": {"schema": "hepta-smollm-neural-native-check-v2",
              "runtime_snapshot_and_raw_sha256_written": True,
              "first_workflow_missing_field_guard_does_not_apply": True,
              "actual_runtime_parent_source_ordinary_guards_still_required": True},
    "gates": gates,
    "call_chain": [
        {"entry": "proposal_rounds", "path": [
            "real_public_initial_three_rounds_hold_and_read_original_current",
            "for round in 1..=3 -> train_round",
            "hepta_smollm_observed_execution_v1.main -> rounds.run",
            "trainer.run(operation=train) -> original per-role train/evaluate phases"],
         "roles": "Five actual artifacts; candidate, fresh-budget-matched-lora and budget-matched-full-tune require the plan training_steps and matched token schedules. current-backbone and randomized-rank-matched-lora require zero gradient steps.",
         "round_guard_seconds": 2700, "all_phase_worst_cases_covered": False},
        {"entry": "descendants", "path": [
            "validate v2 configuration and current ordinary readback",
            "fresh campaign with empty candidate_training_lineage",
            "for number in range(1,4) -> rounds.run with actual same-campaign parent lineage"],
         "caveat": "The workflow condition requires ordinary success, not proposal_rounds success. It separately needs the ordinary-0 readback produced by the loop, so absent readback can fail; that is not a cross-run authorization gate."},
        {"entry": "answer_eos_research", "path": [
            "validate original gate receipts, source, current parent and completed loop",
            "rounds.run with research_profile, round=1, proposal_training_lineage=[]"],
         "caveat": "Requires successful original outcomes; if reached this is still an additional training/evaluation recipe."},
    ],
    "new_trial_boundary": {
        "fresh_root": "$RUNNER_TEMP/hepta-public-initial-v2",
        "per_round_create_new": "output.mkdir(mode=0o700, parents=False, exist_ok=False)",
        "same_output_directory_reuse_refused": True,
        "prior_spent_ledger_import_or_reconciliation_in_reviewed_entry_paths": False,
        "scope": "This is a statement about the exact reviewed workflow and entry paths, not an audit of every external trainer implementation. Their current source/material/snapshot checks and within-campaign ancestry do not establish prior-run budget or holdout continuity.",
        "lineage": "Measured ancestry produced within this campaign; a new campaign starts empty.",
        "current_hold_and_no_install": "Preserved qualification and installation barriers; they do not prevent or undo consumed training/evaluation.",
        "quality_limits": ["public smoke tasks", "controlled issuer", "per-round-only budget matching", "cumulative_budget_matched=false", "independent_future_quality=false", "product_qualification=false"],
    },
    "not_claimed": ["these H3 workflows actually ran", "new training or inference executed by this reviewer", "historical H2 skip guarantees H3 skip", "public model qualification", "new trial authorization", "joint acceptance"],
    "parent_decision": "Keep H3 immutable branch/compare reviewable; do not open PR, edit or skip original CI, or start a new trial. The already authorized H3 local native continues independently.",
    "actions": {"desktop_calls": 0, "cargo_runs": 0, "training_trials": 0,
                "source_mutations": 0, "workflow_mutations": 0, "remote_bulk_reads": 0,
                "github_read_only_file_requests": 6},
    "prior_first_workflow_report_preserved": {"path": "../review.json", "sha256": hashlib.sha256((ROOT.parent / "review.json").read_bytes()).hexdigest()},
}
save(ROOT / "review.json", review)
print(json.dumps({"status": "STATIC_ASSEMBLY_COMPLETE", "source_files": len(inventory),
                  "review": facts(ROOT / "review.json"),
                  "exact_binding": facts(ROOT / "exact-h3-six-source-binding.json"),
                  "native_or_training_executed": False}, ensure_ascii=False))
