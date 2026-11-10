//! Real actor/publication and synthetic separately signed evidence fixtures.
//! These tests do not qualify trained models or independent scientific owners.

use std::sync::Arc;
use std::sync::atomic::Ordering;
use std::sync::atomic::AtomicUsize;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_learning_artifacts::*;
use codex_hepta_learning_ledger::*;
use codex_hepta_neuron::*;
use codex_hepta_types::StableId;
use codex_hepta_types::Digest32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use super::support::{Fixture as EvidenceFixture, read_request, reply, response};
use crate::neuron_generation_current::test_support::Fixture as Publication;
use crate::neuron_generation_service::spawn_neuron_generation_service;
use crate::neuron_generation_update_bootstrap::{
    learning_test_baseline, learning_test_decision, learning_test_receipt,
};
use crate::*;

#[path = "neuron_generation_runtime_test_support.rs"]
// This reused fixture also defines helpers for the broader runtime suite.
#[allow(dead_code)]
mod host;

#[derive(Clone, Copy)]
enum Profile { Retained, Updated }

#[derive(Clone, Default)]
struct Control {
    calls: Arc<AtomicUsize>,
    reads: Arc<AtomicUsize>,
}

impl CellGenerationControlPortV2 for Control {
    fn execute_generation(
        &mut self, manifest: &CellBackendManifestV2, request: &CellGenerationRequestV2,
    ) -> Result<CellGenerationProposalV2, CellGenerationErrorV2> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        Ok(CellGenerationProposalV2 {
            request_digest: request.digest()?, bundle_digest: manifest.bundle_digest,
            runtime_digest: manifest.runtime_digest, device_digest: manifest.device_digest,
            successor_state: request.predecessor.state.clone(), output_delta: Vec::new(),
            disposition: CellGenerationDispositionV2::Stopped,
            cost: CellTaskCostV2::new(CellTaskCostIdentityV2 {
                task_digest: request.task_digest, source_digest: manifest.source_digest,
            }).map_err(|_| CellGenerationErrorV2::InvalidBinding)?,
        })
    }
    fn read_generation(
        &mut self, _request: &CellGenerationRequestV2,
    ) -> Result<Option<CellGenerationProposalV2>, CellGenerationErrorV2> {
        self.reads.fetch_add(1, Ordering::SeqCst);
        Ok(None)
    }
    fn cancel_generation(
        &mut self, _request: &CellGenerationRequestV2,
    ) -> Result<(), CellGenerationErrorV2> { Ok(()) }
}

struct Fixture {
    host: host::Fixture,
    publication: Publication,
    coordinator: LearningIterationCoordinatorV1,
    runtime: AgentdGenerationUpdateRuntimeV1,
    verifier: LearningEvidenceVerifierV1,
    profile: Profile,
    control: Control,
}

