#!/usr/bin/env python3
"""Check current navigation/profile identity, never synthesize execution evidence."""
from __future__ import annotations
import argparse
import json
import subprocess
import tomllib
from pathlib import Path
from report_module_evidence import ROOT, check_symbol, check_test_selector, validate_contract
from check_invariant_evidence import load, require, safe

REGISTRY = 'config/pon/applicability-v1.json'
CLASSES = {'source-binding', 'local-execution', 'historical-receipt',
           'hosted-head-check', 'prospective-merge-check', 'external-acceptance'}
NATIVE_STORAGE_PROFILE = 'native-authenticated-storage-v1'
EVALUATION_QUORUM_PROFILE = 'native-evaluation-quorum-v2'
MODEL_EVOLUTION_PROFILE = 'model-evolution-v5'
MODEL_TASK_WINDOWS_PROFILE = 'model-task-windows-v1'
CELL_P2P_PROFILE = 'cell-p2p-v1'
NATIVE_CONTINUATION_PROFILES = {
    'native-growth-reference-v2': {
        'configuration': 'config/pon/growth-reference-v2.json',
        'revision_pointer': 'consensus_revision', 'consensus_revision': 17,
        'document': 'docs/development/specs/pon/PERMANENT_ACCOUNT_STORAGE_BOUNDARY.md',
        'entrypoint': {'path': 'trillionnium/crates/trnm-pon-node/src/store/growth_reference.rs',
                       'symbol': 'Node::growth_reference_observation'},
        'modules': ['M00', 'M06', 'M07', 'M08', 'M17'],
        'tests': ['trillionnium/crates/trnm-pon-node/src/store/growth_reference_tests.rs::' + name
                  for name in ('native_growth_reference_signed_zero_reentry_and_cold_recovery',
                               'native_growth_reference_reorganization_cut_and_corruption_fail_stop',
                               'native_growth_reference_65537_signed_accounts_and_cold_reopen',
                               'native_growth_reference_public_checked_apis_bind_actual_profile_parent')],
    },
    'native-local-budget-obligations-v1': {
        'configuration': None, 'revision_pointer': None, 'consensus_revision': None,
        'document': 'docs/development/specs/pon/REWARD_BUDGETS_V1.md',
        'entrypoint': {'path': 'trillionnium/crates/trnm-pon-node/src/store/native_budget.rs',
                       'symbol': 'Node::reserve_native_budget_v1'},
        'modules': ['M07', 'M12', 'M15', 'M17'],
        'tests': ['trillionnium/crates/trnm-pon-node/src/store/native_budget_tests.rs::' + name
                  for name in ('native_signed_funding_and_exact_operations_survive_both_backends_reopen',
                               'fork_or_spent_source_denies_new_intent_but_preserves_resource_and_target_receipt',
                               'transaction_failure_leaves_no_partial_record_head_or_double_resource_charge',
                               'cold_open_refuses_deleted_oversized_and_forged_funding_records',
                               'native_mining_funds_keep_maturity_and_do_not_create_payment_authority',
                               'abrupt_exit_preserves_committed_resource_reservations_and_pending_intent')],
    },
}
MODEL_AND_CELL_TESTS = {
    MODEL_EVOLUTION_PROFILE: {
        'trillionnium/crates/trnm-protocol/tests/integer_evolution_v3.rs': {
            'exact_maximum_payload_and_envelope_roundtrip_preserve_old_codec',
            'aliases_empty_graph_overbudget_and_noncanonical_bytes_are_refused',
        },
        'trillionnium/crates/trnm-mvcc-fee/tests/model_evolution_v5.rs': {
            'actual_joint_router_expert_then_base_and_mask_adopt_from_real_successor_parent',
            'native_refuses_forged_parent_hash_basis_alias_noop_and_cross_profile',
        },
        'trillionnium/crates/trnm-pon-node/tests/evolution_cli.rs': {
            'explicit_revision16_cli_is_distinct_reopens_and_refuses_revision15_store',
            'signed_joint_update_has_native_packet_membership_and_survives_store_reopen',
        },
        'formal/pon-nakamoto-v1/test_model_evolution_oracle.py': {
            'ModelEvolutionOracleTests.test_committed_context_wire_model_and_successor_vectors',
            'ModelEvolutionOracleTests.test_enabled_graph_ties_and_disabled_router_maximum',
            'ModelEvolutionOracleTests.test_checked_normalization_noop_range_and_basis_equivalence',
            'ModelEvolutionOracleTests.test_complete_model_canonical_reserved_byte_and_old_magic',
        },
    },
    MODEL_TASK_WINDOWS_PROFILE: {
        'trillionnium/crates/trnm-mvcc-fee/tests/model_evolution_v5.rs': {
            'pinned_new_text_windows_select_frozen_roots_and_replay_actual_parent_controls_at_activation',
            'external_data_owner_signature_roots_order_and_repeated_content_fail_closed',
        },
        'trillionnium/crates/trnm-pon-node/tests/evolution_cli.rs': {
            'external_window_has_real_pnw1_membership_and_pinned_store_reopen',
            'window_cli_requires_every_pin_and_refuses_substitution_wrong_owner_or_reopen',
        },
        'formal/pon-nakamoto-v1/test_model_task_windows_oracle.py': {
            'ModelTaskWindowsOracleTests.test_signed_manifest_and_native_differential_fixture_are_reproducible',
            'ModelTaskWindowsOracleTests.test_full_content_hash_and_snapshot_root_detect_replacement',
            'ModelTaskWindowsOracleTests.test_token_filter_clipping_and_bias_are_explicit',
        },
    },
    CELL_P2P_PROFILE: {
        'trillionnium/crates/trnm-data-availability/src/cell/tests.rs': {
            'origin_offline_independent_replicas_multisource_and_corrupt_cache_repair',
            'missing_chunk_never_publishes_partial_payload_and_verified_cache_resumes',
            'wrong_pins_context_chunks_and_noncanonical_manifests_fail_closed',
            'foreign_database_is_not_repurposed',
            'corrupt_network_supplier_is_rejected_and_honest_peer_completes_same_pin',
            'exhausted_transport_budget_keeps_verified_chunks_for_retry',
            'slow_response_cannot_extend_absolute_deadline_and_honest_peer_keeps_pin',
        },
    },
}
EVALUATION_QUORUM_TESTS = {
    'trillionnium/crates/trnm-mvcc-fee/tests/evaluation_quorum_v2.rs': {
        'independent_reference_vectors_match_native_domains_counts_and_records',
        'fresh_profile_refuses_attested_models_and_cross_version_replay',
    },
    'trillionnium/crates/trnm-pon-node/tests/model_evidence_v3.rs': {
        'explicit_quorum_native_release_survives_one_absence_and_hash_appeal_with_durable_reorg',
    },
    'trillionnium/crates/trnm-pon-node/tests/model_composition_v4.rs': {
        'quorum_profile_replays_two_composition_generations_and_zero_score_components',
    },
    'trillionnium/crates/trnm-pon-node/tests/evaluation_quorum_cli.rs': {
        'explicit_cli_profile_has_distinct_context_and_cannot_reopen_a_legacy_store',
    },
    'formal/pon-nakamoto-v1/test_native_evaluation_quorum_oracle.py': {
        'NativeEvaluationQuorumReferenceTests.test_exact_retained_vectors_recompute_without_native_output',
        'NativeEvaluationQuorumReferenceTests.test_one_missing_is_tolerated_but_never_becomes_a_vote',
        'NativeEvaluationQuorumReferenceTests.test_plan_commits_disqualification_without_shrinking_threshold',
        'NativeEvaluationQuorumReferenceTests.test_actual_conflicts_recount_and_hash_appeal_is_record_only',
    },
}
NATIVE_STORAGE_ENTRY = {
    'path': 'trillionnium/crates/trnm-pon-node/src/store.rs',
    'symbol': 'Node::open_with_authenticated_state',
}
NATIVE_STORAGE_TESTS = {
    'trillionnium/crates/trnm-pon-node/src/native_authenticated_tests.rs': {
        'native_authenticated_signed_growth_branches_reopen_and_compact_queries',
        'native_authenticated_namespaces_missing_nodes_and_corrupt_records_fail_closed',
        'native_authenticated_process_exit_before_commit_cold_recovers_without_destructors',
    },
    'trillionnium/crates/trnm-pon-node/src/store/authenticated_migration_tests.rs': {
        'authenticated_migration_preserves_signed_branches_and_irreversible_local_facts',
        'authenticated_migration_retains_partial_reorganization_then_target_recovers_once',
        'authenticated_migration_rechecks_retained_authority_including_inactive_branches',
        'authenticated_migration_rejects_external_owner_journal_and_required_marker',
        'authenticated_migration_atomic_target_creation_never_overwrites_a_racing_destination',
        'authenticated_migration_last_callback_cannot_hide_raw_file_or_receipt_changes',
        'authenticated_migration_process_exit_leaves_pending_and_source_reopens',
    },
    'trillionnium/crates/trnm-pon-node/tests/authenticated_storage_cli.rs': {
        'explicit_backend_mines_and_cold_reopens_the_same_authenticated_native_state',
        'explicit_and_default_storage_namespaces_reject_each_other_without_changing_the_database',
        'invalid_backend_scope_and_external_owner_combinations_reject_before_open',
    },
    'formal/pon-nakamoto-v1/test_native_authenticated_storage_oracle.py': {
        'MigrationPreservationOracle.test_every_retained_table_is_checked_including_empty_ones',
        'MigrationPreservationOracle.test_retained_values_cannot_change_type_or_contents',
        'SignedApplicationControls.test_self_consistent_state_records_cannot_change_signed_transfer_amount',
        'SignedApplicationControls.test_native_compact_query_is_independently_checked_when_present',
    },
}


