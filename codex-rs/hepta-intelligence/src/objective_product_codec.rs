//! Bounded versioned binary codec for durable objective publication frames.
//!
//! This codec is owner-local persistence, not a public wire protocol. It uses
//! fixed-width numeric fields, raw 32-byte digests and length-prefixed stable
//! identifiers. Decode rejects trailing bytes and every collection is bounded
//! before allocation.

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
use codex_hepta_objective::SoftDirection;
use codex_hepta_objective::SoftPreference;
use codex_hepta_objective::SuccessPredicate;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use super::ObjectivePublicationStoreErrorV1;
use super::RunStartSnapshotV1;

const BODY_MAGIC: &[u8; 8] = b"OBJPUB01";
const MAX_ID_BYTES: usize = 128;
const MAX_CONSTRAINTS: usize = 256;
const MAX_PREDICATES: usize = 128;
const MAX_ACTIONS: usize = 128;
const MAX_SOFT_DIMENSIONS: usize = 64;

pub(super) fn encode_publication(
    admission: &ObjectiveAdmissionReceiptV1,
    objective: &ObjectiveCompileReceipt,
    run_start: &RunStartSnapshotV1,
) -> Result<Vec<u8>, ObjectivePublicationStoreErrorV1> {
    if admission.authority.grants_any() {
        return Err(ObjectivePublicationStoreErrorV1::Corrupt);
    }
    let mut out = Writer::new();
    out.raw(BODY_MAGIC);
    out.id(&admission.profile_id)?;
    out.u64(admission.profile_revision.get());
    out.digest(admission.profile_digest);
    out.digest(admission.supplied_source_digest);
    out.digest(admission.intent_digest);
    out.digest(admission.admitted_source_digest);
    out.u64(admission.observed_at_unix_micros);
    match admission.deadline_unix_micros {
        Some(value) => {
            out.u8(1);
            out.u64(value);
        }
        None => out.u8(0),
    }
    out.u8(0); // AuthorityPosture::DENY_ALL

    encode_objective(&mut out, &objective.objective)?;
    out.u8(match objective.disposition {
        CompileDisposition::Compiled => 0,
        CompileDisposition::ExplicitAbstain => 1,
    });
    out.count(objective.removed_action_ids.len(), MAX_ACTIONS)?;
    for id in &objective.removed_action_ids {
        out.id(id)?;
    }

    out.id(&run_start.run_id)?;
    out.digest(run_start.objective_digest);
    out.digest(run_start.hard_constraint_digest);
    out.digest(run_start.preference_state_digest);
    out.digest(run_start.model_tuple_digest);
    out.digest(run_start.prompt_registry_digest);
    out.digest(run_start.artifact_set_digest);
    out.u64(run_start.authority_epoch);
    out.u64(run_start.generation);
    out.digest(run_start.fence_digest);
    Ok(out.finish())
}

pub(super) fn decode_publication(
    payload: &[u8],
) -> Result<
    (
        ObjectiveAdmissionReceiptV1,
        ObjectiveCompileReceipt,
        RunStartSnapshotV1,
    ),
    ObjectivePublicationStoreErrorV1,
