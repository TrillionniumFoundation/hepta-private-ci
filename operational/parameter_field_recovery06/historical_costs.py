"""Execution06 cost accounting copied from the frozen execution04 adapter.

The strict mode requires original preflight bytes. The separately registered
public-summary mode records missing bytes and uses a new cost-only schema. It
never manufactures a real-kernel-preflight receipt or a new preflight PASS.
"""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib
import json
import math
from pathlib import Path
import re

PACKAGE = 'experiments.parameter_field_fullstudy_20261029.'
HISTORY_SHA = '2848a9fc4b3092b79c3bff158b4c966bce5941760c0ea531eb7b4cb45c31c785'
REPORT_SHA = 'ccfe0f9fa555906f9cda0834424a5396c7146f523a47a4cd8696134d007e614f'
STRICT = 'strict_original_receipts'
PROJECTED = 'preregistered_public_summary_projection'
PROJECTION_SCHEMA = 'hepta.fullstudy.explicit-historical-cost-projection.1'
BINDING_SCHEMA = 'hepta.fullstudy.historical-cost-adapter-binding.1'
EXPECTED_EPISODES = {'episode02': 576, 'episode03': 78336}

SOURCE_EPISODE = 'execution04_durable_20261030'
TARGET_EPISODE = 'execution06_detached_20261030'
FACT_SCHEMA = 'hepta.execution06.execution04-cost-facts.1'
PRODUCER_CONFIG_SCHEMA = 'hepta.execution06.producer-config.1'
WORK_ROOT = Path(__file__).resolve().parents[3]
A29_FAILURE_SHA = 'eedb52e2cc05c5fdcc8ed295f27954952730038cdc2851ca4d7e110562f7e0ec'
OLD_CONFIG_SHA = 'c1a541cd8fca9e43c710cfd5ccf1cb76793a28712d66eed65a238f158de0e57e'
PRE_EXECUTION04_LOWER_BOUND = 182096
EXECUTION04_A29_STEPS = 14784
EXECUTION05_A29_STEPS = 17280
FACT_KEYS = {'schema', 'execution_episode', 'accounted_in_execution_episode',
             'a29_failed', 'outer_envelope', 'import_receipt', 'root_io', 'unknown_additional_work'}
PRODUCER_CONFIG_KEYS = {'schema', 'execution_episode', 'producer_map', 'import_receipt', 'fresh_registration'}


def require(test, message):
    if not test:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_bytes())


def descriptor(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path
            and path.is_file() and not path.is_symlink(), 'Noncanonical or missing metadata: ' + str(path))
    before = path.stat()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    after = path.stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
            'Metadata changed while hashing: ' + str(path))
    return {'path': str(path), 'bytes': after.st_size, 'sha256': digest}


def checked(item):
    require(set(item) == {'path', 'bytes', 'sha256'} and descriptor(item['path']) == item,
            'Pinned metadata identity differs: ' + str(item.get('path')))
    return Path(item['path'])


class _MetadataProjection:
    """Decode selected JSON fields; lexically skip unselected outcome numbers."""
    def __init__(self, text):
        self.text = text
        self.decoder = json.JSONDecoder()

    def ws(self, position):
        while position < len(self.text) and self.text[position].isspace():
            position += 1
        return position

    def value(self, position, selection):
        position = self.ws(position)
        if selection is True:
            return self.decoder.raw_decode(self.text, position)
        char = self.text[position]
        if char == '{':
            result, position = {}, self.ws(position + 1)
            if self.text[position] == '}':
                return result, position + 1
            while True:
                key, position = self.decoder.raw_decode(self.text, position)
                require(isinstance(key, str), 'Invalid JSON object key')
                position = self.ws(position)
                require(self.text[position] == ':', 'Invalid JSON separator')
                chosen = selection.get(key) if isinstance(selection, dict) else None
                value, position = self.value(position + 1, chosen)
                if chosen is not None:
                    result[key] = value
                position = self.ws(position)
                if self.text[position] == '}':
                    return result, position + 1
                require(self.text[position] == ',', 'Invalid JSON object delimiter')
                position = self.ws(position + 1)
        if char == '[':
            result, position = [], self.ws(position + 1)
            if self.text[position] == ']':
                return result, position + 1
            while True:
                chosen = selection[0] if isinstance(selection, list) else None
                value, position = self.value(position, chosen)
                if chosen is not None:
                    result.append(value)
                position = self.ws(position)
                if self.text[position] == ']':
                    return result, position + 1
                require(self.text[position] == ',', 'Invalid JSON array delimiter')
                position = self.ws(position + 1)
        # Only selected values are numerically decoded. Strings are scanned for
        # their boundary; their contents are not returned when unselected.
        if char == '"':
            unused, end = json.decoder.scanstring(self.text, position + 1, True)
            return None, end
        match = re.match(r'(?:-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null)', self.text[position:])
        require(match is not None, 'Invalid unselected JSON token')
        return None, position + match.end()


