"""Cost-only validation of the failed execution05 episode for execution06.

Linux evidence is externally pinned before amendment/initialization. This module
never imports a scientific kernel, interprets outcomes, resumes a failed stage,
or turns a missing outer wait4 into zero. Archive readback is a pinned historical
observation: later checks do not reopen expendable duplicate payloads or claim a
new remote authentication.
"""

from copy import deepcopy
import json
import os
from pathlib import Path
import re

from operational.parameter_field_recovery06 import historical_costs as metadata

BASE = Path(__file__).resolve().parents[3]
SOURCE_EPISODE = 'execution05_backpressure_20261030'
TARGET_EPISODE = 'execution06_detached_20261030'
SOURCE_COMMIT = '7544b0a57a3b5624f3f2190449efeb84854b414d'
PINS_SCHEMA = 'hepta.execution06.execution05-source-pins.1'
FACT_SCHEMA = 'hepta.execution06.execution05-cost-facts.1'
PINS_KEYS = {'schema', 'source_episode', 'target_episode', 'frozen_source_commit', 'roots',
             'archive_manifest', 'archive_verification', 'remote_closure', 'forensics',
             'forensics_measurement', 'key_receipts', 'actual_outer_wait4_missing', 'unknown_additional_work'}
FACT_KEYS = {'schema', 'execution_episode', 'accounted_in_execution_episode',
             'failure_sources', 'import_receipt', 'unknown_additional_work'}
GRADIENT_STEPS = 17280
OPTIMIZER_STEPS = 15984
CONTROLLER_CPU = 1548.712305
SUPERVISOR_SELF_CPU = 7.248885367
WORKER_CPU = 1512.719833
KNOWN = {
    'a29_failed': ('fullstudy_execution05_durable_raw/stage_A/seed-29/FAILED.json',
                   '8638412963d8d6191e9b3d9ab5cfe97c7b9aa890a1eb025213c17a997351c514'),
    'controller_wait4': ('fullstudy_execution05_ops/supervisor_run/children/controller.EXIT.json',
                         'd2986e6ee5060090b962ed0b472bc4b6fc8059069922533cbba676f3e41108d5'),
    'worker_wait4': ('fullstudy_execution05_ops/wrapper_runs/CONTROLLER/273933-1819746/owned_children/001.WAIT4.json',
                     '3b2058c9ac257f4026f74af1e290dd32e06619fd965086280c1c40acf9a76bb4'),
    'primary_failed': ('fullstudy_execution05_ops/FAILED.json',
                       'c509c0b523fba34e0aa5190549d7bc78d2f5bedfb60b0041365abbbbd608a897'),
    'prior_import_receipt': ('fullstudy_execution05_durable_raw/imports/execution04/A-17/IMPORT_RECEIPT.json',
                            '3b071dbaf2fc9468f3adbca069bb8ea297bdb2d2764d649dee8e21e54dad9fdd'),
    'forensics': ('executor_recovery_20261030T1152/failed05_forensics/FAILED_A29_COST_FORENSICS.json',
                  '25eab40176693625b3c6fcf6f29be7ee566805d32301b84191fe154a930af324'),
    'forensics_measurement': ('executor_recovery_20261030T1152/failed05_forensics/measurement/WAIT4.json',
                             'a3bb92e5327c5ee214fe057d5fab592b291be5606e8844b18aaf5f7345d4acb9')}
KEY_RECEIPTS = set(KNOWN) - {'forensics', 'forensics_measurement'}
require, checked, descriptor, read = metadata.require, metadata.checked, metadata.descriptor, metadata.read


def roots():
    return {name: str(BASE / relative) for name, relative in {
        'raw': 'fullstudy_execution05_durable_raw', 'ops': 'fullstudy_execution05_ops',
        'cas': 'fullstudy_execution05_durable_raw_cas', 'prereg': 'execution05_preregistration_inputs',
        'recovery': 'executor_recovery_20261030T1152',
        'forensics': 'executor_recovery_20261030T1152/failed05_forensics'}.items()}


