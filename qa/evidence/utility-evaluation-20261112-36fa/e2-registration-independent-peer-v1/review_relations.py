"""Static, fixed-byte supplemental review. No project code is executed."""
from pathlib import Path
import ast
import copy
import hashlib
import json
import re
import tomllib

D = Path('/tmp/hepta-36fa-root-product-e2-proposal-v1/registration-components-frozen-v2')
OUT = Path('/tmp/hepta-36fa-e2-registration-independent-review-v1')
ROOT = D.parent
VIEW = Path('/tmp/hepta-36fa-root-product-composition-v6/after')
PREFIX = 'codex-rs/hepta-agentd/src/'
BASE = Path('/tmp/hepta-36fa-e1-source-candidate-v1/after/CALLERS.toml')
selected = {'pin', 'check', 'strict_pairs', 'read_json', 'json_bytes', 'save', 'rust_code', 'balanced', 'declarations', 'source_layers'}
# Only this reviewer's explicitly listed, already preserved pure text helpers.
script = ast.parse((OUT / 'review_bytes_v2.py').read_text())
exec(compile(ast.Module(body=[x for x in script.body if isinstance(x, ast.FunctionDef) and x.name in selected],
                        type_ignores=[]), 'reviewer_pure_text_helpers', 'exec'), globals())

boundary = read_json(D / 'BOUNDARY_ROWS.json')
protected = read_json(D / 'PROTECTED_ROWS.json')
original, own, view, layers = source_layers(read_json(D / 'SOURCE_PINS.json'))
base = tomllib.loads(BASE.read_text())
exact_call_patterns = {
    'e2_original_task_host_lanes_serve': r'\boriginal_host\.serve\s*\(',
    'e2_remote_serve': r'\bremote::serve\s*\(',
    'e2_circuit_task_runtime_bootstrap_v1_take_original_root_lane': r'\bself\.bootstrap\.take_original_root_lane\s*\(',
    'e2_daemon_cell_port_new': r'\bDaemonCellPort::new\s*\(',
    'e2_daemon_loans_new': r'\bDaemonLoans::new\s*\(',
    'e2_reverse_client_new': r'\bReverseClient::new\s*\(',
    'e2_budget_new': r'\bBudget::new\s*\(',
    'e2_lane_new': r'\bLane::new\s*\(',
    'e2_original_root_lane_factory_take': r'self\.original_root\.take\(\)\.ok_or\(Error::Unavailable\)\?\.take\s*\(',
}


def locations(text, pattern):
    code = rust_code(text)
    result = []
    for match in re.finditer(pattern, code):
        line_start = code.rfind('\n', 0, match.start()) + 1
        if re.search(r'\bfn\s+$', code[line_start:match.start()]):
            continue
        line_end = text.find('\n', match.end())
        if line_end < 0:
            line_end = len(text)
        result.append(dict(line=text.count('\n', 0, match.start()) + 1,
                           text=text[line_start:line_end]))
    assert result, pattern
    return result


call_pairs = []
for row in boundary['new_rows']:
    method = row['symbol'].rsplit('::', 1)[-1]
    pattern = exact_call_patterns.get(row['id'], row.get('call_pattern', r'\b' + re.escape(method) + r'\s*\('))
    for path in row['product_callers']:
        call_pairs.append(dict(id=row['id'], symbol=row['symbol'], receiver=row.get('receiver_type'),
                               definition_path=row['definition_path'], caller_path=path,
                               caller_identity=pin(view[path].encode()), call_sites=locations(view[path], pattern)))
assert len(call_pairs) == 94

old_pairs = []
for change in boundary['old_row_changes']:
    row = base['boundary'][change['index']]
    symbol = row['symbol']
    method = symbol.rsplit('::', 1)[-1]
    # Existing custody methods are explicitly UFCS at their new sites. For
    # free functions, the exact old symbol is retained by the caller.
    pattern = r'\b' + re.escape(symbol) + r'\s*\('
    for path in change['added_callers']:
        old_pairs.append(dict(index=change['index'], id=row['id'], symbol=symbol,
                              caller_path=path, source=pin(view[path].encode()),
                              call_sites=locations(view[path], pattern)))
