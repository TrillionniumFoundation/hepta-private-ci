//! Opt-in actual model iteration with original learning authentication,
//! CURRENT publication, generation actor, ACK and protected-checkpoint codec.
//! All keys/custody are isolated research fixtures, never production authority.

use std::fs;
use std::sync::atomic::Ordering;
use std::sync::{Arc, Mutex};

use base64::Engine;
use codex_hepta_learning_artifacts::*;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_neuron::*;
use codex_hepta_types::{Digest32, Generation, StableId};
use serde_json::{Value, json};
use tokio_util::sync::CancellationToken;

use super::super::support as host;
use super::support;
use crate::AgentdConfig;
use crate::AgentdGenerationLearningUseReadbackV1;
use crate::AgentdGenerationUpdateRecoveryV1;
use crate::AgentdGenerationUpdateRequestV1;
use crate::AgentdGenerationUpdateRuntimeOptionsV1;
use crate::AgentdGenerationUpdateRuntimeV1;
use crate::AgentdState;
use crate::LearningIterationCheckpointOwnerV1;
use crate::LearningIterationOwnerFutureV1;
use crate::LearningIterationOwnerPortsV1;
use crate::LearningIterationRuntimeErrorV1;
use crate::NeuronGenerationRuntimeHandleV2;
use crate::PreparedLearningIterationProposalV1;
use crate::RuntimeTasks;
use crate::learning_iteration_channel_v1;
use crate::learning_retained_task_operation_id_v1;
use crate::neuron_generation_channel_v2;
use crate::neuron_generation_current::test_support::{Fixture, Journal};
use crate::neuron_generation_service::spawn_neuron_generation_service;
use crate::prepare_agentd_generation_same_model_task_v1;
use crate::recover_agentd_generation_update_v1;

#[path = "neuron_generation_real_learning_process.rs"]
mod process;
#[path = "neuron_generation_real_learning_trust.rs"]
mod trust;

use process::{Driver, ProcessControl, digest, monotonic, now, persist};
use trust::ResearchTrust;

fn d(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}
fn id(value: impl Into<String>) -> anyhow::Result<StableId> {
    Ok(StableId::new(value.into())?)
}
fn unavailable(error: impl std::fmt::Display) -> LearningIterationRuntimeErrorV1 {
    eprintln!("actual research learning owner refused: {error}");
    LearningIterationRuntimeErrorV1::OwnerUnavailable("actual-research-owner")
}

fn request(
    driver: &Driver,
    config: &CellGenerationConfigV2,
    predecessor: CellRuntimeSnapshotV2,
    label: &str,
) -> anyhow::Result<CellGenerationRequestV2> {
    let admitted = monotonic();
    anyhow::ensure!(admitted > 0, "actual boot clock unavailable");
    Ok(CellGenerationRequestV2 {
        operation_id: format!("{}-{label}", driver.operation),
        task_digest: config.task_digest,
        source_frontier: config.source_frontier,
        predecessor,
        input: serde_json::to_vec(
            &json!({"mode":"conditional_binary", "request_id":format!("{}-{label}", driver.operation),
            "prompt":driver.prepared["next_prompt"]}),
        )?,
        admitted_at_micros: admitted,
        deadline_micros: admitted
            .checked_add(90_000_000)
            .ok_or_else(|| anyhow::anyhow!("native deadline overflow"))?,
    })
}

async fn acknowledge(
    driver: &Driver,
    handle: &NeuronGenerationRuntimeHandleV2,
    label: &str,
) -> anyhow::Result<()> {
    let observed = handle.observe_generation().await?;
    let chunk = observed
        .pending_output()
        .cloned()
        .ok_or_else(|| anyhow::anyhow!("actual model output missing"))?;
    persist(
        &driver.evidence.join(format!("{label}-delivered.json")),
        &chunk.bytes,
    )?;
    handle
        .acknowledge(
            chunk.clone(),
            d(&chunk.bytes).into_array(),
            CellTaskCostV2::new(observed.cost().identity())?,
        )
        .await?;
    anyhow::ensure!(
        handle.drain().await?,
        "original actor did not drain after ACK"
    );
    Ok(())
}

struct Running {
    runtime: AgentdGenerationUpdateRuntimeV1,
    tasks: RuntimeTasks,
    _lifetime: CancellationToken,
    request: Option<CellGenerationRequestV2>,
    readback: Option<AgentdGenerationLearningUseReadbackV1>,
    coordinator: LearningIterationCoordinatorV1,
}

