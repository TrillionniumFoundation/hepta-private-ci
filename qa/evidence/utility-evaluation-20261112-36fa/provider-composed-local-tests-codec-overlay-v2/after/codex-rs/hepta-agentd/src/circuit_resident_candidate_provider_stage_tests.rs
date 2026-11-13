//! Staged Fresh mechanism: no completed Positive/Publication fixture is used.
//! Original clocks, role credentials and independently fixed outcomes are test
//! data, not a real external B measurement or a deployed Root qualification.
use super::*;
use super::stages::{FreshStages, finish_case};
use anyhow::Context as _;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn fresh_original_training_produces_candidate_then_actual_ineligible_b() -> anyhow::Result<()> {
    let mut fixture = Box::pin(FreshStages::new()).await?;
    let result: anyhow::Result<()> = async {
        Box::pin(fixture.complete_training()).await?;
        let training = fixture.training.as_ref().context("actual Training")?.clone();
        anyhow::ensure!(matches!(
            fixture.root_trainer.as_ref().context("same T client")?
                .execute_training(Arc::new(AtomicBool::new(false))).await,
            Err(crate::OriginalCellQ24TrainingCommandErrorV1::ReadbackRequired)
        ), "Fresh Execute cannot be restored");
        anyhow::ensure!(fixture.root_trainer.as_ref().context("same T client")?
            .readback().await? == training);
        Box::pin(fixture.complete_b_and_evaluation()).await?;
        let original = fixture.evaluation.as_ref().context("actual E")?.clone();
        let before = fixture.original_bytes()?;
        anyhow::ensure!(matches!(
            fixture.root_evaluator.as_ref().context("same E client")?.execute_evaluation().await,
            Err(crate::OriginalCellEvaluationCommandErrorV1::ReadbackRequired)
        ), "completed E is not another Execute");
        anyhow::ensure!(fixture.root_evaluator.as_ref().context("same E client")?.readback().await? == original);
        anyhow::ensure!(fixture.original_bytes()? == before, "read-only repeats keep the complete originals");
        Ok(())
    }.await;
    finish_case(result, fixture).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn fresh_original_b_evaluation_recovery_reads_same_result_without_reexecution() -> anyhow::Result<()> {
    let mut fixture = Box::pin(FreshStages::new()).await?;
    let result: anyhow::Result<()> = async {
        Box::pin(fixture.complete_training()).await?;
        Box::pin(fixture.complete_b_and_evaluation()).await?;
        let original = fixture.evaluation.as_ref().context("actual E")?.clone();
        fixture.close_evaluation_clients()?;
        let before = fixture.original_bytes()?;
        fixture.panel.as_mut().context("same completed B panel")?.recover()?;
        let host = fixture.panel.as_ref().context("same recovered E")?.host.as_ref()
            .context("same actual E host")?;
        let (client, peer) = host.fixture_commands(false, None, "original")?;
        // This fresh-shaped caller cannot promote the recovered original host.
        let read: anyhow::Result<()> = async {
            anyhow::ensure!(matches!(client.execute_evaluation().await,
                Err(crate::OriginalCellEvaluationCommandErrorV1::ReadbackRequired)));
            anyhow::ensure!(client.readback().await? == original);
            Ok(())
        }.await;
        drop(client);
        let joined = peer.join().map_err(|_| anyhow::anyhow!("recovered E peer panicked"))?;
        read?;
        joined?;
        anyhow::ensure!(fixture.original_bytes()? == before, "recovery uses the same completed original files");
        Ok(())
    }.await;
    finish_case(result, fixture).await
}
