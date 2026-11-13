//! Config-free factory custody mechanisms. These do not run a cross-process
//! task lane or count a published generation as completed task evidence.

use super::*;
use crate::PreparedRootHostCircuitTaskV1;

#[tokio::test]
#[ignore = "requires original Root host bind and actual signed owner fixtures"]
async fn root_host_task_factory_keeps_unstarted_source_incomplete() -> anyhow::Result<()> {
    let mut fixture = HostFixture::new("root-host-task-source-incomplete", OriginalHeadCase::Current).await?;
    let body: anyhow::Result<()> = (|| {
        let mut generation = fixture.bind()?;
        PreparedRootHostInitialGenerationV1::publish_original_generation(&mut generation)?;
        let published = PreparedRootHostInitialGenerationV1::read_original_generation(&generation)?;
        let (config, inputs, runtime, _request) = fixture.original.take_task_inputs(4)?;
        let task = PreparedRootHostInitialGenerationV1::prepare_original_root_task(generation, inputs)
            .map_err(|error| anyhow::anyhow!("{error}"))?;
        anyhow::ensure!(PreparedRootHostCircuitTaskV1::read_original_root_task_generation(&task)? == published,
            "the Root factory changed the actual protected operation");
        anyhow::ensure!(PreparedRootHostCircuitTaskV1::pending_original_root_task_operations(&task)? == 0,
            "the factory submitted work without the original signed ingress");
        let journal = fixture.original.generation_bytes()?;
        match PreparedRootHostCircuitTaskV1::drain_completed_original_root_task(&task) {
            Err(crate::AgentdError::Invalid(message)) if message == crate::CircuitTaskErrorV1::ReconciliationRequired.to_string() => {},
            Err(error) => anyhow::bail!("unrelated error did not prove missing original Source completion: {error}"),
            Ok(_) => anyhow::bail!("an unstarted Source was accepted as original task completion"),
        }
        anyhow::ensure!(PreparedRootHostCircuitTaskV1::read_original_root_task_generation(&task)? == published,
            "the Source refusal did not retain the same current original generation");
        anyhow::ensure!(fixture.original.generation_bytes()? == journal,
            "the Source refusal changed the original generation journal");
        anyhow::ensure!(config.identity() == &runtime.identity,
            "the original daemon Config identity changed");
        drop(task);
        drop(config);
        drop(runtime);
        Ok(())
    })();
    let cleanup = fixture.finish();
    body?;
    cleanup
}

#[tokio::test]
#[ignore = "requires original Root host bind and actual signed owner fixtures"]
async fn root_host_task_factory_refusal_retains_only_the_same_operation() -> anyhow::Result<()> {
    let mut fixture = HostFixture::new("root-host-task-factory-refusal", OriginalHeadCase::Current).await?;
    let body: anyhow::Result<()> = (|| {
        let mut generation = fixture.bind()?;
        PreparedRootHostInitialGenerationV1::publish_original_generation(&mut generation)?;
        let published = PreparedRootHostInitialGenerationV1::read_original_generation(&generation)?;
        let journal = fixture.original.generation_bytes()?;
        let (config, mut inputs, runtime, _request) = fixture.original.take_task_inputs(4)?;
        inputs.fence.generation = inputs.fence.generation.checked_add(1)
            .ok_or_else(|| anyhow::anyhow!("fixture generation overflow"))?;
        let error = match PreparedRootHostInitialGenerationV1::prepare_original_root_task(generation, inputs) {
            Ok(_) => anyhow::bail!("another generation entered the original task factory"),
            Err(error) => error,
        };
        anyhow::ensure!(error.generation_error().to_string().contains("invalid original owner or capacity"),
            "unexpected factory refusal: {error}");
        anyhow::ensure!(error.read_original_generation_after_installation_failure()? == published,
            "failed installation changed the retained original operation");
        anyhow::ensure!(fixture.original.generation_bytes()? == journal,
            "rejected task fence changed the published generation journal");
        drop(error);
        drop(config);
        drop(runtime);
        Ok(())
    })();
    let cleanup = fixture.finish();
    body?;
    cleanup
}