assert len(old_pairs) == 15

# Selected typed ownership anchors eliminate the generic-method false matches.
# These are observations of exact declarations/calls, not inferred Rust types.
anchors = {
    PREFIX + 'circuit_task_remote_client.rs': [
        'pub(crate) struct DaemonClient {', 'pub(super) task: Mutex<Lane>,',
        'pub(super) loans: Arc<DaemonLoans>,', 'reverse: Mutex<Option<Lane>>,',
        'loans: DaemonLoans::new(pending)', 'self.loans.attach(state, cancellation)?;',
        'while reverse.serve_one(|frame| loans.respond(frame))?',
        'pub(crate) struct DaemonCellPort(pub(super) Arc<DaemonClient>);'],
    PREFIX + 'circuit_task_remote_admission.rs': [
        'pub(super) struct ReverseClient {', 'lane: Arc<Mutex<Lane>>,',
        'pub(super) fn new(lane: Lane, binding: Digest32) -> Self'],
    PREFIX + 'circuit_task_remote_wire.rs': [
        'pub(super) struct Lane {', 'budget: Arc<Budget>,',
        'fn begin(&self) -> Result<Instant, Error>', 'self.budget.begin()',
        'let result = channel.exchange(', 'Option<HostAuthorityPeerChannel>'],
    PREFIX + 'root_original_task_handoff.rs': [
        'async fn connect(path: &Path, end: Instant) -> Result<UnixStream, AgentdError>',
        'tokio::net::UnixStream::connect(path)'],
    PREFIX + 'authority_host_session_task_host.rs': [
        'pub(crate) struct OriginalTaskHostLanes',
        'pub(crate) fn bind_original_task_host_lanes(&self)',
        'pub(crate) fn serve(self)'],
    PREFIX + 'circuit_task_runtime.rs': [
        'original_root: Option<Box<dyn super::root_lane::OriginalRootLaneFactory>>',
        'self.original_root.take().ok_or(Error::Unavailable)?.take()'],
    PREFIX + 'circuit_task_remote_service.rs': [
        'pump: Box<dyn OriginalRootCellPump>',
        'source: Arc<DurableCircuitTaskSourceV1<SW>>',
        'original.pump.execute(admission, input)',
        'let reverse = ReverseClient::new(Lane::new('],
    PREFIX + 'circuit_task_source_readback.rs': [
        'RootMaterial(std::sync::Arc<material::Client>)',
        'OriginalReadback::RootMaterial(original) =>',
        'original.read(identity, &record.snapshot.run_id)',
        'original.read(identity, run_id)'],
}
anchor_audit = []
for path, needles in anchors.items():
    body = view[path]
    for needle in needles:
        assert needle in body, (path, needle)
        anchor_audit.append(dict(path=path, source=pin(body.encode()), needle=needle,
                                 line=body.count('\n', 0, body.index(needle)) + 1))

# Proposed test records retain exact original source bodies and module mounts.
tests = read_json(D / 'TEST_REGISTRATION_DELTA.json')
root_path = tests['root_test_source']
root_body = view[root_path]
check(root_body.encode(), tests['root_mounts']['file'])
support_path = PREFIX + 'authority_host_generation_support_tests.rs'
assert tests['root_mounts']['support'] == view[support_path]
assert '#[path = "authority_host_generation_root_task_tests.rs"]\nmod root_task_tests;' in view[support_path]
assert re.findall(r'^#\[ignore[^\n]+', root_body, re.M) == tests['root_ignore_attributes']
assert tests['root_ignore_attributes'] == ['#[ignore = "requires original Root host bind and actual signed owner fixtures"]'] * 2
for fqn in tests['root_parent_candidates']:
    assert fqn.startswith('runtime::tests::circuit_task_ingress::q24_tests::support::root_initial_custody::host_generation::root_task_tests::')
    assert len(re.findall(r'\basync fn ' + re.escape(fqn.rsplit('::', 1)[-1]) + r'\(', root_body)) == 1
ordinary = []
for layer in ['bootstrap-receipt-tests-layer-v1', 'material-source-mechanism-tests-layer-v1']:
    impact = read_json(ROOT / layer / 'REGISTRATION_IMPACT.json')
    ordinary.extend(impact.get('new_test_fqns', impact.get('new_fqns')))
