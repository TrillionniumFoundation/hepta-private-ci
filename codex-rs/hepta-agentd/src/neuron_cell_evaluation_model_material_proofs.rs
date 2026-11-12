//! Purpose-fixed proof parsing. These are ordinary values, never old seals.
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::DatasetSnapshotV2;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_dataset_snapshot_receipt_v3;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::*;

pub(super) fn execution(
    member: &Member, bundle: &Bundle, execution_digest: Digest32,
    payload: &[u8], signed: &SignedLearningEvidenceV1,
) -> Result<(), Error> {
    let mut raw = Reader::new(&member.execution_record);
    raw.literal(b"HPEXEV01")?;
    let original = SignedLearningEvidenceV1 {
        evidence_id: raw.id()?, principal_id: raw.id()?, role: LearningEvidenceRoleV1::Evaluator,
        trust_digest: raw.digest()?, scope_digest: raw.digest()?,
        objective_digest: raw.digest()?, payload_digest: raw.digest()?,
        authority_epoch: raw.u64()?, issued_at: raw.u64()?, expires_at: raw.u64()?,
        signature: raw.take(64)?.try_into().map_err(|_| Error::Binding("original execution signature"))?,
    };
    let body = raw.bytes()?;
    raw.finish()?;
    if &original != signed || body.len() < 200 {
        return Err(Error::Binding("exact original execution record and signature"));
    }
    let mut key = b"hepta.intelligence-eval.execution-key.v1".to_vec();
    key.extend_from_slice(member.execution_namespace.as_array());
    key.extend_from_slice(Digest32::of_bytes(&member.plan).as_array());
    put_principal(&mut key, &bundle.evaluator);
    let key = Digest32::of_bytes(&key);
    let mut expected = b"hepta.intelligence-eval.signed-execution.v1".to_vec();
    put_id(&mut expected, &bundle.evaluation);
    expected.extend_from_slice(key.as_array());
    expected.extend_from_slice(Digest32::of_bytes(body).as_array());
    if payload != expected { return Err(Error::Binding("same original execution namespace, plan and body")); }
    let mut head = Reader::new(body);
    head.literal(b"HPEXR001")?;
    if head.digest()? != Digest32::of_bytes(&member.plan) {
        return Err(Error::Binding("same original Product plan in execution"));
    }
    let mut tail = Reader::new(&body[body.len() - 160..]);
    if tail.digest()? != bundle.estimate || tail.digest()? != bundle.support
        || tail.digest()? != bundle.confidence || tail.digest()? != execution_digest
    { return Err(Error::Binding("same actual estimates and temporal execution")); }
    let _original_seal_digest = tail.digest()?;
    tail.finish()?;
    Ok(())
}

pub(super) fn holdout(member: &Member, bundle: &Bundle) -> Result<Digest32, Error> {
    if Digest32::of_bytes(&member.holdout) != bundle.holdout {
        return Err(Error::Binding("original consumed holdout preimage"));
    }
    let mut holdout = Reader::new(&member.holdout);
    holdout.literal(b"hepta.intelligence-eval.final-holdout-use.v2")?;
    let manifest = holdout.digest()?;
    if manifest.is_zero() || holdout.id()? != bundle.evaluation || holdout.u8()? != 0
        || holdout.digest()? != bundle.plan || holdout.id()? != bundle.candidate
        || holdout.id()? != bundle.baseline || holdout.digest()? != bundle.objective
        || holdout.digest()? != bundle.dataset || holdout.digest()? != bundle.estimand
        || holdout.digest()? != Digest32::of_bytes(&member.roles)
    { return Err(Error::Binding("complete original holdout semantics")); }
    let _window = holdout.id()?;
    if holdout.digest()?.is_zero() { return Err(Error::Binding("original holdout registry")); }
    holdout.finish()?;
    let mut plan = Reader::new(&member.plan);
    plan.literal(b"hepta.intelligence-eval.product-frozen-plan.v1")?;
    let comparison = Digest32::of_parts(&[b"hepta.agentd.cell-fixed-expert-estimand.v1\0", &member.record]);
    if plan.digest()? != bundle.plan || plan.digest()? != Digest32::of_bytes(&member.roles)
        || plan.digest()? != comparison
    { return Err(Error::Binding("complete original comparison in frozen Product plan")); }
    let candidate_plan = plan.digest()?;
    let baseline_plan = plan.digest()?;
    // The complete plan bytes are authenticated by the original signed raw
    // execution. Parse each original section to reject alternate encodings.
    for _ in 0..member.metrics {
        let _id = plan.id()?;
        if plan.u8()? > 1 { return Err(Error::Binding("plan metric direction")); }
        match plan.u8()? {
            0 => (), 1 => { let _floor = plan.u64()?; },
            _ => return Err(Error::Binding("plan metric floor")),
        }
    }
    let mut roles = Reader::new(&member.roles);
    roles.literal(b"hepta.intelligence-eval.metric-contract.v2")?;
    let _legacy_metric_digest = roles.digest()?;
    for _ in 0..member.metrics {
        if plan.id()? != roles.id()? { return Err(Error::Binding("same original metric role")); }
        let tag = plan.u8()?;
        if roles.u8()? != tag { return Err(Error::Binding("same original metric role tag")); }
        match tag {
            0 | 1 => {
                if plan.u64()? != roles.u64()? { return Err(Error::Binding("same original metric margin")); }
            }
            2 => (),
            _ => return Err(Error::Binding("original metric role tag")),
        }
    }
    roles.finish()?;
    let source_start = plan.offset;
    for _ in 0..member.metrics {
        let _id = plan.id()?;
        if plan.u8()? > 2 { return Err(Error::Binding("original metric estimator")); }
    }
    plan.finish()?;
    let mut estimand = b"hepta.intelligence-eval.product-estimand.v1".to_vec();
    for digest in [comparison, candidate_plan, baseline_plan] {
        estimand.extend_from_slice(digest.as_array());
    }
    estimand.extend_from_slice(&member.plan[source_start..]);
    if estimand != member.estimand {
        return Err(Error::Binding("same comparison, actual temporal plans and estimators"));
    }
    Ok(manifest)
}

