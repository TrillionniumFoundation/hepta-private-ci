#!/usr/bin/env python3
"""Offline pin/diff review only. Does not compile or execute candidate Rust."""
import difflib
import hashlib
import json
import re
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-root-resident-provider-proposal-v1')
OUT = Path(__file__).resolve().parent
INV = Path('/tmp/hepta-36fa-source-repair-canonical-packet-v1/CANONICAL_CLEAN_INVENTORY.expected.json')


def identity(b):
    return {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(b)).encode() + b'\0' + b).hexdigest()}


manifest_raw = (ROOT / 'MANIFEST.json').read_bytes()
manifest = json.loads(manifest_raw)
assert identity(manifest_raw)['git_blob'] == '7cd37e6a6cc391bda9275b938acd7e08263d23a1'
packet_raw = (ROOT / 'SOURCE_PACKET.json').read_bytes()
assert identity(packet_raw)['git_blob'] == '0d42484181e34c178a04c934737cdb99adbaca0d'
inventory_raw = INV.read_bytes()
assert identity(inventory_raw)['sha256'] == '13d3efc000a6f1ae9e15d18e5d3cab27722062c27f3524f4ddd7e32f418fceb9'
inventory = json.loads(inventory_raw)
entries = {r['path']: r for r in inventory['files']}
source_pins = []
for p in sorted((ROOT / 'before').rglob('*')):
    if not p.is_file():
        continue
    path = p.relative_to(ROOT / 'before').as_posix()
    pin = identity(p.read_bytes())
    assert pin['git_blob'] == entries[path]['working_blob']
    source_pins.append({'path': path, 'version': 'cc57 reference', 'local_path': str(p), **pin})
assert len(source_pins) == 21
additions = []
for c in manifest['source_changes']:
    path = c['path']
    after_path = ROOT / 'after' / path
    after = after_path.read_bytes()
    assert identity(after) == c['after']
    source_pins.append({'path': path, 'version': 'candidate after', 'local_path': str(after_path), **identity(after)})
    if c['before'] is None:
        assert path not in entries
        additions.append({'path': path, 'change': 'new file', 'lines': len(after.splitlines())})
        continue
    before = (ROOT / 'before' / path).read_bytes()
    assert identity(before) == c['before']
    left, right = before.splitlines(keepends=True), after.splitlines(keepends=True)
    hunks = []
    for tag, i, j, a, b in difflib.SequenceMatcher(None, left, right, autojunk=False).get_opcodes():
        assert tag in ('equal', 'insert'), (path, tag)
        if tag == 'insert':
            hunks.append({'before_position': i, 'after_lines': [a + 1, b],
                          'text': b''.join(right[a:b]).decode()})
    assert b''.join(line for tag, i, j, a, b in difflib.SequenceMatcher(None, left, right, autojunk=False).get_opcodes()
                    if tag == 'equal' for line in right[a:b]) == before
    additions.append({'path': path, 'change': 'insert-only, every original byte retained in order', 'hunks': hunks})
assert len(manifest['source_changes']) == 8
assert sum(c['before'] is None for c in manifest['source_changes']) == 4
for name in ('authority_host_channel.rs', 'authority_host_descriptor.rs'):
    p = OUT / 'additional-originals' / name
    path = 'codex-rs/hepta-contracts/src/' + name
    pin = identity(p.read_bytes())
    assert pin['git_blob'] == entries[path]['working_blob']
    source_pins.append({'path': path, 'version': 'cc57 exact blob independently fetched', 'local_path': str(p), **pin})

test_path = ROOT / 'after/codex-rs/hepta-agentd/src/root_candidate_stage_handoff_tests.rs'
test_names = re.findall(r'#\[test\]\s*fn (\w+)\(', test_path.read_text())
assert len(test_names) == 4
registration = json.loads((ROOT / 'STRUCTURAL_REGISTRATION_PLAN.json').read_text())
assert len(registration['existing_edges']) == 5
assert all(row['proposed_real_product_callers'] == ['codex-rs/hepta-agentd/src/authority_host_learning_candidate_service.rs']
           for row in registration['existing_edges'])
assert all(row['change_implemented_in_callers'] is False for row in registration['existing_edges'])

