//! These cases use the same actual Material command host and journals.
//! No Root grant or Gate is fabricated; the adapter remains unable to execute.
//! They do not claim a deployed ordinary LEARN loop or later-stage coverage.

use super::*;
use pretty_assertions::assert_eq;

use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_types::StableId;
use crate::LearningIterationRuntimeErrorV1;
use crate::LearningIterationStageOwnerPortsV1;
use crate::learning_iteration_evidence_client::fresh_material_only;
use crate::learning_iteration_evidence_client::recovered_material_only;

#[tokio::test]
async fn ordinary_stage_without_resident_gate_never_dispatches_original_material()
-> anyhow::Result<()> {
    let fixture = MaterialCommandFixture::new().await?;
    let before = fixture.bytes()?;
    let (experience, experience_peer) = connected(
        &fixture, Role::Experience, Mode::ExecuteOnce, None, Effect::Original,
    )?;
    let (dataset, dataset_peer) = connected(
        &fixture, Role::Dataset, Mode::ExecuteOnce, None, Effect::Original,
    )?;
    let owners = fresh_material_only(fixture.config.clone(), experience, dataset)?;
    owners.require_initial(
        &fixture.config.initial, &fixture.config.scope, &fixture.config.verifier,
    )?;
    let mut changed = fixture.config.initial.clone();
    changed.request.operation_id = StableId::new("different-original-ordinary-operation")?;
    assert!(matches!(
        owners.require_initial(&changed, &fixture.config.scope, &fixture.config.verifier),
        Err(LearningIterationRuntimeErrorV1::WrongScope)
    ));
    assert!(matches!(
        owners.execute_stage(&fixture.config.initial, LearningIterationStageV1::Experience).await,
        Err(LearningIterationRuntimeErrorV1::OwnerUnavailable("fresh resident continuation"))
    ));
    assert!(matches!(
        owners.prepare_proposal(&fixture.config.initial).await,
        Err(LearningIterationRuntimeErrorV1::OwnerUnavailable(_))
    ));
    assert_eq!(fixture.bytes()?, before);
    drop(owners);
    assert_eq!(experience_peer.join().map_err(|_| anyhow::anyhow!("Experience peer"))??, 0);
    assert_eq!(dataset_peer.join().map_err(|_| anyhow::anyhow!("Dataset peer"))??, 0);
    assert_eq!(fixture.bytes()?, before);
    Ok(())
}

#[tokio::test]
async fn ordinary_stage_recovery_keeps_original_missing_uncertain_without_claim()
-> anyhow::Result<()> {
    let fixture = MaterialCommandFixture::new().await?;
    let before = fixture.bytes()?;
    let (experience, experience_peer) = connected(
        &fixture, Role::Experience, Mode::ReadbackOnly, None, Effect::Original,
    )?;
    let (dataset, dataset_peer) = connected(
        &fixture, Role::Dataset, Mode::ReadbackOnly, None, Effect::Original,
    )?;
    let owners = recovered_material_only(fixture.config.clone(), experience, dataset)?;
    assert!(matches!(
        owners.execute_stage(&fixture.config.initial, LearningIterationStageV1::Experience).await,
        Err(LearningIterationRuntimeErrorV1::WrongScope)
    ));
    // This result comes from the original Experience journal. An empty
    // checkpoint is never promoted to a new execution or a successful NoUpdate.
    assert!(matches!(
        owners.validate_recovery(&fixture.config.initial).await,
        Err(LearningIterationRuntimeErrorV1::CommitUncertain)
    ));
    assert_eq!(fixture.bytes()?, before);
    drop(owners);
    assert_eq!(experience_peer.join().map_err(|_| anyhow::anyhow!("Experience peer"))??, 1);
    assert_eq!(dataset_peer.join().map_err(|_| anyhow::anyhow!("Dataset peer"))??, 0);
    assert_eq!(fixture.bytes()?, before);
    Ok(())
}