def validate_native_continuation_profile(profile: dict) -> None:
    """Keep the new native reference and local obligations in their exact scope."""
    expected = NATIVE_CONTINUATION_PROFILES[profile['id']]
    for field in ('configuration', 'revision_pointer', 'consensus_revision',
                  'document', 'entrypoint', 'modules'):
        require(profile[field] == expected[field], 'native continuation boundary identity')
    require(set(expected['tests']) <= set(profile['tests']),
            'native continuation recovery and negative controls required')
    require(profile['evidence_class'] == 'source-binding' and profile['receipt'] is None,
            'native continuation navigation cannot claim execution acceptance')


def validate_evaluation_quorum_profile(profile: dict) -> None:
    """Preserve explicit native-profile selection and exact executable bindings."""
    require(profile['configuration'] == 'config/pon/public-evaluation-quorum-v2.json' and
            profile['revision_pointer'] == 'genesis_overrides.consensus_revision' and
            profile['consensus_revision'] == 15,
            'evaluation quorum requires its explicit revision15 configuration')
    require(profile['entrypoint'] == {
        'path': 'trillionnium/crates/trnm-pon-node/src/main.rs', 'symbol': 'run'},
        'evaluation quorum requires the actual profile-selecting Node CLI')
    require(profile['document'] ==
            'docs/protocol/pon-nakamoto-v1/details/NATIVE_EVALUATION_QUORUM_V2.md' and
            set(profile['modules']) == {'M06', 'M10', 'M11', 'M15'},
            'evaluation quorum native replay and release contract identity')
    required = {path + '::' + symbol for path, symbols in EVALUATION_QUORUM_TESTS.items()
                for symbol in symbols}
    require(required <= set(profile['tests']),
            'evaluation quorum native, legacy, Node, CLI and independent oracle controls required')


