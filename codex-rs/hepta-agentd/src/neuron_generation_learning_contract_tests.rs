//! Contract regressions through the real publication, actor and cold readback.
//! Model computation and learning evidence remain explicitly synthetic.

use pretty_assertions::assert_eq;

use codex_hepta_neuron::FileAnchorWitnessStore;

use super::*;
use crate::AgentdError;
use crate::NeuronGenerationLearningReadErrorV1;
use crate::ReadyAgentdGenerationUpdateV1;

struct PublishedContractFixture {
    host: host::Fixture,
    publication: Fixture,
    coordinator: LearningIterationCoordinatorV1,
    ready: ReadyAgentdGenerationUpdateV1<FileAnchorWitnessStore>,
}

impl PublishedContractFixture {
    async fn new(
        change: impl FnOnce(&mut CellGenerationConfigV2, &mut CellGenerationConfigV2),
    ) -> anyhow::Result<Self> {
        let mut host = host::Fixture::new().await;
        let baseline = learning_test_baseline()?;
        let candidate = candidate(&baseline)?;
        bind_test_contract(&mut host.config, &baseline)?;
        let mut next = host.config.clone();
        next.initial.scope.run_id.push_str("-contract-next");
        next.initial.generation += 1;
        next.initial.writer_epoch += 1;
        next.task_digest = d("contract successor task").into_array();
        bind_test_contract(&mut next, &candidate)?;
        change(&mut host.config, &mut next);
        host.config.initial.manifest_digest = host.config.manifest.digest()?;
        next.initial.manifest_digest = next.manifest.digest()?;
        let publication = Fixture::new_with_target(host.config.clone(), next)?;
        let coordinator = decision(&publication, candidate, d("proposal composition"))?;
        let prepared = prepare_agentd_generation_update_v1(
            publication.current.clone(),
            publication.authorities()?,
            publication.stopped_old()?,
            publication.selection()?,
            publication.target_create()?,
            AgentdGenerationUpdateRequestV1 {
                operation_id: learning_updated_task_operation_id_v1(&coordinator)?.to_string(),
            },
        )?;
        let grant = publication.sign(prepared.final_use_binding())?;
        let ready = prepared.publish(&grant)?;
        Ok(Self {
            host,
            publication,
            coordinator,
            ready,
        })
    }
}

#[derive(Clone, Copy, Debug)]
enum ContractSide {
    Baseline,
    Candidate,
}

#[derive(Clone, Copy, Debug)]
enum ContractField {
    StateSchema,
    OutputSchema,
    Encoder,
}