assert ordinary == tests['ordinary_linux_tests'] and len(ordinary) == 7
for fqn in ordinary:
    method = fqn.rsplit('::', 1)[-1]
    sources = [p for p, body in view.items() if p.endswith('_tests.rs') and re.search(r'\bfn ' + re.escape(method) + r'\(', body)]
    assert len(sources) == 1, (fqn, sources)
feature = tests['separate_clock_regression']
assert feature['ignored'] is False and feature['crate'] == 'codex-hepta-neuron'
assert 'fn ' + feature['test'].rsplit('::', 1)[-1] + '(' in view[feature['path']]
assert tests['runner_changes'] == [] and tests['budget_or_filter_changes'] == [] and tests['executed'] is False

# Narrow cross-check of Root's separately authored E1+E3+E2 seed. This does not
# bless future loader integration or refresh any required source bytes.
union_dir = Path('/tmp/hepta-36fa-root-registration-union-seed-v1')
union_review = read_json(union_dir / 'UNION_REVIEW.json')
union_raw = (union_dir / 'CALLERS_E1_E3_E2_SEED.toml').read_bytes()
check(union_raw, union_review['complete_union'])
e3_raw = Path('/tmp/hepta-36fa-root-product-e3-proposal-v1/registration-proposal-v1/after/CALLERS.toml').read_bytes()
check(e3_raw, union_review['E3_projection'])
union, e3 = tomllib.loads(union_raw.decode()), tomllib.loads(e3_raw.decode())
assert len(union['boundary']) == 757 and len(union['protected_file']) == 531
assert union['boundary'][650:666] == e3['boundary'][650:666]
assert union['boundary'][666:757] == boundary['new_rows']
assert union['protected_file'][451:470] == e3['protected_file'][451:470]
assert union['protected_file'][470:531] == protected['append_protected_rows']
overlap = []
for change in boundary['old_row_changes']:
    i = change['index']
    if e3['boundary'][i] != base['boundary'][i]:
        overlap.append(i)
    expected = copy.deepcopy(e3['boundary'][i])
    assert set(expected['product_callers']).isdisjoint(change['added_callers'])
    expected['product_callers'] += change['added_callers']
    assert union['boundary'][i] == expected
assert overlap == [178]
assert union['authority'] == base['authority']

output = dict(format='hepta-independent-e2-registration-relation-and-union-proof-v1',
              actual_typed_collector_executed=False, project_code_executed=False,
              new_listed_call_pairs=call_pairs, old_exact_appended_call_pairs=old_pairs,
              explicit_ownership_anchors=anchor_audit,
              rejected_false_receiver_candidates=boundary['rejected_other_receiver_candidates'],
              tests=dict(delta_identity=pin((D / 'TEST_REGISTRATION_DELTA.json').read_bytes()),
                         root_parents=tests['root_parent_candidates'], root_ignore_attributes=tests['root_ignore_attributes'],
                         ordinary_linux_tests=ordinary, separate_clock_regression=feature,
                         root_test_source=dict(path=root_path, **pin(root_body.encode())),
                         no_runner_budget_or_filter_changes=True, actual_execution=False,
                         known_material_test_missing_brace='Original e120 body ends without its third function closing brace; separate 0cefd metadata/source successor appends only } plus LF. This frozen v2 source index predates that correction.'),
              root_union_seed=dict(review=pin((union_dir / 'UNION_REVIEW.json').read_bytes()), source=pin(union_raw),
                                   E3_boundary_slice=[650, 666], E2_boundary_slice=[666, 757],
                                   E3_guard_slice=[451, 470], E2_guard_slice=[470, 531],
                                   old_caller_overlap=overlap, exact_appends_preserve_E3=True,
                                   final_registration=False))
save(OUT / 'RELATION_AND_UNION_PROOF.json', output)
print(json.dumps(dict(status='STATIC_RELATION_AND_UNION_REVIEW_COMPLETE',
                      file=pin((OUT / 'RELATION_AND_UNION_PROOF.json').read_bytes())), indent=2))
