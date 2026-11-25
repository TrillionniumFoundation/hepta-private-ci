//! Versioned, proposal-only authenticated admission for a coupled field family.
//! Host integration must resolve the current registered profile, actual artifact
//! bytes/holdout uses and owner/budget frontiers independently of the request.
//! The receipt grants no writer, selection, installation or runtime authority.
use codex_hepta_intelligence_eval::{
    IndependentEvaluationBundleV1, IndependentEvaluationDispositionV1, MetricRoleContractV2,
    SignedEvaluationError, SignedEvaluationEvidenceV1, decide_with_signed_evidence_v2,
    evaluation_signing_payload_v2,
};
use codex_hepta_learning_ledger::{
    LearningEvidenceRoleV1, LearningEvidenceVerifierV1, SignedEvidenceError,
    SignedLearningEvidenceV1, VerifiedLearningEvidenceV1, verify_signed_independent_roles_v1,
};
use codex_hepta_plasticity::ParameterCandidateKindV2;
use codex_hepta_plasticity::coupled_field_v1::{
    CoupledFieldProfileV1, ErrorV1 as FieldError, GeneratedCoupledFieldV1, verify_coupled_field_v1,
};
use codex_hepta_types::{AuthorityPosture, Digest32, Generation, StableId};
use std::collections::BTreeMap;

