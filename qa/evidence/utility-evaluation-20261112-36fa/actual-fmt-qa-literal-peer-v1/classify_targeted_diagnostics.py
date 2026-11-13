"""Classify literal diagnostics using frozen AST/source text, never execute QA.

Only this audit's lexer and balanced-delimiter helpers are imported. No repository
module, mutation, verifier, test case, Git operation, or native command is invoked.
"""
import ast
import base64
import collections
import hashlib
import json
import re
from pathlib import Path

from check_fixed_contract_anchors import function_span, lex, groups

HERE = Path(__file__).resolve().parent
BASE = Path('/tmp/hepta-36fa-coordinator-f905-registration-v1')
AGENT = 'codex-rs/hepta-agentd/src/'
FMT = Path('/tmp/hepta-36fa-provider-0c59-fix101-apply-fmt-runtime-v1/fmt.after.postimages.json')
INVENTORY = Path('/tmp/hepta-36fa-provider-0c59-finalfmt-inventory-recovery-v1/final.inventory.exact_recovered.json')


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def main():
    diagnostic = json.loads((HERE / 'LITERAL_OCCURRENCE_DIAGNOSTIC.json').read_bytes())
    packet_raw = FMT.read_bytes()
    inventory_raw = INVENTORY.read_bytes()
    assert identity(packet_raw) == diagnostic['actual_fmt_packet']
    assert identity(inventory_raw) == diagnostic['actual_full_inventory']
    packet = json.loads(packet_raw)
    changes = {r['path']: r for r in packet['changes']}
    inventory = {r['path']: r for r in json.loads(inventory_raw)['files']}
    assert len(changes) == 62
    for item in diagnostic['qa_inputs']:
        raw = (BASE / 'before' / item['path']).read_bytes()
        assert identity(raw) == {k: item[k] for k in ('bytes', 'sha256', 'git_blob')}
        actual = inventory[item['path']]
        assert actual['bytes'] == len(raw)
        assert actual['sha256'] == hashlib.sha256(raw).hexdigest()
        assert actual['working_blob'] == identity(raw)['git_blob']

    def original_source(path, side):
        if path in changes:
            raw = base64.b64decode(changes[path][side + '_raw_base64'], validate=True)
        else:
            raw = (BASE / 'before' / path).read_bytes()
        if side == 'after' or path not in changes:
            row = inventory[path]
            assert (len(raw), hashlib.sha256(raw).hexdigest(), identity(raw)['git_blob']) == (
                row['bytes'], row['sha256'], row['working_blob'])
        return raw.decode()

    # These are manually resolved target expressions, not evaluations of test code.
    synthetic_owner = {1, 6, 9, 17, 18, 19, 26, 27, 28, 30, 32, 33, 34}
    output_only = {0, 3, 4, 12, 14, 15, 22, 37}
    marker_classifier = {10, 11}
    unchanged_targets = {
        2: 'circuit_learning_read_profile.rs',
        5: 'circuit_retained_version_prepared.rs',
        7: 'circuit_evaluated_retention_publication.rs',
        8: 'circuit_evaluated_retention_publication.rs',
        13: 'cell_q24_training_command_connection.rs',
        16: 'cell_q24_material_receipt_owner.rs',
        29: 'cell_q24_training_command.rs',
        31: 'cell_q24_training_command_readback.rs',
    }
    composite_targets = {20, 21, 23, 24, 25, 35, 36}
    all_ids = synthetic_owner | output_only | marker_classifier | set(unchanged_targets) | composite_targets
    assert all_ids == set(range(len(diagnostic['rows'])))
    classifications = []
    for index, row in enumerate(diagnostic['rows']):
        qa = (BASE / 'before' / row['qa_path']).read_text()
        tree = ast.parse(qa)
        functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                     and n.name == row['scope'].rsplit('.', 1)[-1]]
        assert len(functions) == 1
        fn = functions[0]
        method = ast.get_source_segment(qa, fn)
        lines = qa.splitlines()
        snippet = '\n'.join(lines[max(fn.lineno - 1, row['line'] - 4):min(fn.end_lineno, row['line'] + 3)])
        extra = {}
        if index in synthetic_owner:
            category = 'synthetic_unregistered_caller_output'
            reason = 'owner. is a generated attack expression, never a source lookup. Its losses in other fixtures do not require a marker migration.'
        elif index in output_only:
            category = 'replacement_or_injected_attack_output'
            reason = 'This string is emitted into the mutant or is replacement indentation; it is not the original span selected for deletion/replacement.'
        elif index in marker_classifier:
            category = 'classifier_over_existing_marker_parameter'
            reason = 'startswith classifies the already specified marker. This prefix is not itself looked up in the Rust source.'
        elif index in unchanged_targets:
            category = 'actual_target_outside_exhaustive_fmt_changes'
            path = AGENT + unchanged_targets[index]
            assert path not in changes and path in inventory
            extra = {'resolved_target': path, 'actual_inventory_row': inventory[path]}
            reason = 'The test targets this unchanged source. The global substring loss occurred only in unrelated changed files. This establishes no fmt-induced migration, not a prior QA verdict.'
        else:
            category = 'complete_target_marker_checked_below'
            reason = 'The partial string is composed into a complete marker or selected inside the original Legacy branch. Exact original target spans are compared separately below.'
        classifications.append({'diagnostic_row': index, 'qa_path': row['qa_path'], 'scope': row['scope'],
                                'line': row['line'], 'partial_value': row['value'], 'category': category,
                                'reason': reason, 'method_identity': identity(method.encode()),
                                'source_excerpt': snippet, **extra})

    checks = []
    for filename, predecessor in [('circuit_selection_receipt_owner.rs', 'training_evidence'),
                                  ('circuit_next_use_receipt_owner.rs', 'predecessors')]:
        for function, marker in [
                ('readback_source', f'self.{predecessor}(&source).await?'),
                ('finish_original_readback', f'self.{predecessor}(source).await?')]:
            checks.append({'path': AGENT + filename, 'function': function, 'marker': marker,
                           'match_kind': 'literal', 'diagnostic_rows': [20, 21]})
        kind = 'compact_whitespace' if 'next_use' in filename else 'literal'
        checks.append({'path': AGENT + filename, 'function': 'readback_source',
                       'marker': f'let before = self.{predecessor}(&source).await?;',
                       'match_kind': kind, 'diagnostic_rows': [23]})
        checks.append({'path': AGENT + filename, 'function': 'finish_original_readback',
                       'marker': f'self.{predecessor}(source).await?',
                       'match_kind': kind, 'diagnostic_rows': [24]})
    checks.append({'path': AGENT + 'circuit_retained_version_state.rs', 'function': 'read_original',
                   'marker': 'let last = state.observe_phase()?;\n        let after = state.artifacts.read_current()?;',
                   'match_kind': 'literal', 'diagnostic_rows': [35, 36]})
    for marker in ['snapshot: &self.context.training,', 'live: &self.live,', 'trainer,']:
        checks.append({'path': AGENT + 'circuit_evaluated_selection_command_service.rs',
                       'function': 'observe_original', 'marker': marker,
                       'branch': 'OriginalPredecessors::Legacy(trainer) => {',
                       'match_kind': 'literal', 'diagnostic_rows': [25]})
    results = []
    for item in checks:
        out = dict(item)
        counts = {}
        evidence = {}
        for side in ['before', 'after']:
            text = original_source(item['path'], side)
            start, end = function_span(text, item['function'])
            if 'branch' in item:
                assert text[start:end].count(item['branch']) == 1
                start = text.index(item['branch'], start, end)
                opening = text.index('{', start, end)
                tokens, _ = lex(text)
                pairs, _ = groups(tokens)
                opening_token = next(i for i, token in enumerate(tokens) if token[2] == opening)
                end = tokens[pairs[opening_token]][3]
            body = text[start:end]
            if item['match_kind'] == 'literal':
                spans = [(start + m.start(), start + m.end()) for m in re.finditer(re.escape(item['marker']), body)]
            else:
                positions = [i for i in range(start, end) if not text[i].isspace()]
                compact = ''.join(text[i] for i in positions)
                wanted = ''.join(item['marker'].split())
                spans = [(positions[m.start()], positions[m.end() - 1] + 1)
                         for m in re.finditer(re.escape(wanted), compact)]
            counts[side] = len(spans)
            evidence[side] = {'source_identity': identity(text.encode()), 'scope': [start, end],
                              'matches': [{'start': a, 'end': b, 'raw': text[a:b]} for a, b in spans]}
        assert counts['before'] == counts['after'] and counts['after'] > 0, out
        if 'branch' in item:
            assert counts == {'before': 1, 'after': 1}
        out.update(counts=counts, evidence=evidence)
        results.append(out)

    qa_path = 'qa/b4-no-bypass/test_evaluated_published_read_source_closure.py'
    qa_text = (BASE / 'before' / qa_path).read_text()
    assert 'self.manifest["boundary"][541:569], ORDINARY_NEW_BOUNDARIES' in qa_text
    assert 'self.assertEqual(len(boundaries), 621)' in qa_text
    provider = (BASE / 'before/qa/b4-no-bypass/test_resident_provider_local_read_source_closure.py').read_text()
    assert 'self.manifest["boundary"][569:], CONTRACT["new_boundaries"]' in provider
    output = {
        'format': 'hepta-actual-fmt-targeted-qa-diagnostic-classification-v1',
        'input_fmt': identity(packet_raw), 'actual_inventory': identity(inventory_raw),
        'input_diagnostic': identity((HERE / 'LITERAL_OCCURRENCE_DIAGNOSTIC.json').read_bytes()),
        'classification_counts': dict(collections.Counter(x['category'] for x in classifications)),
        'classifications': classifications, 'targeted_marker_checks': results,
        'targeted_marker_check_count': len(results),
        'identified_fmt_induced_marker_migrations': [],
        'required_refresh_obligations': [
            'Recompute affected exact masked/literal scope hashes and module shapes from actual post-format bytes. The affected-path counts are upper bounds, not claims that every contained hash differs.',
            'After sole-writer contract refresh, synchronize its exact SHA256 in test_resident_provider_local_read_source_closure.py without changing the failure predicate.',
            'After independent coordinator registration, update full-inventory count 621 and complete boundary digests to the final exact manifest, preserving the historical ORDINARY_NEW_BOUNDARIES slice [541:569] and the full provider extension slice [569:].',
            'Append actual new Root test FQNs/parent mounts to the existing exact workflow and QA inventories; do not count ignored methods as default passes or alter budgets.',
            'Retain original source roots, ignored paths, forbidden markers, scope selectors, each occurrence attack, same-function assertions and failure expectations.'
        ],
        'limitations': [
            'No QA, verifier, collector, Rust compiler, formatter, native H job, or source mutation was executed.',
            'The initial scan covers AST Constant strings, not arbitrary evaluation of every dynamically constructed Python expression.',
            'The twelve targeted checks close the concrete composite/branch risks found in that diagnostic, not all possible runtime paths.',
            'The independent 83-attack report verifies source anchor occurrence stability only, not mutant rejection.',
            'No conclusion is inherited from historical source qualification, and no complete repository scan or final registration approval is asserted.'
        ]
    }
    raw = (json.dumps(output, sort_keys=True, indent=2) + '\n').encode()
    with (HERE / 'TARGETED_LITERAL_CLASSIFICATION.json').open('xb') as f:
        f.write(raw)
    print(json.dumps({'identity': identity(raw), 'classification_counts': output['classification_counts'],
                      'targeted_checks': len(results), 'fmt_induced_migrations': []}, sort_keys=True))


if __name__ == '__main__':
    main()