def validate_native_storage_profile(profile: dict) -> None:
    """A local storage namespace cannot acquire consensus or legacy-open authority."""
    require(all(profile[field] is None for field in (
        'configuration', 'revision_pointer', 'consensus_revision')),
        'native authenticated storage is local, not a consensus revision')
    require(profile['entrypoint'] == NATIVE_STORAGE_ENTRY,
            'native authenticated storage requires the explicit opener')
    require(profile['document'] ==
            'docs/protocol/pon-nakamoto-v1/details/NATIVE_AUTHENTICATED_STORAGE_V1.md',
            'native authenticated storage contract identity')
    require(set(profile['modules']) == {'M06', 'M07', 'M08', 'M15', 'M17'},
            'native authenticated storage responsibility coverage')
    required = {path + '::' + symbol for path, symbols in NATIVE_STORAGE_TESTS.items()
                for symbol in symbols}
    require(required <= set(profile['tests']),
            'native authenticated storage control selector coverage')


def validate_model_and_cell_profile(profile: dict) -> None:
    """Byte transport and optional task sources cannot inherit another authority."""
    identifier = profile['id']
    require(identifier in MODEL_AND_CELL_TESTS, 'unknown model/cell boundary')
    if identifier == CELL_P2P_PROFILE:
        require(all(profile[field] is None for field in (
            'configuration', 'revision_pointer', 'consensus_revision')),
            'cell transport is local byte distribution, not a consensus revision')
        entry = {'path': 'trillionnium/crates/trnm-data-availability/src/bin/trnm-cell.rs',
                 'symbol': 'run'}
        document = 'docs/protocol/pon-nakamoto-v1/details/CELL_P2P_V1.md'
        modules = {'M09'}
    else:
        require(profile['configuration'] == 'config/pon/model-evolution-v5.json' and
                profile['revision_pointer'] == 'consensus_revision' and
                type(profile['consensus_revision']) is int and profile['consensus_revision'] == 16,
                'model evolution and pinned task windows require explicit revision16')
        entry = {'path': 'trillionnium/crates/trnm-pon-node/src/main.rs', 'symbol': 'run'}
        if identifier == MODEL_EVOLUTION_PROFILE:
            document = 'docs/development/specs/pon/MODEL_EVOLUTION_V5.md'
            modules = {'M00', 'M06', 'M10', 'M11', 'M15'}
        else:
            document = 'docs/development/specs/pon/MODEL_TASK_WINDOWS_V1.md'
            modules = {'M06', 'M11', 'M15'}
    require(profile['entrypoint'] == entry, 'model/cell boundary requires its actual explicit CLI')
    require(profile['document'] == document and set(profile['modules']) == modules,
            'model/cell contract and responsibility identity')
    required = {path + '::' + symbol for path, symbols in MODEL_AND_CELL_TESTS[identifier].items()
                for symbol in symbols}
    require(required <= set(profile['tests']), 'model/cell negative and native control coverage')


