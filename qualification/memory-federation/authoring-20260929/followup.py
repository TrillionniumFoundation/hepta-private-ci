#!/usr/bin/env python3
"""Exact-source authoring patch. Never called by qualification."""
from pathlib import Path

ROOT = Path.cwd()
WIRE = 'codex-rs/hepta-memory-federation-wire/src/'


def replace(path, old, new):
    p = ROOT / path
    text = p.read_text()
    if text.count(old) != 1:
        raise ValueError(f'preimage mismatch: {path}: {old[:80]}')
    p.write_text(text.replace(old, new))


def append(path, text):
    p = ROOT / path
    p.write_text(p.read_text() + text)


replace(WIRE + 'lib.rs', 'pub use product::FederationAuthenticatedTransportV1;', 'pub use product::FEDERATION_TRANSPORT_CONTEXT_KEY_BYTES;\npub use product::FederationAuthenticatedTransportV1;')
replace(WIRE + 'lib.rs', 'pub use product::FederationWireTransportV2;', 'pub use product::FederationTransportContextIssuerV1;\npub use product::FederationTransportContextVerifierV1;\npub use product::FederationWireTransportV2;')
replace('scripts/prepare_memory_federation_observation.py', 'set(verifier.tracked_source_paths(row)) | set(row["observedSourcePaths"])', 'set(verifier.tracked_source_paths(row)) | set(row["observedSourcePaths"]) | set(NEW_EVIDENCE)')

replace(WIRE + 'recovery_index.rs', '''    pub(crate) fn stage_at(&self, now_unix_ms: u64) -> Result<Self, FederationRecoveryError> {
''', '''    pub(crate) fn stage_at(&self, now_unix_ms: u64) -> Result<Self, FederationRecoveryError> {
        self.stage_maintenance_at(now_unix_ms, FEDERATION_RECOVERY_CLEANUP_BATCH)
    }

    pub(crate) fn stage_maintenance_at(
        &self,
        now_unix_ms: u64,
        maximum_records: usize,
    ) -> Result<Self, FederationRecoveryError> {
''')
replace(WIRE + 'recovery_index.rs', '        next.purge_expired(now_unix_ms);', '        next.purge_expired_bounded(now_unix_ms, maximum_records.min(FEDERATION_RECOVERY_CLEANUP_BATCH))?;')

host_method = '''    /// Commit at most one 64-row expiry-maintenance quantum across durable
    /// protocol rows and the live replay cache. This owner operation performs
    /// no remote I/O, query replay, credential change, or authority decision.
    /// Use it between admissions so failed requests cannot stall cleanup by
    /// repeatedly rolling back their temporary transaction state.
    pub fn maintain_expired(&mut self, now_unix_ms: u64) -> Result<usize, FederationHostError> {
        let maximum = crate::recovery::FEDERATION_RECOVERY_CLEANUP_BATCH;
        let before = self.recovery.replay_len() + self.recovery.attempt_len();
        let next = self.recovery.stage_maintenance_at(now_unix_ms, maximum)?;
        let removed = before - next.replay_len() - next.attempt_len();
        let mut replay = self.replay.clone();
        let live_removed = replay
            .purge_expired_bounded(now_unix_ms, maximum.saturating_sub(removed))
            .map_err(FederationHostError::Replay)?;
        self.commit_recovery_and_replay(next, replay)?;
        Ok(removed + live_removed)
    }

'''
replace(WIRE + 'host.rs', '    pub fn recovery_snapshot(&self)', host_method + '    pub fn recovery_snapshot(&self)')

client_method = '''    /// Persist one bounded expiry-maintenance quantum independently of any
    /// request. Failed admission cleanup is intentionally rolled back; this
    /// owner entrypoint makes progress without replaying a query. Derived client
    /// metadata is reconciled by the existing atomic state replacement.
    pub fn maintain_expired(&mut self, now_unix_ms: u64) -> Result<usize, FederationClientError> {
        let maximum = crate::recovery::FEDERATION_RECOVERY_CLEANUP_BATCH;
        let before = self.recovery.replay_len() + self.recovery.attempt_len();
        let next = self.recovery.stage_maintenance_at(now_unix_ms, maximum)?;
        let removed = before - next.replay_len() - next.attempt_len();
        let mut replay = self.replay.clone();
        let live_removed = replay.purge_expired_bounded(now_unix_ms, maximum.saturating_sub(removed))?;
        self.replace_state_and_replay(next, self.attempts.clone(), self.frontiers.clone(), replay)?;
        Ok(removed + live_removed)
    }

'''
replace(WIRE + 'client/persistence.rs', '    pub fn recovery_snapshot(&self)', client_method + '    pub fn recovery_snapshot(&self)')
for marker in ['    pub fn into_wire_host(self)', '    pub fn into_wire_client(self)']:
    replace(WIRE + 'product/bridge.rs', marker, '''    /// Run owner-local bounded maintenance through the same durable wire owner.
    /// It never dispatches or retries a product query.
    pub fn maintain_expired(&mut self, now_unix_ms: u64) -> Result<usize, FederationProductErrorV1> {
        Ok(self.wire.maintain_expired(now_unix_ms)?)
    }

''' + marker)

