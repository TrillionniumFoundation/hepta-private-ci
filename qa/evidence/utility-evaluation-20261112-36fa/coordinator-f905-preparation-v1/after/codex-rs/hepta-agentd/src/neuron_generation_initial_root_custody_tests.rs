//! Actual protected Root CURRENT and the unchanged signed task execution path.
//! These are unexecuted engineering test cases, not deployment/quality evidence.

use super::*;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires actual RootAuthorityDirectory and original signed owner fixtures"]
async fn root_initial_custody_refuses_another_operation_without_rewriting_current() -> anyhow::Result<()> {
    let fixture = RootFixture::new("root-custody-wrong-operation").await?;
    let prepared = fixture.prepare_original()?;
    let before = fixture.root_bytes()?;
    let journal_before = fixture.generation_bytes()?;
    let rejected = Custody::from_original_prepared(prepared, "different-root-original-operation".into());
    anyhow::ensure!(matches!(rejected, Err(crate::AgentdError::Invalid(ref text))
        if text == "original initial generation operation cannot be recovered"),
        "a different operation must not borrow the original preparation");
    anyhow::ensure!(fixture.root_bytes()? == before, "original protected Current changed");
    anyhow::ensure!(fixture.generation_bytes()? == journal_before, "original target changed");
    anyhow::ensure!(fixture.providers.authority.capacity()?.used_nonces == 0, "no grant was consumed");
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires actual RootAuthorityDirectory and original signed owner fixtures"]
async fn root_initial_custody_failed_publish_keeps_only_same_operation_readback() -> anyhow::Result<()> {
    let fixture = RootFixture::new("root-custody-failed-publication").await?;
    let mut custody = fixture.custody()?;
    anyhow::ensure!(matches!(custody.read_original_operation()?, NeuronGenerationInitialReadbackV1::Prepared));
    let signed = fixture.sign(&custody)?;
    let mut damaged = signed.clone();
    anyhow::ensure!(!damaged.signature.is_empty(), "original issuer signature is complete");
    damaged.signature[0] ^= 1;
    let before = fixture.root_bytes()?;
    let journal_before = fixture.generation_bytes()?;
    let failure = custody.publish(&damaged);
    anyhow::ensure!(failure.is_err(), "the damaged original signature was admitted");
    anyhow::ensure!(matches!(custody.read_original_operation()?, NeuronGenerationInitialReadbackV1::Prepared));
    let repeated = custody.publish(&signed);
    anyhow::ensure!(matches!(repeated, Err(crate::AgentdError::Invalid(ref text))
        if text == "original publication was already consumed"),
        "an error must not return the consumed Prepared value");
    let recovery = custody.recover_original(fixture.providers.selection()?, fixture.providers.target_reopen()?);
    anyhow::ensure!(matches!(recovery, Err(crate::AgentdError::Invalid(ref text))
        if text == "initial generation remains pending; no redispatch"),
        "pending readback must not manufacture a Ready owner");
    anyhow::ensure!(fixture.root_bytes()? == before, "readback or rejection rewrote Current");
    anyhow::ensure!(fixture.generation_bytes()? == journal_before, "readback rewrote the original target");
    anyhow::ensure!(fixture.providers.authority.capacity()?.used_nonces == 0, "bad signature claimed a nonce");
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires actual RootAuthorityDirectory and original signed owner fixtures"]
async fn root_initial_custody_installs_the_original_task_and_drains_its_same_cell() -> anyhow::Result<()> {
    let mut fixture = RootFixture::new("root-custody-original-task").await?;
    let mut custody = fixture.custody()?;
    let signed = fixture.sign(&custody)?;
    custody.publish(&signed)?;
    let published = custody.read_original_operation()?;
    anyhow::ensure!(matches!(&published, NeuronGenerationInitialReadbackV1::Published(actual)
        if actual.signed_grant() == &signed), "the protected store did not retain the original publication");
    let repeated = custody.publish(&signed);
    anyhow::ensure!(matches!(repeated, Err(crate::AgentdError::Invalid(ref text))
        if text == "original publication was already consumed"));
    let before = fixture.root_bytes()?;
    let session = fixture.start(custody).await?;
    let result: anyhow::Result<()> = async {
        anyhow::ensure!(session.installed.custody.read_original_operation()? == published);
        anyhow::ensure!(session.drain().is_err(), "a task without original RunStart cannot complete");
        session.execute().await?;
        let completed = session.drain()?;
        let original = completed.source_publication();
        let expected_input = codex_hepta_neuron::CellStepInputV1 {
            operation_id: original.input().operation_id.clone(),
            scope: fixture.source.scope.clone(), source_frontier: fixture.source.source_frontier,
            objective_digest: fixture.source.objective_digest, ndu_snapshot_digest: fixture.source.ndu_snapshot_digest,
            monotonic_micros: fixture.source.monotonic_micros, deadline_micros: fixture.source.deadline_micros,
            observation: fixture.source.observation.clone(), candidates: fixture.source.candidates.clone(),
        };
        anyhow::ensure!(original.input() == &expected_input, "the actual original Cell input differs");
        anyhow::ensure!(original.original_record().snapshot.run_id == fixture.source.scope.run_id);
        anyhow::ensure!(original.original_record().snapshot.objective_digest == fixture.source.objective_digest);
        anyhow::ensure!(original.bundle_digest() == fixture.bundle.digest()?);
        anyhow::ensure!(!original.output().is_empty(), "no original Circuit result bytes");
        anyhow::ensure!(session.installed.custody.read_original_operation()? == published);
        anyhow::ensure!(fixture.root_bytes()? == before, "task execution changed its publication operation");
        anyhow::ensure!(fixture.providers.authority.capacity()?.used_nonces == 1, "publication claimed more than once");
        Ok(())
    }.await;
    let cleanup = session.finish().await;
    result.and(cleanup)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires actual RootAuthorityDirectory and original signed owner fixtures"]
async fn root_initial_custody_installation_error_retains_original_publication_readback() -> anyhow::Result<()> {
    let mut fixture = RootFixture::new("root-custody-installation-error").await?;
    let mut custody = fixture.custody()?;
    let signed = fixture.sign(&custody)?;
    custody.publish(&signed)?;
    let published = custody.read_original_operation()?;
    let before = fixture.root_bytes()?;
    let (installed, _runtime, _request) = fixture.install(custody, 0)?;
    let error = match installed {
        Ok(_) => anyhow::bail!("the original factory admitted a zero-capacity task"),
        Err(error) => error,
    };
    anyhow::ensure!(matches!(error.original_error(), crate::AgentdError::Invalid(_)));
    anyhow::ensure!(error.read_original_operation()? == published, "installation lost the same original operation");
    anyhow::ensure!(fixture.root_bytes()? == before, "installation rewrote its protected publication");
    anyhow::ensure!(fixture.providers.authority.capacity()?.used_nonces == 1);
    // Source/Cell files may already have been opened. No absence-of-effect or
    // automatic Create retry is inferred from the original installation error.
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires actual RootAuthorityDirectory and original signed owner fixtures"]
async fn root_initial_custody_original_artifact_withdrawal_fences_task_installation() -> anyhow::Result<()> {
    let mut fixture = RootFixture::new("root-custody-original-withdrawal").await?;
    let mut custody = fixture.custody()?;
    let signed = fixture.sign(&custody)?;
    custody.publish(&signed)?;
    let published = custody.read_original_operation()?;
    fixture.providers.withdraw()?;
    let before = fixture.root_bytes()?;
    let (installed, _runtime, _request) = fixture.install(custody, 4)?;
    let error = match installed {
        Ok(_) => anyhow::bail!("withdrawn original Artifact became a task"),
        Err(error) => error,
    };
    anyhow::ensure!(error.read_original_operation()? == published,
                    "historical Published fact must remain distinct from live admission");
    anyhow::ensure!(fixture.root_bytes()? == before, "withdrawal caused a replacement Current");
    anyhow::ensure!(fixture.providers.authority.capacity()?.used_nonces == 1);
    Ok(())
}
