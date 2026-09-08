//! Read-only vertical composition across objective, cognitive, context and NDU stages.
//!
//! The facade derives every cross-stage digest inside one call. It cannot invoke
//! a model, tool, provider or effect and never grants selection, promotion or
//! release authority.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_read::Error as CognitiveReadError;
use codex_hepta_cognitive_read::ReadReceipt;
use codex_hepta_cognitive_read::ReadRequest;
use codex_hepta_cognitive_read::read;
use codex_hepta_cognitive_types::CognitiveSnapshot;
use codex_hepta_cognitive_types::Error as CognitiveSnapshotError;
use codex_hepta_context_compiler::CompilationRequest;
use codex_hepta_context_compiler::ContextCompilationReceipt;
use codex_hepta_context_compiler::ContextRole;
use codex_hepta_context_compiler::Error as ContextCompileError;
use codex_hepta_context_compiler::compile;
use codex_hepta_ndu::AxisDirection;
use codex_hepta_ndu::AxisValue;
use codex_hepta_ndu::ContributionSet;
use codex_hepta_ndu::FeasibilityPosture;
use codex_hepta_ndu::NduError;
use codex_hepta_ndu::NduEvaluationReceipt;
use codex_hepta_ndu::ScalarizationProfile;
use codex_hepta_ndu::UtilityContribution;
use codex_hepta_ndu::UtilityProfile;
use codex_hepta_ndu::evaluate_candidates;
use codex_hepta_objective::CompileDisposition;
use codex_hepta_objective::ObjectiveAdmissionContextV1;
use codex_hepta_objective::ObjectiveAdmissionError;
use codex_hepta_objective::ObjectiveAdmissionProfileV1;
use codex_hepta_objective::ObjectiveAdmissionReceiptV1;
use codex_hepta_objective::ObjectiveCompileReceipt;
use codex_hepta_objective::ObjectiveSourceEnvelopeV1;
use codex_hepta_objective::SoftDirection;
use codex_hepta_objective::SoftPreference;
use codex_hepta_objective::admit_and_compile_objective_v1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AbstentionReason;
use crate::IntelligencePlanReceipt;
use crate::PlanDecision;

const ABSTAIN_ID: &str = "abstain";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReadOnlyUtilityContribution {
    pub candidate_id: StableId,
    pub organ_id: StableId,
    pub feasibility: FeasibilityPosture,
    pub utility: Vec<AxisValue>,
    pub risk: Vec<AxisValue>,
    pub resource: Vec<AxisValue>,
    pub uncertainty: Vec<AxisValue>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReadOnlyVerticalRequest {
    pub plan_id: StableId,
    pub objective_envelope: ObjectiveSourceEnvelopeV1,
    pub objective_profile: ObjectiveAdmissionProfileV1,
    pub objective_context: ObjectiveAdmissionContextV1,
    pub cognitive_snapshot: CognitiveSnapshot,
    pub cognitive_read: ReadRequest,
    pub context: CompilationRequest,
    pub required_read_evidence_item_id: StableId,
    pub ndu_profile: UtilityProfile,
    pub ndu_scalarization_profile_id: StableId,
    pub ndu_contributions: Vec<ReadOnlyUtilityContribution>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReadOnlyVerticalReceipt {
    pub objective_admission: ObjectiveAdmissionReceiptV1,
    pub objective: ObjectiveCompileReceipt,
    pub cognitive_read: ReadReceipt,
    pub context: ContextCompilationReceipt,
    pub ndu: NduEvaluationReceipt,
    pub ndu_support_digest: Digest32,
    pub plan: IntelligencePlanReceipt,
    pub vertical_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Debug)]
pub enum ReadOnlyVerticalError {
    ObjectiveAdmission(ObjectiveAdmissionError),
    ObjectiveConflict(Digest32),
    ObjectiveExplicitAbstain,
    Snapshot(CognitiveSnapshotError),
    CognitiveRead(CognitiveReadError),
    Context(ContextCompileError),
    Ndu(NduError),
    AuthorityEscalation(&'static str),
    DigestMismatch(&'static str),
    SoftDimensionMismatch,
    IllegalCandidate(String),
    MissingReadEvidenceItem(String),
    InvalidReadEvidenceItem(String),
    ReadEvidenceOmitted(String),
    UnknownRecommendation(String),
}

impl fmt::Display for ReadOnlyVerticalError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ReadOnlyVerticalError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::ObjectiveAdmission(error) => Some(error),
            Self::Snapshot(error) => Some(error),
            Self::CognitiveRead(error) => Some(error),
            Self::Context(error) => Some(error),
            Self::Ndu(error) => Some(error),
            Self::ObjectiveConflict(_)
            | Self::ObjectiveExplicitAbstain
            | Self::AuthorityEscalation(_)
            | Self::DigestMismatch(_)
            | Self::SoftDimensionMismatch
            | Self::IllegalCandidate(_)
            | Self::MissingReadEvidenceItem(_)
            | Self::InvalidReadEvidenceItem(_)
            | Self::ReadEvidenceOmitted(_)
            | Self::UnknownRecommendation(_) => None,
        }
    }
}

