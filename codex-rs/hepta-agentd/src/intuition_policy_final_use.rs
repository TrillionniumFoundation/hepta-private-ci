//! Final-use clock, trust, qualification and durable writer serialization.

use super::*;
use codex_hepta_learning_ledger::LedgerWriter;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

/// Agentd-owned clock sampled only after the sole LedgerWriter lock is held.
///
/// Implementations must be nondecreasing for one process generation. A clock
/// failure is a hard admission failure; callers cannot supply or cache `now`.
pub trait IntuitionPolicyClock: Send + Sync {
    fn now(&self) -> Result<u64, AgentdIntuitionPolicyError>;
}

/// Wall-clock milliseconds with a process-local monotonic fence. Evidence validity
/// uses wall-clock timestamps, while a backward host adjustment fails closed.
#[derive(Debug, Default)]
pub struct SystemIntuitionPolicyClock {
    last_seen: AtomicU64,
}

impl IntuitionPolicyClock for SystemIntuitionPolicyClock {
    fn now(&self) -> Result<u64, AgentdIntuitionPolicyError> {
        let current = u64::try_from(
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_err(|_| AgentdIntuitionPolicyError::TrustedClockUnavailable)?
                .as_millis(),
        )
        .map_err(|_| AgentdIntuitionPolicyError::TrustedClockUnavailable)?;
        let mut observed = self.last_seen.load(Ordering::Acquire);
        loop {
            if current < observed {
                return Err(AgentdIntuitionPolicyError::TrustedClockReversed);
            }
            match self.last_seen.compare_exchange_weak(
                observed,
                current,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_) => return Ok(current),
                Err(next) => observed = next,
            }
        }
    }
}

/// Sole Agentd-owned durable Decision sink for this module.
pub struct IntuitionPolicyLearningSink {
    writer: Mutex<LedgerWriter>,
    clock: Arc<dyn IntuitionPolicyClock>,
}

impl IntuitionPolicyLearningSink {
    #[must_use]
    pub fn new(writer: LedgerWriter) -> Self {
        Self::new_with_clock(writer, Arc::new(SystemIntuitionPolicyClock::default()))
    }

    #[must_use]
    pub fn new_with_clock(writer: LedgerWriter, clock: Arc<dyn IntuitionPolicyClock>) -> Self {
        Self {
            writer: Mutex::new(writer),
            clock,
        }
    }

    pub fn trust_identity(&self) -> Result<(Digest32, u64, Digest32), AgentdIntuitionPolicyError> {
        let writer = self
            .writer
            .lock()
            .map_err(|_| AgentdIntuitionPolicyError::LearningLockPoisoned)?;
        Ok((
            writer.verifier().trust_digest(),
            writer.trust_generation(),
            writer.trust_distribution_digest(),
        ))
    }

    pub fn trust_digest(&self) -> Result<Digest32, AgentdIntuitionPolicyError> {
        Ok(self.trust_identity()?.0)
    }

    /// Rotate the sole writer-owned trust distribution under the same lock used
    /// by final-use admission. A commit either observes the predecessor or the
    /// successor generation; rotation cannot interleave with revalidation.
    pub fn rotate_trust(
        &self,
        root: &codex_hepta_learning_ledger::LearningTrustRootV1,
        signed: codex_hepta_learning_ledger::SignedLearningTrustDistributionV1,
    ) -> Result<Digest32, AgentdIntuitionPolicyError> {
        let mut writer = self
            .writer
            .lock()
            .map_err(|_| AgentdIntuitionPolicyError::LearningLockPoisoned)?;
        let now = self.clock.now()?;
        writer
            .rotate_trust(root, signed, now)
            .map_err(AgentdIntuitionPolicyError::TrustRotation)
    }

    #[allow(clippy::too_many_arguments)]
    pub(super) fn commit_prepared(
        &self,
        agent_id: &AgentId,
        spawn_generation: u64,
        pins: &AgentdIntuitionPolicyPinsV2,
        prepared: PreparedAgentdIntuitionDecisionV3,
        expected_predecessor: Digest32,
        decision_evidence: Option<SignedLearningEvidenceV1>,
    ) -> Result<AgentdIntuitionDecisionReceiptV2, AgentdIntuitionPolicyError> {
        self.commit_prepared_checked(
            agent_id,
            spawn_generation,
            pins,
            prepared,
            expected_predecessor,
            decision_evidence,
            |_| Ok(()),
        )
    }

