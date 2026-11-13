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


/// This uses actual Fresh E/D/T/Candidate handlers and the original A's full
/// record as local trusted fixture data. It does not certify parent-before-
/// child preholding, cross-UID transport or deployed independent B.
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn fresh_original_b_inputs_keep_actual_source_history_when_objective_is_borrowed() -> anyhow::Result<()> {
    use super::super::evaluation_provider::fresh_training::{
        BorrowedOriginalObjective, CompletedTrainingInputs,
    };
    let mut fixture = Box::pin(FreshStages::new()).await?;
    let result: anyhow::Result<()> = async {
        Box::pin(fixture.complete_training()).await?;
        let before = fixture.original_bytes()?;
        let original = fixture.original()?;
        let record = original.previous.original_record();
        let objective = BorrowedOriginalObjective::from_preheld_compiled_objective(
            record.snapshot.objective_digest, &record.objective_semantic_bytes,
            record.objective_function_v1_digest, &record.objective_function_v1_bytes,
        )?;
        let dataset = fixture.dataset_receipt.as_ref().context("actual D")?;
        let training = fixture.training.as_ref().context("actual T")?;
        let candidate = fixture.candidate.as_ref().context("actual Candidate")?;
        let expected_history = original.previous.history_digest().as_str().parse::<Digest32>()?;
        let old = CompletedTrainingInputs::from_original_completion(
            &original.material, dataset, training, candidate, original.baseline.as_ref(),
            &original.previous, &original.source_a, &original.config_a, &original.credentials,
        )?;
        let received = CompletedTrainingInputs::from_preheld_objective_and_original_completion(
            &original.material, dataset, training, candidate, original.baseline.as_ref(),
            objective, &original.source_a, expected_history, &original.config_a, &original.credentials,
        )?;
        drop((old, received));

        anyhow::ensure!(CompletedTrainingInputs::from_preheld_objective_and_original_completion(
            &original.material, dataset, training, candidate, original.baseline.as_ref(),
            objective, &original.source_a, d("another-A-history"), &original.config_a, &original.credentials,
        ).is_err(), "full objective bytes cannot replace actual original A history");
        let mut wrong_source = original.source_a.clone();
        wrong_source.scope.run_id = id("another-original-A-run");
        anyhow::ensure!(CompletedTrainingInputs::from_preheld_objective_and_original_completion(
            &original.material, dataset, training, candidate, original.baseline.as_ref(),
            objective, &wrong_source, expected_history, &original.config_a, &original.credentials,
        ).is_err(), "actual D/T cannot be rebound to another source run");
        let mut wrong_input = original.source_a.clone();
        wrong_input.observation.push(0);
        anyhow::ensure!(CompletedTrainingInputs::from_preheld_objective_and_original_completion(
            &original.material, dataset, training, candidate, original.baseline.as_ref(),
            objective, &wrong_input, expected_history, &original.config_a, &original.credentials,
        ).is_err(), "same run and objective do not replace the original full A input");
        let mut changed_material = original.material.clone();
        changed_material.initial.request.completed_task_receipt = d("rewritten-Material-A-history");
        anyhow::ensure!(CompletedTrainingInputs::from_preheld_objective_and_original_completion(
            &changed_material, dataset, training, candidate, original.baseline.as_ref(),
            objective, &original.source_a, expected_history, &original.config_a, &original.credentials,
        ).is_err(), "actual original D still authenticates the complete original Material");
        let mut wrong_function = record.objective_function_v1_bytes.clone();
        wrong_function.push(0);
        anyhow::ensure!(BorrowedOriginalObjective::from_preheld_compiled_objective(
            record.snapshot.objective_digest, &record.objective_semantic_bytes,
            record.objective_function_v1_digest, &wrong_function,
        ).is_err(), "complete original objective function bytes remain mandatory");
        anyhow::ensure!(fixture.original_bytes()? == before,
            "borrowing objectives and rejected input substitutions do not change original evidence");
        Ok(())
    }.await;
    finish_case(result, fixture).await
}