struct ResearchPorts {
    driver: Driver,
    trust: ResearchTrust,
    publication: Arc<Fixture>,
    old: Mutex<Option<Journal>>,
    config: Mutex<Option<AgentdConfig>>,
    state: Arc<AgentdState>,
    control: ProcessControl,
    checkpoint: Mutex<LearningIterationCheckpointOwnerV1>,
    receipts: Mutex<Vec<(LearningIterationReceiptV1, Value)>>,
    runtime: tokio::sync::Mutex<Option<Running>>,
    episode: Digest32,
    initial_head: Digest32,
}

impl ResearchPorts {
    async fn stage(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        stage: LearningIterationStageV1,
    ) -> anyhow::Result<(LearningIterationObservationV1, Value)> {
        let coordinator = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
        let reference = |name: &str, value: Value| -> anyhow::Result<Value> {
            let path = self.driver.evidence.join(name);
            let bytes = serde_json::to_vec(&value)?;
            persist(&path, &bytes)?;
            Ok(
                json!({"path":path,"sha256":d(&bytes).to_string(),"bytes":bytes.len(),"native_owner":true}),
            )
        };
        match stage {
            LearningIterationStageV1::Experience => Ok((
                LearningIterationObservationV1::Experience {
                    episode_digest: self.episode,
                    completed_task_receipt: snapshot.request.completed_task_receipt,
                },
                reference(
                    "experience.json",
                    json!({"completed_task_receipt":snapshot.request.completed_task_receipt.to_string(),
                "episode_digest":self.episode.to_string(),"frozen_plan":self.driver.frozen}),
                )?,
            )),
            LearningIterationStageV1::Dataset => Ok((
                LearningIterationObservationV1::Dataset {
                    snapshot_digest: digest(&self.driver.prepared["dataset"]["sha256"])?,
                    episode_digest: self.episode,
                    withdrawal_frontier: d(
                        b"public-synthetic-research-source-no-private-subjects-v1",
                    ),
                    rows: u32::try_from(
                        self.driver.prepared["dataset_rows"]
                            .as_u64()
                            .ok_or_else(|| anyhow::anyhow!("dataset rows"))?,
                    )?,
                    bytes: self.driver.prepared["dataset_bytes"]
                        .as_u64()
                        .ok_or_else(|| anyhow::anyhow!("dataset bytes"))?,
                },
                reference("dataset.json", self.driver.prepared["dataset"].clone())?,
            )),
            LearningIterationStageV1::Training => {
                let driver = self.driver.clone();
                let admission = json!({"initial_learning_head":self.initial_head.to_string(),"dataset_learning_head":snapshot.head_digest.to_string()});
                let response =
                    tokio::task::spawn_blocking(move || driver.run("train", admission, None))
                        .await??;
                let result = &response["result"];
                let mut candidate = snapshot.request.selected_bundle.clone();
                candidate.artifact_id = id(format!("{}-trained", self.driver.operation))?;
                candidate.generation = candidate.generation.next()?;
                candidate.components.cell_adapter = Some(digest(&result["candidate"]["adapter"])?);
                candidate.components.composition = digest(&result["candidate"]["contract"])?;
                let source_bundle = snapshot.request.selected_bundle.digest()?;
                candidate.rollback_predecessor = Some(source_bundle);
                candidate.training_lineage = Some(CellTrainingLineageV1 {
                    source_bundle,
                    dataset: digest(&result["dataset_sha256"])?,
                    update_rule: digest(&result["source_digest"])?,
                    evaluation_profile: snapshot.request.evaluation_profile,
                });
                Ok((
                    LearningIterationObservationV1::Training {
                        candidate: Box::new(candidate),
                        steps: result["steps"]
                            .as_u64()
                            .ok_or_else(|| anyhow::anyhow!("actual steps"))?,
                        milliseconds: result["milliseconds"]
                            .as_u64()
                            .ok_or_else(|| anyhow::anyhow!("actual training time"))?,
                        artifact_bytes: result["artifact_bytes"]
                            .as_u64()
                            .ok_or_else(|| anyhow::anyhow!("actual artifact bytes"))?,
                    },
                    response["evidence"].clone(),
                ))
            }
            LearningIterationStageV1::Evaluation => {
                let driver = self.driver.clone();
                let response =
                    tokio::task::spawn_blocking(move || driver.run("evaluate", json!({}), None))
                        .await??;
                anyhow::ensure!(
                    response["result"]["disposition"] == "NoUpdate",
                    "actual candidate was not rejected; this research driver has no proposal authority"
                );
                anyhow::ensure!(
                    digest(&response["result"]["candidate"]["adapter"])?
                        == coordinator
                            .candidate()
                            .and_then(|c| c.components.cell_adapter)
                            .ok_or_else(|| anyhow::anyhow!("actual candidate binding"))?,
                    "evaluation used another artifact"
                );
                Ok((
                    LearningIterationObservationV1::Evaluation {
                        candidate_bundle: coordinator
                            .candidate()
                            .ok_or_else(|| anyhow::anyhow!("candidate"))?
                            .digest()?,
                        evaluation_profile: snapshot.request.evaluation_profile,
                        disposition: LearningEvaluationDispositionV1::NoUpdate,
                    },
                    response["evidence"].clone(),
                ))
            }
            LearningIterationStageV1::Selection => {
                let old = self
                    .old
                    .lock()
                    .map_err(|_| anyhow::anyhow!("old owner poisoned"))?
                    .take()
                    .ok_or_else(|| anyhow::anyhow!("old owner already handed off"))?;
                let config = self
                    .config
                    .lock()
                    .map_err(|_| anyhow::anyhow!("config poisoned"))?
                    .take()
                    .ok_or_else(|| anyhow::anyhow!("runtime config already handed off"))?;
                let prepared = prepare_agentd_generation_same_model_task_v1(
                    self.publication.current.clone(),
                    self.publication.authorities()?,
                    old,
                    self.publication.selection()?,
                    self.publication.target_create()?,
                    AgentdGenerationUpdateRequestV1 {
                        operation_id: learning_retained_task_operation_id_v1(&coordinator)?
                            .to_string(),
                    },
                )?;
                let signed = self.publication.sign(prepared.final_use_binding())?;
                let ready = prepared.publish(&signed)?;
                let mut runtime = ready.into_runtime(
                    config,
                    self.control.clone(),
                    monotonic,
                    AgentdGenerationUpdateRuntimeOptionsV1::default(),
                )?;
                let bootstrap = runtime
                    .config
                    .take_neuron_generation_bootstrap()
                    .ok_or_else(|| anyhow::anyhow!("missing ordinary actor bootstrap"))?;
                let (mut tasks, lifetime) = host::host();
                spawn_neuron_generation_service(
                    &mut tasks,
                    bootstrap,
                    Arc::clone(&self.state),
                    lifetime.clone(),
                )?;
                let observation = runtime.handle.read_learning_selection(&coordinator).await?;
                let evidence = reference(
                    "selection-owner.json",
                    json!({"current":serde_json::from_slice::<Value>(&self.publication.bytes("current.json")?)?,
                    "signed_grant":runtime.publication.signed_grant(),"publication":runtime.publication.publication_digest()?.to_string()}),
                )?;
                *self.runtime.lock().await = Some(Running {
                    runtime,
                    tasks,
                    _lifetime: lifetime,
                    request: None,
                    readback: None,
                    coordinator: coordinator.clone(),
                });
                Ok((observation, evidence))
            }
            LearningIterationStageV1::NextUse => {
                let mut running = self
                    .runtime
                    .lock()
                    .await
                    .take()
                    .ok_or_else(|| anyhow::anyhow!("missing selected actor"))?;
                let request = request(
                    &self.driver,
                    &self.publication.target_config,
                    running.runtime.handle.snapshot().await?,
                    "next-task",
                )?;
                let intent = request.intent()?;
                anyhow::ensure!(
                    running
                        .runtime
                        .handle
                        .read_learning_next_use(&coordinator, &intent)
                        .await
                        .is_err(),
                    "uncommitted use must be refused"
                );
                let receipt = running.runtime.handle.step(request.clone()).await?;
                let pending = running
                    .runtime
                    .handle
                    .read_learning_next_use_readback(&coordinator, &intent)
                    .await?;
                persist(
                    &self.driver.evidence.join("next-use-pending.json"),
                    &serde_json::to_vec(&pending)?,
                )?;
                acknowledge(&self.driver, &running.runtime.handle, "next-use").await?;
                let observation = running
                    .runtime
                    .handle
                    .read_learning_next_use(&coordinator, &intent)
                    .await?;
                let readback = running
                    .runtime
                    .handle
                    .read_learning_next_use_readback(&coordinator, &intent)
                    .await?;
                persist(
                    &self.driver.evidence.join("next-use-acked.json"),
                    &serde_json::to_vec(&readback)?,
                )?;
                let evidence = reference(
                    "next-use-owner.json",
                    json!({"readback":readback,
                    "original_generation_request":request,"receipt":receipt,"native_nonce_count":self.publication.authority.capacity()?.used_nonces}),
                )?;
                running.request = Some(request);
                running.readback = Some(readback);
                running.coordinator = coordinator;
                *self.runtime.lock().await = Some(running);
                Ok((observation, evidence))
            }
            LearningIterationStageV1::Proposal => {
                anyhow::bail!("NoUpdate never publishes a candidate proposal")
            }
        }
    }