def summary_cost_metadata(path):
    parser = _MetadataProjection(Path(path).read_text())
    value, end = parser.value(0, {'schema': True, 'preflights': [{'source': True, 'gradient_microsteps': True}]})
    require(parser.ws(end) == len(parser.text), 'Trailing engineering-summary content')
    require(value.get('schema') == 'hepta.fullstudy.engineering-summary.1', 'Wrong public engineering summary')
    return value


def selected_metadata(path, selection):
    """Read bounded metadata fields and lexically skip every other value."""
    require(Path(path).stat().st_size <= 2 * 1024 ** 2, 'Cost metadata exceeds bounded input size')
    parser = _MetadataProjection(Path(path).read_text())
    value, end = parser.value(0, selection)
    require(parser.ws(end) == len(parser.text), 'Trailing cost metadata content')
    return value


def _number(value, name):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
            'Invalid nonnegative measured cost: ' + name)
    return value


def _root_io_path(path):
    path = Path(path)
    ordinary = WORK_ROOT / 'fullstudy_execution04_ops/root_steps'
    readback = WORK_ROOT / 'continuation_recovery_20261030/current_readiness_0253/root_archive_io/01_A-17/readback_steps'
    require((path.name == 'WAIT4.json' and path.parent.parent == ordinary)
            or (path.name == 'WAIT4.json' and path.parent.parent == readback
                and path.parent.name in ('000', '001', '002', '003', '004')),
            'Root IO receipt is outside the two registered execution04 locations')


