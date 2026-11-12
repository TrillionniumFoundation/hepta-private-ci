//! Verify complete original Product commitment chains, without old seal decode.
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::super::contract::Context;
use super::Error;
use super::codec::Member;
use super::codec::Reader;
use crate::learning_owner_evidence;

#[path = "neuron_cell_evaluation_model_material_proofs.rs"]
mod proofs;
pub(super) use proofs::cohort;

pub(super) struct Checked {
    pub plan: Digest32,
    pub dataset: Digest32,
    pub manifest: Digest32,
    pub estimand: Digest32,
    pub execution: Digest32,
    pub publication: Digest32,
    pub qualification: Digest32,
    pub authentication: Digest32,
    pub retention: Vec<Digest32>,
    pub qualified: bool,
    pub evaluator_issued_at: u64,
}

struct Bundle {
    evaluation: StableId,
    candidate: StableId,
    baseline: StableId,
    generator: AuthenticatedPrincipalV1,
    evaluator: AuthenticatedPrincipalV1,
    plan: Digest32,
    holdout: Digest32,
    objective: Digest32,
    dataset: Digest32,
    estimand: Digest32,
    estimate: Digest32,
    support: Digest32,
    confidence: Digest32,
    retention: Vec<Digest32>,
    snapshot_ids: Vec<StableId>,
    common: usize,
}

fn bundle(bytes: &[u8], metrics: u32) -> Result<Bundle, Error> {
    if !(1..=128).contains(&metrics) {
        return Err(Error::Binding("original bounded metric count"));
    }
    let mut reader = Reader::new(bytes);
    reader.literal(b"hepta.intelligence-eval.independent-decision.v1")?;
    let evaluation = reader.id()?;
    let candidate = reader.id()?;
    let baseline = reader.id()?;
    if reader.u8()? != 0 {
        return Err(Error::Binding("only original Qualification material"));
    }
    let generator = reader.principal()?;
    let evaluator = reader.principal()?;
    let plan = reader.digest()?;
    let holdout = reader.digest()?;
    let objective = reader.digest()?;
    let dataset = reader.digest()?;
    let estimand = reader.digest()?;
    let estimate = reader.digest()?;
    let support = reader.digest()?;
    let confidence = reader.digest()?;
    let retention = (0..reader.count(16)?)
        .map(|_| reader.digest())
        .collect::<Result<Vec<_>, _>>()?;
    if reader.digest()? != Digest32::ZERO {
        return Err(Error::Binding("original panel unlearning profile"));
    }
    let snapshot_ids = reader.ids()?;
    let _future_windows = reader.ids()?;
    let _alpha = reader.u32()?;
    let _comparisons = reader.u32()?;
    for _ in 0..metrics {
        let _id = reader.id()?;
        if reader.u8()? > 1 {
            return Err(Error::Binding("original metric direction"));
        }
        for _ in 0..4 {
            let _endpoint = reader.u64()?;
        }
        match reader.u8()? {
            0 => (),
            1 => {
                let _floor = reader.u64()?;
            }
            _ => return Err(Error::Binding("original metric floor")),
        }
        if reader.digest()?.is_zero() {
            return Err(Error::Binding("original metric support"));
        }
    }
    let common = reader.offset;
    if reader.u8()? != 2 || !reader.ids()?.is_empty() {
        return Err(Error::Binding(
            "canonical original signed request, not a claimed decision",
        ));
    }
    reader.finish()?;
    Ok(Bundle {
        evaluation,
        candidate,
        baseline,
        generator,
        evaluator,
        plan,
        holdout,
        objective,
        dataset,
        estimand,
        estimate,
        support,
        confidence,
        retention,
        snapshot_ids,
        common,
    })
}

