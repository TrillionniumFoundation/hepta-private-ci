//! Private bounded journal encoding. Not a platform wire-protocol implementation.

use codex_hepta_objective::ActionClass;
use codex_hepta_objective::CompileDisposition;
use codex_hepta_objective::ConfirmationPolicy;
use codex_hepta_objective::Constraint;
use codex_hepta_objective::ConstraintClass;
use codex_hepta_objective::ConstraintRelation;
use codex_hepta_objective::ObjectiveAdmissionReceiptV1;
use codex_hepta_objective::ObjectiveCompileReceipt;
use codex_hepta_objective::ObjectiveFunction;
use codex_hepta_objective::PredicateTerminality;
use codex_hepta_objective::RunStartSnapshotV1;
use codex_hepta_objective::SoftDirection;
use codex_hepta_objective::SoftPreference;
use codex_hepta_objective::SourceTrust;
use codex_hepta_objective::SuccessPredicate;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::CandidateSetCompleteness;
use crate::CreditAssignment;
use crate::DurableLedgerError;
use crate::EpisodeDecision;
use crate::LedgerEvent;
use crate::LedgerRecord;
use crate::OutcomeFinality;
use crate::OutcomeObservation;
use crate::Revocation;
use crate::RunStartPublicationV1;

// Run-start publication atomically carries the admitted objective and frozen
// run snapshot. Keep one bounded frame rather than splitting a crash-sensitive
// transaction across records.
pub(crate) const MAX_EVENT: usize = 512 * 1024;
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
        4 => LedgerEvent::RunStart(Box::new(decode_run_start(&mut reader)?)),
        _ => return Err(DurableLedgerError::Corrupt),
    };
    if !reader.0.is_empty() {
        return Err(DurableLedgerError::Corrupt);
    }
    Ok(event)
}

fn decode_run_start(reader: &mut Reader<'_>) -> Result<RunStartPublicationV1, DurableLedgerError> {
    let record_id = reader.id()?;
    let profile_id = reader.id()?;
    let profile_revision = Revision::new(reader.u64()?).map_err(|_| DurableLedgerError::Corrupt)?;
    let profile_digest = reader.digest()?;
    let supplied_source_digest = reader.digest()?;
    let intent_digest = reader.digest()?;
    let admitted_source_digest = reader.digest()?;
    let observed_at_unix_micros = reader.u64()?;
    let deadline_unix_micros = match reader.byte()? {
        0 => None,
        1 => Some(reader.u64()?),
        _ => return Err(DurableLedgerError::Corrupt),
    };
    let authority = AuthorityPosture {
        runtime: reader.boolean()?,
        production_writer: reader.boolean()?,
        model_invocation: reader.boolean()?,
        provider_dispatch: reader.boolean()?,
        external_effect: reader.boolean()?,
        selection: reader.boolean()?,
        promotion: reader.boolean()?,
        release: reader.boolean()?,
    };
    let admission = ObjectiveAdmissionReceiptV1 {
        profile_id,
        profile_revision,
        profile_digest,
        supplied_source_digest,
        intent_digest,
        admitted_source_digest,
        observed_at_unix_micros,
        deadline_unix_micros,
        authority,
    };

    let disposition = match reader.byte()? {
        0 => CompileDisposition::Compiled,
        1 => CompileDisposition::ExplicitAbstain,
        _ => return Err(DurableLedgerError::Corrupt),
    };
    let removed_action_ids = reader.ids(128)?;

    let request_id = reader.id()?;
    let principal_scope = reader.id()?;
    let revision = Revision::new(reader.u64()?).map_err(|_| DurableLedgerError::Corrupt)?;
    let source_trust = match reader.byte()? {
        0 => SourceTrust::PrincipalStructured,
        1 => SourceTrust::RegisteredAdapter,
        2 => SourceTrust::UntrustedEvidence,
        _ => return Err(DurableLedgerError::Corrupt),
    };
    let source_digest = reader.digest()?;
    let schema_digest = reader.digest()?;
    let hard_constraint_digest = reader.digest()?;
    let semantic_digest = reader.digest()?;

    let constraints = (0..reader.count(256)?)
        .map(|_| {
            Ok(Constraint {
                id: reader.id()?,
                class: match reader.byte()? {
                    0 => ConstraintClass::Constitutional,
                    1 => ConstraintClass::Principal,
                    2 => ConstraintClass::Environment,
                    3 => ConstraintClass::Task,
                    _ => return Err(DurableLedgerError::Corrupt),
                },
                axis: reader.id()?,
                relation: decode_relation(reader.byte()?)?,
                bound: FixedQ32::from_raw(reader.i64()?),
                evidence_source: reader.id()?,
            })
        })
        .collect::<Result<Vec<_>, DurableLedgerError>>()?;

    let success_predicates = (0..reader.count(256)?)
        .map(|_| {
            Ok(SuccessPredicate {
                id: reader.id()?,
                axis: reader.id()?,
                relation: decode_relation(reader.byte()?)?,
                bound: FixedQ32::from_raw(reader.i64()?),
                evidence_source: reader.id()?,
                terminality: match reader.byte()? {
                    0 => PredicateTerminality::Intermediate,
                    1 => PredicateTerminality::Terminal,
                    _ => return Err(DurableLedgerError::Corrupt),
                },
            })
        })
        .collect::<Result<Vec<_>, DurableLedgerError>>()?;

    let legal_actions = (0..reader.count(128)?)
        .map(|_| {
            Ok(ActionClass {
                id: reader.id()?,
                confirmation: match reader.byte()? {
                    0 => ConfirmationPolicy::NotRequired,
                    1 => ConfirmationPolicy::Required,
                    _ => return Err(DurableLedgerError::Corrupt),
                },
            })
        })
        .collect::<Result<Vec<_>, DurableLedgerError>>()?;

    let soft_preferences = (0..reader.count(64)?)
        .map(|_| {
            Ok(SoftPreference {
                dimension: reader.id()?,
                direction: match reader.byte()? {
                    0 => SoftDirection::Maximize,
                    1 => SoftDirection::Minimize,
                    _ => return Err(DurableLedgerError::Corrupt),
                },
                weight: FixedQ32::from_raw(reader.i64()?),
            })
        })
        .collect::<Result<Vec<_>, DurableLedgerError>>()?;

    let objective = ObjectiveFunction {
        request_id,
        principal_scope,
        revision,
        source_trust,
        source_digest,
        schema_digest,
        hard_constraint_digest,
        semantic_digest,
        constraints,
        success_predicates,
        legal_actions,
        soft_preferences,
    };
    let compile = ObjectiveCompileReceipt {
        objective,
        disposition,
        removed_action_ids,
    };

    let objective_v1_json = reader.bytes(262_144)?;
    let objective_v1_digest = reader.digest()?;

    let run_start = RunStartSnapshotV1 {
        run_id: reader.id()?,
        objective_digest: reader.digest()?,
        hard_constraint_digest: reader.digest()?,
        preference_state_digest: reader.digest()?,
        model_tuple_digest: reader.digest()?,
        prompt_registry_digest: reader.digest()?,
        artifact_set_digest: reader.digest()?,
        authority_epoch: reader.u64()?,
        generation: reader.u64()?,
        fence_digest: reader.digest()?,
    };

    Ok(RunStartPublicationV1 {
        record_id,
        objective_v1_json,
        objective_v1_digest,
        admission,
        compile,
        run_start,
    })
}

