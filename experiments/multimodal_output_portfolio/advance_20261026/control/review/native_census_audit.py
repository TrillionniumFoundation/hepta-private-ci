"""Independent closed-record census/lifecycle audit; no model or source loader.

The original numerical gates are reproduced without redefining them. A separate
engineering_complete field requires complete, consistent recorded execution and
zero operational exceptions. Statistical PASS and engineering completeness are
deliberately distinct. No existing result or candidate is written by this tool.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import struct
import time


POLICIES = ('dynamic', 'fixed_late')
ROUTES = ('image', 'text', 'audio', 'video')
VIEWS = ('clean', 'noise', 'occlusion', 'missing_trusted', 'conflict_untrusted',
         'missing_untrusted', 'missing_unknown', 'both_missing')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def feature_digest(features):
    raw = b'hepta.neuron.input-features.q24.v1' + struct.pack('>Q', len(features))
    return hashlib.sha256(raw + b''.join(struct.pack('>q', value) for value in features)).hexdigest()


def ece(probabilities, outcomes):
    if not probabilities:
        return None
    groups = defaultdict(list)
    for probability, outcome in zip(probabilities, outcomes):
        groups[probability].append(int(outcome))
    return sum(len(values) * abs(sum(values) / len(values) - probability)
               for probability, values in groups.items()) / len(probabilities)


def upper_binomial(successes, count):
    """One-sided exact95% bound, meaningful only under its stated trial model."""
    if successes == count:
        return 1.
    if successes == 0:
        return 1 - .05 ** (1 / count)
    low, high = 0., 1.
    coefficients = [math.lgamma(count + 1) - math.lgamma(i + 1) - math.lgamma(count - i + 1)
                    for i in range(successes + 1)]
    for _ in range(80):
        middle = (low + high) / 2
        terms = [coefficient + i * math.log(middle) + (count - i) * math.log1p(-middle)
                 for i, coefficient in enumerate(coefficients)]
        maximum = max(terms)
        cdf = math.exp(maximum) * sum(math.exp(value - maximum) for value in terms)
        if cdf > .05:
            low = middle
        else:
            high = middle
    return (low + high) / 2


class Audit:
    def __init__(self, root, pins):
        self.root, self.pins = root.resolve(), pins
        self.errors, self.checked_media, self.cached_hashes = [], 0, {}

    def require(self, condition, message):
        if not condition:
            self.errors.append(message)

    def read(self, path, required=True):
        path = Path(path)
        if not path.exists() and not required:
            return None
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError) as error:
            self.errors.append(f'{path}: {type(error).__name__}: {error}')
            return None

    def identity(self, path, expected):
        path = str(Path(path).resolve())
        if path not in self.cached_hashes:
            try:
                self.cached_hashes[path] = sha(path)
            except OSError as error:
                self.errors.append(f'{path}: {error}')
                return
        self.require(self.cached_hashes[path] == expected, 'File SHA mismatch: ' + path)

    def decision(self, envelope, label):
        decision = envelope['decision']; selected = decision['selected_action']
        mask, ticks = decision['actual_mask'], decision['ticks']
        self.require(len(mask) == 102 and bool(ticks), label + ': actual mask/tick census')
        self.require((selected is not None) == any(mask), label + ': selected/nonempty disagreement')
        self.require(selected is None or selected in (*range(100), 101), label + ': unavailable stop/invalid action')
        actions = [tick['action'] for tick in ticks]
        self.require(len(actions) == len(set(actions)), label + ': duplicate action ticks')
        if selected is not None:
            chosen = [tick for tick in ticks if tick['action'] == selected]
            self.require(mask[selected] and len(chosen) == 1 and chosen[0]['admitted'], label + ': selection not actually admitted')
        for action, permitted in enumerate(mask):
            if permitted:
                self.require(action in actions and next(t['admitted'] for t in ticks if t['action'] == action),
                             label + ': mask lacks an actual admitted tick')
        return decision

    def receipt(self, directory, filename, committed, decision, kind):
        value = self.read(directory / filename)
        owner = self.read(directory / committed)
        if value is None or owner is None:
            return None
        event = decision['decision']
        self.require(value['decision_digest'] == decision['decision_digest']
            and value['request_id'] == event['request_id'] and value['action'] == event['selected_action'],
            str(directory) + ': outcome belongs to a different decision')
        self.require(value['evidence_origin'] == kind and value['private_truth_utility_supplied'] is False,
                     str(directory) + ': outcome provenance/target boundary')
        self.require(value['decision_received_ns'] < value['generation_started_ns'] < value['observed_ns'],
                     str(directory) + ': outcome causal clock')
        self.require(owner['status']['pending'] is None, str(directory) + ': uncommitted outcome')
        if kind == 'own_generated_output':
            self.require(value['target_belief_updated'] is False, str(directory) + ': own output used as target evidence')
            self.require(set(value['media']) == set(ROUTES), str(directory) + ': four actual output modalities missing')
            for modality, path in value['media'].items():
                self.identity(path, value['media_sha256'][modality]); self.checked_media += 1
        else:
            self.require(value['target_supplied'] is False and value['source_acquisition_cached'] is False,
                         str(directory) + ': invalid late evidence provenance')
            self.require(len(value['source_wav_paths']) == len(value['source_wav_sha256']) == 2,
                         str(directory) + ': wrong source utterance count')
        return value

    def lifecycle(self, directory, policy, group, route, error=None):
        descriptor = self.read(directory / 'descriptor.json')
        first = self.read(directory / 'DECISION_H2.json', required=error is None)
        later = self.read(directory / 'DECISION_H1.json', required=False)
        episode = self.read(directory / 'EPISODE.json', required=error is None)
        encoding = self.read(directory / 'PUBLIC_ENCODING.json', required=error is None)
        label = str(directory)
        if error is not None:
            self.require(self.read(directory / 'EXECUTION_FAILURE.json') == error, label + ': failure custody differs')
        if descriptor:
            self.require(descriptor['policy'] == policy and descriptor['source_group_id'] == group, label + ': descriptor identity')
            for path_key, digest in (('weights_path', descriptor['pins']['weights']),
                    ('calibration_path', descriptor['pins']['calibration']),
                    ('likelihood_path', descriptor['likelihood_sha256']), ('observer_path', descriptor['observer_sha256'])):
                path = str(Path(descriptor[path_key]).resolve())
                self.require(self.pins.get(path) == digest, label + ': actual dependency absent from prospective pins')
                self.identity(path, digest)
        if not first:
            return first, later, episode, encoding
        root = self.decision(first, label + '/H2')
        child = self.decision(later, label + '/H1') if later else None
        if error is None:
            self.require((root['selected_action'] == 101) == (later is not None), label + ': acquisition/H1 census')
        if later:
            self.require(child['remaining'] == 1 and child['parent_outcome_digest'] ==
                self.read(directory / 'COMMITTED_EXTERNAL_AUDIO.json')['outcome_digest'], label + ': H1 has no committed external parent')
        if episode and error is None:
            last = child or root
            self.require(episode['initial_action'] == root['selected_action'] and episode['final_action'] == last['selected_action'],
                         label + ': episode/decision action mapping')
            self.require(episode['route'] == route and episode['policy'] == policy and episode['source_group'] == group,
                         label + ': closed episode source/policy identity')
            self.require(episode['closed_owner']['pending'] is None and episode['closed_owner']['completed'], label + ': lifecycle did not close')
            self.require(episode['private_target_read_by_online'] is False and encoding['hidden_target_supplied'] is False,
                         label + ': private target boundary')
            emits = isinstance(last['selected_action'], int) and last['selected_action'] < 100
            self.require(episode['actual_output_bundle'] == emits, label + ': actual bundle/selected output mismatch')
            self.require(episode['actual_external_acquisitions'] == int(root['selected_action'] == 101), label + ': actual external call count')
            if root['selected_action'] == 101:
                receipt = self.receipt(directory, 'EXTERNAL_AUDIO.json', 'COMMITTED_EXTERNAL_AUDIO.json', first, 'external_source_audio')
                self.require(receipt is not None and receipt['source_group_id'] == group, label + ': late evidence crossed source group')
            if emits:
                self.receipt(directory, 'ACTUAL_OUTPUT.json', 'COMMITTED_OUTPUT.json', later or first, 'own_generated_output')
            ticks = [t for decision in (root, child) if decision for t in decision['ticks']]
            sequences = [t['sequence'] for t in ticks]
            self.require(sequences == list(range(1, len(ticks) + 1)), label + ': original owner tick sequence gap')
            self.require(episode['closed_owner']['native_sequence'] == len(ticks), label + ': closed owner frontier differs')
        return first, later, episode, encoding


def qualification_summary(rows, missing, original, audit):
    result = {}
    for policy in POLICIES:
        chosen = [row for row in rows if row['policy'] == policy]
        absent = [row for row in missing if row['policy'] == policy]
        initial = [row for row in chosen if row['initial_selected_probability'] is not None]
        selected_ece = ece([row['initial_selected_probability'] for row in initial], [row['strict_success'] for row in initial])
        pp = [p for row in chosen for p in row['initial_code_confidence']]
        yy = [int(code == row['offline_target_code']) for row in chosen for code in range(len(row['initial_code_confidence']))]
        pooled = ece(pp, yy); coverage = sum(row['request_nonempty'] for row in chosen) / len(chosen)
        accepted = sum(row['accepted'] for row in absent); upper = upper_binomial(accepted, len(absent))
        gates = {'selected_action_ece': selected_ece is not None and selected_ece <= .03,
            'pooled_ece': pooled is not None and pooled <= .03, 'ID_request_coverage': coverage >= .25,
            'all_missing_false_acceptance': len(absent) == 600 and upper <= .004999}
        reported = original[policy]
        audit.require(gates == reported['gates'] and all(gates.values()) == reported['study_qualified'],
                      policy + ': original numerical qualification gates differ')
        audit.require(abs(upper - reported['all_missing_one_sided_95_upper']) < 1e-12, policy + ': binomial arithmetic differs')
        result[policy] = {'original_numerical_gates': reported['gates'],
            'original_study_qualified_preserved': reported['study_qualified'], 'independently_recomputed_gates': gates,
            'initial_selected_ECE': selected_ece, 'pooled_endpoint_ECE': pooled, 'request_coverage': coverage,
            'false_acceptances': accepted, 'nominal_one_sided_95_bound_under_iid_trial_model': upper,
            'unique_source_speakers': len({row['speaker'] for row in absent}),
            'unique_numeric_public_inputs': len({row['public_numeric_input_sha256'] for row in absent}),
            'unique_actual_native_inputs': len({row['actual_native_input_feature_sha256'] for row in absent}),
            'unique_numeric_initial_states': len({row['initial_numeric_state_sha256'] for row in absent}),
            'unique_RNG_states': len({row['RNG_state_sha256'] for row in absent})}
    return result


def main():
    parser = argparse.ArgumentParser()
    for name in ('run', 'protocol', 'allocation', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--phase', choices=('qualification', 'confirmation'), required=True)
    args = parser.parse_args()
    protocol, allocation = json.loads(args.protocol.read_text()), json.loads(args.allocation.read_text())
    if sha(args.allocation) != protocol['source_allocation_sha256']:
        raise ValueError('Audit allocation differs from the prospective protocol')
    audit = Audit(args.run, protocol['frozen_candidate_sha256'])
    report_path = args.report or args.run / 'REPORT.json'
    report, start = audit.read(report_path), audit.read(args.run / 'START.json')
    rows, missing = audit.read(args.run / 'ROWS.json'), audit.read(args.run / 'MISSING_ROWS.json')
    if any(value is None for value in (report, start, rows, missing)):
        raise ValueError('Only a completely closed run may enter this audit')
    role = 'qualification_id' if args.phase == 'qualification' else 'confirmation'
    selected = allocation['roles'][role]; pairs = selected['pair_count']
    expected = {(i, route, policy) for i in range(pairs) for route in ROUTES for policy in POLICIES
                if args.phase == 'qualification' or route in ('image', 'video') or policy == 'dynamic'}
    keys = [(row['case_index'], row['route'], row['policy']) for row in rows]
    audit.require(len(keys) == len(set(keys)) and set(keys) == expected, 'ID complete registered Cartesian census/duplicate check')
    audit.require(len(rows) == (320 if args.phase == 'qualification' else 1020), 'ID total census')
    audit.require(report['phase'] == args.phase and report['protocol_sha256'] == start['protocol_sha256'] == sha(args.protocol),
                  'Run phase/protocol identity')
    group_counts = Counter()
    for row in rows:
        try:
            case, route, policy = row['case_index'], row['route'], row['policy']
            writer = str(selected['pair_writer_ids'][case]); speaker = selected['speaker_by_writer'][writer]
            group = f'writer:{writer}:speaker:{speaker}'
            directory = args.run / 'ID' / f'pair-{case:03d}' / route / policy
            audit.require(Path(row['actual_directory']).resolve() == directory.resolve(), str(directory) + ': path identity')
            audit.require(row['source_group'] == group and row['writer'] == writer and row['speaker'] == speaker
                and row['view'] == VIEWS[case % 8], str(directory) + ': registered source mapping')
            group_counts[policy, group] += 1
            audit.require(audit.read(directory / 'OFFLINE_SCORE.json') == row, str(directory) + ': score custody')
            first, later, episode, _ = audit.lifecycle(directory, policy, group, route, row['execution_error'])
            initial = first['decision']['selected_action'] if first else None
            final = (later or first)['decision']['selected_action'] if first else None
            cost = .002 * (int(initial == 101) + int(isinstance(final, int) and final < 100))
            audit.require(row['initial_action'] == initial and row['final_action'] == final
                and abs(row['registered_cost'] - cost) < 1e-12, str(directory) + ': registered selected-action cost mapping')
            public = audit.read(directory.parent / (policy + '-input') / 'PUBLIC_INPUT.json', required=row['execution_error'] is None)
            if public:
                source = selected['source_records'][2 * case:2 * case + 2]
                if public['identity']['public_swap_command']:
                    source = source[::-1]
                target = 10 * source[0]['label'] + source[1]['label']
                audit.require(row['offline_target_code'] == target, str(directory) + ': public command/target mapping')
        except (KeyError, TypeError, ValueError, IndexError, StopIteration) as error:
            audit.errors.append(f'ID row {row.get("case_index")}/{row.get("route")}/{row.get("policy")}: {type(error).__name__}: {error}')
    expected_groups = 10 if args.phase == 'qualification' else 85
    for policy in POLICIES:
        policy_rows = [row for row in rows if row['policy'] == policy]
        audit.require(len({row['source_group'] for row in policy_rows}) == expected_groups, policy + ': writer/speaker group census')
        if args.phase == 'qualification':
            audit.require(len(policy_rows) == 160 and all(value == 16 for (p, _), value in group_counts.items() if p == policy),
                          policy + ':160 ID requests and16 tasks per group required')
        else:
            primary = [row for row in policy_rows if row['route'] in ('image', 'video')]
            counts = Counter(row['source_group'] for row in primary)
            audit.require(len(primary) == 340 and len(counts) == 85 and set(counts.values()) == {4},
                          policy + ':340 primary cases and4 per source group required')
    if args.phase == 'qualification':
        expected_missing = {(i, p) for i in range(600) for p in POLICIES}
        keys = [(row['source_index'], row['policy']) for row in missing]
        audit.require(len(keys) == len(set(keys)) and set(keys) == expected_missing, 'Missing complete Cartesian census/duplicates')
        source_rows = allocation['roles']['qualification_ood']['recordings']
        for row in missing:
            try:
                index, policy = row['source_index'], row['policy']; source = source_rows[index]
                directory = args.run / 'OOD' / f'source-{index:03d}' / policy
                audit.require(audit.read(directory / 'MISSING_OBSERVATION.json') == row, str(directory) + ': missing observation custody')
                audit.require(row['speaker'] == source['speaker'] and row['source_waveform_sha256'] == source['sha256'],
                              str(directory) + ': missing source identity')
                first, _, episode, encoded = audit.lifecycle(directory, policy, 'speaker.' + source['speaker'], 'image')
                decision = first['decision']; initial = encoded['fresh_owner']['status']
                audit.require(row['accepted'] == any(decision['actual_mask']), str(directory) + ': false acceptance mapping')
                audit.require(encoded['features'] == [0] * 176 and row['source_waveform_model_reads'] == 0,
                              str(directory) + ': all-missing input scope')
                audit.require(row['public_numeric_input_sha256'] == feature_digest(encoded['features'])
                    and row['actual_native_input_feature_sha256'] == decision['ticks'][0]['feature_digest']
                    and row['initial_numeric_state_sha256'] == digest_json({k: initial[k] for k in
                        ('native_sequence', 'eligibility_q24', 'utility_q32')})
                    and row['RNG_state_sha256'] == digest_json({'RNG': 'none; deterministic native forward; missing bypass'}),
                    str(directory) + ': duplicate-input/state/RNG identity mapping')
            except (KeyError, TypeError, ValueError, IndexError, StopIteration) as error:
                audit.errors.append(f'Missing row {row.get("source_index")}/{row.get("policy")}: {type(error).__name__}: {error}')
        for policy in POLICIES:
            group = [row for row in missing if row['policy'] == policy]
            audit.require(len(group) == len({row['speaker'] for row in group}) == len({row['source_waveform_sha256'] for row in group}) == 600,
                          policy + ':600 distinct registered missing-source identities required')
        numerical = qualification_summary(rows, missing, report['summary'], audit)
    else:
        audit.require(not missing, 'Confirmation has no additional missing-source cohort')
        numerical = {'original_primary_report_preserved': report['summary'],
                     'bootstrap_formula_static_review': 'Correct paired85-group entropic moment bootstrap with two-sided98.3333333333% limits; no resampling or outcome-driven alternative contrast was added by this audit.'}
    failures = sum(row['execution_error'] is not None for row in rows)
    audit.require(report['policy_episodes'] == len(rows) and report['all_missing_physical_requests'] == len(missing),
                  'Report/closed record census')
    result = {'schema': 'hepta.advance.independent-native-census-audit.v1', 'phase': args.phase,
        'recorded_ns': time.time_ns(), 'engineering_complete': not audit.errors and failures == 0,
        'census_and_lifecycle_consistent': not audit.errors, 'execution_errors_retained': failures,
        'audit_violations': audit.errors, 'ID_rows': len(rows), 'missing_rows': len(missing),
        'actual_media_sha_checks': audit.checked_media, 'numerical_results_without_new_gates': numerical,
        'gate_scope': 'engineering_complete is a separate execution audit; it is not retroactively represented as an original statistical gate and never changes the original study_qualified result.',
        'original_outer_process_returncode': report.get('original_process_returncode', 0),
        'report_serialization_recovered': report.get('report_serialization_recovered', False),
        'IID_addendum': 'The registered source cohort uses deterministic hash ordering and disjoint sampling without replacement. IID Bernoulli requests are a hypothetical interpretation condition for the nominal bound, not a demonstrated property of those identities. Repeated deterministic all-missing numerical inputs/states add no input-space coverage. This supports the exact structural missing-input scope and cannot certify natural OOD robustness.',
        'input_sha256': {str(path.resolve()): sha(path) for path in (args.protocol, args.allocation,
            args.run / 'ROWS.json', args.run / 'MISSING_ROWS.json', report_path)},
        'audit_source_sha256': sha(__file__), 'models_or_source_role_loaders_called': False,
        'source_or_candidate_modified': False}
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')
    print(json.dumps({'engineering_complete': result['engineering_complete'], 'ID_rows': len(rows),
        'missing_rows': len(missing), 'execution_errors': failures, 'violations': audit.errors,
        'output_sha256': sha(args.output)}))


if __name__ == '__main__':
    main()
