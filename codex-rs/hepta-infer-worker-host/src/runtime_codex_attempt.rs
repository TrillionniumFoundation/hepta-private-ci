//! Compile-time state model for one runtime.codex effect attempt.
//!
//! This module is intentionally free of network and persistence I/O. It gives
//! the native caller a closed transition vocabulary while the existing durable
//! owners remain authoritative. In particular, there is no pre-effect abort
//! method after `enter_effect`: once effect entry is possible, recovery is
//! reconcile/quarantine only.

use std::error::Error as StdError;
use std::fmt;
use std::marker::PhantomData;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Admitted;
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PayloadFrozen;
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Authorized;
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DurablePrepared;
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct OwnerCommitted;
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct EffectEntered;
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Started;
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Terminal;
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Quarantined;
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AbortedBeforeEffect;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AttemptIdentity {
    pub operation_id: StableId,
    pub request_digest: Digest32,
    pub payload_digest: Digest32,
    pub deadline_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AttemptError {
    EmptyDigest(&'static str),
    InvalidDeadline,
    PayloadDrift,
    InvalidOwnerRevision,
    OwnerDispatchMismatch,
    InvalidTurnIdentity,
}

impl fmt::Display for AttemptError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for AttemptError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Attempt<State> {
    identity: AttemptIdentity,
    authority_binding_digest: Option<Digest32>,
    dispatch_digest: Option<Digest32>,
    owner_revision: Option<u64>,
    turn_id: Option<StableId>,
    terminal_or_evidence_digest: Option<Digest32>,
    effect_may_have_happened: bool,
    state: PhantomData<State>,
}

impl Attempt<Admitted> {
    pub fn new(identity: AttemptIdentity) -> Result<Self, AttemptError> {
        if identity.request_digest.is_zero() {
            return Err(AttemptError::EmptyDigest("request"));
        }
        if identity.payload_digest.is_zero() {
            return Err(AttemptError::EmptyDigest("payload"));
        }
        if identity.deadline_ms == 0 {
            return Err(AttemptError::InvalidDeadline);
        }
        Ok(Self {
            identity,
            authority_binding_digest: None,
            dispatch_digest: None,
            owner_revision: None,
            turn_id: None,
            terminal_or_evidence_digest: None,
            effect_may_have_happened: false,
            state: PhantomData,
        })
    }

    pub fn freeze_payload(
        self,
        observed_payload_digest: Digest32,
    ) -> Result<Attempt<PayloadFrozen>, AttemptError> {
        if observed_payload_digest != self.identity.payload_digest {
            return Err(AttemptError::PayloadDrift);
        }
        Ok(self.transition())
    }
}

impl Attempt<PayloadFrozen> {
    pub fn authorize(
        mut self,
        authority_binding_digest: Digest32,
    ) -> Result<Attempt<Authorized>, AttemptError> {
        if authority_binding_digest.is_zero() {
            return Err(AttemptError::EmptyDigest("authority binding"));
        }
        self.authority_binding_digest = Some(authority_binding_digest);
        Ok(self.transition())
    }
}

impl Attempt<Authorized> {
    pub fn prepare_durable(
        mut self,
        dispatch_digest: Digest32,
    ) -> Result<Attempt<DurablePrepared>, AttemptError> {
        if dispatch_digest.is_zero() {
            return Err(AttemptError::EmptyDigest("dispatch"));
        }
        self.dispatch_digest = Some(dispatch_digest);
        Ok(self.transition())
    }
}

impl Attempt<DurablePrepared> {
    pub fn commit_owner(
        mut self,
        owner_revision: u64,
        owner_dispatch_digest: Digest32,
    ) -> Result<Attempt<OwnerCommitted>, AttemptError> {
        if owner_revision == 0 {
            return Err(AttemptError::InvalidOwnerRevision);
        }
        if self.dispatch_digest != Some(owner_dispatch_digest) {
            return Err(AttemptError::OwnerDispatchMismatch);
        }
        self.owner_revision = Some(owner_revision);
        Ok(self.transition())
    }
}

impl Attempt<OwnerCommitted> {
    pub fn abort_before_effect(
        mut self,
        reason_digest: Digest32,
    ) -> Result<Attempt<AbortedBeforeEffect>, AttemptError> {
        if reason_digest.is_zero() {
            return Err(AttemptError::EmptyDigest("abort reason"));
        }
        self.terminal_or_evidence_digest = Some(reason_digest);
        Ok(self.transition())
    }

    #[must_use]
    pub fn enter_effect(mut self) -> Attempt<EffectEntered> {
        self.effect_may_have_happened = true;
        self.transition()
    }
}

impl Attempt<EffectEntered> {
    pub fn started(mut self, turn_id: StableId) -> Result<Attempt<Started>, AttemptError> {
        if turn_id.as_str().is_empty() {
            return Err(AttemptError::InvalidTurnIdentity);
        }
        self.turn_id = Some(turn_id);
        Ok(self.transition())
    }

    pub fn quarantine(
        mut self,
        evidence_digest: Digest32,
    ) -> Result<Attempt<Quarantined>, AttemptError> {
        if evidence_digest.is_zero() {
            return Err(AttemptError::EmptyDigest("quarantine evidence"));
        }
        self.terminal_or_evidence_digest = Some(evidence_digest);
        Ok(self.transition())
    }
}

impl Attempt<Started> {
    pub fn terminal(
        mut self,
        response_digest: Digest32,
    ) -> Result<Attempt<Terminal>, AttemptError> {
        if response_digest.is_zero() {
            return Err(AttemptError::EmptyDigest("terminal response"));
        }
        self.terminal_or_evidence_digest = Some(response_digest);
        Ok(self.transition())
    }

    pub fn quarantine(
        mut self,
        evidence_digest: Digest32,
    ) -> Result<Attempt<Quarantined>, AttemptError> {
        if evidence_digest.is_zero() {
            return Err(AttemptError::EmptyDigest("quarantine evidence"));
        }
        self.terminal_or_evidence_digest = Some(evidence_digest);
        Ok(self.transition())
    }
}

impl<State> Attempt<State> {
    #[must_use]
    pub fn identity(&self) -> &AttemptIdentity {
        &self.identity
    }

    #[must_use]
    pub fn dispatch_digest(&self) -> Option<Digest32> {
        self.dispatch_digest
    }

    #[must_use]
    pub fn owner_revision(&self) -> Option<u64> {
        self.owner_revision
    }

    #[must_use]
    pub fn turn_id(&self) -> Option<&StableId> {
        self.turn_id.as_ref()
    }

    #[must_use]
    pub fn effect_may_have_happened(&self) -> bool {
        self.effect_may_have_happened
    }

    fn transition<Next>(self) -> Attempt<Next> {
        Attempt {
            identity: self.identity,
            authority_binding_digest: self.authority_binding_digest,
            dispatch_digest: self.dispatch_digest,
            owner_revision: self.owner_revision,
            turn_id: self.turn_id,
            terminal_or_evidence_digest: self.terminal_or_evidence_digest,
            effect_may_have_happened: self.effect_may_have_happened,
            state: PhantomData,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn identity() -> AttemptIdentity {
        AttemptIdentity {
            operation_id: StableId::new("runtime-codex-attempt").unwrap(),
            request_digest: Digest32::of_bytes(b"request"),
            payload_digest: Digest32::of_bytes(b"payload"),
            deadline_ms: 10_000,
        }
    }

    #[test]
    fn exact_typestate_path_binds_owner_and_terminal_identity() {
        let payload = identity().payload_digest;
        let dispatch = Digest32::of_bytes(b"dispatch");
        let attempt = Attempt::new(identity())
            .unwrap()
            .freeze_payload(payload)
            .unwrap()
            .authorize(Digest32::of_bytes(b"authority"))
            .unwrap()
            .prepare_durable(dispatch)
            .unwrap()
            .commit_owner(7, dispatch)
            .unwrap();
        assert!(!attempt.effect_may_have_happened());
        let entered = attempt.enter_effect();
        assert!(entered.effect_may_have_happened());
        let terminal = entered
            .started(StableId::new("turn-1").unwrap())
            .unwrap()
            .terminal(Digest32::of_bytes(b"terminal"))
            .unwrap();
        assert_eq!(terminal.owner_revision(), Some(7));
        assert_eq!(terminal.turn_id().unwrap().as_str(), "turn-1");
    }

    #[test]
    fn owner_dispatch_drift_is_rejected_before_effect_entry() {
        let payload = identity().payload_digest;
        let attempt = Attempt::new(identity())
            .unwrap()
            .freeze_payload(payload)
            .unwrap()
            .authorize(Digest32::of_bytes(b"authority"))
            .unwrap()
            .prepare_durable(Digest32::of_bytes(b"dispatch-a"))
            .unwrap();
        assert_eq!(
            attempt.commit_owner(2, Digest32::of_bytes(b"dispatch-b")),
            Err(AttemptError::OwnerDispatchMismatch)
        );
    }

    #[test]
    fn pre_effect_abort_remains_definitively_unsent() {
        let payload = identity().payload_digest;
        let dispatch = Digest32::of_bytes(b"dispatch");
        let aborted = Attempt::new(identity())
            .unwrap()
            .freeze_payload(payload)
            .unwrap()
            .authorize(Digest32::of_bytes(b"authority"))
            .unwrap()
            .prepare_durable(dispatch)
            .unwrap()
            .commit_owner(2, dispatch)
            .unwrap()
            .abort_before_effect(Digest32::of_bytes(b"cancelled"))
            .unwrap();
        assert!(!aborted.effect_may_have_happened());
    }

    #[test]
    fn unknown_after_entry_is_quarantined_not_aborted() {
        let payload = identity().payload_digest;
        let dispatch = Digest32::of_bytes(b"dispatch");
        let quarantined = Attempt::new(identity())
            .unwrap()
            .freeze_payload(payload)
            .unwrap()
            .authorize(Digest32::of_bytes(b"authority"))
            .unwrap()
            .prepare_durable(dispatch)
            .unwrap()
            .commit_owner(2, dispatch)
            .unwrap()
            .enter_effect()
            .quarantine(Digest32::of_bytes(b"transport-unknown"))
            .unwrap();
        assert!(quarantined.effect_may_have_happened());
        assert!(quarantined.turn_id().is_none());
    }
}
