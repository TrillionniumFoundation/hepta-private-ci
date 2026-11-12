//! Strict paired-mode public commitment parsing. Values reconstructed here are
//! only the public comparison contract, never an execution/owner/plan seal.

use codex_hepta_intelligence_eval::OnPolicyArmBindingV1;
use codex_hepta_intelligence_eval::OnPolicyPairContractV1;
use codex_hepta_intelligence_eval::OnPolicyPairingContractV1;
use super::*;

const PLAN: &[u8] = b"hepta.intelligence-eval.product-frozen-paired-on-policy.v1";
const PAIRS: &[u8] = b"hepta.intelligence-eval.on-policy-pair-contract.v1";

pub(super) fn is_paired(member: &Member) -> bool {
    member.plan.starts_with(PLAN)
}

fn contract(bytes: &[u8]) -> Result<OnPolicyPairingContractV1, Error> {
    let mut read = Reader::new(bytes);
    read.literal(PAIRS)?;
    if read.u8()? != 0 {
        return Err(Error::Binding("paired material supports actual FreshEmpty only"));
    }
    // Each pair consumes two original episodes within the producer's 64 cap.
    let count = read.count(32)?;
    if count == 0 {
        return Err(Error::Binding("nonempty actual on-policy pair contract"));
    }
    let mut pairs = Vec::with_capacity(count);
    for _ in 0..count {
        let pair_id = read.id()?;
        let input_digest = read.digest()?;
        let protocol_digest = read.digest()?;
        if read.u8()? != 0 {
            return Err(Error::Binding("original candidate arm tag"));
        }
        let candidate = arm(&mut read)?;
        if read.u8()? != 1 {
            return Err(Error::Binding("original baseline arm tag"));
        }
        let baseline = arm(&mut read)?;
        pairs.push(OnPolicyPairContractV1 {
            pair_id, input_digest, protocol_digest, candidate, baseline,
        });
    }
    read.finish()?;
    let pairing = OnPolicyPairingContractV1 { pairs };
    if pairing.canonical_commitment_bytes()
        .map_err(|_| Error::Binding("valid complete original pair contract"))? != bytes
    {
        return Err(Error::Binding("canonical original pair contract bytes"));
    }
    Ok(pairing)
}

fn arm(read: &mut Reader<'_>) -> Result<OnPolicyArmBindingV1, Error> {
    Ok(OnPolicyArmBindingV1 {
        decision_id: read.id()?,
        principal_lineage: read.id()?,
        episode_lineage: read.id()?,
        behavior_run_id: read.id()?,
        model_digest: read.digest()?,
    })
}

pub(super) fn holdout(member: &Member, bundle: &Bundle) -> Result<(), Error> {
    let mut plan = Reader::new(&member.plan);
    plan.literal(PLAN)?;
    let comparison = Digest32::of_parts(&[
        b"hepta.agentd.cell-paired-on-policy-estimand.v1\0", &member.record,
    ]);
    if plan.digest()? != bundle.plan
        || plan.digest()? != Digest32::of_bytes(&member.roles)
        || plan.digest()? != comparison
    {
        return Err(Error::Binding("complete original paired comparison in Product plan"));
    }
    let candidate_plan = plan.digest()?;
    let baseline_plan = plan.digest()?;
    let pairing = contract(plan.bytes()?)?;
    if plan.u32()? != member.metrics {
        return Err(Error::Binding("complete paired metric contract count"));
    }
    for _ in 0..member.metrics {
        let _id = plan.id()?;
        if plan.u8()? > 1 {
            return Err(Error::Binding("paired metric direction"));
        }
        match plan.u8()? {
            0 => (),
            1 => { let _floor = plan.u64()?; }
            _ => return Err(Error::Binding("paired metric floor")),
        }
    }
    if plan.u32()? != member.metrics {
        return Err(Error::Binding("complete paired metric role count"));
    }
    let mut roles = Reader::new(&member.roles);
    roles.literal(b"hepta.intelligence-eval.metric-contract.v2")?;
    let _legacy_metric_digest = roles.digest()?;
    for _ in 0..member.metrics {
        if plan.id()? != roles.id()? {
            return Err(Error::Binding("same original paired metric role"));
        }
        let tag = plan.u8()?;
        if roles.u8()? != tag {
            return Err(Error::Binding("same original paired metric role tag"));
        }
        match tag {
            0 | 1 => {
                if plan.u64()? != roles.u64()? {
                    return Err(Error::Binding("same original frozen paired margin"));
                }
            }
            2 => (),
            _ => return Err(Error::Binding("original paired metric role tag")),
        }
    }
    roles.finish()?;
    let source_start = plan.offset;
    if plan.u32()? != member.metrics {
        return Err(Error::Binding("complete paired metric source count"));
    }
    for _ in 0..member.metrics {
        let _id = plan.id()?;
        if plan.u8()? > 2 {
            return Err(Error::Binding("original paired metric estimator"));
        }
    }
    plan.finish()?;
    let mut estimand = b"hepta.intelligence-eval.product-paired-on-policy-estimand.v1".to_vec();
    for digest in [
        comparison, candidate_plan, baseline_plan,
        pairing.digest().map_err(|_| Error::Binding("paired estimand contract"))?,
    ] {
        estimand.extend_from_slice(digest.as_array());
    }
    estimand.extend_from_slice(&member.plan[source_start..]);
    if estimand != member.estimand {
        return Err(Error::Binding("same original paired estimand, contract and estimators"));
    }
    Ok(())
}

pub(super) fn require_pairing(
    member: &Member,
    context: &Context,
    expected: Digest32,
) -> Result<(), Error> {
    let mut plan = Reader::new(&member.plan);
    plan.literal(PLAN)?;
    for _ in 0..5 { plan.digest()?; }
    let pairing = contract(plan.bytes()?)?;
    if pairing.digest().map_err(|_| Error::Binding("paired cohort commitment"))? != expected {
        return Err(Error::Binding("same original paired cohort and frozen Product contract"));
    }
    let original = codex_hepta_learning_artifacts::LearningIterationCoordinatorV1::from_snapshot(
        context.training.clone())?;
    let candidate = original.candidate().ok_or(Error::Binding("original paired T candidate"))?
        .digest().map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?;
    let baseline = context.training.request.selected_bundle.digest()
        .map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?;
    for pair in &pairing.pairs {
        if pair.candidate.model_digest != candidate
            || pair.baseline.model_digest != baseline
            || pair.candidate.behavior_run_id == context.training.request.source_run_id
            || pair.baseline.behavior_run_id == context.training.request.source_run_id
        {
            return Err(Error::Binding("actual original paired models and independent B run identities"));
        }
    }
    Ok(())
}