/// Host-resolved binding, not a caller-selected artifact digest. A real host
/// adapter must verify materialization of the exact candidate and durable
/// final-holdout consumption before returning this binding.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CoupledFieldCandidateBindingV1 {
    pub candidate_id: StableId,
    pub artifact_bytes_digest: Digest32,
    pub evaluation_dataset_digest: Digest32,
    pub plan_digest: Digest32,
    pub holdout_use_digest: Digest32,
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CoupledFieldCurrentSnapshotV1 {
    pub scope_id: StableId,
    pub profile_digest: Digest32,
    pub objective_digest: Digest32,
    pub selected_artifact_digest: Digest32,
    pub baseline_id: StableId,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub artifact_registry_head: Digest32,
    pub learning_ledger_head: Digest32,
    pub owner_evidence_set: Digest32,
    pub budget_receipt: Digest32,
    pub trust_digest: Digest32,
    pub valid_until: u64,
    /// Canonical order by candidate ID. Covers every nonzero update.
    pub updates: Vec<CoupledFieldCandidateBindingV1>,
}
/// Trusted in-process owner seam; never exposed as a request/wire capability.
/// Do not implement this by echoing request fields. Re-resolve actual current
/// state, registered policy/profile, content materialization and holdout owner.
pub trait CoupledFieldCurrentOwnerPortV1 {
    fn current(
        &mut self,
        scope: &StableId,
        now: u64,
    ) -> Result<CoupledFieldCurrentSnapshotV1, CoupledFieldAdmissionErrorV1>;
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CoupledFieldEvaluationV1 {
    pub bundle: IndependentEvaluationBundleV1,
    pub metric_roles: Vec<MetricRoleContractV2>,
    pub evidence: SignedEvaluationEvidenceV1,
    /// Additional evaluator signature binds the exact evaluated artifact
    /// bytes, host-resolved snapshot and existing signed metric payload.
    pub artifact_attestation: SignedLearningEvidenceV1,
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CoupledFieldAdmissionRequestV1 {
    pub profile: CoupledFieldProfileV1,
    pub generated: GeneratedCoupledFieldV1,
    pub generator_attestation: SignedLearningEvidenceV1,
    pub observer_attestation: SignedLearningEvidenceV1,
    pub evaluations: Vec<CoupledFieldEvaluationV1>,
    pub no_change_attestation: Option<SignedLearningEvidenceV1>,
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CoupledFieldEvaluatedCandidateV1 {
    pub candidate_id: StableId,
    pub artifact_bytes_digest: Digest32,
    pub disposition: IndependentEvaluationDispositionV1,
    pub evaluation_digest: Digest32,
}
/// Opaque receipt; only this module constructs it. This is evidence for a
/// later independently authorized selection, not selection or a CAS write.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CoupledFieldAdmissionReceiptV1 {
    snapshot_digest: Digest32,
    profile_digest: Digest32,
    evaluation_digest: Digest32,
    evaluated: Vec<CoupledFieldEvaluatedCandidateV1>,
    authority: AuthorityPosture,
}
impl CoupledFieldAdmissionReceiptV1 {
    pub fn snapshot_digest(&self) -> Digest32 {
        self.snapshot_digest
    }
    pub fn profile_digest(&self) -> Digest32 {
        self.profile_digest
    }
    pub fn evaluation_digest(&self) -> Digest32 {
        self.evaluation_digest
    }
    pub fn evaluated(&self) -> &[CoupledFieldEvaluatedCandidateV1] {
        &self.evaluated
    }
    pub fn no_eligible_update(&self) -> bool {
        !self.evaluated.iter().any(|x| {
            x.disposition == IndependentEvaluationDispositionV1::EligibleForIndependentSelection
        })
    }
    pub fn authority(&self) -> AuthorityPosture {
        self.authority
    }
}
#[derive(Debug)]
pub enum CoupledFieldAdmissionErrorV1 {
    OwnerUnavailable,
    InvalidSnapshot,
    CurrentChanged,
    Field(FieldError),
    Binding(&'static str),
    Signature(SignedEvidenceError),
    Evaluation(SignedEvaluationError),
    MissingEvaluation,
    DuplicateEvaluation,
    UnexpectedEvaluation,
    MissingNoChange,
    UnexpectedNoChange,
}
impl std::fmt::Display for CoupledFieldAdmissionErrorV1 {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for CoupledFieldAdmissionErrorV1 {}
impl From<FieldError> for CoupledFieldAdmissionErrorV1 {
    fn from(x: FieldError) -> Self {
        Self::Field(x)
    }
}
impl From<SignedEvidenceError> for CoupledFieldAdmissionErrorV1 {
    fn from(x: SignedEvidenceError) -> Self {
        Self::Signature(x)
    }
}
impl From<SignedEvaluationError> for CoupledFieldAdmissionErrorV1 {
    fn from(x: SignedEvaluationError) -> Self {
        Self::Evaluation(x)
    }
}
type E = CoupledFieldAdmissionErrorV1;
fn id(b: &mut Vec<u8>, x: &StableId) {
    b.extend_from_slice(&(x.as_str().len() as u64).to_be_bytes());
    b.extend_from_slice(x.as_str().as_bytes());
}
fn dg(b: &mut Vec<u8>, x: Digest32) {
    b.extend_from_slice(x.as_array());
}
fn nonzero(x: &[Digest32]) -> bool {
    x.iter().all(|d| !d.is_zero())
}
fn require(ok: bool, e: E) -> Result<(), E> {
    if ok { Ok(()) } else { Err(e) }
}
pub fn coupled_field_snapshot_digest_v1(s: &CoupledFieldCurrentSnapshotV1) -> Result<Digest32, E> {
    require(
        s.baseline_generation.next() == Ok(s.candidate_generation)
            && s.valid_until > 0
            && s.updates.len() <= 31,
        E::InvalidSnapshot,
    )?;
    require(
        nonzero(&[
            s.profile_digest,
            s.objective_digest,
            s.selected_artifact_digest,
            s.artifact_registry_head,
            s.learning_ledger_head,
            s.owner_evidence_set,
            s.budget_receipt,
            s.trust_digest,
        ]),
        E::InvalidSnapshot,
    )?;
    require(
        s.updates
            .windows(2)
            .all(|w| w[0].candidate_id < w[1].candidate_id),
        E::InvalidSnapshot,
    )?;
    let mut b = b"hepta.intelligence.coupled-field.current-snapshot.v1\0".to_vec();
    id(&mut b, &s.scope_id);
    id(&mut b, &s.baseline_id);
    for d in [
        s.profile_digest,
        s.objective_digest,
        s.selected_artifact_digest,
        s.artifact_registry_head,
        s.learning_ledger_head,
        s.owner_evidence_set,
        s.budget_receipt,
        s.trust_digest,
    ] {
        dg(&mut b, d);
    }
    for v in [
        s.baseline_generation.get(),
        s.candidate_generation.get(),
        s.valid_until,
        s.updates.len() as u64,
    ] {
        b.extend_from_slice(&v.to_be_bytes());
    }
    for x in &s.updates {
        require(
            nonzero(&[
                x.artifact_bytes_digest,
                x.evaluation_dataset_digest,
                x.plan_digest,
                x.holdout_use_digest,
            ]),
            E::InvalidSnapshot,
        )?;
        id(&mut b, &x.candidate_id);
        for d in [
            x.artifact_bytes_digest,
            x.evaluation_dataset_digest,
            x.plan_digest,
            x.holdout_use_digest,
        ] {
            dg(&mut b, d);
        }
    }
    Ok(Digest32::of_bytes(&b))
}
fn payload(tag: &[u8], s: &CoupledFieldCurrentSnapshotV1) -> Result<Vec<u8>, E> {
    let mut b = tag.to_vec();
    dg(&mut b, coupled_field_snapshot_digest_v1(s)?);
    Ok(b)
}
pub fn coupled_field_generator_payload_v1(s: &CoupledFieldCurrentSnapshotV1) -> Result<Vec<u8>, E> {
    payload(b"hepta.intelligence.coupled-field.generator.v1\0", s)
}
pub fn coupled_field_observer_payload_v1(s: &CoupledFieldCurrentSnapshotV1) -> Result<Vec<u8>, E> {
    payload(b"hepta.intelligence.coupled-field.observer.v1\0", s)
}
pub fn coupled_field_no_change_payload_v1(
    s: &CoupledFieldCurrentSnapshotV1,
    no_change: &StableId,
) -> Result<Vec<u8>, E> {
    let mut b = payload(b"hepta.intelligence.coupled-field.no-change.v1\0", s)?;
    id(&mut b, no_change);
    Ok(b)
}
pub fn coupled_field_evaluation_artifact_payload_v1(
    s: &CoupledFieldCurrentSnapshotV1,
    binding: &CoupledFieldCandidateBindingV1,
    bundle: &IndependentEvaluationBundleV1,
    roles: &[MetricRoleContractV2],
) -> Result<Vec<u8>, E> {
    let mut b = payload(
        b"hepta.intelligence.coupled-field.evaluated-artifact.v1\0",
        s,
    )?;
    id(&mut b, &binding.candidate_id);
    dg(&mut b, binding.artifact_bytes_digest);
    dg(
        &mut b,
        Digest32::of_bytes(
            &evaluation_signing_payload_v2(bundle, roles).map_err(SignedEvaluationError::from)?,
        ),
    );
    Ok(b)
}
fn signed_digest(e: &SignedLearningEvidenceV1) -> Digest32 {
    let mut b = e.signing_bytes();
    b.extend_from_slice(&e.signature);
    Digest32::of_bytes(&b)
}
fn separate(
    generator: &VerifiedLearningEvidenceV1,
    obs: &VerifiedLearningEvidenceV1,
    e: &VerifiedLearningEvidenceV1,
    now: u64,
) -> Result<(), E> {
    verify_signed_independent_roles_v1(generator, e, now)?;
    verify_signed_independent_roles_v1(obs, e, now)?;
    Ok(())
}
/// Reconstruct the entire declared finite action family, authenticate generator
/// and independent observer, require exact current artifact/plan/holdout bindings
/// and authenticate every outcome, including ineligible candidates.
/// Successful admission is DENY_ALL. A later writer must revalidate the current
/// owner snapshot and budget within its own transaction; this double read is
/// not an atomic activation fence.
pub fn admit_authenticated_coupled_field_v1(
    req: CoupledFieldAdmissionRequestV1,
    scope: &StableId,
    current: &mut impl CoupledFieldCurrentOwnerPortV1,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<CoupledFieldAdmissionReceiptV1, E> {
    let s = current.current(scope, now)?;
    let sd = coupled_field_snapshot_digest_v1(&s)?;
    require(
        &s.scope_id == scope
            && now <= s.valid_until
            && s.trust_digest == verifier.trust_digest()
            && s.objective_digest == verifier.objective_digest(),
        E::InvalidSnapshot,
    )?;
    require(
        req.profile.objective_digest == s.objective_digest
            && req.profile.selected_artifact_digest == s.selected_artifact_digest,
        E::Binding("profile context"),
    )?;
    verify_coupled_field_v1(&req.profile, s.profile_digest, &req.generated)?;
    let updates = req
        .generated
        .candidates
        .iter()
        .filter(|c| c.kind == ParameterCandidateKindV2::Update)
        .collect::<Vec<_>>();
    require(
        updates.len() == s.updates.len()
            && updates
                .iter()
                .zip(&s.updates)
                .all(|(u, b)| u.candidate_id == b.candidate_id),
        E::Binding("complete current candidate family"),
    )?;
    require(
        s.updates
            .iter()
            .all(|b| b.evaluation_dataset_digest != req.profile.dataset_digest),
        E::Binding("separate evaluation dataset"),
    )?;
    let generator = verifier.verify(
        LearningEvidenceRoleV1::Generator,
        &req.generator_attestation,
        &coupled_field_generator_payload_v1(&s)?,
        now,
    )?;
    let obs = verifier.verify(
        LearningEvidenceRoleV1::Observer,
        &req.observer_attestation,
        &coupled_field_observer_payload_v1(&s)?,
        now,
    )?;
    verify_signed_independent_roles_v1(&generator, &obs, now)?;
    require(req.evaluations.len() <= 31, E::UnexpectedEvaluation)?;
    let mut eval = BTreeMap::new();
    for e in req.evaluations {
        let k = e.bundle.candidate_id.clone();
        if eval.insert(k, e).is_some() {
            return Err(E::DuplicateEvaluation);
        }
    }
    let mut b = b"hepta.intelligence.coupled-field.admission.v1\0".to_vec();
    for d in [
        sd,
        s.profile_digest,
        verifier.trust_digest(),
        signed_digest(&req.generator_attestation),
        signed_digest(&req.observer_attestation),
    ] {
        dg(&mut b, d);
    }
    let mut evaluated = Vec::new();
    let mut evaluator_id: Option<StableId> = None;
    if updates.is_empty() {
        require(eval.is_empty(), E::UnexpectedEvaluation)?;
        let nc = req
            .generated
            .candidates
            .iter()
            .find(|c| c.kind == ParameterCandidateKindV2::NoChange)
            .ok_or(E::Binding("no change"))?;
        let att = req
            .no_change_attestation
            .as_ref()
            .ok_or(E::MissingNoChange)?;
        let e = verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            att,
            &coupled_field_no_change_payload_v1(&s, &nc.candidate_id)?,
            now,
        )?;
        separate(&generator, &obs, &e, now)?;
        b.push(0);
        dg(&mut b, signed_digest(att));
    } else {
        require(req.no_change_attestation.is_none(), E::UnexpectedNoChange)?;
        b.push(1);
        for binding in &s.updates {
            let x = eval
                .remove(&binding.candidate_id)
                .ok_or(E::MissingEvaluation)?;
            let q = &x.bundle;
            require(
                q.candidate_id == binding.candidate_id
                    && q.baseline_id == s.baseline_id
                    && q.objective_digest == s.objective_digest
                    && q.dataset_digest == binding.evaluation_dataset_digest
                    && q.frozen_plan.plan_digest == binding.plan_digest
                    && q.holdout_use.use_digest == binding.holdout_use_digest
                    && &q.generator == generator.principal(),
                E::Binding("evaluation lineage"),
            )?;
            if let Some(previous) = &evaluator_id {
                require(
                    previous == &q.evaluator.principal_id,
                    E::Binding("evaluator family identity"),
                )?;
            } else {
                evaluator_id = Some(q.evaluator.principal_id.clone());
            }
            let evp = evaluation_signing_payload_v2(q, &x.metric_roles)
                .map_err(SignedEvaluationError::from)?;
            let e = verifier.verify(
                LearningEvidenceRoleV1::Evaluator,
                &x.evidence.evaluator_bundle,
                &evp,
                now,
            )?;
            require(
                e.principal() == &q.evaluator,
                E::Binding("evaluator signer"),
            )?;
            separate(&generator, &obs, &e, now)?;
            let ap = coupled_field_evaluation_artifact_payload_v1(&s, binding, q, &x.metric_roles)?;
            let art = verifier.verify(
                LearningEvidenceRoleV1::Evaluator,
                &x.artifact_attestation,
                &ap,
                now,
            )?;
            require(
                art.principal() == e.principal(),
                E::Binding("artifact evaluator signer"),
            )?;
            let decision = decide_with_signed_evidence_v2(
                x.bundle,
                x.metric_roles,
                &x.evidence,
                verifier,
                now,
            )?;
            let d = decision.decision;
            require(
                d.candidate_id == binding.candidate_id
                    && d.baseline_id == s.baseline_id
                    && !d.authority.grants_any(),
                E::Binding("evaluation decision"),
            )?;
            let tag = match d.disposition {
                IndependentEvaluationDispositionV1::EligibleForIndependentSelection => 0,
                IndependentEvaluationDispositionV1::Ineligible => 1,
                IndependentEvaluationDispositionV1::InsufficientEvidence => 2,
            };
            id(&mut b, &binding.candidate_id);
            b.push(tag);
            for z in [
                binding.artifact_bytes_digest,
                d.evidence_digest,
                decision.authentication_digest,
                signed_digest(&x.artifact_attestation),
            ] {
                dg(&mut b, z);
            }
            evaluated.push(CoupledFieldEvaluatedCandidateV1 {
                candidate_id: binding.candidate_id.clone(),
                artifact_bytes_digest: binding.artifact_bytes_digest,
                disposition: d.disposition,
                evaluation_digest: d.evidence_digest,
            });
        }
        require(eval.is_empty(), E::UnexpectedEvaluation)?;
    }
    require(current.current(scope, now)? == s, E::CurrentChanged)?;
    Ok(CoupledFieldAdmissionReceiptV1 {
        snapshot_digest: sd,
        profile_digest: s.profile_digest,
        evaluation_digest: Digest32::of_bytes(&b),
        evaluated,
        authority: AuthorityPosture::DENY_ALL,
    })
}
#[cfg(test)]
#[path = "coupled_field_admission_tests.rs"]
mod tests;