pub(super) fn verify(
    member: &Member,
    context: &Context,
    task: &crate::OriginalCellEvaluationPanelTaskV1,
    generator: &VerifiedLearningEvidenceV1,
    current: u64,
) -> Result<Checked, Error> {
    let bundle = bundle(&member.request, member.metrics)?;
    let original = codex_hepta_learning_artifacts::LearningIterationCoordinatorV1::from_snapshot(
        context.training.clone(),
    )?;
    let candidate = original
        .candidate()
        .ok_or(Error::Binding("actual original Candidate"))?;
    if bundle.evaluation != task.plan_id
        || bundle.candidate != candidate.artifact_id
        || bundle.baseline != context.training.request.selected_bundle.artifact_id
        || bundle.objective != context.verifier.objective_digest()
        || &bundle.generator != generator.principal()
        || bundle.evaluator.principal_id != context.training.owners.evaluator
    {
        return Err(Error::Binding(
            "original Product member, Candidate, parent and roles",
        ));
    }
    let (plan_payload, plan_signed) = learning_owner_evidence::decode(&member.generator)?;
    let product_generator = context.verifier.verify(
        LearningEvidenceRoleV1::Generator,
        &plan_signed,
        &plan_payload,
        current,
    )?;
    if plan_payload != bundle.plan.as_array()
        || product_generator.principal() != generator.principal()
        || product_generator.controller_id() != generator.controller_id()
    {
        return Err(Error::Binding("same original Generator and frozen plan"));
    }
    let mut expected = b"hepta.intelligence-eval.signed-request.v2".to_vec();
    expected.extend_from_slice(b"hepta.intelligence-eval.signed-request.v1");
    expected.extend_from_slice(&u64::from(member.metrics).to_be_bytes());
    expected.extend_from_slice(Digest32::of_bytes(&member.request).as_array());
    expected.extend_from_slice(Digest32::of_bytes(&member.roles).as_array());
    let (product_payload, product_signed) = learning_owner_evidence::decode(&member.evaluator)?;
    if product_payload != expected {
        return Err(Error::Binding(
            "complete original Product request and roles preimages",
        ));
    }
    let evaluator = context.verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        &product_signed,
        &expected,
        current,
    )?;
    if evaluator.principal() != &bundle.evaluator {
        return Err(Error::Binding("original Product Evaluator"));
    }
    verify_signed_actor_separation(generator, &evaluator, current)?;
    let mut authentication = b"hepta.intelligence-eval.authenticated-decision.v1".to_vec();
    authentication.extend_from_slice(context.verifier.trust_digest().as_array());
    for signed in [&plan_signed, &product_signed] {
        authentication.extend_from_slice(Digest32::of_bytes(&signed.signing_bytes()).as_array());
        authentication.extend_from_slice(&signed.signature);
    }
    let authentication = Digest32::of_bytes(&authentication);
    let mut decision = Reader::new(&member.decision);
    if decision.take(bundle.common)? != &member.request[..bundle.common] {
        return Err(Error::Binding("same full Product bundle before decision"));
    }
    let disposition = decision.u8()?;
    if disposition > 1 {
        return Err(Error::Binding("known actual panel decision"));
    }
    let failed = decision.ids()?;
    decision.finish()?;
    let mut qualification = Reader::new(&member.qualification);
    qualification.literal(b"hepta.intelligence-eval.product-qualification.v4")?;
    let execution_digest = qualification.digest()?;
    if qualification.digest()? != bundle.objective
        || qualification.digest()? != bundle.dataset
        || qualification.digest()? != Digest32::of_bytes(&member.decision)
        || qualification.digest()? != context.verifier.trust_digest()
        || qualification.digest()? != authentication
    {
        return Err(Error::Binding(
            "original Qualification full decision and authentication",
        ));
    }
    let publication = qualification.digest()?;
    if publication.is_zero()
        || qualification.id()? != bundle.evaluation
        || qualification.id()? != bundle.candidate
        || qualification.id()? != bundle.baseline
        || qualification.u8()? != disposition
        || qualification.ids()? != failed
        || qualification.id()? != bundle.candidate
        || qualification.principal()? != bundle.evaluator
        || qualification.principal()? != bundle.generator
        || qualification.u8()? != 0
        || qualification.ids()? != bundle.snapshot_ids
        || qualification.u8()? != 0
        || qualification.u8()? != 0
    {
        return Err(Error::Binding(
            "complete original Qualification fields and DENY_ALL",
        ));
    }
    qualification.finish()?;
    let (execution_payload, execution_signed) = learning_owner_evidence::decode(&member.execution)?;
    let execution = context.verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        &execution_signed,
        &execution_payload,
        current,
    )?;
    if execution.principal() != evaluator.principal()
        || execution.controller_id() != evaluator.controller_id()
    {
        return Err(Error::Binding(
            "same original Product and execution custody",
        ));
    }
    verify_signed_actor_separation(generator, &execution, current)?;
    proofs::execution(
        member,
        &bundle,
        execution_digest,
        &execution_payload,
        &execution_signed,
    )?;
    proofs::publication(
        member,
        context,
        &bundle,
        execution_digest,
        authentication,
        publication,
        disposition,
        &failed,
        [&plan_signed, &product_signed, &execution_signed],
    )?;
    let manifest = proofs::holdout(member, &bundle)?;
    if Digest32::of_bytes(&member.estimand) != bundle.estimand {
        return Err(Error::Binding(
            "original comparison and temporal estimand preimage",
        ));
    }
    Ok(Checked {
        plan: bundle.plan,
        dataset: bundle.dataset,
        manifest,
        estimand: bundle.estimand,
        execution: execution_digest,
        publication,
        qualification: Digest32::of_bytes(&member.qualification),
        authentication,
        retention: bundle.retention,
        qualified: disposition == 0,
        evaluator_issued_at: product_signed.issued_at,
    })
}

pub(super) fn put_id(bytes: &mut Vec<u8>, id: &StableId) {
    bytes.extend_from_slice(&(id.as_str().len() as u32).to_be_bytes());
    bytes.extend_from_slice(id.as_str().as_bytes());
}
pub(super) fn put_principal(bytes: &mut Vec<u8>, principal: &AuthenticatedPrincipalV1) {
    put_id(bytes, &principal.principal_id);
    for digest in [
        principal.credential_chain_digest,
        principal.signing_key_digest,
        principal.scope_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for value in [
        principal.authority_epoch,
        principal.authenticated_at,
        principal.expires_at,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
}
