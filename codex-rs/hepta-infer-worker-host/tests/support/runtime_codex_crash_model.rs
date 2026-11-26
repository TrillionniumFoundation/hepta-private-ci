//! Executable closed-world model for the runtime.codex crash-injection matrix.
//!
//! This model deliberately distinguishes an Agentd effect-entry CAS from a
//! physical provider request. Only the caller that receives the fresh,
//! non-idempotent CAS acknowledgement owns a one-shot send permit. A lost or
//! idempotent acknowledgement is reconciliation evidence, never another send
//! permit. These tests supplement, but do not replace, process-level fault
//! injection on a selected target host.

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum LocalState {
    Empty,
    Reserved,
    Prepared,
    FenceUnknown,
    EffectEntered,
    Started,
    TerminalDurable,
    Released,
    Quarantined,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum OwnerState {
    Empty,
    ContextAttached,
    EffectEntryCommitted,
    CancelledBeforeEffect,
    Terminal,
    Indeterminate,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ReplayPosture {
    FreshAdmission,
    ReconcileOwner,
    ReconcileSameOperation,
    Closed,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum FenceResult {
    FreshAck,
    LostAck,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ModelError {
    InvalidTransition,
    DigestMismatch,
    StaleRevision,
    MissingAbortProof,
    MissingFreshFenceAck,
    DuplicateProviderSend,
    TerminalEvidenceRequired,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct Scenario {
    id: &'static str,
    local: LocalState,
    owner: OwnerState,
    fence_may_have_committed: bool,
    provider_may_have_received: bool,
    physical_provider_sends: u8,
    terminal_observed: bool,
    capacity_held: bool,
    replay: ReplayPosture,
}

const SCENARIOS: [Scenario; 22] = [
    Scenario {
        id: "RCX-CRASH-01",
        local: LocalState::Empty,
        owner: OwnerState::Empty,
        fence_may_have_committed: false,
        provider_may_have_received: false,
        physical_provider_sends: 0,
        terminal_observed: false,
        capacity_held: false,
        replay: ReplayPosture::FreshAdmission,
    },
    Scenario {
        id: "RCX-CRASH-02",
        local: LocalState::Reserved,
        owner: OwnerState::ContextAttached,
        fence_may_have_committed: false,
        provider_may_have_received: false,
        physical_provider_sends: 0,
        terminal_observed: false,
        capacity_held: true,
        replay: ReplayPosture::ReconcileOwner,
    },
    Scenario {
        id: "RCX-CRASH-03",
        local: LocalState::Prepared,
        owner: OwnerState::ContextAttached,
        fence_may_have_committed: false,
        provider_may_have_received: false,
        physical_provider_sends: 0,
        terminal_observed: false,
        capacity_held: true,
        replay: ReplayPosture::ReconcileOwner,
    },
    Scenario {
        id: "RCX-CRASH-04",
        local: LocalState::Prepared,
        owner: OwnerState::CancelledBeforeEffect,
        fence_may_have_committed: false,
        provider_may_have_received: false,
        physical_provider_sends: 0,
        terminal_observed: false,
        capacity_held: true,
        replay: ReplayPosture::ReconcileOwner,
    },
    Scenario {
        id: "RCX-CRASH-05",
        local: LocalState::Released,
        owner: OwnerState::CancelledBeforeEffect,
        fence_may_have_committed: false,
        provider_may_have_received: false,
        physical_provider_sends: 0,
        terminal_observed: false,
        capacity_held: false,
        replay: ReplayPosture::Closed,
    },
    Scenario {
        id: "RCX-CRASH-06",
        local: LocalState::FenceUnknown,
        owner: OwnerState::ContextAttached,
        fence_may_have_committed: true,
        provider_may_have_received: false,
        physical_provider_sends: 0,
        terminal_observed: false,
        capacity_held: true,
        replay: ReplayPosture::ReconcileOwner,
    },
    Scenario {
        id: "RCX-CRASH-07",
        local: LocalState::FenceUnknown,
        owner: OwnerState::EffectEntryCommitted,
        fence_may_have_committed: true,
        provider_may_have_received: false,
        physical_provider_sends: 0,
        terminal_observed: false,
        capacity_held: true,
        replay: ReplayPosture::ReconcileSameOperation,
    },
    Scenario {
        id: "RCX-CRASH-08",
        local: LocalState::EffectEntered,
        owner: OwnerState::EffectEntryCommitted,
        fence_may_have_committed: true,
        provider_may_have_received: false,
        physical_provider_sends: 0,
        terminal_observed: false,
        capacity_held: true,
        replay: ReplayPosture::ReconcileSameOperation,
    },
    Scenario {
        id: "RCX-CRASH-09",
        local: LocalState::EffectEntered,
        owner: OwnerState::EffectEntryCommitted,
        fence_may_have_committed: true,
        provider_may_have_received: true,
        physical_provider_sends: 0,
        terminal_observed: false,
        capacity_held: true,
        replay: ReplayPosture::ReconcileSameOperation,
    },
    Scenario {
        id: "RCX-CRASH-10",
        local: LocalState::EffectEntered,
        owner: OwnerState::EffectEntryCommitted,
        fence_may_have_committed: true,
        provider_may_have_received: true,
        physical_provider_sends: 1,
        terminal_observed: false,
        capacity_held: true,
        replay: ReplayPosture::ReconcileSameOperation,
    },
    Scenario {
        id: "RCX-CRASH-11",
        local: LocalState::EffectEntered,
        owner: OwnerState::EffectEntryCommitted,
        fence_may_have_committed: true,
        provider_may_have_received: false,
        physical_provider_sends: 0,
        terminal_observed: true,
        capacity_held: true,
        replay: ReplayPosture::ReconcileOwner,
    },
    Scenario {
        id: "RCX-CRASH-12",
        local: LocalState::Released,
        owner: OwnerState::Terminal,
        fence_may_have_committed: true,
        provider_may_have_received: false,
        physical_provider_sends: 0,
        terminal_observed: true,
        capacity_held: false,
        replay: ReplayPosture::Closed,
    },
    Scenario {
        id: "RCX-CRASH-13",
        local: LocalState::EffectEntered,
        owner: OwnerState::EffectEntryCommitted,
        fence_may_have_committed: true,
        provider_may_have_received: true,
        physical_provider_sends: 1,
        terminal_observed: false,
        capacity_held: true,
        replay: ReplayPosture::ReconcileSameOperation,
    },
    Scenario {
        id: "RCX-CRASH-14",
        local: LocalState::Started,
        owner: OwnerState::EffectEntryCommitted,
        fence_may_have_committed: true,
        provider_may_have_received: true,
        physical_provider_sends: 1,
        terminal_observed: false,
        capacity_held: true,
        replay: ReplayPosture::ReconcileSameOperation,
    },
    Scenario {
        id: "RCX-CRASH-15",
        local: LocalState::Started,
        owner: OwnerState::Indeterminate,
        fence_may_have_committed: true,
        provider_may_have_received: true,
        physical_provider_sends: 1,
        terminal_observed: false,
        capacity_held: true,
        replay: ReplayPosture::ReconcileSameOperation,
    },
    Scenario {
        id: "RCX-CRASH-16",
        local: LocalState::Started,
        owner: OwnerState::EffectEntryCommitted,
        fence_may_have_committed: true,
        provider_may_have_received: true,
        physical_provider_sends: 1,
        terminal_observed: true,
        capacity_held: true,
        replay: ReplayPosture::ReconcileOwner,
    },
    Scenario {
        id: "RCX-CRASH-17",
        local: LocalState::TerminalDurable,
        owner: OwnerState::EffectEntryCommitted,
        fence_may_have_committed: true,
        provider_may_have_received: true,
        physical_provider_sends: 1,
        terminal_observed: true,
        capacity_held: true,
        replay: ReplayPosture::ReconcileOwner,
    },
    Scenario {
        id: "RCX-CRASH-18",
        local: LocalState::TerminalDurable,
        owner: OwnerState::Terminal,
        fence_may_have_committed: true,
        provider_may_have_received: true,
        physical_provider_sends: 1,
        terminal_observed: true,
        capacity_held: true,
        replay: ReplayPosture::ReconcileOwner,
    },
    Scenario {
        id: "RCX-CRASH-19",
        local: LocalState::Released,
        owner: OwnerState::Terminal,
        fence_may_have_committed: true,
        provider_may_have_received: true,
        physical_provider_sends: 1,
        terminal_observed: true,
        capacity_held: false,
        replay: ReplayPosture::Closed,
    },
    Scenario {
        id: "RCX-CRASH-20",
        local: LocalState::Quarantined,
        owner: OwnerState::Indeterminate,
        fence_may_have_committed: true,
        provider_may_have_received: true,
        physical_provider_sends: 1,
        terminal_observed: false,
        capacity_held: true,
        replay: ReplayPosture::ReconcileSameOperation,
    },
    Scenario {
        id: "RCX-CRASH-21",
        local: LocalState::Quarantined,
        owner: OwnerState::EffectEntryCommitted,
        fence_may_have_committed: true,
        provider_may_have_received: false,
        physical_provider_sends: 0,
        terminal_observed: false,
        capacity_held: true,
        replay: ReplayPosture::ReconcileSameOperation,
    },
    Scenario {
        id: "RCX-CRASH-22",
        local: LocalState::Quarantined,
        owner: OwnerState::Indeterminate,
        fence_may_have_committed: true,
        provider_may_have_received: true,
        physical_provider_sends: 1,
        terminal_observed: false,
        capacity_held: true,
        replay: ReplayPosture::ReconcileSameOperation,
    },
];

#[derive(Clone, Debug, Eq, PartialEq)]
struct Machine {
    local: LocalState,
    owner: OwnerState,
    dispatch_digest: u64,
    owner_digest: Option<u64>,
    owner_revision: u64,
    abort_proof: bool,
    fresh_send_permit: bool,
    fence_may_have_committed: bool,
    provider_may_have_received: bool,
    physical_provider_sends: u8,
    terminal_observed: bool,
    capacity_held: bool,
}

impl Machine {
    fn prepared() -> Self {
        Self {
            local: LocalState::Prepared,
            owner: OwnerState::ContextAttached,
            dispatch_digest: 0x5a17_d15c,
            owner_digest: None,
            owner_revision: 2,
            abort_proof: true,
            fresh_send_permit: false,
            fence_may_have_committed: false,
            provider_may_have_received: false,
            physical_provider_sends: 0,
            terminal_observed: false,
            capacity_held: true,
        }
    }

    fn abort_before_effect(
        &mut self,
        expected_revision: u64,
        digest: u64,
    ) -> Result<(), ModelError> {
        if !self.abort_proof {
            return Err(ModelError::MissingAbortProof);
        }
        if expected_revision != self.owner_revision {
            return Err(ModelError::StaleRevision);
        }
        if digest != self.dispatch_digest {
            return Err(ModelError::DigestMismatch);
        }
        if self.local != LocalState::Prepared || self.owner != OwnerState::ContextAttached {
            return Err(ModelError::InvalidTransition);
        }
        self.local = LocalState::Released;
        self.owner = OwnerState::CancelledBeforeEffect;
        self.owner_digest = Some(digest);
        self.owner_revision += 1;
        self.abort_proof = false;
        self.capacity_held = false;
        Ok(())
    }

    fn commit_effect_entry_fence(
        &mut self,
        expected_revision: u64,
        digest: u64,
        result: FenceResult,
    ) -> Result<(), ModelError> {
        if expected_revision != self.owner_revision {
            return Err(ModelError::StaleRevision);
        }
        if digest != self.dispatch_digest {
            return Err(ModelError::DigestMismatch);
        }
        if self.owner != OwnerState::ContextAttached || self.local != LocalState::Prepared {
            return Err(ModelError::InvalidTransition);
        }

        // Set this before modelling the response. The RPC may have committed
        // even when its acknowledgement is lost.
        self.fence_may_have_committed = true;
        self.abort_proof = false;
        self.owner = OwnerState::EffectEntryCommitted;
        self.owner_digest = Some(digest);
        self.owner_revision += 1;
        match result {
            FenceResult::FreshAck => {
                self.local = LocalState::EffectEntered;
                self.fresh_send_permit = true;
            }
            FenceResult::LostAck => {
                self.local = LocalState::FenceUnknown;
                self.fresh_send_permit = false;
            }
        }
        Ok(())
    }

    fn reconcile_committed_fence(&mut self, digest: u64) -> Result<(), ModelError> {
        if self.owner != OwnerState::EffectEntryCommitted
            || self.owner_digest != Some(digest)
            || !self.fence_may_have_committed
        {
            return Err(ModelError::InvalidTransition);
        }
        // An idempotent status/receipt proves owner state but cannot mint the
        // fresh one-shot send permit.
        self.local = LocalState::FenceUnknown;
        self.fresh_send_permit = false;
        Ok(())
    }

    fn physical_provider_send(&mut self) -> Result<(), ModelError> {
        if !self.fresh_send_permit
            || self.local != LocalState::EffectEntered
            || self.owner != OwnerState::EffectEntryCommitted
        {
            return Err(ModelError::MissingFreshFenceAck);
        }
        if self.physical_provider_sends != 0 {
            return Err(ModelError::DuplicateProviderSend);
        }
        self.fresh_send_permit = false;
        self.provider_may_have_received = true;
        self.physical_provider_sends = 1;
        Ok(())
    }

    fn typed_pre_admission_rejection(&mut self) -> Result<(), ModelError> {
        if self.owner != OwnerState::EffectEntryCommitted
            || self.local != LocalState::EffectEntered
            || self.physical_provider_sends != 0
        {
            return Err(ModelError::InvalidTransition);
        }
        self.owner = OwnerState::Terminal;
        self.local = LocalState::Released;
        self.owner_revision += 1;
        self.terminal_observed = true;
        self.capacity_held = false;
        Ok(())
    }

    fn observe_started(&mut self) -> Result<(), ModelError> {
        if self.local != LocalState::EffectEntered || self.physical_provider_sends != 1 {
            return Err(ModelError::InvalidTransition);
        }
        self.local = LocalState::Started;
        Ok(())
    }

    fn observe_terminal(&mut self) -> Result<(), ModelError> {
        if self.local != LocalState::Started || self.physical_provider_sends != 1 {
            return Err(ModelError::TerminalEvidenceRequired);
        }
        self.local = LocalState::TerminalDurable;
        self.owner = OwnerState::Terminal;
        self.owner_revision += 1;
        self.terminal_observed = true;
        self.capacity_held = false;
        Ok(())
    }
}

#[test]
fn all_twenty_two_crash_windows_preserve_global_invariants() {
    assert_eq!(SCENARIOS.len(), 22);
    for scenario in SCENARIOS {
        assert!(scenario.physical_provider_sends <= 1, "{} duplicated effect", scenario.id);
        if scenario.physical_provider_sends == 1 {
            assert!(scenario.fence_may_have_committed, "{} sent before owner fence", scenario.id);
            assert!(scenario.provider_may_have_received);
        }
        if scenario.fence_may_have_committed {
            assert_ne!(scenario.replay, ReplayPosture::FreshAdmission);
        }
        if scenario.local == LocalState::Released {
            assert!(matches!(
                scenario.owner,
                OwnerState::CancelledBeforeEffect | OwnerState::Terminal
            ));
            assert!(!scenario.capacity_held);
        }
        if matches!(
            scenario.local,
            LocalState::Reserved
                | LocalState::Prepared
                | LocalState::FenceUnknown
                | LocalState::EffectEntered
                | LocalState::Started
                | LocalState::TerminalDurable
                | LocalState::Quarantined
        ) && scenario.owner != OwnerState::Terminal
        {
            assert!(scenario.capacity_held, "{} released unresolved capacity", scenario.id);
        }
        if scenario.terminal_observed && scenario.owner == OwnerState::Terminal {
            assert!(matches!(
                scenario.replay,
                ReplayPosture::Closed | ReplayPosture::ReconcileOwner
            ));
        }
    }
}

#[test]
fn fresh_effect_entry_ack_is_the_only_send_permit() {
    let mut winner = Machine::prepared();
    winner
        .commit_effect_entry_fence(2, winner.dispatch_digest, FenceResult::FreshAck)
        .unwrap();
    winner.physical_provider_send().unwrap();
    assert_eq!(winner.physical_provider_sends, 1);
    assert_eq!(
        winner.physical_provider_send(),
        Err(ModelError::MissingFreshFenceAck)
    );

    let mut lost_ack = Machine::prepared();
    lost_ack
        .commit_effect_entry_fence(2, lost_ack.dispatch_digest, FenceResult::LostAck)
        .unwrap();
    assert_eq!(
        lost_ack.physical_provider_send(),
        Err(ModelError::MissingFreshFenceAck)
    );
    lost_ack
        .reconcile_committed_fence(lost_ack.dispatch_digest)
        .unwrap();
    assert_eq!(
        lost_ack.physical_provider_send(),
        Err(ModelError::MissingFreshFenceAck)
    );
    assert_eq!(lost_ack.physical_provider_sends, 0);
}

#[test]
fn abort_is_exact_before_fence_and_impossible_after_fence() {
    let mut before = Machine::prepared();
    let snapshot = before.clone();
    assert_eq!(
        before.abort_before_effect(1, before.dispatch_digest),
        Err(ModelError::StaleRevision)
    );
    assert_eq!(before, snapshot);
    assert_eq!(
        before.abort_before_effect(2, before.dispatch_digest ^ 1),
        Err(ModelError::DigestMismatch)
    );
    assert_eq!(before, snapshot);
    before
        .abort_before_effect(2, before.dispatch_digest)
        .unwrap();
    assert_eq!(before.local, LocalState::Released);
    assert_eq!(before.owner, OwnerState::CancelledBeforeEffect);

    let mut after = Machine::prepared();
    after
        .commit_effect_entry_fence(2, after.dispatch_digest, FenceResult::FreshAck)
        .unwrap();
    assert_eq!(
        after.abort_before_effect(3, after.dispatch_digest),
        Err(ModelError::MissingAbortProof)
    );
    assert!(after.capacity_held);
}

#[test]
fn two_workers_cannot_both_receive_a_send_permit() {
    let mut owner = Machine::prepared();
    owner
        .commit_effect_entry_fence(2, owner.dispatch_digest, FenceResult::FreshAck)
        .unwrap();

    let mut loser_view = owner.clone();
    loser_view.fresh_send_permit = false;
    loser_view.local = LocalState::FenceUnknown;
    loser_view
        .reconcile_committed_fence(owner.dispatch_digest)
        .unwrap();

    owner.physical_provider_send().unwrap();
    assert_eq!(
        loser_view.physical_provider_send(),
        Err(ModelError::MissingFreshFenceAck)
    );
    assert_eq!(owner.physical_provider_sends, 1);
    assert_eq!(loser_view.physical_provider_sends, 0);
}

#[test]
fn typed_pre_admission_rejection_closes_both_owners_without_provider_effect() {
    let mut machine = Machine::prepared();
    machine
        .commit_effect_entry_fence(2, machine.dispatch_digest, FenceResult::FreshAck)
        .unwrap();
    machine.typed_pre_admission_rejection().unwrap();
    assert_eq!(machine.owner, OwnerState::Terminal);
    assert_eq!(machine.local, LocalState::Released);
    assert_eq!(machine.physical_provider_sends, 0);
    assert!(machine.terminal_observed);
    assert!(!machine.capacity_held);
}

#[test]
fn terminal_settlement_is_exactly_once_and_releases_capacity() {
    let mut machine = Machine::prepared();
    machine
        .commit_effect_entry_fence(2, machine.dispatch_digest, FenceResult::FreshAck)
        .unwrap();
    machine.physical_provider_send().unwrap();
    machine.observe_started().unwrap();
    machine.observe_terminal().unwrap();
    assert_eq!(machine.owner, OwnerState::Terminal);
    assert_eq!(machine.local, LocalState::TerminalDurable);
    assert!(machine.terminal_observed);
    assert!(!machine.capacity_held);
    assert_eq!(
        machine.observe_terminal(),
        Err(ModelError::TerminalEvidenceRequired)
    );
}