    async fn cold_reopen(
        &self,
        host: &mut host::Fixture,
        finished: &LearningIterationSnapshotV1,
    ) -> anyhow::Result<()> {
        let mut running = self
            .runtime
            .lock()
            .await
            .take()
            .ok_or_else(|| anyhow::anyhow!("selected owner missing"))?;
        let request = running
            .request
            .take()
            .ok_or_else(|| anyhow::anyhow!("original next task missing"))?;
        let readback = running
            .readback
            .take()
            .ok_or_else(|| anyhow::anyhow!("original next use missing"))?;
        let coordinator = running.coordinator.clone();
        let intent = request.intent()?;
        let receipt = running.runtime.handle.step(request.clone()).await?;
        let observation = running
            .runtime
            .handle
            .read_learning_next_use(&coordinator, &intent)
            .await?;
        anyhow::ensure!(
            finished
                .receipts
                .last()
                .is_some_and(|last| last.observation == observation),
            "completed learning checkpoint does not contain the actual use"
        );
        let retained = [
            self.publication.bytes("current.json")?,
            self.publication.bytes("target-journal")?,
            self.publication.bytes("target-witness")?,
            self.publication.bytes("final-use/authority.claims")?,
        ];
        let intent_digest = running.runtime.publication.intent_digest();
        running.tasks.shutdown().await;
        drop(running);
        // The original learning owner is already complete and stopped. Rebuild
        // the Fleet lifecycle and AgentdState through the retained native test
        // path; no live service or startup/retirement fence is bypassed.
        let ready = recover_agentd_generation_update_v1(
            self.publication.reopen_current()?,
            self.publication.authorities()?,
            self.publication.selection()?,
            self.publication.target_reopen()?,
            AgentdGenerationUpdateRecoveryV1 {
                operation_id: learning_retained_task_operation_id_v1(&coordinator)?.to_string(),
                intent_digest,
            },
        )?;
        let running_generation = host
            .identity
            .spawn_generation
            .checked_add(1)
            .ok_or_else(|| anyhow::anyhow!("Fleet generation overflow"))?;
        let config = support::next_config(host, running_generation).await?;
        let mut runtime = ready.into_runtime(
            config,
            self.control.clone(),
            monotonic,
            AgentdGenerationUpdateRuntimeOptionsV1::default(),
        )?;
        let bootstrap = runtime
            .config
            .take_neuron_generation_bootstrap()
            .ok_or_else(|| anyhow::anyhow!("missing recovered actor"))?;
        let (mut tasks, lifetime) = host::host();
        spawn_neuron_generation_service(
            &mut tasks,
            bootstrap,
            Arc::clone(host.state()),
            lifetime.clone(),
        )?;
        anyhow::ensure!(
            runtime.handle.step(request.clone()).await? == receipt,
            "cold native receipt differs"
        );
        anyhow::ensure!(
            runtime
                .handle
                .read_learning_next_use(&coordinator, &intent)
                .await?
                == observation,
            "cold use differs"
        );
        anyhow::ensure!(
            runtime
                .handle
                .read_learning_next_use_readback(&coordinator, &intent)
                .await?
                == readback,
            "cold raw readback differs"
        );
        anyhow::ensure!(
            retained
                == [
                    self.publication.bytes("current.json")?,
                    self.publication.bytes("target-journal")?,
                    self.publication.bytes("target-witness")?,
                    self.publication.bytes("final-use/authority.claims")?
                ],
            "recovery rewrote native owner files"
        );
        let driver = self.driver.clone();
        let inputs = self.control.model_request(&request)?;
        let cold = tokio::task::spawn_blocking(move || driver.run("probe_recover", inputs, None))
            .await??;
        anyhow::ensure!(
            cold["result"]["new_forward_calls"] == 0,
            "cold worker executed another forward"
        );
        persist(
            &self.driver.evidence.join("next-use-cold-owner.json"),
            &serde_json::to_vec(&json!({"readback":readback,"worker_recovery":cold,
                "original_generation_request":request,"receipt":receipt,
                "reopened_spawn_generation":host.identity.spawn_generation,
                "native_nonce_count":self.publication.authority.capacity()?.used_nonces,
                "native_daemon_os_restart":false}))?,
        )?;
        *self.runtime.lock().await = Some(Running {
            runtime,
            tasks,
            _lifetime: lifetime,
            request: Some(request),
            readback: Some(readback),
            coordinator,
        });
        Ok(())
    }