impl Fixture {
    async fn new(profile: Profile) -> anyhow::Result<Self> {
        let mut host = host::Fixture::new().await;
        let baseline = learning_test_baseline()?;
        let mut candidate = baseline.clone();
        candidate.artifact_id = StableId::new("fixture-rejected-candidate")?;
        candidate.generation = candidate.generation.next()?;
        candidate.rollback_predecessor = Some(baseline.digest()?);
        candidate.training_lineage = Some(CellTrainingLineageV1 {
            source_bundle: baseline.digest()?, dataset: d("dataset"),
            update_rule: d("update"), evaluation_profile: d("evaluation"),
        });
        host.config.manifest.bundle_digest = baseline.digest()?.into_array();
        host.config.manifest.encoder = Some(baseline.components.encoder.into_array());
        host.config.manifest.state_schema = baseline.components.state_schema.into_array();
        host.config.manifest.output_schema = baseline.components.output_schema.into_array();
        host.config.initial.manifest_digest = host.config.manifest.digest()?;
        let mut next = host.config.clone();
        next.initial.scope.run_id.push_str("-evidence-next");
        next.initial.generation += 1;
        next.initial.writer_epoch += 1;
        next.task_digest = d("different ordinary task").into_array();
        if matches!(profile, Profile::Updated) {
            next.manifest.bundle_digest = candidate.digest()?.into_array();
            next.initial.manifest_digest = next.manifest.digest()?;
        }
        let publication = Publication::new_with_target(host.config.clone(), next)?;
        let prior = learning_test_decision(&publication, baseline, "none")?;
        let verifier = verifier(prior.snapshot())?;
        let mut owners = prior.snapshot().owners.clone();
        owners.evidence_trust_digest = verifier.trust_digest();
        let mut coordinator = LearningIterationCoordinatorV1::new(
            prior.snapshot().request.clone(), owners,
        )?;
        for original in &prior.snapshot().receipts {
            let observation = if matches!(profile, Profile::Updated)
                && original.observation.stage() == LearningIterationStageV1::Evaluation
            {
                LearningIterationObservationV1::Evaluation {
                    candidate_bundle: candidate.digest()?,
                    evaluation_profile: d("evaluation"),
                    disposition: LearningEvaluationDispositionV1::Qualified,
                }
            } else { original.observation.clone() };
            coordinator.record(learning_test_receipt(&coordinator, observation), 20)?;
        }
        if matches!(profile, Profile::Updated) {
            coordinator.record(learning_test_receipt(&coordinator,
                LearningIterationObservationV1::Proposal {
                    candidate_bundle: candidate.digest()?,
                    proposal_id: coordinator.snapshot().request.operation_id.clone(),
                    composition_digest: d("proposal composition"),
                    disposition: LearningProposalDispositionV1::UpdateCandidates,
                }), 20)?;
        }
        let operation = match profile {
            Profile::Retained => learning_retained_task_operation_id_v1(&coordinator)?,
            Profile::Updated => learning_updated_task_operation_id_v1(&coordinator)?,
        };
        let request = AgentdGenerationUpdateRequestV1 { operation_id: operation.to_string() };
        let prepared = match profile {
            Profile::Retained => prepare_agentd_generation_same_model_task_v1(
                publication.current.clone(), publication.authorities()?, publication.stopped_old()?,
                publication.selection()?, publication.target_create()?, request,
            )?,
            Profile::Updated => prepare_agentd_generation_update_v1(
                publication.current.clone(), publication.authorities()?, publication.stopped_old()?,
                publication.selection()?, publication.target_create()?, request,
            )?,
        };
        let signed = publication.sign(prepared.final_use_binding())?;
        let ready = prepared.publish(&signed)?;
        for (generation, lifecycle) in [
            (2, AgentLifecycle::Draining), (3, AgentLifecycle::Stopped),
            (4, AgentLifecycle::Starting),
        ] {
            host.registry.compare_and_transition(&host.identity.agent_id, generation, lifecycle)?;
            if generation == 2 {
                host.state().refresh_generation()?;
                host.state().mark_draining()?;
            }
        }
        host.identity.spawn_generation = 5;
        let i = &host.identity;
        let config = AgentdConfig::load(
            i.fleet_root.clone(), i.agent_id.clone(), i.spawn_generation,
            i.home_root.clone(), i.run_root.clone(), i.home_root.clone(), i.workspace.clone(),
        )?;
        host.reopen_state().await;
        host.registry.compare_and_transition(&host.identity.agent_id, 5, AgentLifecycle::Running)?;
        host.state().refresh_generation()?;
        let control = Control::default();
        let runtime = ready.into_runtime(config, control.clone(), host.clock(),
            AgentdGenerationUpdateRuntimeOptionsV1::default())?;
        Ok(Self { host, publication, coordinator, runtime, verifier, profile, control })
    }

    fn start(&mut self) -> anyhow::Result<RuntimeTasks> {
        let bootstrap = self.runtime.config.take_neuron_generation_bootstrap()
            .ok_or_else(|| anyhow::anyhow!("missing original actor"))?;
        let (mut tasks, cancellation) = host::host();
        spawn_neuron_generation_service(
            &mut tasks, bootstrap, Arc::clone(self.host.state()), cancellation,
        )?;
        Ok(tasks)
    }

