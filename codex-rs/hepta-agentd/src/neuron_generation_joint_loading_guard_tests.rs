//! Original CURRENT, actor, journal and recovery with a synthetic worker.
//! A committed successful proposal alone cannot attest a native v4 model load.

use codex_hepta_neuron::CellGenerationDispositionV2;
use pretty_assertions::assert_eq;

use super::*;

#[tokio::test]
async fn joint_candidate_without_native_loading_proof_is_refused_before_and_after_recovery()
-> anyhow::Result<()> {
    for profile in [
        codex_hepta_infer_core::JOINT_V4_LOADING_PROCESS_PROFILE,
        "joint-generator-proposal-linux-v2",
    ] {
        let mut f = UpdatedRuntime::new_with_contract(RuntimeTestContract::Joint(profile)).await?;
        let (mut tasks, _lifetime) = support::start(&mut f.runtime, &f.host)?;
        let baseline = f.publication.old_config.manifest.clone();
        let selection = f.read_selection(&f.coordinator).await?;
        f.coordinator.record(
            learning_test_receipt(&f.coordinator, selection),
            /*now_unix_seconds*/ 20,
        )?;
        let operation = learning_updated_task_operation_id_v1(&f.coordinator)?;
        let request = support::request(
            &f.publication.target_config,
            f.runtime.handle.snapshot().await?,
        );
        let intent = request.intent()?;
        let receipt = f.runtime.handle.step(request.clone()).await?;
        assert!(matches!(
            receipt.disposition,
            CellGenerationDispositionV2::Advanced | CellGenerationDispositionV2::Stopped
        ));
        assert!(f.read_use(&f.coordinator, &intent).await.is_err());
        assert!(
            f.runtime
                .handle
                .read_learning_updated_next_use_readback(&f.coordinator, &baseline, &intent)
                .await
                .is_err()
        );
        let retained = (
            f.publication.bytes("current.json")?,
            f.publication.bytes("target-journal")?,
            f.publication.bytes("target-witness")?,
            f.publication.bytes("final-use/authority.claims")?,
        );
        let intent_digest = f.runtime.publication.intent_digest();
        tasks.shutdown().await;
        drop(f.runtime);
        drop(tasks);
        let ready = recover_agentd_generation_update_v1(
            f.publication.reopen_current()?,
            f.publication.authorities()?,
            f.publication.selection()?,
            f.publication.target_reopen()?,
            AgentdGenerationUpdateRecoveryV1 {
                operation_id: operation.to_string(),
                intent_digest,
            },
        )?;
        assert!(
            ready
                .read_learning_updated_next_use(&f.coordinator, &baseline, &intent)
                .is_err()
        );
        f.runtime = ready.into_runtime(
            support::next_config(&mut f.host, /*running_generation*/ 6).await?,
            f.control.clone(),
            f.host.clock(),
            AgentdGenerationUpdateRuntimeOptionsV1::default(),
        )?;
        let (mut tasks, _lifetime) = support::start(&mut f.runtime, &f.host)?;
        assert_eq!(f.runtime.handle.step(request).await?, receipt);
        assert!(f.read_use(&f.coordinator, &intent).await.is_err());
        assert_eq!(
            f.coordinator.next_stage(),
            Some(LearningIterationStageV1::NextUse)
        );
        assert_eq!(f.control.executions.load(Ordering::SeqCst), 1);
        assert_eq!(f.control.reads.load(Ordering::SeqCst), 0);
        assert_eq!(f.publication.authority.capacity()?.used_nonces, 1);
        assert_eq!(
            (
                f.publication.bytes("current.json")?,
                f.publication.bytes("target-journal")?,
                f.publication.bytes("target-witness")?,
                f.publication.bytes("final-use/authority.claims")?,
            ),
            retained
        );
        tasks.shutdown().await;
    }
    Ok(())
}
