"""Reviewer-owned pure byte/lexical verification of two fixed source layers.

Reads only explicit local artifacts. Does not import project or author code,
invoke Rust/QA/collector tools, contact H, or mutate candidate source.
"""
from pathlib import Path
import ast
import hashlib
import json
import re

ROOT = Path('/tmp/hepta-36fa-root-product-e2-proposal-v1')
OUT = Path('/tmp/hepta-36fa-e2-prefreeze-successors-independent-review-v1')
V8 = Path('/tmp/hepta-36fa-root-product-composition-v8/after')
V9 = Path('/tmp/hepta-36fa-root-product-composition-v9/after')
LEX = Path('/tmp/hepta-36fa-e2-registration-independent-review-v1/review_bytes_v2.py')


def pin(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                git_blob=hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest())


def check(raw, expected):
    actual = pin(raw)
    assert actual == {key: expected[key] for key in actual}, (actual, expected)
    return actual


def pairs(items):
    result = {}
    for key, value in items:
        assert key not in result, key
        result[key] = value
    return result


def read_json(path):
    return json.loads(path.read_bytes(), object_pairs_hook=pairs)


def save(name, value):
    raw = (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + '\n').encode()
    path = OUT / name
    with path.open('xb') as target:
        target.write(raw)
    assert path.read_bytes() == raw
    return dict(path=str(path), **pin(raw))