def profile_table(profiles: list[dict]) -> str:
    lines = ['| Boundary / modules | Configuration / revision | Contract | Entrypoint | Exact test selector |',
             '|---|---|---|---|---|']
    for row in profiles:
        config = row['configuration']
        configuration = (f"[{Path(config).name}](../../{config}), revision{row['consensus_revision']}"
                         if config else 'Local/research boundary; no consensus revision')
        doc = row['document']
        entry = row['entrypoint']
        lines.append('| ' + ' | '.join([row['id'] + ' / ' + ', '.join(row['modules']),
                     configuration, f'[{Path(doc).stem}](../../{doc})',
                     f"[{entry['symbol']}](../../{entry['path']})",
                     '<br>'.join(row['tests'])]) + ' |')
    return '\n'.join(lines)


def validate(root: Path = ROOT) -> dict:
    root = Path(root).resolve()
    data = load(safe(root, REGISTRY))
    require(data['schema'] == 'pon-applicability-v1', 'applicability schema')
    require(set(data['evidence_classes']) == CLASSES, 'evidence class separation')
    require(data['module_contracts'] == 'config/pon/module-contracts-v1.json' and
            data['module_maturity'] == 'config/pon/module-maturity-v1.json' and
            data['source_inventory'] == 'config/portability-inventory-v1.json',
            'canonical authority changed')
    safe(root, data['source_inventory'])
    validate_contract(root)
    contracts = load(safe(root, data['module_contracts']))['modules']
    maturity = {m['id']: m for m in load(safe(root, data['module_maturity']))['modules']}
    rows = []
    for module in contracts:
        safe(root, module['specification'])
        for procedure in maturity[module['id']]['responsibilities']:
            rows.append({'module': module['id'], 'document': module['specification'],
                         **procedure, 'evidence_class': 'source-binding'})
    profiles = data['profiles']
    require(len(profiles) == len({p['id'] for p in profiles}), 'duplicate applicability profile')
    require({p['id'] for p in profiles} == {'evaluation-v1', 'lifecycle-v2', 'lifecycle-v3',
            'lifecycle-v4', 'checkpoint-tile-v1', 'local-pool-reconciliation',
            'protected-hello-handoff', 'integer-factor-v2', 'public-intake-v3-r10',
            'continuity-v1', 'model-evidence-v3', 'w1-verifier-equivalence',
            'history-state-resource-bounds', 'internal-error-identity', 'model-composition-v4',
            'account-archive-research-v1', 'model-window-history-v1', NATIVE_STORAGE_PROFILE,
            EVALUATION_QUORUM_PROFILE, MODEL_EVOLUTION_PROFILE, MODEL_TASK_WINDOWS_PROFILE,
            CELL_P2P_PROFILE, *NATIVE_CONTINUATION_PROFILES},
            'applicability profile coverage')
    for profile in profiles:
        require(profile['modules'] and set(profile['modules']) <= set(maturity), 'profile modules')
        require(len(profile['modules']) == len(set(profile['modules'])), 'duplicate profile module')
        if profile['id'] == NATIVE_STORAGE_PROFILE:
            validate_native_storage_profile(profile)
        if profile['id'] == EVALUATION_QUORUM_PROFILE:
            validate_evaluation_quorum_profile(profile)
        if profile['id'] in MODEL_AND_CELL_TESTS:
            validate_model_and_cell_profile(profile)
        if profile['id'] in NATIVE_CONTINUATION_PROFILES:
            validate_native_continuation_profile(profile)
        safe(root, profile['document'])
        check_symbol(root, profile['entrypoint'])
        require(profile['tests'], 'missing profile tests')
        require(len(profile['tests']) == len(set(profile['tests'])), 'duplicate profile test selector')
        for selector in profile['tests']:
            check_test_selector(root, selector)
        require(profile['evidence_class'] == 'source-binding' and profile['receipt'] is None,
                'source navigation masquerades as execution receipt')
        if profile['configuration'] is not None:
            config = load(safe(root, profile['configuration']))
            value = config
            for part in profile['revision_pointer'].split('.'):
                value = value[part]
            require(type(value) is int and value == profile['consensus_revision'], 'profile revision drift')
        else:
            require(profile['consensus_revision'] is None and profile['revision_pointer'] is None,
                    'transport/local policy masquerades as consensus revision')
    authority = safe(root, 'docs/architecture/TRNM_DOCUMENTATION_AUTHORITY_V1.md').read_text()
    expected_table = '<!-- applicability-table:start -->\n' + profile_table(profiles) + '\n<!-- applicability-table:end -->'
    require(expected_table in authority, 'documentation applicability table drift')
    snapshot = load(safe(root, 'docs/development/CURRENT_SNAPSHOT_V1.json'))
    cargo = tomllib.loads(safe(root, 'trillionnium/Cargo.toml').read_text())
    require(snapshot['workspace_packages'] == len(cargo['workspace']['members']), 'snapshot package drift')
    require(snapshot['applicability_registry'] == REGISTRY, 'snapshot applicability authority')
    require(data['delivery'] == {'candidate_identity': 'derive-from-git-at-verification',
            'hosted_head_status': 'not-established-by-this-registry',
            'prospective_merge_status': 'not-established-by-this-registry',
            'production_activation': False}, 'unearned delivery status')
    return {'result': 'PASS', 'procedures': rows, 'profiles': profiles,
            'tests_executed_by_this_checker': False, 'acceptance_granted': False}


def markdown(result: dict) -> str:
    lines = ['| Module / procedure | Document | Source owners | Controlled entrypoint | Test selectors | Evidence class |',
             '|---|---|---|---|---|---|']
    for row in result['procedures']:
        refs = lambda values: '<br>'.join(v['path'] + '::' + v['symbol'] for v in values) or 'none'
        entry = row['controlled_entrypoint']
        lines.append('| ' + ' | '.join([row['operation'], row['document'], refs(row['runtime_symbols']),
                     refs([entry]) if entry else 'none', '<br>'.join(row['evidence_selectors']) or 'none',
                     row['evidence_class']]) + ' |')
    return '\n'.join(lines)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--format', choices=['json', 'markdown'], default='json')
    args = parser.parse_args()
    result = validate()
    git = lambda *args: subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()
    result['source_identity'] = {'baseline_head': git('rev-parse', 'HEAD'),
                                 'baseline_tree': git('rev-parse', 'HEAD^{tree}'),
                                 'candidate_state': 'dirty-candidate' if git('status', '--porcelain') else 'committed-clean'}
    print(markdown(result) if args.format == 'markdown' else json.dumps(result, indent=2))
