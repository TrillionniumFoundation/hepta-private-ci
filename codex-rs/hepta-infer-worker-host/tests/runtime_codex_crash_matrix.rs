//! Executable recovery model for the runtime.codex crash-injection matrix.
//!
//! These tests do not replace process-level fault injection. They make the
//! transition and replay invariants closed-world and executable for every
//! documented persistence, owner-RPC, and socket-write boundary.

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum LocalState {
    Empty,
    Reserved,
    Prepared,
    EffectEntered,
    Started,
    Terminal,
    Released,
    Quarantined,
    Fenced,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum OwnerState {
    Empty,
    ContextAttached,
    Dispatched,
    CancelledBeforeEffect,
    Terminal,
    Indeterminate,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ReplayPosture {
    FreshAdmission,
    NoProviderQuestion,
    ReconcileSameOperation,
    Closed,
    RejectConflict,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ModelError {
    InvalidTransition,
    DigestMismatch,
    StaleRevision,
    AlreadyOwned,
    DuplicatePhysicalSend,
    MissingAbortProof,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct Scenario {
    id: &'static str,
    local: LocalState,
    owner: OwnerState,
    effect_may_have_happened: bool,
    physical_sends: u8,
    provider_terminal_observed: bool,
    capacity_held: bool,
    replay: ReplayPosture,
}

const SCENARIOS: [Scenario; 22] = [
    Scenario {
        id: "RCX-CRASH-01",
        local: LocalState::Empty,
        owner: OwnerState::Empty,
        effect_may_have_happened: false,
        physical_sends: 0,
        provider_terminal_observed: false,
        capacity_held: false,
        replay: ReplayPosture::FreshAdmission,
    },
    Scenario {
        id: "RCX-CRASH-02",
        local: LocalState::Reserved,
        owner: OwnerState::ContextAttached,
        effect_may_have_happened: false,
        physical_sends: 0,
        provider_terminal_observed: false,
        capacity_held: true,
        replay: ReplayPosture::NoProviderQuestion,
    },
    Scenario {
        id: "RCX-CRASH-03",
        local: LocalState::Fenced,
        owner: OwnerState::ContextAttached,
        effect_may_have_happened: false,
        physical_sends: 0,
        provider_terminal_observed: false,
        capacity_held: true,
        replay: ReplayPosture::ReconcileSameOperation,
    },
    Scenario {
        id: "RCX-CRASH-04",
        local: LocalState::Prepared,
        owner: OwnerState::ContextAttached,
        effect_may_have_happened: false,
        physical_sends: 0,
        provider_terminal_observed: false,
        capacity_held: true,
        replay: ReplayPosture::ReconcileSameOperation,
    },
    Scenario {
        id: "RCX-CRASH-05",
        local: LocalState::Prepared,
        owner: OwnerState::Dispatched,
        effect_may_have_happened: false,
        physical_sends: 0,
        provider_terminal_observed: false,
        capacity_held: true,
        replay: ReplayPosture::ReconcileSameOperation,
    },
    Scenario {
        id: "RCX-CRASH-06",
        local: LocalState::Prepared,
        owner: OwnerState::Dispatched,
        effect_may_have_happened: false,
        physical_sends: 0,
        provider_terminal_observed: false,
        capacity_held: true,
        replay: ReplayPosture::ReconcileSameOperation,
    },
    Scenario {
        id: "RCX-CRASH-07",
        local: LocalState::Released,
        owner: OwnerState::CancelledBeforeEffect,
        effect_may_have_happened: false,
        physical_sends: 0,
        provider_terminal_observed: false,
        capacity_held: false,
        replay: ReplayPosture::Closed,
    },
    Scenario {
        id: "RCX-CRASH-08",
        local: LocalState::Released,
        owner: OwnerState::CancelledBeforeEffect,
        effect_may_have_happened: false,
        physical_sends: 0,
        provider_terminal_observed: false,
        capacity_held: false,
        replay: ReplayPosture::Closed,
    },
    Scenario {
        id: "RCX-CRASH-09",
        local: LocalState::Released,
        owner: OwnerState::CancelledBeforeEffect,
        effect_may_have_happened: false,
        physical_sends: 0,
        provider_terminal_observed: false,
        capacity_held: false,
        replay: ReplayPosture::Closed,
    },
    Scenario {
        id: "RCX-CRASH-10",
        local: LocalState::Released,
        owner: OwnerState::CancelledBeforeEffect,
        effect_may_have_happened: false,
        physical_sends: 0,
        provider_terminal_observed: false,
        capacity_held: false,
        replay: ReplayPosture::Closed,
    },
    Scenario {
        id: "RCX-CRASH-11",
        local: LocalState::EffectEntered,
        owner: OwnerState::Dispatched,
        effect_may_have_happened: true,
        physical_sends: 0,
        provider_terminal_observed: false,
        capacity_held: true,
        replay: ReplayPosture::ReconcileSameOperation,
    },
    Scenario {
        id: "RCX-CRASH-12",
        local: LocalState::EffectEntered,
        owner: OwnerState::Dispatched,
        effect_may_have_happened: true,
        physical_sends: 1,
        provider_terminal_observed: false,
        capacity_held: true,
        replay: ReplayPosture::ReconcileSameOperation,
    },
    Scenario {
        id: "RCX-CRASH-13",
        local: LocalState::EffectEntered,
        owner: OwnerState::Dispatched,
        effect_may_have_happened: true,
        physical_sends: 1,
        provider_terminal_observed: false,
        capacity_held: true,
        replay: ReplayPosture::ReconcileSameOperation,
    },
    Scenario {
        id: "RCX-CRASH-14",
        local: LocalState::Fenced,
        owner: OwnerState::Dispatched,
        effect_may_have_happened: true,
        physical_sends: 1,
        provider_terminal_observed: false,
        capacity_held: true,
        replay: ReplayPosture::ReconcileSameOperation,
    },
    Scenario {
        id: "RCX-CRASH-15",
        local: LocalState::Started,
        owner: OwnerState::Dispatched,
        effect_may_have_happened: true,
        physical_sends: 1,
        provider_terminal_observed: false,
        capacity_held: true,
        replay: ReplayPosture::ReconcileSameOperation,
    },
    Scenario {
        id: "RCX-CRASH-16",
        local: LocalState::Fenced,
        owner: OwnerState::Dispatched,
        effect_may_have_happened: true,
        physical_sends: 1,
        provider_terminal_observed: true,
        capacity_held: true,
        replay: ReplayPosture::ReconcileSameOperation,
    },
    Scenario {
        id: "RCX-CRASH-17",
        local: LocalState::Terminal,
        owner: OwnerState::Dispatched,
        effect_may_have_happened: true,
        physical_sends: 1,
        provider_terminal_observed: true,
        capacity_held: true,
        replay: ReplayPosture::ReconcileSameOperation,
    },
    Scenario {
        id: "RCX-CRASH-18",
        local: LocalState::Quarantined,
        owner: OwnerState::Indeterminate,
        effect_may_have_happened: true,
        physical_sends: 1,
        provider_terminal_observed: true,
        capacity_held: true,
        replay: ReplayPosture::ReconcileSameOperation,
    },
    Scenario {
        id: "RCX-CRASH-19",
        local: LocalState::Quarantined,
        owner: OwnerState::Indeterminate,
        effect_may_have_happened: true,
        physical_sends: 1,
        provider_terminal_observed: false,
        capacity_held: true,
        replay: ReplayPosture::ReconcileSameOperation,
    },
    Scenario {
        id: "RCX-CRASH-20",
        local: LocalState::EffectEntered,
        owner: OwnerState::Dispatched,
        effect_may_have_happened: true,
        physical_sends: 1,
        provider_terminal_observed: false,
        capacity_held: true,
        replay: ReplayPosture::ReconcileSameOperation,
    },
    Scenario {
        id: "RCX-CRASH-21",
        local: LocalState::Prepared,
        owner: OwnerState::Dispatched,
        effect_may_have_happened: false,
        physical_sends: 0,
        provider_terminal_observed: false,
        capacity_held: true,
        replay: ReplayPosture::ReconcileSameOperation,
    },
    Scenario {
        id: "RCX-CRASH-22",
        local: LocalState::Prepared,
        owner: OwnerState::Dispatched,
        effect_may_have_happened: false,
        physical_sends: 0,
        provider_terminal_observed: false,
        capacity_held: true,
        replay: ReplayPosture::RejectConflict,
    },
];

#[derive(Clone, Debug, Eq, PartialEq)]
struct Machine {
    local: LocalState,
    owner: OwnerState,
    digest: u64,
    owner_digest: Option<u64>,
    owner_revision: u64,
    abort_proof: bool,
    effect_may_have_happened: bool,
    physical_sends: u8,
    provider_terminal_observed: bool,
    capacity_held: bool,
}

impl Machine {
    fn dispatched() -> Self {
        Self {
            local: LocalState::Prepared,
            owner: OwnerState::Dispatched,
            digest: 0x5a17_d15c,
            owner_digest: Some(0x5a17_d15c),
            owner_revision: 3,
            abort_proof: true,
            effect_may_have_happened: false,
            physical_sends: 0,
            provider_terminal_observed: false,
            capacity_held: true,
        }
    }

    fn mark_dispatched(
        &mut self,
        expected_revision: u64,
        digest: u64,
    ) -> Result<(), ModelError> {
        if expected_revision != self.owner_revision {
            return Err(ModelError::StaleRevision);
        }
        if digest != self.digest {
            return Err(ModelError::DigestMismatch);
        }
        if self.owner == OwnerState::Dispatched && self.owner_digest == Some(digest) {
            return Err(ModelError::AlreadyOwned);
        }
        Err(ModelError::InvalidTransition)
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
        if digest != self.digest || self.owner_digest != Some(digest) {
            return Err(ModelError::DigestMismatch);
        }
        if self.local != LocalState::Prepared || self.owner != OwnerState::Dispatched {
            return Err(ModelError::InvalidTransition);
        }
        self.local = LocalState::Released;
        self.owner = OwnerState::CancelledBeforeEffect;
        self.owner_revision += 1;
        self.abort_proof = false;
        self.capacity_held = false;
        Ok(())
    }

    fn enter_effect(&mut self) -> Result<(), ModelError> {
        if self.local != LocalState::Prepared
            || self.owner != OwnerState::Dispatched
            || self.owner_digest != Some(self.digest)
        {
            return Err(ModelError::InvalidTransition);
        }
        self.local = LocalState::EffectEntered;
        self.abort_proof = false;
        self.effect_may_have_happened = true;
        Ok(())
    }

    fn physical_send(&mut self) -> Result<(), ModelError> {
        if self.local != LocalState::EffectEntered {
            return Err(ModelError::InvalidTransition);
        }
        if self.physical_sends != 0 {
            return Err(ModelError::DuplicatePhysicalSend);
        }
        self.physical_sends = 1;
        Ok(())
    }

    fn observe_started(&mut self) -> Result<(), ModelError> {
        if self.local != LocalState::EffectEntered || self.physical_sends != 1 {
            return Err(ModelError::InvalidTransition);
        }
        self.local = LocalState::Started;
        Ok(())
    }

    fn observe_terminal(&mut self) -> Result<(), ModelError> {
        if self.local != LocalState::Started || self.physical_sends != 1 {
            return Err(ModelError::InvalidTransition);
        }
        self.local = LocalState::Terminal;
        self.owner = OwnerState::Terminal;
        self.owner_revision += 1;
        self.provider_terminal_observed = true;
        self.capacity_held = false;
        Ok(())
    }
}

#[test]
fn all_twenty_two_crash_windows_preserve_global_invariants() {
    assert_eq!(SCENARIOS.len(), 22);
    for scenario in SCENARIOS {
        assert!(scenario.physical_sends <= 1, "{} duplicated effect", scenario.id);
        if scenario.effect_may_have_happened {
            assert!(!matches!(
                scenario.replay,
                ReplayPosture::FreshAdmission | ReplayPosture::NoProviderQuestion
            ));
        }
        if scenario.local == LocalState::Released {
            assert_eq!(scenario.owner, OwnerState::CancelledBeforeEffect);
            assert!(!scenario.effect_may_have_happened);
            assert_eq!(scenario.physical_sends, 0);
            assert!(!scenario.capacity_held);
        }
        if matches!(
            scenario.local,
            LocalState::Prepared
                | LocalState::EffectEntered
                | LocalState::Started
                | LocalState::Quarantined
                | LocalState::Fenced
        ) {
            assert!(scenario.capacity_held, "{} released unresolved capacity", scenario.id);
        }
        if scenario.local == LocalState::Terminal {
            assert!(scenario.provider_terminal_observed);
            if scenario.owner != OwnerState::Terminal {
                assert!(scenario.capacity_held);
            }
        }
        if scenario.replay == ReplayPosture::RejectConflict {
            assert_eq!(scenario.id, "RCX-CRASH-22");
        }
    }
}

#[test]
fn exact_cross_owner_abort_is_atomic_and_digest_bound() {
    let mut machine = Machine::dispatched();
    let before = machine.clone();
    assert_eq!(
        machine.abort_before_effect(machine.owner_revision, machine.digest ^ 1),
        Err(ModelError::DigestMismatch)
    );
    assert_eq!(machine, before);

    let revision = machine.owner_revision;
    machine
        .abort_before_effect(revision, machine.digest)
        .unwrap();
    assert_eq!(machine.local, LocalState::Released);
    assert_eq!(machine.owner, OwnerState::CancelledBeforeEffect);
    assert!(!machine.capacity_held);
    assert!(!machine.effect_may_have_happened);
}

#[test]
fn duplicate_owner_stale_revision_and_semantic_drift_do_not_mutate_state() {
    let mut machine = Machine::dispatched();
    let before = machine.clone();
    assert_eq!(
        machine.mark_dispatched(machine.owner_revision, machine.digest),
        Err(ModelError::AlreadyOwned)
    );
    assert_eq!(machine, before);
    assert_eq!(
        machine.abort_before_effect(machine.owner_revision - 1, machine.digest),
        Err(ModelError::StaleRevision)
    );
    assert_eq!(machine, before);
    assert_eq!(
        machine.abort_before_effect(machine.owner_revision, 0xbad0_d1ce),
        Err(ModelError::DigestMismatch)
    );
    assert_eq!(machine, before);
}

#[test]
fn effect_entry_destroys_abort_authority_and_allows_one_send_only() {
    let mut machine = Machine::dispatched();
    machine.enter_effect().unwrap();
    assert_eq!(
        machine.abort_before_effect(machine.owner_revision, machine.digest),
        Err(ModelError::MissingAbortProof)
    );
    machine.physical_send().unwrap();
    assert_eq!(
        machine.physical_send(),
        Err(ModelError::DuplicatePhysicalSend)
    );
    machine.observe_started().unwrap();
    machine.observe_terminal().unwrap();
    assert_eq!(machine.local, LocalState::Terminal);
    assert_eq!(machine.owner, OwnerState::Terminal);
    assert!(machine.provider_terminal_observed);
    assert!(!machine.capacity_held);
}
