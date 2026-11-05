#!/usr/bin/env python3
"""Reopen existing evidence only; never starts a native process or a test."""
import base64
import collections
import gzip
import hashlib
import json
import pathlib
import re
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent
WORK = ROOT.parents[1]
ORIG = ROOT / 'fb9-originals'
FB9 = 'fb9e131272f7e7a138d6c0d1af2b048b9a6ab7ff'
EXPECTED_TREES = {
    'fb9': FB9,
    '5b': 'b26598d0d97d8d51e723bb5582137315f2174d35',
    'e78': 'e78c819b8b1f435f8b37bea17b4ffdc724961aa2',
    'eed': 'ca1c4671ef6b2773280d01b5d76c6166252f5856',
}

def sha(data):
    return hashlib.sha256(data).hexdigest()

def git(data, kind='blob'):
    return hashlib.sha1(f'{kind} {len(data)}\0'.encode() + data).hexdigest()

def identity(path):
    data = path.read_bytes()
    return dict(path=str(path), bytes=len(data), sha256=sha(data), git_blob=git(data))

def read(path):
    return json.loads(path.read_text())

def save(name, value):
    path = ROOT / name
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    return identity(path)

def check_bytes(data, pin):
    assert len(data) == pin['bytes'], (len(data), pin)
    assert sha(data) == pin['sha256'], pin
    if 'git_blob' in pin:
        assert git(data) == pin['git_blob'], pin

def merkle(leaves):
    root = {}
    for leaf in leaves:
        node = root
        parts = leaf['path'].split('/')
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        assert parts[-1] not in node, leaf
        node[parts[-1]] = (leaf['mode'], leaf['sha'])
    count = 0
    def visit(node):
        nonlocal count
        entries = []
        for name, value in node.items():
            if isinstance(value, dict):
                mode, digest, order = '40000', visit(value), (name + '/').encode()
            else:
                mode, digest = value
                order = name.encode()
            entries.append((order, mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(digest)))
        count += 1
        return git(b''.join(item[1] for item in sorted(entries)), 'tree')
    return visit(root), count

