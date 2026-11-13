"""Reviewer-owned, standard-library-only byte and declaration analysis.

Never imports project modules, invokes a Rust/QA collector, or runs author
preparation code. All source reads are from the explicitly frozen local inputs.
"""
from pathlib import Path
import base64
import copy
import difflib
import gzip
import hashlib
import json
import re
import tomllib

ROOT = Path('/tmp/hepta-36fa-root-product-e2-proposal-v1')
DATA = ROOT / 'registration-components-frozen-v2'
VIEW = Path('/tmp/hepta-36fa-root-product-composition-v6/after')
BASE = Path('/tmp/hepta-36fa-e1-source-candidate-v1/after/CALLERS.toml')
OUT = Path('/tmp/hepta-36fa-e2-registration-independent-review-v1')
META = Path('/tmp/hepta-36fa-e2-declaration-metadata-increment-v1')
PREFIX = 'codex-rs/hepta-agentd/src/'


def pin(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                git_blob=hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest())


def check(raw, expected):
    actual = pin(raw)
    assert actual == {k: expected[k] for k in actual}, (actual, expected)
    return actual


def strict_pairs(pairs):
    out = {}
    for key, value in pairs:
        assert key not in out, key
        out[key] = value
    return out


def read_json(path):
    return json.loads(path.read_bytes(), object_pairs_hook=strict_pairs)


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + '\n').encode()


def save(path, raw):
    if not isinstance(raw, bytes):
        raw = json_bytes(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)
    assert path.read_bytes() == raw
    return dict(path=str(path), **pin(raw))


def rust_code(text):
    """Mask Rust comments and literal tokens without changing character offsets.

    Lifetimes are left in place. This is a bounded lexical aid for the frozen
    sources, not a Rust type checker or a substitute for the project collector.
    """
    result = list(text)
    position = 0
    size = len(text)
    while position < size:
        end = None
        if text.startswith('//', position):
            end = text.find('\n', position)
            if end < 0:
                end = size
        elif text.startswith('/*', position):
            depth, end = 1, position + 2
            while end < size and depth:
                if text.startswith('/*', end):
                    depth += 1
                    end += 2
                elif text.startswith('*/', end):
                    depth -= 1
                    end += 2
                else:
                    end += 1
            assert depth == 0
        else:
            raw = re.match(r'(?:br|cr|r)(#*)"', text[position:])
            if raw:
                suffix = '"' + raw.group(1)
                close = text.find(suffix, position + raw.end())
                assert close >= 0
                end = close + len(suffix)
            elif text[position] == '"':
                end = position + 1
                while end < size:
                    if text[end] == '\\':
                        end += 2
                    elif text[end] == '"':
                        end += 1
                        break
                    else:
                        end += 1
                assert end <= size and text[end - 1] == '"'
            elif text[position] == "'":
                char = re.match(r"'(?:\\(?:u\{[0-9a-fA-F_]+\}|x[0-9a-fA-F]{2}|.)|[^'\\\n])'", text[position:])
                if char:
                    end = position + char.end()
        if end is None:
            position += 1
        else:
            for i in range(position, end):
                if result[i] != '\n':
                    result[i] = ' '
            position = end
    return ''.join(result)


def balanced(code):
    pending, pairs = [], {}
    for position, char in enumerate(code):
        if char == '{':
            pending.append(position)
        elif char == '}':
            assert pending, position
            pairs[pending.pop()] = position + 1
    assert not pending, pending
    return pairs