report = {
  'format': 'hepta-original-root-provider-independent-static-peer-v1',
  'status': 'NO_CONCRETE_SOURCE_DEFECT_IDENTIFIED_WITHIN_REVIEWED_SCOPE; HOLD_FOR_COMPILE_INTEGRATION_AND_GATES',
  'candidate_manifest': identity(manifest_raw),
  'candidate_packet': identity(packet_raw),
  'base_source': manifest['source'],
  'base_full_inventory': {'path': str(INV), **identity(inventory_raw)},
  'candidate_tree_is_projection_only': manifest['expected_preformat_candidate_tree'],
  'expected_candidate_leaf_count': manifest['expected_candidate_leaf_count'],
  'review_method': 'Complete manual read of the eight after images, relevant original call-chain implementations and four test bodies, plus independent exact byte/pin and insert-only checks. No Rust parser, formatter, compiler, H call, main, gate, or behavior test was run.',
  'source_pins': source_pins,
  'existing_source_preservation': additions,
  'semantic_review': [
    {
      'area': 'Dedicated capability transfer and descriptor ownership',
      'anchors': ['root_candidate_stage_handoff.rs::send_root_candidate_stage_handoff',
                  'root_candidate_stage_handoff.rs::receive_root_candidate_stage_handoff',
                  'root_candidate_stage_handoff_wire.rs::{send,receive}',
                  'notes_bootstrap.rs::received_descriptors'],
      'finding': 'The private new frame requires exactly 21 rights, one sender Root pidfd plus ten ordered stream/pidfd pairs, a bounded nonempty body, and no ancillary truncation. Received rights are adopted as OwnedFd before every subsequent rejection. Ten stream objects are AF_UNIX/SOCK_STREAM and de-aliased by device/inode. Send owns the endpoints and socket, while only original Root/recipient pin arguments are borrowed. The old two-right marker, parser and eight-FD send bound remain unchanged.',
      'limitation': 'API consumption does not prevent a trusted or hostile provider from duplicating descriptors before supplying them. Kernel FD transfer itself is not a cryptographic grant or proof of purpose; original protocol and owner once-state remain necessary.'
    },
    {
      'area': 'Actual Root, recipient and role peer identity',
      'anchors': ['root_production_handoff.rs::{root_pair,require_root_pin}',
                  'root_candidate_stage_handoff.rs::{require_root,require_process,validate_packet}',
                  'learning_owner_command_channel.rs::original_owner_command_channel_v1',
                  'authority_host_peer.rs::HostAuthorityPeerChannel::from_stream',
                  'authority_host_channel.rs::OwnerChannel::{new,check}'],
      'finding': 'Public send/receive and opaque consumption require actual real/effective UID0. The unnamed datagram pair is bound to its Root creator by SO_PEERCRED and the transferred live pidfd. Sender checks its creator PID and recipient pin; packet admission independently requires the actual receiving PID plus matching boot/start identity. Original role constructors still check actual peer socket UID/PID, same-UID/same-PID refusal, boot/start and pidfd type/PID/liveness. Packet lane metadata only supplies comparisons; it cannot retarget an established socket.',
      'limitation': 'The public receiver does not complete all ten role authentications by itself. They occur in the consuming original StageOwners constructors, and remote servers must already be configured for the actual recipient. The provider must supply genuinely Root-targeted endpoints; no current stock-main provider was established by this review.'
    },
    {
      'area': 'Authority and trust provenance',
      'anchors': ['authority_host_learning_candidate_service.rs::RootResidentLearningRegistrationV3::into_candidate_service',
                  'authority_host_learning_resident_authority.rs::ResidentRootAuthorityV3::{readonly,perform}',
                  'authority_host_learning_resident_runtime.rs::compose'],
      'finding': 'The packet contains no fresh/recovered switch, material configuration, model, verifier, grant, signature, receipt or outcome. Original material/protocol/baseline/verifier and the nonconstructible original registration are supplied independently. Fresh versus recovered comes solely from the registration private authorization enum. Two original authority Check calls surround actual role admission; compose retains complete initial/scope/trust/baseline consistency checks. Wire metadata cannot create Root custody or promote recovered channels.',
      'limitation': 'Check uses the original Observe boundary and is not itself a fresh work admission. Work still requires the existing original runtime/checkpoint CAS and later dispatch guards. The candidate does not activate stock main, supply missing real owner credentials, or establish a real task chain.'
    },
    {
      'area': 'Absolute deadline and finite execution scope',
      'anchors': ['root_candidate_stage_handoff.rs::{send_root_candidate_stage_handoff,validate_packet,RootCandidateStageHandoffV1::into_original_streams,require_timing}',
                  'cell_q24_candidate_stage_owners.rs::restrict_original_handoff_deadline',
                  'authority_host_learning_candidate_service.rs::RootResidentCandidateServiceV1::run'],
      'finding': 'Sender fixes monotonic ends before role serialization. Receive and consumption reject zero/elapsed or excessive remaining lifetime. Sampling Instant before monotonic conversion gives a conservative global end, and min-only consuming restriction narrows both Candidate and common deadlines before runtime composition. Service deadline is also bounded by the same end and the consumer lifetime. Original 30s/500ms exchange and 300s session limits remain unchanged.',
      'limitation': 'The global public execution/await cap is preserved. Original inner OwnerChannel constructors still establish their own Instant from remaining Duration at construction; this is not proof that every inner Instant numerically equals the packet end. A remote effect already dispatched may outlive cancellation, so the result remains uncertain pending original explicit readback, never rollback or fabricated NoUpdate.'
    },
    {
      'area': 'Service supervision, A disconnect and cancellation',
      'anchors': ['authority_host_learning_candidate_service.rs::{CloseOriginalStream::drop,RootResidentCandidateServiceV1::run}',
                  'authority_host_learning_resident_runtime.rs::RootResidentLearningRuntimeV3::run',
                  'authority_host_learning_resident_transport.rs::RootResidentLearningHandleV3::serve_original_stream'],
      'finding': 'The service owns the original runtime and exactly one blocking server. A EOF merely ends/drops the server handle: the original coordinator deliberately waits for its independent Root cancellation and can retain active admitted work. Explicit Root cancellation or global expiry cancels the child token, shuts down the owned stream and awaits the combined work. Dropping the async service shuts down its clone and cancels its child token; no original peer process is killed or recreated.',
      'limitation': 'Dropping a Rust future does not synchronously join the already running blocking task; the code/documentation promise closure/cancellation on drop, not a completed join. Explicit cancellation join behavior and absence of lifecycle stalls have not been executed with actual original owners. Service Ok/Err is a lifetime result, not a learning disposition.'
    },
    {
      'area': 'Source-level type and module connections',
      'anchors': ['lib.rs Linux exports', 'root_production_handoff.rs::candidate_stages module',
                  'authority_host_learning_resident.rs::candidate_service module',
                  'authority_host_learning_candidate_service.rs original UFCS calls'],
      'finding': 'The four old files are insert-only with every original byte retained. Linux mounts/exports, child access to parent-private original registration state, Root profile getters, AgentdError IO/GenerationFenced variants and explicit original UFCS call targets are present in the pinned baseline. The new consuming deadline method only reduces private fields. No known missing name or type mismatch was identified by this manual review.',
      'limitation': 'This is not Rust compilation, borrow checking, linter approval or a complete typed-caller result. Exact formatted literals and all new caller/fence data remain unfinished.'
    }
  ],
  'prepared_test_review': {
    'executed_by_this_peer': 0,
    'test_names': test_names,
    'genuine_mechanisms': ['Actual anonymous sockets and SCM_RIGHTS transfer retain ordered communication after originals drop.',
                          'CLOEXEC is inspected on every returned descriptor.',
                          'Old/new right-count and body separation uses the original old parser, with EOF checks after rejection.',
                          'Duplicated underlying socket is rejected and all received descriptors are dropped.',
                          'Metadata mutants exercise the actual parser/validator and real current PID/boot/start comparison.'],
    'coverage_boundary': 'All 21 raw FD slots intentionally use UnixStreams in the unprivileged framing test. No public Root receiver, real pidfd identity, original registration, ten-owner service, authority revocation, elapsed handoff, cancellation, or independent B is exercised by these four methods.',
    'integration_blockers_before_landing': [
      'At least one original-owner public send/receive/registration/service normal complete NoUpdate route, with exact original T/E/Version/S/C/current material and full signatures.',
      'Recovered original registration selects only recovered channels and rejects fresh Admit; changed grant/lease/trust/material is refused.',
      'Actual A EOF after admission does not cancel Root work; Root cancellation and deadline close the server and join owned work without replay.',
      'Real elapsed handoff/admission rejects past end and never installs a later global end; wrong role socket/pidfd/recipient is rejected.',
      'Original scoped formatting/compilation, postformat caller/protection/QA/allowlist integration, and all unchanged exact-source gates.'
    ]
  },
  'registration_plan_review': {'existing_real_edges': registration['existing_edges'],
                               'current_callers_changed': False,
                               'current_original_boundary_count': 569,
                               'current_original_protected_rows': 422,
                               'complete_collector_still_required': True},
  'decision': 'Suitable as a frozen, reviewable HOLD candidate. No approval to integrate, run or deploy is implied. No concrete source defect was identified in this bounded review; the listed integration and qualification gaps remain real blockers to landing.',
  'authority_granted': False,
  'real_task_chains': 0,
  'runtime_tests_executed': 0,
  'native_or_source_mutations': 0
}
target = OUT / 'REVIEW.json'
with target.open('x', encoding='utf-8') as f:
    json.dump(report, f, indent=2, ensure_ascii=False, sort_keys=True)
    f.write('\n')
print(json.dumps({'path': str(target), **identity(target.read_bytes()),
                  'source_versions': len(source_pins), 'candidate_files': 8, 'tests_prepared_not_run': len(test_names)}))
