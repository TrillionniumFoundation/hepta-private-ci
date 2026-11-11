#!/usr/bin/env python3
"""Compose the next evidence ledger without changing historical native receipts."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
WORK = BASE.parent
OLD = WORK / 'mem8-owner-followup-v6'
PREFIX = 'qualification/memory-cell-mem8-owner/run-001/'

def read(path):
    return json.loads(path.read_text())

def write(name, value):
    (BASE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--checkpoint', required=True)
    args = ap.parse_args()
    blockers = read(OLD / 'BLOCKERS.json')
    manifest = read(OLD / 'MANIFEST.json')
    sources = read(BASE / 'CURRENT_SOURCES_G.json')
    g_audit = read(BASE / 'ROOT_G_READBACK_AUDIT.json')
    source_audit = read(BASE / 'ROOT_SOURCE_READBACK_AUDIT.json')
    ci_publication = read(WORK / 'mem8-ci-followup-v9/PUBLICATION.json')
    ci_readback = read(WORK / 'mem8-ci-followup-v9/ROOT_READBACK_AUDIT.json')
    f1fd = read(WORK / 'mem8-dependency-closure/F1FD_FULL_SUMMARY.json')
    integrated = read(WORK / 'mem-final-composition-readonly/PUBLICATION.json')
    review_audit = read(BASE / 'ROOT_FINAL_REVIEW_READBACK_AUDIT.json')
    assert review_audit['passed'] and review_audit['full_remote_binary_readback']
    assert review_audit['offline_replay']['published_commit'] == integrated['commit']
    assert ci_readback['passed'] and ci_publication['ref_moved']
    assert f1fd['qualification']['passed'] == 268 and f1fd['qualification']['failed'] == 0
    assert g_audit['passed'] and source_audit['passed']
    assert len(sources['files']) == 38
    entries = read(BASE / 'SOURCE_STAGED_PUBLICATION.json')['entries'] + read(BASE / 'SOURCE_AUDIT_ENTRIES.json') + read(BASE / 'GATEWAY_AUDIT_ENTRIES.json') + read(BASE / 'FINAL_REVIEW_AUDIT_ENTRIES.json')
    blobs = {x['path'].removeprefix(PREFIX): x['sha'] for x in entries}
    g = copy.deepcopy(blockers['g_native_context_followup'])
    g.update({
        'status': 'PASSED_EXACT_G_SIX_REGRESSIONS_BUILD_FMT_FIX_ROOT_READBACK',
        'actual_g_native_result': sources['g_native_validation'],
        'existing_six_cases_only_planned': False,
        'actual_provider_case_executed': False,
        'new_model_calls_this_g_run': 0,
        'root_complete_readback': True,
        'root_audit': 'g-native-context/ROOT_G_READBACK_AUDIT.json',
        'root_audit_blob': blobs['g-native-context/ROOT_G_READBACK_AUDIT.json'],
        'complete_evidence_index': 'g-native-context/G_COMPLETE_EVIDENCE_INDEX.json',
        'native_archive_blob': '887bd1823ce74a0e579dac39deae6bd9a77fae8c',
        'native_archive_sha256': '3babe551f6a029803467dbc89f5ea949c88b93916bb20c3638bb5ba276b50a75',
        'native_archive_bytes': 49292,
        'all_five_phase_source_guards_clean': True,
        'provider_case_status': 'COMPILED_IGNORED_NOT_EXECUTED',
        'original_deployment_recovery_claimed': False,
        'unseen_benefit_evaluated': False,
    })
    source_inventory = {
        'status': 'PINNED_METADATA_VERIFIED_CURRENT_GLOBAL_EXPOSURE_UNKNOWN',
        'observed_at': source_audit['offline_replay']['metadata_observed_at_utc'],
        'known_exclusion_groups': 69,
        'mem_lineage_exclusion_groups': 67,
        'additional_prior_pilot_groups': 2,
        'catalog_groups': 178,
        'candidate_role_groups': 81,
        'known_excluded_candidate_groups': 65,
        'not_in_known_union_upper_bound': 16,
        'upper_bound_by_original_role': {'development': 7, 'retention_validation': 9},
        'verified_unseen_capacity': None,
        'admitted_new_sources': 0,
        'current_complete_exposure_certified': False,
        'working_state_gate_minimum': 20,
        'working_state_gate_minimum_each_role': 4,
        'historic_mem6_working_state_allocation': {'development': 16, 'retention_validation': 4},
        'optimistic_shortfall_to_W_total': 4,
        'optimistic_development_shortfall_to_historic_W_allocation': 9,
        'episodic_E_numeric_minimum': None,
        'episodic_E_requires_separate_pre_execution_protocol': True,
        'old_W_minima_transferred_to_E': False,
        'report': 'source-exclusion/REPORT.md',
        'per_group_provenance': 'source-exclusion/EXCLUSIONS.json',
        'capacity': 'source-exclusion/CAPACITY.json',
        'root_audit': 'source-exclusion/ROOT_SOURCE_READBACK_AUDIT.json',
        'archive_blob': '97bd07d1ec0efb027cc7737a47911ad128bd4c3c',
        'archive_bytes': 68968,
        'archive_sha256': '5d2780a32a4ae1b42925ce3b484c7b616e003a84679ae996b9862da427ad00b1',
        'archive_regular_members': 25,
        'root_full_download_and_offline_replay_passed': True,
        'new_host_jobs_by_root_audit': 0,
        'new_model_calls': 0,
        'new_actor_episodes': 0,
    }
    blockers['checkpoint_utc'] = args.checkpoint
    blockers['previous_checkpoint'] = {'commit': '743efac8d1c89e599b427da7e37f41d18af07985', 'checkpoint_utc': '2026-11-11 05:16:08 UTC'}
    validation = blockers['native_source_validation']
    prior_admission = validation.pop('source_admission_last_completed')
    prior_admission['historical_prior_attempt'] = True
    validation['source_admission_prior_completed_attempt'] = prior_admission
    blockers['provider_smoke_prepared']['last_observed_progress'] = 'Original 04:48 failed attempt: turn/start admitted inProgress, original 20-second completion wait failed, and its after-GET returned 502. Later 05:53 GET-only observations are recorded separately and do not settle the original model/provider outcome.'
    blockers['provider_smoke_prepared']['last_observed_progress_scope'] = 'ORIGINAL_NATIVE_ATTEMPT_NOT_CURRENT_GET_AVAILABILITY'
    blockers['g_native_context_followup'] = g
    blockers['source_exclusion_inventory'] = source_inventory
    blockers['final_source_composition'] = {
        'pr': 5935,
        'head': integrated['commit'],
        'tree': integrated['tree'],
        'parents': integrated['parents'],
        'base': integrated['base'],
        'changed_files': 112,
        'pairwise_path_conflicts': 0,
        'original_postimages_preserved': True,
        'root_original_tree_objects_checked': 73,
        'current_ci_status': 'AUTOMATIC_EXISTING_CI_IN_PROGRESS_NO_TERMINAL_QUALIFICATION_YET',
        'main_required_contexts_observed': ['CI required', 'Architecture required'],
        'review_base_branch_is_protected': False,
        'classic_protection_details_read': 'HTTP_403_NOT_INFERRED',
        'new_logic_in_composition': False,
        'provider_cases_remain_ignored': True,
        'source_component_passes_transferred_to_this_head': False,
        'review_bundle': 'integration-review/mem8-composition-ci-blocker-review-v2.tar.xz',
        'root_full_review_bundle_readback': 'integration-review/ROOT_FINAL_REVIEW_READBACK_AUDIT.json',
        'root_full_review_bundle_readback_passed': True,
        'review_bundle_members': 157,
        'final_blocker_review': 'integration-review/FINAL_BLOCKER_REVIEW_V2.json',
    }
    gateway = read(BASE / 'ROOT_GATEWAY_READBACK_AUDIT.json')
    assert gateway['passed'] and gateway['original_provider_final_status'] == 'UNKNOWN'
    blockers['provider_readonly_followup'] = {
        'status': 'ORIGINAL_JOURNAL_ZERO_MATCHES_CURRENT_GETS_200_ORIGINAL_OUTCOME_UNKNOWN',
        'original_journal_window_utc': ['2026-11-11 04:47:00 UTC', '2026-11-11 04:49:00 UTC'],
        'journal_queries': 1,
        'journal_entries': 0,
        'exact_original_identifier_matches': 0,
        'original_provider_final_status': 'UNKNOWN',
        'original_physical_provider_requests': None,
        'current_gets': gateway['current_get_observations'],
        'current_configuration_proves_historical_configuration': False,
        'safe_results_and_terminal_receipts_complete': True,
        'durable_process_stdout_full_readback': False,
        'remote_jobs_cancelled_or_retried': False,
        'new_models': 0,
        'root_audit': 'provider-gateway-readonly/ROOT_GATEWAY_READBACK_AUDIT.json',
        'root_audit_blob': blobs['provider-gateway-readonly/ROOT_GATEWAY_READBACK_AUDIT.json'],
    }
    blockers['owner_stages']['current_G_commit'] = sources['head']
    blockers['owner_stages']['current_G_tree'] = sources['tree']
    blockers['closed_this_followup'].extend([
        {'id': 'G-EXACT-SOURCE-COMPILE-AND-SIX-REGRESSIONS', 'status': 'PASSED_FULL_RAW_ROOT_READBACK', 'scope': 'Exact 9d9b G: six original Agentd cases, format, V8, real CLI build and scoped fix, zero retries, clean source. Ignored provider case not executed; no model or original-owner recovery claim.'},
        {'id': 'RMCP-DC96-THREE-ORIGINAL-FAILURES-READBACK', 'status': 'PASSED_FULL_RAW_ROOT_READBACK', 'scope': 'Original dc96 remains 265 pass / 3 fail. Separate same-source real-CLI repair is 3 pass / 0 fail; all 27 archive members and original 268 IDs independently checked. This is not one full 268-pass run.'},
        {'id': 'KNOWN-SOURCE-EXCLUSIONS-AND-CAPACITY-AUDIT', 'status': 'METADATA_AUDIT_COMPLETE_EXPOSURE_GATE_REMAINS_OPEN', 'scope': 'All 69 proven exclusions, 16-candidate upper bound and W/E gate distinction verified with full original CAS and selected metadata. No candidate is certified unseen.'},
    ])
    dep = blockers['dependency_consumer_followup']
    dep['published_source_pr'] = 5934
    dep['f1fd_full_rmcp_followup'] = copy.deepcopy(f1fd)
    dep['f1fd_full_rmcp_followup']['root_complete_archive_readback'] = True
    dep['f1fd_full_rmcp_followup']['evidence_commit'] = ci_publication['commit']
    dep['f1fd_full_rmcp_followup']['root_audit_path'] = 'qualification/memory-cell-mem8-ci-followup/checkpoint-v9/ROOT_READBACK_AUDIT.json'
    dep['rmcp_same_source_cli_followup']['complete_raw_archive_root_readback'] = 'PASSED_ALL_27_MEMBERS_ORIGINAL_268_IDS_AND_THREE_REPAIR_IDS'
    dep['rmcp_same_source_cli_followup']['evidence_commit'] = '0e1817df5e97b6cf4916a6b0ca7b43602c03fd4e'
    dep['matrix_production_candidate']['source_commit_publication'] = 'ORIGINAL_GIT_COMMIT_AND_TREE_PUBLISHED_AND_VERIFIED'
    dep['original_dependency_sources_published'] = {
        'dc96': {'commit': 'dc96a441312e239c165c1642880084dfeccc2c71', 'tree': '7796279284170f0f2c92449c1185eecac1f4f1b6', 'parent': '96038ccf0660154fac143ba6cbe4be81e00813e8'},
        'f1fd': {'commit': 'f1fd544b3e12ed6aca83872cdeda8114a1e058c0', 'tree': 'fff40d06312d4f6a185772cd8a62a618d55f31cf', 'parent': 'dc96a441312e239c165c1642880084dfeccc2c71'},
        'original_objects_preserved': True,
        'all_65_postimage_mode_type_blob_size_matches': True,
    }
    by_id = {x['id']: x for x in blockers['open']}
    by_id['ORDINARY-OWNER-BRIDGE']['finding'] += ' Exact G now separately compiles the ignored provider path and passes six existing episodic cases with clean source; the provider case itself has zero executions.'
    by_id['ORDINARY-OWNER-BRIDGE']['closure'] = 'Bind the already implemented and qualified bridge to the retained original deployed writer, caller and authenticated source adapter; recover the exact cut and demonstrate ordinary import/read/replay/withdrawal while preserving original tombstones and uncertain-commit identity.'
    by_id['PROVIDER-RUNTIME-BINDING']['finding'] = 'The original 55951 ordinary fixture has 0 passed / 1 failed, one logical turn admitted and no observed model terminal. G separately passed six non-provider cases; its ignored native context provider case remains unexecuted. Exact original reconciliation is required; physical provider request count remains unknown.'
    by_id['PROVIDER-RUNTIME-BINDING']['finding'] += ' One bounded query of the original gateway window found zero matching records; three current GETs returned 200. Neither observation settles the original turn.'
    by_id['SOURCE-OWNERSHIP-EXPOSURE-AND-TRUST']['finding'] += ' Pinned metadata now proves at least 69 exclusions; the remaining candidate upper bound is 16 (7 development, 9 retention_validation), all current exposure UNKNOWN. Hash and provenance validation does not authenticate current global exposure or original authority.'
    by_id['WORKING-STATE-SCIENTIFIC-GATE']['finding'] += ' Even optimistically the current residual catalog cannot meet the unchanged W minimum of 20 sources; the historical 16/4 allocation would require at least nine additional development groups. E has a separately required protocol, not an inherited W minimum.'
    by_id['HOSTED-CI']['finding'] = 'Exact common MEM, Source A, complete 66f owner CI, original Windows/Linux signed-credit cases, F2 focused groups, G six regressions, and f1fd full Matrix 30/0 have passed their recorded scopes. The original full f1fd RMCP suite now also passed 268/0 with zero retries, all original unique IDs, same-source CLI and clean scoped fix; its complete archive is root-read-back. Final combined source 2ae5215 (112 disjoint paths) is published in #5935 and its existing automatic CI is in progress. No component result is transferred to the combination or to unmet required checks.'
    by_id['HOSTED-CI']['status'] = 'COMPONENT_GATES_PASSED_FINAL_COMPOSITION_REQUIRED_CI_IN_PROGRESS'
    by_id['HOSTED-CI']['closure'] = 'Adjudicate the existing CI required and Architecture required checks and their actual dependencies on the final composition, retaining exact tested source, original logs and any failed or excluded scope. No new all-platform requirement is inferred from a package-level pass.'
    blockers['closed_this_followup'].append({'id':'FULL-F1FD-ORIGINAL-RMCP-CONSUMER-SUITE', 'status':'PASSED_FULL_RAW_ROOT_READBACK', 'scope':'268 original unique cases passed, zero failed/selected skipped/retried; seven unselected. Fresh UUID and all 268 timestamps verified; real same-source CLI and clean scoped fix. Exact f1fd only; integrated 2ae has its own pending CI.'})
    blockers['provider_original_failure_evidence'] = {
        'scope': 'Original failed native 55951 and two existing read-only settlement attempts, with explicitly derived redacted observations',
        'archive': 'provider-original-failure/mem8-provider-55951-original-failure-redacted-v3.tar.xz',
        'archive_blob': '92cde56a3c1aea8fc0d7353621ebeb2ede3257e5',
        'archive_bytes': 56432,
        'archive_sha256': '5cbc5b4d293b57980d9efe02bea0c0ec0bfe0ae165e1c9881801c7bc9cd1ae3c',
        'safe_regular_members': 64,
        'root_full_remote_readback_passed': True,
        'native_selected': 1, 'native_passed': 0, 'native_failed': 1, 'native_retries': 0,
        'physical_provider_requests': None, 'remote_provider_outcome': 'UNKNOWN',
        'readonly_v1_status': 'FAILED_ON_OLD_LOGS_MESSAGE_COLUMN',
        'readonly_v2_status': 'COMPLETED_ORIGINAL_DB_AND_WAL_UNCHANGED_NO_TERMINAL',
        'readonly_v2_completed_at': '2026-11-11T05:29:21.693505+00:00',
        'original_native_raw_junit_observations_binary_unchanged': True,
        'unsafe_original_projections_excluded': True,
        'unsafe_previously_uploaded_unreferenced_objects_excluded': True,
        'unsafe_objects_deleted_from_github_claimed': False,
        'privacy_erratum': 'provider-original-failure/PROJECTION_PRIVACY_ERRATUM.json',
        'new_owner_starts_or_model_replays': 0,
        'new_database_reads_for_redaction': 0,
    }
    blockers['boundaries'].extend([
        'G native compilation and six regression passes do not execute the ignored real-provider context case.',
        'The 16-source residual count is an upper bound outside known exclusions, not verified unseen capacity.',
        'W source minima and the historical W allocation do not become an invented E threshold.',
        'A healthy later GET or empty bounded gateway journal cannot settle the original admitted model turn.',
    ])
    manifest['checkpoint_utc'] = args.checkpoint
    manifest['previous_checkpoint_commit'] = '743efac8d1c89e599b427da7e37f41d18af07985'
    manifest['ci_evidence_parent'] = ci_publication['commit']
    manifest['current_sources'] = {'path': 'CURRENT_SOURCES.json', 'head': sources['head'], 'tree': sources['tree'], 'paths': 38, 'scope': 'MEM component source inventory; the final 112-path integration has a separate source identity and pending CI.', 'complete_owner_native_base': sources['complete_owner_native_base'], 'qualification_retains_each_exact_head': True}
    manifest['g_native_context_followup'] = g
    manifest['source_exclusion_inventory'] = source_inventory
    manifest['provider_readonly_followup'] = blockers['provider_readonly_followup']
    manifest['dependency_source_pr'] = 5934
    manifest['final_source_composition'] = blockers['final_source_composition']
    manifest['provider_original_failure_evidence'] = blockers['provider_original_failure_evidence']
    manifest['current_native_counts']['G_existing_regression_cases'] = {'passed': 6, 'failed': 0, 'unselected': 782, 'provider_case_executions': 0}
    manifest['current_native_counts']['dc96_rmcp_original'] = {'passed': 265, 'failed': 3, 'selected_unique': 268, 'retries': 0}
    manifest['current_native_counts']['dc96_rmcp_separate_cli_recheck'] = {'passed': 3, 'failed': 0, 'retries': 0}
    manifest['current_native_counts']['f1fd_full_rmcp'] = {'passed': 268, 'failed': 0, 'selected_skipped': 0, 'filtered_or_ignored': 7, 'retries': 0}
    for row in [
        {'path': 'g-native-context/NATIVE_EVIDENCE.tar.xz', 'bytes': 49292, 'sha256': '3babe551f6a029803467dbc89f5ea949c88b93916bb20c3638bb5ba276b50a75', 'git_blob_sha': '887bd1823ce74a0e579dac39deae6bd9a77fae8c', 'members': 67, 'scope': 'Exact G native six-case result, all five phase receipts, source and actual CLI identity; ignored provider case not executed.'},
        {'path': 'g-native-context/FORMAT_EVIDENCE.tar.xz', 'bytes': 41624, 'sha256': 'd2fee84f30985c162ef778c9956c033c74f252bef8be5a7c03ae84c290056c14', 'git_blob_sha': '82b44ef97739e5e1afb1fb993d16de1545517a4e', 'members': 43, 'scope': 'Original G formatter inputs, postimages and clean donor receipts; not a separate native run.'},
        {'path': 'static-reviews/mem8-static-owner-and-successor-review.tar.xz', 'bytes': 20424, 'sha256': '791f0503aa970ea041ce4e4bf1f485bd280657593ba2c2127b4a5d16e95ce1af', 'git_blob_sha': '37cb563274566a559352724e36a1f52c7cfb69be', 'members': 12, 'scope': 'Independent static review and minimum original deployment inputs; requires separately retained exact source artifacts.'},
        {'path': 'source-exclusion/source-exclusion-24files.tar.xz', 'bytes': 68968, 'sha256': '5d2780a32a4ae1b42925ce3b484c7b616e003a84679ae996b9862da427ad00b1', 'git_blob_sha': '97bd07d1ec0efb027cc7737a47911ad128bd4c3c', 'members': 25, 'scope': '24 original source-metadata files and member manifest, full root download/replay passed; current exposure UNKNOWN.'},
        {'path': 'provider-gateway-readonly/PROVIDER_READONLY_EVIDENCE.tar.xz', 'bytes': 10824, 'sha256': '31deecb726696a4bf05b1018243757e99e4f0e63437cdd9040cfa3edd9b06ed7', 'git_blob_sha': '6d81a371568ca552ea4384b0b289034b150c9f86', 'members': 13, 'scope': 'Original-window bounded journal and three current GET-only observations; full safe result/terminal readback, original outcome UNKNOWN. Raw process stdout frontend read was incomplete and that stream is excluded.'},
        {'path': 'provider-original-failure/mem8-provider-55951-original-failure-redacted-v3.tar.xz', 'bytes': 56432, 'sha256': '5cbc5b4d293b57980d9efe02bea0c0ec0bfe0ae165e1c9881801c7bc9cd1ae3c', 'git_blob_sha': '92cde56a3c1aea8fc0d7353621ebeb2ede3257e5', 'members': 64, 'scope': 'Original 55951 failure and existing settlement evidence. Native bytes unchanged; two unsafe projections excluded and replaced by explicitly derived redactions with erratum. Original remote outcome UNKNOWN.'},
        {'path': 'integration-review/mem8-composition-ci-blocker-review-v2.tar.xz', 'bytes': 392476, 'sha256': 'e5988a03861667afeb195e9c09bd6f43f89ea87d562ed59f281e2bded6afa46d', 'git_blob_sha': 'ddbdcb458f0336d6162d9a90b942a3589c134eef', 'members': 157, 'scope': 'Published 112-path composition, 73 original Git trees, 107 CI source files, 121 frozen CI files, 30 blocker evidence pins and independent V2 review. Complete remote binary and every member verified by root, offline replay passed. No combined-head CI terminal or new model result claimed.'},
    ]:
        assert row['path'] not in {x['path'] for x in manifest['archives']}
        manifest['archives'].append(row)
    for path in ['g-native-context/ROOT_G_READBACK_AUDIT.json', 'source-exclusion/ROOT_SOURCE_READBACK_AUDIT.json', 'provider-gateway-readonly/ROOT_GATEWAY_READBACK_AUDIT.json', 'integration-review/ROOT_FINAL_REVIEW_READBACK_AUDIT.json']:
        manifest['audits'].append({'path': path, 'git_blob_sha': blobs[path]})
    manifest['notes'].append('This checkpoint adds exact G native qualification, actual complete f1fd RMCP 268/0, full dc96 evidence readback, the 69-group exclusion audit, explicit provider projection correction and the complete 157-member composition/CI/blocker review. Old source-specific results and failures remain unchanged; the combined source has its own ongoing existing CI. No whole-repository or model-benefit result is inferred.')
    manifest['notes'] = [
        ('Historical v6 composition: owner-binding eb3616fdce370fc6bd23a6ddf17cd94265a5bcd3 with CI 26467689b04bd183fef2dc347fdd085fcde6d41e produced checkpoint 743efac8d1c89e599b427da7e37f41d18af07985. This later composition retains that ancestry and adds CI evidence through the separately recorded ci_evidence_parent.' if note.startswith('The historical owner snapshot incorporated CI evidence commit') else note)
        for note in manifest['notes']
    ]
    assert len(blockers['open']) == manifest['open_original_blocker_count'] == 10
    assert not blockers['production_adoption'] and not manifest['production_adoption']
    assert blockers['physical_provider_requests'] is None and manifest['physical_provider_requests'] is None
    write('BLOCKERS.json', blockers)
    write('MANIFEST.json', manifest)
    write('CURRENT_SOURCES.json', sources)
    write('CORE_COMPOSITION_AUDIT.json', {'checkpoint_utc': args.checkpoint, 'open_original_blockers': 10, 'archives': len(manifest['archives']), 'source_paths': 38, 'original_provider_physical_requests': None, 'new_scored_memory_actor_episodes': 0, 'production_adoption': False, 'g_provider_executions': 0, 'passed': True})
    print(json.dumps({'written': ['BLOCKERS.json', 'MANIFEST.json', 'CURRENT_SOURCES.json', 'CORE_COMPOSITION_AUDIT.json'], 'archives': len(manifest['archives']), 'open_original_blockers': 10}))

if __name__ == '__main__':
    main()
