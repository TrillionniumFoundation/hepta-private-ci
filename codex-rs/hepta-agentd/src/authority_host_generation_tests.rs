//! Real protected-host composition mechanisms, not a useful A/B/C result or
//! process-cold deployment. No product issuer or original owner is substituted.

use super::*;

#[tokio::test]
#[ignore = "requires original Root host bind and actual signed owner fixtures"]
async fn root_host_initial_publication_enters_original_task_factory_and_drain() -> anyhow::Result<()> {
    let mut fixture = HostFixture::new("root-host-initial-task", OriginalHeadCase::Current).await?;
    let mut task = None;
    let mut returned_host = None;
    let body: anyhow::Result<()> = async {
        let names = fixture.protected_files()?;
        let target = fixture.original.generation_bytes()?;
        let mut generation = fixture.bind()?;
        anyhow::ensure!(fixture.protected_files()? == names, "binding created protected CURRENT state");
        anyhow::ensure!(fixture.original.generation_bytes()? == target, "binding modified the target");
        PreparedRootHostInitialGenerationV1::publish_original_generation(&mut generation)?;
        let observed = PreparedRootHostInitialGenerationV1::read_original_generation(&generation)?;
        let NeuronGenerationInitialReadbackV1::Published(published) = &observed else {
            anyhow::bail!("the original host did not read a published operation");
        };
        anyhow::ensure!(published.signed_grant() == &fixture.signed, "publication changed the original full grant");
        anyhow::ensure!(published.intent_digest() == Digest32::from_array(fixture.binding.request_sha256), "publication changed the original intent");
        let after = fixture.original.generation_bytes()?;
        anyhow::ensure!(PreparedRootHostInitialGenerationV1::publish_original_generation(&mut generation).is_err(), "the consumed attempt was dispatched again");
        anyhow::ensure!(fixture.original.generation_bytes()? == after, "rejected redispatch wrote the journal");
        let (config, inputs, runtime, request) = fixture.original.take_task_inputs(4)?;
        let (host, installed) = PreparedRootHostInitialGenerationV1::into_original_q24_task(generation, config, inputs)
            .map_err(|error| anyhow::anyhow!("{error}"))?;
        returned_host = Some(host);
        task = Some(start_original_task(installed, runtime, request).await?);
        let original = task.as_ref().ok_or_else(|| anyhow::anyhow!("task was not retained"))?;
        original.execute().await?;
        let first = original.drain()?;
        let second = original.drain()?;
        anyhow::ensure!(first.source_publication() == second.source_publication(), "same-Arc original Source publication changed");
        anyhow::ensure!(first.source_publication().bundle_digest() == fixture.original.bundle.digest()?, "completed Source used another model bundle");
        anyhow::ensure!(first.source_publication().input().scope == fixture.original.source.scope, "completed Source used another task scope");
        Ok(())
    }.await;
    let task_cleanup = match task { Some(task) => task.finish().await, None => Ok(()) };
    drop(returned_host);
    let peer_cleanup = fixture.finish();
    body?;
    task_cleanup?;
    peer_cleanup
}

#[tokio::test]
#[ignore = "requires original Root host bind and actual signed owner fixtures"]
async fn root_host_initial_binding_refuses_same_issuer_revoked_grant() -> anyhow::Result<()> {
    rejected_binding("root-host-initial-revoked", OriginalHeadCase::GrantRevoked,
        "original issuer revoked this generation grant").await
}

#[tokio::test]
#[ignore = "requires original Root host bind and actual signed owner fixtures"]
async fn root_host_initial_binding_refuses_stale_original_consumer_head() -> anyhow::Result<()> {
    rejected_binding("root-host-initial-stale-head", OriginalHeadCase::ConsumerStale,
        "original issuer, lease and existing consumer are not current").await
}

#[tokio::test]
#[ignore = "requires original Root host bind and actual signed owner fixtures"]
async fn root_host_initial_binding_refuses_another_complete_intent() -> anyhow::Result<()> {
    let mut fixture = HostFixture::new("root-host-initial-other-intent", OriginalHeadCase::Current).await?;
    let body: anyhow::Result<()> = (|| {
        let names = fixture.protected_files()?;
        let target = fixture.original.generation_bytes()?;
        fixture.inputs.as_mut().ok_or_else(|| anyhow::anyhow!("original inputs missing"))?
            .request.operation_id.push_str("-different");
        let error = match fixture.bind() {
            Ok(_) => anyhow::bail!("the full original signed intent was replaced"),
            Err(error) => error,
        };
        anyhow::ensure!(error.to_string().contains("initial generation differs from the registered host operation"), "unexpected original refusal: {error}");
        anyhow::ensure!(fixture.protected_files()? == names, "refused intent created protected CURRENT");
        anyhow::ensure!(fixture.original.generation_bytes()? == target, "refused intent modified target files");
        Ok(())
    })();
    let cleanup = fixture.finish();
    body?;
    cleanup
}