def execution04_cost_plan(facts_descriptor, expected_import_receipt_descriptor):
    """Verify only the fixed failed A29 plus declared disjoint root measurements.

    The trusted registration pins facts_descriptor. Every receipt is separately
    hashed. No source pin is learned from the receipt being authenticated, no
    scientific value is decoded, and the inclusive outer CPU is never added.
    """
    facts = read(checked(facts_descriptor))
    require(set(facts) == FACT_KEYS and facts['schema'] == FACT_SCHEMA
            and facts['execution_episode'] == SOURCE_EPISODE
            and facts['accounted_in_execution_episode'] == TARGET_EPISODE
            and facts['unknown_additional_work'] is True,
            'Wrong or incomplete execution04 cost facts contract')
    require(facts['import_receipt'] == expected_import_receipt_descriptor,
            'Cost facts do not bind the registered A17 import')
    imported = read(checked(expected_import_receipt_descriptor))
    require(imported.get('schema') == 'hepta.execution06.a17-import.1'
            and imported.get('complete') is True and imported.get('imported') is True
            and imported.get('executed_here') is False and imported.get('seed') == 17
            and imported.get('source_episode') == SOURCE_EPISODE
            and imported.get('target_episode') == TARGET_EPISODE
            and imported.get('scientific_cost_owner') == SOURCE_EPISODE + ':A-17'
            and imported.get('new_scheduled_gradient_microsteps') == 0
            and imported.get('fresh_raw') == str(WORK_ROOT / 'fullstudy_execution06_durable_raw'),
            'Only the closed imported execution04 A17 can own current A17 cost')
    bindings = [facts_descriptor, expected_import_receipt_descriptor]
    failure_item = facts['a29_failed']
    require(checked(failure_item) == WORK_ROOT / 'fullstudy_execution04_durable_raw/stage_A/seed-29/FAILED.json'
            and failure_item['sha256'] == A29_FAILURE_SHA, 'Not the fixed failed execution04 A29 receipt')
    failure = selected_metadata(failure_item['path'], {
        'complete': True, 'error_type': True, 'message': True, 'partial_evidence_preserved': True,
        'cpu_seconds': True, 'wall_seconds': True,
        'costs': {'scheduled_gradient_microsteps': True, 'gradient_backward_calls': True, 'optimizer_steps': True}})
    require(failure.get('complete') is False and failure.get('error_type') == 'MemoryError'
            and failure.get('message') == 'Registered cgroup margin/pending-growth reserve exhausted'
            and failure.get('partial_evidence_preserved') is True
            and type(failure['costs']['scheduled_gradient_microsteps']) is int
            and failure['costs']['scheduled_gradient_microsteps'] == EXECUTION04_A29_STEPS
            and failure['costs']['gradient_backward_calls'] == EXECUTION04_A29_STEPS
            and failure['costs']['optimizer_steps'] == 13728,
            'Execution04 A29 failure/cost metadata differs')
    _number(failure['cpu_seconds'], 'failed A29 CPU')
    _number(failure['wall_seconds'], 'failed A29 wall')
    bindings.append(failure_item)
    outer_item = facts['outer_envelope']
    require(checked(outer_item) == WORK_ROOT / 'fullstudy_execution04_ops/wait4_launcher/WAIT4_COMPLETE.json',
            'Not the original execution04 outer wait4 receipt')
    outer = read(outer_item['path'])
    old_config = imported['anchors']['config']
    checked(old_config)
    require(old_config['sha256'] == OLD_CONFIG_SHA and outer.get('config') == old_config
            and outer.get('schema') == 'hepta.fullstudy.execution04-outer-wait4.1'
            and outer.get('exit_code') == 1
            and outer.get('do_not_add_nested_science_driver_archive_or_supervisor_ledgers') is True
            and outer.get('unwaited_orphan_costs_unknown_if_failure') is True,
            'Execution04 outer failure/configuration scope differs')
    inclusive = _number(outer['total_cpu_seconds_inclusive'], 'outer inclusive CPU')
    require(inclusive == _number(outer['user_cpu_seconds'], 'outer user CPU')
            + _number(outer['system_cpu_seconds'], 'outer system CPU'), 'Outer wait4 sum differs')
    launcher = _number(outer['launcher_cpu_seconds_separate'], 'outer measuring-parent CPU')
    bindings.extend((outer_item, old_config))
    require(isinstance(facts['root_io'], list), 'Root IO measurements must be a list')
    paths, digests, identities, roots = set(), set(), set(), []
    for row in facts['root_io']:
        require(set(row) == {'receipt', 'scope'} and row['scope'] == 'independent_root_step',
                'Root IO requires an explicit independent-root scope')
        item = row['receipt']
        path = checked(item)
        _root_io_path(path)
        require(item['path'] not in paths and item['sha256'] not in digests, 'Duplicate root IO receipt')
        record = read(path)
        require(record.get('schema') == 'hepta.execution04.root-engineering-wait4.1'
                and record.get('complete') is True
                and record.get('scope') == 'Local helper and waited descendants; excludes remote service compute and other root commands',
                'Root IO is not an actual completed wait4 measurement')
        child = record['child']
        identity = child['identity']
        require(type(identity['pid']) is int and identity['pid'] > 0
                and str(identity['start_ticks']).isdigit(), 'Invalid measured child identity')
        pair = (identity['pid'], str(identity['start_ticks']))
        require(pair not in identities and pair != (outer['child_identity']['pid'], str(outer['child_identity']['start_ticks'])), 'Duplicate or nested outer child')
        child_cpu = _number(child['total_cpu_seconds'], 'root child CPU')
        require(child_cpu == _number(child['user_cpu_seconds'], 'root child user CPU')
                + _number(child['system_cpu_seconds'], 'root child system CPU'), 'Root child wait4 sum differs')
        parent_cpu = _number(record['measuring_parent_cpu_seconds'], 'root measuring-parent CPU')
        require(type(child['exit_code']) is int and record['command_success'] is (child['exit_code'] == 0)
                and child['unwaited_orphan_costs_unknown_if_failure'] is (child['exit_code'] != 0),
                'Root IO exit status/cost scope differs')
        for key in ('intent', 'stdout', 'stderr'):
            checked(record[key])
            require(Path(record[key]['path']).parent == path.parent, 'Root IO support belongs to another step')
            bindings.append(record[key])
        bindings.append(item)
        paths.add(item['path'])
        digests.add(item['sha256'])
        identities.add(pair)
        roots.append({'receipt': item, 'scope': row['scope'], 'child_identity': identity,
            'exit_code': child['exit_code'], 'command_success': record['command_success'],
            'child_wait4_cpu_seconds': child_cpu, 'measuring_parent_cpu_seconds': parent_cpu,
            'disjoint_cpu_seconds_lower_bound': child_cpu + parent_cpu,
            'unknown_unwaited_descendant_cpu': child['exit_code'] != 0,
            'nonzero_exit_does_not_erase_measured_cpu': True})
    return {'schema': 'hepta.execution06.verified-execution04-cost-plan.1',
        'facts': facts_descriptor, 'bindings': bindings, 'import_receipt': expected_import_receipt_descriptor,
        'a29_failure': {'receipt': failure_item, **failure,
            'scientific_cost_owner': SOURCE_EPISODE + ':A-29:failed-stage',
            'entry_cleanup_and_unwaited_cpu_unknown': True, 'resumed': False},
        'outer_observation': {'receipt': outer_item, 'total_cpu_seconds_inclusive': inclusive,
            'contains_imported_A17_stage': True, 'included_in_disjoint_cpu_sum': False,
            'unwaited_failed_worker_cpu_coverage_unknown': True,
            'exclusive_overhead_not_inferred_by_subtraction': True},
        'outer_measuring_parent_cpu_seconds': launcher, 'root_io_rows': roots,
        'imported_A17_is_counted_only_in_current_completed_scientific_rows': True,
        'unknown_scopes': ['A29 entry, cleanup, unobserved or unwaited work after its failure measurement',
            'Execution04 exclusive supervisor/controller overhead and any orphan descendants',
            'Other historical/root IO, remote service compute, and earlier missing-receipt CPU',
            'Execution06 operational overhead not represented by current stage intervals; its later outer envelope is an inclusive observation'],
        'scientific_statistics_or_population_changed': False}


