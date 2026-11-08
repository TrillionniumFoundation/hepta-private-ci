//! Explicit external-trained-artifact research selection over original native owners.
//! This module grants no Parameter V3, OPE or production qualification.

use super::*;
use crate::AgentdGenerationUpdateTargetV1;
use crate::AgentdSelectedGenerationV1;
use crate::NeuronGenerationRuntimeHandleV2;
use crate::learning_updated_task_operation_id_v1;
use crate::neuron_generation_current::test_support::RECORDS;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum ResearchFlow {
    RetainedOnly,
    ExternalTrainedArtifact,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum SelectionKind {
    Retained,
    Updated,
}

pub(super) fn kind(coordinator: &LearningIterationCoordinatorV1) -> SelectionKind {
    if coordinator.snapshot().receipts.iter().any(|receipt| {
        matches!(
            receipt.observation,
            LearningIterationObservationV1::Proposal {
                disposition: LearningProposalDispositionV1::UpdateCandidates,
                ..
            }
        )
    }) {
        SelectionKind::Updated
    } else {
        SelectionKind::Retained
    }
}

pub(super) fn operation(coordinator: &LearningIterationCoordinatorV1) -> anyhow::Result<String> {
    Ok(match kind(coordinator) {
        SelectionKind::Retained => learning_retained_task_operation_id_v1(coordinator)?,
        SelectionKind::Updated => learning_updated_task_operation_id_v1(coordinator)?,
    }
    .to_string())
}

pub(super) async fn selection(
    handle: &NeuronGenerationRuntimeHandleV2,
    coordinator: &LearningIterationCoordinatorV1,
    baseline: &CellBackendManifestV2,
) -> anyhow::Result<LearningIterationObservationV1> {
    Ok(match kind(coordinator) {
        SelectionKind::Retained => handle.read_learning_selection(coordinator).await?,
        SelectionKind::Updated => {
            handle
                .read_learning_updated_selection(coordinator, baseline)
                .await?
        }
    })
}

pub(super) async fn next_use(
    handle: &NeuronGenerationRuntimeHandleV2,
    coordinator: &LearningIterationCoordinatorV1,
    baseline: &CellBackendManifestV2,
    intent: &CellGenerationIntentV2,
) -> anyhow::Result<LearningIterationObservationV1> {
    Ok(match kind(coordinator) {
        SelectionKind::Retained => handle.read_learning_next_use(coordinator, intent).await?,
        SelectionKind::Updated => {
            handle
                .read_learning_updated_next_use(coordinator, baseline, intent)
                .await?
        }
    })
}

pub(super) async fn readback(
    handle: &NeuronGenerationRuntimeHandleV2,
    coordinator: &LearningIterationCoordinatorV1,
    baseline: &CellBackendManifestV2,
    intent: &CellGenerationIntentV2,
) -> anyhow::Result<AgentdGenerationLearningUseReadbackV1> {
    Ok(match kind(coordinator) {
        SelectionKind::Retained => {
            handle
                .read_learning_next_use_readback(coordinator, intent)
                .await?
        }
        SelectionKind::Updated => {
            handle
                .read_learning_updated_next_use_readback(coordinator, baseline, intent)
                .await?
        }
    })
}

pub(super) fn admitted_target(
    ports: &ResearchPorts,
    coordinator: &LearningIterationCoordinatorV1,
) -> anyhow::Result<(
    CellGenerationConfigV2,
    ProcessControl,
    AgentdSelectedGenerationV1,
)> {
    match kind(coordinator) {
        SelectionKind::Retained => Ok((
            ports.publication.target_config.clone(),
            ports.control.clone(),
            ports.publication.selection()?,
        )),
        SelectionKind::Updated => {
            anyhow::ensure!(
                ports.flow == ResearchFlow::ExternalTrainedArtifact,
                "ordinary research profile has no external-artifact proposal owner"
            );
            ports
                .external_owner
                .as_ref()
                .ok_or_else(|| anyhow::anyhow!("research proposal owner absent"))?
                .verify_restored(coordinator.snapshot())?;
            let candidate = coordinator
                .candidate()
                .ok_or_else(|| anyhow::anyhow!("actual candidate missing"))?;
            let material: Value = serde_json::from_slice(&fs::read(
                ports
                    .driver
                    .output
                    .join("training/worker/parent-material.json"),
            )?)?;
            let candidate_sha = digest(&material["file_sha256"])?;
            anyhow::ensure!(
                candidate.components.cell_adapter == Some(digest(&material["adapter"])?)
                    && candidate.generation
                        == Generation::new(
                            material["generation"]
                                .as_u64()
                                .ok_or_else(|| anyhow::anyhow!("actual candidate generation"))?
                        )?,
                "selected candidate differs from trained artifact"
            );
            let proposal = coordinator
                .snapshot()
                .receipts
                .iter()
                .find(|r| {
                    matches!(
                        r.observation,
                        LearningIterationObservationV1::Proposal { .. }
                    )
                })
                .ok_or_else(|| anyhow::anyhow!("original proposal receipt missing"))?;
            let lineage = candidate
                .training_lineage
                .as_ref()
                .ok_or_else(|| anyhow::anyhow!("actual training lineage missing"))?;
            let mut config = ports.publication.target_config.clone();
            config.manifest.bundle_digest = candidate.digest()?.into_array();
            config.manifest.learning = CellLearningBindingV2::Frozen {
                weights: candidate_sha.into_array(),
            };
            config.manifest.evolution.structure = candidate.components.composition.into_array();
            config.manifest.evolution.lineage = Digest32::of_parts(&[
                b"hepta.research.external-trained-lineage.v1\0",
                lineage.source_bundle.as_array(),
                lineage.dataset.as_array(),
                lineage.update_rule.as_array(),
                lineage.evaluation_profile.as_array(),
                candidate_sha.as_array(),
            ])
            .into_array();
            config.manifest.evolution.adoption_receipt = proposal.evidence_digest.into_array();
            config.initial.manifest_digest = config.manifest.digest()?;
            let control = ProcessControl::for_candidate(
                ports.driver.clone(),
                config.manifest.clone(),
                material,
            )?;
            let selected = ports.publication.publish_research_next_selection(
                &config.manifest,
                "actual-external-trained-candidate",
            )?;
            Ok((config, control, selected))
        }
    }
}

pub(super) fn reopen_selection(
    ports: &ResearchPorts,
    coordinator: &LearningIterationCoordinatorV1,
) -> anyhow::Result<AgentdSelectedGenerationV1> {
    match kind(coordinator) {
        SelectionKind::Retained => ports.publication.selection(),
        SelectionKind::Updated => ports.publication.research_selection(),
    }
}

pub(super) fn reopen_target(
    ports: &ResearchPorts,
    config: CellGenerationConfigV2,
) -> anyhow::Result<AgentdGenerationUpdateTargetV1<FileAnchorWitnessStore>> {
    Ok(AgentdGenerationUpdateTargetV1 {
        file: ports.publication.file("target-journal")?,
        witness: ports.publication.witness("target-witness", &config)?,
        config,
        max_records: RECORDS,
    })
}

/// The positive named test cannot pass merely because a legal retained path
/// completed. Bind the actual hot delivery and cold worker output to the fresh
/// candidate selected by the original update owner.
pub(super) fn require_actual_adoption(
    ports: &ResearchPorts,
    running: &Running,
    readback: &AgentdGenerationLearningUseReadbackV1,
    finished: &LearningIterationSnapshotV1,
    evaluation: &Value,
) -> anyhow::Result<Value> {
    anyhow::ensure!(
        kind(&running.coordinator) == SelectionKind::Updated,
        "legal NoUpdate completed; positive Adopt qualification not met"
    );
    let candidate = running
        .coordinator
        .candidate()
        .ok_or_else(|| anyhow::anyhow!("fresh trained candidate missing"))?;
    let candidate_sha = digest(&evaluation["candidate"]["file_sha256"])?;
    let candidate_adapter = digest(&evaluation["candidate"]["adapter"])?;
    anyhow::ensure!(
        evaluation["disposition"] == "Qualified"
            && candidate_sha != digest(&ports.driver.prepared["parent"]["file_sha256"])?
            && candidate.components.cell_adapter == Some(candidate_adapter),
        "actual adoption did not select a distinct qualified training output"
    );
    let original: Value = serde_json::to_value(readback)?;
    let payload: Value = serde_json::from_str(
        original["payload_json"]
            .as_str()
            .ok_or_else(|| anyhow::anyhow!("original native use payload missing"))?,
    )?;
    let manifest: CellBackendManifestV2 = serde_json::from_str(
        payload["manifest_json"]
            .as_str()
            .ok_or_else(|| anyhow::anyhow!("original native use manifest missing"))?,
    )?;
    anyhow::ensure!(
        payload["disposition"] == "adopted_model_reset"
            && payload["learning_operation_id"] == ports.driver.operation
            && payload["observation"]["kind"] == "next_use"
            && payload["observation"]["bundle_digest"]
                == serde_json::to_value(candidate.digest()?.into_array())?
            && manifest == running.target_config.manifest
            && manifest.bundle_digest == candidate.digest()?.into_array()
            && matches!(manifest.learning, CellLearningBindingV2::Frozen { weights }
                    if weights == candidate_sha.into_array()),
        "original updated NextUse did not bind the exact fresh candidate"
    );
    let hot: Value = serde_json::from_slice(&fs::read(
        ports.driver.evidence.join("next-use-delivered.json"),
    )?)?;
    let cold: Value = serde_json::from_slice(&fs::read(
        ports.driver.evidence.join("next-use-cold-owner.json"),
    )?)?;
    let recovered = &cold["worker_recovery"]["result"];
    anyhow::ensure!(
        cold["readback"] == original
            && [&hot, recovered]
                .into_iter()
                .all(
                    |output| output["selected_adapter"] == evaluation["candidate"]["adapter"]
                        && output["selected_file_sha256"] == evaluation["candidate"]["file_sha256"]
                        && output["observation"]["request_id"]
                            == format!("{}-next-task", ports.driver.operation)
                )
            && hot["native_request_digest"] == recovered["native_request_digest"]
            && hot["observation"] == recovered["observation"]
            && recovered["previous_worker_pid"] == hot["worker_pid"]
            && recovered["worker_pid"] != hot["worker_pid"]
            && hot["forward_counter_before"] == 0
            && hot["forward_counter_after"] == 1
            && recovered["forward_counter_before"] == 1
            && recovered["forward_counter_after"] == 1,
        "hot/cold actual model outputs or process-ledger identity differ"
    );
    ports
        .external_owner
        .as_ref()
        .ok_or_else(|| anyhow::anyhow!("research owner missing"))?
        .verify_restored(finished)?;
    Ok(json!({"original_proposal":"UpdateCandidates",
        "selected_candidate_bundle":candidate.digest()?.to_string(),
        "selected_candidate_sha256":candidate_sha.to_string(),
        "hot_and_cold_original_readback_equal":true,
        "hot_worker_pid":hot["worker_pid"],"cold_worker_pid":recovered["worker_pid"],
        "hot_forward_budget_delta":1,"cold_forward_budget_delta":0,
        "forward_count_kind":"source-bound-live-worker-ledger-delta-inference"}))
}

fn changed_contexts(
    snapshot: &LearningIterationSnapshotV1,
) -> anyhow::Result<Vec<(&'static str, LearningIterationSnapshotV1)>> {
    let mut cases = Vec::new();
    let mut changed = snapshot.clone();
    changed.request.operation_id =
        id(format!("{}-wrong-operation", snapshot.request.operation_id))?;
    cases.push(("wrong-operation", changed));
    let mut changed = snapshot.clone();
    changed.request.evaluation_profile = d(b"changed-research-evaluation-profile");
    cases.push(("changed-frozen-profile", changed));
    let mut changed = snapshot.clone();
    changed.request.budget.maximum_training_steps += 1;
    cases.push(("changed-training-budget", changed));
    let mut changed = snapshot.clone();
    changed.request.selected_artifact_digest = d(b"substituted-baseline-artifact");
    cases.push(("substituted-baseline-artifact", changed));
    let mut changed = snapshot.clone();
    changed.request.selected_bundle.components.cell_adapter =
        Some(d(b"substituted-baseline-adapter"));
    cases.push(("substituted-baseline-bundle", changed));
    let mut changed = snapshot.clone();
    changed.owners.proposal = id("wrong-research-proposal-owner")?;
    cases.push(("wrong-proposal-owner", changed));
    let mut changed = snapshot.clone();
    let training = changed
        .receipts
        .iter_mut()
        .find_map(|receipt| match &mut receipt.observation {
            LearningIterationObservationV1::Training { candidate, .. } => Some(candidate),
            _ => None,
        })
        .ok_or_else(|| anyhow::anyhow!("actual Training receipt absent"))?;
    training.components.cell_adapter = Some(d(b"substituted-trained-adapter"));
    cases.push(("substituted-training-candidate", changed));
    if snapshot.receipts.iter().any(|receipt| {
        matches!(
            receipt.observation,
            LearningIterationObservationV1::Proposal { .. }
        )
    }) {
        let mut changed = snapshot.clone();
        for receipt in &mut changed.receipts {
            if let LearningIterationObservationV1::Proposal {
                composition_digest, ..
            } = &mut receipt.observation
            {
                *composition_digest = d(b"substituted-research-owner-composition");
            }
        }
        cases.push(("substituted-proposal-composition", changed));
    }
    Ok(cases)
}

fn original_owner_bytes(ports: &ResearchPorts) -> anyhow::Result<Vec<(String, Vec<u8>)>> {
    let mut bytes = Vec::new();
    for root in ["external-artifact-owner", "external-artifact-owner-anchor"] {
        let directory = ports.driver.evidence.join(root);
        let mut entries = fs::read_dir(&directory)?
            .map(|entry| entry.map(|e| e.path()))
            .collect::<Result<Vec<_>, _>>()?;
        entries.sort();
        for entry in entries {
            anyhow::ensure!(
                fs::symlink_metadata(&entry)?.is_file(),
                "research owner entry is not a regular file"
            );
            bytes.push((entry.to_string_lossy().into_owned(), fs::read(entry)?));
        }
    }
    for name in [
        "current.json",
        "learning-checkpoint",
        "final-use/authority.claims",
    ] {
        bytes.push((name.into(), ports.publication.bytes(name)?));
    }
    Ok(bytes)
}

pub(super) fn reject_prepared_contexts(
    ports: &ResearchPorts,
    snapshot: &LearningIterationSnapshotV1,
    proposal: &crate::learning_iteration_research_external::ResearchExternalTrainedArtifactProposalV1,
) -> anyhow::Result<()> {
    let before = original_owner_bytes(ports)?;
    let mut results = Vec::new();
    for (case, changed) in changed_contexts(snapshot)? {
        let rejection = proposal
            .commit_for(&changed, now()?)
            .err()
            .ok_or_else(|| anyhow::anyhow!("research proposal accepted negative context {case}"))?;
        anyhow::ensure!(
            original_owner_bytes(ports)? == before,
            "rejected proposal changed owner, CURRENT, checkpoint or nonce claims"
        );
        results.push(json!({"case":case,"rejected":true,"error":rejection.to_string()}));
    }
    persist(
        &ports
            .driver
            .evidence
            .join("external-proposal-context-rejections.json"),
        &serde_json::to_vec(
            &json!({"schema":"hepta.research.external-proposal-context-rejections.v1",
            "operation":snapshot.request.operation_id.to_string(),"phase":"before-original-Proposal",
            "results":results,"selection_current_checkpoint_and_nonce_unchanged":true,
            "qualification":"HOLD_NO_GO"}),
        )?,
    )?;
    Ok(())
}

pub(super) fn reopen_and_reject_restored_contexts(
    ports: &ResearchPorts,
    finished: &LearningIterationSnapshotV1,
) -> anyhow::Result<()> {
    let initial =
        LearningIterationCoordinatorV1::new(finished.request.clone(), finished.owners.clone())?;
    let before = original_owner_bytes(ports)?;
    let reopened = ResearchExternalTrainedArtifactOwnerV1::create(
        ports.driver.evidence.join("external-artifact-owner"),
        ports.driver.output.clone(),
        ports.driver.evidence.clone(),
        initial.snapshot(),
    )?;
    reopened.verify_restored(finished)?;
    let mut results = Vec::new();
    for (case, changed) in changed_contexts(finished)? {
        let rejection = reopened.verify_restored(&changed).err().ok_or_else(|| {
            anyhow::anyhow!("reopened proposal owner accepted negative context {case}")
        })?;
        reopened.verify_restored(finished)?;
        anyhow::ensure!(
            original_owner_bytes(ports)? == before,
            "rejected restored context rewrote original owner or native state"
        );
        results.push(json!({"case":case,"rejected":true,"error":rejection.to_string()}));
    }
    persist(
        &ports
            .driver
            .evidence
            .join("external-owner-cold-rejections.json"),
        &serde_json::to_vec(
            &json!({"schema":"hepta.research.external-owner-cold-rejections.v1",
            "operation":finished.request.operation_id.to_string(),"reopened_directory_fds":true,
            "results":results,"original_snapshot_reverified":true,"owner_and_native_bytes_unchanged":true,
            "native_daemon_os_restart":false,"qualification":"HOLD_NO_GO"}),
        )?,
    )?;
    Ok(())
}

/// Exercise the new material boundary with the genuine, already authenticated
/// four-receipt prefix and concrete prepared payload. Original files are moved
/// aside, never overwritten; every attempted fault is restored before checking
/// the rejection, and the substituted bytes are retained as research evidence.
pub(super) fn reject_external_material_faults(
    ports: &ResearchPorts,
    snapshot: &LearningIterationSnapshotV1,
    proposal: &crate::learning_iteration_research_external::ResearchExternalTrainedArtifactProposalV1,
) -> anyhow::Result<()> {
    let owner = ports
        .external_owner
        .as_ref()
        .ok_or_else(|| anyhow::anyhow!("research material owner absent"))?;
    anyhow::ensure!(
        snapshot.receipts.len() == 4
            && LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?.next_stage()
                == Some(LearningIterationStageV1::Proposal),
        "real authenticated proposal prefix required"
    );
    let before = original_owner_bytes(ports)?;
    let faults = ports.driver.evidence.join("external-material-faults");
    fs::create_dir(&faults)?;
    let mut results = Vec::new();
    for (case, relative, substitute) in [
        (
            "candidate-byte-substitution",
            "training/worker/artifact.safetensors",
            true,
        ),
        (
            "missing-actual-training-start",
            "training-start.json",
            false,
        ),
    ] {
        let path = ports.driver.output.join(relative);
        let original = fs::read(&path)?;
        let original_hash = d(&original);
        let retained = path.with_file_name(format!(
            "{}.research-retained-original",
            path.file_name()
                .and_then(|name| name.to_str())
                .ok_or_else(|| anyhow::anyhow!("material filename"))?
        ));
        anyhow::ensure!(
            !retained.exists(),
            "fault control original already retained"
        );
        fs::rename(&path, &retained)?;
        let attempted = (|| -> anyhow::Result<Option<LearningIterationRuntimeErrorV1>> {
            if substitute {
                let mut changed = original.clone();
                anyhow::ensure!(changed.len() > 4, "actual candidate bytes required");
                let at = changed.len() - 4;
                changed[at] ^= 1;
                persist(&path, &changed)?;
            }
            Ok(proposal.commit_for(snapshot, now()?).err())
        })();
        // Restore regardless of the owner result. A failed cleanup preserves the
        // original under its explicit retained name and fails this whole run.
        let substituted = faults.join(format!("{case}.bin"));
        let substituted_hash = if path.exists() {
            fs::rename(&path, &substituted)?;
            Some(d(&fs::read(&substituted)?).to_string())
        } else {
            None
        };
        fs::rename(&retained, &path)?;
        std::fs::File::open(
            path.parent()
                .ok_or_else(|| anyhow::anyhow!("material parent"))?,
        )?
        .sync_all()?;
        anyhow::ensure!(
            fs::read(&path)? == original,
            "fault control did not restore exact original bytes"
        );
        let rejection = attempted?
            .ok_or_else(|| anyhow::anyhow!("owner accepted external material fault {case}"))?;
        anyhow::ensure!(
            matches!(
                &rejection,
                LearningIterationRuntimeErrorV1::OwnerUnavailable(
                    "research-external-trained-artifact-v1"
                )
            ),
            "material fault did not reach the concrete research owner boundary"
        );
        anyhow::ensure!(
            original_owner_bytes(ports)? == before,
            "material rejection wrote reservation/CURRENT/checkpoint/nonce claims"
        );
        // This must reread the restored real materials successfully, rather than
        // retaining a cached rejection or merely trusting the old payload.
        owner.prepare(snapshot)?;
        results.push(
            json!({"case":case,"rejected":true,"error":rejection.to_string(),
            "original_path":path,"original_sha256":original_hash.to_string(),
            "substituted_sha256":substituted_hash,"original_bytes_restored":true,
            "fresh_prepare_after_restore_succeeded":true}),
        );
    }
    persist(
        &ports
            .driver
            .evidence
            .join("external-material-rejections.json"),
        &serde_json::to_vec(
            &json!({"schema":"hepta.research.external-material-rejections.v1",
            "operation":snapshot.request.operation_id.to_string(),"original_four_receipt_head":snapshot.head_digest.to_string(),
            "snapshot_and_prepared_payload_unchanged":true,"results":results,
            "selection_current_checkpoint_nonce_and_proposal_store_unchanged":true,"qualification":"HOLD_NO_GO"}),
        )?,
    )?;
    Ok(())
}
