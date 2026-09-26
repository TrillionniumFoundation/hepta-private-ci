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
    Admitted,
    ContextAttached,
    Dispatched,
    CancelledBeforeEffect,
    Cancelling,
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
enum CrashPoint {
    BeforeAdmission,
    AfterAdmissionBeforePrepare,
    DuringDispatchPersistence,
    PreparedBeforeOwnerRpc,
    OwnerRpcRequestAckLost,
    OwnerCommitResponseLost,
    OwnerFenceFailureBeforeEffect,
    CognitiveRevalidationFailure,
    CancellationOrDeadlineBeforeEntry,
    RevocationAdvanceBeforeEntry,
    AfterTokenEntryBeforeWrite,
    PartialSocketWrite,
    FullWriteAckLost,
    StartedPersistenceFailure,
    ProcessDeathAfterStart,
    TerminalSettlementFailure,
    OwnerTerminalAckLost,
    OwnerLossConcurrentWithTerminal,
    HistoryUnavailableAfterLoss,
    DuplicateOwnerRace,
    StaleRevisionMutation,
    SemanticIdentityConflict,
}

const ALL_CRASH_POINTS: [CrashPoint; 22] = [
    CrashPoint::BeforeAdmission,
    CrashPoint::AfterAdmissionBeforePrepare,
    CrashPoint::DuringDispatchPersistence,
    CrashPoint::PreparedBeforeOwnerRpc,
    CrashPoint::OwnerRpcRequestAckLost,
    CrashPoint::OwnerCommitResponseLost,
    CrashPoint::OwnerFenceFailureBeforeEffect,
    CrashPoint::CognitiveRevalidationFailure,
    CrashPoint::CancellationOrDeadlineBeforeEntry,
    CrashPoint::RevocationAdvanceBeforeEntry,
    CrashPoint::AfterTokenEntryBeforeWrite,
    CrashPoint::PartialSocketWrite,
    CrashPoint::FullWriteAckLost,
    CrashPoint::StartedPersistenceFailure,
    CrashPoint::ProcessDeathAfterStart,
    CrashPoint::TerminalSettlementFailure,
    CrashPoint::OwnerTerminalAckLost,
    CrashPoint::OwnerLossConcurrentWithTerminal,
    CrashPoint::HistoryUnavailableAfterLoss,
    CrashPoint::DuplicateOwnerRace,
    CrashPoint::StaleRevisionMutation,
    CrashPoint::SemanticIdentityConflict,
];

#[derive(Clone, Debug, Eq, PartialEq)]
struct Machine {
    local: LocalState,
    owner: OwnerState,
    operation_digest: u64,
    owner_dispatch_digest: Option<u64>,
    owner_revision: u64,
    abort_proof: bool,
    effect_may_have_happened: bool,
    physical_sends: u8,
    provider_terminal_observed: bool,
    capacity_held: bool,
    conflict: bool,
}

impl Default for Machine {
    fn default() -> Self {
        Self {
            local: LocalState::Empty,
            owner: OwnerState::Empty,
            operation_digest: 0x5a17_d15c,
            owner_dispatch_digest: None,
            owner_revision: 0,
            abort_proof: false,
            effect_may_have_happened: false,
            physical_sends: 0,
            provider_terminal_observed: false,
            capacity_held: false,
            conflict: false,
        }
    }
}

impl Machine {
    fn admit(&mut self) -> Result<(), ModelError> {
        if self.local != LocalState::Empty || self.owner != OwnerState::Empty {
            return Err(ModelError::InvalidTransition);
        }
        self.local = LocalState::Reserved;
        self.owner = OwnerState::Admitted;
        self.owner_revision = 1;
        self.capacity_held = true;
        Ok(())
    }

    fn attach_context(&mut self) -> Result<(), ModelError> {
        if self.local != LocalState::Reserved || self.owner != OwnerState::Admitted {
            return Err(ModelError::InvalidTransition);
        }
        self.owner = OwnerState::ContextAttached;
        self.owner_revision += 1;
        Ok(())
    }