    fn read<'a>(&'a self, intent: Option<&'a CellGenerationIntentV2>) -> GenerationLearningStageReadV1<'a> {
        match (self.profile, intent) {
            (Profile::Retained, None) => GenerationLearningStageReadV1::RetainedSelection,
            (Profile::Retained, Some(intent)) => GenerationLearningStageReadV1::RetainedNextUse { intent },
            (Profile::Updated, None) => GenerationLearningStageReadV1::UpdatedSelection {
                previous_manifest: &self.publication.old_config.manifest,
            },
            (Profile::Updated, Some(intent)) => GenerationLearningStageReadV1::UpdatedNextUse {
                previous_manifest: &self.publication.old_config.manifest, intent,
            },
        }
    }

    fn retained_bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        ["current.json", "target-journal", "target-witness", "final-use/authority.claims"]
            .into_iter().map(|path| self.publication.bytes(path)).collect()
    }
}

fn d(label: &str) -> Digest32 { Digest32::of_bytes(label.as_bytes()) }

fn verifier(snapshot: &LearningIterationSnapshotV1) -> anyhow::Result<LearningEvidenceVerifierV1> {
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let scope = d("generation evidence fixture");
    Ok(LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: scope, objective_digest: snapshot.request.envelope.objective_digest,
        authority_epoch: 1,
        signers: [
            (snapshot.owners.selector.clone(), LearningEvidenceRoleV1::Selector, 71),
            (snapshot.owners.next_use_observer.clone(), LearningEvidenceRoleV1::Observer, 72),
        ].into_iter().map(|(actor, role, byte)| {
            let key = SigningKey::from_bytes(&[byte; 32]).verifying_key().to_bytes();
            TrustedLearningSignerV1 {
                principal: AuthenticatedPrincipalV1 {
                    principal_id: actor, credential_chain_digest: d("fixture credential"),
                    signing_key_digest: Digest32::of_bytes(&key), scope_digest: scope,
                    authority_epoch: 1, authenticated_at: now - 60, expires_at: now + 600,
                },
                controller_id: StableId::new(format!("fixture-controller-{byte}")).unwrap(),
                verifying_key: key, roles: vec![role], revoked_at: None,
            }
        }).collect(),
    })?)
}

fn evidence_fixture(
    f: &Fixture, receipt: LearningIterationReceiptV1,
) -> anyhow::Result<EvidenceFixture> {
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let (role, byte) = match receipt.observation.stage() {
        LearningIterationStageV1::Selection => (LearningEvidenceRoleV1::Selector, 71),
        _ => (LearningEvidenceRoleV1::Observer, 72),
    };
    let mut signature = SignedLearningEvidenceV1 {
        evidence_id: StableId::new("original-fixture-result")?,
        principal_id: receipt.actor_id.clone(), role, trust_digest: f.verifier.trust_digest(),
        scope_digest: d("generation evidence fixture"), objective_digest: f.verifier.objective_digest(),
        authority_epoch: 1, issued_at: now, expires_at: now + 600,
        payload_digest: Digest32::of_bytes(&learning_iteration_receipt_signing_bytes_v1(&receipt)?),
        signature: [0; 64],
    };
    signature.signature = SigningKey::from_bytes(&[byte; 32])
        .sign(&signature.signing_bytes()).to_bytes();
    Ok(EvidenceFixture {
        initial: LearningIterationCoordinatorV1::new(
            f.coordinator.snapshot().request.clone(), f.coordinator.snapshot().owners.clone(),
        )?.snapshot().clone(),
        receipt, verifier: f.verifier.clone(), signature,
    })
}

async fn authenticate(
    f: &Fixture, original: &EvidenceFixture, read: GenerationLearningStageReadV1<'_>,
) -> anyhow::Result<AuthenticatedGenerationLearningStageV1> {
    let receipt = &original.receipt;
    let (client, mut server) = original.client()?;
    let evidence = original.evidence();
    let owner = std::thread::spawn(move || -> anyhow::Result<()> {
        let request = read_request(&mut server)?;
        reply(&mut server, &response(request, evidence))
    });
    let result = read_generation_learning_stage_v1(GenerationLearningStageReadbackRequestV1 {
        runtime: &f.runtime.handle, snapshot: f.coordinator.snapshot(), receipt, read,
        verifier: &f.verifier,
    }, &client).await?;
    owner.join().expect("synthetic evidence owner")?;
    assert_eq!(result.attestation(), &original.signature);
    Ok(result)
}

