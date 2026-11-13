//! Reopen the actual protected CURRENT and existing original journal after
//! dropping custody. Authorities remain the existing engineering fixtures;
//! these tests do not claim a complete Root process or daemon restart.

use super::*;
use codex_hepta_types::Digest32;
use crate::neuron_generation_current::NeuronGenerationCurrentOwnerV1;
use crate::neuron_generation_update::AgentdGenerationUpdateRecoveryV1;

fn reopened_current(fixture: &RootFixture) -> anyhow::Result<Arc<NeuronGenerationCurrentOwnerV1>> {
    let root = RootAuthorityDirectory::open(fixture.root_directory.path())?;
    Ok(Arc::new(NeuronGenerationCurrentOwnerV1::open(
        root, &fixture.providers.target_config.initial.scope,
    )?))
}

fn recovery(intent_digest: Digest32) -> AgentdGenerationUpdateRecoveryV1 {
    AgentdGenerationUpdateRecoveryV1 { operation_id: OPERATION.into(), intent_digest }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires actual RootAuthorityDirectory and original signed owner fixtures"]
async fn root_initial_cold_entry_reopens_existing_current_and_runs_the_original_task() -> anyhow::Result<()> {
    let mut fixture = RootFixture::new("root-custody-cold-original-task").await?;
    let mut old = fixture.custody()?;
    let signed = fixture.sign(&old)?;
    let intent = old.intent_digest();
    let binding = old.final_use_binding().clone();
    old.publish(&signed)?;
    let published = old.read_original_operation()?;
    let before = fixture.root_bytes()?;
    let target_before = fixture.generation_bytes()?;
    drop(old);

    let mut recovered = Custody::recover_from_original_current(
        reopened_current(&fixture)?, fixture.providers.authorities()?,
        fixture.providers.selection()?, fixture.providers.target_reopen()?, recovery(intent),
    )?;
    anyhow::ensure!(recovered.final_use_binding() == &binding);
    anyhow::ensure!(recovered.read_original_operation()? == published);
    anyhow::ensure!(fixture.root_bytes()? == before, "cold entry rewrote protected history");
    anyhow::ensure!(fixture.generation_bytes()? == target_before, "cold entry replaced the target");
    anyhow::ensure!(matches!(recovered.publish(&signed), Err(crate::AgentdError::Invalid(ref text))
        if text == "original publication was already consumed"), "cold entry must not expose Prepared");
    // No Source or Cell existed before this first installation. Create is the
    // explicit initial task lifecycle, not a fallback from a failed Recover.
    let session = fixture.start(recovered).await?;
    let result: anyhow::Result<()> = async {
        session.execute().await?;
        let completion = session.drain()?;
        let source = completion.source_publication();
        anyhow::ensure!(source.original_record().snapshot.run_id == fixture.source.scope.run_id);
        anyhow::ensure!(source.original_record().snapshot.objective_digest == fixture.source.objective_digest);
        anyhow::ensure!(source.bundle_digest() == fixture.bundle.digest()?);
        anyhow::ensure!(!source.output().is_empty(), "reopened original task has no result");
        anyhow::ensure!(session.installed.custody.read_original_operation()? == published);
        anyhow::ensure!(fixture.root_bytes()? == before, "task replaced the original publication");
        anyhow::ensure!(fixture.providers.authority.capacity()?.used_nonces == 1,
                        "recovery claimed another grant");
        Ok(())
    }.await;
    let cleanup = session.finish().await;
    result.and(cleanup)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires actual RootAuthorityDirectory and original signed owner fixtures"]
async fn root_initial_cold_entry_refuses_pending_without_reprepare_or_grant() -> anyhow::Result<()> {
    let fixture = RootFixture::new("root-custody-cold-pending").await?;
    let old = fixture.custody()?;
    let intent = old.intent_digest();
    drop(old);
    let before = fixture.root_bytes()?;
    let target_before = fixture.generation_bytes()?;
    let rejected = Custody::recover_from_original_current(
        reopened_current(&fixture)?, fixture.providers.authorities()?,
        fixture.providers.selection()?, fixture.providers.target_reopen()?, recovery(intent),
    );
    anyhow::ensure!(matches!(rejected, Err(crate::AgentdError::Invalid(ref text))
        if text == "initial generation remains pending; no redispatch"));
    anyhow::ensure!(fixture.root_bytes()? == before, "pending recovery rewrote Current");
    anyhow::ensure!(fixture.generation_bytes()? == target_before, "pending recovery recreated target");
    anyhow::ensure!(fixture.providers.authority.capacity()?.used_nonces == 0);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires actual RootAuthorityDirectory and original signed owner fixtures"]
async fn root_initial_cold_entry_rechecks_original_artifact_after_published_readback() -> anyhow::Result<()> {
    let fixture = RootFixture::new("root-custody-cold-withdrawn").await?;
    let mut old = fixture.custody()?;
    let signed = fixture.sign(&old)?;
    old.publish(&signed)?;
    let intent = old.intent_digest();
    let published = old.read_original_operation()?;
    let selected = fixture.providers.selection()?;
    drop(old);
    fixture.providers.withdraw()?;
    let current = reopened_current(&fixture)?;
    let operation = current.recover_initial_operation(OPERATION, intent)?;
    anyhow::ensure!(current.read_initial_operation(&operation)? == published);
    let before = fixture.root_bytes()?;
    let target_before = fixture.generation_bytes()?;
    let rejected = Custody::recover_from_original_current(
        current, fixture.providers.authorities()?, selected,
        fixture.providers.target_reopen()?, recovery(intent),
    );
    anyhow::ensure!(rejected.is_err(), "historical Published bypassed original Artifact withdrawal");
    anyhow::ensure!(fixture.root_bytes()? == before);
    anyhow::ensure!(fixture.generation_bytes()? == target_before);
    anyhow::ensure!(fixture.providers.authority.capacity()?.used_nonces == 1);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires actual RootAuthorityDirectory and original signed owner fixtures"]
async fn root_initial_cold_entry_retains_same_operation_after_installation_error() -> anyhow::Result<()> {
    let mut fixture = RootFixture::new("root-custody-cold-install-error").await?;
    let mut old = fixture.custody()?;
    let signed = fixture.sign(&old)?;
    let intent = old.intent_digest();
    old.publish(&signed)?;
    let published = old.read_original_operation()?;
    let (installed, _runtime, _request) = fixture.install(old, 0)?;
    let error = match installed {
        Ok(_) => anyhow::bail!("the original factory admitted zero capacity"),
        Err(error) => error,
    };
    anyhow::ensure!(error.read_original_operation()? == published);
    drop(error);
    let before = fixture.root_bytes()?;
    let target_before = fixture.generation_bytes()?;
    let mut recovered = Custody::recover_from_original_current(
        reopened_current(&fixture)?, fixture.providers.authorities()?,
        fixture.providers.selection()?, fixture.providers.target_reopen()?, recovery(intent),
    )?;
    anyhow::ensure!(recovered.read_original_operation()? == published);
    anyhow::ensure!(matches!(recovered.publish(&signed), Err(crate::AgentdError::Invalid(ref text))
        if text == "original publication was already consumed"));
    anyhow::ensure!(fixture.root_bytes()? == before);
    anyhow::ensure!(fixture.generation_bytes()? == target_before);
    anyhow::ensure!(fixture.providers.authority.capacity()?.used_nonces == 1);
    // Only generation custody is recovered. This case deliberately does not
    // retry Source Create or infer a missing Source from the installation error.
    Ok(())
}