def nonoverlapping_cost_ledger(current, prior):
    """Lower bound from disjoint measured intervals, with inclusive views separate."""
    plan = prior['execution04_cost_plan']
    failed05 = prior['execution05_cost_plan']
    a17 = [row for row in current if row.get('phase') == 'A' and row.get('seed') == 17]
    require(len(a17) == 1, 'Current logical study must contain exactly one imported A17 cost row')
    additive, missing = [], []
    for index, row in enumerate([*current, *prior['engineering_receipts']]):
        if row.get('cpu_seconds') is None:
            missing.append({'row_index': index, 'kind': row['kind'], 'phase': row.get('phase'), 'seed': row.get('seed')})
            continue
        imported = row is a17[0]
        additive.append({'kind': row['kind'], 'phase': row.get('phase'), 'seed': row.get('seed'),
            'cpu_seconds': _number(row['cpu_seconds'], 'completed stage CPU'),
            'scientific_cost_owner': SOURCE_EPISODE + ':A-17' if imported else 'current-ledger-row:' + str(index),
            'imported': imported, 'executed_in_execution06': not imported and row in current,
            'scope': 'Original stage interval, not process-entry/exit or an inclusive controller total'})
    failure = plan['a29_failure']
    additive.extend(({'kind': 'historical_failed_A29_stage', 'receipt': failure['receipt'],
        'cpu_seconds': failure['cpu_seconds'], 'scientific_cost_owner': failure['scientific_cost_owner']},
        {'kind': 'execution04_outer_measuring_parent', 'receipt': plan['outer_observation']['receipt'],
         'cpu_seconds': plan['outer_measuring_parent_cpu_seconds']}))
    additive.extend({'kind': 'execution04_independent_root_step', 'receipt': row['receipt'],
        'cpu_seconds': row['disjoint_cpu_seconds_lower_bound'], 'exit_code': row['exit_code']} for row in plan['root_io_rows'])
    additive.extend({'kind': 'execution05_' + name, **failed05[name]}
                    for name in ('controller_wait4', 'supervisor_self_interval'))
    return {'schema': 'hepta.execution06.nonoverlapping-cost-ledger.1',
        'additive_cpu_observations': additive,
        'known_disjoint_cpu_seconds_lower_bound': sum(row['cpu_seconds'] for row in additive),
        'inclusive_cpu_observations_not_added': [plan['outer_observation']],
        'execution05_nested_cpu_observations_not_added': failed05['nested_observations_not_added'],
        'execution05_actual_outer_wait4_missing': True,
        'execution05_measured_disjoint_cpu_seconds_lower_bound': failed05['measured_disjoint_cpu_seconds_lower_bound'],
        'current_rows_with_unavailable_cpu': missing, 'unknown_scopes': [*plan['unknown_scopes'], *failed05['unknown_scopes']],
        'unknown_additional_cpu': True, 'whole_campaign_cpu_total_or_upper_bound_known': False,
        'a17_current_scientific_rows': 1, 'a17_failed_increment_rows': 0,
        'execution04_a29_failed_gradient_microsteps_lower_bound': EXECUTION04_A29_STEPS,
        'pre_execution04_gradient_microsteps_lower_bound': PRE_EXECUTION04_LOWER_BOUND,
        'historical_gradient_microsteps_lower_bound_including_execution04': PRE_EXECUTION04_LOWER_BOUND + EXECUTION04_A29_STEPS,
        'execution05_a29_failed_gradient_microsteps_lower_bound': EXECUTION05_A29_STEPS,
        'execution05_imported_A17_new_scientific_work': 0,
        'historical_gradient_microsteps_lower_bound_including_execution05': prior['gradient_microsteps_known_lower_bound'],
        'do_not_add_this_ledger_to_a_later_inclusive_execution06_outer_envelope': True}