pub(in super::super) fn cohort(
    member: &Member, checked: &Checked, context: &Context,
    task: &crate::OriginalCellEvaluationPanelTaskV1,
    generator: &VerifiedLearningEvidenceV1, current: u64,
) -> Result<Digest32, Error> {
    let (payload, signed) = learning_owner_evidence::decode(&member.freeze)?;
    let evaluator = context.verifier.verify(LearningEvidenceRoleV1::Evaluator, &signed, &payload, current)?;
    if evaluator.principal().principal_id != context.training.owners.evaluator {
        return Err(Error::Binding("original independent B freeze owner"));
    }
    verify_signed_actor_separation(generator, &evaluator, current)?;
    let mut proof = Reader::new(&member.cohort);
    proof.literal(b"hepta.circuit.original-evaluation-cohort-current.v1\0")?;
    if proof.digest()? != checked.plan || proof.digest()? != checked.manifest
        || proof.digest()? != checked.dataset
    { return Err(Error::Binding("same original cohort, frozen holdout and Dataset")); }
    let head = proof.digest()?;
    let correction = proof.digest()?;
    let revocation = proof.digest()?;
    if proof.digest()? != task.cohort_rule_digest
        || proof.digest()? != context.registration.evaluation_profile()
        || proof.digest()? != context.training.head_digest
        || proof.digest()? != context.scope.binding()
    { return Err(Error::Binding("same registered B rule, panel, Training and scope")); }
    if proof.digest()?.is_zero() || proof.digest()?.is_zero() {
        return Err(Error::Binding("original independent B ledger and trust distribution"));
    }
    for evidence in [&context.training_evidence, &signed] {
        let mut full = evidence.signing_bytes();
        full.extend_from_slice(&evidence.signature);
        let count = proof.u64()?;
        if count != full.len() as u64 || proof.take(full.len())? != full {
            return Err(Error::Binding("same complete original B freeze and Training signatures"));
        }
    }
    if proof.u64()? != payload.len() as u64 || proof.take(payload.len())? != payload {
        return Err(Error::Binding("same original B freeze payload"));
    }
    proof.finish()?;
    let mut freeze = Reader::new(&payload);
    freeze.literal(b"hepta.learning-ledger.dataset-freeze-plan.v2")?;
    let length = usize::try_from(freeze.u64()?).map_err(|_| Error::Binding("B snapshot identifier"))?;
    if length > 128 { return Err(Error::Binding("bounded original B snapshot")); }
    let snapshot_id = StableId::new(std::str::from_utf8(freeze.take(length)?)
        .map_err(|_| Error::Binding("B snapshot identifier"))?)
        .map_err(|_| Error::Binding("B snapshot identifier"))?;
    let objective = freeze.digest()?;
    let inclusion = freeze.digest()?;
    if objective != context.verifier.objective_digest() || freeze.digest()? != head {
        return Err(Error::Binding("original B freeze objective and ledger head"));
    }
    let eligible_frontier = freeze.u64()?;
    let outcome_watermark = freeze.u64()?;
    if freeze.digest()? != correction || freeze.digest()? != revocation {
        return Err(Error::Binding("original correction and revocation cuts"));
    }
    let count = freeze.u64()?;
    if count == 0 || count > 4096 { return Err(Error::Binding("complete bounded original B source set")); }
    let source_record_digests = (0..count).map(|_| freeze.digest()).collect::<Result<Vec<_>, _>>()?;
    freeze.finish()?;
    // V3 is explicitly a public self-describing digest value, not a Cell,
    // Runner, Qualification or execution seal. Recompute its original identity
    // from the authenticated original freeze and actual complete zero-pending cut.
    verify_dataset_snapshot_receipt_v3(&DatasetSnapshotReceiptV3 {
        snapshot: DatasetSnapshotV2 {
            snapshot_id, ledger_head_digest: head, objective_digest: objective,
            eligible_frontier, outcome_watermark, source_record_digests,
            pending_outcomes: 0, censored_outcomes: 0, dataset_digest: checked.dataset,
            authority: AuthorityPosture::DENY_ALL,
        },
        producer: evaluator.principal().clone(), correction_cut_digest: correction,
        revocation_cut_digest: revocation, inclusion_policy_digest: inclusion,
    }, current).map_err(|_| Error::Binding("same self-verifying original B Dataset"))?;
    Ok(Digest32::of_bytes(&member.cohort))
}