    fn prepare_dispatch(&mut self) -> Result<(), ModelError> {
        if self.local != LocalState::Reserved || self.owner != OwnerState::ContextAttached {
            return Err(ModelError::InvalidTransition);
        }
        self.local = LocalState::Prepared;
        self.abort_proof = true;
        Ok(())
    }

    fn commit_owner_dispatch(
        &mut self,
        expected_revision: u64,
        dispatch_digest: u64,
    ) -> Result<(), ModelError> {
        if expected_revision != self.owner_revision {
            return Err(ModelError::StaleRevision);
        }
        if dispatch_digest != self.operation_digest {
            return Err(ModelError::DigestMismatch);
        }
        match self.owner {
            OwnerState::ContextAttached => {
                self.owner = OwnerState::Dispatched;
                self.owner_dispatch_digest = Some(dispatch_digest);
                self.owner_revision += 1;
                Ok(())
            }
            OwnerState::Dispatched if self.owner_dispatch_digest == Some(dispatch_digest) => {
                Err(ModelError::AlreadyOwned)
            }
            OwnerState::Dispatched => Err(ModelError::DigestMismatch),
            _ => Err(ModelError::InvalidTransition),
        }
    }

    fn abort_before_effect(
        &mut self,
        expected_owner_revision: u64,
        dispatch_digest: u64,
    ) -> Result<(), ModelError> {
        if !self.abort_proof {
            return Err(ModelError::MissingAbortProof);
        }
        if expected_owner_revision != self.owner_revision {
            return Err(ModelError::StaleRevision);
        }
        if self.owner_dispatch_digest != Some(dispatch_digest)
            || dispatch_digest != self.operation_digest
        {
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
            || self.owner_dispatch_digest != Some(self.operation_digest)
        {
            return Err(ModelError::InvalidTransition);
        }
        self.abort_proof = false;
        self.effect_may_have_happened = true;
        self.local = LocalState::EffectEntered;
        Ok(())
    }

    fn physical_send(&mut self) -> Result<(), ModelError> {
        if self.local != LocalState::EffectEntered || !self.effect_may_have_happened {
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
        if !matches!(self.local, LocalState::EffectEntered | LocalState::Started)
            || self.physical_sends != 1
        {
            return Err(ModelError::InvalidTransition);
        }
        self.provider_terminal_observed = true;
        self.local = LocalState::Terminal;
        self.owner = OwnerState::Terminal;
        self.owner_revision += 1;
        self.capacity_held = false;
        Ok(())
    }

    fn quarantine(&mut self) {
        self.local = LocalState::Quarantined;
        self.owner = OwnerState::Indeterminate;
        self.abort_proof = false;
        self.capacity_held = true;
    }

    fn process_reopen(&mut self) {
        self.abort_proof = false;
        if matches!(
            self.local,
            LocalState::Prepared | LocalState::EffectEntered | LocalState::Started | LocalState::Fenced
        ) {
            self.capacity_held = true;
        }
    }

    fn replay_posture(&self) -> ReplayPosture {
        if self.conflict {
            return ReplayPosture::RejectConflict;
        }
        if self.local == LocalState::Empty && self.owner == OwnerState::Empty {
            return ReplayPosture::FreshAdmission;
        }
        if self.local == LocalState::Released
            && self.owner == OwnerState::CancelledBeforeEffect
        {
            return ReplayPosture::Closed;
        }
        if self.local == LocalState::Terminal && self.owner == OwnerState::Terminal {
            return ReplayPosture::Closed;
        }
        if self.effect_may_have_happened
            || self.owner == OwnerState::Dispatched
            || matches!(
                self.local,
                LocalState::Prepared
                    | LocalState::EffectEntered
                    | LocalState::Started
                    | LocalState::Quarantined
                    | LocalState::Fenced
            )
        {
            return ReplayPosture::ReconcileSameOperation;
        }
        ReplayPosture::NoProviderQuestion
    }

    fn assert_global_invariants(&self) {
        assert!(self.physical_sends <= 1, "duplicate physical effect: {self:?}");
        if self.local == LocalState::Released {
            assert_eq!(self.owner, OwnerState::CancelledBeforeEffect);
            assert!(!self.effect_may_have_happened);
            assert_eq!(self.physical_sends, 0);
            assert!(!self.capacity_held);
        }
        if self.effect_may_have_happened {
            assert!(!self.abort_proof);
            assert_ne!(self.replay_posture(), ReplayPosture::FreshAdmission);
            assert_ne!(self.replay_posture(), ReplayPosture::NoProviderQuestion);
        }
        if matches!(
            self.local,
            LocalState::Prepared
                | LocalState::EffectEntered
                | LocalState::Started
                | LocalState::Quarantined
                | LocalState::Fenced
        ) {
            assert!(self.capacity_held);
        }
        if self.local == LocalState::Terminal {
            assert!(self.provider_terminal_observed);
            assert!(!self.capacity_held);
        }
    }
}

fn prepared_machine() -> Machine {
    let mut machine = Machine::default();
    machine.admit().unwrap();
    machine.attach_context().unwrap();
    machine.prepare_dispatch().unwrap();
    machine
}

fn dispatched_machine() -> Machine {
    let mut machine = prepared_machine();
    let revision = machine.owner_revision;
    machine
        .commit_owner_dispatch(revision, machine.operation_digest)
        .unwrap();
    machine
}

fn entered_machine(send: bool) -> Machine {
    let mut machine = dispatched_machine();
    machine.enter_effect().unwrap();
    if send {
        machine.physical_send().unwrap();
    }
    machine
}

fn simulate(point: CrashPoint) -> Machine {
    match point {
        CrashPoint::BeforeAdmission => Machine::default(),
        CrashPoint::AfterAdmissionBeforePrepare => {
            let mut machine = Machine::default();
            machine.admit().unwrap();
            machine.attach_context().unwrap();
            machine
        }
        CrashPoint::DuringDispatchPersistence => {
            let mut machine = Machine::default();
            machine.admit().unwrap();
            machine.attach_context().unwrap();
            machine.local = LocalState::Fenced;
            machine.process_reopen();
            machine
        }
        CrashPoint::PreparedBeforeOwnerRpc => {
            let mut machine = prepared_machine();
            machine.process_reopen();
            machine
        }
        CrashPoint::OwnerRpcRequestAckLost | CrashPoint::OwnerCommitResponseLost => {
            let mut machine = dispatched_machine();
            machine.process_reopen();
            machine
        }
        CrashPoint::OwnerFenceFailureBeforeEffect
        | CrashPoint::CognitiveRevalidationFailure
        | CrashPoint::CancellationOrDeadlineBeforeEntry
        | CrashPoint::RevocationAdvanceBeforeEntry => {
            let mut machine = dispatched_machine();
            let revision = machine.owner_revision;
            machine
                .abort_before_effect(revision, machine.operation_digest)
                .unwrap();
            machine
        }
        CrashPoint::AfterTokenEntryBeforeWrite => {
            let mut machine = entered_machine(false);
            machine.process_reopen();
            machine
        }
        CrashPoint::PartialSocketWrite | CrashPoint::FullWriteAckLost => {
            let mut machine = entered_machine(true);
            machine.process_reopen();
            machine
        }
        CrashPoint::StartedPersistenceFailure => {
            let mut machine = entered_machine(true);
            machine.local = LocalState::Fenced;
            machine.process_reopen();
            machine
        }
        CrashPoint::ProcessDeathAfterStart => {
            let mut machine = entered_machine(true);
            machine.observe_started().unwrap();
            machine.process_reopen();
            machine
        }
        CrashPoint::TerminalSettlementFailure => {
            let mut machine = entered_machine(true);
            machine.provider_terminal_observed = true;
            machine.local = LocalState::Fenced;
            machine.process_reopen();
            machine
        }
        CrashPoint::OwnerTerminalAckLost => {
            let mut machine = entered_machine(true);
            machine.observe_started().unwrap();
            machine.provider_terminal_observed = true;
            machine.local = LocalState::Terminal;
            machine.owner = OwnerState::Dispatched;
            machine.capacity_held = true;
            machine
        }
        CrashPoint::OwnerLossConcurrentWithTerminal => {
            let mut machine = entered_machine(true);
            machine.provider_terminal_observed = true;
            machine.quarantine();
            machine
        }
        CrashPoint::HistoryUnavailableAfterLoss => {
            let mut machine = entered_machine(true);
            machine.quarantine();
            machine.process_reopen();
            machine
        }
        CrashPoint::DuplicateOwnerRace => {
            let mut winner = dispatched_machine();
            let revision = winner.owner_revision;
            assert_eq!(
                winner.commit_owner_dispatch(revision, winner.operation_digest),
                Err(ModelError::AlreadyOwned)
            );
            winner.enter_effect().unwrap();
            winner.physical_send().unwrap();
            winner
        }
        CrashPoint::StaleRevisionMutation => {
            let mut machine = dispatched_machine();
            let before = machine.clone();
            assert_eq!(
                machine.abort_before_effect(
                    machine.owner_revision.saturating_sub(1),
                    machine.operation_digest,
                ),
                Err(ModelError::StaleRevision)
            );
            assert_eq!(machine, before);
            machine
        }
        CrashPoint::SemanticIdentityConflict => {
            let mut machine = dispatched_machine();
            let before = machine.clone();
            assert_eq!(
                machine.commit_owner_dispatch(machine.owner_revision, 0xbad0_d1ce),
                Err(ModelError::DigestMismatch)
            );
            assert_eq!(machine, before);
            machine.conflict = true;
            machine
        }
    }
}

#[test]
fn all_twenty_two_crash_windows_preserve_global_invariants() {
    for point in ALL_CRASH_POINTS {
        let machine = simulate(point);
        machine.assert_global_invariants();
    }
}

#[test]
fn only_exact_cross_owner_abort_can_release_pre_effect_capacity() {
    let mut machine = dispatched_machine();
    let before = machine.clone();
    assert_eq!(
        machine.abort_before_effect(machine.owner_revision, machine.operation_digest ^ 1),
        Err(ModelError::DigestMismatch)
    );
    assert_eq!(machine, before);

    let revision = machine.owner_revision;
    machine
        .abort_before_effect(revision, machine.operation_digest)
        .unwrap();
    machine.assert_global_invariants();
    assert_eq!(machine.replay_posture(), ReplayPosture::Closed);
}

#[test]
fn effect_entry_destroys_abort_authority_and_reopen_never_replays() {
    let mut machine = entered_machine(true);
    assert_eq!(machine.abort_before_effect(machine.owner_revision, machine.operation_digest), Err(ModelError::MissingAbortProof));
    machine.process_reopen();
    assert_eq!(machine.replay_posture(), ReplayPosture::ReconcileSameOperation);
    assert_eq!(machine.physical_send(), Err(ModelError::DuplicatePhysicalSend));
    machine.assert_global_invariants();
}

#[test]
fn terminal_and_quarantine_capacity_semantics_are_distinct() {
    let mut terminal = entered_machine(true);
    terminal.observe_started().unwrap();
    terminal.observe_terminal().unwrap();
    terminal.assert_global_invariants();
    assert_eq!(terminal.replay_posture(), ReplayPosture::Closed);

    let quarantine = simulate(CrashPoint::HistoryUnavailableAfterLoss);
    quarantine.assert_global_invariants();
    assert!(quarantine.capacity_held);
    assert_eq!(quarantine.replay_posture(), ReplayPosture::ReconcileSameOperation);
}