> {
    let mut input = Reader::new(payload);
    if input.raw(BODY_MAGIC.len())? != BODY_MAGIC {
        return Err(ObjectivePublicationStoreErrorV1::Corrupt);
    }
    let admission = ObjectiveAdmissionReceiptV1 {
        profile_id: input.id()?,
        profile_revision: input.revision()?,
        profile_digest: input.digest()?,
        supplied_source_digest: input.digest()?,
        intent_digest: input.digest()?,
        admitted_source_digest: input.digest()?,
        observed_at_unix_micros: input.u64()?,
        deadline_unix_micros: match input.u8()? {
            0 => None,
            1 => Some(input.u64()?),
            _ => return Err(ObjectivePublicationStoreErrorV1::Corrupt),
        },
        authority: match input.u8()? {
            0 => AuthorityPosture::DENY_ALL,
            _ => return Err(ObjectivePublicationStoreErrorV1::Corrupt),
        },
    };
    let objective = ObjectiveCompileReceipt {
        objective: decode_objective(&mut input)?,
        disposition: match input.u8()? {
            0 => CompileDisposition::Compiled,
            1 => CompileDisposition::ExplicitAbstain,
            _ => return Err(ObjectivePublicationStoreErrorV1::Corrupt),
        },
        removed_action_ids: read_ids(&mut input, MAX_ACTIONS)?,
    };
    let run_start = RunStartSnapshotV1 {
        run_id: input.id()?,
        objective_digest: input.digest()?,
        hard_constraint_digest: input.digest()?,
        preference_state_digest: input.digest()?,
        model_tuple_digest: input.digest()?,
        prompt_registry_digest: input.digest()?,
        artifact_set_digest: input.digest()?,
        authority_epoch: input.u64()?,
        generation: input.u64()?,
        fence_digest: input.digest()?,
    };
    input.finish()?;
    Ok((admission, objective, run_start))
}

fn encode_objective(
    out: &mut Writer,
    objective: &ObjectiveFunction,
) -> Result<(), ObjectivePublicationStoreErrorV1> {
    out.id(&objective.request_id)?;
    out.id(&objective.principal_scope)?;
    out.u64(objective.revision.get());
    out.digest(objective.source_digest);
    out.digest(objective.schema_digest);
    out.digest(objective.hard_constraint_digest);
    out.digest(objective.semantic_digest);

    out.count(objective.constraints.len(), MAX_CONSTRAINTS)?;
    for constraint in &objective.constraints {
        out.id(&constraint.id)?;
        out.u8(match constraint.class {
            ConstraintClass::Constitutional => 0,
            ConstraintClass::Principal => 1,
            ConstraintClass::Environment => 2,
            ConstraintClass::Task => 3,
        });
        out.id(&constraint.axis)?;
        out.u8(relation_tag(constraint.relation));
        out.i64(constraint.bound.raw());
        out.id(&constraint.evidence_source)?;
    }

    out.count(objective.success_predicates.len(), MAX_PREDICATES)?;
    for predicate in &objective.success_predicates {
        out.id(&predicate.id)?;
        out.id(&predicate.axis)?;
        out.u8(relation_tag(predicate.relation));
        out.i64(predicate.bound.raw());
        out.id(&predicate.evidence_source)?;
        out.u8(match predicate.terminality {
            PredicateTerminality::Intermediate => 0,
            PredicateTerminality::Terminal => 1,
        });
    }

    out.count(objective.legal_actions.len(), MAX_ACTIONS)?;
    for action in &objective.legal_actions {
        out.id(&action.id)?;
        out.u8(match action.confirmation {
            ConfirmationPolicy::NotRequired => 0,
            ConfirmationPolicy::Required => 1,
        });
    }

    out.count(objective.soft_preferences.len(), MAX_SOFT_DIMENSIONS)?;
    for preference in &objective.soft_preferences {
        out.id(&preference.dimension)?;
        out.u8(match preference.direction {
            SoftDirection::Maximize => 0,
            SoftDirection::Minimize => 1,
        });
        out.i64(preference.weight.raw());
    }
    Ok(())
}

