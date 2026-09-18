//! Private bounded journal encoding. Not a platform wire-protocol implementation.

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::AuthenticatedOutcomeRecordV2;
use crate::AuthenticatedOutcomeTerminality;
use crate::CandidateSetCompleteness;
use crate::CreditAllocationBatchRecordV2;
use crate::CreditAllocationRecordV2;
use crate::CreditAssignment;
use crate::DurableLedgerError;
use crate::EpisodeDecision;
use crate::LedgerEvent;
use crate::LedgerRecord;
use crate::OutcomeFinality;
use crate::OutcomeObservation;
use crate::Revocation;
use crate::UnlearningLineageEventV1;

pub(crate) const MAX_EVENT: usize = 64 * 1024;
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
        0 => LedgerEvent::Decision(EpisodeDecision {
            record_id: reader.id()?,
            episode_id: reader.id()?,
            objective_digest: reader.digest()?,
            policy_id: reader.id()?,
            candidate_ids: {
                let count = u32::from_be_bytes(reader.take()?) as usize;
                if count > 128 {
                    return Err(DurableLedgerError::Corrupt);
                }
                (0..count)
                    .map(|_| reader.id())
                    .collect::<Result<Vec<_>, _>>()?
            },
            selected_candidate_id: reader.id()?,
            selected_propensity: ProbabilityQ32::from_raw(u64::from_be_bytes(reader.take()?))
                .map_err(|_| DurableLedgerError::Corrupt)?,
            completeness: match reader.byte()? {
                0 => CandidateSetCompleteness::Complete,
                1 => CandidateSetCompleteness::Incomplete,
                _ => return Err(DurableLedgerError::Corrupt),
            },
            support_digest: reader.digest()?,
        }),
        1 => LedgerEvent::Outcome(OutcomeObservation {
            record_id: reader.id()?,
            outcome_id: reader.id()?,
            episode_id: reader.id()?,
            observer_id: reader.id()?,
            value: FixedQ32::from_raw(i64::from_be_bytes(reader.take()?)),
            finality: match reader.byte()? {
                0 => OutcomeFinality::Intermediate,
                1 => OutcomeFinality::Terminal,
                _ => return Err(DurableLedgerError::Corrupt),
            },
            support_digest: reader.digest()?,
        }),
        2 => LedgerEvent::Credit(CreditAssignment {
            record_id: reader.id()?,
            credit_id: reader.id()?,
            episode_id: reader.id()?,
            outcome_id: reader.id()?,
            target_artifact_id: reader.id()?,
            allocator_id: reader.id()?,
            credit: FixedQ32::from_raw(i64::from_be_bytes(reader.take()?)),
            support_digest: reader.digest()?,
        }),
        3 => LedgerEvent::Revocation(Revocation {
            record_id: reader.id()?,
            target_record_id: reader.id()?,
            authority_id: reader.id()?,
            reason_digest: reader.digest()?,
        }),
        4 => LedgerEvent::AuthenticatedOutcomeV2(AuthenticatedOutcomeRecordV2 {
            record_id: reader.id()?,
            outcome_id: reader.id()?,
            episode_id: reader.id()?,
            observer_id: reader.id()?,
            observer_credential_chain_digest: reader.digest()?,
            observer_signing_key_digest: reader.digest()?,
            observer_scope_digest: reader.digest()?,
            observer_authority_epoch: u64::from_be_bytes(reader.take()?),
            observed_at: reader.optional_u64()?,
            value: reader.optional_fixed()?,
            unit_profile_digest: reader.digest()?,
            support_digest: reader.digest()?,
            latest_observable_at: u64::from_be_bytes(reader.take()?),
            expected_delay_profile_digest: reader.digest()?,
            terminality: match reader.byte()? {
                0 => AuthenticatedOutcomeTerminality::Pending,
                1 => AuthenticatedOutcomeTerminality::Censored,
                2 => AuthenticatedOutcomeTerminality::Terminal,
                _ => return Err(DurableLedgerError::Corrupt),
            },
            censoring_reason: reader.optional_id()?,
            correction_predecessor: reader.optional_id()?,
            finalized_at: reader.optional_u64()?,
            authentication_digest: reader.digest()?,
        }),
        5 => LedgerEvent::CreditBatchV2(CreditAllocationBatchRecordV2 {
            record_id: reader.id()?,
            batch_id: reader.id()?,
            episode_id: reader.id()?,
            outcome_id: reader.id()?,
            allocator_id: reader.id()?,
            allocator_credential_chain_digest: reader.digest()?,
            allocator_signing_key_digest: reader.digest()?,
            allocator_scope_digest: reader.digest()?,
            allocator_authority_epoch: u64::from_be_bytes(reader.take()?),
            terminal_outcome: FixedQ32::from_raw(i64::from_be_bytes(reader.take()?)),
            allocations: {
                let count = u32::from_be_bytes(reader.take()?) as usize;
                if count > 256 {
                    return Err(DurableLedgerError::Corrupt);
                }
                (0..count)
                    .map(|_| {
                        Ok(CreditAllocationRecordV2 {
                            target_artifact_id: reader.id()?,
                            credit: FixedQ32::from_raw(i64::from_be_bytes(reader.take()?)),
                        })
                    })
                    .collect::<Result<Vec<_>, DurableLedgerError>>()?
            },
            conservation_residual: FixedQ32::from_raw(i64::from_be_bytes(reader.take()?)),
            support_digest: reader.digest()?,
            authentication_digest: reader.digest()?,
        }),
        6 => LedgerEvent::UnlearningLineageV1(UnlearningLineageEventV1 {
            record_id: reader.id()?,
            lineage_id: reader.id()?,
            source_record_id: reader.id()?,
            dataset_snapshot_id: reader.id()?,
            artifact_id: reader.id()?,
            authority_id: reader.id()?,
            reason_digest: reader.digest()?,
            authentication_digest: reader.digest()?,
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

    fn id(&mut self) -> Result<StableId, DurableLedgerError> {
        let length = u32::from_be_bytes(self.take()?) as usize;
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

    fn optional_id(&mut self) -> Result<Option<StableId>, DurableLedgerError> {
        match self.byte()? {
            0 => Ok(None),
            1 => self.id().map(Some),
            _ => Err(DurableLedgerError::Corrupt),
        }
    }

    fn optional_u64(&mut self) -> Result<Option<u64>, DurableLedgerError> {
        match self.byte()? {
            0 => Ok(None),
            1 => Ok(Some(u64::from_be_bytes(self.take()?))),
            _ => Err(DurableLedgerError::Corrupt),
        }
    }

    fn optional_fixed(&mut self) -> Result<Option<FixedQ32>, DurableLedgerError> {
        match self.byte()? {
            0 => Ok(None),
            1 => Ok(Some(FixedQ32::from_raw(i64::from_be_bytes(self.take()?)))),
            _ => Err(DurableLedgerError::Corrupt),
        }
    }

    fn digest(&mut self) -> Result<Digest32, DurableLedgerError> {
        Ok(Digest32::from_array(self.take()?))
    }

    fn byte(&mut self) -> Result<u8, DurableLedgerError> {
        Ok(self.take::<1>()?[0])
    }
}