    /// Recheck the canonical product owners after any writer-lock wait and
    /// immediately before append. This callback can only reject admission; it
    /// receives neither the writer nor a capability to publish effects.
    #[allow(clippy::too_many_arguments)]
    pub(super) fn commit_prepared_checked<F, E>(
        &self,
        agent_id: &AgentId,
        spawn_generation: u64,
        pins: &AgentdIntuitionPolicyPinsV2,
        prepared: PreparedAgentdIntuitionDecisionV3,
        expected_predecessor: Digest32,
        decision_evidence: Option<SignedLearningEvidenceV1>,
        final_use: F,
    ) -> Result<AgentdIntuitionDecisionReceiptV2, E>
    where
        F: FnOnce(&dyn IntuitionPolicyClock) -> Result<(), E>,
        E: From<AgentdIntuitionPolicyError>,
    {
        // This is the sole final-use serialization boundary. The product clock,
        // current trust distribution, all three qualification signatures, host
        // pins and the durable Decision append are evaluated under one lock.
        let mut writer = self
            .writer
            .lock()
            .map_err(|_| AgentdIntuitionPolicyError::LearningLockPoisoned)?;
        let now = self.clock.now()?;
        writer
            .revalidate_trust(now)
            .map_err(AgentdIntuitionPolicyError::Learning)?;
        let current_trust_digest = writer.verifier().trust_digest();
        let current_trust_generation = writer.trust_generation();
        let current_distribution_digest = writer.trust_distribution_digest();

        if prepared.owner_agent_id != *agent_id
            || prepared.owner_spawn_generation != spawn_generation
            || prepared.owner_trust_digest != current_trust_digest
            || prepared.owner_trust_generation != current_trust_generation
            || prepared.owner_trust_distribution_digest != current_distribution_digest
        {
            return Err(AgentdIntuitionPolicyError::PreparedOwnerMismatch.into());
        }
        validate_prepared_time(prepared.prepared_at, prepared.qualification_expires_at, now)?;
        validate_current_pins(
            pins,
            &prepared.request,
            &prepared.profile,
            &prepared.scoring,
            &prepared.assignment,
        )?;

        final_use(self.clock.as_ref())?;
        // The product fence may read signed owner files or other durable
        // registries. Its return must not reuse time sampled before that I/O.
        let now = self.clock.now()?;
        writer
            .revalidate_trust(now)
            .map_err(AgentdIntuitionPolicyError::Learning)?;
        validate_prepared_time(prepared.prepared_at, prepared.qualification_expires_at, now)?;

        let revalidated = decide_authenticated_intuition_v3(
            prepared.request.clone(),
            prepared.profile.clone(),
            prepared.scoring.clone(),
            prepared.assignment.clone(),
            prepared.qualification.as_borrowed(),
            writer.verifier(),
            now,
        )
        .map_err(AgentdIntuitionPolicyError::from)?;
        if revalidated != prepared.decision {
            return Err(AgentdIntuitionPolicyError::PreparedQualificationMismatch.into());
        }
        let current_binding = product_host_binding_digest(
            agent_id,
            spawn_generation,
            current_trust_digest,
            pins,
            revalidated.authentication_digest,
        );
        if current_binding != prepared.host_binding_digest {
            return Err(AgentdIntuitionPolicyError::PreparedProfileMismatch.into());
        }

        let (production_record_id, learning) =
            match (prepared.production.clone(), decision_evidence) {
                (Some(production), Some(evidence)) => {
                    let record_id = production.record_id.clone();
                    let retry_production = production.clone();
                    let retry_evidence = evidence.clone();
                    let receipt = match writer.append_decision(
                        expected_predecessor,
                        production,
                        &evidence,
                        now,
                    ) {
                        Ok(receipt) => receipt,
                        Err(ProductionLedgerError::IndeterminateAfterLedgerCommit {
                            receipt,
                            witness_error: _,
                        }) => preserve_known_commit(
                            receipt,
                            writer.append_decision(
                                expected_predecessor,
                                retry_production,
                                &retry_evidence,
                                now,
                            ),
                        )
                        .map_err(|receipt| {
                            AgentdIntuitionPolicyError::IndeterminateAfterLedgerCommit { receipt }
                        })?,
                        Err(error) => {
                            return Err(AgentdIntuitionPolicyError::Learning(error).into());
                        }
                    };
                    (Some(record_id), Some(receipt))
                }
                (Some(_), None) => {
                    return Err(AgentdIntuitionPolicyError::MissingDecisionEvidence.into());
                }
                (None, Some(_)) => {
                    return Err(AgentdIntuitionPolicyError::UnexpectedDecisionEvidence.into());
                }
                (None, None) => (None, None),
            };

        let mut bytes = b"hepta.agentd.committed-intuition.v2\0".to_vec();
        bytes.extend_from_slice(prepared.prepared_digest.as_array());
        bytes.extend_from_slice(&now.to_be_bytes());
        bytes.extend_from_slice(&current_trust_generation.to_be_bytes());
        bytes.extend_from_slice(current_distribution_digest.as_array());
        match &learning {
            Some(receipt) => {
                bytes.push(1);
                bytes.extend_from_slice(receipt.event_digest.as_array());
                bytes.extend_from_slice(receipt.chain_digest.as_array());
                bytes.extend_from_slice(&receipt.sequence.get().to_be_bytes());
            }
            None => bytes.push(0),
        }
        Ok(AgentdIntuitionDecisionReceiptV2 {
            decision: revalidated,
            host_binding_digest: prepared.host_binding_digest,
            production_record_id,
            learning,
            service_receipt_digest: Digest32::of_bytes(&bytes),
        })
    }
}

/// Reconciliation cannot turn a known commit into a not-committed failure.
pub(super) fn preserve_known_commit<T, E>(committed: T, replay: Result<T, E>) -> Result<T, T> {
    replay.map_err(|_| committed)
}

pub(super) fn validate_prepared_time(
    prepared_at: u64,
    qualification_expires_at: u64,
    now: u64,
) -> Result<(), AgentdIntuitionPolicyError> {
    if now < prepared_at {
        return Err(AgentdIntuitionPolicyError::PreparedClockReversed);
    }
    // A freshly signed Decision cannot extend the original qualification lease.
    if now >= qualification_expires_at {
        return Err(AgentdIntuitionPolicyError::PreparedEvidenceExpired);
    }
    Ok(())
}
