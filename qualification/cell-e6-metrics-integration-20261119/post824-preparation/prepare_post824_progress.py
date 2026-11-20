"""Preserve the 824 snapshot and add terminal CI, E5 and E6 observations."""

import copy
import datetime
import hashlib
import json
import lzma
from pathlib import Path
import shutil
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent
OUT = ROOT / "post824-publication"
EVIDENCE = OUT / "qualification/cell-e6-metrics-integration-20261119"
JOINT = OUT / "qualification/cell-joint-20261118-2e9b"
OLD = ROOT / "followup-publication/qualification/cell-joint-20261118-2e9b/CURRENT_PROGRESS.json"
OLD_SHA = "3cc021446a076f04c3654a5416964d29071ac1decf413cd3107abdd0f062e238"
BASE = "8240292307116aa4063f7c63d8cdf48a0e8ef773"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def jload(path):
    return json.loads(Path(path).read_bytes())


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def main():
    old_raw = OLD.read_bytes()
    assert sha(old_raw) == OLD_SHA
    old = json.loads(old_raw)
    current = copy.deepcopy(old)
    now = datetime.datetime.now(datetime.timezone.utc)
    current["observed_at_utc"] = now.isoformat()
    current["observed_at_user_timezone"] = now.astimezone(ZoneInfo("America/New_York")).isoformat()
    current["previous_evidence_commit"] = BASE
    JOINT.mkdir(parents=True, exist_ok=True)
    history = JOINT / "checkpoint-824-successor"
    history.mkdir(exist_ok=False)
    compressed = lzma.compress(old_raw, preset=6)
    assert lzma.decompress(compressed) == old_raw
    (history / "previous-current-824.json.xz").write_bytes(compressed)
    save(history / "PREVIOUS_BINDING.json", {"commit": BASE, "original_bytes": len(old_raw), "original_sha256": OLD_SHA, "archive_bytes": len(compressed), "archive_sha256": sha(compressed)})
    scope = current["checkpoint_scope"]
    scope["previous_current_sha256"] = OLD_SHA
    scope["previous_current_exact_bytes"] = "checkpoint-824-successor/previous-current-824.json.xz"
    scope["new_source_change"] = "Only the Codespell workflow classifies one exact immutable binary shard after checking its regular-file type, length and SHA256. Runtime source and experiment gates are unchanged."

    ci = jload(EVIDENCE / "ci-824-complete/READOUT.json")
    assert ci["head_sha"] == BASE and ci["run_conclusion"] == "failure"
    assert ci["total_jobs"] == 37 and ci["job_counts"] == {"success": 19, "failure": 10, "cancelled": 4, "skipped": 4}
    assert all(job["status"] == "completed" for job in ci["all_jobs"])
    jobs = {job["id"]: job for job in ci["all_jobs"]}
    selected = [136202001708, 136202214782, 136202214948, 136202214966, 136202214979, 136202215292, 136202215359, 136202215425, 136202215426, 136202215448, 136202215451, 136202215471, 136202215513, 136202392522]
    mac = jload(EVIDENCE / "macintel-lease-fixture-review/READOUT.json")
    current["CI"]["latest_824_terminal_workflow_observation"] = {
        "source_head": BASE,
        "source_tree": "2ec6ba4ee575eba4daee656ccf3d218074efd65c",
        "actual_selected_job_checkout": ci["actual_selected_job_checkout"],
        "run_id": ci["run_id"],
        "run_status": ci["run_status"],
        "run_conclusion": ci["run_conclusion"],
        "run_updated_at": ci["run_updated_at"],
        "all_37_jobs_terminal": True,
        "job_counts": ci["job_counts"],
        "selected_jobs": [jobs[job] for job in selected],
        "new_helper_linux_and_windows_clippy_passed": True,
        "new_helper_sha256": "e69d4ccd85f8a38d2720eccdaae57208a3f463951dac8bb5b833f89e89388bca",
        "mac_intel": mac["mac_intel"],
        "mac_intel_causal_observation": mac["causal_observation"],
        "mac_intel_fixture_and_three_product_files_exact_across_four_refs": True,
        "mac_intel_direct_call_path_to_new_helper_observed": False,
        "mac_arm_executed": False,
        "mac_arm_cancellation_cause": None,
        "cargo_deny_cause": None,
        "cargo_deny_retrieval_error_retained": "Transport closed",
        "gnu_musl_independent_physical_execution_or_summed_cost_claimed": False,
        "whole_mac_or_joint_CI_passed": False,
        "readout_sha256": sha((EVIDENCE / "ci-824-complete/READOUT.json").read_bytes()),
        "archive_sha256": "f3abb9657fb4bdd6bc0082c2ae5b313025fa31e05c4673f5a9fbdc7fb0af7e84",
        "evidence_directory": "../cell-e6-metrics-integration-20261119/ci-824-complete",
    }
    current["CI"]["latest_exact_binary_classification_correction"] = {
        "workflow": ".github/workflows/codespell.yml",
        "workflow_sha256": "d19ff4e23b7ed3b413be94626f52e3ead5ec1318b058d0040266c5bb12e4f366",
        "exact_path": "qualification/cell-e6-metrics-integration-20261119/mac-native5-complete/native5-and-cache-originals.tar.xz.part-002",
        "exact_binary_bytes": 150516,
        "exact_binary_sha256": "6ad85c1eb8adbe0f061f65b097df84b078851a90c495da5163596c540ae8b61c",
        "codespell_version": "2.4.3",
        "first_NUL_byte_offset": 1165,
        "binary_detection_prefix_bytes": 1024,
        "guard_controls_passed": ["absent", "exact", "same_length_tamper", "truncated", "symlink", "directory"],
        "skip_is_one_exact_path": True,
        "original_binary_bytes_unchanged": True,
        "broad_glob_or_wordlist_added": False,
        "integrated_workflow_executed_at_snapshot": False,
        "evidence_directory": "../cell-e6-metrics-integration-20261119/codespell-binary-classification",
    }
    gate = jload(WORK / "metrics_gate_work/followup-final-gate-1/RESULT.json")
    assert gate["status"] == "PASS" and gate["head"] == BASE
    current["CI"]["checkpoint_824_original_blob_validation"] = {
        "base": gate["base"], "head": BASE, "tree": gate["tree"],
        "changed_paths": gate["changed_paths"], "exact_objects": gate["exact_objects"],
        "status": gate["status"], "original_maximum_bytes": 512000,
        "gate_wall_seconds": gate["gate_wall_seconds"], "owner_wall_seconds": gate["owner_wall_seconds"],
        "result_sha256": "17275ff00a228e38b789d0267e54f68bbd994c8eb2999b1e78ec8e080afb0e01",
        "evidence_directory": "../cell-e6-metrics-integration-20261119/checkpoint-824-readback",
    }

    e5 = jload(EVIDENCE / "e5-v2-complete-readback/BINDINGS.json")
    assert e5["summary"]["original_static_representation_admitted_count"] == 0
    assert e5["summary"]["complete_encoding_and_token_bounds_fit_count"] == 7
    current["E5"]["latest_v2_complete_targets_and_original_gate"] = {
        "source_prs": [6793, 6794, 6795, 6796, 6797],
        "final_head": "faeed277149701a316085a0453b05480df528655",
        "final_tree": "7a24f4e0323411e6d8dbe9cf65d1e4786385bea9",
        "all_draft_open_unmerged": True,
        "original_v1_head_unchanged": "148e37c26586677e83f0e57e100def8805c1a020",
        "original_identities_budgets_order_and_negative_results_preserved": True,
        "independent_branch_evidence_not_joint_runtime": True,
        "complete_binding": e5,
        "real_users": 0,
        "new_training_updates": 0,
        "new_model_calls": 0,
        "new_native_replays": 0,
        "original_final_blob_gate": {"status": "PASS", "changed_paths": 26, "maximum_bytes": 512000, "result_sha256": "39a2b1dc7c588ce60066a904866493c9c4f81439ff7505baa7ad7348f3493bd8"},
        "full_274_member_archive_root_verified": True,
        "archive_sha256": "c29e3372f6765f3c671019150f347eae3a511933ced1a68b161386ab96ff6923",
        "evidence_directory": "../cell-e6-metrics-integration-20261119/e5-v2-complete-readback",
    }

    e6 = jload(EVIDENCE / "e6-8996-noupdate8-readback/SUMMARY.json")
    assert e6["source"] == "8996e4c5b6a8662c51f47d9e164b8c839635c796"
    assert e6["new_Root_mechanism_parent_passed"] is True and e6["new_ordinary_parent_passed"] is False
    assert e6["refused_historical_request"] == 65 and e6["historical_cap"] == 64
    current["E6"]["latest_8996_complete_ordinary_attempt"] = {
        "source": e6["source"], "tree": e6["tree"],
        "public_pr": 6776, "public_head": "7bb71087b21b0c98998acfaf4d499b6395d929a5",
        "public_tree": "10e4ae616971337d67381bac76f75ece10f1f1f1",
        "publication_adds_evidence_without_product_byte_changes": True,
        "draft_open_unmerged": True,
        "full1159_source_CLI_passed_on_8996": True,
        "full1159_result_sha256": "1241dd778f529ffdebf4239dd31c45e30d7d4b8e775567a6192ee572c7e1b3cf",
        "old433_907_398_gate_evidence_remains_bound_to_d035": True,
        "exact_marker_framing_change_bytes": 2,
        "strict_Root_parent_and_same_source_prior34_assertions_retained": True,
        "components": [{k: row[k] for k in ["path", "sha256", "cases", "command_seconds", "owner_seconds"]} for row in e6["new_actual_components"]],
        "actual_new_component_cases": 34,
        "actual_new_component_failure_error_skip": 0,
        "actual_Root_mechanism_parent_passed": True,
        "actual_Root_parent_terminal_branches": e6["new_Root_mechanism_terminal_branches"],
        "actual_Root_parent_orders_each": e6["new_Root_mechanism_orders_each"],
        "ordinary_parent_executed": True,
        "ordinary_parent_passed": False,
        "ordinary_parent_result_sha256": e6["new_ordinary_parent_result_sha256"],
        "ordinary_parent_JUnit_sha256": e6["new_ordinary_parent_JUnit_sha256"],
        "ordinary_parent_command_seconds": e6["parent_command_seconds"],
        "enclosing_pipeline_owner_seconds": e6["pipeline_owner_seconds"],
        "nested_owner_costs_must_not_be_summed": True,
        "local_C_receipt_elapsed_micros": e6["C_receipt_returned_elapsed_micros"],
        "local_C_publish_elapsed_micros": e6["C_Source_publish_returned_elapsed_micros"],
        "local_C_RunStart_elapsed_micros": e6["C_final_run_start_returned_elapsed_micros"],
        "request65_is_attempted_ID_refused_before_socket_exchange": True,
        "original_client_limit": 64,
        "NextUse_executed": False,
        "terminal_Accept_executed": False,
        "complete_C_and_learning_qualification": False,
        "cold_D_executed": False,
        "Adopt_executed": False,
        "FinalUse_and_settlement_qualified": False,
        "old_static63_projection_refuted": True,
        "independent_source_projection_only": {"unmodified_full_path": 70, "actual_observed_through_attempt": 65, "66_through70_not_executed": True, "proposed_same_operation_savings": 6, "proposed_full_path": 64, "candidate_implemented_or_executed_at_snapshot": False},
        "source_review_constraints": "Preserve Selection pre-await admission, actual registered Weak/Arc slot identity, fresh Ready/installed/generation/prefix/expiry checks inside real operation, source/factory/cancellation pre/postchecks, error fencing, recovery paths and independent Accept. A ready hint cannot grant authority.",
        "original_deadlines_limits_acceptance_unchanged": True,
        "full612_originals_root_verified": True,
        "archive_sha256": "b86604090557849cadea5992cc2f58a3fd3c7d5320e27cd79bbf31387c3d01f3",
        "summary_sha256": "a316f970778a5257a17b93f7365ffa0b4c7e2c4e5088900db7fc2ad3aa4f8e3c",
        "publication_gate_sha256": "53c15e44c109890d61058f0a52fc1bb1ea8bcce5dd3bf675c3bdb52ba77f94b0",
        "evidence_directory": "../cell-e6-metrics-integration-20261119/e6-8996-noupdate8-readback",
    }
    current["interpretation"] = (
        "The original #6709 correction and its114 original tests remain unchanged. E1/E2 real student results remain ResearchNoUpdate; all56 evaluation calls are spent. The new E3 SmolLM2 recovery remains incomplete while original T2 history remains intact. E4 still has no proven advantage over strong single-model repair. E5 v2 now has published complete target evidence:7 complete encodings satisfy length bounds, but zero sources pass the original static context gate and every training prefix remains false. E6 exact8996 passes fresh34 native components and the actual Root mechanism parent; its complete ordinary NoUpdate8 attempt fails at attempted historical request65 before socket exchange. C local receipt/publication/RunStart return, but NextUse, delivery completion, Accept, cold D, Adopt, FinalUse and settlement are unqualified. Exact tail source analysis projects70 entries, with a proposed six-entry reduction only through fully checked real same-operation admission; no new implementation or native result is claimed in this snapshot. Actual824 CI has Linux/Windows Clippy pass, Mac Intel unit pass and cognitive fixture-expiry failure, and four Mac ARM jobs cancelled without a runner. The entire workflow fails. This checkpoint only adds one hash-guarded binary Codespell classification plus immutable evidence; runtime code, original limits and all ten joint qualification flags remain unchanged. Chain original liveness/F0 and full-cost gaps remain. Independent branches are not a new joint execution."
    )
    for key in ["joint_execution_source", "joint_execution_tree", "historical_freeze_rewritten", "E1", "E2", "E3", "E4", "Chain", "metrics_integration_6709", "qualification"]:
        assert current[key] == old[key], key
    assert len(current["qualification"]) == 10 and all(value is False for value in current["qualification"].values())
    save(JOINT / "CURRENT_PROGRESS.json", current)
    assert (JOINT / "CURRENT_PROGRESS.json").stat().st_size <= 512000
    (JOINT / "CURRENT_PROGRESS.md").write_text(f'''# E1–E6 continuation: exact evidence and one binary classification

Observed: {current["observed_at_user_timezone"]} (America/New_York).

**All ten joint qualification flags remain false.** Original experiment identities, budgets, source order, acceptance rules and negative history are unchanged. The exact prior 824 JSON is preserved in checkpoint-824-successor. Independent E5/E6 branch evidence does not constitute a new joint runtime execution.

## Source change

The only new non-evidence source file is `.github/workflows/codespell.yml`. Codespell 2.4.3 examined the first 1024 bytes of an immutable compressed archive shard, whose first NUL is at byte1165, then decoded random bytes as text. The workflow now verifies that one exact path is a regular file of150516 bytes with SHA256 `6ad85c1eb8adbe0f061f65b097df84b078851a90c495da5163596c540ae8b61c`, before excluding that single binary path from spelling. The six guard controls cover exact/absent/tampered/truncated/symlink/directory cases. No artifact bytes, wordlist, broad glob, runtime source or experiment gate changed. Integrated CI for this new workflow has not run at this snapshot.

## Actual terminal824 CI

Run44710897181, actual selected-job checkout41efe113b0becba5234af5c0de197c31bb5a4581, completed with failure:37 jobs,19 success,10 failure,4 cancelled,4 skipped. The helper Result-propagation correction has actual Linux and Windows Clippy PASS. Rust format and Linux/Windows native paths pass. Linux GNU and musl report successful targets; their remote execution is not counted twice or summed as independent physical work.

Mac Intel hepta-agentd unit tests pass without cache in115.6s. The cognitive target fails in2.7s: its existing fixture minted a lease with only52ms until the next integer second, then opening the executor took263ms. The unchanged product correctly rejected the expired lease before H7 setup, intended sleep and final quarantine assertions. The fixture and three relevant product files are byte-identical across238/d1d/824/actual merge41, and the new material helper has no direct call path to this fixture. This is not an overall Mac PASS. All four Mac ARM jobs were cancelled with runner_id0; the cancellation cause is unknown and no ARM execution is claimed. Cargo-deny remains failed with its cause unknown because the log response closed. Historical failures are retained.

## Experiment results

| Experiment | Actual latest result | Qualification still missing |
| --- | --- | --- |
| E1 | Real students remain1/4 on A and0/4 on future tasks; the original56-call collection is spent. | Matched same-information controls and executable unseen/future gain. |
| E2 | Real student recovery remains0/4. | Verified correction benefit with retained old capability. |
| E3 | New SmolLM2 material recovery is incomplete; original T2 observations are retained. | Ready authorized teacher material and matched-budget complementarity. |
| E4 | Original PP/CC/PC/CP remain5/6 and do not beat the strong single-model repair baseline. | New-task message benefit and original edge/message/Cell controls. |
| E5 | Five independent Drafts6793–6797 publish exact v2 input/target evidence. Seven complete encodings satisfy length limits, zero pass the original static gate, zero train. | Genuine context closure, original budget mappings and independent future verification;48 materials still missing for64. |
| E6 | Exact8996 reruns34 components successfully and passes the real Root mechanism parent; complete NoUpdate8 fails at attempted request65/max64. | Complete ordinary NoUpdate, authorized Adopt, new C/cold recovery/new D/FinalUse/settlement. |

## E5 complete target evidence

The original16 public projects and290 native cases remain in their frozen order, with zero authenticated users. One before-only retrieval creates15 bounded inputs; jsonschema remains refused in place. All15 full-template prefixes fit3200 tokens. Eight complete compact action sets reconstruct all original after bytes; seven target-scope refusals remain and rich exceeds the384-token target cap. Seven complete encodings satisfy all length limits. The original counter still rejects every static prefix because `v1_static_context_closed` is false for these partial views. Optimizer/compute/verifier/future mappings remain separate incomplete gates. No null or false field was converted into admission. The original v1 negative result and earlier imprecise derived terminology remain preserved with an explicit correction.

The final independent head is faeed277149701a316085a0453b05480df528655. Its original512000-byte gate passes26 paths. The complete274-member archive was independently reopened by root; no model, native replay or training was added by this readback.

## E6 complete actual failure

Runtime source8996e4c5b6a8662c51f47d9e164b8c839635c796 changes only two marker-framing bytes from d035. Fresh full1159 source validation, all34 original native components and the real Root parent pass. The Root parent preserves StalePrepare/Revoked and both SourceFirst/CurrentFirst orders. Earlier433/907/398 source results remain attributed to d035; they are not relabelled as fresh8996 executions.

The ordinary parent actually ran and failed in90.9185s. C receipt returns at5.419372s, Source publication at5.424108s and RunStart at5.424725s. These are local progress, not whole-C or learning acceptance. The historical client rejects attempted ID65 before socket encoding/exchange. NextUse stage, delivery completion and independent Accept do not run. Cold D and Adopt remain paused and all whole-parent/FinalUse/settlement flags are false.

Independent exact-source tail review gives installation56–57, Selection post-admission58–59, Selection stage60–61, NextUse pre62–63, NextUse post64–65, then unexecuted NextUse66–67, delivery completion68–69 and Accept70. The old63 estimate is refuted. A new design may remove six redundant exchanges by placing logical admission checks inside each actual synchronous stage operation. This is only a projection. Selection retains its pre-await admission; actual registered Weak/Arc slot identity, fresh readiness, installed owner, decision prefix, expiry, source/factory/cancellation pre/postchecks, error fencing, recovery and independent Accept remain required. A ready hint never grants permission.

The full612-original archive,200235726 original bytes compressed into eight bounded parts, was independently reopened and verified. Publication PR6776 is Draft at7bb71087b21b0c98998acfaf4d499b6395d929a5; it retains runtime8996 and the failure. Original2s/500ms deadlines and64-entry limit are unchanged. Nested compile, component, Root, ordinary-parent and enclosing-owner intervals are not summed as independent costs.

## Existing integration and system boundary

The #6709 metrics correction remains in the joint lineage with114 original tests across18 modules, zero failure/error/skip and the expected old-code negative control. Completed-use counts still require actual use and cold-process evidence; status labels alone do not establish completion.

Chain W1 mechanism results, original F0 failures, inherited contract gaps, unknown full physical cost and unchanged reward scope remain. No production activation, merge, public-reward expansion or new exhausted model-call budget is represented by this checkpoint.
''')
    preparation = EVIDENCE / "post824-preparation"
    preparation.mkdir(exist_ok=False)
    for path in [Path(__file__), ROOT / "verify_post824_input_archives.py", ROOT / "verify_post824_e6_archive.py", ROOT / "verify_post824_ci_archive.py", WORK / "metrics_gate_work/post824_blob_gate.py"]:
        shutil.copyfile(path, preparation / path.name)
    print(json.dumps({"current_bytes": (JOINT / "CURRENT_PROGRESS.json").stat().st_size, "current_sha256": sha((JOINT / "CURRENT_PROGRESS.json").read_bytes()), "markdown_sha256": sha((JOINT / "CURRENT_PROGRESS.md").read_bytes()), "qualifications": current["qualification"]}, indent=2))


if __name__ == "__main__":
    main()