#[tokio::test]
async fn retained_and_updated_original_evidence_survives_actor_and_runtime_reopen()
-> anyhow::Result<()> {
    for profile in [Profile::Retained, Profile::Updated] {
        let mut f = Fixture::new(profile).await?;
        let mut tasks = f.start()?;
        let selection = match profile {
            Profile::Retained => f.runtime.handle.read_learning_selection(&f.coordinator).await?,
            Profile::Updated => f.runtime.handle.read_learning_updated_selection(
                &f.coordinator, &f.publication.old_config.manifest,
            ).await?,
        };
        let receipt = learning_test_receipt(&f.coordinator, selection);
        let selection_evidence = evidence_fixture(&f, receipt.clone())?;
        let before = f.retained_bytes()?;
        assert_eq!(authenticate(&f, &selection_evidence, f.read(None)).await?.receipt(), &receipt);
        assert_eq!(f.retained_bytes()?, before);
        f.coordinator.record(receipt.clone(), 20)?;
        assert_eq!(authenticate(&f, &selection_evidence, f.read(None)).await?.receipt(), &receipt);
        let request = CellGenerationRequestV2 {
            operation_id: "next-use".into(), task_digest: f.publication.target_config.task_digest,
            source_frontier: f.publication.target_config.source_frontier,
            predecessor: f.runtime.handle.snapshot().await?, input: vec![1],
            admitted_at_micros: 10, deadline_micros: 10_000,
        };
        let intent = request.intent()?;
        let committed = f.runtime.handle.step(request.clone()).await?;
        let observation = match profile {
            Profile::Retained => f.runtime.handle.read_learning_next_use(&f.coordinator, &intent).await?,
            Profile::Updated => f.runtime.handle.read_learning_updated_next_use(
                &f.coordinator, &f.publication.old_config.manifest, &intent,
            ).await?,
        };
        let use_receipt = learning_test_receipt(&f.coordinator, observation);
        let use_evidence = evidence_fixture(&f, use_receipt.clone())?;
        let before = f.retained_bytes()?;
        assert_eq!(authenticate(&f, &use_evidence, f.read(Some(&intent))).await?.receipt(), &use_receipt);
        f.coordinator.record(use_receipt.clone(), 20)?;
        assert_eq!(f.coordinator.next_stage(), None);
        assert_eq!(authenticate(&f, &use_evidence, f.read(Some(&intent))).await?.receipt(), &use_receipt);
        assert_eq!(f.retained_bytes()?, before);
        assert_eq!(f.control.calls.load(Ordering::SeqCst), 1);
        assert_eq!(f.control.reads.load(Ordering::SeqCst), 0);
        assert_eq!(f.publication.authority.capacity()?.used_nonces, 1);
        let completed = f.coordinator.snapshot().clone();
        let publication = f.runtime.publication.clone();
        let operation = match profile {
            Profile::Retained => learning_retained_task_operation_id_v1(&f.coordinator)?,
            Profile::Updated => learning_updated_task_operation_id_v1(&f.coordinator)?,
        };
        let old_handle = f.runtime.handle.clone();
        let observed = f.runtime.handle.observe_generation().await?;
        let cost = f.runtime.handle.task_cost().await?;
        tasks.shutdown().await;
        drop(f.runtime);
        drop(tasks);
        assert!(old_handle.snapshot().await.is_err());
        drop(old_handle);

        // Neither a different operation nor a different intent may borrow the
        // published owner, and a refusal cannot create a replacement journal.
        for (operation_id, intent_digest) in [
            (format!("{operation}-substituted"), publication.intent_digest()),
            (operation.to_string(), d("substituted generation intent")),
        ] {
            assert!(recover_agentd_generation_update_v1(
                f.publication.reopen_current()?, f.publication.authorities()?,
                f.publication.selection()?, f.publication.target_reopen()?,
                AgentdGenerationUpdateRecoveryV1 { operation_id, intent_digest },
            ).is_err());
        }
        let ready = recover_agentd_generation_update_v1(
            f.publication.reopen_current()?, f.publication.authorities()?,
            f.publication.selection()?, f.publication.target_reopen()?,
            AgentdGenerationUpdateRecoveryV1 {
                operation_id: operation.to_string(), intent_digest: publication.intent_digest(),
            },
        )?;
        // Reopen the Fleet state with a fresh process generation, preserving
        // the same task publication rather than signing or resetting it again.
        for (generation, lifecycle) in [
            (6, AgentLifecycle::Draining), (7, AgentLifecycle::Stopped),
            (8, AgentLifecycle::Starting),
        ] {
            f.host.registry.compare_and_transition(&f.host.identity.agent_id, generation, lifecycle)?;
            if generation == 6 {
                f.host.state().refresh_generation()?;
                f.host.state().mark_draining()?;
            }
        }
        f.host.identity.spawn_generation = 9;
        let i = &f.host.identity;
        let config = AgentdConfig::load(
            i.fleet_root.clone(), i.agent_id.clone(), i.spawn_generation,
            i.home_root.clone(), i.run_root.clone(), i.home_root.clone(), i.workspace.clone(),
        )?;
        f.host.reopen_state().await;
        f.host.registry.compare_and_transition(&f.host.identity.agent_id, 9, AgentLifecycle::Running)?;
        f.host.state().refresh_generation()?;
        f.runtime = ready.into_runtime(config, f.control.clone(), f.host.clock(),
            AgentdGenerationUpdateRuntimeOptionsV1::default())?;
        f.coordinator = LearningIterationCoordinatorV1::from_snapshot(completed.clone())?;
        let mut tasks = f.start()?;
        assert_eq!(f.runtime.publication, publication);
        assert_eq!(f.runtime.handle.observe_generation().await?, observed);
        assert_eq!(f.runtime.handle.task_cost().await?, cost);

        // Both stages use exactly the signatures retained before shutdown.
        // Completed-history prefix reconstruction must not issue new evidence.
        assert_eq!(authenticate(&f, &selection_evidence, f.read(None)).await?.receipt(), &receipt);
        assert_eq!(authenticate(&f, &use_evidence, f.read(Some(&intent))).await?.receipt(), &use_receipt);
        assert_eq!(f.coordinator.snapshot(), &completed);
        assert_eq!(f.runtime.handle.step(request).await?, committed);

        let (client, mut server) = use_evidence.client()?;
        let mut wrong_intent = intent.clone();
        wrong_intent.task_digest = d("different next task").into_array();
        assert!(matches!(read_generation_learning_stage_v1(GenerationLearningStageReadbackRequestV1 {
            runtime: &f.runtime.handle, snapshot: f.coordinator.snapshot(), receipt: &use_receipt,
            read: f.read(Some(&wrong_intent)), verifier: &f.verifier,
        }, &client).await, Err(GenerationLearningStageReadbackErrorV1::Generation(_))));
        server.set_nonblocking(true)?;
        assert_eq!(std::io::Read::read(&mut server, &mut [0]).unwrap_err().kind(),
            std::io::ErrorKind::WouldBlock);
        assert_eq!(f.retained_bytes()?, before);
        assert_eq!((f.control.calls.load(Ordering::SeqCst), f.control.reads.load(Ordering::SeqCst)), (1, 0));
        assert_eq!(f.publication.authority.capacity()?.used_nonces, 1);
        tasks.shutdown().await;
    }
    Ok(())
}