#[tokio::test]
#[ignore = "requires original Root host bind and actual signed owner fixtures"]
async fn root_host_initial_existing_state_reopens_after_old_session_is_dropped() -> anyhow::Result<()> {
    let mut fixture = HostFixture::new("root-host-initial-reopen", OriginalHeadCase::Current).await?;
    let body: anyhow::Result<()> = (|| {
        let mut original = fixture.bind()?;
        PreparedRootHostInitialGenerationV1::publish_original_generation(&mut original)?;
        let before = PreparedRootHostInitialGenerationV1::read_original_generation(&original)?;
        let journal = fixture.original.generation_bytes()?;
        drop(original);
        // This is an actual same-process protected owner reopen, explicitly
        // distinct from daemon/Root process restart and full ordinary recovery.
        let recovered = PreparedHostAuthoritySession::recover_original_initial_generation(
            fixture.session()?, fixture.recovery_inputs()?,
        )?;
        anyhow::ensure!(PreparedRootHostInitialGenerationV1::read_original_generation(&recovered)? == before, "cold entry substituted the original publication");
        anyhow::ensure!(fixture.original.generation_bytes()? == journal, "existing recovery rewrote generation evidence");
        drop(recovered);
        Ok(())
    })();
    let cleanup = fixture.finish();
    body?;
    cleanup
}

async fn rejected_binding(run: &str, head: OriginalHeadCase, expected: &str) -> anyhow::Result<()> {
    let mut fixture = HostFixture::new(run, head).await?;
    let body: anyhow::Result<()> = (|| {
        let names = fixture.protected_files()?;
        let target = fixture.original.generation_bytes()?;
        let consumer = fixture.consumer.current_external_frontier()?;
        let error = match fixture.bind() {
            Ok(_) => anyhow::bail!("original head refusal was bypassed"),
            Err(error) => error,
        };
        anyhow::ensure!(error.to_string().contains(expected), "unexpected original refusal: {error}");
        anyhow::ensure!(fixture.protected_files()? == names, "refused grant created protected CURRENT");
        anyhow::ensure!(fixture.original.generation_bytes()? == target, "refused grant modified target files");
        anyhow::ensure!(fixture.consumer.current_external_frontier()? == consumer, "binding refreshed or claimed the original consumer");
        Ok(())
    })();
    let cleanup = fixture.finish();
    body?;
    cleanup
}

#[tokio::test]
#[ignore = "requires original Root host bind and actual signed owner fixtures"]
async fn root_host_initial_request_reads_the_exact_binding_without_preparing() -> anyhow::Result<()> {
    let fixture = HostFixture::new("root-host-initial-request", OriginalHeadCase::Current).await?;
    let body: anyhow::Result<()> = (|| {
        let names = fixture.protected_files()?;
        let target = fixture.original.generation_bytes()?;
        let frontier = fixture.consumer.current_external_frontier()?;
        let session = fixture.session()?;
        let inputs = fixture.inputs.as_ref().ok_or_else(|| anyhow::anyhow!("original inputs missing"))?;
        let actual = PreparedHostAuthoritySession::original_initial_generation_request(
            &session, &inputs.selected, &inputs.target, &inputs.request,
        )?;
        anyhow::ensure!(actual == fixture.binding, "the original full request changed");
        anyhow::ensure!(actual == fixture.signed.grant.binding, "the original issuer signed another full request");
        anyhow::ensure!(fixture.protected_files()? == names, "request preview created CURRENT state");
        anyhow::ensure!(fixture.original.generation_bytes()? == target, "request preview wrote target files");
        anyhow::ensure!(fixture.consumer.current_external_frontier()? == frontier, "request preview consumed or refreshed authority");
        drop(session);
        Ok(())
    })();
    let cleanup = fixture.finish();
    body?;
    cleanup
}

async fn start_original_task(
    mut installed: Installed,
    runtime: RuntimeFixture,
    request: AuthBusObjectiveIngress,
) -> anyhow::Result<RootSession> {
    let (bootstrap, invocation) = installed.config.take_circuit_task_bootstrap()?
        .ok_or_else(|| anyhow::anyhow!("the actual host factory did not install a task"))?;
    runtime.state.attach_automation_store(AutomationStore::open(&runtime.identity.layout).await?)?;
    anyhow::ensure!(runtime.state.circuit_task.set(bootstrap.handle()).is_ok(), "one original task handle");
    anyhow::ensure!(runtime.state.circuit_task_invocation.set(invocation).is_ok(), "one original Source invocation");
    let cancellation = CancellationToken::new();
    let worker = tokio::spawn(bootstrap.run(Arc::clone(&runtime.state), cancellation.clone()));
    Ok(RootSession { runtime, request, installed, cancellation, worker: Some(worker) })
}
