"""Synthetic cost-only provenance tests; no actual archive/worker claims."""

from copy import deepcopy
import ast
import hashlib
import json
from pathlib import Path
import resource
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE))
from operational.parameter_field_recovery06 import execution05_costs as failed05


def saved(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode())
    return failed05.descriptor(path)


def measured(root, index):
    folder = root / str(index)
    return saved(folder / 'WAIT4.json', {
        'schema': 'hepta.execution04.root-engineering-wait4.1', 'complete': True, 'command_success': True,
        'child': {'exit_code': 0, 'wait_status': 0, 'identity': {'pid': 10000 + index, 'start_ticks': str(index)},
                  'total_cpu_seconds': .75, 'user_cpu_seconds': .5, 'system_cpu_seconds': .25},
        'measuring_parent_cpu_seconds': .01,
        'intent': saved(folder / 'INTENT.json', {'synthetic_only': True}),
        'stdout': saved(folder / 'stdout.json', {'synthetic_only': True}),
        'stderr': saved(folder / 'stderr.json', {'synthetic_only': True})})


def fixture(root, imported):
    """Every file is a labeled temporary contract fixture, never real science."""
    old = failed05.read(imported['path'])
    previous = {**old, 'schema': 'hepta.execution05.a17-import.1', 'target_episode': failed05.SOURCE_EPISODE,
                'fresh_raw': str(root / 'fullstudy_execution05_durable_raw'), 'synthetic_only': True}
    failure = {'complete': False, 'costs': {'scheduled_gradient_microsteps': 17280,
        'gradient_backward_calls': 17280, 'optimizer_steps': 15984}, 'cpu_seconds': 1509.489910855,
        'wall_seconds': 2117.036076925997}
    controller = {'exit_code': 1, 'wait_status': 256, 'total_cpu_seconds': 1548.712305,
        'user_cpu_seconds': 1509.827213, 'system_cpu_seconds': 38.885092,
        'identity': {'pid': 273933, 'start_ticks': '1819746'}, 'synthetic_only': True}
    worker = {'exit_code': -15, 'wait_status': 15, 'cpu_seconds': 1512.719833,
        'user_cpu_seconds': 1486.049402, 'system_cpu_seconds': 26.670431,
        'identity': {'pid': 282783, 'parent_pid': 273933, 'start_ticks': 1854924},
        'scientific_completion_claim': False, 'synthetic_only': True}
    primary = {'schema': 'hepta.fullstudy.execution05-failure.1', 'complete': False,
        'execution_episode': failed05.SOURCE_EPISODE, 'message': 'Controller exited before durable full-grid closure',
        'costs': {'self_cpu_seconds_since_init': 7.248885367, 'wait4_children_inclusive_cpu_seconds': 1548.712305,
                  'unwaited_descendant_costs_unknown': True}, 'synthetic_only': True}
    values = {'a29_failed': failure, 'controller_wait4': controller, 'worker_wait4': worker,
              'primary_failed': primary, 'prior_import_receipt': previous}
    refs = {name: saved(root / failed05.KNOWN[name][0], value) for name, value in values.items()}
    trace = saved(root / 'fullstudy_execution05_durable_raw/stage_A/seed-29/bank/trace.jsonl.gz',
                  {'synthetic_metadata_only_not_a_real_trace': True})
    marker = root / 'fullstudy_execution05_durable_raw/stage_A/seed-29/COMPLETE.json'
    scan = {'complete_newline_terminated_cost_rows': 96, 'gzip_eof_and_checksum_verified': False,
            'incomplete_gzip_container': True, 'sum_of_explicit_counter_values_lower_bound': {
                'scheduled_gradient_microsteps': 16128, 'gradient_backward_calls': 16128, 'optimizer_steps': 14976},
            'omitted_optimizer_entries_not_imputed_as_observed_zero': True}
    forensic = {'schema': 'hepta.execution05.failed-A29-cost-forensics.1',
        'execution_episode': failed05.SOURCE_EPISODE, 'complete': True, 'scientific_complete': False,
        'new_scientific_work': 0, 'outcomes_or_weights_decoded': False, 'SOURCE_RAW_OPS_writes': False,
        'original_failure': refs['a29_failed'], 'failure_cost_only_projection': failure,
        'CPU_nonoverlap': {'controller_wait4': {'receipt': refs['controller_wait4']},
                          'worker_wait4': {'receipt': refs['worker_wait4']}, 'primary_failure': refs['primary_failed']},
        'historical_anchors': {'import_receipt': refs['prior_import_receipt']},
        'completion_markers_and_head_artifacts_exist': {str(marker): False},
        'original_trace': trace, 'trace_cost_only_prefix_scan': scan, 'synthetic_only': True}
    fdesc = saved(root / failed05.KNOWN['forensics'][0], forensic)
    m = measured(root / 'executor_recovery_20261030T1152/failed05_forensics/measurement', 0)
    target = root / failed05.KNOWN['forensics_measurement'][0]
    target.write_bytes(Path(m['path']).read_bytes())
    # Support paths must share the exact measuring directory.
    mvalue = failed05.read(target)
    for key in ('intent', 'stdout', 'stderr'):
        mvalue[key] = saved(target.parent / Path(mvalue[key]['path']).name, {'synthetic_only': True})
    m = saved(target, mvalue)
    bundle = root / 'synthetic_failure_archive'
    logical = saved(bundle / 'LOGICAL_PATHS.json', {'schema': 'hepta.execution05.failure-logical-paths.1', 'synthetic_only': True})
    external = saved(bundle / 'EXTERNAL_REFERENCES.json', {'schema': 'hepta.execution05.failure-external-references.1', 'synthetic_only': True})
    binding = {'schema': 'hepta.execution05.terminal-failure-bundle-binding.1',
        'execution_episode': failed05.SOURCE_EPISODE, 'source_commit': failed05.SOURCE_COMMIT,
        'terminal_phase': 'FAILED', 'completed_jobs': ['A-17'], 'accepted_archive_barriers': 1,
        'planned_jobs': 14, 'planned_archive_barriers': 17, 'scientific_completion_claim': False,
        'logical_paths': logical, 'external_references': external}
    support = [saved(root / 'fullstudy_execution05_durable_raw_cas/fixture.json', {'synthetic_only': True}),
               saved(root / 'execution05_preregistration_inputs/fixture.json', {'synthetic_only': True})]
    files = [*refs.values(), fdesc, m, trace, logical, external, *support]
    rows = [{'path': str(Path(item['path']).relative_to(root)), 'source': item['path'],
             'bytes': item['bytes'], 'sha256': item['sha256'], 'chunks': []} for item in files]
    part = saved(bundle / 'archive/part-0000.tar.gz', {'synthetic_only_not_a_real_archive': True})
    manifest = {'schema': 'hepta.fullstudy.durable-archive-manifest.1', 'binding': binding,
        'scientific_values_interpreted': False, 'files': rows, 'logical_files': len(rows),
        'logical_bytes': sum(row['bytes'] for row in rows), 'parts': [{'artifact': part}]}
    manifest_desc = saved(bundle / 'archive/MANIFEST.json', manifest)
    verification = saved(bundle / 'archive/VERIFIED.json', {
        'schema': 'hepta.fullstudy.durable-archive-verification.1', 'binding': binding,
        'manifest': manifest_desc, 'verification_complete': True, 'logical_files_verified': len(rows),
        'logical_bytes_verified': manifest['logical_bytes'], 'chunks_verified': 0,
        'parts_verified': 1, 'scientific_values_interpreted': False, 'synthetic_only': True})
    archive_cost = saved(bundle / 'archive/ARCHIVE_COST.json', {
        'schema': 'hepta.fullstudy.durable-archive-cost.1', 'binding': binding, 'synthetic_only': True})
    items = []
    for index, item in enumerate((part, manifest_desc, verification, archive_cost), 1):
        items.append({'local': item, 'readback': {**item, 'path': str(bundle / 'retired' / str(index))},
            'remote_readback_performed': True, 'distinct_inode': True, 'xattr_verified': True,
            'remote_identity': {'library_file_id': 'synthetic-only-' + str(index)},
            'readback_wait4': measured(bundle / 'synthetic_remote_measurements', index)})
    closure = saved(bundle / 'REMOTE_BYTES_VERIFIED.json', {
        'schema': 'hepta.execution05.failure-archive-remote-bytes-verified.1', 'execution_episode': failed05.SOURCE_EPISODE,
        'complete': True, 'scientific_complete': False, 'manifest': manifest_desc,
        'archive_verification': verification, 'remote_bytes_verified': True,
        'all_items_same_actual_uploaded_version': True, 'items': items, 'synthetic_only': True})
    pins = {'schema': failed05.PINS_SCHEMA, 'source_episode': failed05.SOURCE_EPISODE,
        'target_episode': failed05.TARGET_EPISODE, 'frozen_source_commit': failed05.SOURCE_COMMIT,
        'roots': {name: str(root / Path(path).relative_to(failed05.BASE)) for name, path in failed05.roots().items()},
        'archive_manifest': manifest_desc, 'archive_verification': verification, 'remote_closure': closure,
        'forensics': fdesc, 'forensics_measurement': m, 'key_receipts': refs,
        'actual_outer_wait4_missing': True, 'unknown_additional_work': True}
    pins_desc = saved(root / 'execution06_preregistration_inputs/FAILURE05_SOURCE_PINS.json', pins)
    facts = {'schema': failed05.FACT_SCHEMA, 'execution_episode': failed05.SOURCE_EPISODE,
        'accounted_in_execution_episode': failed05.TARGET_EPISODE, 'failure_sources': pins_desc,
        'import_receipt': imported, 'unknown_additional_work': True}
    facts_desc = saved(root / 'SYNTHETIC_EXECUTION05_COST_FACTS.json', facts)
    known = {name: (relative, ({**refs, 'forensics': fdesc, 'forensics_measurement': m})[name]['sha256'])
             for name, (relative, unused) in failed05.KNOWN.items()}
    return {'pins': pins, 'pins_descriptor': pins_desc, 'facts': facts, 'facts_descriptor': facts_desc,
            'known': known, 'root': root, 'imported': imported}


