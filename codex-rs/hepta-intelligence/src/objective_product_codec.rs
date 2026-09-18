//! Canonical bounded codec for durable objective publication frames.

use std::str::FromStr;

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
use serde::Deserialize;
use serde::Serialize;

use super::ObjectivePublicationStoreErrorV1;
use super::RunStartSnapshotV1;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct StoredPublicationBody {
    admission: StoredAdmission,
    objective: StoredCompileReceipt,
    run_start: StoredRunStart,
}

impl StoredPublicationBody {
    pub(super) fn from_typed(
        admission: &ObjectiveAdmissionReceiptV1,
        objective: &ObjectiveCompileReceipt,
        run_start: &RunStartSnapshotV1,
    ) -> Self {
        Self {
            admission: StoredAdmission::from(admission),
            objective: StoredCompileReceipt::from(objective),
            run_start: StoredRunStart::from(run_start),
        }
    }

    pub(super) fn into_typed(
        self,
    ) -> Result<
        (
            ObjectiveAdmissionReceiptV1,
            ObjectiveCompileReceipt,
            RunStartSnapshotV1,
        ),
        ObjectivePublicationStoreErrorV1,
    > {
        Ok((
            self.admission.into_typed()?,
            self.objective.into_typed()?,
            self.run_start.into_typed()?,
        ))
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredAdmission {
    profile_id: String,
    profile_revision: u64,
    profile_digest: String,
    supplied_source_digest: String,
    intent_digest: String,
    admitted_source_digest: String,
    observed_at_unix_micros: u64,
    deadline_unix_micros: Option<u64>,
    authority: String,
}

impl From<&ObjectiveAdmissionReceiptV1> for StoredAdmission {
    fn from(value: &ObjectiveAdmissionReceiptV1) -> Self {
        Self {
            profile_id: value.profile_id.to_string(),
            profile_revision: value.profile_revision.get(),
            profile_digest: value.profile_digest.to_string(),
            supplied_source_digest: value.supplied_source_digest.to_string(),
            intent_digest: value.intent_digest.to_string(),
            admitted_source_digest: value.admitted_source_digest.to_string(),
            observed_at_unix_micros: value.observed_at_unix_micros,
            deadline_unix_micros: value.deadline_unix_micros,
            authority: "deny_all".to_string(),
        }
    }
}

impl StoredAdmission {
    fn into_typed(self) -> Result<ObjectiveAdmissionReceiptV1, ObjectivePublicationStoreErrorV1> {
        if self.authority != "deny_all" {
            return Err(ObjectivePublicationStoreErrorV1::Corrupt);
        }
        Ok(ObjectiveAdmissionReceiptV1 {
            profile_id: stable_id(self.profile_id)?,
            profile_revision: revision(self.profile_revision)?,
            profile_digest: digest(self.profile_digest)?,
            supplied_source_digest: digest(self.supplied_source_digest)?,
            intent_digest: digest(self.intent_digest)?,
            admitted_source_digest: digest(self.admitted_source_digest)?,
            observed_at_unix_micros: self.observed_at_unix_micros,
            deadline_unix_micros: self.deadline_unix_micros,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredCompileReceipt {
    objective: StoredObjectiveFunction,
    disposition: String,
    removed_action_ids: Vec<String>,
}

impl From<&ObjectiveCompileReceipt> for StoredCompileReceipt {
    fn from(value: &ObjectiveCompileReceipt) -> Self {
        Self {
            objective: StoredObjectiveFunction::from(&value.objective),
            disposition: match value.disposition {
                CompileDisposition::Compiled => "compiled",
                CompileDisposition::ExplicitAbstain => "explicit_abstain",
            }
            .to_string(),
            removed_action_ids: value
                .removed_action_ids
                .iter()
                .map(ToString::to_string)
                .collect(),
        }
    }
}

impl StoredCompileReceipt {
    fn into_typed(self) -> Result<ObjectiveCompileReceipt, ObjectivePublicationStoreErrorV1> {
        Ok(ObjectiveCompileReceipt {
            objective: self.objective.into_typed()?,
            disposition: match self.disposition.as_str() {
                "compiled" => CompileDisposition::Compiled,
                "explicit_abstain" => CompileDisposition::ExplicitAbstain,
                _ => return Err(ObjectivePublicationStoreErrorV1::Corrupt),
            },
            removed_action_ids: self
                .removed_action_ids
                .into_iter()
                .map(stable_id)
                .collect::<Result<Vec<_>, _>>()?,
        })
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredObjectiveFunction {
    request_id: String,
    principal_scope: String,
    revision: u64,
    source_digest: String,
    schema_digest: String,
    hard_constraint_digest: String,
    semantic_digest: String,
    constraints: Vec<StoredConstraint>,
    success_predicates: Vec<StoredSuccessPredicate>,
    legal_actions: Vec<StoredAction>,
    soft_preferences: Vec<StoredSoftPreference>,
}

impl From<&ObjectiveFunction> for StoredObjectiveFunction {
    fn from(value: &ObjectiveFunction) -> Self {
        Self {
            request_id: value.request_id.to_string(),
            principal_scope: value.principal_scope.to_string(),
            revision: value.revision.get(),
            source_digest: value.source_digest.to_string(),
            schema_digest: value.schema_digest.to_string(),
            hard_constraint_digest: value.hard_constraint_digest.to_string(),
            semantic_digest: value.semantic_digest.to_string(),
            constraints: value.constraints.iter().map(StoredConstraint::from).collect(),
            success_predicates: value
                .success_predicates
                .iter()
                .map(StoredSuccessPredicate::from)
                .collect(),
            legal_actions: value.legal_actions.iter().map(StoredAction::from).collect(),
            soft_preferences: value
                .soft_preferences
                .iter()
                .map(StoredSoftPreference::from)
                .collect(),
        }
    }
}

impl StoredObjectiveFunction {
    fn into_typed(self) -> Result<ObjectiveFunction, ObjectivePublicationStoreErrorV1> {
        Ok(ObjectiveFunction {
            request_id: stable_id(self.request_id)?,
            principal_scope: stable_id(self.principal_scope)?,
            revision: revision(self.revision)?,
            source_digest: digest(self.source_digest)?,
            schema_digest: digest(self.schema_digest)?,
            hard_constraint_digest: digest(self.hard_constraint_digest)?,
            semantic_digest: digest(self.semantic_digest)?,
            constraints: self
                .constraints
                .into_iter()
                .map(StoredConstraint::into_typed)
                .collect::<Result<Vec<_>, _>>()?,
            success_predicates: self
                .success_predicates
                .into_iter()