append(WIRE + 'host_atomicity_tests.rs', '''

#[test]
fn owner_maintenance_progresses_after_failed_admission_without_replaying_queries() {
    let limits = FederationRecoveryLimitsV1 {
        replay_capacity: 512,
        replay_per_peer_capacity: 128,
        attempt_capacity: 512,
        attempt_per_peer_capacity: 128,
    };
    let mut state = DurableFederationStateV1::empty(id("peer-b"), limits, NOW).expect("state");
    for (peer, expiry) in [("peer-c", NOW + 1_000), ("peer-a", NOW + 2_000)] {
        for slot in 0..128 {
            let key = digest(format!("maintenance-{peer}-{slot}").as_bytes());
            state.record_verified_frame(*key.as_array(), &id(peer), expiry).expect("fixture row");
        }
    }
    let store = ControlledStore::default();
    store.state.lock().expect("store").snapshot = Some(state.snapshot_bytes().expect("snapshot"));
    let control = store.clone();
    let mut host = FederationWireHostV1::open(id("peer-b"), credentials(), 512, 128, limits, store, NOW)
        .expect("host");
    let packet = encode_from_a(FederationWireMessageV1::Query(query()), 119);
    let before = host.recovery_snapshot().expect("before");
    assert!(matches!(host.admit(&id("peer-a"), &packet, NOW + 3_000),
        Err(FederationHostError::Recovery(FederationRecoveryError::ReplayPeerCapacityExhausted))));
    assert_eq!(host.recovery_snapshot().expect("denial unchanged"), before);
    control.fail_next_store();
    assert!(matches!(host.maintain_expired(NOW + 3_000),
        Err(FederationHostError::Recovery(FederationRecoveryError::StoreUnavailable))));
    assert_eq!(host.recovery_snapshot().expect("failure unchanged"), before);
    for _ in 0..4 {
        assert_eq!(host.maintain_expired(NOW + 3_000).expect("maintenance"), 64);
    }
    assert_eq!(host.maintain_expired(NOW + 3_000).expect("drained"), 0);
    assert!(matches!(host.admit(&id("peer-a"), &packet, NOW + 3_001).expect("first admission"),
        FederationHostAdmissionV1::Query(_)));
    assert_eq!(host.maintain_expired(NOW + 3_002).expect("live fence retained"), 0);
    assert!(host.admit(&id("peer-a"), &packet, NOW + 3_003).is_err());
    assert!(host.maintain_expired(NOW + 2_999).is_err());
}
''')
append(WIRE + 'client_tests/recovery.rs', '''

#[test]
fn client_owner_maintenance_is_atomic_and_reconciles_expired_attempt_metadata() {
    let store = ControlledStore::default();
    let control = store.clone();
    let mut client = open_client(store, NOW);
    client.begin_query(&id("peer-b"), query(), NOW + 1, NOW + 100).expect("query");
    let before = client.recovery_snapshot().expect("before");
    control.fail_next_store();
    assert!(matches!(client.maintain_expired(NOW + 101),
        Err(FederationClientError::Recovery(FederationRecoveryError::StoreUnavailable))));
    assert_eq!(client.recovery_snapshot().expect("failure unchanged"), before);
    assert_eq!(client.maintain_expired(NOW + 101).expect("maintenance"), 1);
    let mut restarted = open_client(client.into_recovery_store(), NOW + 102);
    assert_eq!(restarted.maintain_expired(NOW + 102).expect("drained"), 0);
    assert!(restarted.maintain_expired(NOW + 100).is_err());
}
''')
append('docs/modules/memory.federation/INDEXED_ADMISSION.md', '''

## Owner maintenance progress under repeated admission failure

Host and client expose `maintain_expired(now)` through their existing product
bridge. A call commits a shared maximum of 64 expired durable protocol rows and
live replay rows through the same recovery store, without sending or retrying a
query. The selected host owner must budget these calls between admissions;
there is no second worker, authority store, or automatic query retry here.
This matters when a denied attempt would repeatedly discard its staged cleanup
and otherwise never reach later expired rows in a full peer partition. A failed
maintenance store leaves the live snapshot unchanged; a successful call makes
its cleanup and clock high-water mark durable before installing state. Live
replay and cancellation fences remain untouched. Client metadata reconciliation,
state cloning, and full snapshot persistence still have bounded O(n) costs; the
64-row limit is not a claim of constant total operation cost. Regressions cover
partition pressure, a failed maintenance write, progress through multiple
quanta, replay retention, restart, and clock rollback.

The public crate root now also exports the already implemented configured
transport-context issuer, verifier, and key-size constant. This repairs product
consumer compilation without introducing a bare trusted-context constructor.
''')