def declarations(text):
    code = rust_code(text)
    braces = balanced(code)
    implementations = []
    for match in re.finditer(r'(?m)^[ \t]*impl\b', code):
        opening = code.find('{', match.end())
        assert opening in braces
        implementations.append((match.start(), braces[opening], text[match.start():opening].strip()))
    functions = []
    pattern = r'(?m)^[ \t]*(?:(pub(?:\([^\n]*?\))?)\s+)?(?:(?:async|unsafe|const)\s+)*fn\s+(\w+)\s*[(<]'
    for match in re.finditer(pattern, code):
        parens = brackets = 0
        opening = None
        # Include the opening parenthesis captured by the expression; array
        # semicolons are parameter syntax, not abstract-method terminators.
        for position in range(match.end() - 1, len(code)):
            char = code[position]
            if char == '(':
                parens += 1
            elif char == ')':
                parens -= 1
            elif char == '[':
                brackets += 1
            elif char == ']':
                brackets -= 1
            elif char == ';' and parens <= 0 and brackets == 0:
                break
            elif char == '{' and parens <= 0 and brackets == 0:
                opening = position
                break
        if opening is None:
            continue
        assert opening in braces
        end = braces[opening]
        enclosing = [x for x in implementations if x[0] < match.start() < x[1]]
        header = min(enclosing, key=lambda x: x[1] - x[0])[2] if enclosing else None
        functions.append(dict(name=match.group(2), visibility=match.group(1) or 'private',
                              impl_header=header, start=match.start(), end=end,
                              body=text[match.start():end]))
    # All explicit non-private declarations in the fixed production sources
    # must be represented by the line-based function matcher, including those
    # with bracketed fixed-size parameters. Abstract trait methods have no pub.
    visible = list(re.finditer(r'\bpub(?:\([^\n]*?\))?\s+(?:(?:async|unsafe|const)\s+)*fn\s+(\w+)\b', code))
    assert len(visible) == sum(f['visibility'] != 'private' for f in functions), (len(visible), len(functions))
    return functions


def source_layers(source_index):
    original, own, packet_audits = {}, {}, []
    for layer in source_index['layers']:
        path = ROOT / layer['layer'] / 'SOURCE_PACKET.json'
        packet_raw = path.read_bytes()
        check(packet_raw, layer)
        packet = read_json(path)
        entries = packet.get('entries', packet.get('images'))
        assert isinstance(entries, list)
        layer_paths = []
        for row in entries:
            relative = row['path']
            before, after = row.get('before_utf8'), row.get('after_utf8')
            if after is None and isinstance(row.get('after'), str):
                before, after = row['before'], row['after']
            assert isinstance(after, str)
            for side, body in [('before', before), ('after', after)]:
                if isinstance(row.get(side), dict):
                    check(body.encode(), row[side])
            if relative in own:
                assert own[relative] == before, (layer['layer'], relative)
            else:
                original[relative] = before
            own[relative] = after
            layer_paths.append(relative)
        assert len(layer_paths) == len(set(layer_paths))
        packet_audits.append(dict(layer=layer['layer'], **pin(packet_raw), paths=layer_paths))
    assert len(own) == 67
    view = {}
    for entry in source_index['files']:
        path = entry['path']
        check(own[path].encode(), entry['e2_own'])
        if path == PREFIX + 'authority_host_session_generation_task_handoff.rs':
            body = own[path]
        else:
            body = (VIEW / path).read_bytes().decode()
        check(body.encode(), entry['reviewed_composed'])
        assert entry['shared_other_frozen_layers'] == (body != own[path])
        view[path] = body
    assert set(view) == set(own)
    return original, own, view, packet_audits