    fn verify_reference(&self, reference: &Value) -> anyhow::Result<()> {
        if reference["native_owner"] == true {
            let path = std::path::PathBuf::from(
                reference["path"]
                    .as_str()
                    .ok_or_else(|| anyhow::anyhow!("native evidence path"))?,
            );
            anyhow::ensure!(
                path.canonicalize()?
                    .starts_with(self.driver.evidence.canonicalize()?),
                "foreign native evidence"
            );
            anyhow::ensure!(
                d(&fs::read(path)?) == digest(&reference["sha256"])?,
                "changed native owner receipt"
            );
        } else {
            self.driver.verify_evidence(reference)?;
        }
        Ok(())
    }
}

impl LearningIterationOwnerPortsV1 for ResearchPorts {
    fn restore<'a>(
        &'a self,
        request: &'a LearningIterationRequestV1,
    ) -> LearningIterationOwnerFutureV1<'a, Option<LearningIterationSnapshotV1>> {
        Box::pin(async move {
            self.checkpoint
                .lock()
                .map_err(unavailable)?
                .restore(request)
                .map_err(unavailable)
        })
    }
    fn checkpoint<'a>(
        &'a self,
        expected: Digest32,
        snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, Digest32> {
        Box::pin(async move {
            let head = self
                .checkpoint
                .lock()
                .map_err(unavailable)?
                .checkpoint(expected, snapshot)
                .map_err(unavailable)?;
            // Read the exact bytes just acknowledged by the original CAS owner.
            // Preserve initial/Selection/final cuts; collectors never re-encode
            // or truncate a completed snapshot into purported earlier evidence.
            let bytes = self
                .publication
                .bytes("learning-checkpoint")
                .map_err(unavailable)?;
            let path = self.driver.evidence.join(format!(
                "native-checkpoint-{}-owner.json",
                snapshot.receipts.len()
            ));
            if path.exists() {
                if fs::read(&path).map_err(unavailable)? != bytes {
                    return Err(LearningIterationRuntimeErrorV1::CommitUncertain);
                }
            } else {
                persist(&path, &bytes).map_err(unavailable)?;
            }
            Ok(head)
        })
    }
    fn execute_stage<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
        stage: LearningIterationStageV1,
    ) -> LearningIterationOwnerFutureV1<'a, LearningIterationReceiptV1> {
        Box::pin(async move {
            let (observation, reference) =
                self.stage(snapshot, stage).await.map_err(unavailable)?;
            self.verify_reference(&reference).map_err(unavailable)?;
            let receipt = LearningIterationReceiptV1 {
                operation_id: snapshot.request.operation_id.clone(),
                predecessor: snapshot.head_digest,
                actor_id: snapshot.owners.owner(stage).clone(),
                evidence_digest: digest(&reference["sha256"]).map_err(unavailable)?,
                observed_unix_seconds: now().map_err(unavailable)?,
                observation,
            };
            self.receipts
                .lock()
                .map_err(unavailable)?
                .push((receipt.clone(), reference));
            Ok(receipt)
        })
    }
    fn prepare_proposal<'a>(
        &'a self,
        _snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, PreparedLearningIterationProposalV1> {
        Box::pin(async {
            Err(LearningIterationRuntimeErrorV1::OwnerUnavailable(
                "research has no proposal authority",
            ))
        })
    }
    fn receipt_attestation<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
        receipt: &'a LearningIterationReceiptV1,
        _now: u64,
    ) -> LearningIterationOwnerFutureV1<'a, SignedLearningEvidenceV1> {
        Box::pin(async move {
            let reference = self
                .receipts
                .lock()
                .map_err(unavailable)?
                .iter()
                .find(|(actual, _)| actual == receipt)
                .map(|(_, reference)| reference.clone())
                .ok_or(LearningIterationRuntimeErrorV1::OwnerUnavailable(
                    "receipt not owned by this actual run",
                ))?;
            self.verify_reference(&reference).map_err(unavailable)?;
            if matches!(
                receipt.observation.stage(),
                LearningIterationStageV1::Selection | LearningIterationStageV1::NextUse
            ) {
                let mut predecessor = snapshot.clone();
                let count = predecessor
                    .receipts
                    .iter()
                    .position(|r| r == receipt)
                    .unwrap_or(predecessor.receipts.len());
                predecessor.receipts.truncate(count);
                predecessor.head_digest = receipt.predecessor;
                let coordinator = LearningIterationCoordinatorV1::from_snapshot(predecessor)?;
                let guard = self.runtime.lock().await;
                let runtime =
                    guard
                        .as_ref()
                        .ok_or(LearningIterationRuntimeErrorV1::OwnerUnavailable(
                            "actual generation owner unavailable",
                        ))?;
                let actual = if receipt.observation.stage() == LearningIterationStageV1::Selection {
                    runtime
                        .runtime
                        .handle
                        .read_learning_selection(&coordinator)
                        .await
                        .map_err(unavailable)?
                } else {
                    let intent = runtime
                        .request
                        .as_ref()
                        .ok_or(LearningIterationRuntimeErrorV1::OwnerUnavailable(
                            "actual task missing",
                        ))?
                        .intent()
                        .map_err(unavailable)?;
                    runtime
                        .runtime
                        .handle
                        .read_learning_next_use(&coordinator, &intent)
                        .await
                        .map_err(unavailable)?
                };
                if actual != receipt.observation {
                    return Err(LearningIterationRuntimeErrorV1::OwnerUnavailable(
                        "live owner observation changed",
                    ));
                }
            }
            self.trust.sign(receipt).map_err(unavailable)
        })
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "explicit pinned local model, research directory and process budget required"]
async fn actual_smollm_training_no_update_native_next_use_and_cold_readback() -> anyhow::Result<()>
{
    let driver = Driver::open()?;
    let prepared = &driver.prepared;
    let mut host = host::Fixture::new().await;
    host.directory.disable_cleanup(true);
    let baseline = CellCompatibilityBundleV1 {
        artifact_id: id(format!("{}-retained", driver.operation))?,
        generation: Generation::new(
            prepared["parent"]["generation"]
                .as_u64()
                .ok_or_else(|| anyhow::anyhow!("parent generation"))?,
        )?,
        components: CellBundleComponentsV1 {
            base: digest(&prepared["model_config"]["material_manifest_sha256"])?,
            organ_adapter: None,
            cell_adapter: Some(digest(&prepared["parent"]["adapter"])?),
            heads: d(b"yes:10407,no:4607/raw-logit-q32"),
            composition: digest(&prepared["parent"]["contract"])?,
            encoder: digest(&prepared["model_config"]["material_manifest_sha256"])?,
            tokenizer: digest(&prepared["model_config"]["material_manifest_sha256"])?,
            normalizer: d(b"identity-no-model-normalization-v1"),
            calibration: digest(&prepared["evaluation_profile_sha256"])?,
            numeric_profile: digest(&prepared["helper_sha256"])?,
            output_schema: d(b"hepta.research.smollm.actual-proposal.v1"),
            state_schema: d(b"research-stateless-conditional-binary-input.v1"),
            state_semantics: d(b"complete-input-retention-no-hidden-recurrent-state-v1"),
        },
        training_lineage: None,
        rollback_predecessor: None,
    };
    let manifest = &mut host.config.manifest;
    manifest.profile = "research-smollm-process-v1".into();
    manifest.source_digest = digest(&prepared["source_digest"])?.into_array();
    manifest.bundle_digest = baseline.digest()?.into_array();
    manifest.encoder = Some(baseline.components.encoder.into_array());
    manifest.head = Some(baseline.components.heads.into_array());
    manifest.memory = None;
    manifest.world_model = None;
    manifest.decoder = Some(baseline.components.output_schema.into_array());
    manifest.runtime_digest = digest(&prepared["worker_sha256"])?.into_array();
    manifest.device_digest = JointGenerationProcessWorkerV1::observed_device_digest()?;
    manifest.input_schema = d(b"conditional-binary-prompt-with-stable-request-id-v1").into_array();
    manifest.state_schema = baseline.components.state_schema.into_array();
    manifest.output_schema = baseline.components.output_schema.into_array();
    manifest.learning = CellLearningBindingV2::Frozen {
        weights: digest(&prepared["parent"]["file_sha256"])?.into_array(),
    };
    manifest.evolution = CellEvolutionBindingV2 {
        structure: baseline.components.composition.into_array(),
        lineage: digest(&prepared["frozen"]["sha256"])?.into_array(),
        source_dependencies: manifest.source_digest,
        adoption_receipt: digest(&prepared["frozen"]["sha256"])?.into_array(),
    };
    manifest.max_input_bytes = 4096;
    manifest.max_state_bytes = 4096;
    manifest.max_delta_bytes = 16384;
    manifest.max_prefix_bytes = 32768;
    host.config.initial.scope.principal_digest = d(driver.operation.as_bytes()).into_array();
    host.config.initial.scope.cell_id = format!("{}-cell", driver.operation);
    host.config.initial.scope.run_id = format!("{}-source", driver.operation);
    host.config.initial.state.clear();
    host.config.initial.manifest_digest = host.config.manifest.digest()?;
    host.config.task_digest =
        d(format!("{}-source-task", driver.operation).as_bytes()).into_array();
    host.config.source_frontier = digest(&prepared["frozen"]["sha256"])?.into_array();
    let mut target = host.config.clone();
    target.initial.scope.run_id = format!("{}-next", driver.operation);
    target.initial.generation += 1;
    target.initial.writer_epoch += 1;
    target.task_digest = d(format!("{}-next-task", driver.operation).as_bytes()).into_array();
    let publication = Arc::new(Fixture::new_research(host.config.clone(), target)?);
    persist(
        &driver.evidence.join("isolated-owner-paths.json"),
        &serde_json::to_vec(&json!({
            "fleet_root":host.directory.path(),"generation_owner_root":publication.research_directory()?,
            "retained_on_failure":true,"research_only":true,
        }))?,
    )?;
    let source_control = ProcessControl::new(driver.clone(), host.config.manifest.clone());
    let (source_handle, bootstrap) = neuron_generation_channel_v2(
        &host.identity,
        publication.old_journal()?,
        source_control.clone(),
        monotonic,
        1,
    )?;
    let (mut source_tasks, lifetime) = host::host();
    spawn_neuron_generation_service(
        &mut source_tasks,
        bootstrap,
        Arc::clone(host.state()),
        lifetime,
    )?;
    let source_request = request(
        &driver,
        &host.config,
        source_handle.snapshot().await?,
        "source-task",
    )?;
    let source_receipt = source_handle.step(source_request).await?;
    acknowledge(&driver, &source_handle, "source-use").await?;
    let completed = d(&serde_json::to_vec(&source_receipt)?);
    let episode = d(&fs::read(
        driver.evidence.join("source-use-delivered.json"),
    )?);
    persist(
        &driver.evidence.join("source-task-receipt.json"),
        &serde_json::to_vec(&source_receipt)?,
    )?;
    source_tasks.shutdown().await;
    drop(source_handle);
    drop(source_tasks);
    let old = publication.old_journal()?;
    anyhow::ensure!(
        old.is_drained()? && old.observe_generation()?.is_terminal(),
        "source task did not actually complete"
    );
    let config = support::next_config(&mut host, 2).await?;
    let objective = digest(&prepared["evaluation_profile_sha256"])?;
    let trust = ResearchTrust::new(&driver.operation, objective, driver.deadline)?;
    let scope = &host.config.initial.scope;
    let learning_request = LearningIterationRequestV1 {
        operation_id: id(driver.operation.clone())?,
        principal_id: id(Digest32::from_array(scope.principal_digest).to_string())?,
        agent_id: id(scope.agent_id.clone())?,
        cell_id: id(scope.cell_id.clone())?,
        source_run_id: id(scope.run_id.clone())?,
        completed_task_receipt: completed,
        selected_artifact_digest: digest(&prepared["parent"]["file_sha256"])?,
        evaluation_profile: objective,
        selected_bundle: baseline,
        envelope: IterationEnvelopeV1 {
            envelope_id: id(format!("{}-envelope", driver.operation))?,
            base_commit: d(driver.source_commit.as_bytes()),
            base_tree: d(driver.source_tree.as_bytes()),
            objective_digest: objective,
            grammar_digest: d(b"original-smollm-10-step-lora-training-v1"),
            maximum_files: 1,
            maximum_diff_bytes: 1_048_576,
            maximum_candidates: 1,
            maximum_parallel_sandboxes: 1,
            expiry_unix_seconds: driver.deadline,
        },
        budget: LearningIterationBudgetV1 {
            maximum_dataset_rows: 4,
            maximum_dataset_bytes: 16384,
            maximum_training_steps: 10,
            maximum_training_milliseconds: 90_000,
            maximum_artifact_bytes: 1_048_576,
        },
    };
    let owners = trust.owners()?;
    let initial = LearningIterationCoordinatorV1::new(learning_request.clone(), owners.clone())?;
    let checkpoint =
        publication.research_checkpoint(learning_request.clone(), owners.clone(), true)?;
    let control = ProcessControl::new(driver.clone(), publication.target_config.manifest.clone());
    let ports = Arc::new(ResearchPorts {
        driver: driver.clone(),
        trust,
        publication: publication.clone(),
        old: Mutex::new(Some(old)),
        config: Mutex::new(Some(config)),
        state: Arc::clone(host.state()),
        control: control.clone(),
        checkpoint: Mutex::new(checkpoint),
        receipts: Mutex::new(Vec::new()),
        runtime: tokio::sync::Mutex::new(None),
        episode,
        initial_head: initial.snapshot().head_digest,
    });
    persist(
        &driver.evidence.join("native-before-training.json"),
        &serde_json::to_vec(&json!({"operation":driver.operation,
        "initial_learning_head":initial.snapshot().head_digest.to_string(),"evaluation_profile":objective.to_string(),
        "source_commit":driver.source_commit,"source_tree":driver.source_tree,"envelope_git_digest_encoding":"sha256-canonical-lowercase-git-object-id-text",
        "frozen_plan_sha256":driver.frozen,"created_unix_seconds":now()?,"absolute_deadline_unix_seconds":driver.deadline,
        "maximum_training_milliseconds":learning_request.budget.maximum_training_milliseconds,
        "current_research_owner":serde_json::from_slice::<Value>(&publication.bytes("current.json")?)?}))?,
    )?;
    let (handle, bootstrap) = learning_iteration_channel_v1(
        host.identity.agent_id.clone(),
        host.identity.spawn_generation,
        owners.clone(),
        ports.clone(),
        ports.trust.verifier.clone(),
        1,
    )?;
    let cancellation = CancellationToken::new();
    let task = tokio::spawn(bootstrap.run(Arc::clone(host.state()), cancellation.clone()));
    let finished = handle.submit(learning_request.clone()).await?;
    cancellation.cancel();
    task.await??;
    anyhow::ensure!(
        LearningIterationCoordinatorV1::from_snapshot(finished.clone())?
            .next_stage()
            .is_none(),
        "native iteration incomplete"
    );
    let checkpoint_before = publication.bytes("learning-checkpoint")?;
    drop(handle);
    ports.cold_reopen(&mut host, &finished).await?;
    *ports
        .checkpoint
        .lock()
        .map_err(|_| anyhow::anyhow!("checkpoint poisoned"))? =
        publication.research_checkpoint(learning_request.clone(), owners.clone(), false)?;
    let (recovered, bootstrap) = learning_iteration_channel_v1(
        host.identity.agent_id.clone(),
        host.identity.spawn_generation,
        owners,
        ports.clone(),
        ports.trust.verifier.clone(),
        1,
    )?;
    let cancellation = CancellationToken::new();
    let task = tokio::spawn(bootstrap.run(Arc::clone(host.state()), cancellation.clone()));
    anyhow::ensure!(
        recovered.submit(learning_request).await? == finished,
        "restored native learning receipt differs"
    );
    cancellation.cancel();
    task.await??;
    anyhow::ensure!(
        publication.bytes("learning-checkpoint")? == checkpoint_before,
        "completed learning restore rewrote checkpoint"
    );
    anyhow::ensure!(
        source_control.executions.load(Ordering::SeqCst) == 1
            && control.executions.load(Ordering::SeqCst) == 1,
        "owner recovery dispatched another model call"
    );
    anyhow::ensure!(
        publication.authority.capacity()?.used_nonces == 1,
        "cold recovery consumed another grant nonce"
    );
    let outer: Value = serde_json::from_slice(&checkpoint_before)?;
    let raw = base64::engine::general_purpose::STANDARD_NO_PAD.decode(
        outer["snapshot"]
            .as_str()
            .ok_or_else(|| anyhow::anyhow!("checkpoint bytes"))?,
    )?;
    anyhow::ensure!(
        &raw[..8] == b"HEPLCP02",
        "original checkpoint codec not used"
    );
    persist(
        &driver.evidence.join("native-completed-checkpoint.bin"),
        &raw,
    )?;
    persist(
        &driver
            .evidence
            .join("native-completed-checkpoint-owner.json"),
        &checkpoint_before,
    )?;
    let mut running = ports
        .runtime
        .lock()
        .await
        .take()
        .ok_or_else(|| anyhow::anyhow!("original owner missing"))?;
    let readback = running
        .readback
        .take()
        .ok_or_else(|| anyhow::anyhow!("original use readback missing"))?;
    persist(
        &driver.evidence.join("native-completed-use-readback.json"),
        &serde_json::to_vec(&readback)?,
    )?;
    let result = json!({"schema":"hepta.research.real-model-native-completion.v1","result":"PASS",
        "operation":driver.operation,"initial_learning_head":initial.snapshot().head_digest.to_string(),"learning_head":finished.head_digest.to_string(),
        "checkpoint_sha256":d(&raw).to_string(),"frozen_plan_sha256":driver.frozen,"evaluation_profile":objective.to_string(),
        "actual_training_optimizer_steps":10,"actual_source_forward_calls":1,"actual_evaluation_forward_calls":8,"actual_next_task_forward_calls":1,
        "disposition":"NoUpdate","selected_adapter":driver.prepared["parent"]["adapter"],"retained_artifact_sha256":driver.prepared["parent"]["file_sha256"],
        "original_learning_signature_verifier":true,"original_checkpoint_codec":true,"original_generation_actor":true,
        "generation_owner_reopened":true,"worker_process_restarted":true,"learning_owner_reopened":true,"reexecuted_after_recovery":false,
        "native_daemon_os_restart":false,"native_fleet_lifecycle_recreated":true,"research_keys_and_custody":true,"independent_operator_custody":false,
        "production_root_capability":false,"production_final_use":false,"production_activation":false,"qualification":"HOLD_NO_GO"});
    persist(
        &driver.evidence.join("native-result.json"),
        &serde_json::to_vec(&result)?,
    )?;
    running.tasks.shutdown().await;
    println!(
        "HEPTA_REAL_MODEL_NATIVE_COMPLETION_V1 {}",
        serde_json::to_string(&result)?
    );
    Ok(())
}