def descriptor_shape(item):
    require(isinstance(item, dict) and set(item) == {'path', 'bytes', 'sha256'}
            and isinstance(item['path'], str) and Path(item['path']).is_absolute()
            and '..' not in Path(item['path']).parts and type(item['bytes']) is int and item['bytes'] >= 0
            and isinstance(item['sha256'], str) and re.fullmatch(r'[0-9a-f]{64}', item['sha256']),
            'Invalid exact evidence descriptor')


def measured_step(item, bindings):
    """Check an actual small external_step receipt without rerunning the step."""
    step = read(checked(item))
    require(step.get('schema') == 'hepta.execution04.root-engineering-wait4.1'
            and step.get('complete') is True and step.get('command_success') is True
            and step['child']['exit_code'] == 0 and step['child']['wait_status'] == 0,
            'Historical helper lacks successful actual wait4')
    require(metadata._number(step['child']['total_cpu_seconds'], 'historical helper CPU')
            == metadata._number(step['child']['user_cpu_seconds'], 'helper user CPU')
            + metadata._number(step['child']['system_cpu_seconds'], 'helper system CPU'),
            'Historical helper wait4 CPU sum differs')
    metadata._number(step['measuring_parent_cpu_seconds'], 'historical helper measuring parent')
    for name in ('intent', 'stdout', 'stderr'):
        checked(step[name])
        require(Path(step[name]['path']).parent == Path(item['path']).parent,
                'Historical helper support belongs to another step')
        bindings.append(step[name])
    bindings.append(item)
    return step