def main():
    manifest = read_json(DATA / 'MANIFEST.json')
    assert pin((DATA / 'MANIFEST.json').read_bytes())['git_blob'] == '7cb9cbfbad4887a79128e085e54792d960fbf3e3'
    checked_inputs = []
    for row in manifest['files']:
        raw = (DATA / row['path']).read_bytes()
        checked_inputs.append(dict(path=row['path'], **check(raw, row)))
    representations = []
    for representation in read_json(DATA / 'LOSSLESS_REPRESENTATIONS.json'):
        zipped = bytearray()
        for part in representation['parts']:
            encoded = (DATA / part['path']).read_bytes()
            check(encoded, part)
            assert len(encoded) <= manifest['bounded_part_limit'] == 262145
            assert encoded.endswith(b'\n') and b'\n' not in encoded[:-1]
            decoded = base64.b64decode(encoded[:-1], validate=True)
            assert base64.b64encode(decoded) + b'\n' == encoded
            assert len(zipped) == part['offset']
            check(decoded, part['decoded'])
            zipped.extend(decoded)
        check(bytes(zipped), representation['gzip'])
        recovered = gzip.decompress(zipped)
        check(recovered, representation['raw'])
        assert recovered == (DATA / representation['raw_path']).read_bytes()
        representations.append(dict(path=representation['raw_path'], raw=pin(recovered),
                                    gzip=pin(zipped), parts=representation['parts'], exact=True))

    boundary = read_json(DATA / 'BOUNDARY_ROWS.json')
    protected = read_json(DATA / 'PROTECTED_ROWS.json')
    source_index = read_json(DATA / 'SOURCE_PINS.json')
    original, own, view, layer_audit = source_layers(source_index)
    before_raw = BASE.read_bytes()
    after_raw = (DATA / 'CALLERS_E1_E2_PROJECTION.toml').read_bytes()
    before, after = tomllib.loads(before_raw.decode()), tomllib.loads(after_raw.decode())
    check(before_raw, boundary['base_callers'])
    assert len(before['boundary']) == 650 and len(before['protected_file']) == 451
    splice_document = read_json(DATA / 'EXACT_REGISTRATION_SPLICES.json')
    check(before_raw, splice_document['before'])
    check(after_raw, splice_document['after'])
    forward = before_raw.decode()
    splice_audit = []
    for splice in splice_document['splices']:
        old, new = splice['before_utf8'], splice['after_utf8']
        check(old.encode(), splice['before'])
        check(new.encode(), splice['after'])
        assert forward.count(old) == 1, splice['label']
        forward = forward.replace(old, new, 1)
        splice_audit.append(dict(label=splice['label'], before=splice['before'], after=splice['after']))
    assert forward.encode() == after_raw
    reverse = forward
    for splice in reversed(splice_document['splices']):
        assert reverse.count(splice['after_utf8']) == 1, splice['label']
        reverse = reverse.replace(splice['after_utf8'], splice['before_utf8'], 1)
    assert reverse.encode() == before_raw
    assert len(splice_audit) == 19

    old_changes = {x['index']: x for x in boundary['old_row_changes']}
    assert len(old_changes) == 12
    for index, row in enumerate(before['boundary']):
        expected = old_changes[index]['after'] if index in old_changes else row
        assert after['boundary'][index] == expected
        assert {k: v for k, v in row.items() if k != 'product_callers'} == {k: v for k, v in expected.items() if k != 'product_callers'}
        if index in old_changes:
            change = old_changes[index]
            assert row == change['before']
            assert expected['product_callers'] == row['product_callers'] + change['added_callers']
            assert set(row['product_callers']).isdisjoint(change['added_callers'])
    assert sum(len(x['added_callers']) for x in old_changes.values()) == 15
    assert len(boundary['new_rows']) == 91
    assert after['boundary'][650:] == boundary['new_rows']
    new_ids = [x['id'] for x in boundary['new_rows']]
    assert len(set(new_ids)) == 91 and set(new_ids).isdisjoint(x['id'] for x in before['boundary'])
    assert len({x['symbol'] for x in boundary['new_rows']}) == 91
    assert {x['symbol'] for x in boundary['new_rows']}.isdisjoint(x['symbol'] for x in before['boundary'])
    assert boundary['required_boundary_ids_append'] == new_ids

    old_guards = {x['index']: x for x in protected['old_required_rebindings']}
    assert sorted(old_guards) == [265, 444, 446, 447, 449]
    required_audit = []
    for index, row in enumerate(before['protected_file']):
        expected = old_guards[index]['after'] if index in old_guards else row
        assert after['protected_file'][index] == expected
        assert {k: v for k, v in row.items() if k != 'required'} == {k: v for k, v in expected.items() if k != 'required'}
        if index in old_guards:
            change = old_guards[index]
            assert row == change['before']
            rebuilt = copy.deepcopy(row)
            for replacement in change['required_replacements']:
                j = replacement['required_index']
                assert rebuilt['required'][j] == replacement['before_utf8']
                check(replacement['before_utf8'].encode(), replacement['before'])
                check(replacement['after_utf8'].encode(), replacement['after'])
                rebuilt['required'][j] = replacement['after_utf8']
                assert replacement['after_utf8'] in view[change['path']]
                required_audit.append(dict(index=index, required_index=j, path=change['path'],
                                           before=replacement['before'], after=replacement['after']))
            assert rebuilt == expected
            check(view[change['path']].encode(), change['source_after'])
    assert len(required_audit) == 7
    assert after['protected_file'][411] == before['protected_file'][411]
    assert after['protected_file'][198] == before['protected_file'][198] == protected['original_feature_guard_198_unchanged']
    assert after['protected_file'][451:] == protected['append_protected_rows']
    assert len(protected['append_protected_rows']) == 61
    assert len({x['path'] for x in protected['append_protected_rows']}) == 61
    for row in protected['append_protected_rows']:
        assert row['required'] == [view[row['path']]]
        assert row['forbidden'] == ['SigningKey::generate', 'SigningKey::from_bytes', 'permit_all', 'AllowVerifier']
        assert not row['path'].endswith('_tests.rs')
        assert not any(marker in view[row['path']] for marker in row['forbidden'])
    for key in before:
        if key not in ['boundary', 'protected_file', 'privileged_inventory']:
            assert after[key] == before[key], key
    assert set(after) == set(before)
    pi = copy.deepcopy(before['privileged_inventory'])
    pi['required_boundary_ids'] += new_ids
    assert after['privileged_inventory'] == pi
    assert all(x is False for x in after['authority'].values())
    assert after['ignored_path_fragments'] == ['/tests/', '/examples/', '_tests.rs']

    # Re-enumerate explicit production declarations from the 12 exact layers.
    # This checks the metadata inventory; it does not execute the project scan.
    own_functions, view_functions, new_definitions = {}, {}, []
    for path in sorted(own):
        if path.endswith('_tests.rs'):
            continue
        own_functions[path] = declarations(own[path])
        view_functions[path] = declarations(view[path])
        old_functions = declarations(original[path]) if original[path] is not None else []
        old_keys = {(x['impl_header'], x['name'], x['visibility']) for x in old_functions}
        for function in own_functions[path]:
            key = (function['impl_header'], function['name'], function['visibility'])
            if function['visibility'] != 'private' and key not in old_keys:
                new_definitions.append(dict(path=path, **function))
    declared = read_json(DATA / 'DECLARATION_DISPOSITIONS.json')
    def key(row):
        return row['path'], row['impl_header'], row['name'], row['visibility']
    assert len(declared) == 157 == len(new_definitions)
    assert len({key(x) for x in declared}) == 157
    assert {key(x) for x in declared} == {key(x) for x in new_definitions}

    # Root requested a separate metadata successor bound to each existing
    # whole_source_required target, including the six shared Root-v6 images.
    refreshed = copy.deepcopy(declared)
    metadata_changes, unique_matches = [], []
    for index, row in enumerate(declared):
        check(view[row['path']].encode(), row['whole_source_required'])
        matches = [x for x in view_functions[row['path']]
                   if (x['impl_header'], x['name'], x['visibility']) == (row['impl_header'], row['name'], row['visibility'])]
        assert len(matches) == 1, key(row)
        current = matches[0]
        target = refreshed[index]
        for field in ['start', 'end', 'body']:
            target[field] = current[field]
        target['identity'] = pin(current['body'].encode())
        immutable = set(row) - {'start', 'end', 'body', 'identity'}
        assert all(row[k] == target[k] for k in immutable)
        assert view[row['path']][target['start']:target['end']] == target['body']
        unique_matches.append(dict(index=index, path=row['path'], name=row['name'],
                                   impl_header=row['impl_header'], visibility=row['visibility'],
                                   match_count=1, source=row['whole_source_required'],
                                   start=target['start'], end=target['end'], identity=target['identity']))
        if target != row:
            metadata_changes.append(dict(index=index, path=row['path'], name=row['name'],
                                         impl_header=row['impl_header'], visibility=row['visibility'],
                                         changed_fields=sorted(k for k in row if row[k] != target[k]),
                                         source=row['whole_source_required'],
                                         before={k: row[k] for k in ['start', 'end', 'identity']},
                                         after={k: target[k] for k in ['start', 'end', 'identity']},
                                         body_changed=row['body'] != target['body']))
    assert len(metadata_changes) == 10
    assert sum(x['body_changed'] for x in metadata_changes) == 4
    old_meta_raw = (DATA / 'DECLARATION_DISPOSITIONS.json').read_bytes()
    new_meta_raw = json_bytes(refreshed)
    assert json_bytes(declared) == old_meta_raw
    reverse_meta = copy.deepcopy(refreshed)
    for change in metadata_changes:
        index = change['index']
        for field in ['start', 'end', 'body', 'identity']:
            reverse_meta[index][field] = declared[index][field]
    assert json_bytes(reverse_meta) == old_meta_raw
    metadata_files = []
    metadata_files.append(save(META / 'DECLARATION_DISPOSITIONS.before.json', old_meta_raw))
    metadata_files.append(save(META / 'DECLARATION_DISPOSITIONS.after.json', new_meta_raw))
    patch = ''.join(difflib.unified_diff(old_meta_raw.decode().splitlines(True), new_meta_raw.decode().splitlines(True),
                                       fromfile='DECLARATION_DISPOSITIONS.before.json', tofile='DECLARATION_DISPOSITIONS.after.json')).encode()
    metadata_files.append(save(META / 'EXACT_METADATA_DELTA.patch', patch))
    metadata_files.append(save(META / 'MATCH_AND_INVERSE_PROOF.json', dict(
        format='hepta-independent-e2-declaration-metadata-rebinding-proof-v1',
        before=pin(old_meta_raw), after=pin(new_meta_raw), all_157_unique_matches=unique_matches,
        changes=metadata_changes, exact_inverse_equal=True,
        allowed_fields=['start', 'end', 'body', 'identity'], all_other_fields_identical=True,
        old_metadata_preserved=True, source_changed=False, collector_executed=False,
        source_target_rule='Exact existing whole_source_required body; 67 frozen own paths with six reviewed Root-v6 shared images.')))

    alias = {'original_remote_channel': 'channel', 'original_remote_channel_until': 'channel_until'}
    definition_audit, caller_locations = [], []
    for row in boundary['new_rows']:
        path = row['definition_path']
        assert all(marker in view[path] for marker in row['definition_markers'])
        assert path not in row['product_callers']
        assert len(row['product_callers']) == len(set(row['product_callers']))
        method = alias.get(row['symbol'].rsplit('::', 1)[-1], row['symbol'].rsplit('::', 1)[-1])
        receiver = row.get('receiver_type')
        bodies = [x for x in view_functions[path] if x['name'] == method and
                  ((receiver and receiver in (x['impl_header'] or '')) or
                   (not receiver and (not x['impl_header'] or row['symbol'] == 'material::Client::read')))]
        abstract = row['id'] in {
            'e2_original_root_lane_factory_take', 'e2_original_root_lane_factory_original_handoff_registry',
            'e2_original_root_cell_pump_execute', 'e2_original_root_cell_pump_read', 'e2_original_root_cell_pump_clock'}
        assert len(bodies) == (0 if abstract else 1), (row['id'], len(bodies))
        definition_audit.append(dict(id=row['id'], path=path, symbol=row['symbol'], receiver=receiver,
                                     abstract_trait_method=abstract, matches=len(bodies),
                                     identity=pin(bodies[0]['body'].encode()) if bodies else None))
        for caller in row['product_callers']:
            body = view[caller]
            code = rust_code(body)
            search = row.get('call_pattern', r'\b' + re.escape(row['symbol'].rsplit('::', 1)[-1]) + r'\s*\(')
            matches = list(re.finditer(search, code))
            assert matches, (row['id'], caller, search)
            caller_locations.append(dict(id=row['id'], symbol=row['symbol'], caller=caller,
                                         lexical_candidates=[dict(line=body.count('\n', 0, m.start()) + 1,
                                                                  context=body[max(0, body.rfind('\n', 0, m.start()) + 1):body.find('\n', m.end()) if body.find('\n', m.end()) >= 0 else len(body)]) for m in matches],
                                         note='Explicit frozen call-site text, followed by manual receiver review; not a project typed scan.'))
    material = next(row for row in boundary['new_rows'] if row['id'] == 'e2_material_client_read')
    assert 'receiver_type' not in material
    material_matches = {path: len(re.findall(material['call_pattern'], rust_code(body))) for path, body in view.items()}
    assert {p: n for p, n in material_matches.items() if n} == {PREFIX + 'circuit_task_source_readback.rs': 2}
    classified_ids = {item for row in refreshed for item in row['boundary_ids']}
    assert len(classified_ids) == 86
    for row in refreshed:
        matches = []
        for new in boundary['new_rows']:
            method = alias.get(new['symbol'].rsplit('::', 1)[-1], new['symbol'].rsplit('::', 1)[-1])
            if new['definition_path'] != row['path'] or method != row['name']:
                continue
            receiver = new.get('receiver_type')
            if receiver and receiver not in (row['impl_header'] or ''):
                continue
            if not receiver and row['impl_header'] and new['symbol'] != 'material::Client::read':
                continue
            matches.append(new['id'])
        assert matches == row['boundary_ids']
        if row['path'] == PREFIX + 'circuit_task_driver.rs' and row['name'] == 'execute':
            assert row['body'] in original[row['path']]

    feature = 'codex-rs/hepta-neuron/src/feature_control.rs'
    feature_guard = before['protected_file'][198]
    assert all(item in view[feature] for item in feature_guard['required'])
    for ordered in feature_guard.get('required_function_order', []):
        offset = 0
        for item in ordered['sequence']:
            offset = view[feature].index(item, offset) + len(item)

    report = dict(
        format='hepta-independent-e2-registration-byte-proof-v1',
        project_execution=False, h=False, project_collector_executed=False,
        input_manifest=pin((DATA / 'MANIFEST.json').read_bytes()), input_files=checked_inputs,
        lossless=representations, source_layers=layer_audit, source_files=source_index['files'],
        base_callers=pin(before_raw), projection=pin(after_raw), splices=splice_audit,
        exact_full_forward_and_reverse=True,
        preservation=dict(old_boundaries=650, old_noncaller_fields_equal=True,
                          old_append_rows=12, old_added_callers=15, new_boundaries=91,
                          old_protected_rows=451, old_nonrequired_fields_equal=True,
                          old_required_rebindings=required_audit, new_full_file_guards=61,
                          old_row_411_equal=True, old_feature_198_equal=True,
                          all_forbidden_and_order_fields_equal=True,
                          authority_all_false=True, ignored_path_fragments_equal=True,
                          only_other_change='91 required_boundary_ids appended in order'),
        explicit_declarations=dict(count=157, independently_enumerated_exact_key_set=True,
                                   explicit_boundaries=86, abstract_trait_boundaries=5,
                                   unregistered_bounded_helpers=70, original_execute_body=1,
                                   stale_original_metadata=metadata_changes,
                                   separate_metadata_successor=metadata_files),
        definition_audit=definition_audit, caller_locations=caller_locations,
        limited_scope='Only the frozen E2 projection and listed sources. No final E1/E2/E3/loader union, project typed scan, QA, Rust, source gate, or runtime qualification.')
    save(OUT / 'BYTE_AND_SOURCE_PROOF.json', report)
    print(json.dumps(dict(status='PURE_BYTE_AND_SOURCE_ANALYSIS_COMPLETE', output=str(OUT),
                          metadata_successor=str(META), stale_declarations=len(metadata_changes),
                          body_changes=sum(x['body_changed'] for x in metadata_changes),
                          caller_pairs=len(caller_locations), byte_proof=pin((OUT / 'BYTE_AND_SOURCE_PROOF.json').read_bytes())), indent=2))


if __name__ == '__main__':
    main()
