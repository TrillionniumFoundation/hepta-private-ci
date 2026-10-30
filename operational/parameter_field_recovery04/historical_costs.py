"""Explicit historical cost evidence, without changing frozen science modules.

The strict mode requires original preflight bytes. The separately registered
public-summary mode records missing bytes and uses a new cost-only schema. It
never manufactures a real-kernel-preflight receipt or a new preflight PASS.
"""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib
import json
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
    result['unknown_partial_work'] = True
    result['historical_evidence_tiers'] = {
        'preserved_original_engineering_receipt_microsteps': sum(row['gradient_microsteps'] for row in result['engineering_receipts']),
        'preserved_original_failure_receipt_lower_bound': sum(row['training_microsteps_lower_bound'] for row in original_rows),
        'recovered_partial_raw_audit_lower_bound': 576,
        'public_summary_missing_original_preflight_lower_bound': summary_total,
        'historical_observation_missing_original_episode03_receipts_lower_bound': 78336,
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
            + 'No new preflight PASS or recovered original receipt is claimed by this adapter. The historical V5 FAIL remains preserved; prior repeated seeds are not new independent samples.\n')

    report._durable_historical_cost_adapter = True
    report.prior_costs, report.cost_rows, report.render = prior, rows, render
    try:
        yield {'history_mode': plan['history_mode'], 'projection_verified': True,
               'scientific_or_statistical_functions_replaced': False}
    finally:
        report.prior_costs, report.cost_rows, report.render = original_prior, original_rows, original_render
        del report._durable_historical_cost_adapter