def validate_source_pins(pins_descriptor):
    """Verify actual failed05 provenance before a fresh06 import exists."""
    pins = read(checked(pins_descriptor))
    require(set(pins) == PINS_KEYS and pins['schema'] == PINS_SCHEMA
            and pins['source_episode'] == SOURCE_EPISODE and pins['target_episode'] == TARGET_EPISODE
            and pins['frozen_source_commit'] == SOURCE_COMMIT and pins['roots'] == roots()
            and pins['actual_outer_wait4_missing'] is True and pins['unknown_additional_work'] is True
            and set(pins['key_receipts']) == KEY_RECEIPTS, 'Wrong failed execution05 source-pins contract')
    bindings = [pins_descriptor]
    receipts = {**pins['key_receipts'], 'forensics': pins['forensics'],
                'forensics_measurement': pins['forensics_measurement']}
    for name, (relative, digest) in KNOWN.items():
        item = receipts[name]
        require(checked(item) == BASE / relative and item['sha256'] == digest,
                'Not the externally verified failed execution05 evidence: ' + name)
        bindings.append(item)
    manifest_item = pins['archive_manifest']
    manifest = read(checked(manifest_item))
    verification = read(checked(pins['archive_verification']))
    bindings.extend((manifest_item, pins['archive_verification']))
    binding = manifest['binding']
    require(manifest['schema'] == 'hepta.fullstudy.durable-archive-manifest.1'
            and manifest['scientific_values_interpreted'] is False
            and binding['schema'] == 'hepta.execution05.terminal-failure-bundle-binding.1'
            and binding['execution_episode'] == SOURCE_EPISODE and binding['source_commit'] == SOURCE_COMMIT
            and binding['terminal_phase'] == 'FAILED' and binding['completed_jobs'] == ['A-17']
            and binding['accepted_archive_barriers'] == 1 and binding['planned_jobs'] == 14
            and binding['planned_archive_barriers'] == 17 and binding['scientific_completion_claim'] is False,
            'Failure archive binding does not preserve the actual incomplete episode')
    indexed = {}
    for row in manifest['files']:
        relative = Path(row['path'])
        require(not relative.is_absolute() and '..' not in relative.parts and relative.parts
                and row['source'] == str(BASE / relative) and row['path'] not in indexed,
                'Failure archive source/logical path differs or is duplicated')
        item = {'path': row['source'], 'bytes': row['bytes'], 'sha256': row['sha256']}
        descriptor_shape(item)
        indexed[row['path']] = item
    require(manifest['logical_files'] == len(indexed)
            and manifest['logical_bytes'] == sum(row['bytes'] for row in manifest['files']),
            'Failure archive logical counts differ')
    for name in ('raw', 'ops', 'cas', 'prereg', 'forensics'):
        prefix = str(Path(pins['roots'][name]).relative_to(BASE)) + '/'
        require(any(path.startswith(prefix) for path in indexed), 'Failure archive omits source root: ' + name)
    for item in receipts.values():
        relative = str(Path(item['path']).relative_to(BASE))
        require(indexed.get(relative) == item, 'Failure archive omits or changes a pinned cost/forensic receipt')
    for name, schema in (('logical_paths', 'hepta.execution05.failure-logical-paths.1'),
                         ('external_references', 'hepta.execution05.failure-external-references.1')):
        item = binding[name]
        value = read(checked(item))
        require(value['schema'] == schema and indexed.get(str(Path(item['path']).relative_to(BASE))) == item,
                'Failure archive full logical/external index differs')
        bindings.append(item)
    require(verification['schema'] == 'hepta.fullstudy.durable-archive-verification.1'
            and verification['binding'] == binding and verification['manifest'] == manifest_item
            and verification['verification_complete'] is True
            and verification['logical_files_verified'] == manifest['logical_files']
            and verification['logical_bytes_verified'] == manifest['logical_bytes']
            and verification['chunks_verified'] == sum(len(row['chunks']) for row in manifest['files'])
            and verification['parts_verified'] == len(manifest['parts'])
            and verification['scientific_values_interpreted'] is False,
            'Failure archive was not actually verified in full')
    closure = read(checked(pins['remote_closure']))
    bindings.append(pins['remote_closure'])
    require(closure['schema'] == 'hepta.execution05.failure-archive-remote-bytes-verified.1'
            and closure['execution_episode'] == SOURCE_EPISODE and closure['complete'] is True
            and closure['scientific_complete'] is False and closure['manifest'] == manifest_item
            and closure['archive_verification'] == pins['archive_verification']
            and closure['remote_bytes_verified'] is True and closure['all_items_same_actual_uploaded_version'] is True,
            'Failure archive lacks a pinned actual remote-byte closure')
    cost_path = Path(manifest_item['path']).parent / 'ARCHIVE_COST.json'
    archive_cost = descriptor(cost_path)
    archive_cost_record = read(cost_path)
    require(archive_cost_record['schema'] == 'hepta.fullstudy.durable-archive-cost.1'
            and archive_cost_record['binding'] == binding, 'Failure archive cost binding differs')
    bindings.append(archive_cost)
    expected = [part['artifact'] for part in manifest['parts']] + [manifest_item, pins['archive_verification'], archive_cost]
    require(len(closure['items']) == len(expected), 'Failure archive remote item population differs')
    remote_ids = set()
    for item, original in zip(closure['items'], expected, strict=True):
        descriptor_shape(original)
        descriptor_shape(item['readback'])
        require(item['local'] == original and item['remote_readback_performed'] is True
                and item['distinct_inode'] is True and item['xattr_verified'] is True
                and item['readback']['path'] != original['path']
                and all(item['readback'][name] == original[name] for name in ('bytes', 'sha256')),
                'Failure archive historical remote-byte observation differs')
        identity = item['remote_identity']['library_file_id']
        require(isinstance(identity, str) and identity and identity not in remote_ids,
                'Failure archive remote identity missing or repeated')
        remote_ids.add(identity)
        measured_step(item['readback_wait4'], bindings)
    for name in ('WAIT4_COMPLETE.json', 'WAIT4_PRIMARY_INVALID.json', 'LAUNCH_FAILED.json'):
        require(not os.path.lexists(BASE / 'fullstudy_execution05_ops/wait4_launcher' / name),
                'Previously missing execution05 outer receipt now exists; new provenance review required')
    forensic = read(pins['forensics']['path'])
    require(forensic['schema'] == 'hepta.execution05.failed-A29-cost-forensics.1'
            and forensic['execution_episode'] == SOURCE_EPISODE and forensic['complete'] is True
            and forensic['scientific_complete'] is False and forensic['new_scientific_work'] == 0
            and forensic['outcomes_or_weights_decoded'] is False and forensic['SOURCE_RAW_OPS_writes'] is False
            and forensic['original_failure'] == receipts['a29_failed']
            and forensic['CPU_nonoverlap']['controller_wait4']['receipt'] == receipts['controller_wait4']
            and forensic['CPU_nonoverlap']['worker_wait4']['receipt'] == receipts['worker_wait4']
            and forensic['CPU_nonoverlap']['primary_failure'] == receipts['primary_failed']
            and forensic['historical_anchors']['import_receipt'] == receipts['prior_import_receipt'],
            'Cost-only forensic scope or original receipt bindings differ')
    for path, exists in forensic['completion_markers_and_head_artifacts_exist'].items():
        require(exists is False and not os.path.lexists(path), 'Failed A29 acquired a completion/head artifact')
    trace = forensic['original_trace']
    require(indexed.get(str(Path(trace['path']).relative_to(BASE))) == trace,
            'Archived truncated trace differs from original cost-only scan')
    measured_step(pins['forensics_measurement'], bindings)
    unique = {}
    for item in bindings:
        require(item['path'] not in unique or unique[item['path']] == item, 'Conflicting failed05 evidence bindings')
        unique[item['path']] = item
    return {'pins': pins, 'forensics': forensic, 'bindings': list(unique.values()),
            'remote_readback_is_pinned_historical_observation_not_new_remote_authentication': True,
            'archive_payload_or_scientific_values_decoded_here': False}


