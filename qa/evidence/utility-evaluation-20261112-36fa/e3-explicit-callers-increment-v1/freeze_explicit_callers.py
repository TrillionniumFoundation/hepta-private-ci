"""Freeze only explicit receivers and one original API argument comment.

Pure byte work: this script does not import a project module, execute a
collector, compile, format, test, publish Git objects, or contact a host.
"""
from pathlib import Path
import difflib
import hashlib
import json

ROOT = Path('/tmp/hepta-36fa-root-product-e3-proposal-v1')
OUT = ROOT / 'explicit-callers-increment-v1'
PREFIX = 'codex-rs/hepta-agentd/src/'


def identity(data):
    return {
        'bytes': len(data),
        'sha256': hashlib.sha256(data).hexdigest(),
        'git_blob': hashlib.sha1(
            b'blob ' + str(len(data)).encode() + b'\0' + data
        ).hexdigest(),
    }


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(data)
    assert path.read_bytes() == data


def save_json(name, value):
    data = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()
    save(OUT / name, data)
    return identity(data)


changes = [
    ('root-service-layer-v1', 'authority_host_resident_cli.rs',
     'let work = service.run(cancellation.clone());',
     'let work = codex_hepta_agentd::RootResidentCandidateServiceV1::run(service, cancellation.clone());',
     'The exact same owned service and cancellation argument enter the original by-value run method.'),
    ('late-enrollment-layer-v1', 'authority_host_resident_enrollment_cli.rs',
     'let work = service.run(cancellation.clone());',
     'let work = codex_hepta_agentd::RootResidentCandidateEnrollmentServiceV3::run(service, cancellation.clone());',
     'The exact same owned enrollment service and cancellation argument enter its by-value run method.'),
    ('late-enrollment-layer-v1', 'authority_host_resident_enrollment.rs',
     'let work = service.run(bounded.clone());',
     'let work = RootResidentCandidateServiceV1::run(service, bounded.clone());',
     'The destructured original service is explicitly named; the child cancellation token is unchanged.'),
    ('late-enrollment-layer-v1', 'production_resident_enrollment.rs',
     'let join = enrollment.enroll_original_root(root);',
     'let join = crate::AgentdRootResidentEnrollmentV3::enroll_original_root(&enrollment, root);',
     'The original method has an &self receiver; this spelling retains the same borrow and owned root argument.'),
    ('late-enrollment-layer-v1', 'authority_host_resident_enrollment_connect.rs',
     'profile, authorization, trust.verifier, None, timeout, wire::remaining(session_end)?,',
     'profile, authorization, trust.verifier, /*expected*/ None, timeout, wire::remaining(session_end)?,',
     'The original expected Option argument is unchanged; only its original parameter name is documented.'),
]

entries = []
splices = []
patch = []
for layer, name, old, new, reason in changes:
    path = PREFIX + name
    base = ROOT / layer
    manifest = json.loads((base / 'MANIFEST.json').read_bytes())
    frozen = next(row for row in manifest['sources'] if row['path'] == path)
    before = (base / 'after' / path).read_bytes()
    assert identity(before) == frozen['after'], path
    old_bytes, new_bytes = old.encode(), new.encode()
    assert before.count(old_bytes) == 1, path
    after = before.replace(old_bytes, new_bytes)
    assert after.count(new_bytes) == 1, path
    assert after.replace(new_bytes, old_bytes) == before, path
    save(OUT / 'before' / path, before)
    save(OUT / 'after' / path, after)
    entries.append({
        'path': path, 'predecessor_layer': layer,
        'before': identity(before), 'after': identity(after),
        'before_utf8': before.decode(), 'after_utf8': after.decode(),
    })
    splices.append({
        'path': path, 'before_text': old, 'after_text': new,
        'occurrences': 1, 'inverse_full_bytes_equal': True,
        'reason': reason,
    })
    patch.extend(difflib.unified_diff(
        before.decode().splitlines(keepends=True),
        after.decode().splitlines(keepends=True),
        fromfile='a/' + path, tofile='b/' + path,
    ))

references = []
for path in [
    PREFIX + 'authority_host_learning_candidate_service.rs',
    PREFIX + 'resident_learning_delivery.rs',
    PREFIX + 'authority_host_learning_resident_transport.rs',
]:
    references.append({'path': path, **identity((ROOT / 'references' / path).read_bytes())})

packet = {
    'format': 'hepta-source-packet-v1',
    'state': 'LOCAL_FROZEN_PROPOSAL_NOT_COMPILED_OR_EXECUTED',
    'base_commit': 'b6084394a4a38ab495c16eaba09e879f04a96f8e',
    'prerequisites': [
        {'packet': '0dc5e98ff38ed0c4c4defe277d21a5cb90bae37b', 'layer': 'root-service-layer-v1'},
        {'packet': '388bfb3f3ab70e5f39d847c26d2d48daa2c7ead1', 'layer': 'late-enrollment-layer-v1'},
    ],
    'entries': entries,
}
payloads = []
payloads.append({'path': 'SOURCE_PACKET.json', **save_json('SOURCE_PACKET.json', packet)})
patch_bytes = ''.join(patch).encode()
save(OUT / 'SOURCE_DELTA.patch', patch_bytes)
payloads.append({'path': 'SOURCE_DELTA.patch', **identity(patch_bytes)})
payloads.append({'path': 'EXACT_SOURCE_SPLICES.json', **save_json('EXACT_SOURCE_SPLICES.json', splices)})
payloads.append({'path': 'SOURCE_REFERENCES.json', **save_json('SOURCE_REFERENCES.json', references)})
review = {
    'scope': 'Five exact spelling-only splices in five previously proposed E3 source paths.',
    'source_paths': 5, 'exact_splices': 5,
    'semantic_change_claim': 'No change to receiver objects, arguments, transport, permissions, counters, timeouts, or cancellation.',
    'static_evidence': [
        'All five complete predecessor bodies match their immutable manifest identities.',
        'Each replacement occurs once and its inverse reproduces the complete predecessor bytes.',
        'The original CandidateService run receiver is self by value.',
        'The enrollment service run receiver is self by value.',
        'The original AgentdRootResidentEnrollmentV3 enroll_original_root receiver is &self.',
        'The original recovery parameter name is expected; its None value is unchanged.',
    ],
    'reason': 'Make match/destructure/tuple-bound authority receivers explicit for review and the unchanged conservative typed matcher. The positional comment names an unchanged original API parameter.',
    'not_performed': ['original collector', 'QA', 'Rust compile', 'Rust tests', 'formatter', 'H', 'Git source create', 'ref mutation'],
    'limits': [
        'Explicit spelling is not a claim that the unchanged full collector or any runtime gate has passed.',
        'This independent layer does not modify either prior frozen E3 layer.',
        'Root remains the only integrator of overlapping E1/E2/E3 files.',
    ],
}
payloads.append({'path': 'REVIEW.json', **save_json('REVIEW.json', review)})
script = Path(__file__).read_bytes()
save(OUT / 'freeze_explicit_callers.py', script)
payloads.append({'path': 'freeze_explicit_callers.py', **identity(script)})
manifest = {
    'format': 'hepta-local-frozen-source-increment-v1',
    'state': 'computed identities, local complete bytes; no Git publication asserted',
    'sources': [{k: row[k] for k in ['path', 'predecessor_layer', 'before', 'after']} for row in entries],
    'payloads': payloads,
}
manifest_identity = save_json('MANIFEST.json', manifest)
print(json.dumps({'packet': payloads[0], 'manifest': manifest_identity, 'source_paths': 5, 'exact_splices': 5}, sort_keys=True))