def history_plan(config, config_item):
    """Verify actual source evidence and return deterministic cost-only metadata."""
    checked(config_item)
    require(read(config_item['path']) == config, 'Configuration object differs from pinned bytes')
    mode = config.get('history_mode', STRICT)
    require(mode in (STRICT, PROJECTED), 'Unknown historical-cost mode')
    history_item = config['historical_inputs']
    checked(history_item)
    require(history_item['sha256'] == HISTORY_SHA, 'Original historical REPORT_INPUTS bytes differ')
    original = read(history_item['path'])
    require(original.get('schema') == 'hepta.fullstudy.report-inputs.1'
            and original['integrity']['historical_exact_regression_gate'].startswith('FAIL'),
            'Historical V5 FAIL must remain preserved')
    require(len(original['engineering_preflights']) == 2, 'Original engineering population differs')
    originals = [*original['engineering_preflights'], *[r['receipt'] for r in original['failed_attempts']]]
    relocations = {}
    for relocation in config.get('history_receipt_relocations', []):
        old, new = relocation['original_receipt'], relocation['recovered_receipt']
        require(old in originals and old['path'] not in relocations, 'Unknown or duplicate historical relocation')
        require(all(new[k] == old[k] for k in ('bytes', 'sha256')), 'Historical relocation changes original bytes')
        checked(new)
        relocations[old['path']] = new
    bindings = [config_item, history_item]

    def restore(item):
        actual = relocations.get(item['path'], item)
        checked(actual)
        bindings.append(actual)
        return actual

    restored = deepcopy(original)
    for row in restored['failed_attempts']:
        row['receipt'] = restore(row['receipt'])
    summary_rows = []
    if mode == STRICT:
        restored['engineering_preflights'] = [restore(item) for item in original['engineering_preflights']]
    else:
        summary_item = config['historical_summary']
        checked(summary_item)
        public = summary_cost_metadata(summary_item['path'])
        declarations = config['missing_preflight_receipts']
        require(len(declarations) == len(public['preflights']) == 2, 'Projected preflight population differs')
        require([row['original_receipt'] for row in declarations] == original['engineering_preflights'],
                'Projection does not bind the two original missing descriptors')
        require([row['source'] for row in public['preflights']] == original['engineering_preflights'],
                'Public summary source descriptors differ')
        bindings.append(summary_item)
        for declaration, observation in zip(declarations, public['preflights']):
            old = declaration['original_receipt']
            require(type(declaration['gradient_microsteps']) is int
                    and declaration['gradient_microsteps'] == observation['gradient_microsteps'] == 432,
                    'Public-summary cost differs from the fixed two 432-step observations')
            require(old['path'] not in relocations and not Path(old['path']).exists(),
                    'A declared missing preflight has an available path; use an explicit revised strict registration')
            summary_rows.append({'schema': 'hepta.fullstudy.summary-backed-engineering-cost.1',
                'kind': 'summary_backed_historical_engineering', 'gradient_microsteps_lower_bound': 432,
                'public_summary': summary_item, 'expected_unavailable_original_receipt': old,
                'original_receipts_available': False, 'cannot_reverify_original_preflight': True,
                'new_preflight_executed': False, 'original_receipt_impersonation': False,
                'included_in_completed_receipt_gradient_microsteps': False})
        restored['engineering_preflights'] = []
    declared = config['additional_failed_episodes']
    require(len(declared) == 2 and {r['key'] for r in declared} == set(EXPECTED_EPISODES), 'Historical episode population differs')
    natives, episodes = [], set()
    for row in sorted(declared, key=lambda item: item['key']):
        key, item = row['key'], row['native_fact_receipt']
        checked(item)
        native = read(item['path'])
        require(native.get('schema') == 'hepta.fullstudy.explicit-historical-cost-facts.1'
                and native.get('scheduled_microsteps_lower_bound') == EXPECTED_EPISODES[key]
                and type(native.get('scheduled_microsteps_lower_bound')) is int
                and native.get('engineering_microsteps_included') == 0
                and native.get('unknown_additional_work') is True
                and native.get('original_receipt_impersonation') is False
                and native.get('underlying_evidence_available_now') is (key == 'episode02')
                and isinstance(native.get('actual_attempt_id'), str)
                and isinstance(native.get('observation_basis'), str) and bool(native['observation_basis']),
                'Explicit historical episode facts differ: ' + key)
        require(native['execution_episode'] not in episodes and native.get('supporting_evidence'), 'Duplicate or unsupported historical episode')
        episodes.add(native['execution_episode'])
        for evidence in native['supporting_evidence']:
            checked(evidence)
            bindings.append(evidence)
        bindings.append(item)
        natives.append({'key': key, 'native_fact_receipt': item,
                        'evidence_tier': 'recovered_partial_raw_audit' if key == 'episode02' else 'historical_observation_original_receipts_missing',
                        'facts': native})
    require(config['execution_episode'] == TARGET_EPISODE, 'Cost plan belongs to another recovery episode')
    producer_item = config['producer_config']
    producer = read(checked(producer_item))
    require(set(producer) == PRODUCER_CONFIG_KEYS and producer['schema'] == PRODUCER_CONFIG_SCHEMA
            and producer['execution_episode'] == TARGET_EPISODE, 'Unregistered execution06 producer configuration')
    checked(producer['producer_map'])
    extra_costs = execution04_cost_plan(config['execution04_cost_facts'], producer['import_receipt'])
    from operational.parameter_field_recovery06 import execution05_costs
    failed05_source = config['execution05_costs_source']
    require(checked(failed05_source) == Path(execution05_costs.__file__).resolve(),
            'Execution05 cost source identity differs')
    failed05 = execution05_costs.execution05_cost_plan(config['execution05_cost_facts'], producer['import_receipt'])
    bindings.extend((producer_item, producer['producer_map'], failed05_source, *extra_costs['bindings'], *failed05['bindings']))
    adapter = config['history_adapter_source']
    require(checked(adapter) == Path(__file__).resolve(), 'Historical adapter source identity differs')
    bindings.append(adapter)
    unique = {}
    for item in bindings:
        require(item['path'] not in unique or unique[item['path']] == item, 'Conflicting historical binding')
        unique[item['path']] = item
    return {'schema': PROJECTION_SCHEMA, 'history_mode': mode, 'execution_episode': config['execution_episode'],
        'configuration': config_item, 'adapter_source': adapter, 'original_historical_inputs': history_item,
        'original_integrity_preserved': original['integrity'],
        'restored_engineering_preflights': restored['engineering_preflights'],
        'restored_failed_attempts': restored['failed_attempts'],
        'summary_backed_engineering': summary_rows, 'additional_episode_facts': natives,
        'execution04_cost_plan': extra_costs, 'execution05_cost_plan': failed05,
        'actual_file_bindings': list(unique.values()),
        'original_preflight_bytes_missing': mode == PROJECTED,
        'scientific_statistics_or_population_changed': False}, restored