pub(super) fn publication(
    member: &Member, context: &Context, bundle: &Bundle,
    execution_digest: Digest32, authentication: Digest32, publication: Digest32,
    disposition: u8, failed: &[StableId], signatures: [&SignedLearningEvidenceV1; 3],
) -> Result<(), Error> {
    if member.execution_namespace.is_zero() || member.qualification_namespace.is_zero()
        || member.execution_namespace == member.qualification_namespace
    { return Err(Error::Binding("distinct original raw execution and Qualification namespaces")); }
    let mut execution = b"hepta.intelligence-eval.execution-key.v1".to_vec();
    execution.extend_from_slice(member.execution_namespace.as_array());
    execution.extend_from_slice(Digest32::of_bytes(&member.plan).as_array());
    put_principal(&mut execution, &bundle.evaluator);
    let mut key = b"hepta.agentd.original-evaluation-qualification.v1\0".to_vec();
    for digest in [context.training.head_digest, context.scope.binding(),
        member.execution_namespace, member.qualification_namespace, Digest32::of_bytes(&execution),
        Digest32::of_bytes(&member.execution_record), context.verifier.trust_digest()]
    { key.extend_from_slice(digest.as_array()); }
    put_long(&mut key, &member.record);
    for principal in [&bundle.generator, &bundle.evaluator] {
        put_long(&mut key, principal.principal_id.as_str().as_bytes());
        for digest in [principal.credential_chain_digest, principal.signing_key_digest, principal.scope_digest] {
            key.extend_from_slice(digest.as_array());
        }
        for value in [principal.authority_epoch, principal.authenticated_at, principal.expires_at] {
            key.extend_from_slice(&value.to_be_bytes());
        }
    }
    key.extend_from_slice(&(bundle.retention.len() as u64).to_be_bytes());
    for digest in &bundle.retention { key.extend_from_slice(digest.as_array()); }
    key.extend_from_slice(Digest32::ZERO.as_array());
    for signed in std::iter::once(&context.training_evidence).chain(signatures) {
        put_long(&mut key, &signed.signing_bytes());
        key.extend_from_slice(&signed.signature);
    }
    if Digest32::of_bytes(&key) != member.binding {
        return Err(Error::Binding("exact original Qualification namespace and four full signatures"));
    }
    let mut completed = b"hepta.agentd.original-qualification-record.v1\0".to_vec();
    put_long(&mut completed, context.training.request.operation_id.as_str().as_bytes());
    for digest in [member.binding, execution_digest, Digest32::of_bytes(&member.decision),
        context.verifier.trust_digest(), authentication]
    { completed.extend_from_slice(digest.as_array()); }
    for id in [&bundle.evaluation, &bundle.candidate, &bundle.baseline] {
        put_long(&mut completed, id.as_str().as_bytes());
    }
    completed.push(disposition);
    completed.extend_from_slice(&(failed.len() as u64).to_be_bytes());
    for id in failed { put_long(&mut completed, id.as_str().as_bytes()); }
    completed.push(0);
    if Digest32::of_parts(&[b"hepta.agentd.original-qualification-publication.v1\0",
        member.binding.as_array(), &completed]) != publication
    { return Err(Error::Binding("same original durable Qualification publication")); }
    Ok(())
}

fn put_long(bytes: &mut Vec<u8>, value: &[u8]) {
    bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
    bytes.extend_from_slice(value);
}