pub fn run_read_only_vertical(
    request: ReadOnlyVerticalRequest,
) -> Result<ReadOnlyVerticalReceipt, ReadOnlyVerticalError> {
    let ReadOnlyVerticalRequest {
        plan_id,
        objective_envelope,
        objective_profile,
        objective_context,
        cognitive_snapshot,
        cognitive_read: read_request,
        context: context_request,
        required_read_evidence_item_id,
        ndu_profile,
        ndu_scalarization_profile_id,
        ndu_contributions,
    } = request;

    cognitive_snapshot
        .validate_integrity()
        .map_err(ReadOnlyVerticalError::Snapshot)?;
    ensure_no_authority("cognitive snapshot", cognitive_snapshot.authority)?;

    let objective_outcome = admit_and_compile_objective_v1(
        &objective_envelope,
        &objective_profile,
        &objective_context,
    )
    .map_err(ReadOnlyVerticalError::ObjectiveAdmission)?;
    ensure_no_authority("objective admission", objective_outcome.receipt.authority)?;
    let objective_admission = objective_outcome.receipt;
    let objective = objective_outcome
        .compile_result
        .map_err(|conflict| ReadOnlyVerticalError::ObjectiveConflict(conflict.conflict_digest))?;
    if objective.disposition != CompileDisposition::Compiled {
        return Err(ReadOnlyVerticalError::ObjectiveExplicitAbstain);
    }
    let objective_digest = objective.objective.semantic_digest;
    ensure_digest("compiled objective", objective_digest)?;

    if read_request.snapshot_digest != cognitive_snapshot.snapshot_digest {
        return Err(ReadOnlyVerticalError::DigestMismatch(
            "cognitive read snapshot",
        ));
    }
    let cognitive_read = read(&cognitive_snapshot, read_request)
        .map_err(ReadOnlyVerticalError::CognitiveRead)?;
    ensure_no_authority("cognitive read", cognitive_read.authority)?;

    if context_request.run_snapshot_digest != cognitive_snapshot.snapshot_digest {
        return Err(ReadOnlyVerticalError::DigestMismatch(
            "context snapshot",
        ));
    }
    if context_request.objective_digest != objective_digest {
        return Err(ReadOnlyVerticalError::DigestMismatch(
            "context objective",
        ));
    }
    validate_read_evidence_item(
        &context_request,
        &required_read_evidence_item_id,
        cognitive_snapshot.snapshot_digest,
        cognitive_read.receipt_digest,
    )?;
    let context = compile(context_request).map_err(ReadOnlyVerticalError::Context)?;
    ensure_no_authority("context compilation", context.authority)?;
    if !context
        .untrusted_evidence_ids
        .iter()
        .any(|item_id| item_id == &required_read_evidence_item_id)
    {
        return Err(ReadOnlyVerticalError::ReadEvidenceOmitted(
            required_read_evidence_item_id.to_string(),
        ));
    }

    validate_soft_dimensions(&objective.objective.soft_preferences, &ndu_profile)?;
    let legal_actions = objective
        .objective
        .legal_actions
        .iter()
        .map(|action| action.id.clone())
        .collect::<BTreeSet<_>>();
    let ndu_support_digest = stage_support_digest(
        objective_digest,
        cognitive_snapshot.snapshot_digest,
        cognitive_read.receipt_digest,
        context.context_digest,
    );
    let generation = cognitive_snapshot.generation;
    let contributions = ndu_contributions
        .into_iter()
        .map(|contribution| {
            if !legal_actions.contains(&contribution.candidate_id) {
                return Err(ReadOnlyVerticalError::IllegalCandidate(
                    contribution.candidate_id.to_string(),
                ));
            }
            let support_digest = contribution_support_digest(
                ndu_support_digest,
                &contribution.candidate_id,
                &contribution.organ_id,
            );
            Ok(UtilityContribution {
                candidate_id: contribution.candidate_id,
                organ_id: contribution.organ_id,
                objective_digest,
                generation,
                feasibility: contribution.feasibility,
                utility: contribution.utility,
                risk: contribution.risk,
                resource: contribution.resource,
                uncertainty: contribution.uncertainty,
                support_digest,
            })
        })
        .collect::<Result<Vec<_>, ReadOnlyVerticalError>>()?;
    let scalarization = derive_scalarization(
        ndu_scalarization_profile_id,
        &objective.objective.soft_preferences,
    );
    let ndu = evaluate_candidates(
        ContributionSet {
            objective_digest,
            generation,
            contributions,
        },
        ndu_profile,
        scalarization,
    )
    .map_err(ReadOnlyVerticalError::Ndu)?;

    let plan = plan_from_ndu(
        PlanBindings {
            plan_id,
            objective_digest,
            snapshot_digest: cognitive_snapshot.snapshot_digest,
            read_digest: cognitive_read.receipt_digest,
            context_digest: context.context_digest,
            support_digest: ndu_support_digest,
        },
        &ndu,
    )?;
    ensure_no_authority("intelligence plan", plan.authority)?;
    if plan.effect_authority {
        return Err(ReadOnlyVerticalError::AuthorityEscalation(
            "intelligence plan effect authority",
        ));
    }

    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.intelligence.read-only-vertical.v1");
    push_id(&mut bytes, &plan.plan_id);
    bytes.extend_from_slice(objective_admission.profile_digest.as_array());
    bytes.extend_from_slice(objective_admission.intent_digest.as_array());
    bytes.extend_from_slice(objective_admission.admitted_source_digest.as_array());
    bytes.extend_from_slice(objective_digest.as_array());
    bytes.extend_from_slice(cognitive_snapshot.snapshot_digest.as_array());
    bytes.extend_from_slice(cognitive_read.receipt_digest.as_array());
    bytes.extend_from_slice(context.context_digest.as_array());
    bytes.extend_from_slice(ndu_support_digest.as_array());
    bytes.extend_from_slice(ndu.evaluation_digest.as_array());
    bytes.extend_from_slice(plan.plan_digest.as_array());

    Ok(ReadOnlyVerticalReceipt {
        objective_admission,
        objective,
        cognitive_read,
        context,
        ndu,
        ndu_support_digest,
        plan,
        vertical_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn validate_read_evidence_item(
    request: &CompilationRequest,
    required_id: &StableId,
    snapshot_digest: Digest32,
    read_digest: Digest32,
) -> Result<(), ReadOnlyVerticalError> {
    let mut matches = request
        .items
        .iter()
        .filter(|item| &item.item_id == required_id);
    let Some(item) = matches.next() else {
        return Err(ReadOnlyVerticalError::MissingReadEvidenceItem(
            required_id.to_string(),
        ));
    };
    if matches.next().is_some()
        || item.role != ContextRole::UntrustedEvidence
        || item.content_digest != read_digest
        || item.source_digest != snapshot_digest
        || item.contains_secret
    {
        return Err(ReadOnlyVerticalError::InvalidReadEvidenceItem(
            required_id.to_string(),
        ));
    }
    Ok(())
}

fn validate_soft_dimensions(
    preferences: &[SoftPreference],
    profile: &UtilityProfile,
) -> Result<(), ReadOnlyVerticalError> {
    let mut expected = preferences
        .iter()
        .map(|preference| {
            let direction = match preference.direction {
                SoftDirection::Maximize => AxisDirection::Maximize,
                SoftDirection::Minimize => AxisDirection::Minimize,
            };
            (preference.dimension.clone(), direction)
        })
        .collect::<Vec<_>>();
    expected.sort();
    let mut actual = profile.dimensions.clone();
    actual.sort();
    if expected != actual {
        return Err(ReadOnlyVerticalError::SoftDimensionMismatch);
    }
    Ok(())
}

fn derive_scalarization(
    profile_id: StableId,
    preferences: &[SoftPreference],
) -> Option<ScalarizationProfile> {
    if preferences.is_empty() {
        return None;
    }
    Some(ScalarizationProfile {
        profile_id,
        weights: preferences
            .iter()
            .map(|preference| AxisValue {
                axis: preference.dimension.clone(),
                value: preference.weight,
            })
            .collect(),
    })
}

fn ensure_no_authority(
    stage: &'static str,
    authority: AuthorityPosture,
) -> Result<(), ReadOnlyVerticalError> {
    if authority.grants_any() {
        return Err(ReadOnlyVerticalError::AuthorityEscalation(stage));
    }
    Ok(())
}

fn ensure_digest(
    stage: &'static str,
    digest: Digest32,
) -> Result<(), ReadOnlyVerticalError> {
    if digest.is_zero() {
        return Err(ReadOnlyVerticalError::DigestMismatch(stage));
    }
    Ok(())
}

fn stage_support_digest(
    objective_digest: Digest32,
    snapshot_digest: Digest32,
    read_digest: Digest32,
    context_digest: Digest32,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.intelligence.vertical-support.v1");
    bytes.extend_from_slice(objective_digest.as_array());
    bytes.extend_from_slice(snapshot_digest.as_array());
    bytes.extend_from_slice(read_digest.as_array());
    bytes.extend_from_slice(context_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn contribution_support_digest(
    stage_digest: Digest32,
    candidate_id: &StableId,
    organ_id: &StableId,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.intelligence.vertical-contribution.v1");
    bytes.extend_from_slice(stage_digest.as_array());
    push_id(&mut bytes, candidate_id);
    push_id(&mut bytes, organ_id);
    Digest32::of_bytes(&bytes)
}

struct PlanBindings {
    plan_id: StableId,
    objective_digest: Digest32,
    snapshot_digest: Digest32,
    read_digest: Digest32,
    context_digest: Digest32,
    support_digest: Digest32,
}

fn plan_from_ndu(
    bindings: PlanBindings,
    receipt: &NduEvaluationReceipt,
) -> Result<IntelligencePlanReceipt, ReadOnlyVerticalError> {
    let mut considered = receipt
        .evaluated_candidates
        .iter()
        .map(|candidate| candidate.candidate_id.clone())
        .chain(
            receipt
                .rejected_candidates
                .iter()
                .map(|candidate| candidate.candidate_id.clone()),
        )
        .collect::<Vec<_>>();
    considered.sort();
    considered.dedup();

    let decision = match &receipt.advisory_recommendation {
        Some(candidate_id) if candidate_id.as_str() == ABSTAIN_ID => {
            PlanDecision::Abstained(AbstentionReason::NoEligibleCandidate)
        }
        Some(candidate_id) => {
            if !receipt
                .evaluated_candidates
                .iter()
                .any(|candidate| &candidate.candidate_id == candidate_id)
            {
                return Err(ReadOnlyVerticalError::UnknownRecommendation(
                    candidate_id.to_string(),
                ));
            }
            PlanDecision::Selected(candidate_id.clone())
        }
        None => PlanDecision::Abstained(AbstentionReason::NoEligibleCandidate),
    };

    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.intelligence.ndu-plan.v1");
    push_id(&mut bytes, &bindings.plan_id);
    bytes.extend_from_slice(bindings.objective_digest.as_array());
    bytes.extend_from_slice(bindings.snapshot_digest.as_array());
    bytes.extend_from_slice(bindings.read_digest.as_array());
    bytes.extend_from_slice(bindings.context_digest.as_array());
    bytes.extend_from_slice(bindings.support_digest.as_array());
    bytes.extend_from_slice(receipt.evaluation_digest.as_array());
    match &decision {
        PlanDecision::Selected(candidate_id) => {
            bytes.push(1);
            push_id(&mut bytes, candidate_id);
        }
        PlanDecision::Abstained(AbstentionReason::NoEligibleCandidate) => bytes.push(0),
    }
    for candidate_id in &considered {
        push_id(&mut bytes, candidate_id);
    }

    Ok(IntelligencePlanReceipt {
        plan_id: bindings.plan_id,
        decision,
        considered_candidates: considered,
        plan_digest: Digest32::of_bytes(&bytes),
        effect_authority: false,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}
