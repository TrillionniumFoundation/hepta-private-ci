//! Private bounded journal encoding. Not a platform wire-protocol implementation.

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::AuthenticatedDecisionV2;
use crate::AuthenticatedOutcomeV2;
use crate::CandidateSetCompleteness;
use crate::CreditAllocationBatchV2;
use crate::CreditAssignment;
use crate::DurableCreditAllocationV1;
use crate::DurableLedgerError;
use crate::DurableOutcomeTerminalityV2;
use crate::EpisodeDecision;
use crate::LedgerEvent;
use crate::LedgerRecord;
use crate::OutcomeFinality;
use crate::OutcomeObservation;
use crate::Revocation;
use crate::UnlearningLineageEventV1;

pub(crate) const MAX_EVENT: usize = 32 * 1024;
pub(crate) const FRAME_OVERHEAD: usize = 112;
const DOMAIN: &[u8] = b"hepta.learning-ledger.event.v1";

pub(crate) fn encode_frame(record: &LedgerRecord) -> Result<Vec<u8>, DurableLedgerError> {
    let payload = crate::ledger::encode_event(&record.event);
    if payload.len() > MAX_EVENT {
        return Err(DurableLedgerError::Capacity);
    }
    let size = payload.len() as u32;
    let mut frame = Vec::with_capacity(payload.len() + FRAME_OVERHEAD);
    frame.extend_from_slice(&size.to_be_bytes());
    frame.extend_from_slice(&(!size).to_be_bytes());
    frame.extend_from_slice(&record.sequence.get().to_be_bytes());
    frame.extend_from_slice(record.predecessor_chain_digest.as_array());
    frame.extend_from_slice(&payload);
    frame.extend_from_slice(record.chain_digest.as_array());
    let checksum = Digest32::of_bytes(&frame);
    frame.extend_from_slice(checksum.as_array());
    Ok(frame)
}

pub(crate) fn decode_event(mut input: &[u8]) -> Result<LedgerEvent, DurableLedgerError> {
    input = input
        .strip_prefix(DOMAIN)
        .ok_or(DurableLedgerError::Corrupt)?;
    let mut reader = Reader(input);
    let event = match reader.byte()? {
        0 => LedgerEvent::Decision(reader.decision()?),
        1 => LedgerEvent::Outcome(reader.outcome()?),
        2 => LedgerEvent::Credit(reader.credit()?),
        3 => LedgerEvent::Revocation(reader.revocation()?),
        4 => LedgerEvent::DecisionV2(AuthenticatedDecisionV2 {
            decision: reader.decision()?,
            generator_credential_chain_digest: reader.digest()?,
            generator_signing_key_digest: reader.digest()?,
            generator_controller_id: reader.id()?,
            generator_scope_digest: reader.digest()?,
            generator_authority_epoch: reader.u64()?,
            candidate_set_digest: reader.digest()?,
            candidate_count: reader.u32()?,
            omitted_count_bound: reader.u32()?,
            candidate_receipt_digest: reader.digest()?,
            evidence_digest: reader.digest()?,
        }),
        5 => LedgerEvent::OutcomeV2(AuthenticatedOutcomeV2 {
            record_id: reader.id()?,
            outcome_id: reader.id()?,
            episode_id: reader.id()?,
            observer_id: reader.id()?,
            observer_credential_chain_digest: reader.digest()?,
            observer_signing_key_digest: reader.digest()?,
            observer_controller_id: reader.id()?,
            observer_scope_digest: reader.digest()?,
            observer_authority_epoch: reader.u64()?,
            observed_at: reader.optional_u64()?,
            value: reader.optional_fixed()?,
            unit_profile_digest: reader.digest()?,
            support_digest: reader.digest()?,
            latest_observable_at: reader.u64()?,
            expected_delay_profile_digest: reader.digest()?,
            terminality: match reader.byte()? {
                0 => DurableOutcomeTerminalityV2::Pending,
                1 => DurableOutcomeTerminalityV2::Censored,
                2 => DurableOutcomeTerminalityV2::Terminal,
                _ => return Err(DurableLedgerError::Corrupt),
            },
            censoring_reason: reader.optional_id()?,
            correction_predecessor: reader.optional_id()?,
            finalized_at: reader.optional_u64()?,
            evidence_digest: reader.digest()?,
        }),
        6 => LedgerEvent::CreditBatchV2(CreditAllocationBatchV2 {
            record_id: reader.id()?,
            batch_id: reader.id()?,
            episode_id: reader.id()?,
            outcome_id: reader.id()?,
            allocator_id: reader.id()?,
            allocator_credential_chain_digest: reader.digest()?,
            allocator_signing_key_digest: reader.digest()?,
            allocator_controller_id: reader.id()?,
            allocator_scope_digest: reader.digest()?,
            allocator_authority_epoch: reader.u64()?,
            terminal_outcome: reader.fixed()?,
            allocations: reader.credit_allocations()?,
            conservation_residual: reader.fixed()?,
            parent_credit_id: reader.optional_id()?,
            rule_digest: reader.digest()?,
            support_digest: reader.digest()?,
            evidence_digest: reader.digest()?,
        }),
        7 => LedgerEvent::UnlearningV1(UnlearningLineageEventV1 {
            record_id: reader.id()?,
            lineage_id: reader.id()?,
            scope_digest: reader.digest()?,
            authority_id: reader.id()?,
            authority_credential_chain_digest: reader.digest()?,
            authority_signing_key_digest: reader.digest()?,
            authority_controller_id: reader.id()?,
            authority_epoch: reader.u64()?,
            reason_digest: reader.digest()?,
            source_record_ids: reader.ids(64)?,
            dataset_ids: reader.ids(64)?,
            artifact_ids: reader.ids(64)?,
            predecessor_lineage_id: reader.optional_id()?,
            evidence_digest: reader.digest()?,
        }),
        _ => return Err(DurableLedgerError::Corrupt),
    };
    if !reader.0.is_empty() {
        return Err(DurableLedgerError::Corrupt);
    }
    Ok(event)
}