def execution05_cost_plan(facts_descriptor, expected_import_receipt_descriptor):
    facts = read(checked(facts_descriptor))
    require(set(facts) == FACT_KEYS and facts['schema'] == FACT_SCHEMA
            and facts['execution_episode'] == SOURCE_EPISODE and facts['accounted_in_execution_episode'] == TARGET_EPISODE
            and facts['unknown_additional_work'] is True and facts['import_receipt'] == expected_import_receipt_descriptor,
            'Wrong or incomplete execution05 cost facts contract')
    verified = validate_source_pins(facts['failure_sources'])
    pins, forensic = verified['pins'], verified['forensics']
    imported = read(checked(expected_import_receipt_descriptor))
    previous = read(pins['key_receipts']['prior_import_receipt']['path'])
    require(imported['schema'] == 'hepta.execution06.a17-import.1'
            and imported['complete'] is True and imported['imported'] is True and imported['executed_here'] is False
            and imported['seed'] == 17 and imported['source_episode'] == 'execution04_durable_20261030'
            and imported['target_episode'] == TARGET_EPISODE
            and imported['scientific_cost_owner'] == 'execution04_durable_20261030:A-17'
            and imported['new_scheduled_gradient_microsteps'] == 0
            and imported['fresh_raw'] == str(BASE / 'fullstudy_execution06_durable_raw')
            and previous['scientific_cost_owner'] == imported['scientific_cost_owner']
            and previous['new_scheduled_gradient_microsteps'] == 0
            and previous['anchors']['scientific_complete'] == imported['anchors']['scientific_complete'],
            'Failed05 history does not share the same once-counted original04 A17')
    refs = pins['key_receipts']
    failure = metadata.selected_metadata(refs['a29_failed']['path'], {
        'complete': True, 'cpu_seconds': True, 'wall_seconds': True,
        'costs': {'scheduled_gradient_microsteps': True, 'gradient_backward_calls': True, 'optimizer_steps': True}})
    require(failure == forensic['failure_cost_only_projection'] and failure['complete'] is False
            and failure['costs'] == {'scheduled_gradient_microsteps': GRADIENT_STEPS,
                'gradient_backward_calls': GRADIENT_STEPS, 'optimizer_steps': OPTIMIZER_STEPS}
            and all(type(value) is int for value in failure['costs'].values()), 'Failed05 cumulative work differs')
    metadata._number(failure['cpu_seconds'], 'failed05 phase CPU')
    metadata._number(failure['wall_seconds'], 'failed05 phase wall')
    controller = read(refs['controller_wait4']['path'])
    worker = read(refs['worker_wait4']['path'])
    primary = metadata.selected_metadata(refs['primary_failed']['path'], {
        'schema': True, 'complete': True, 'execution_episode': True, 'message': True,
        'costs': {'self_cpu_seconds_since_init': True, 'wait4_children_inclusive_cpu_seconds': True,
                  'unwaited_descendant_costs_unknown': True}})
    require(controller['exit_code'] == 1 and controller['wait_status'] == 256
            and controller['total_cpu_seconds'] == CONTROLLER_CPU
            and controller['total_cpu_seconds'] == controller['user_cpu_seconds'] + controller['system_cpu_seconds']
            and worker['exit_code'] == -15 and worker['wait_status'] == 15
            and worker['cpu_seconds'] == WORKER_CPU
            and worker['cpu_seconds'] == worker['user_cpu_seconds'] + worker['system_cpu_seconds']
            and worker['identity']['parent_pid'] == controller['identity']['pid']
            and worker['scientific_completion_claim'] is False
            and primary['schema'] == 'hepta.fullstudy.execution05-failure.1'
            and primary['complete'] is False and primary['execution_episode'] == SOURCE_EPISODE
            and primary['costs']['self_cpu_seconds_since_init'] == SUPERVISOR_SELF_CPU
            and primary['costs']['wait4_children_inclusive_cpu_seconds'] == CONTROLLER_CPU
            and primary['costs']['unwaited_descendant_costs_unknown'] is True,
            'Failed05 actual wait4 nesting or primary CPU scope differs')
    trace = forensic['trace_cost_only_prefix_scan']
    require(trace['complete_newline_terminated_cost_rows'] == 96
            and trace['gzip_eof_and_checksum_verified'] is False and trace['incomplete_gzip_container'] is True
            and trace['sum_of_explicit_counter_values_lower_bound'] == {
                'scheduled_gradient_microsteps': 16128, 'gradient_backward_calls': 16128, 'optimizer_steps': 14976}
            and trace['omitted_optimizer_entries_not_imputed_as_observed_zero'] is True,
            'Failed05 truncated trace corroboration differs')
    return {'schema': 'hepta.execution06.verified-execution05-cost-plan.1',
        'facts': facts_descriptor, 'failure_sources': facts['failure_sources'],
        'bindings': [facts_descriptor, expected_import_receipt_descriptor, *verified['bindings']],
        'a29_failure': {'receipt': refs['a29_failed'], **failure,
            'scientific_cost_owner': SOURCE_EPISODE + ':A-29:failed-stage', 'resumed': False},
        'trace_corroboration_not_added': deepcopy(trace),
        'controller_wait4': {'receipt': refs['controller_wait4'], 'cpu_seconds': CONTROLLER_CPU,
                            'includes_worker_and_nested_phase_cpu': True},
        'supervisor_self_interval': {'receipt': refs['primary_failed'], 'cpu_seconds': SUPERVISOR_SELF_CPU,
                                    'full_process_lifetime_claimed': False},
        'nested_observations_not_added': [
            {'receipt': refs['worker_wait4'], 'cpu_seconds': WORKER_CPU, 'scope': 'nested worker wait4'},
            {'receipt': refs['a29_failed'], 'cpu_seconds': failure['cpu_seconds'], 'scope': 'nested phase interval'}],
        'measured_disjoint_cpu_seconds_lower_bound': CONTROLLER_CPU + SUPERVISOR_SELF_CPU,
        'actual_outer_wait4_missing': True, 'whole_execution05_cpu_total_or_upper_bound_known': False,
        'execution05_imported_A17_new_scientific_work': 0,
        'historical_remote_readback_not_reauthenticated': True,
        'unknown_scopes': ['Execution05 outer launcher and missing process startup/tail intervals',
            'Execution05 root helpers and observers, including missing observer wait4',
            'Earlier missing-receipt CPU and remote service compute'],
        'archive_build_transfer_and_recovery_engineering_costs_owned_by_execution06_root_ledger': True,
        'scientific_statistics_or_population_changed': False}


def build_cost_facts(import_receipt, failure_sources):
    """Create once, only after externally pinned05 closure and actual06 import."""
    checked(import_receipt)
    validate_source_pins(failure_sources)
    facts = {'schema': FACT_SCHEMA, 'execution_episode': SOURCE_EPISODE,
        'accounted_in_execution_episode': TARGET_EPISODE, 'failure_sources': failure_sources,
        'import_receipt': import_receipt, 'unknown_additional_work': True}
    path = BASE / 'execution06_preregistration_inputs/EXECUTION05_COST_FACTS.json'
    with path.open('xb') as stream:
        stream.write((json.dumps(facts, sort_keys=True, indent=2, allow_nan=False) + '\n').encode())
        stream.flush()
        os.fsync(stream.fileno())
    item = descriptor(path)
    execution05_cost_plan(item, import_receipt)
    return item
