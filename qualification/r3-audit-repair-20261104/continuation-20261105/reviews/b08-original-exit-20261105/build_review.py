import collections
import datetime
import difflib
import hashlib
import json
import pathlib
import xml.etree.ElementTree as ET

ROOT = pathlib.Path('/workspace/scratch/07dd58cc9630')
BASE = ROOT / 'ci-audit/published-eed4d6-ci-20261105/b08-source-review-v1'
ROG = ROOT / 'ci-audit/core-wait-span-20261105/project-nonpass-complete-v1/decoded-verified-v1'
OUT = BASE / 'review-v1'
OUT.mkdir(exist_ok=True)

def ident_bytes(b):
    return {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest(), 'git_blob': hashlib.sha1(b'blob ' + str(len(b)).encode() + b'\0' + b).hexdigest()}

def pin(p):
    return {'path': str(p), **ident_bytes(p.read_bytes())}

def read(p):
    return json.loads(p.read_text())

def save(name, value):
    p = OUT / name
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    return pin(p)

def tree_sha(leaves):
    root = {}
    for path, leaf in leaves.items():
        cur = root
        parts = path.split('/')
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = (leaf['mode'], leaf['sha'])
    def rec(node):
        entries = []
        for name, value in node.items():
            is_dir = isinstance(value, dict)
            mode, sha = ('40000', rec(value)) if is_dir else value
            entries.append((name.encode() + (b'/' if is_dir else b''), mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(sha)))
        raw = b''.join(v for _, v in sorted(entries))
        return hashlib.sha1(b'tree ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    return rec(root)

leaf_input = ROOT / 'hepta-audit-fifth/inputs/product-5b-full-leaf-manifest.json'
e78_input = ROOT / 'hepta-audit-fifth/core-musl-initial-source-binding.json'
eed_input = ROOT / 'hepta-audit-fifth/inputs/integrated-14-path-candidate-v2.json'
five = read(leaf_input)
e78 = read(e78_input)
eed = read(eed_input)
maps = {'5b': {x['path']: dict(x) for x in five['leaves']}}
assert tree_sha(maps['5b']) == five['tree']
maps['e78'] = {k: dict(v) for k, v in maps['5b'].items()}
for c in e78['exact_changes']:
    assert maps['e78'][c['path']]['sha'] == c['pre']
    maps['e78'][c['path']]['sha'] = c['post']
assert tree_sha(maps['e78']) == e78['candidate_tree']
maps['eed'] = {k: dict(v) for k, v in maps['5b'].items()}
for c in eed['changes']:
    assert maps['eed'].get(c['path'], {}).get('sha') == c['before_sha']
    maps['eed'][c['path']] = {k: c[k] for k in ('path', 'mode', 'type', 'sha')}
assert tree_sha(maps['eed']) == eed['tree']

sources = []
for p in sorted((BASE / 'source').glob('*.source.txt')):
    logical = p.name.removesuffix('.source.txt').replace('__', '/')
    b = p.read_bytes()
    old = BASE / 'cabc-source' / p.name
    assert old.exists()
    old_b = old.read_bytes()
    assert ident_bytes(b)['git_blob'] == maps['5b'][logical]['sha']
    assert all(maps[k][logical]['sha'] == maps['5b'][logical]['sha'] and maps[k][logical]['mode'] == maps['5b'][logical]['mode'] for k in maps)
    sources.append({'logical_source_path': logical, 'current_full_source': pin(p), 'cabc_full_source': pin(old), 'cabc_equals_5b': old_b == b, '5b_e78_eed_equal': True, 'mode': maps['5b'][logical]['mode'], 'cabc_to_5b_delta': ''.join(difflib.unified_diff(old_b.decode().splitlines(True), b.decode().splitlines(True), fromfile='cabc/' + logical, tofile='5b/' + logical))})
assert len(sources) == 15
assert sum(not x['cabc_equals_5b'] for x in sources) == 1
changed = next(x for x in sources if not x['cabc_equals_5b'])
assert changed['logical_source_path'] == 'codex-rs/core/tests/common/responses.rs'
assert changed['cabc_to_5b_delta'].count('\n+') == 6  # filename plus five lines
bridge = {'schema': 'b08-source-leaf-bridge-v1', 'inputs': [pin(leaf_input), pin(e78_input), pin(eed_input)], 'whole_trees_independently_recomputed': {k: {'tree': tree_sha(v), 'leaves': len(v)} for k, v in maps.items()}, 'cabc_source_commit': 'cabcb40d36e116beaa65750e1f674c52035da785', 'published_eed_commit': 'eed4d6bb61b789b19f60facc79f9e031765fa4c9', 'source_files': sources, 'limit': 'This is a complete 15-file relevant source bridge plus recomputed full 5b/e78/eed trees. It does not relabel e78 execution as eed GNU execution.'}
bridge_pin = save('source-leaf-bridge.json', bridge)

projection_path = ROOT / 'ci-audit/published-eed4d6-ci-20261105/six-exit-scope-review-v1/scope-projection.json'
cases = [x for x in read(projection_path)['cases'] if x['blocker'] == 'B08']
assert len(cases) == 4 and len({x['test'] for x in cases}) == 4
raw_path = ROG / 'original-owning-projects.stdout'
raw = raw_path.read_bytes()
lines = raw.splitlines(keepends=True)
offsets = [0]
for line in lines:
    offsets.append(offsets[-1] + len(line))
xml_path = ROG / 'original-owning-projects.junit.xml'
xml_root = ET.parse(xml_path).getroot()
review = read(ROG / 'original-owning-projects-review.json')
assert review['retries'] == 0 and review['programs_helpers_stable'] is True
before = read(ROG / 'original-owning-projects-before-source-guard.json')
after = read(ROG / 'original-owning-projects-after-source-guard.json')
for field in ['source_tree', 'ordinary_head', 'ordinary_index', 'locks']:
    assert before[field] == after[field]
assert before['source_tree'] == e78['candidate_tree']
assert not before['unexpected_untracked'] and not after['unexpected_untracked']
case_outputs = []
for i, c in enumerate(cases, 1):
    name = c['test']
    scope = c['linux_rog_e78_actual_scope']
    assert scope['result'] == 'PASS' and scope['observed_early_returns'] == []
    start, end = scope['raw_start_line'], scope['raw_end_line']
    block = b''.join(lines[start - 1:end])
    text = block.decode()
    assert text.count('test ' + name + ' ... ok') == 1
    assert 'running 1 test' in text and '1 passed; 0 failed; 0 ignored' in text
    assert 'Skipping test because it cannot execute when network is disabled in a Codex sandbox.' not in text
    rows = [x for x in xml_root.iter('testcase') if x.get('name') == name]
    assert len(rows) == 1
    row = rows[0]
    assert row.find('failure') is None and row.find('error') is None and row.find('skipped') is None
    assert row.get('classname') == c['binary']
    p = OUT / ('case-%02d.original-raw-block.txt' % i)
    p.write_bytes(block)
    case_outputs.append({**c, 'raw_block': pin(p), 'full_original_raw': pin(raw_path), 'raw_byte_start': offsets[start - 1], 'raw_byte_end_exclusive': offsets[end], 'junit_attributes': dict(row.attrib), 'junit_xml_fragment': ET.tostring(row, encoding='unicode'), 'complete_original_junit': pin(xml_path), 'observation': 'Actual one-case libtest PASS and fresh JUnit PASS. No observed network-skip text or other recorded early return.'})

selection = read(ROG / 'project-catalog-selection.json')
programs = [x for x in selection['programs'] if x['binary_id'] in {x['binary'] for x in cases}]
assert len(programs) == 2
execution = {'schema': 'b08-four-actual-case-evidence-v1', 'command': read(ROG / 'original-owning-projects-command.json'), 'overall_original_scope': {'exit_code': 100, 'selected': 3967, 'passed': 3962, 'failed': 5, 'retries': 0, 'must_not_be_relabelled_suite_pass': True}, 'original_inputs': [pin(ROG / x) for x in ['original-owning-projects-command.json', 'original-owning-projects-status.json', 'original-owning-projects-review.json', 'original-owning-projects-before-source-guard.json', 'original-owning-projects-after-source-guard.json', 'project-catalog-selection.json', 'metadata-binding.json']], 'source_and_index_locks_before_after_equal': True, 'programs_helpers_stable_as_original_review': True, 'actual_selected_programs': programs, 'cases': case_outputs, 'windows_eed_receipt': pin(ROOT / 'ci-audit/published-eed4d6-ci-20261105/success-review-v2/review.json'), 'windows_5b_projection': pin(projection_path)}
execution_pin = save('four-case-evidence.json', execution)

exit_path = ROOT / 'hepta-audit-fourth/inputs/seven-pending-manifest.json'
contract = read(exit_path)
exit_row = next(x for x in contract['original_exit_conditions'] if x['id'] == 'B08')
result = {
    'schema': 'b08-original-exit-independent-review-v1',
    'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'recommendation': 'CLOSED_SCOPED_ELIGIBLE_FOR_ROOT_DECISION',
    'not_a_ledger_status_mutation': True,
    'original_exit_source': pin(exit_path),
    'original_exit': exit_row,
    'wire_contract_precision': contract['wire_contract_precision'],
    'evidence': {'source_leaf_bridge': bridge_pin, 'four_actual_cases': execution_pin},
    'exact_four_names': [x['test'] for x in cases],
    'requirements': [
        {'requirement': '实际 prompt 已附加的 retained calls 与真实 output 对应', 'assessment': 'SATISFIED_WITH_ACTUAL_E78_GNU_EXECUTION_AND_UNCHANGED_RELEVANT_SOURCE', 'source': 'session/turn.rs:1793-1823 constructs actual prompt input, calls attach_pending_to_prompt, then passes &prompt to try_run_sampling_request. test_support.rs:72-83 only reads retained_calls_for_output. Namespace integration uses the real mock request, actual flush_rollout/load_history and output call_id, not manufactured metadata.', 'original_assertions': ['tools.rs:405-426 exact namespace/name/input/output wire tuple', 'tools.rs:450-483 exact persisted tuple and retained namespaced call', 'tools.rs:515-563 escaped serialized-byte overflow marker and preserved earlier retained calls', 'tools.rs:597-619 second replay plus exact direct exec retained arguments']},
        {'requirement': '原 exact calls 断言及边界负向语义保留', 'assessment': 'SATISFIED_BY_EXISTING_IN_CASE_ASSERTIONS', 'source': 'executed_tool_calls_tests.rs retains pending>256 overflow marker, observer None before attach, exact retained vector after attach, exact replay, compaction observer None, and 512-item retained history bound/omission accounting. These are actual assertions inside the two original passing tests.', 'mutation_negative_claim': 'No separate mutation-negative run or manifest is claimed or required by the frozen B08 exit text.'},
        {'requirement': '非官方 wire 无私有字段且官方矩阵原语义不变', 'assessment': 'SATISFIED', 'source': 'client_tests.rs:154-331 exercises four resolved endpoint/name combinations with content_item_kinds true/false and Responses Lite true/false (16 combinations). ChatGPT Codex strips; first-party OpenAI keeps even under a custom friendly name; non-standard endpoint strips even if named OpenAI. Exact original prompt input is unchanged after each provider serialization. provider_accepts_internal_chat_message_metadata checks the resolved exact public URL, not display name.'},
        {'requirement': '不改变生产持久化', 'assessment': 'SATISFIED_FOR_THIS_REPAIR_AND_SOURCE_BRIDGE', 'source': 'All relevant production files are byte-identical between frozen cabc and 5b/e78/eed, including recorder, actual turn caller, client preparation, protocol models, session persistence, rollout recorder/policy and endpoint predicate. Recorder remains in-memory; test getter is read-only. durable_input reads actual persisted history after flush and asserts private metadata absent from captured wire. Only one of 15 relevant files differs since cabc: five unrelated test-helper module/export lines in common/responses.rs; all existing helper bodies remain unchanged.'}
    ],
    'platform_and_source_scope': {'GNU_e78': '4 original cases actually passed at e78 under original project command, 0 retries. Overall project command still exit100 due to five other recorded failures.', 'Windows_5b': '3 applicable unit cases actually passed in original full Core shard logs.', 'Windows_eed': 'Same 3 applicable unit cases actually passed in the current full Core lifecycle target (2340 passed, 3 original ignored overall).', 'namespace_on_Windows': 'Original tools.rs module is cfg-not-Windows; no Windows run invented.', 'eed_GNU': 'NOT_EXECUTED. Source equality is not relabelled execution.'},
    'exit_condition_precision': ['No original_failure_snapshot48 row names a B08-specific five-platform requirement.', 'Q02 four-Unix collection plan is an evidence collection plan, not an added original exit condition.', 'Current complete-workspace gate remains under B15; this review does not close B15 or the original platform/full-matrix gates.', 'All four GNU original blocks have no observed early return; the integration early-return branch would print a fixed network-disabled line, absent from its complete captured block.'],
    'actions_in_this_review': {'native_commands': 0, 'tests': 0, 'retries': 0, 'source_changes': 0, 'ref_changes': 0},
    'limits': ['Case qualification is attached to the recorded source/platform/command. Whole project exit100, direct parallel failures, resource refusals, 25 other early returns and old driver UNKNOWN remain unchanged.', 'This recommends scoped closure to root; it does not modify the 23-row ledger or declare the whole candidate green.']
}
review_pin = save('independent-review.json', result)
print(json.dumps({'review': review_pin, 'source_bridge': bridge_pin, 'four_case_evidence': execution_pin, 'source_files': len(sources)}, ensure_ascii=False))