class Failed05EvidenceChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='execution06-synthetic-failure05-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        science = saved(self.root / 'ORIGINAL_A17_SYNTHETIC.json', {'synthetic_only': True})
        self.imported = saved(self.root / 'IMPORT.json', {'schema': 'hepta.execution06.a17-import.1',
            'complete': True, 'imported': True, 'executed_here': False, 'seed': 17,
            'source_episode': 'execution04_durable_20261030', 'target_episode': failed05.TARGET_EPISODE,
            'scientific_cost_owner': 'execution04_durable_20261030:A-17', 'new_scheduled_gradient_microsteps': 0,
            'fresh_raw': str(self.root / 'fullstudy_execution06_durable_raw'),
            'anchors': {'scientific_complete': science}, 'synthetic_only': True})
        self.data = fixture(self.root, self.imported)
        for name, value in (('BASE', self.root), ('KNOWN', self.data['known'])):
            change = patch.object(failed05, name, value)
            change.start()
            self.addCleanup(change.stop)

    def plan(self):
        return failed05.execution05_cost_plan(self.data['facts_descriptor'], self.imported)

    def rebind_pins(self, pins):
        self.data['pins_descriptor'] = saved(self.root / 'CHANGED_PINS.json', pins)
        self.data['facts']['failure_sources'] = self.data['pins_descriptor']
        self.data['facts_descriptor'] = saved(self.root / 'CHANGED_FACTS.json', self.data['facts'])

    def test_preserved_execution04_verifier_ast_has_only_episode_metadata_migration(self):
        source = Path(failed05.__file__).resolve().parents[3]
        before = source / 'fullstudy_recovery05_git/operational/parameter_field_recovery05/historical_costs.py'
        after = Path(failed05.metadata.__file__).resolve()
        text = before.read_text().replace('hepta.execution05.', 'hepta.execution06.')
        text = text.replace('fullstudy_execution05', 'fullstudy_execution06').replace('Execution05', 'Execution06')
        text = text.replace('execution05_backpressure_20261030', 'execution06_detached_20261030')
        old_function = next(node for node in ast.parse(text).body if isinstance(node, ast.FunctionDef) and node.name == 'execution04_cost_plan')
        new_function = next(node for node in ast.parse(after.read_text()).body if isinstance(node, ast.FunctionDef) and node.name == 'execution04_cost_plan')
        self.assertEqual(ast.dump(old_function, include_attributes=False), ast.dump(new_function, include_attributes=False))

    def test_two_cpu_intervals_only_and_zero_new_import_work(self):
        plan = self.plan()
        self.assertEqual(plan['a29_failure']['costs']['scheduled_gradient_microsteps'], 17280)
        self.assertEqual(plan['a29_failure']['costs']['optimizer_steps'], 15984)
        self.assertEqual(plan['measured_disjoint_cpu_seconds_lower_bound'], 1555.961190367)
        self.assertEqual(plan['execution05_imported_A17_new_scientific_work'], 0)
        self.assertEqual(len(plan['nested_observations_not_added']), 2)
        self.assertTrue(plan['actual_outer_wait4_missing'])
        self.assertFalse(plan['whole_execution05_cpu_total_or_upper_bound_known'])
        self.assertEqual(plan['trace_corroboration_not_added']['sum_of_explicit_counter_values_lower_bound']['scheduled_gradient_microsteps'], 16128)

    def test_builder_writes_once_and_refuses_overwrite(self):
        item = failed05.build_cost_facts(self.imported, self.data['pins_descriptor'])
        self.assertEqual(failed05.read(item['path']), self.data['facts'])
        with self.assertRaises(FileExistsError):
            failed05.build_cost_facts(self.imported, self.data['pins_descriptor'])

    def test_retired_payloads_are_not_reopened_or_treated_as_new_readback(self):
        closure = failed05.read(self.data['pins']['remote_closure']['path'])
        self.assertTrue(all(not Path(row['readback']['path']).exists() for row in closure['items']))
        self.assertTrue(self.plan()['historical_remote_readback_not_reauthenticated'])

    def test_changed_cost_bytes_refuse_before_projection(self):
        path = Path(self.data['pins']['key_receipts']['a29_failed']['path'])
        value = failed05.read(path)
        value['costs']['scheduled_gradient_microsteps'] += 1
        saved(path, value)
        with self.assertRaisesRegex(ValueError, 'Pinned metadata identity'):
            self.plan()

    def test_outer_presence_or_completion_marker_is_not_assumed_zero(self):
        path = self.root / 'fullstudy_execution05_ops/wait4_launcher/WAIT4_COMPLETE.json'
        saved(path, {'synthetic_only': True})
        with self.assertRaisesRegex(ValueError, 'outer receipt now exists'):
            self.plan()
        path.unlink()
        path = self.root / 'fullstudy_execution05_durable_raw/stage_A/seed-29/COMPLETE.json'
        saved(path, {'synthetic_only': True})
        with self.assertRaisesRegex(ValueError, 'acquired a completion'):
            self.plan()

    def test_missing_cpu_field_is_rejected_not_defaulted(self):
        refs = self.data['pins']['key_receipts']
        value = failed05.read(refs['controller_wait4']['path'])
        value.pop('total_cpu_seconds')
        item = saved(Path(refs['controller_wait4']['path']), value)
        # Even changing the externally supplied descriptor cannot replace the original pin.
        pins = deepcopy(self.data['pins'])
        pins['key_receipts']['controller_wait4'] = item
        self.rebind_pins(pins)
        with self.assertRaisesRegex(ValueError, 'externally verified'):
            self.plan()

    def test_wrong_import_owner_or_extra_new_A17_work_refuses(self):
        old = failed05.read(self.imported['path'])
        for field, value in (('new_scheduled_gradient_microsteps', 39168), ('scientific_cost_owner', 'execution05:A-17')):
            changed = saved(self.root / ('WRONG_' + field + '.json'), {**old, field: value})
            self.data['facts']['import_receipt'] = changed
            facts = saved(self.root / 'CHANGED_FACTS.json', self.data['facts'])
            with self.assertRaisesRegex(ValueError, 'once-counted'):
                failed05.execution05_cost_plan(facts, changed)

    def test_missing_remote_item_or_unverified_byte_flag_refuses(self):
        pins = deepcopy(self.data['pins'])
        original = failed05.read(pins['remote_closure']['path'])
        for modified in ({**original, 'items': original['items'][:-1]}, {**original, 'remote_bytes_verified': False}):
            pins['remote_closure'] = saved(self.root / 'WRONG_CLOSURE.json', modified)
            self.rebind_pins(pins)
            with self.assertRaisesRegex(ValueError, 'remote'):
                self.plan()

    def test_archive_omission_wrong_logical_source_and_duplicate_refuse(self):
        pins = deepcopy(self.data['pins'])
        original = failed05.read(pins['archive_manifest']['path'])
        for action in ('omit', 'source', 'duplicate'):
            value = deepcopy(original)
            if action == 'omit':
                value['files'].pop()
            elif action == 'source':
                value['files'][0]['source'] = str(self.root / 'another.json')
            else:
                value['files'].append(deepcopy(value['files'][0]))
            pins['archive_manifest'] = saved(self.root / 'WRONG_MANIFEST.json', value)
            self.rebind_pins(pins)
            with self.assertRaisesRegex(ValueError, 'archive'):
                self.plan()


if __name__ == '__main__':
    wall, cpu = time.monotonic(), time.process_time()
    run = unittest.main(exit=False, verbosity=2)
    print(json.dumps({'synthetic_only': True, 'tests': run.result.testsRun, 'success': run.result.wasSuccessful(),
        'forbidden_scientific_imports': [name for name in ('torch', 'numpy') if name in sys.modules],
        'science_workers_started': 0, 'cpu_seconds': time.process_time() - cpu,
        'wall_seconds': time.monotonic() - wall, 'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024}))
    raise SystemExit(0 if run.result.wasSuccessful() else 1)