fn decode_objective(
    input: &mut Reader<'_>,
) -> Result<ObjectiveFunction, ObjectivePublicationStoreErrorV1> {
    let request_id = input.id()?;
    let principal_scope = input.id()?;
    let revision = input.revision()?;
    let source_digest = input.digest()?;
    let schema_digest = input.digest()?;
    let hard_constraint_digest = input.digest()?;
    let semantic_digest = input.digest()?;

    let constraint_count = input.count(MAX_CONSTRAINTS)?;
    let mut constraints = Vec::with_capacity(constraint_count);
    for _ in 0..constraint_count {
        constraints.push(Constraint {
            id: input.id()?,
            class: match input.u8()? {
                0 => ConstraintClass::Constitutional,
                1 => ConstraintClass::Principal,
                2 => ConstraintClass::Environment,
                3 => ConstraintClass::Task,
                _ => return Err(ObjectivePublicationStoreErrorV1::Corrupt),
            },
            axis: input.id()?,
            relation: relation(input.u8()?)?,
            bound: FixedQ32::from_raw(input.i64()?),
            evidence_source: input.id()?,
        });
    }

    let predicate_count = input.count(MAX_PREDICATES)?;
    let mut success_predicates = Vec::with_capacity(predicate_count);
    for _ in 0..predicate_count {
        success_predicates.push(SuccessPredicate {
            id: input.id()?,
            axis: input.id()?,
            relation: relation(input.u8()?)?,
            bound: FixedQ32::from_raw(input.i64()?),
            evidence_source: input.id()?,
            terminality: match input.u8()? {
                0 => PredicateTerminality::Intermediate,
                1 => PredicateTerminality::Terminal,
                _ => return Err(ObjectivePublicationStoreErrorV1::Corrupt),
            },
        });
    }

    let action_count = input.count(MAX_ACTIONS)?;
    let mut legal_actions = Vec::with_capacity(action_count);
    for _ in 0..action_count {
        legal_actions.push(ActionClass {
            id: input.id()?,
            confirmation: match input.u8()? {
                0 => ConfirmationPolicy::NotRequired,
                1 => ConfirmationPolicy::Required,
                _ => return Err(ObjectivePublicationStoreErrorV1::Corrupt),
            },
        });
    }

    let preference_count = input.count(MAX_SOFT_DIMENSIONS)?;
    let mut soft_preferences = Vec::with_capacity(preference_count);
    for _ in 0..preference_count {
        soft_preferences.push(SoftPreference {
            dimension: input.id()?,
            direction: match input.u8()? {
                0 => SoftDirection::Maximize,
                1 => SoftDirection::Minimize,
                _ => return Err(ObjectivePublicationStoreErrorV1::Corrupt),
            },
            weight: FixedQ32::from_raw(input.i64()?),
        });
    }

    Ok(ObjectiveFunction {
        request_id,
        principal_scope,
        revision,
        source_digest,
        schema_digest,
        hard_constraint_digest,
        semantic_digest,
        constraints,
        success_predicates,
        legal_actions,
        soft_preferences,
    })
}

fn read_ids(
    input: &mut Reader<'_>,
    maximum: usize,
) -> Result<Vec<StableId>, ObjectivePublicationStoreErrorV1> {
    let count = input.count(maximum)?;
    let mut values = Vec::with_capacity(count);
    for _ in 0..count {
        values.push(input.id()?);
    }
    Ok(values)
}

const fn relation_tag(relation: ConstraintRelation) -> u8 {
    match relation {
        ConstraintRelation::AtLeast => 0,
        ConstraintRelation::AtMost => 1,
        ConstraintRelation::Equal => 2,
    }
}

fn relation(tag: u8) -> Result<ConstraintRelation, ObjectivePublicationStoreErrorV1> {
    match tag {
        0 => Ok(ConstraintRelation::AtLeast),
        1 => Ok(ConstraintRelation::AtMost),
        2 => Ok(ConstraintRelation::Equal),
        _ => Err(ObjectivePublicationStoreErrorV1::Corrupt),
    }
}

struct Writer {
    bytes: Vec<u8>,
}

impl Writer {
    fn new() -> Self {
        Self { bytes: Vec::new() }
    }

    fn finish(self) -> Vec<u8> {
        self.bytes
    }

    fn raw(&mut self, value: &[u8]) {
        self.bytes.extend_from_slice(value);
    }

    fn u8(&mut self, value: u8) {
        self.bytes.push(value);
    }

    fn u32(&mut self, value: u32) {
        self.raw(&value.to_be_bytes());
    }

    fn u64(&mut self, value: u64) {
        self.raw(&value.to_be_bytes());
    }

    fn i64(&mut self, value: i64) {
        self.raw(&value.to_be_bytes());
    }

    fn digest(&mut self, value: Digest32) {
        self.raw(value.as_array());
    }

