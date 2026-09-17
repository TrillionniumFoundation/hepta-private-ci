//! Private bounded journal encoding. Not a platform wire-protocol implementation.

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::AuthenticatedDecisionRecordV2;
use crate::AuthenticatedOutcomeRecordV2;
use crate::AuthenticatedOutcomeV1;
use crate::AuthenticatedPrincipalV1;
use crate::CandidateSetCompleteness;
use crate::CandidateSetCompletenessReceiptV1;
use crate::ConservedCreditBatchRecordV2;
use crate::CreditAllocationBatchV1;
use crate::CreditAllocationV1;
use crate::CreditAssignment;
use crate::DurableLedgerError;
use crate::EpisodeDecision;
use crate::LedgerEvent;
use crate::LedgerRecord;
use crate::OutcomeFinality;
use crate::OutcomeObservation;
use crate::OutcomeTerminalityV1;
use crate::OutcomeWatermarkV1;
use crate::Revocation;

pub(crate) const MAX_EVENT: usize = 32 * 1024;
pub(crate) const FRAME_OVERHEAD: usize = 112;
const DOMAIN: &[u8] = b"hepta.learning-ledger.event.v1";
const MAX_DURABLE_CREDIT_ALLOCATIONS: usize = 224;

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
            candidate_ids: reader.ids(128)?,
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
        4 => LedgerEvent::AuthenticatedDecision(AuthenticatedDecisionRecordV2 {
            record_id: reader.id()?,
            episode_id: reader.id()?,
            objective_digest: reader.digest()?,
            policy_id: reader.id()?,
            generator: reader.principal()?,
            completeness: reader.candidate_receipt()?,
            candidate_ids: reader.ids(128)?,
            selected_candidate_id: reader.id()?,
            selected_propensity: ProbabilityQ32::from_raw(u64::from_be_bytes(reader.take()?))
                .map_err(|_| DurableLedgerError::Corrupt)?,
            evidence_digest: reader.digest()?,
        }),
        5 => LedgerEvent::AuthenticatedOutcome(AuthenticatedOutcomeRecordV2 {
            outcome: AuthenticatedOutcomeV1 {
                record_id: reader.id()?,
                outcome_id: reader.id()?,
                episode_id: reader.id()?,
                observer: reader.principal()?,
                observed_at: reader.optional_u64()?,
                value: reader.optional_fixed()?,
                unit_profile_digest: reader.digest()?,
                support_digest: reader.digest()?,
                watermark: OutcomeWatermarkV1 {
                    latest_observable_at: u64::from_be_bytes(reader.take()?),
                    expected_delay_profile_digest: reader.digest()?,
                    terminality: match reader.byte()? {
                        0 => OutcomeTerminalityV1::Pending,
                        1 => OutcomeTerminalityV1::Censored,
                        2 => OutcomeTerminalityV1::Terminal,
                        _ => return Err(DurableLedgerError::Corrupt),
                    },
                    censoring_reason: reader.optional_id()?,
                    correction_predecessor: reader.optional_id()?,
                    finalized_at: reader.optional_u64()?,
                },
            },
            evidence_digest: reader.digest()?,
        }),
        6 => {
            let record_id = reader.id()?;
            let batch_id = reader.id()?;
            let episode_id = reader.id()?;
            let outcome_id = reader.id()?;
            let allocator = reader.principal()?;
            let terminal_outcome = FixedQ32::from_raw(i64::from_be_bytes(reader.take()?));
            let count = u32::from_be_bytes(reader.take()?) as usize;
            if count == 0 || count > MAX_DURABLE_CREDIT_ALLOCATIONS {
                return Err(DurableLedgerError::Corrupt);
            }
            let allocations = (0..count)
                .map(|_| {
                    Ok(CreditAllocationV1 {
                        target_id: reader.id()?,
                        credit: FixedQ32::from_raw(i64::from_be_bytes(reader.take()?)),
                    })
                })
                .collect::<Result<Vec<_>, DurableLedgerError>>()?;
            let conservation_residual = FixedQ32::from_raw(i64::from_be_bytes(reader.take()?));
            let support_digest = reader.digest()?;
            let finalized = match reader.byte()? {
                0 => false,
                1 => true,
                _ => return Err(DurableLedgerError::Corrupt),
            };
            LedgerEvent::ConservedCreditBatch(ConservedCreditBatchRecordV2 {
                record_id,
                batch: CreditAllocationBatchV1 {
                    batch_id,
                    episode_id,
                    outcome_id,
                    allocator,
                    terminal_outcome,
                    allocations,
                    conservation_residual,
                    support_digest,
                    finalized,
                },
                batch_digest: reader.digest()?,
                evidence_digest: reader.digest()?,
            })
        }
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

    fn ids(&mut self, maximum: usize) -> Result<Vec<StableId>, DurableLedgerError> {
        let count = u32::from_be_bytes(self.take()?) as usize;
        if count > maximum {
            return Err(DurableLedgerError::Corrupt);
        }
        (0..count).map(|_| self.id()).collect()
    }

    fn digest(&mut self) -> Result<Digest32, DurableLedgerError> {
        Ok(Digest32::from_array(self.take()?))
    }

    fn byte(&mut self) -> Result<u8, DurableLedgerError> {
        Ok(self.take::<1>()?[0])
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

    fn principal(&mut self) -> Result<AuthenticatedPrincipalV1, DurableLedgerError> {
        Ok(AuthenticatedPrincipalV1 {
            principal_id: self.id()?,
            credential_chain_digest: self.digest()?,
            signing_key_digest: self.digest()?,
            scope_digest: self.digest()?,
            authority_epoch: u64::from_be_bytes(self.take()?),
            authenticated_at: u64::from_be_bytes(self.take()?),
            expires_at: u64::from_be_bytes(self.take()?),
        })
    }

    fn candidate_receipt(
        &mut self,
    ) -> Result<CandidateSetCompletenessReceiptV1, DurableLedgerError> {
        Ok(CandidateSetCompletenessReceiptV1 {
            set_id: self.id()?,
            state_digest: self.digest()?,
            generator_id: self.id()?,
            generator_code_digest: self.digest()?,
            grammar_digest: self.digest()?,
            hard_filter_digest: self.digest()?,
            truncation_digest: self.digest()?,
            candidates_digest: self.digest()?,
            candidate_count: u32::from_be_bytes(self.take()?),
            omitted_count_bound: u32::from_be_bytes(self.take()?),
            canonical_order_digest: self.digest()?,
            complete_for_generator: match self.byte()? {
                0 => false,
                1 => true,
                _ => return Err(DurableLedgerError::Corrupt),
            },
        })
    }
}
