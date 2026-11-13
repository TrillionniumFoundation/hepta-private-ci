//! Uses the real original Root host and same-task Source/Cell fixture. The
//! local task path sends no new ready event, so this checks the existing-state
//! observation used by cold startup. It is not a process-cold or IPC result.

use super::*;
use crate::OriginalRootCircuitTaskCustodyV1;
use crate::circuit_task::original_prefreeze_source::test_support::EvidenceFixture;

#[tokio::test]
#[ignore = "requires original Root host bind and actual signed owner fixtures"]
async fn root_prefreeze_ready_reads_existing_source_without_future_event() -> anyhow::Result<()> {
    let mut fixture = HostFixture::new("root-prefreeze-existing-source", OriginalHeadCase::Current).await?;
    let mut task = None;
    let mut returned_host = None;
    let body: anyhow::Result<()> = async {
        let evidence = EvidenceFixture::new(fixture.original.source.clone(),
            crate::circuit_feature_task_digest_v1(&fixture.original.definition, &fixture.original.source)?,
            OPERATION, Digest32::from_array(fixture.binding.request_sha256))?;
        let mut generation = fixture.bind()?;
        PreparedRootHostInitialGenerationV1::publish_original_generation(&mut generation)?;
        let (config, inputs, runtime, request) = fixture.original.take_task_inputs(4)?;
        let (host, installed) = PreparedRootHostInitialGenerationV1::into_original_q24_task(generation, config, inputs)
            .map_err(|error| anyhow::anyhow!("{error}"))?;
        returned_host = Some(host);
        anyhow::ensure!(OriginalRootCircuitTaskCustodyV1::original_prefreeze_is_pending(
            &installed.custody, &evidence.request)?, "an unstarted Source was already complete");
        match OriginalRootCircuitTaskCustodyV1::require_original_completed_source(&installed.custody) {
            Err(crate::AgentdError::Invalid(message)) if message == crate::CircuitTaskErrorV1::ReconciliationRequired.to_string() => {},
            Err(error) => anyhow::bail!("unrelated original Source refusal: {error}"),
            Ok(_) => anyhow::bail!("the unstarted original Source was accepted"),
        }
        task = Some(start_original_task(installed, runtime, request).await?);
        let original = task.as_ref().ok_or_else(|| anyhow::anyhow!("original task missing"))?;
        original.execute().await?;
        let journal = fixture.original.generation_bytes()?;
        anyhow::ensure!(!OriginalRootCircuitTaskCustodyV1::original_prefreeze_is_pending(
            &original.installed.custody, &evidence.request)?, "completed existing Source waited for a future event");
        OriginalRootCircuitTaskCustodyV1::require_original_completed_source(&original.installed.custody)?;
        let first = OriginalRootCircuitTaskCustodyV1::read_original_prefreeze_source(
            &original.installed.custody, &evidence.request)?;
        let second = OriginalRootCircuitTaskCustodyV1::read_original_prefreeze_source(
            &original.installed.custody, &evidence.request)?;
        anyhow::ensure!(first == second, "same original complete Source payload changed");
        anyhow::ensure!(fixture.original.generation_bytes()? == journal, "readiness observation mutated the generation");
        Ok(())
    }.await;
    let task_cleanup = match task { Some(task) => task.finish().await, None => Ok(()) };
    drop(returned_host);
    let peer_cleanup = fixture.finish();
    body?;
    task_cleanup?;
    peer_cleanup
}