struct Reader<'a>(&'a [u8]);

impl Reader<'_> {
    fn take<const N: usize>(&mut self) -> Result<[u8; N], DurableLedgerError> {
        let Some((value, remaining)) = self.0.split_at_checked(N) else {
            return Err(DurableLedgerError::Corrupt);
        };
        self.0 = remaining;
        value.try_into().map_err(|_| DurableLedgerError::Corrupt)
    }

    fn decision(&mut self) -> Result<EpisodeDecision, DurableLedgerError> {
        Ok(EpisodeDecision {
            record_id: self.id()?,
            episode_id: self.id()?,
            objective_digest: self.digest()?,
            policy_id: self.id()?,
            candidate_ids: self.ids(128)?,
            selected_candidate_id: self.id()?,
            selected_propensity: ProbabilityQ32::from_raw(self.u64()?)
                .map_err(|_| DurableLedgerError::Corrupt)?,
            completeness: match self.byte()? {
                0 => CandidateSetCompleteness::Complete,
                1 => CandidateSetCompleteness::Incomplete,
                _ => return Err(DurableLedgerError::Corrupt),
            },
            support_digest: self.digest()?,
        })
    }

    fn outcome(&mut self) -> Result<OutcomeObservation, DurableLedgerError> {
        Ok(OutcomeObservation {
            record_id: self.id()?,
            outcome_id: self.id()?,
            episode_id: self.id()?,
            observer_id: self.id()?,
            value: self.fixed()?,
            finality: match self.byte()? {
                0 => OutcomeFinality::Intermediate,
                1 => OutcomeFinality::Terminal,
                _ => return Err(DurableLedgerError::Corrupt),
            },
            support_digest: self.digest()?,
        })
    }

    fn credit(&mut self) -> Result<CreditAssignment, DurableLedgerError> {
        Ok(CreditAssignment {
            record_id: self.id()?,
            credit_id: self.id()?,
            episode_id: self.id()?,
            outcome_id: self.id()?,
            target_artifact_id: self.id()?,
            allocator_id: self.id()?,
            credit: self.fixed()?,
            support_digest: self.digest()?,
        })
    }

    fn revocation(&mut self) -> Result<Revocation, DurableLedgerError> {
        Ok(Revocation {
            record_id: self.id()?,
            target_record_id: self.id()?,
            authority_id: self.id()?,
            reason_digest: self.digest()?,
        })
    }

    fn credit_allocations(&mut self) -> Result<Vec<DurableCreditAllocationV1>, DurableLedgerError> {
        let count = self.u32()? as usize;
        if count > 128 {
            return Err(DurableLedgerError::Corrupt);
        }
        (0..count)
            .map(|_| {
                Ok(DurableCreditAllocationV1 {
                    target_id: self.id()?,
                    credit: self.fixed()?,
                })
            })
            .collect()
    }

    fn ids(&mut self, max: usize) -> Result<Vec<StableId>, DurableLedgerError> {
        let count = self.u32()? as usize;
        if count > max {
            return Err(DurableLedgerError::Corrupt);
        }
        (0..count).map(|_| self.id()).collect()
    }

    fn optional_id(&mut self) -> Result<Option<StableId>, DurableLedgerError> {
        match self.byte()? {
            0 => Ok(None),
            1 => Ok(Some(self.id()?)),
            _ => Err(DurableLedgerError::Corrupt),
        }
    }

    fn optional_u64(&mut self) -> Result<Option<u64>, DurableLedgerError> {
        match self.byte()? {
            0 => Ok(None),
            1 => Ok(Some(self.u64()?)),
            _ => Err(DurableLedgerError::Corrupt),
        }
    }

    fn optional_fixed(&mut self) -> Result<Option<FixedQ32>, DurableLedgerError> {
        match self.byte()? {
            0 => Ok(None),
            1 => Ok(Some(self.fixed()?)),
            _ => Err(DurableLedgerError::Corrupt),
        }
    }

    fn id(&mut self) -> Result<StableId, DurableLedgerError> {
        let length = self.u32()? as usize;
        if !(1..=128).contains(&length) {
            return Err(DurableLedgerError::Corrupt);
        }
        let Some((bytes, remaining)) = self.0.split_at_checked(length) else {
            return Err(DurableLedgerError::Corrupt);
        };
        self.0 = remaining;
        let text = std::str::from_utf8(bytes).map_err(|_| DurableLedgerError::Corrupt)?;
        StableId::new(text).map_err(|_| DurableLedgerError::Corrupt)
    }

    fn digest(&mut self) -> Result<Digest32, DurableLedgerError> {
        Ok(Digest32::from_array(self.take()?))
    }

    fn fixed(&mut self) -> Result<FixedQ32, DurableLedgerError> {
        Ok(FixedQ32::from_raw(i64::from_be_bytes(self.take()?)))
    }

    fn u64(&mut self) -> Result<u64, DurableLedgerError> {
        Ok(u64::from_be_bytes(self.take()?))
    }

    fn u32(&mut self) -> Result<u32, DurableLedgerError> {
        Ok(u32::from_be_bytes(self.take()?))
    }

    fn byte(&mut self) -> Result<u8, DurableLedgerError> {
        Ok(self.take::<1>()?[0])
    }
}