fn decode_relation(value: u8) -> Result<ConstraintRelation, DurableLedgerError> {
    match value {
        0 => Ok(ConstraintRelation::AtLeast),
        1 => Ok(ConstraintRelation::AtMost),
        2 => Ok(ConstraintRelation::Equal),
        _ => Err(DurableLedgerError::Corrupt),
    }
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

    fn digest(&mut self) -> Result<Digest32, DurableLedgerError> {
        Ok(Digest32::from_array(self.take()?))
    }

    fn count(&mut self, maximum: usize) -> Result<usize, DurableLedgerError> {
        let value = u32::from_be_bytes(self.take()?) as usize;
        if value > maximum {
            return Err(DurableLedgerError::Corrupt);
        }
        Ok(value)
    }

    fn ids(&mut self, maximum: usize) -> Result<Vec<StableId>, DurableLedgerError> {
        let count = self.count(maximum)?;
        (0..count).map(|_| self.id()).collect()
    }

    fn bytes(&mut self, maximum: usize) -> Result<Vec<u8>, DurableLedgerError> {
        let length = self.count(maximum)?;
        let Some((bytes, remaining)) = self.0.split_at_checked(length) else {
            return Err(DurableLedgerError::Corrupt);
        };
        self.0 = remaining;
        Ok(bytes.to_vec())
    }

    fn u64(&mut self) -> Result<u64, DurableLedgerError> {
        Ok(u64::from_be_bytes(self.take()?))
    }

    fn i64(&mut self) -> Result<i64, DurableLedgerError> {
        Ok(i64::from_be_bytes(self.take()?))
    }

    fn boolean(&mut self) -> Result<bool, DurableLedgerError> {
        match self.byte()? {
            0 => Ok(false),
            1 => Ok(true),
            _ => Err(DurableLedgerError::Corrupt),
        }
    }

    fn byte(&mut self) -> Result<u8, DurableLedgerError> {
        Ok(self.take::<1>()?[0])
    }
}