def _load_binding(spec):
    binding = spec['historical_cost_compatibility']
    require(binding.get('schema') == BINDING_SCHEMA, 'Missing explicit historical cost adapter binding')
    config_item, projection_item = binding['configuration'], binding['projection']
    config = read(checked(config_item))
    actual = read(checked(projection_item))
    expected, restored = history_plan(config, config_item)
    require(actual == expected and binding['adapter_source'] == expected['adapter_source'], 'Historical cost projection differs from preregistration')
    require(spec['engineering_preflights'] == restored['engineering_preflights']
            and spec['failed_attempts'] == restored['failed_attempts']
            and spec['integrity'] == restored['integrity'], 'Report historical inputs differ from the verified projection')
    report_item = config['helper_pins']['report_results.py']
    require(checked(report_item).name == 'report_results.py' and report_item['sha256'] == REPORT_SHA,
            'Only the frozen original report reader is supported')
    return expected, report_item


def _prior_costs(original, spec, plan):
    # The original reader still verifies every actual original receipt supplied.
    result = original(spec)
    require(len(result['engineering_receipts']) == (2 if plan['history_mode'] == STRICT else 0), 'Actual preflight receipt population differs')
    original_rows = deepcopy(result['failed_attempts'])
    seen = {row['receipt']['schema'] + ':' + row.get('execution_episode', str(i)) for i, row in enumerate(original_rows)}
    appended = []
    for item in plan['additional_episode_facts']:
        facts = item['facts']
        identity = facts['schema'] + ':' + facts['execution_episode']
        require(identity not in seen, 'A historical episode would be added twice')
        seen.add(identity)
        appended.append({'receipt': facts, 'native_fact_receipt': item['native_fact_receipt'],
            'actual_attempt_id': facts['actual_attempt_id'], 'execution_episode': facts['execution_episode'],
            'training_microsteps_lower_bound': facts['scheduled_microsteps_lower_bound'],
            'engineering_microsteps_included': 0, 'unknown_additional_work': True,
            'evidence_tier': item['evidence_tier'], 'original_receipt_impersonation': False,
            'legacy_failed_attempts_container_is_compatibility_only_not_proof_of_scientific_failure': item['key'] == 'episode03'})
    summary_total = sum(row['gradient_microsteps_lower_bound'] for row in plan['summary_backed_engineering'])
    result['failed_attempts'] = [*original_rows, *appended]
    result['summary_backed_engineering_projections'] = deepcopy(plan['summary_backed_engineering'])
    result['gradient_microsteps_known_lower_bound'] += sum(row['training_microsteps_lower_bound'] for row in appended) + summary_total
    require(result['gradient_microsteps_known_lower_bound'] == PRE_EXECUTION04_LOWER_BOUND,
            'Preserved pre-execution04 lower bound changed')
    extra = plan['execution04_cost_plan']
    failure = extra['a29_failure']
    result['pre_execution04_gradient_microsteps_lower_bound'] = PRE_EXECUTION04_LOWER_BOUND
    result['execution04_cost_plan'] = deepcopy(extra)
    result['failed_attempts'].append({'receipt': {
        'schema': 'hepta.execution06.failed-stage-cost-projection.1',
        'complete': False, 'cpu_seconds': failure['cpu_seconds'], 'wall_seconds': failure['wall_seconds'],
        'costs': deepcopy(failure['costs']), 'actual_original_failure_receipt': failure['receipt']},
        'actual_attempt_id': 'execution04-A-29', 'execution_episode': SOURCE_EPISODE,
        'training_microsteps_lower_bound': EXECUTION04_A29_STEPS, 'engineering_microsteps_included': 0,
        'unknown_additional_work': True, 'original_receipt_impersonation': False,
        'evidence_tier': 'literal_failed_stage_receipt', 'cost_only_not_a_new_scientific_sample': True,
        'a17_excluded_from_failed_increment': True, 'resumed': False})
    result['gradient_microsteps_known_lower_bound'] += EXECUTION04_A29_STEPS
    failed05 = plan['execution05_cost_plan']
    result['execution05_cost_plan'] = deepcopy(failed05)
    failure05 = failed05['a29_failure']
    result['failed_attempts'].append({'receipt': {
        'schema': 'hepta.execution06.failed-stage-cost-projection.1', 'complete': False,
        'cpu_seconds': failure05['cpu_seconds'], 'wall_seconds': failure05['wall_seconds'],
        'costs': deepcopy(failure05['costs']), 'actual_original_failure_receipt': failure05['receipt']},
        'actual_attempt_id': 'execution05-A-29', 'execution_episode': 'execution05_backpressure_20261030',
        'training_microsteps_lower_bound': EXECUTION05_A29_STEPS, 'engineering_microsteps_included': 0,
        'unknown_additional_work': True, 'original_receipt_impersonation': False,
        'evidence_tier': 'literal_failed_stage_receipt_with_cost_only_trace_corroboration',
        'cost_only_not_a_new_scientific_sample': True, 'a17_excluded_from_failed_increment': True,
        'phase_cpu_is_nested_not_additive_to_execution05_controller': True, 'resumed': False})
    result['gradient_microsteps_known_lower_bound'] += EXECUTION05_A29_STEPS
    require(result['gradient_microsteps_known_lower_bound'] == 214160, 'Historical lower bound must include both failures once')
    result['unknown_partial_work'] = True
    result['historical_evidence_tiers'] = {
        'preserved_original_engineering_receipt_microsteps': sum(row['gradient_microsteps'] for row in result['engineering_receipts']),
        'preserved_original_failure_receipt_lower_bound': sum(row['training_microsteps_lower_bound'] for row in original_rows),
        'recovered_partial_raw_audit_lower_bound': 576,
        'public_summary_missing_original_preflight_lower_bound': summary_total,
        'historical_observation_missing_original_episode03_receipts_lower_bound': 78336,
        'execution04_A29_literal_failure_lower_bound': EXECUTION04_A29_STEPS,
        'execution05_A29_literal_failure_lower_bound': EXECUTION05_A29_STEPS,
        'additional_unobserved_work': 'unknown'}
    result['historical_projection_disclosure'] = {
        'history_mode': plan['history_mode'], 'original_preflight_bytes_missing': plan['original_preflight_bytes_missing'],
        'cannot_reverify_original_preflight': plan['original_preflight_bytes_missing'],
        'new_preflight_pass_claimed': False, 'original_episode03_receipts_available_now': False,
        'episode03_subsequent_execution_endpoint_access_and_whole_episode_cpu': 'unknown',
        'all_prior_lower_bounds_are_costs_not_new_independent_scientific_samples': True}
    result['scope'] = 'Verified original receipts, explicitly separate recovered-audit, public-summary and historical-observation lower bounds; inclusive historical subtotals are never added again.'
    return result


