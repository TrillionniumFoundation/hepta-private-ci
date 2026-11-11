//! Real CURRENT/files/FinalUse continuation from synthetic qualified evidence.
//! This verifies local choice binding, not independent model quality.

use super::*;
use pretty_assertions::assert_eq;

fn qualified_local(
    original: &LearningIterationCoordinatorV1,
    disposition: LearningLocalDispositionV2,
    policy: &str,
) -> anyhow::Result<LearningIterationCoordinatorV1> {
    let snapshot = original.snapshot();
    let mut c = LearningIterationCoordinatorV1::new(snapshot.request.clone(), snapshot.owners.clone())?;
    for receipt in &snapshot.receipts[..3] { c.record(receipt.clone(), 20)?; }
    let candidate_bundle = c.candidate().unwrap().digest()?;
    for observation in [
        LearningIterationObservationV1::Evaluation {
            candidate_bundle, evaluation_profile: snapshot.request.evaluation_profile,
            disposition: LearningEvaluationDispositionV1::Qualified,
        },
        LearningIterationObservationV1::Proposal {
            candidate_bundle, proposal_id: snapshot.request.operation_id.clone(),
            composition_digest: d("qualified-proposal"),
            disposition: LearningProposalDispositionV1::UpdateCandidates,
        },
    ] { c.record(observed(&c, observation), 20)?; }
    let choice = LearningIterationObservationV1::LocalDecisionV2(LearningLocalDecisionV2 {
        proposal_head: c.snapshot().head_digest,
        candidate_bundle,
        selected_bundle: match disposition {
            LearningLocalDispositionV2::AdoptCandidate => candidate_bundle,
            LearningLocalDispositionV2::DeferCandidate | LearningLocalDispositionV2::RetainParent =>
                snapshot.request.selected_bundle.digest()?,
        },
        policy_digest: d(policy), reason_digest: d("node keeps parent"), disposition,
    });
    c.record(observed(&c, choice), 20)?;
    Ok(c)
}

#[test]
fn qualified_local_retention_reaches_actual_parent_use_and_cold_recovery() -> anyhow::Result<()> {
    for disposition in [LearningLocalDispositionV2::DeferCandidate, LearningLocalDispositionV2::RetainParent] {
        let (f, original) = setup()?;
        let mut c = qualified_local(&original, disposition, "original-node-policy")?;
        let operation = learning_retained_task_operation_id_v1(&c)?;
        let mut ready = recover_after_lost_ack(&f, &c)?;
        let other = qualified_local(&original, disposition, "substituted-node-policy")?;
        assert_ne!(learning_retained_task_operation_id_v1(&other)?, operation);
        assert!(ready.read_learning_selection(&other).is_err());
        let selection = ready.read_learning_selection(&c)?;
        c.record(observed(&c, selection), 20)?;
        let request = request(&ready.journal, &f.target_config, "local-choice-fresh-task")?;
        let intent = request.intent()?;
        ready.journal.admit(request.clone(), /*now_micros*/ 10)?;
        settle(&mut ready, &f, &request, CellGenerationDispositionV2::Advanced)?;
        let actual = ready.read_learning_next_use(&c, &intent)?;
        assert!(matches!(actual, LearningIterationObservationV1::RetainedModelNextUse { .. }));
        let saved = (f.bytes("current.json")?, f.bytes("target-journal")?,
            f.bytes("target-witness")?, f.bytes("final-use/authority.claims")?);
        let intent_digest = ready.publication.intent_digest();
        drop(ready);
        let ready = recover_agentd_generation_update_v1(f.reopen_current()?, f.authorities()?,
            f.selection()?, f.target_reopen()?, AgentdGenerationUpdateRecoveryV1 {
                operation_id: operation.as_str().into(), intent_digest,
            })?;
        assert_eq!(ready.read_learning_next_use(&c, &intent)?, actual);
        c.record(observed(&c, actual), 20)?;
        assert_eq!(c.snapshot().receipts.len(), 8);
        assert_eq!(c.disposition(), LearningIterationDispositionV1::UsedByNextTask);
        assert_eq!(learning_retained_task_operation_id_v1(&c)?, operation);
        assert_eq!(f.authority.capacity()?.used_nonces, 1);
        assert_eq!((f.bytes("current.json")?, f.bytes("target-journal")?,
            f.bytes("target-witness")?, f.bytes("final-use/authority.claims")?), saved);
    }
    Ok(())
}

#[test]
fn qualified_local_adoption_reaches_actual_candidate_and_keeps_decision_operation() -> anyhow::Result<()> {
    let (parent_fixture, original) = setup()?;
    let mut c = qualified_local(&original, LearningLocalDispositionV2::AdoptCandidate,
        "original-node-adoption-policy")?;
    let mut previous = parent_fixture.old_config.clone();
    let mut target = parent_fixture.target_config.clone();
    // Match the existing consumer's complete shared manifest contract. The
    // generic CURRENT fixture intentionally uses unrelated placeholder pins.
    for (config, bundle) in [(&mut previous, &c.snapshot().request.selected_bundle),
        (&mut target, c.candidate().unwrap())] {
        config.manifest.bundle_digest = bundle.digest()?.into_array();
        config.manifest.encoder = Some(bundle.components.encoder.into_array());
        config.manifest.state_schema = bundle.components.state_schema.into_array();
        config.manifest.output_schema = bundle.components.output_schema.into_array();
        config.initial.manifest_digest = config.manifest.digest()?;
    }
    let f = Fixture::new_with_target(previous, target)?;
    let scope = FrozenLearningScopeV2::freeze(&c.snapshot().request, &c.snapshot().owners,
        LearningUpdateScopeV2::Cell, d("update"))?;
    scope.validate_snapshot(c.snapshot())?;
    let operation = crate::learning_updated_task_operation_id_v1(&c)?;
    let prepared = crate::prepare_agentd_generation_update_v1(f.current.clone(), f.authorities()?,
        f.stopped_old()?, f.selection()?, f.target_create()?, AgentdGenerationUpdateRequestV1 {
            operation_id: operation.to_string(),
        })?;
    let grant = f.sign(prepared.final_use_binding())?;
    let mut ready = prepared.publish(&grant)?;
    let selection = ready.read_learning_updated_selection(&c, &f.old_config.manifest)?;
    c.record(observed(&c, selection), 20)?;
    let request = request(&ready.journal, &f.target_config, "local-adoption-fresh-task")?;
    let intent = request.intent()?;
    ready.journal.admit(request.clone(), /*now_micros*/ 10)?;
    settle(&mut ready, &f, &request, CellGenerationDispositionV2::Advanced)?;
    let actual = ready.read_learning_updated_next_use(&c, &f.old_config.manifest, &intent)?;
    assert!(matches!(actual, LearningIterationObservationV1::NextUse { .. }));
    c.record(observed(&c, actual), 20)?;
    assert_eq!(c.disposition(), LearningIterationDispositionV1::UsedByNextTask);
    assert_eq!(crate::learning_updated_task_operation_id_v1(&c)?, operation);
    assert_eq!(c.snapshot().receipts.len(), 8);
    assert_eq!(f.authority.capacity()?.used_nonces, 1);
    scope.validate_snapshot(c.snapshot())?;
    Ok(())
}