#[tokio::test]
async fn published_contract_mismatch_cannot_become_selection_or_recovered_next_use()
-> anyhow::Result<()> {
    for side in [ContractSide::Baseline, ContractSide::Candidate] {
        for field in [
            ContractField::StateSchema,
            ContractField::OutputSchema,
            ContractField::Encoder,
        ] {
            let mut f = PublishedContractFixture::new(|baseline, candidate| {
                let manifest = match side {
                    ContractSide::Baseline => &mut baseline.manifest,
                    ContractSide::Candidate => &mut candidate.manifest,
                };
                let wrong = d("published incompatible contract").into_array();
                match field {
                    ContractField::StateSchema => manifest.state_schema = wrong,
                    ContractField::OutputSchema => manifest.output_schema = wrong,
                    ContractField::Encoder => manifest.encoder = Some(wrong),
                }
            })
            .await?;
            let field_name = match field {
                ContractField::StateSchema => "state schema",
                ContractField::OutputSchema => "output schema",
                ContractField::Encoder => "encoder",
            };
            let expected = format!("learning {field_name} differs from the published runtime");
            let previous_manifest = f.publication.old_config.manifest.clone();
            let selection_coordinator = f.coordinator.clone();
            assert!(matches!(
                f.ready.read_learning_updated_selection(&f.coordinator, &previous_manifest),
                Err(AgentdError::Invalid(message)) if message == expected
            ), "{side:?} {field:?}");

            let control = support::Control::default();
            let mut runtime = f.ready.into_runtime(
                support::next_config(&mut f.host, 2).await?,
                control.clone(),
                f.host.clock(),
                AgentdGenerationUpdateRuntimeOptionsV1::default(),
            )?;
            let (mut tasks, _lifetime) = support::start(&mut runtime, &f.host)?;
            assert!(matches!(
                runtime.handle.read_learning_updated_selection(&f.coordinator, &previous_manifest).await,
                Err(NeuronGenerationLearningReadErrorV1::Observation(AgentdError::Invalid(message)))
                    if message == expected
            ));

            // Simulate a persisted selection from an older reader. A matching
            // publication identity and committed work must not bypass the new
            // contract check at the independently recovered NextUse boundary.
            let selection = LearningIterationObservationV1::Selection {
                candidate_bundle: f.coordinator.next_task_bundle().unwrap().digest()?,
                selection_digest: runtime.publication.selection_observation_digest(),
            };
            f.coordinator.record(learning_test_receipt(&f.coordinator, selection), 20)?;
            let request = support::request(
                &f.publication.target_config,
                runtime.handle.snapshot().await?,
            );
            let intent = request.intent()?;
            runtime.handle.step(request).await?;
            assert!(matches!(
                runtime.handle.read_learning_updated_next_use(&f.coordinator, &previous_manifest, &intent).await,
                Err(NeuronGenerationLearningReadErrorV1::Observation(AgentdError::Invalid(message)))
                    if message == expected
            ));
            let observed = runtime.handle.observe_generation().await?;
            let chunk = observed.pending_output().cloned().unwrap();
            let output_path = f.host.directory.path().join("contract-output");
            std::fs::write(&output_path, &chunk.bytes)?;
            std::fs::File::open(&output_path)?.sync_all()?;
            std::fs::File::open(f.host.directory.path())?.sync_all()?;
            runtime.handle.acknowledge(
                chunk.clone(),
                Digest32::of_bytes(&chunk.bytes).into_array(),
                CellTaskCostV2::new(observed.cost().identity())?,
            ).await?;
            assert!(runtime.handle.drain().await?);
            let retained = (
                f.publication.bytes("current.json")?,
                f.publication.bytes("target-journal")?,
                f.publication.bytes("target-witness")?,
                f.publication.bytes("final-use/authority.claims")?,
            );
            let operation_id = runtime.publication.operation_id().to_owned();
            let intent_digest = runtime.publication.intent_digest();
            tasks.shutdown().await;
            drop(runtime);
            drop(tasks);
            f.coordinator = LearningIterationCoordinatorV1::from_snapshot(
                f.coordinator.snapshot().clone(),
            )?;
            let ready = recover_agentd_generation_update_v1(
                f.publication.reopen_current()?,
                f.publication.authorities()?,
                f.publication.selection()?,
                f.publication.target_reopen()?,
                AgentdGenerationUpdateRecoveryV1 { operation_id, intent_digest },
            )?;
            assert!(matches!(
                ready.read_learning_updated_selection(&selection_coordinator, &previous_manifest),
                Err(AgentdError::Invalid(message)) if message == expected
            ));
            assert!(matches!(
                ready.read_learning_updated_next_use(&f.coordinator, &previous_manifest, &intent),
                Err(AgentdError::Invalid(message)) if message == expected
            ));
            assert_eq!(
                (
                    control.executions.load(Ordering::SeqCst),
                    control.reads.load(Ordering::SeqCst),
                    f.publication.authority.capacity()?.used_nonces,
                ),
                (1, 0, 1)
            );
            assert_eq!(std::fs::read(output_path)?, chunk.bytes);
            assert_eq!(
                (
                    f.publication.bytes("current.json")?,
                    f.publication.bytes("target-journal")?,
                    f.publication.bytes("target-witness")?,
                    f.publication.bytes("final-use/authority.claims")?,
                ),
                retained
            );
        }
    }
    Ok(())
}

#[tokio::test]
async fn backend_without_encoder_retains_its_explicit_optional_contract() -> anyhow::Result<()> {
    let f = PublishedContractFixture::new(|baseline, candidate| {
        baseline.manifest.encoder = None;
        candidate.manifest.encoder = None;
    })
    .await?;
    assert!(matches!(
        f.ready.read_learning_updated_selection(&f.coordinator, &f.publication.old_config.manifest)?,
        LearningIterationObservationV1::Selection { candidate_bundle, .. }
            if candidate_bundle == f.coordinator.next_task_bundle().unwrap().digest()?
    ));
    Ok(())
}