def _current_cost_rows(report, complete, operations, endpoint):
    """Same current-run ledger construction as the pinned original cost_rows."""
    rows = []
    for (phase, seed), record in complete.items():
        ledger = record['work' if phase == 'C' else 'reconstruction_work' if phase == 'R' else 'costs']
        rows.append({'kind': 'training' if phase in ('A', 'B', 'C') else 'reconstruction' if phase == 'R' else 'constructed_witness',
            'phase': phase, 'seed': seed, 'gradient_microsteps': report.microsteps(ledger), 'ledger': ledger,
            'wall_seconds': record.get('wall_seconds', ledger.get('wall_seconds')),
            'cpu_seconds': record.get('cpu_seconds', ledger.get('cpu_seconds')),
            'process_peak_rss_bytes': operations[(phase, seed)].get('process_peak_rss_bytes')})
    for phase, record in endpoint.items():
        ledger = record['scoring_work' if phase == 'C' else 'scoring_costs']
        rows.append({'kind': 'endpoint_scoring', 'phase': phase, 'gradient_microsteps': report.microsteps(ledger),
            'ledger': ledger, 'wall_seconds': record.get('wall_seconds', ledger.get('wall_seconds')),
            'cpu_seconds': record.get('cpu_seconds', ledger.get('cpu_seconds')),
            'process_peak_rss_bytes': record.get('process_peak_rss_bytes')})
    return rows


