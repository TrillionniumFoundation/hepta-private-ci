#!/usr/bin/env python3
"""Author a source-only proposal from an immutable reviewed platform.wire head.

This is not a qualification runner. It never changes a candidate ref or issues
acceptance receipts. The separate publisher exports only the resulting source
commit to a proposal ref; promotion requires an explicit GitHub ref operation.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys

SOURCE = 'df550741c58081c3271ce2b2dce92e95d1bfb4d4'
ROOT = Path(sys.argv[1]).resolve()
os.chdir(ROOT)

def run(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()

def change(path: str, old: str, new: str, count: int = 1) -> None:
    p = Path(path)
    text = p.read_text()
    if text.count(old) != count:
        raise RuntimeError(f'{path}: expected {count} reviewed anchors, got {text.count(old)}: {old[:100]!r}')
    p.write_text(text.replace(old, new))

def add(path: str, text: str) -> None:
    p = Path(path)
    if p.exists():
        raise RuntimeError(f'new source path already exists: {path}')
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)

assert run('git', 'rev-parse', 'HEAD') == SOURCE
assert not run('git', 'status', '--porcelain', '--untracked-files=all')
change('codex-rs/Cargo.lock', '''name = "codex-hepta-wire"
version = "0.0.0"
dependencies = [
 "codex-hepta-types",
]''', '''name = "codex-hepta-wire"
version = "0.0.0"
dependencies = [
 "codex-hepta-types",
 "serde_json",
]''')

add('codex-rs/hepta-wire/src/feed.rs', '''//! Bounded work with explicit ownership of the unconsumed transport suffix.

#[must_use = "process the batch and resubmit input after bytes_consumed"]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DecodeFeed<B> {
    batch: B,
    bytes_consumed: usize,
}

impl<B> DecodeFeed<B> {
    pub(crate) fn new(batch: B, bytes_consumed: usize) -> Self {
        Self { batch, bytes_consumed }
    }

    pub fn batch(&self) -> &B { &self.batch }

    pub const fn bytes_consumed(&self) -> usize { self.bytes_consumed }

    pub fn into_parts(self) -> (B, usize) { (self.batch, self.bytes_consumed) }
}
''')
change('codex-rs/hepta-wire/src/lib.rs', 'mod frame;\n', 'mod feed;\nmod frame;\n')
change('codex-rs/hepta-wire/src/lib.rs', 'pub use frame::DecodeFrameError;\n', 'pub use feed::DecodeFeed;\npub use frame::DecodeFrameError;\n')

p = Path('codex-rs/hepta-wire/src/stream.rs')
s = p.read_text()
start = s.index('    /// Feed a transport chunk and preserve both a valid decoded prefix and a')
end = s.index('    /// Lossless convenience alias.', start)
s = s[:start] + '''    /// Consume a bounded prefix of a borrowed transport chunk.
    ///
    /// Resource exhaustion yields without poisoning. Process the returned batch,
    /// then resubmit `chunk[result.bytes_consumed()..]` on the same decoder.
    /// A non-empty feed either consumes bytes or reports a terminal error. Only
    /// one admitted partial frame is retained; coalescing cannot cause rejection.
    pub fn feed(&mut self, chunk: &[u8]) -> crate::DecodeFeed<StreamDecodeBatch> {
        if let Some(error) = self.terminal_error.clone() {
            return crate::DecodeFeed::new(StreamDecodeBatch {
                frames: Vec::new(), terminal_error: Some(error),
            }, 0);
        }
        let mut decoded = Vec::new();
        let mut offset = 0;
        while offset < chunk.len() && offset < self.max_feed_bytes {
            if decoded.len() >= self.max_frames_per_feed {
                break;
            }
            if self.expected_frame_length.is_none() {
                let remaining = WIRE_HEADER_BYTES.saturating_sub(self.buffer.len());
                let copied = remaining.min(chunk.len() - offset)
                    .min(self.max_feed_bytes - offset);
                self.buffer.extend_from_slice(&chunk[offset..offset + copied]);
                offset += copied;
                if self.buffer.len() < WIRE_HEADER_BYTES { break; }
                let parsed = match FrameHeader::parse(&self.buffer) {
                    Ok(header) => header,
                    Err(error) => return crate::DecodeFeed::new(
                        self.fail(decoded, StreamDecodeError::HeaderParse(error)), offset),
                };
                let header = match parsed.validate() {
                    Ok(header) => header,
                    Err(error) => return crate::DecodeFeed::new(
                        self.fail(decoded, StreamDecodeError::HeaderValidation(error)), offset),
                };
                if let Some(negotiated) = self.negotiated_version
                    && header.version() != negotiated {
                    return crate::DecodeFeed::new(self.fail(decoded,
                        StreamDecodeError::NegotiatedVersionMismatch {
                            negotiated, observed: header.version(), byte_offset: 4,
                        }), offset);
                }
                self.buffer.reserve_exact(header.frame_length().saturating_sub(self.buffer.len()));
                self.expected_frame_length = Some(header.frame_length());
            }
            let Some(expected) = self.expected_frame_length else { continue; };
            let copied = expected.saturating_sub(self.buffer.len())
                .min(chunk.len() - offset).min(self.max_feed_bytes - offset);
            self.buffer.extend_from_slice(&chunk[offset..offset + copied]);
            offset += copied;
            if self.buffer.len() < expected { break; }
            let frame = std::mem::replace(&mut self.buffer, Vec::with_capacity(WIRE_HEADER_BYTES));
            self.expected_frame_length = None;
            match decode_frame(&frame).map_err(StreamDecodeError::Frame) {
                Ok(envelope) => decoded.push(envelope),
                Err(error) => return crate::DecodeFeed::new(self.fail(decoded, error), offset),
            }
        }
        crate::DecodeFeed::new(StreamDecodeBatch {
            frames: decoded, terminal_error: None,
        }, offset)
    }

    /// Strict compatibility API for callers that require consumption of the
    /// entire supplied chunk. Its per-call work/byte ceiling remains explicit.
    /// Live transports use `feed` so resource yields never reject a valid stream.
    pub fn push_batch(&mut self, chunk: &[u8]) -> StreamDecodeBatch {
        let (batch, consumed) = self.feed(chunk).into_parts();
        if batch.terminal_error().is_some() || consumed == chunk.len() {
            return batch;
        }
        let work_exhausted = batch.frames().len() >= self.max_frames_per_feed;
        let (frames, _) = batch.into_parts();
        let error = if work_exhausted {
            StreamDecodeError::WorkFrameLimit {
                attempted: self.max_frames_per_feed.saturating_add(1),
                maximum: self.max_frames_per_feed, byte_offset: consumed,
            }
        } else {
            StreamDecodeError::BufferLimit {
                attempted: consumed.saturating_add(1),
                maximum: self.max_feed_bytes, byte_offset: consumed,
            }
        };
        self.fail(frames, error)
    }

''' + s[end:]
s = s.replace('Two independent budgets apply to every feed: retained/borrowed bytes and',
              'Two independent work budgets apply to every feed: consumed bytes and')
s = s.replace('Configure the per-feed byte budget in maximum-frame units while using',
              'Configure the per-feed byte-work budget in maximum-frame units while using')
p.write_text(s)
change('codex-rs/hepta-wire/src/stream_tests.rs', '''fn buffer_limit_rejects_before_copying_unbounded_chunk()''',
       '''fn unbounded_invalid_chunk_rejects_after_only_the_fixed_header()''')
change('codex-rs/hepta-wire/src/stream_tests.rs', '''    assert!(matches!(
        decoder.push(&oversized).terminal_error(),
        Some(StreamDecodeError::BufferLimit { .. })
    ));''', '''    assert!(is_magic(decoder.push(&oversized).terminal_error()));
    assert!(decoder.is_poisoned());''')

session_path = 'codex-rs/hepta-wire/src/session.rs'
for typ, batch in [
    ('NegotiatedStreamingDecoder', 'NegotiatedDecodeBatch'),
    ('WireSessionDecoder', 'WireSessionDecodeBatch'),
]:
    p = Path(session_path)
    text = p.read_text()
    impl_start = text.index(f'impl {typ} {{')
    next_impl = text.find('\nimpl ', impl_start + 1)
    if next_impl < 0: next_impl = len(text)
    section = text[impl_start:next_impl]
    if typ == 'NegotiatedStreamingDecoder':
        old = '''        let stream_batch = self.stream.push_batch(chunk);
        let (decoded, stream_error) = stream_batch.into_parts();'''
    else:
        old = '''        let (decoded, stream_error) = self.stream.push_batch(chunk).into_parts();'''
    new = f'''        let stream_batch = self.stream.push_batch(chunk);
        self.admit_stream_batch(stream_batch)
    }}

    /// Process bounded input, retaining the transport's unconsumed suffix in
    /// the caller. A yield is not an error and never resets negotiation.
    pub fn feed(&mut self, chunk: &[u8]) -> crate::DecodeFeed<{batch}> {{
        if let Some(error) = self.terminal_error.clone() {{
            return crate::DecodeFeed::new({batch} {{
                frames: Vec::new(), terminal_error: Some(error),
            }}, 0);
        }}
        let (stream_batch, consumed) = self.stream.feed(chunk).into_parts();
        crate::DecodeFeed::new(self.admit_stream_batch(stream_batch), consumed)
    }}

    fn admit_stream_batch(&mut self, stream_batch: crate::StreamDecodeBatch) -> {batch} {{
        let (decoded, stream_error) = stream_batch.into_parts();'''
    assert section.count(old) == 1, typ
    p.write_text(text[:impl_start] + section.replace(old, new) + text[next_impl:])

secure = 'codex-rs/hepta-wire/src/secure_session.rs'
change(secure, 'b"HPTA-WIRE-SESSION-V1\\0"', 'b"HPTA-WIRE-SESSION-V2\\0"')
change(secure, '''pub struct NegotiationTranscript {
    digest: Digest32,
}''', '''pub struct NegotiationTranscript {
    digest: Digest32,
    negotiated: NegotiatedWire,
    registry_digest: Digest32,
}''')
change(secure, '''            digest: Digest32::of_bytes(&encoded),
        })''', '''            digest: Digest32::of_bytes(&encoded),
            negotiated,
            registry_digest,
        })''')
change(secure, '''            &capabilities,
        ]);''', '''            &capabilities,
            &(role.as_str().len() as u32).to_be_bytes(),
            role.as_str().as_bytes(),
        ]);''')
change(secure, '''    pub fn admit_envelope(&self, envelope: &DecodedEnvelope) -> Result<(), WireSessionError> {
        self.registry''', '''    pub fn admit_envelope(&self, envelope: &DecodedEnvelope) -> Result<(), WireSessionError> {
        if self.transcript.negotiated != self.negotiated
            || self.transcript.registry_digest != self.registry.snapshot_digest()
        {
            return Err(WireSessionError::NegotiationResultMismatch);
        }
        self.registry''')
p = Path(secure)
s = p.read_text()
a = s.index('        if !constant_time_eq(\n            &record[6..session_end],')
b = s.index('        let length_offset = session_end + 8;', a)
semantic = s[a:b]
s = s[:a] + s[b:]
anchor = '''        let envelope = self
            .session
            .decode_frame(&record[frame_start..frame_end])'''
assert s.count(anchor) == 1
s = s.replace(anchor, '''        // Session and sequence claims are interpreted only after authenticating
        // the bounded record; forged semantic fields cannot select an oracle.
''' + semantic + anchor)
p.write_text(s)

add('codex-rs/hepta-wire/tests/review_regressions.rs', r'''//! Regression cases for the September 28 source repair. No external effects.
use std::error::Error;
use std::sync::Arc;
use codex_hepta_types::{Generation, StableId};
use codex_hepta_wire::*;

fn id(text: &str) -> Result<StableId, Box<dyn Error>> { Ok(StableId::new(text)?) }
fn frame(generation: u64, size: usize) -> Result<DecodedEnvelope, Box<dyn Error>> {
    Ok(DecodedEnvelope::V2(WireEnvelopeV2::new(
        id("schema.review")?, id("producer.review")?,
        Generation::new(generation)?, vec![0x5a; size],
    )?))
}
fn session(role: &str) -> Result<WireSession, Box<dyn Error>> {
    let descriptor = SchemaDescriptor::new(id("schema.review")?, WireVersion::V2,
        WireVersion::V2, MAX_WIRE_PAYLOAD_BYTES)?;
    let required = WireCapabilities::METADATA_BOUND_DIGEST.union(WireCapabilities::SCHEMA_ADMISSION);
    let policy = SchemaPolicy::new(descriptor, vec![id("producer.review")?],
        vec![id("role.alpha")?, id("role.beta")?], required)?;
    let mut builder = FrozenSchemaRegistryBuilder::new();
    builder.register(policy)?;
    let registry = Arc::new(builder.freeze()?);
    let offer = NegotiationOffer::current();
    let posture = negotiate(&offer, &offer, required)?;
    // Deterministic test-only binding. Production must use transport-owned inputs.
    let transcript = NegotiationTranscript::from_offers(&offer, &offer, posture,
        registry.snapshot_digest(), &[0x37; 32])?;
    Ok(WireSession::new(posture, id(role)?, registry, transcript))
}
fn drain(decoder: &mut StreamingDecoder, input: &[u8]) -> Vec<DecodedEnvelope> {
    let mut offset = 0;
    let mut frames = Vec::new();
    while offset < input.len() {
        let (batch, consumed) = decoder.feed(&input[offset..]).into_parts();
        assert!(consumed > 0 && consumed <= input.len() - offset);
        assert!(batch.terminal_error().is_none());
        frames.extend(batch.into_parts().0);
        offset += consumed;
        assert!(!decoder.is_poisoned());
        assert!(decoder.buffered_len() <= MAX_WIRE_FRAME_BYTES);
    }
    frames
}
#[test]
fn coalesced_large_frames_yield_without_rejecting_or_retaining_suffix() -> Result<(), Box<dyn Error>> {
    let frames: Vec<_> = (1..=5).map(|n| frame(n, MAX_WIRE_PAYLOAD_BYTES / 2)).collect::<Result<_, _>>()?;
    let input: Vec<_> = frames.iter().flat_map(DecodedEnvelope::encode).collect();
    assert!(input.len() > MAX_WIRE_FRAME_BYTES * MAX_BUFFERED_WIRE_FRAMES);
    let mut coalesced = StreamingDecoder::new();
    assert_eq!(drain(&mut coalesced, &input), frames);
    assert_eq!(coalesced.buffered_len(), 0);
    for size in [53, 54, 55, 4096, MAX_WIRE_FRAME_BYTES] {
        let mut decoder = StreamingDecoder::new();
        let mut received = Vec::new();
        for chunk in input.chunks(size) { received.extend(drain(&mut decoder, chunk)); }
        assert_eq!(received, frames);
        assert_eq!(decoder.buffered_len(), 0);
    }
    Ok(())
}
#[test]
fn work_budget_is_a_resumable_yield_in_live_feed() -> Result<(), Box<dyn Error>> {
    let value = frame(1, 1)?;
    let input = value.encode().repeat(MAX_WIRE_FRAMES_PER_FEED + 3);
    let mut decoder = StreamingDecoder::with_limits(1, 2)?;
    let values = drain(&mut decoder, &input);
    assert_eq!(values.len(), MAX_WIRE_FRAMES_PER_FEED + 3);
    assert!(values.iter().all(|v| *v == value));
    Ok(())
}
#[test]
fn every_single_split_of_good_bad_good_preserves_prefix_and_poison() -> Result<(), Box<dyn Error>> {
    let good = frame(1, 1)?;
    let mut bad = frame(2, 1)?.encode();
    *bad.last_mut().ok_or("empty frame")? ^= 1;
    let input = [good.encode(), bad, good.encode()].concat();
    for split in 0..=input.len() {
        let mut decoder = StreamingDecoder::new();
        let mut received = Vec::new();
        let mut failed = false;
        for chunk in [&input[..split], &input[split..]] {
            if failed { break; }
            let (batch, consumed) = decoder.feed(chunk).into_parts();
            assert!(consumed <= chunk.len());
            failed = batch.terminal_error().is_some();
            received.extend(batch.into_parts().0);
        }
        assert!(failed && decoder.is_poisoned());
        assert_eq!(received, vec![good.clone()]);
        let again = decoder.feed(&good.encode());
        assert_eq!(again.bytes_consumed(), 0);
        assert!(again.batch().frames().is_empty());
        assert!(again.batch().terminal_error().is_some());
    }
    Ok(())
}
#[test]
fn negotiated_and_policy_decoders_preserve_consumption_on_yield() -> Result<(), Box<dyn Error>> {
    let session = session("role.alpha")?;
    let input = frame(1, 1)?.encode().repeat(MAX_WIRE_FRAMES_PER_FEED + 1);
    let mut selected = NegotiatedStreamingDecoder::new(session.negotiated());
    let mut policy = WireSessionDecoder::new(session);
    let first = selected.feed(&input);
    let second = policy.feed(&input);
    assert_eq!(first.bytes_consumed(), second.bytes_consumed());
    assert_eq!(first.batch().frames().len(), MAX_WIRE_FRAMES_PER_FEED);
    assert!(first.batch().terminal_error().is_none());
    assert!(second.batch().terminal_error().is_none());
    assert_eq!(selected.feed(&input[first.bytes_consumed()..]).batch().frames().len(), 1);
    assert_eq!(policy.feed(&input[second.bytes_consumed()..]).batch().frames().len(), 1);
    Ok(())
}
#[test]
fn same_transcript_different_runtime_roles_have_different_session_ids() -> Result<(), Box<dyn Error>> {
    let a = session("role.alpha")?;
    let b = session("role.beta")?;
    assert_eq!(a.transcript().digest(), b.transcript().digest());
    assert_eq!(a.registry().snapshot_digest(), b.registry().snapshot_digest());
    assert_ne!(a.session_id(), b.session_id());
    Ok(())
}
#[test]
fn forged_identity_and_sequence_are_authenticated_before_semantic_errors() -> Result<(), Box<dyn Error>> {
    let mut sender = AuthenticatedWireSession::new(session("role.alpha")?,
        SessionMacKey::new([0x73; 32])?, SessionEndpoint::Initiator)?;
    let record = sender.seal_envelope(&frame(1, 1)?)?;
    for offset in [6, 37, 38, 45] {
        let mut receiver = AuthenticatedWireSession::new(session("role.alpha")?,
            SessionMacKey::new([0x73; 32])?, SessionEndpoint::Responder)?;
        let mut forged = record.clone();
        forged[offset] ^= 1;
        assert!(matches!(receiver.open_record(&forged), Err(AuthenticatedSessionError::MacMismatch { .. })));
        assert!(receiver.is_poisoned());
    }
    let mut receiver = AuthenticatedWireSession::new(session("role.alpha")?,
        SessionMacKey::new([0x73; 32])?, SessionEndpoint::Responder)?;
    receiver.open_record(&record)?;
    assert!(matches!(receiver.open_record(&record), Err(AuthenticatedSessionError::SequenceMismatch { .. })));
    Ok(())
}
#[test]
fn transcript_cannot_be_rebound_to_another_registry() -> Result<(), Box<dyn Error>> {
    let original = session("role.alpha")?;
    let mut builder = FrozenSchemaRegistryBuilder::new();
    builder.register(SchemaPolicy::new(
        SchemaDescriptor::new(id("schema.review")?, WireVersion::V2, WireVersion::V2, 128)?,
        vec![id("producer.review")?], vec![id("role.alpha")?],
        WireCapabilities::METADATA_BOUND_DIGEST.union(WireCapabilities::SCHEMA_ADMISSION),
    )?)?;
    let rebound = WireSession::new(original.negotiated(), id("role.alpha")?,
        Arc::new(builder.freeze()?), original.transcript());
    assert!(matches!(rebound.admit_envelope(&frame(1, 1)?), Err(WireSessionError::NegotiationResultMismatch)));
    Ok(())
}
''')

lane = '.github/workflows/lane-a-foundation.yml'
change(lane, '''      - "codex-rs/hepta-*/**"
      - "codex-rs/kernel-*/**"''', '''      # BEGIN GENERATED LANE A MODULE PATHS
      # END GENERATED LANE A MODULE PATHS
      - "docs/modules/MODULES.json"
      - "codex-rs/Cargo.toml"
      - "codex-rs/Cargo.lock"
      - "scripts/generate_lane_a_workflow_paths.py"
      - "scripts/test_generate_lane_a_workflow_paths.py"''')
for old in ['      - "docs/modules/platform.types/**"\n', '      - "docs/modules/platform.wire/**"\n']:
    change(lane, old, '')
run('python3', 'scripts/generate_lane_a_workflow_paths.py', 'write')
change(lane, '''          python3 scripts/verify_lane_a_foundation.py self-test''',
       '''          python3 scripts/generate_lane_a_workflow_paths.py check
          python3 -m unittest discover -s scripts -p 'test_generate_lane_a_workflow_paths.py'
          python3 scripts/verify_lane_a_foundation.py self-test''', 2)

fuzz = '.github/workflows/platform-wire-fuzz.yml'
change(fuzz, '      - name: Verify exact source and install pinned fuzz toolchain',
       '      - name: Verify exact source and install pinned fuzz toolchain\n        id: setup')
change(fuzz, ' --profile minimal --component llvm-tools-preview', ' --profile minimal')
change(fuzz, '''      - "codex-rs/hepta-wire/**"''', '''      - "codex-rs/hepta-wire/**"
      - "codex-rs/hepta-types/**"
      - "codex-rs/Cargo.lock"
      - "codex-rs/Cargo.toml"''', 2)
change(fuzz, '''          FUZZ_SECONDS: ${{ steps.duration.outputs.seconds }}''', '''          FUZZ_SECONDS: ${{ steps.duration.outputs.seconds }}
          SETUP_OUTCOME: ${{ steps.setup.outcome }}''')
change(fuzz, '''"duration_seconds": int(os.environ["FUZZ_SECONDS"]),
              "status": "passed" if os.environ["FUZZ_OUTCOME"] == "success" else "failed",''', '''"duration_seconds": int(os.environ.get("FUZZ_SECONDS") or "0"),
              "status": ("passed" if os.environ["FUZZ_OUTCOME"] == "success"
                         else "failed" if os.environ["FUZZ_OUTCOME"] == "failure"
                         else "infrastructure_invalid"),
              "setup_outcome": os.environ.get("SETUP_OUTCOME", "unknown"),
              "source_tree": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], text=True).strip(),
              "workflow_sha": os.environ.get("GITHUB_WORKFLOW_SHA", ""),
              "runner_image": os.environ.get("ImageVersion", "unknown"),''')
change(fuzz, '''      - name: Resolve bounded fuzz duration
        id: duration''', '''      - name: Resolve bounded fuzz duration
        env:
          REQUESTED_DURATION: ${{ inputs.duration_seconds }}
        id: duration''')
change(fuzz, "workflow_dispatch) seconds='${{ inputs.duration_seconds }}' ;;", 'workflow_dispatch) seconds="$REQUESTED_DURATION" ;;')

current = 'docs/lane-a-foundation/platform.wire/CURRENT_IMPLEMENTATION.md'
text = Path(current).read_text()
if '## Durability and activation' not in text:
    change(current, '## Negotiation, session and admission invariants', '''## Durability and activation

Wire decoders own connection-local buffers only. They do not own durable domain
authority or business state. Source composition is not production activation.

## Negotiation, session and admission invariants''')
if '## Target-only design' not in text:
    change(current, '## Known limits and non-claims', '''## Target-only design

Selected production transports still require transport-owner authentication,
crash/recovery evidence, protected target-host qualification and distinct
independent reviewer/operations acceptance. An in-process V3 envelope round trip
does not prove that HPTM wraps the physical App Server turn/start exchange.

## Known limits and non-claims''')
if '## Integration prerequisites' not in text:
    with Path(current).open('a') as out:
        out.write('''\n## Integration prerequisites\n\nExact-head and deterministic-merge checks must pass for the final source commit.\nProtected target-host, reviewer, operations and release evidence must bind that\nsame source. Historical receipts cannot satisfy these gates.\n''')

add('docs/modules/platform.wire/STREAM_AND_SESSION_V2_REPAIR.md', '''# Bounded feed and role-bound session identity

## Streaming contract

Live transports use `StreamingDecoder::feed`, `NegotiatedStreamingDecoder::feed`
or `WireSessionDecoder::feed`. Each returns `DecodeFeed<B>`, containing a batch
and `bytes_consumed`. Process all completed frames, then inspect the terminal
error. In the absence of an error, resubmit the unconsumed suffix on the same
decoder. A byte/work budget exhaustion yields without poisoning; it is not a
protocol rejection. No suffix is silently copied or discarded.

Retained state is at most one structurally admitted frame. Byte-work and
completed-frame ceilings independently bound each call, including the returned
batch. Protocol/admission errors preserve the completed prefix and poison the
session. A poisoned decoder consumes zero further bytes. `push`/`push_batch`
remain strict, bounded compatibility calls: exceeding their documented per-call
budget is terminal. They are not the chunk-invariant live transport interface.

## Session identity profile 2

The HPTA V1/V2 frame layout and HPTM V1 record layout are unchanged. Session ID
profile 2 uses the new domain `HPTA-WIRE-SESSION-V2\\0`, the transcript digest,
registry digest, selected version and effective capability bytes, followed by a
u32 big-endian runtime-role byte length and the UTF-8 runtime role. This profile
is not a reinterpretation of the previous identity domain. Profile-1 records
cannot be replayed into profile-2 sessions; there is no fallback. Peers must
upgrade together or establish separate explicitly compatible sessions.

A transcript retains its negotiated posture and registry digest. Recombining it
with a different posture or registry is rejected at envelope admission. Runtime
policy role is shared session context; it is distinct from local initiator or
responder direction. Transport owners remain responsible for authenticating peer
identities, supplying fresh channel binding/nonces and distributing session keys.

## Authenticated record processing

Only public framing/length bounds are inspected before MAC verification. Session
ID and sequence semantics are checked after the MAC and before frame/domain
decode. Forged semantic fields fail authentication, while authenticated replay
still produces a sequence rejection. Authentication failure remains fatal; this
change does not claim resistance to connection-termination denial of service.

## Evidence boundary

These changes are ordinary source changes, not qualification or acceptance
receipts. The source-authoring branch may produce a proposal, but candidate
qualification is read-only and tests the final exact commit. Production transport
activation, real cross-host recovery, protected host qualification, independent
acceptance and release remain closed until supported by their own evidence.
''')
for path in ['docs/modules/platform.wire/TECHNICAL.md', current,
             'docs/modules/platform.wire/SECURITY_AND_QUALIFICATION.md',
             'qualification/module-execution-dossiers/detail/platform.wire.md']:
    with Path(path).open('a') as out:
        out.write('''\n### September 28 source repair\n\nThe bounded live-feed API and session identity profile 2 supersede earlier\nper-chunk buffering and role-free identity descriptions. See\n`docs/modules/platform.wire/STREAM_AND_SESSION_V2_REPAIR.md`. Compatibility\n`push_batch` is strict; `feed` preserves unconsumed transport ownership across\nyields. Neither source availability nor this note grants production acceptance.\n''')

subprocess.run(['cargo', 'fmt', '--manifest-path', 'codex-rs/Cargo.toml', '--package', 'codex-hepta-wire'], check=True)
subprocess.run(['git', 'add', 'codex-rs/Cargo.lock', 'codex-rs/hepta-wire',
                '.github/workflows/lane-a-foundation.yml', '.github/workflows/platform-wire-fuzz.yml',
                'docs/modules/platform.wire', current,
                'qualification/module-execution-dossiers/detail/platform.wire.md'], check=True)
tree = run('git', 'write-tree')
map_path = Path('docs/modules/platform.wire/IMPLEMENTATION_MAP.json')
mapping = json.loads(map_path.read_text())
paths = {row['path'] for row in mapping['sourceObjects']}
paths.update(['codex-rs/hepta-wire/src/feed.rs', 'codex-rs/hepta-wire/tests/review_regressions.rs',
              'codex-rs/Cargo.lock', '.github/workflows/platform-wire-fuzz.yml',
              '.github/workflows/platform-wire-repair.yml',
              'docs/modules/platform.wire/STREAM_AND_SESSION_V2_REPAIR.md',
              'scripts/generate_lane_a_workflow_paths.py', 'scripts/test_generate_lane_a_workflow_paths.py'])
mapping['sourceObjects'] = [{'path': path, 'object': run('git', 'rev-parse', f'{tree}:{path}')} for path in sorted(paths)]
for operation in mapping['operations']:
    if operation['operation'] in {'session_decode', 'schema_admission', 'negotiate'}:
        tests = operation.setdefault('tests', [])
        if 'codex-rs/hepta-wire/tests/review_regressions.rs' not in tests:
            tests.append('codex-rs/hepta-wire/tests/review_regressions.rs')
assert mapping['productionImplementation'] is False
map_path.write_text(json.dumps(mapping, indent=2) + '\n')
subprocess.run(['git', 'add', str(map_path)], check=True)
subprocess.run(['git', 'diff', '--cached', '--check'], check=True)
print('SOURCE_PROPOSAL_READY=' + run('git', 'write-tree'), flush=True)
