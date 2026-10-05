//! Deterministic high-contention model for the runtime.codex effect-entry fence.
//!
//! This supplements the 22-cut state model. It exercises many duplicate owners,
//! restarts, stale revisions and semantic-digest conflicts without depending on
//! a scheduler-specific ordering. Process-level and target-host stress remain
//! separate qualification gates.

use std::sync::Arc;
use std::sync::Barrier;
use std::sync::Mutex;
use std::thread;

const EXPECTED_DIGEST: u64 = 0x5a17_d15c_2026_0929;
const EXPECTED_REVISION: u64 = 41;
const CONTENDERS: usize = 256;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum OwnerPhase {
    ContextAttached,
    Dispatched,
    Terminal,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct OwnerRecord {
    phase: OwnerPhase,
    revision: u64,
    dispatch_digest: Option<u64>,
    physical_sends: u8,
    terminal_observed: bool,
    capacity_held: bool,
}

impl OwnerRecord {
    fn new() -> Self {
        Self {
            phase: OwnerPhase::ContextAttached,
            revision: EXPECTED_REVISION,
            dispatch_digest: None,
            physical_sends: 0,
            terminal_observed: false,
            capacity_held: true,
        }
    }

    fn enter_effect(
        &mut self,
        revision: u64,
        digest: u64,
    ) -> Result<FenceAck, FenceError> {
        if revision != self.revision {
            return Err(FenceError::StaleRevision);
        }
        if digest != EXPECTED_DIGEST {
            return Err(FenceError::DigestMismatch);
        }
        match self.phase {
            OwnerPhase::ContextAttached => {
                self.phase = OwnerPhase::Dispatched;
                self.dispatch_digest = Some(digest);
                self.revision += 1;
                Ok(FenceAck::Fresh)
            }
            OwnerPhase::Dispatched if self.dispatch_digest == Some(digest) => {
                Ok(FenceAck::Idempotent)
            }
            OwnerPhase::Dispatched | OwnerPhase::Terminal => Err(FenceError::InvalidTransition),
        }
    }

    fn send(&mut self, ack: FenceAck) -> Result<(), FenceError> {
        if ack != FenceAck::Fresh
            || self.phase != OwnerPhase::Dispatched
            || self.dispatch_digest != Some(EXPECTED_DIGEST)
        {
            return Err(FenceError::NoFreshSendPermit);
        }
        if self.physical_sends != 0 {
            return Err(FenceError::DuplicateSend);
        }
        self.physical_sends = 1;
        Ok(())
    }

    fn settle_terminal(&mut self, observed: bool) -> Result<(), FenceError> {
        if self.phase != OwnerPhase::Dispatched || !observed {
            return Err(FenceError::TerminalEvidenceRequired);
        }
        self.phase = OwnerPhase::Terminal;
        self.revision += 1;
        self.terminal_observed = true;
        self.capacity_held = false;
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum FenceAck {
    Fresh,
    Idempotent,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum FenceError {
    StaleRevision,
    DigestMismatch,
    InvalidTransition,
    NoFreshSendPermit,
    DuplicateSend,
    TerminalEvidenceRequired,
}

#[test]
fn two_hundred_fifty_six_duplicate_owners_produce_one_fresh_winner_and_send() {
    let owner = Arc::new(Mutex::new(OwnerRecord::new()));
    let barrier = Arc::new(Barrier::new(CONTENDERS));
    let mut workers = Vec::with_capacity(CONTENDERS);

    for _ in 0..CONTENDERS {
        let owner = Arc::clone(&owner);
        let barrier = Arc::clone(&barrier);
        workers.push(thread::spawn(move || {
            barrier.wait();
            let ack = {
                let mut record = owner.lock().expect("owner lock");
                record.enter_effect(EXPECTED_REVISION, EXPECTED_DIGEST)
            };
            match ack {
                Ok(FenceAck::Fresh) => {
                    owner
                        .lock()
                        .expect("owner lock")
                        .send(FenceAck::Fresh)
                        .expect("fresh winner sends once");
                    (1_u64, 1_u64, 0_u64)
                }
                Ok(FenceAck::Idempotent) => {
                    let result = owner
                        .lock()
                        .expect("owner lock")
                        .send(FenceAck::Idempotent);
                    assert_eq!(result, Err(FenceError::NoFreshSendPermit));
                    (0, 0, 1)
                }
                Err(FenceError::StaleRevision) => (0, 0, 1),
                other => panic!("unexpected contender result: {other:?}"),
            }
        }));
    }

    let (fresh, sends, losers) = workers
        .into_iter()
        .map(|worker| worker.join().expect("contender join"))
        .fold((0, 0, 0), |left, right| {
            (left.0 + right.0, left.1 + right.1, left.2 + right.2)
        });
    assert_eq!(fresh, 1);
    assert_eq!(sends, 1);
    assert_eq!(losers, (CONTENDERS - 1) as u64);
    let record = owner.lock().expect("owner lock");
    assert_eq!(record.physical_sends, 1);
    assert_eq!(record.phase, OwnerPhase::Dispatched);
    assert!(record.capacity_held);
}

#[test]
fn restart_snapshot_never_serializes_or_recreates_a_send_permit() {
    let mut owner = OwnerRecord::new();
    let fresh = owner
        .enter_effect(EXPECTED_REVISION, EXPECTED_DIGEST)
        .expect("fresh fence");
    assert_eq!(fresh, FenceAck::Fresh);

    // Durable state contains the committed fence but no process-local permit.
    let mut reopened = owner;
    let recovered = reopened
        .enter_effect(owner.revision, EXPECTED_DIGEST)
        .expect("idempotent recovery");
    assert_eq!(recovered, FenceAck::Idempotent);
    assert_eq!(
        reopened.send(recovered),
        Err(FenceError::NoFreshSendPermit)
    );
    assert_eq!(reopened.physical_sends, 0);
    assert!(reopened.capacity_held);
}

#[test]
fn ten_thousand_stale_revisions_are_mutation_atomic() {
    for offset in 1..=10_000_u64 {
        let mut owner = OwnerRecord::new();
        let before = owner;
        let stale = if offset % 2 == 0 {
            EXPECTED_REVISION.saturating_sub(offset)
        } else {
            EXPECTED_REVISION.saturating_add(offset)
        };
        assert_eq!(
            owner.enter_effect(stale, EXPECTED_DIGEST),
            Err(FenceError::StaleRevision)
        );
        assert_eq!(owner, before);
    }
}

#[test]
fn ten_thousand_digest_conflicts_are_mutation_atomic() {
    for offset in 1..=10_000_u64 {
        let mut owner = OwnerRecord::new();
        let before = owner;
        assert_eq!(
            owner.enter_effect(EXPECTED_REVISION, EXPECTED_DIGEST ^ offset),
            Err(FenceError::DigestMismatch)
        );
        assert_eq!(owner, before);
    }
}

#[test]
fn lost_fence_ack_cannot_be_recovered_into_a_send_permit() {
    let mut server = OwnerRecord::new();
    let _lost_response = server
        .enter_effect(EXPECTED_REVISION, EXPECTED_DIGEST)
        .expect("server committed fence");

    // The caller did not observe the fresh ACK. A later exact query is
    // idempotent evidence only.
    let recovered = server
        .enter_effect(server.revision, EXPECTED_DIGEST)
        .expect("query exact committed fence");
    assert_eq!(recovered, FenceAck::Idempotent);
    assert_eq!(
        server.send(recovered),
        Err(FenceError::NoFreshSendPermit)
    );
    assert_eq!(server.physical_sends, 0);
    assert!(server.capacity_held);
}

#[test]
fn terminal_requires_evidence_and_releases_capacity_once() {
    let mut owner = OwnerRecord::new();
    let ack = owner
        .enter_effect(EXPECTED_REVISION, EXPECTED_DIGEST)
        .expect("fresh fence");
    owner.send(ack).expect("one send");
    assert_eq!(
        owner.settle_terminal(false),
        Err(FenceError::TerminalEvidenceRequired)
    );
    assert!(owner.capacity_held);
    owner.settle_terminal(true).expect("terminal evidence");
    assert_eq!(owner.phase, OwnerPhase::Terminal);
    assert!(!owner.capacity_held);
    assert!(owner.terminal_observed);
    assert_eq!(
        owner.settle_terminal(true),
        Err(FenceError::TerminalEvidenceRequired)
    );
    assert_eq!(owner.physical_sends, 1);
}