def main():
    # Strictly reopen the pre-existing lossless archive, including all 22 parts.
    manifest_path = ROOT / 'fb9-original-archive-manifest.json'
    assert git(manifest_path.read_bytes()) == '87873969544e952a8fcff9ad771f834ffc856537'
    manifest = read(manifest_path)
    archive_assets, parts, originals = [], [], []
    for asset in manifest['assets']:
        chunks = []
        offset = 0
        for number, pin in enumerate(asset['chunks']):
            path = ROOT / 'fb9-transport' / f"{asset['name']}.part-{number:03d}.base64.txt"
            raw = path.read_bytes()
            check_bytes(raw, pin)
            assert pin['offset'] == offset
            offset += len(raw)
            chunks.append(raw)
            parts.append(identity(path))
        encoded = b''.join(chunks)
        assert len(encoded) == asset['base64_bytes'] and sha(encoded) == asset['base64_sha256']
        compressed = base64.b64decode(encoded, validate=True)
        check_bytes(compressed, asset['gzip'])
        decoded = gzip.decompress(compressed)
        check_bytes(decoded, asset['original'])
        path = ORIG / asset['name']
        assert path.read_bytes() == decoded
        archive_assets.append(identity(path))
        if asset['name'] != 'complete-small-originals.json':
            originals.append(identity(path))
    assert len(parts) == 22 and len(archive_assets) == 10
    small = read(ORIG / 'complete-small-originals.json')
    assert len(small['files']) == 33
    for record in small['files']:
        data = record['content'].encode()
        check_bytes(data, record)
        path = ORIG / 'small' / record['name']
        assert path.read_bytes() == data
        originals.append(identity(path))
    assert len(originals) == 42 and sum(x['bytes'] for x in originals) == 60915164

    old_ledger = read(ROOT / 'original-ledger.json')
    old_map = read(ROOT / 'original-case-map.json')
    assert git((ROOT / 'original-ledger.json').read_bytes()) == '63518e970668e3a77ade10ae0230b99bc728f726'
    assert git((ROOT / 'original-case-map.json').read_bytes()) == 'c9265a2edc78d3e78e6ef137cf90498194a5bf5c'
    old_row = next(row for row in old_map['rows'] if row['id'] == 'B09')
    ledger_row = next(row for row in old_ledger['items'] if row['id'] == 'B09')
    assert old_row['original_exit_condition_zh'] == ledger_row['original_exit_condition_zh']
    roster = old_row['case_roster']
    keys = [(row['binary'], row['test']) for row in roster]
    assert len(keys) == len(set(keys)) == 19

    review = read(ORIG / 'full-workspace-review.json')
    selection = read(ORIG / 'full-workspace-selection.json')
    catalog = read(ORIG / 'full-workspace-catalog.stdout')
    status = read(ORIG / 'full-workspace-status.json')
    command = read(ORIG / 'small/full-workspace-command.json')
    host = read(ORIG / 'small/native-host.json')
    assert command['argv'] == ['just', 'test', '--locked', '--cargo-profile', 'dev-small', '--no-tests', 'fail', '--retries', '0', '--success-output', 'immediate']
    assert command['source'] == review['source'] == selection['source'] == host['source'] == FB9
    assert command['attempt'] == 1 and review['retries'] == 0
    assert host['host_alias'] == 'rog' and host['uname'][0] == 'Linux' and host['uname'][4] == 'x86_64'
    assert 'host: x86_64-unknown-linux-gnu\n' in host['rustc']
    assert review['exit_code'] == status['exit_code'] == 100 and review['passed'] is False
    assert review['counts'] == {'PASS': 19490, 'FAIL': 16}
    assert review['binary_before'] == review['binary_after'] == selection['test_binaries_after_catalog_before_just']
    assert review['helpers_before'] == review['helpers_after'] == selection['helpers_after_catalog_before_just']
    assert len(review['binary_before']) == 321 and len(review['helpers_before']) == 33
    assert review['binary_stable'] and review['helpers_stable'] and review['source_unchanged']
    programs = {r['binary_id']: r for r in review['binary_before']}
    assert len(programs) == 321

    guards = []
    for path in sorted((ORIG / 'small').glob('*-source-guard.json')):
        guard = read(path)
        assert guard['expected_source'] == guard['actual_source'] == FB9
        assert guard['head'] == 'cabcb40d36e116beaa65750e1f674c52035da785'
        assert guard['ordinary_index']['sha256'] == 'c41b4d7645b2b88431ed024e9cc683e31d43fafe7290280eaf0bae656fd6a922'
        assert guard['ordinary_index']['bytes'] == 1222758
        assert guard['untracked_source_paths'] == guard['allowed_untracked_source_paths'] == []
        guards.append(dict(identity=identity(path), original=guard))
    assert len(guards) == 10
    assert all(g['original']['locks'] == guards[0]['original']['locks'] for g in guards)
    assert guards[0]['original']['locks']['codex-rs/Cargo.lock']['sha256'] == '4a7a5535cf045089458468411e126b5f59bc6bbf34fc0deead9b0c1b8d84000a'
    assert guards[0]['original']['locks']['MODULE.bazel.lock']['sha256'] == '11f8a421224b9b05f32c4c14054e8868083d989fc497310c8d51e1156f189ca3'

    def ckey(row):
        return row['classname'], row['name']
    selected = collections.Counter(ckey(row) for row in selection['expected_selected'])
    reviewed = collections.Counter((row['classname'], row['name'], row['result']) for row in review['cases'])
    cases = list(ET.parse(ORIG / 'full-workspace.junit.xml').iter('testcase'))
    xmlrows = [(e.get('classname'), e.get('name'), 'FAIL' if e.find('failure') is not None or e.find('error') is not None else 'SKIP' if e.find('skipped') is not None else 'PASS') for e in cases]
    assert len(cases) == 19506 and collections.Counter(xmlrows) == reviewed
    assert collections.Counter((c,n) for c,n,_ in xmlrows) == selected
    assert all(v == 1 for v in selected.values())
    xml_by_key = {(e.get('classname'),e.get('name')): e for e in cases}
    actual_catalog = collections.Counter()
    ignored_catalog = collections.Counter()
    for suite in catalog['rust-suites'].values():
        for name, detail in suite['testcases'].items():
            key = (suite['binary-id'], name)
            if detail['ignored'] is False and detail['filter-match'] == {'status':'matches'}:
                actual_catalog[key] += 1
            else:
                assert detail['ignored'] is True and detail['filter-match'] == {'status':'mismatch','reason':'ignored'}, (key,detail)
                ignored_catalog[key] += 1
    assert actual_catalog == selected and sum(ignored_catalog.values()) == 57
    early = review['early_return_case_observations']
    assert len(early) == 25
    early_keys = {(r['classname'],r['name']) for r in early}
    assert not set(keys) & early_keys

    raw = (ORIG / 'full-workspace.log').read_bytes()
    summary_matches = list(re.finditer(rb'^     Summary \[\s*227\.067s\] 19506 tests run: 19490 passed \(5 slow\), 16 failed, 57 skipped\r?$', raw, re.M))
    assert len(summary_matches) == 1
    summary_offset = summary_matches[0].start()
    header_pattern = rb'^        (PASS|FAIL|TIMEOUT) \[\s*([0-9.]+)s\] (\S+) ([^\r\n]+)\r?$'
    headers = list(re.finditer(header_pattern, raw[:summary_offset], re.M))
    summary_failures = collections.Counter((m[3].decode(),m[4].decode(),m[1].decode()) for m in re.finditer(header_pattern,raw[summary_offset:],re.M))
    assert summary_failures == collections.Counter({k:v for k,v in reviewed.items() if k[2]=='FAIL'})
    rawcounter = collections.Counter((m[3].decode(),m[4].decode(),m[1].decode()) for m in headers)
    assert rawcounter == reviewed, (len(headers),len(cases))
    by_key = collections.defaultdict(list)
    for i, m in enumerate(headers):
        by_key[(m[3].decode(),m[4].decode())].append((m, headers[i+1].start() if i+1 < len(headers) else summary_offset))
    excerpt_index = read(ROOT / 'source-case-excerpt-index.json')
    out = ROOT / 'raw-case-blocks'
    out.mkdir(exist_ok=True)
    case_rows = []
    skip_re = re.compile(rb'Skipping test (?:because|in the Wine)|skipping capability test:')
    for pos, (binary,name) in enumerate(keys,1):
        assert len(by_key[(binary,name)]) == 1
        m,end = by_key[(binary,name)][0]
        block = raw[m.start():end]
        assert m[1] == b'PASS'
        assert len(re.findall(rb'^    test '+re.escape(name.encode())+rb' \.\.\. ok\r?$',block,re.M)) == 1
        assert len(re.findall(rb'^    test result: ok\. 1 passed; 0 failed; 0 ignored; 0 measured; [0-9]+ filtered out; finished in [0-9.]+s\r?$',block,re.M)) == 1
        assert not skip_re.search(block)
        xml = xml_by_key[(binary,name)]
        assert xml.find('failure') is None and xml.find('skipped') is None and xml.find('error') is None
        dest = out/f'{pos:02d}-{name.split("::")[-1]}.log'
        dest.write_bytes(block)
        src = excerpt_index[pos-1]
        assert src['test'] == name and src['binary'] == binary
        source_file = pathlib.Path(src['source_excerpt']['source_file'])
        source_lines = source_file.read_bytes().splitlines(keepends=True)
        excerpt = pathlib.Path(src['source_excerpt']['path'])
        assert b''.join(source_lines[src['source_excerpt']['start_line']-1:src['source_excerpt']['end_line']]) == excerpt.read_bytes()
        case_rows.append(dict(position=pos, classname=binary, name=name, result='PASS', seconds=xml.get('time'),
            junit_attributes=dict(xml.attrib), raw_block=dict(identity(dest), byte_offset=m.start(), end_byte_offset_exclusive=end,
                first_line=raw.count(b'\n',0,m.start())+1, last_line=raw.count(b'\n',0,end)),
            original_program_before_and_after=programs[binary], original_catalog_detail=catalog['rust-suites'][binary]['testcases'][name],
            source_excerpt=dict(src['source_excerpt'],identity=identity(excerpt)), no_observed_early_return=True))
    feature = (out/'08-turn_recover_requires_hepta_turn_recovery_feature.log').read_text()
    assert 'turn/recover' in feature and 'disabled-feature-turn' in feature
    assert 'code: -32600' in feature and 'turn/recover requires features.hepta_turn_recovery=true' in feature

    trees, tree_rows = {}, []
    for label,expected in EXPECTED_TREES.items():
        path = ROOT/'fb9-leaves.json' if label=='fb9' else WORK/f'hepta-audit-fifth/recovery-2113/trees/{label}-leaves.json'
        tree = read(path)
        actual, count = merkle(tree['leaves'])
        assert tree['tree'] == actual == expected
        trees[label] = {x['path']:x for x in tree['leaves']}
        tree_rows.append(dict(label=label,tree=actual,leaves=len(tree['leaves']),merkle_nodes_recomputed=count,source=identity(path)))
    source_rows = []
    fetched = read(ROOT/'source-fetch-list.json') + read(ROOT/'source-fetch-additional-list.json')
    assert len({x['path'] for x in fetched}) == len(fetched)
    for row in fetched:
        path = ROOT/'source'/(row['path'].replace('/','__')+'.source.txt')
        pin = identity(path)
        assert pin['git_blob'] == row['sha']
        leaves = {label:{k:tree[row['path']][k] for k in ['mode','type','sha']} for label,tree in trees.items()}
        assert len({json.dumps(v,sort_keys=True) for v in leaves.values()}) == 1
        assert all(v['sha'] == pin['git_blob'] for v in leaves.values())
        source_rows.append(dict(logical_path=row['path'],identity=pin,leaves=leaves))
    invariant_build_inputs = []
    for path in trees['fb9']:
        if pathlib.PurePosixPath(path).name in ['Cargo.toml','Cargo.lock','MODULE.bazel.lock']:
            vals = [{k:t[path][k] for k in ['mode','type','sha']} for t in trees.values()]
            assert len({json.dumps(v,sort_keys=True) for v in vals}) == 1, path
            invariant_build_inputs.append(dict(path=path,leaf=vals[0]))

    bridge_pin = save('source-leaf-bridge-v1.json',dict(schema='b09-source-leaf-bridge/v1',trees=tree_rows,
        complete_source_files=source_rows,unchanged_workspace_build_inputs=invariant_build_inputs,
        limits=['These leaf equalities preserve the reviewed B09 tests and production paths; they do not relabel the fb9 native execution as an eed whole-tree run.',
                'Source contents are complete, while human semantic review concentrates on the exact original cases and their direct handlers/terminalization paths.']))
    cases_pin = save('original-19-case-evidence-v1.json',dict(schema='b09-original-cases/v1',original_exit=old_row['original_exit_condition_zh'],
        literal_original_contract_sources=[identity(ROOT/'original-ledger.json'),identity(ROOT/'original-case-map.json')],
        source_tree=FB9,native_job=manifest['original_job'],host=host,original_command=command,
        exact_original_case_count=19,cases=case_rows,
        enclosing_full_result=dict(selected=19506,passed=19490,failed=16,ignored_catalog=57,observed_early_returns=25,exit_code=100,whole_passed=False),
        program_count=321,helper_count=33,programs_and_helpers_stable=True,source_guards=guards,source_bridge=bridge_pin))
    result = dict(schema='b09-complete-original-verification/v1',result='VERIFIED_ORIGINAL_19_PASS_SCOPED',no_native_or_tests=True,
        original_files=len(originals),original_bytes=sum(x['bytes'] for x in originals),originals=originals,
        original_archive_manifest=identity(manifest_path),transport_parts=parts,decoded_assets=archive_assets,
        full_roster_count=19506,full_roster_equal_across_raw_xml_review_catalog=True,summary_repeated_failure_lines_checked_separately=16,unique_b09_cases=19,b09_pass=19,b09_observed_early_return=0,
        source_bridge=bridge_pin,case_evidence=cases_pin,
        original_full_failure_preserved=True,whole_candidate_qualified=False,
        classification='Original named controls satisfied on recorded GNU/Linux source fb9, with unchanged reviewed source leaves through 5b/e78/eed. Root decides B09 closure under its literal exit; no additional platform gate is invented.')
    pin = save('complete-original-verification-v1.json',result)
    print(json.dumps(dict(result=result['result'],case_evidence=cases_pin,source_bridge=bridge_pin,verification=pin),ensure_ascii=False))

if __name__ == '__main__':
    main()