def main():
    own_ast = ast.parse(LEX.read_text())
    selected = [n for n in own_ast.body if isinstance(n, ast.FunctionDef)
                and n.name in {'rust_code', 'balanced', 'declarations'}]
    assert {n.name for n in selected} == {'rust_code', 'balanced', 'declarations'}
    namespace = {'re': re}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(LEX), 'exec'), namespace)
    declarations = namespace['declarations']
    layers = [
        ('common-startup-increment-v1', '07cb756ca663e7fd802e008e258cb3828d73e636'),
        ('prefreeze-mechanism-tests-layer-v1', '474fe0d12b9d73cb94136e4e46d09394e495bbe3'),
    ]
    provided, inputs, audit = {}, [], []
    for dependency in ['prefreeze-source-layer-v1', 'prefreeze-ready-increment-v1']:
        packet_path = ROOT / dependency / 'SOURCE_PACKET.json'
        packet = read_json(packet_path)
        inputs.append(dict(path=str(packet_path), **pin(packet_path.read_bytes())))
        for entry in packet['entries']:
            check(entry['after_utf8'].encode(), entry['after'])
            provided[entry['path']] = entry['after_utf8']
    all_entries = {}
    for layer, expected in layers:
        directory = ROOT / layer
        raw = (directory / 'SOURCE_PACKET.json').read_bytes()
        assert pin(raw)['git_blob'] == expected
        manifest = read_json(directory / 'MANIFEST.json')
        inputs.append(dict(path=str(directory / 'MANIFEST.json'),
                           **pin((directory / 'MANIFEST.json').read_bytes())))
        for entry in manifest['files']:
            body = (directory / entry['path']).read_bytes()
            inputs.append(dict(path=str(directory / entry['path']), **check(body, entry)))
        packet = read_json(directory / 'SOURCE_PACKET.json')
        entries = packet['entries']
        assert len({e['path'] for e in entries}) == len(entries)
        rows = []
        for entry in entries:
            path = entry['path']
            before, after = entry.get('before_utf8'), entry['after_utf8']
            check(after.encode(), entry['after'])
            if entry['before'] is not None:
                check(before.encode(), entry['before'])
                baseline = provided.get(path)
                if baseline is None:
                    baseline = (V8 / path).read_bytes().decode()
                assert before == baseline, path
            else:
                assert before is None and not (V8 / path).exists() and path not in provided
            assert (V9 / path).read_bytes() == after.encode(), path
            before_defs = declarations(before) if before is not None else []
            after_defs = declarations(after)
            rows.append(dict(path=path, before=entry['before'], after=entry['after'],
                             old_function_count=len(before_defs), new_function_count=len(after_defs),
                             v9_exact=True,
                             declarations=[dict(name=f['name'], visibility=f['visibility'],
                                 receiver=f['impl_header'], line=after[:f['start']].count('\n')+1,
                                 body_pin=pin(f['body'].encode())) for f in after_defs]))
            all_entries[path] = entry
        audit.append(dict(layer=layer, source_packet=pin(raw), rows=rows))

    common_entry = next(iter(read_json(ROOT / layers[0][0] / 'SOURCE_PACKET.json')['entries']))
    before, after = common_entry['before_utf8'], common_entry['after_utf8']
    before_defs, after_defs = declarations(before), declarations(after)
    assert len(before_defs) == 1 and len(after_defs) == 2
    old = before_defs[0]
    public = next(f for f in after_defs if f['name'] == old['name'])
    internal = next(f for f in after_defs if f['name'] == old['name'] + '_before')
    assert public['visibility'] == 'pub' and internal['visibility'] == 'pub(crate)'
    first = '        self.read_original_root_task_generation()?;'
    old_suffix = old['body'][old['body'].index(first):]
    new_suffix = internal['body'][internal['body'].index(first):]
    assert old_suffix == new_suffix
    old_signature = old['body'][:old['body'].index(' {')]
    new_signature = public['body'][:public['body'].index(' {')]
    assert old_signature == new_signature
    delegate = ('        PreparedRootHostCircuitTaskV1::handoff_and_serve_original_root_circuit_task_before(\n'
                '            self, production_handoff, task_handoff, original_root_pidfd, consumer_state_root,\n'
                '            task_path, loan_path, session_nonce, startup_end,\n'
                '        )\n    }')
    assert public['body'].endswith(delegate)
    assert public['body'].count('handoff_and_serve_original_root_circuit_task_before(') == 1
    clamp = 'let startup_end = startup_end.min(Instant::now() + Duration::from_secs(30)).min(self.end);'
    assert clamp in internal['body']
    assert internal['body'].index(clamp) < internal['body'].index('require_before(startup_end)?;') < internal['body'].index(first)
    splices = read_json(ROOT / layers[0][0] / 'EXACT_SOURCE_SPLICES.json')
    common_splices = splices.get('splices', splices.get('operations'))
    assert isinstance(common_splices, list) and len(common_splices) == 1
    s = common_splices[0]
    old_part, new_part = s['before_utf8'], s['after_utf8']
    assert before.count(old_part) == 1
    position = before.index(old_part)
    forward = before[:position] + new_part + before[position+len(old_part):]
    assert forward == after
    assert after[:position] + old_part + after[position+len(new_part):] == before

    tests_packet = read_json(ROOT / layers[1][0] / 'SOURCE_PACKET.json')
    test_splices = read_json(ROOT / layers[1][0] / 'EXACT_SOURCE_SPLICES.json')['splices']
    tests_by_path = {e['path']: e for e in tests_packet['entries']}
    assert len(tests_by_path) == 8 and len(test_splices) == 4
    mounts = []
    for s in test_splices:
        e = tests_by_path[s['path']]
        assert len(e['before_utf8'].encode()) == s['before_bytes']
        assert e['after_utf8'] == e['before_utf8'] + s['append_utf8']
        assert e['after_utf8'][:-len(s['append_utf8'])] == e['before_utf8']
        assert declarations(e['before_utf8']) == declarations(e['after_utf8'])
        mounts.append(dict(path=s['path'], prefix_preserved=True, append=s['append_utf8'],
                           unchanged_function_count=len(declarations(e['before_utf8']))))
    cases = []
    for e in tests_packet['entries']:
        if e['before'] is None:
            body = e['after_utf8']
            for f in declarations(body):
                prefix = body[max(0, f['start']-160):f['start']]
                if '#[test]' in prefix or '#[tokio::test]' in prefix:
                    cases.append(dict(path=e['path'], name=f['name'],
                        ignored='#[ignore =' in prefix, line=body[:f['start']].count('\n')+1,
                        exact_body=f['body'], body_pin=pin(f['body'].encode())))
    assert len(cases) == 4 and sum(c['ignored'] for c in cases) == 1
    hint = next(c for c in cases if c['name'].startswith('original_source_hint'))['exact_body']
    assert hint.index('let joined = worker.join()') < hint.index('    result?;') < hint.index('    joined??;')
    assert 'hint.wait_original(end)?;' in hint and 'original.wait_original(expired)' in hint
    root = next(c for c in cases if c['ignored'])['exact_body']
    assert root.index('task.finish().await') < root.index('fixture.finish()') < root.index('    body?;')
    assert root.count('read_original_prefreeze_source(') == 2
    assert 'first == second' in root and 'fixture.original.generation_bytes()? == journal' in root
    positive = next(c for c in cases if c['name'] == 'prefreeze_request_reads_actual_source_without_future_evidence')['exact_body']
    negative = next(c for c in cases if c['name'] == 'prefreeze_request_refuses_rebinding_and_other_enrolled_generator')['exact_body']
    assert positive.index('fixture.source.withdraw_source(') < positive.index('evidence.verify()? == admitted') < positive.index('== Err(Error::Unavailable)')
    assert negative.count('evidence.verify() == Err(Error::InvalidBinding)') == 5
    assert negative.index('evidence.verifier.verify(') < negative.index('evidence.request.require_evidence(')
    assert 'evidence.verify()? == original_binding' in negative
    result = dict(format='hepta-prefreeze-successors-independent-byte-proof-v1',
                  H_calls=0, project_execution=False, source_or_registry_edits=False,
                  source_git_writes=False, all_declared_checks_passed=True,
                  inputs=inputs, layers=audit,
                  common_startup=dict(public_signature_same=True, original_body_suffix_exact=True,
                      suffix_bytes=len(old_suffix.encode()), suffix_pin=pin(old_suffix.encode()),
                      delegation_once=True, private_clamp=clamp,
                      original_body_retains_single_lane_before_bind_send=True,
                      original_body_retains_original_scoped_threads_and_join=True,
                      sole_splice_forward_and_inverse_exact=True),
                  test_mounts=mounts, exact_cases=cases,
                  method_classification='One ignored Root case and three ordinary mechanism cases; no results executed.',
                  limits=['Lexical braces and signatures are not Rust type checking.',
                          'Tests do not establish real Root disclosure registration, cross-UID IPC, full cold recovery, or a functioning normal Material CLI.',
                          'No production method body is changed by the test layer.',
                          'The hint thread is joined before propagated Result errors; inherited RootSession timeout/cancellation does not prove worker termination.'])
    print(json.dumps(save('BYTE_AND_FLOW_PROOF.json', result)))


if __name__ == '__main__':
    main()
