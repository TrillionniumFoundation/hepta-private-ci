//! Predecessor-bound artifact lifecycle journal.
//!
//! The stable transition validator remains available. This additive journal
//! checks current state, expected head, event identity, actor role and replay
//! integrity before publishing a deny-all receipt. Actor evidence is supplied
//! only after host authentication; this source type does not verify signatures.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ArtifactClosureError;
use crate::ArtifactLifecycleEventV1;
use crate::ArtifactLifecycleStateV1;
use crate::validate_artifact_lifecycle_transition;

const MAX_LIFECYCLE_RECORDS: usize = crate::MAX_DURABLE_RECORDS;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LifecycleActorRoleV2 {
    Producer,
    Evaluator,
    ShadowOperator,
    CanaryOperator,
    HumanOperator,
    Selector,
    QuarantineAuthority,
    RevocationAuthority,
    RetirementAuthority,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LifecycleActorEvidenceV2 {
    pub actor_id: StableId,
    pub credential_digest: Digest32,
    pub role: LifecycleActorRoleV2,
    pub authority_epoch: u64,
    pub verified_at: u64,
    pub expires_at: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LifecycleAppendDispositionV2 {
    Appended,
    IdempotentReplay,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactLifecycleJournalRecordV2 {
    pub sequence: u64,
    pub predecessor_head_digest: Digest32,
    pub event_digest: Digest32,
    pub chain_digest: Digest32,
    pub producer_id: StableId,
    pub actor: LifecycleActorEvidenceV2,
    pub event: ArtifactLifecycleEventV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactLifecycleJournalSnapshotV2 {
    pub records: Vec<ArtifactLifecycleJournalRecordV2>,
    pub head_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactLifecycleJournalReceiptV2 {
    pub disposition: LifecycleAppendDispositionV2,
    pub sequence: u64,
    pub event_digest: Digest32,
    pub head_digest: Digest32,
    pub state: ArtifactLifecycleStateV1,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug)]
pub struct ArtifactLifecycleJournalV2 {
    records: Vec<ArtifactLifecycleJournalRecordV2>,
    states: BTreeMap<StableId, ArtifactLifecycleStateV1>,
    event_digests: BTreeMap<StableId, Digest32>,
    head_digest: Digest32,
}

impl Default for ArtifactLifecycleJournalV2 {
    fn default() -> Self {
        Self {
            records: Vec::new(),
            states: BTreeMap::new(),
            event_digests: BTreeMap::new(),
            head_digest: Digest32::ZERO,
        }
    }
}

impl ArtifactLifecycleJournalV2 {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    #[must_use]
    pub fn head_digest(&self) -> Digest32 {
        self.head_digest
    }

    #[must_use]
    pub fn records(&self) -> &[ArtifactLifecycleJournalRecordV2] {
        &self.records
    }

    pub fn append(
        &mut self,
        expected_head_digest: Digest32,
        producer_id: &StableId,
        actor: LifecycleActorEvidenceV2,
        event: ArtifactLifecycleEventV1,
        now: u64,
    ) -> Result<ArtifactLifecycleJournalReceiptV2, ArtifactLifecycleJournalError> {
        if expected_head_digest != self.head_digest {
            return Err(ArtifactLifecycleJournalError::HeadMismatch);
        }
        validate_actor_current(&actor, now)?;
        validate_actor_event_binding(&actor, &event)?;
        if event.occurred_at > now {
            return Err(ArtifactLifecycleJournalError::EventTimeWindow);
        }
        let event_digest = validate_artifact_lifecycle_transition(producer_id, &event)?;
        if let Some(existing_digest) = self.event_digests.get(&event.event_id) {
            if *existing_digest != event_digest {
                return Err(ArtifactLifecycleJournalError::EventIdentityConflict);
            }
            let existing = self
                .records
                .iter()
                .find(|record| record.event.event_id == event.event_id)
                .ok_or(ArtifactLifecycleJournalError::InternalInvariant)?;
            return Ok(ArtifactLifecycleJournalReceiptV2 {
                disposition: LifecycleAppendDispositionV2::IdempotentReplay,
                sequence: existing.sequence,
                event_digest,
                head_digest: self.head_digest,
                state: existing.event.next_state,
                authority: AuthorityPosture::DENY_ALL,
            });
        }
        if self.records.len() >= MAX_LIFECYCLE_RECORDS {
            return Err(ArtifactLifecycleJournalError::RecordLimit);
        }
        let current = self
            .states
            .get(&event.artifact_id)
            .copied()
            .unwrap_or(ArtifactLifecycleStateV1::Proposed);
        if current != event.prior_state {
            return Err(ArtifactLifecycleJournalError::StatePredecessorMismatch);
        }
        if !role_allows(actor.role, producer_id, &event) {
            return Err(ArtifactLifecycleJournalError::ActorRoleDenied);
        }

        let sequence = u64::try_from(self.records.len())
            .map_err(|_| ArtifactLifecycleJournalError::Arithmetic)?
            .checked_add(1)
            .ok_or(ArtifactLifecycleJournalError::Arithmetic)?;
        let predecessor_head_digest = self.head_digest;
        let chain_digest = digest_chain(
            sequence,
            predecessor_head_digest,
            producer_id,
            &actor,
            event_digest,
        );
        let record = ArtifactLifecycleJournalRecordV2 {
            sequence,
            predecessor_head_digest,
            event_digest,
            chain_digest,
            producer_id: producer_id.clone(),
            actor,
            event: event.clone(),
        };
        self.states
            .insert(event.artifact_id.clone(), event.next_state);
        self.event_digests
            .insert(event.event_id.clone(), event_digest);
        self.records.push(record);
        self.head_digest = chain_digest;
        Ok(ArtifactLifecycleJournalReceiptV2 {
            disposition: LifecycleAppendDispositionV2::Appended,
            sequence,
            event_digest,
            head_digest: chain_digest,
            state: event.next_state,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    #[must_use]
    pub fn snapshot(&self) -> ArtifactLifecycleJournalSnapshotV2 {
        ArtifactLifecycleJournalSnapshotV2 {
            records: self.records.clone(),
            head_digest: self.head_digest,
        }
    }

    pub fn from_snapshot(
        snapshot: ArtifactLifecycleJournalSnapshotV2,
        _now: u64,
    ) -> Result<Self, ArtifactLifecycleJournalError> {
        let expected_head = snapshot.head_digest;
        let mut journal = Self::new();
        for expected in snapshot.records {
            journal.replay_record(expected)?;
        }
        if journal.head_digest != expected_head {
            return Err(ArtifactLifecycleJournalError::SnapshotMismatch);
        }
        Ok(journal)
    }

    fn replay_record(
        &mut self,
        expected: ArtifactLifecycleJournalRecordV2,
    ) -> Result<(), ArtifactLifecycleJournalError> {
        if expected.predecessor_head_digest != self.head_digest {
            return Err(ArtifactLifecycleJournalError::SnapshotMismatch);
        }
        validate_actor_replay(&expected.actor)?;
        validate_actor_event_binding(&expected.actor, &expected.event)?;

        let event_digest =
            validate_artifact_lifecycle_transition(&expected.producer_id, &expected.event)?;
        if event_digest != expected.event_digest {
            return Err(ArtifactLifecycleJournalError::SnapshotMismatch);
        }
        if self.event_digests.contains_key(&expected.event.event_id) {
            return Err(ArtifactLifecycleJournalError::SnapshotMismatch);
        }
        if self.records.len() >= MAX_LIFECYCLE_RECORDS {
            return Err(ArtifactLifecycleJournalError::RecordLimit);
        }

        let current = self
            .states
            .get(&expected.event.artifact_id)
            .copied()
            .unwrap_or(ArtifactLifecycleStateV1::Proposed);
        if current != expected.event.prior_state
            || !role_allows(expected.actor.role, &expected.producer_id, &expected.event)
        {
            return Err(ArtifactLifecycleJournalError::SnapshotMismatch);
        }

        let sequence = u64::try_from(self.records.len())
            .map_err(|_| ArtifactLifecycleJournalError::Arithmetic)?
            .checked_add(1)
            .ok_or(ArtifactLifecycleJournalError::Arithmetic)?;
        if sequence != expected.sequence {
            return Err(ArtifactLifecycleJournalError::SnapshotMismatch);
        }
        let chain_digest = digest_chain(
            sequence,
            expected.predecessor_head_digest,
            &expected.producer_id,
            &expected.actor,
            expected.event_digest,
        );
        if chain_digest != expected.chain_digest {
            return Err(ArtifactLifecycleJournalError::SnapshotMismatch);
        }

        self.states.insert(
            expected.event.artifact_id.clone(),
            expected.event.next_state,
        );
        self.event_digests
            .insert(expected.event.event_id.clone(), expected.event_digest);
        self.head_digest = expected.chain_digest;
        self.records.push(expected);
        Ok(())
    }
}

fn validate_actor_replay(
    actor: &LifecycleActorEvidenceV2,
) -> Result<(), ArtifactLifecycleJournalError> {
    if actor.credential_digest.is_zero()
        || actor.authority_epoch == 0
        || actor.verified_at > actor.expires_at
    {
        return Err(ArtifactLifecycleJournalError::InvalidActorEvidence);
    }
    Ok(())
}

fn validate_actor_current(
    actor: &LifecycleActorEvidenceV2,
    now: u64,
) -> Result<(), ArtifactLifecycleJournalError> {
    validate_actor_replay(actor)?;
    if now < actor.verified_at || now > actor.expires_at {
        return Err(ArtifactLifecycleJournalError::InvalidActorEvidence);
    }
    Ok(())
}

fn validate_actor_event_binding(
    actor: &LifecycleActorEvidenceV2,
    event: &ArtifactLifecycleEventV1,
) -> Result<(), ArtifactLifecycleJournalError> {
    if event.actor_id != actor.actor_id
        || event.actor_credential_digest != actor.credential_digest
        || event.authority_epoch != actor.authority_epoch
        || event.occurred_at < actor.verified_at
        || event.occurred_at > actor.expires_at
    {
        return Err(ArtifactLifecycleJournalError::ActorBindingMismatch);
    }
    Ok(())
}

fn role_allows(
    role: LifecycleActorRoleV2,
    producer_id: &StableId,
    event: &ArtifactLifecycleEventV1,
) -> bool {
    match role {
        LifecycleActorRoleV2::Producer => {
            event.actor_id == *producer_id
                && event.prior_state == ArtifactLifecycleStateV1::Proposed
                && event.next_state == ArtifactLifecycleStateV1::Trained
        }
        LifecycleActorRoleV2::Evaluator => {
            event.prior_state == ArtifactLifecycleStateV1::Trained
                && event.next_state == ArtifactLifecycleStateV1::Evaluated
        }
        LifecycleActorRoleV2::ShadowOperator => {
            event.prior_state == ArtifactLifecycleStateV1::Evaluated
                && event.next_state == ArtifactLifecycleStateV1::Shadow
        }
        LifecycleActorRoleV2::CanaryOperator => {
            event.prior_state == ArtifactLifecycleStateV1::Shadow
                && event.next_state == ArtifactLifecycleStateV1::Canary
        }
        LifecycleActorRoleV2::HumanOperator => {
            event.prior_state == ArtifactLifecycleStateV1::Canary
                && event.next_state == ArtifactLifecycleStateV1::OperatorAccepted
        }
        LifecycleActorRoleV2::Selector => {
            event.prior_state == ArtifactLifecycleStateV1::OperatorAccepted
                && event.next_state == ArtifactLifecycleStateV1::Selected
        }
        LifecycleActorRoleV2::QuarantineAuthority => {
            event.next_state == ArtifactLifecycleStateV1::Quarantined
        }
        LifecycleActorRoleV2::RevocationAuthority => {
            event.next_state == ArtifactLifecycleStateV1::Revoked
        }
        LifecycleActorRoleV2::RetirementAuthority => {
            event.next_state == ArtifactLifecycleStateV1::Retired
        }
    }
}

fn digest_chain(
    sequence: u64,
    predecessor_head_digest: Digest32,
    producer_id: &StableId,
    actor: &LifecycleActorEvidenceV2,
    event_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.learning-artifacts.lifecycle-journal.v2".to_vec();
    bytes.extend_from_slice(&sequence.to_be_bytes());
    bytes.extend_from_slice(predecessor_head_digest.as_array());
    push_id(&mut bytes, producer_id);
    push_id(&mut bytes, &actor.actor_id);
    bytes.extend_from_slice(actor.credential_digest.as_array());
    bytes.push(match actor.role {
        LifecycleActorRoleV2::Producer => 0,
        LifecycleActorRoleV2::Evaluator => 1,
        LifecycleActorRoleV2::ShadowOperator => 2,
        LifecycleActorRoleV2::CanaryOperator => 3,
        LifecycleActorRoleV2::HumanOperator => 4,
        LifecycleActorRoleV2::Selector => 5,
        LifecycleActorRoleV2::QuarantineAuthority => 6,
        LifecycleActorRoleV2::RevocationAuthority => 7,
        LifecycleActorRoleV2::RetirementAuthority => 8,
    });
    bytes.extend_from_slice(&actor.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&actor.verified_at.to_be_bytes());
    bytes.extend_from_slice(&actor.expires_at.to_be_bytes());
    bytes.extend_from_slice(event_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    let len = u64::try_from(raw.len()).unwrap_or(u64::MAX);
    bytes.extend_from_slice(&len.to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ArtifactLifecycleJournalError {
    Transition(ArtifactClosureError),
    HeadMismatch,
    InvalidActorEvidence,
    ActorBindingMismatch,
    EventTimeWindow,
    ActorRoleDenied,
    StatePredecessorMismatch,
    EventIdentityConflict,
    RecordLimit,
    SnapshotMismatch,
    InternalInvariant,
    Arithmetic,
}

impl fmt::Display for ArtifactLifecycleJournalError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ArtifactLifecycleJournalError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Transition(error) => Some(error),
            Self::HeadMismatch
            | Self::InvalidActorEvidence
            | Self::ActorBindingMismatch
            | Self::EventTimeWindow
            | Self::ActorRoleDenied
            | Self::StatePredecessorMismatch
            | Self::EventIdentityConflict
            | Self::RecordLimit
            | Self::SnapshotMismatch
            | Self::InternalInvariant
            | Self::Arithmetic => None,
        }
    }
}

impl From<ArtifactClosureError> for ArtifactLifecycleJournalError {
    fn from(value: ArtifactClosureError) -> Self {
        Self::Transition(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid test id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn actor(actor_id: &str, role: LifecycleActorRoleV2) -> LifecycleActorEvidenceV2 {
        LifecycleActorEvidenceV2 {
            actor_id: id(actor_id),
            credential_digest: digest(&format!("credential-{actor_id}")),
            role,
            authority_epoch: 4,
            verified_at: 10,
            expires_at: 100,
        }
    }

    fn event(
        event_id: &str,
        artifact_id: &StableId,
        actor: &LifecycleActorEvidenceV2,
        prior_state: ArtifactLifecycleStateV1,
        next_state: ArtifactLifecycleStateV1,
        occurred_at: u64,
    ) -> ArtifactLifecycleEventV1 {
        ArtifactLifecycleEventV1 {
            event_id: id(event_id),
            artifact_id: artifact_id.clone(),
            prior_state,
            next_state,
            actor_id: actor.actor_id.clone(),
            actor_credential_digest: actor.credential_digest,
            evidence_digest: digest(&format!("evidence-{event_id}")),
            authority_epoch: actor.authority_epoch,
            occurred_at,
        }
    }

    #[test]
    fn art_06_snapshot_replay_survives_historical_actor_expiry() {
        let producer_id = id("producer");
        let artifact_id = id("artifact");
        let producer = actor("producer", LifecycleActorRoleV2::Producer);
        let mut journal = ArtifactLifecycleJournalV2::new();
        journal
            .append(
                Digest32::ZERO,
                &producer_id,
                producer.clone(),
                event(
                    "trained",
                    &artifact_id,
                    &producer,
                    ArtifactLifecycleStateV1::Proposed,
                    ArtifactLifecycleStateV1::Trained,
                    20,
                ),
                20,
            )
            .expect("historical append succeeds while credential is current");

        let snapshot = journal.snapshot();
        let mut reopened =
            ArtifactLifecycleJournalV2::from_snapshot(snapshot, 101).expect("historical replay");
        assert_eq!(reopened.head_digest(), journal.head_digest());

        assert_eq!(
            reopened.append(
                reopened.head_digest(),
                &producer_id,
                producer.clone(),
                event(
                    "late-replay",
                    &id("artifact-late"),
                    &producer,
                    ArtifactLifecycleStateV1::Proposed,
                    ArtifactLifecycleStateV1::Trained,
                    100,
                ),
                101,
            ),
            Err(ArtifactLifecycleJournalError::InvalidActorEvidence)
        );
    }

    #[test]
    fn art_06_new_lifecycle_event_cannot_be_future_dated() {
        let producer_id = id("producer");
        let artifact_id = id("artifact");
        let producer = actor("producer", LifecycleActorRoleV2::Producer);
        let mut journal = ArtifactLifecycleJournalV2::new();
        assert_eq!(
            journal.append(
                Digest32::ZERO,
                &producer_id,
                producer.clone(),
                event(
                    "future-trained",
                    &artifact_id,
                    &producer,
                    ArtifactLifecycleStateV1::Proposed,
                    ArtifactLifecycleStateV1::Trained,
                    21,
                ),
                20,
            ),
            Err(ArtifactLifecycleJournalError::EventTimeWindow)
        );
    }

    #[test]
    fn art_06_lifecycle_journal_enforces_head_state_and_role() {
        let producer_id = id("producer");
        let artifact_id = id("artifact");
        let producer = actor("producer", LifecycleActorRoleV2::Producer);
        let evaluator = actor("evaluator", LifecycleActorRoleV2::Evaluator);
        let mut journal = ArtifactLifecycleJournalV2::new();
        let trained = journal
            .append(
                Digest32::ZERO,
                &producer_id,
                producer.clone(),
                event(
                    "trained",
                    &artifact_id,
                    &producer,
                    ArtifactLifecycleStateV1::Proposed,
                    ArtifactLifecycleStateV1::Trained,
                    20,
                ),
                20,
            )
            .expect("producer may publish trained state");
        assert_eq!(
            journal.append(
                Digest32::ZERO,
                &producer_id,
                evaluator.clone(),
                event(
                    "evaluated",
                    &artifact_id,
                    &evaluator,
                    ArtifactLifecycleStateV1::Trained,
                    ArtifactLifecycleStateV1::Evaluated,
                    21,
                ),
                21,
            ),
            Err(ArtifactLifecycleJournalError::HeadMismatch)
        );
        journal
            .append(
                trained.head_digest,
                &producer_id,
                evaluator.clone(),
                event(
                    "evaluated",
                    &artifact_id,
                    &evaluator,
                    ArtifactLifecycleStateV1::Trained,
                    ArtifactLifecycleStateV1::Evaluated,
                    21,
                ),
                21,
            )
            .expect("independent evaluator may advance state");
        let denied = actor("intruder", LifecycleActorRoleV2::Selector);
        assert_eq!(
            journal.append(
                journal.head_digest(),
                &producer_id,
                denied.clone(),
                event(
                    "skip-to-selected",
                    &artifact_id,
                    &denied,
                    ArtifactLifecycleStateV1::Evaluated,
                    ArtifactLifecycleStateV1::Selected,
                    22,
                ),
                22,
            ),
            Err(ArtifactLifecycleJournalError::Transition(
                ArtifactClosureError::InvalidLifecycleTransition
            ))
        );
    }

    #[test]
    fn art_06_lifecycle_head_binds_actor_evidence_window() {
        let producer_id = id("producer");
        let artifact_id = id("artifact");
        let producer = actor("producer", LifecycleActorRoleV2::Producer);
        let mut journal = ArtifactLifecycleJournalV2::new();
        journal
            .append(
                Digest32::ZERO,
                &producer_id,
                producer.clone(),
                event(
                    "trained",
                    &artifact_id,
                    &producer,
                    ArtifactLifecycleStateV1::Proposed,
                    ArtifactLifecycleStateV1::Trained,
                    20,
                ),
                20,
            )
            .expect("append succeeds");

        let mut tampered = journal.snapshot();
        tampered.records[0].actor.verified_at = 11;
        assert_eq!(
            ArtifactLifecycleJournalV2::from_snapshot(tampered, 20),
            Err(ArtifactLifecycleJournalError::SnapshotMismatch)
        );
    }

    #[test]
    fn art_06_lifecycle_journal_replays_exact_snapshot() {
        let producer_id = id("producer");
        let artifact_id = id("artifact");
        let producer = actor("producer", LifecycleActorRoleV2::Producer);
        let mut journal = ArtifactLifecycleJournalV2::new();
        journal
            .append(
                Digest32::ZERO,
                &producer_id,
                producer.clone(),
                event(
                    "trained",
                    &artifact_id,
                    &producer,
                    ArtifactLifecycleStateV1::Proposed,
                    ArtifactLifecycleStateV1::Trained,
                    20,
                ),
                20,
            )
            .expect("append succeeds");
        let reopened = ArtifactLifecycleJournalV2::from_snapshot(journal.snapshot(), 20)
            .expect("snapshot replays");
        assert_eq!(reopened.head_digest(), journal.head_digest());
        assert_eq!(reopened.records(), journal.records());
    }
}