#[tokio::test]
async fn substituted_receipt_and_unpublished_actor_never_contact_evidence_owner()
-> anyhow::Result<()> {
    let mut f = Fixture::new(Profile::Retained).await?;
    let (handle, bootstrap) = neuron_generation_channel_v2(
        &f.host.identity, f.host.journal_with("unpublished", f.host.config.clone()),
        f.host.control.clone(), f.host.clock(), 1,
    )?;
    let (mut tasks, cancellation) = host::host();
    spawn_neuron_generation_service(
        &mut tasks, bootstrap, Arc::clone(f.host.state()), cancellation,
    )?;
    let observation = LearningIterationObservationV1::Selection {
        candidate_bundle: f.coordinator.snapshot().request.selected_bundle.digest()?,
        selection_digest: d("not an original publication"),
    };
    let receipt = learning_test_receipt(&f.coordinator, observation);
    let fixture = evidence_fixture(&f, receipt.clone())?;
    let (client, mut server) = fixture.client()?;
    let result = read_generation_learning_stage_v1(GenerationLearningStageReadbackRequestV1 {
        runtime: &handle, snapshot: f.coordinator.snapshot(), receipt: &receipt,
        read: f.read(None), verifier: &f.verifier,
    }, &client).await;
    assert!(matches!(result, Err(GenerationLearningStageReadbackErrorV1::Generation(
        NeuronGenerationLearningReadErrorV1::Observation(AgentdError::GenerationFenced(_))
    ))));
    tasks.shutdown().await;
    let mut tasks = f.start()?;
    assert!(matches!(read_generation_learning_stage_v1(GenerationLearningStageReadbackRequestV1 {
        runtime: &f.runtime.handle, snapshot: f.coordinator.snapshot(), receipt: &receipt,
        read: f.read(None), verifier: &f.verifier,
    }, &client).await, Err(GenerationLearningStageReadbackErrorV1::Evidence(
        LearningIterationRuntimeErrorV1::WrongScope
    ))));
    let mut wrong = receipt.clone();
    wrong.actor_id = StableId::new("substitute-owner")?;
    assert!(read_generation_learning_stage_v1(GenerationLearningStageReadbackRequestV1 {
        runtime: &f.runtime.handle, snapshot: f.coordinator.snapshot(), receipt: &wrong,
        read: f.read(None), verifier: &f.verifier,
    }, &client).await.is_err());
    assert_eq!(f.control.calls.load(Ordering::SeqCst), 0);
    server.set_nonblocking(true)?;
    assert_eq!(std::io::Read::read(&mut server, &mut [0]).unwrap_err().kind(),
        std::io::ErrorKind::WouldBlock);
    tasks.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn revocation_during_attestation_read_is_rechecked_by_original_actor()
-> anyhow::Result<()> {
    let mut f = Fixture::new(Profile::Retained).await?;
    let mut tasks = f.start()?;
    let observation = f.runtime.handle.read_learning_selection(&f.coordinator).await?;
    let receipt = learning_test_receipt(&f.coordinator, observation);
    let fixture = evidence_fixture(&f, receipt.clone())?;
    let (client, mut server) = fixture.client()?;
    let evidence = fixture.evidence();
    let authority = Arc::clone(&f.publication.authority);
    let grant_id = f.runtime.publication.signed_grant().grant.grant_id.clone();
    let owner = std::thread::spawn(move || -> anyhow::Result<()> {
        let request = read_request(&mut server)?;
        let mut revoked = authority.revocation_head()?;
        revoked.revision += 1;
        revoked.revoked_grant_ids.insert(grant_id);
        authority.update_revocations(revoked)?;
        reply(&mut server, &response(request, evidence))
    });
    assert!(matches!(read_generation_learning_stage_v1(GenerationLearningStageReadbackRequestV1 {
        runtime: &f.runtime.handle, snapshot: f.coordinator.snapshot(), receipt: &receipt,
        read: f.read(None), verifier: &f.verifier,
    }, &client).await, Err(GenerationLearningStageReadbackErrorV1::Generation(_))));
    owner.join().expect("synthetic evidence owner")?;
    assert_eq!(f.control.calls.load(Ordering::SeqCst), 0);
    assert_eq!(f.publication.authority.capacity()?.used_nonces, 1);
    tasks.shutdown().await;
    Ok(())
}