    fn id(&mut self, value: &StableId) -> Result<(), ObjectivePublicationStoreErrorV1> {
        let text = value.as_str().as_bytes();
        if text.len() > MAX_ID_BYTES {
            return Err(ObjectivePublicationStoreErrorV1::Corrupt);
        }
        self.count(text.len(), MAX_ID_BYTES)?;
        self.raw(text);
        Ok(())
    }

    fn count(
        &mut self,
        value: usize,
        maximum: usize,
    ) -> Result<(), ObjectivePublicationStoreErrorV1> {
        if value > maximum {
            return Err(ObjectivePublicationStoreErrorV1::Capacity);
        }
        let value = u32::try_from(value).map_err(|_| ObjectivePublicationStoreErrorV1::Capacity)?;
        self.u32(value);
        Ok(())
    }
}

struct Reader<'a> {
    bytes: &'a [u8],
    cursor: usize,
}

impl<'a> Reader<'a> {
    fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, cursor: 0 }
    }

    fn finish(self) -> Result<(), ObjectivePublicationStoreErrorV1> {
        if self.cursor == self.bytes.len() {
            Ok(())
        } else {
            Err(ObjectivePublicationStoreErrorV1::Corrupt)
        }
    }

    fn raw(&mut self, length: usize) -> Result<&'a [u8], ObjectivePublicationStoreErrorV1> {
        let end = self
            .cursor
            .checked_add(length)
            .ok_or(ObjectivePublicationStoreErrorV1::Corrupt)?;
        let value = self
            .bytes
            .get(self.cursor..end)
            .ok_or(ObjectivePublicationStoreErrorV1::Corrupt)?;
        self.cursor = end;
        Ok(value)
    }

    fn u8(&mut self) -> Result<u8, ObjectivePublicationStoreErrorV1> {
        self.raw(1)?
            .first()
            .copied()
            .ok_or(ObjectivePublicationStoreErrorV1::Corrupt)
    }

    fn u32(&mut self) -> Result<u32, ObjectivePublicationStoreErrorV1> {
        Ok(u32::from_be_bytes(
            self.raw(4)?
                .try_into()
                .map_err(|_| ObjectivePublicationStoreErrorV1::Corrupt)?,
        ))
    }

    fn u64(&mut self) -> Result<u64, ObjectivePublicationStoreErrorV1> {
        Ok(u64::from_be_bytes(
            self.raw(8)?
                .try_into()
                .map_err(|_| ObjectivePublicationStoreErrorV1::Corrupt)?,
        ))
    }

    fn i64(&mut self) -> Result<i64, ObjectivePublicationStoreErrorV1> {
        Ok(i64::from_be_bytes(
            self.raw(8)?
                .try_into()
                .map_err(|_| ObjectivePublicationStoreErrorV1::Corrupt)?,
        ))
    }

    fn digest(&mut self) -> Result<Digest32, ObjectivePublicationStoreErrorV1> {
        let bytes: [u8; 32] = self
            .raw(32)?
            .try_into()
            .map_err(|_| ObjectivePublicationStoreErrorV1::Corrupt)?;
        Ok(Digest32::from_array(bytes))
    }

    fn revision(&mut self) -> Result<Revision, ObjectivePublicationStoreErrorV1> {
        Revision::new(self.u64()?).map_err(|_| ObjectivePublicationStoreErrorV1::Corrupt)
    }

    fn id(&mut self) -> Result<StableId, ObjectivePublicationStoreErrorV1> {
        let length = self.count(MAX_ID_BYTES)?;
        let text = std::str::from_utf8(self.raw(length)?)
            .map_err(|_| ObjectivePublicationStoreErrorV1::Corrupt)?;
        StableId::new(text.to_string()).map_err(|_| ObjectivePublicationStoreErrorV1::Corrupt)
    }

    fn count(&mut self, maximum: usize) -> Result<usize, ObjectivePublicationStoreErrorV1> {
        let value =
            usize::try_from(self.u32()?).map_err(|_| ObjectivePublicationStoreErrorV1::Corrupt)?;
        if value > maximum {
            return Err(ObjectivePublicationStoreErrorV1::Corrupt);
        }
        Ok(value)
    }
}
