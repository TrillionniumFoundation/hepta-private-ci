"""Prepare the d1d successor without rewriting historical experiment records."""

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
OUT = ROOT / "followup-publication"
EVIDENCE = OUT / "qualification/cell-e6-metrics-integration-20261119"
JOINT = OUT / "qualification/cell-joint-20261118-2e9b"
OLD = ROOT / "next-publication/qualification/cell-joint-20261118-2e9b/CURRENT_PROGRESS.json"
OLD_SHA = "172a7975075ff94523c56ee7ed814c9ee81221080250f73867664b777d685d23"
BASE = "d1d3896e2a2628977bc466cee1e00aea93971949"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def jload(path):
    return json.loads(Path(path).read_bytes())


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def main():
    old_bytes = OLD.read_bytes()
    assert sha(old_bytes) == OLD_SHA
    old = json.loads(old_bytes)
    current = copy.deepcopy(old)
    now = datetime.datetime.now(datetime.timezone.utc)
    current["observed_at_utc"] = now.isoformat()
    current["observed_at_user_timezone"] = now.astimezone(ZoneInfo("America/New_York")).isoformat()
    current["previous_evidence_commit"] = BASE
    JOINT.mkdir(parents=True, exist_ok=True)
    history = JOINT / "checkpoint-d1d-successor"
    history.mkdir(exist_ok=False)
    compressed = lzma.compress(old_bytes, preset=6)
    (history / "previous-current-d1d.json.xz").write_bytes(compressed)
    assert lzma.decompress(compressed) == old_bytes
    write_json(history / "PREVIOUS_BINDING.json", {"commit": BASE, "original_bytes": len(old_bytes), "original_sha256": OLD_SHA, "archive_bytes": len(compressed), "archive_sha256": sha(compressed)})
    current["checkpoint_scope"]["previous_current_sha256"] = OLD_SHA
    current["checkpoint_scope"]["previous_current_exact_bytes"] = "checkpoint-d1d-successor/previous-current-d1d.json.xz"
    current["checkpoint_scope"]["latest_continuation_fields_take_precedence_over_historical_running_snapshots"] = True
    current["checkpoint_scope"]["current_execution_is_not_a_new_joint_run"] = True
    current["checkpoint_scope"]["new_source_change"] = "Only the fixture helper Result propagation correction; E5/E6 independent source is archived as evidence, not merged into joint runtime."

    native6 = jload(EVIDENCE / "mac-helper-clippy-fix/RESULT.json")
    assert native6["source_unchanged_during_validation"] and native6["exit_code"] == 1
    assert [s["exit_code"] for s in native6["stages"]] == [0, 0, 101]
    current["CI"]["latest_d1d_workflow_observation"] = {
        "source_head": BASE,
        "source_tree": "05c2e91d6387b60b07952282a8911ca52dd3d0bd",
        "actual_merge": "f8aba45bc00865f522cc4e0a78c80078cd8ec062",
        "actual_merge_base": "061334747ce9d87690c40df48eeedf239156b57d",
        "old_event_base_metadata": "2742bc37e9f4a74fba32bb534230de55f431e9ea",
        "same_base_name_metadata_refreshed": True,
        "old_architecture_base_job_remains_failed": True,
        "blocking_run": 44704388275,
        "complete_job_count": 37,
        "terminal_conclusions": {"success": 20, "failure": 12, "cancelled": 1, "skipped": 4},
        "blocking_result": "failure",
        "engineering_integrity": "success",
        "v8_canary": "success",
        "Windows_private_state_security": "success",
        "architecture_workflow_at_observation": "in_progress",
        "new_mac_linux_clippy_regression": {
            "jobs": [136180423581, 136180423696],
            "cause": "Two unwrap calls introduced in the fixture helper outside test functions.",
            "own_regression_not_inherited": True,
            "original_failure_retained": True,
            "new_source_lint_passed": False,
        },
        "mac_arm_bazel": {
            "job": 136180423580,
            "whole_job": "failure",
            "hepta_agentd_unit_tests": {"passed": True, "cached": False, "seconds": 92.1},
            "hepta_cognitive_write_qualification": {"passed": True, "cached": False, "seconds": 3.3},
            "failed_targets": ["core-all-test", "app-server-all-test"],
            "this_is_older_d1d_merge_not_new_helper_source": True,
        },
        "contract_gate": "Nine foreign Chain workflow references in four historical JSONs are interpreted as local paths; sampled files occur in merge base, not d1d source. No verifier waiver or historical rewrite.",
        "cargo_deny_cause": None,
        "cargo_deny_log_retrieval": "Transport closed",
        "evidence_directory": "../cell-e6-metrics-integration-20261119/ci-d1d-complete",
    }
    current["CI"]["latest_mac_fixture_helper_correction"] = {
        "path": "codex-rs/hepta-agentd/src/learning_iteration_research_external_material_tests.rs",
        "old_sha256": "8bc7dba30f6656fa0f0150ba2502bcd3f2f29e7f4c397c45dbb58a6d7520597f",
        "new_sha256": "e69d4ccd85f8a38d2720eccdaae57208a3f463951dac8bb5b833f89e89388bca",
        "change": "Return io::Result, propagate canonicalize error with ?, return tempdir_in Result, unwrap at six original test call sites.",
        "lint_waiver_added": False,
        "product_guards_unchanged": True,
        "other_fixture_unchanged": True,
        "actual_local_source_scope": native6["source_scope"],
        "actual_result_sha256": "23808e94f0d189cef34e02b11a9f58f9b8d274a6674739c6b10cb6436d102aae",
        "actual_stages": native6["stages"],
        "actual_owner_wall_seconds": native6["owner_wall_seconds"],
        "lint_passed": False,
        "native_cases_executed": 0,
        "blocker": "Original locked Inflector 0.11.4 registry crate archive absent in offline cache; unpacked source alone does not satisfy Cargo download path.",
        "five_exact_git_dependency_refs_verified": True,
        "new_download_or_native7_owner_started": False,
        "evidence_directory": "../cell-e6-metrics-integration-20261119/mac-helper-clippy-fix",
    }
    current["CI"]["checkpoint_d1d_original_blob_validation"] = {
        "base": "238fc48402f786db3d7f2a80b0abad6c0e5322bb",
        "head": BASE,
        "tree": "05c2e91d6387b60b07952282a8911ca52dd3d0bd",
        "changed_paths": 97,
        "original_maximum_bytes": 512000,
        "status": "PASS",
        "result_sha256": "5b9bb2e5904bf9c3c9fcb0ff8a7d712e5130c4b8ed55131870212bdd30d5b435",
        "gate_wall_seconds": 0.8263097809976898,
        "owner_wall_seconds": 2.169731805999618,
        "initial_preparation_keyerror_tree_retained": True,
        "evidence_directory": "../cell-e6-metrics-integration-20261119/checkpoint-d1d-readback",
    }
    source_result = jload(WORK / "e6_owner_work/ack_source_probe2_RESULT.json")
    component_root = WORK / "e6_owner_work/ack_source_d035_original_results"
    native_manifest = jload(component_root / "MANIFEST.json")
    pipeline = jload(component_root / "ack-source-native-pipeline-1__RESULT.json")
    current["E6"]["latest_ack_source_continuation"] = {
        "source": native_manifest["source"],
        "tree": native_manifest["tree"],
        "parent": "02d5b32dd81c4fc820d8468c617908c8f2907a50",
        "public_PR_head_at_previous_read": "02d5b32dd81c4fc820d8468c617908c8f2907a50",
        "source_commit_object_created_but_branch_not_yet_advanced_at_snapshot": True,
        "source_inventory_sha256": source_result["source_before_sha256"],
        "source_gate": {"tests": 433, "modules": 49, "protected_rows": 907, "affected_boundaries": 398, "full_cli_boundaries": 1159, "passed": True, "result_sha256": "d0ae06d0fca137c7eccddf85b16df5061beca66b50535da59822a5a249d7b428", "owner_wall_seconds": source_result["owner_wall_seconds"], "full_cli_wall_seconds": source_result["full_caller_proof_wall_seconds"]},
        "exact_source_blob_freeze_result_sha256": "29dffe1f73ac04741c2d59112ad5e6edc2b3f7361a18175a9d4891325f3b1f27",
        "component_results": native_manifest["files"][:4],
        "native_case_sets_passed": [11, 16, 5, 2],
        "native_cases_total": 34,
        "native_failure_error_skip": 0,
        "root_mechanism_parent_passed": False,
        "root_mechanism_failure": "StalePrepare child completed both ordering assertions, but libtest joined first success marker to test progress line; exact-line parent assertion failed. Revoked phase and ordinary NoUpdate did not execute.",
        "pipeline_result_sha256": "f9bf927ccf172c166864704e085309a99cd7652df3c66e6ad574cbe84f4846fa",
        "pipeline_owner_wall_seconds": pipeline["owner_wall_seconds"],
        "ordinary_NoUpdate_parent_executed": False,
        "complete_NoUpdate": False,
        "new_C_completed": False,
        "cold_new_D_completed": False,
        "FinalUse_completed": False,
        "settlement_completed": False,
        "root_budget": 64,
        "deadlines_changed": False,
        "arbitrary_same_run_replay_serialization_proved": False,
        "next_marker_repair": {"test_source_bytes_changed": 2, "product_bytes_changed": 0, "strict_marker_assertions_preserved": True, "same_source_prior34_guard_preserved": True, "new_head_34_reexecution_required": True, "new_full_cli_owner": "dpty-0a3309c54cefc0ee35511d7acd408a58aa425182dda929858c16e44485f3e554", "new_full_cli_owner_started_utc": "2026-11-20T09:18:54Z", "new_full_cli_result_at_snapshot": None},
        "evidence_directory": "../cell-e6-metrics-integration-20261119/e6-d035-readback",
    }
    measure_path = WORK / "e5_bounded_retrieval_v2/tokenizer-1/MEASUREMENT_READOUT.json"
    measure = jload(measure_path)
    assert measure["row_count"] == 16 and measure["measured_prefixes"] == measure["prefixes_fit_3200"] == 15
    assert not any(measure["training_prefix_1_4_16_admitted"].values())
    current["E5"]["latest_before_only_representation_v2"] = {
        "original_v1_negative_unchanged": True,
        "independent_candidate_not_joint_runtime": True,
        "public_source_PR_at_snapshot": None,
        "preimplementation_freeze_sha256": "55c13e3a93bd2b42e2ddac756636fe5d305c1d06ba307fcaa9727397caab12ec",
        "source_freeze_sha256": measure["source_freeze_sha256"],
        "input_freeze_sha256": measure["input_freeze_sha256"],
        "peer_manifest_sha256": "4b82ead538caf0636a9e1c75f2c3c62e42fa401662d39167cfbd1606d4c3a499",
        "original_source_order_and_all_290_native_cases_preserved": True,
        "retrieval_passes_per_original_source": 1,
        "source_rows_retained": 16,
        "byte_views": 15,
        "refused_ordinal": 13,
        "refusal": "jsonschema highest-ranked complete runtime group exceeds view limits; no truncation, reorder, replacement or second retrieval.",
        "synthetic_source_controls_passed": 16,
        "original_formatter_passed_and_10_ASTs_equal": True,
        "exact_tokenizer_measurement": measure,
        "after_target_contents_read_at_snapshot": False,
        "complete_representation_or_training_admitted": False,
        "partial_view_semantic_closure_proved": False,
        "next_target_measurement": "Separate frozen owner, algorithm and budgets; no input or ranking feedback from after targets. Not yet a result at this snapshot.",
        "evidence_directory": "../cell-e6-metrics-integration-20261119/e5-v2-input-readback",
    }
    current["E6"]["latest_Adopt_authority_addendum"] = {
        "original_eight_design_files_unchanged": True,
        "default_disabled_primitive_still_uncompiled_unwired": True,
        "four_envelopes": ["artifact-use grant", "selector decision", "final Root intent", "original controller authorization"],
        "new_live_revocation_source_is_required_not_supplied": True,
        "before_after_reads_do_not_prove_atomic_revocation_order": True,
        "additional_controls_planned": 12,
        "additional_controls_executed": 0,
        "evidence_directory": "../cell-e6-metrics-integration-20261119/adopt-authority-addendum",
    }
    current["interpretation"] = (
        "The original #6709 metrics integration and its controls remain unchanged. Original E1/E2 real student results remain ResearchNoUpdate; E3 bounded teacher material remains incomplete; E4 has not beaten strong single-model repair. E5 v1 remains inadmissible at every original prefix. Separate frozen before-only v2 retrieval has 15/16 byte views and exact measured full-template prefixes at most 3200 tokens; jsonschema ordinal13 is refused, target/output coverage remains unmeasured, and every training flag remains false. Independent E6 source d035 passes the original source gates and 34 native components but its Root mechanism parent fails strict log framing before ordinary NoUpdate starts; a marker-only repair is being validated with the original same-source component guard. Previous NoUpdate6 Unavailable, all prior failures, cold-D and Adopt authority gaps remain. The d1d actual Mac merge passed hepta-agentd unit and cognitive-write targets; the complete blocking workflow failed, including this checkpoint's own two helper unwrap regressions. The new Result-propagation correction has actual fmt/check pass; local lint stopped on absent locked registry material, and fresh-source lint/native is not claimed. Chain liveness, original F0 failures and unknown full-system cost remain. All ten joint qualification flags remain false, and independent branch evidence is not a joint execution."
    )
    assert current["qualification"] == old["qualification"] and len(current["qualification"]) == 10
    assert all(v is False for v in current["qualification"].values())
    for key in ["joint_execution_source", "joint_execution_tree", "historical_freeze_rewritten", "E1", "E2", "E3", "E4", "Chain", "metrics_integration_6709"]:
        assert current[key] == old[key], key
    write_json(JOINT / "CURRENT_PROGRESS.json", current)
    assert (JOINT / "CURRENT_PROGRESS.json").stat().st_size <= 512000
    (JOINT / "CURRENT_PROGRESS.md").write_text(f'''# E1–E6 continuation: helper correction and exact evidence

Observed: {current["observed_at_user_timezone"]} (America/New_York).

All ten joint qualification flags remain **false**. The original E1–E6 experiment identities, source order, budgets, acceptance rules and negative history are retained. This checkpoint follows d1d3896e2a2628977bc466cee1e00aea93971949; its exact previous CURRENT JSON is preserved in checkpoint-d1d-successor. Independent E5/E6 source results are evidence, not a new integrated joint execution.

## Concrete source correction

The prior checkpoint introduced two unwrap calls in the Mac fixture helper, and actual Mac/Linux CI denied them. The helper now returns io::Result, propagates canonicalize with ?, and returns tempdir_in directly. Six original test functions unwrap the result. No lint waiver, product guard, test assertion or second fixture is changed. The actual source SHA is e69d4ccd85f8a38d2720eccdaae57208a3f463951dac8bb5b833f89e89388bca.

The independent Mac checkout (238fc484 plus two fixture patches) performed the exact source CAS and original just fmt / --check, both exit 0 with unchanged validation inventory. Original just fix then failed in 1.062970125 seconds because offline Cargo lacked the locked Inflector archive; explicit lint and native tests were not reached. Five exact Git dependency caches are verified. Unpacked registry directories alone do not make offline Cargo material complete. This is not a new-source lint pass.

The older d1d actual merge f8aba45bc00865f522cc4e0a78c80078cd8ec062 independently passed noncached Mac hepta-agentd unit tests (92.1 s) and cognitive-write tests (3.3 s). Its overall Bazel job still failed in core/app-server. The two observations are kept distinct.

## Current experiment evidence

| Experiment | Actual result retained | Still required |
| --- | --- | --- |
| E1 | Both real 32-update students remain 1/4 on A; future panel 0/4. Original 56 evaluation calls spent. | Same-information retrieval comparison and positive unseen/future native gain. |
| E2 | Actual student action/recovery evaluation remains 0/4 recovery; no demonstrated retained new future capability. | Verified correction benefit and old-capability retention; no extra exhausted calls. |
| E3 | New SmolLM2 weight recovery is terminal incomplete; no new teacher calls. Original T2 history remains intact. | Authorized complete new material and matched-budget complementarity. |
| E4 | PP/CC/PC/CP remain 5/6 and do not beat the strong single-model baseline; original controls retained. | New-task communication benefit and edge/message/Cell controls under original budget. |
| E5 | Original 16 public projects, zero authenticated users and zero growth training. V1 remains failed. Separate v2 has 15 exact full-template inputs within 3200 tokens; jsonschema is refused in place. | Immutable-view target coverage, full output/EOS token bounds, original optimizer/compute mappings and independent future evaluation. Input fit alone is insufficient. |
| E6 | d035 original source gates and 34 native components pass; Root mechanism parent fails log framing before ordinary NoUpdate begins. Earlier NoUpdate6 Invalid(Unavailable) remains. | Marker-only same-source validation, complete ordinary NoUpdate, genuine Adopt authority, new C/cold recovery/new D/FinalUse/settlement. |

## E6 exact scope

Source d0353abfbf9ac783f0fe842fe313977e9d49bff9 retains all original authorization checks after durable Source completion. Missing/Pending observations no longer contend with the unique execution's CURRENT lane. This does not establish arbitrary same-run replay serialization. Original source checks passed 433 tests across 49 modules, 907 protected rows, 398 affected boundaries and the full 1159-boundary CLI. Original project lint, blob tests and 512000 gate passed.

The exact four original native families (11, 16, 5, 2) passed, with all case identities and zero failures/errors/skips verified. The subsequent Root mechanism parent failed because libtest placed the first success marker on its progress line. StalePrepare child assertions completed; Revoked and the ordinary NoUpdate parent did not run. The next change adds only an explicit newline and preserves exact-line assertions, the 64-read limit, every deadline and the requirement that all 34 prerequisites match the new source. New full CLI validation is in progress at this snapshot. No completed C/D, FinalUse or settlement is claimed.

The Adopt addendum keeps the eight original design files and default-disabled primitive intact. It separates the artifact-use grant, selector, Root intent and original controller authorization, and records missing live revocation/ordering semantics. Twelve further controls are planned; none ran. It is not production authority.

## E5 exact scope

The v2 policy and code were frozen before the one-pass retrieval. All 16 original rows remain. Fifteen byte views were produced; jsonschema ordinal 13 was rejected when the top complete runtime group could not fit. Nothing was truncated or replaced. Full original verifier cases remain outside the partial prompt; semantic closure is not claimed.

The pinned tokenizer measured complete native-chat prefixes for all fifteen views: loguru 2851 tokens and maximum attrs 2986. Input-only prefixes 1 and 4 fit; prefix 16 does not. Target coverage, complete output/EOS limits, full SFT positions, optimizer units, budgets and B/C are still absent. Every complete-representation and training flag remains false. No model forward, generation, native replay or training update ran. Subsequent after-target analysis must use a separate frozen owner and cannot feed back into these inputs.

## CI and publication boundaries

The d1d blocking workflow completed all 37 jobs: 20 successes, 12 failures, one cancellation and four skips. Engineering integrity, v8 and Windows private-state security succeeded; these do not qualify E6 business outcomes. Original own-Clippy failures and full logs are retained. The contract gate still interprets foreign Chain workflow references from historical base evidence as local paths; the verifier and historical bytes were not weakened or rewritten. Cargo-deny log retrieval failed, so its cause remains unknown.

The same base branch metadata was refreshed to actual 061334747ce9d87690c40df48eeedf239156b57d. No code or branch name changed. Old architecture-event failures remain. The new helper must receive fresh-source CI. The exact d1d 97-path original blob gate passed; this successor requires a separate exact-tree gate before nonforce CAS publication.

## Evidence map

All paths below are under qualification/cell-e6-metrics-integration-20261119. Archive manifests verify complete member names, bytes and SHA256 after reopening; parts stay below the original 512000-byte threshold.

| Directory | Scope |
| --- | --- |
| checkpoint-d1d-readback | Original d1d preparation failure, passing exact-object gate and publication receipts. |
| ci-d1d-complete | Full retrieved d1d CI logs, all-job observation, exact base/merge and metadata refresh. |
| mac-helper-clippy-fix | Minimal source diff, actual native6 fmt/source receipts and locked-material failure. |
| mac-native5-complete | Full earlier seed/native5 originals; no new test result. |
| e6-d035-readback | Selected exact source/native results, original Root failure and marker-only proposed correction. |
| e5-v2-input-readback | Full 161-file frozen review set, one-pass inputs and exact tokenizer originals. |
| e5-representation-review | V1 lower bound and independent v2 contract review. |
| adopt-authority-addendum | Separate authority/revocation design; planned controls only. |

Original #6709 source-metrics accounting is unchanged: terminal status alone does not count a completed adoption/use cycle. Historical E1/E2 future failures, E3 incomplete material, E4 negative controls, E5 v1 refusals, E6 parent failures and Chain F0/cost negatives remain in CURRENT JSON and their original commits. Unknown whole-system resource and monetary cost stays unknown. No automatic merge or reward expansion occurred.
''')
    print(json.dumps({"json_bytes": (JOINT / "CURRENT_PROGRESS.json").stat().st_size, "json_sha256": sha((JOINT / "CURRENT_PROGRESS.json").read_bytes()), "observed_at_utc": current["observed_at_utc"], "qualification": current["qualification"]}))


if __name__ == "__main__":
    main()