@contextmanager
def apply_cost_adapter(spec_or_inputs_descriptor, report_module=None):
    """Scope only cost accounting/disclosure; restore all three functions always.

    The analysis wrapper must also retain the original analysis validate()/child
    path, source closure, worker registration and all 26/30 completion seals.
    """
    if set(spec_or_inputs_descriptor) == {'path', 'bytes', 'sha256'}:
        spec = read(checked(spec_or_inputs_descriptor))
    else:
        spec = deepcopy(spec_or_inputs_descriptor)
    plan, report_item = _load_binding(spec)
    report = report_module or importlib.import_module(PACKAGE + 'report_results')
    require(descriptor(Path(report.__file__).resolve()) == report_item, 'Loaded report module is not the bound original')
    require(not getattr(report, '_durable_historical_cost_adapter', False), 'Nested historical cost adapters are forbidden')
    original_prior, original_rows, original_render = report.prior_costs, report.cost_rows, report.render

    def prior(value):
        require(value == spec, 'Cost reader received a different report input manifest')
        return _prior_costs(original_prior, value, plan)

    def rows(complete, operations, endpoint, value):
        history = prior(value)
        current = _current_cost_rows(report, complete, operations, endpoint)
        actual_rows = [*current, *history['engineering_receipts']]
        completed = sum(row['gradient_microsteps'] for row in actual_rows)
        summaries = sum(row['gradient_microsteps_lower_bound'] for row in history['summary_backed_engineering_projections'])
        failed = history['failed_attempts']
        return {'rows': actual_rows, 'failed_attempts': failed,
            'completed_receipt_gradient_microsteps': completed,
            'summary_backed_historical_engineering_microsteps': summaries,
            'all_attempts_gradient_microsteps_known_lower_bound': completed + summaries + sum(row['training_microsteps_lower_bound'] for row in failed),
            'unknown_partial_work': True, 'no_quality_cost_exchange_rate_fitted': True,
            'historical_evidence_tiers': history['historical_evidence_tiers'],
            'historical_projection_disclosure': history['historical_projection_disclosure'],
            'nonoverlapping_cost_ledger': nonoverlapping_cost_ledger(current, history),
            'summary_backed_engineering_projections': history['summary_backed_engineering_projections'],
            'rule': 'Current scientific and endpoint ledgers are counted exactly as in the frozen reader. Missing-original public-summary costs are a separate lower-bound tier, excluded from completed_receipt_gradient_microsteps. Historical failures/observations are counted once. Peak RSS and inclusive CPU observations are not additive.'}

    def render(result):
        text = original_render(result)
        history = result.get('prior_attempt_costs', {})
        disclosure = history.get('historical_projection_disclosure')
        if not disclosure:
            return text
        tiers = history['historical_evidence_tiers']
        return text + '\n\n## Historical cost evidence and missing original bytes\n\n' + (
            f"Preserved original failure-receipt lower bound: {tiers['preserved_original_failure_receipt_lower_bound']:,}; "
            'recovered episode02 partial-raw audit lower bound: 576; episode03 historical-observation lower bound: 78,336. '
            'Original episode03 execution receipts are unavailable now; subsequent work, endpoint access and whole-episode CPU remain unknown. '
            f"Public-summary engineering lower bound: {tiers['public_summary_missing_original_preflight_lower_bound']:,}. "
            + ('The two original preflight RESULT byte streams are missing and cannot be reverified. These 864 summary-supported microsteps are included only in the all-attempts lower bound, not in completed receipt-backed work. '
               if disclosure['original_preflight_bytes_missing'] else 'Both original engineering receipts were verified from their actual bytes. ')
            + 'No new preflight PASS or recovered original receipt is claimed by this adapter. The historical V5 FAIL remains preserved; prior repeated seeds are not new independent samples.\n'
            + '\n## Execution04/05 failures and imported A17 costs\n\n'
            + 'The preserved earlier gradient lower bound is 182,096. Execution04 failed A29 adds 14,784; execution05 failed A29 separately adds 17,280 scheduled/backward calls and 15,984 optimizer steps. The historical gradient lower bound is 214,160. Combined with the complete planned logical study of 343,808, the prospective all-attempts lower bound is 557,968. A29 is rerun as a whole job; no partial-state resume is claimed. '
            + 'Imported A17 is counted once in the completed logical study and adds zero failed-attempt microsteps. '
            + 'The separately reported execution04 outer wait4 CPU contains A17 and is excluded from the additive stage/root ledger. Its exclusive overhead is not inferred by subtraction. '
            + 'The original A29 stage interval, the outer measuring parent and independently declared root wait4 intervals are separate measured lower bounds; nonzero root-command exits retain their measured CPU. '
            + 'The execution05 controller wait4 (1,548.712305 seconds) plus supervisor self interval (7.248885367 seconds) form a separate measured lower bound of 1,555.961190367 seconds. Worker CPU (1,512.719833 seconds) and the failed phase interval are nested and never added. Its actual outer wait4 is missing, not zero. Truncated trace counts corroborate a subset and are not added to cumulative failure counters. '
            + 'The nonoverlapping_cost_ledger lists those components and missing scopes. Archive transfer and recovery engineering are retained in the separate execution06 root ledger. No whole-campaign CPU total or upper bound is claimed.\n')

    report._durable_historical_cost_adapter = True
    report.prior_costs, report.cost_rows, report.render = prior, rows, render
    try:
        yield {'history_mode': plan['history_mode'], 'projection_verified': True,
               'scientific_or_statistical_functions_replaced': False}
    finally:
        report.prior_costs, report.cost_rows, report.render = original_prior, original_rows, original_render
        del report._durable_historical_cost_adapter
