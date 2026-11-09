use codex_hepta_infer_core::JointTensorPacketV1;
use codex_hepta_infer_core::joint_packet_sha256_v1;
use codex_hepta_learning_artifacts::CellBundleComponentsV1;
use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_learning_artifacts::CellTrainingLineageV1;
use codex_hepta_learning_artifacts::IterationEnvelopeV1;
use codex_hepta_learning_artifacts::LearningIterationBudgetV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationOwnersV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationRequestV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::JointBundleAssemblyErrorV1;
use super::assemble_joint_v4_training_bundle_v1;

#[path = "joint_generation_bundle_weight_fixture.rs"]
mod weight_fixture;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

// Structural replay only: none of these labels is a role signature, real
// dataset, training result or current-head authentication.
fn training_snapshot(maximum_artifact_bytes: u64) -> TestResult<LearningIterationSnapshotV1> {
    let request = LearningIterationRequestV1 {
        operation_id: StableId::new("iteration:fixture")?,
        principal_id: StableId::new("principal:fixture")?,
        agent_id: StableId::new("agent:fixture")?,
        cell_id: StableId::new("cell:fixture")?,
        source_run_id: StableId::new("run:fixture")?,
        completed_task_receipt: Digest32::of_bytes(b"fixture-task"),
        selected_artifact_digest: Digest32::of_bytes(b"fixture-artifact"),
        evaluation_profile: Digest32::of_bytes(b"fixture-evaluation"),
        selected_bundle: CellCompatibilityBundleV1 {
            artifact_id: StableId::new("artifact:baseline")?,
            generation: Generation::new(1)?,
            components: CellBundleComponentsV1 {
                base: Digest32::of_bytes(b"fixture-base"),
                organ_adapter: None,
                cell_adapter: None,
                heads: Digest32::of_bytes(b"fixture-heads"),
                composition: Digest32::of_bytes(b"fixture-composition"),
                encoder: Digest32::of_bytes(b"fixture-encoder"),
                tokenizer: Digest32::of_bytes(b"fixture-tokenizer"),
                normalizer: Digest32::of_bytes(b"fixture-normalizer"),
                calibration: Digest32::of_bytes(b"fixture-calibration"),
                numeric_profile: Digest32::of_bytes(b"fixture-numeric"),
                output_schema: Digest32::of_bytes(b"fixture-output"),
                state_schema: Digest32::of_bytes(b"fixture-state-schema"),
                state_semantics: Digest32::of_bytes(b"fixture-state-semantics"),
            },
            training_lineage: None,
            rollback_predecessor: None,
        },
        envelope: IterationEnvelopeV1 {
            envelope_id: StableId::new("window:fixture")?,
            base_commit: Digest32::of_bytes(b"fixture-commit"),
            base_tree: Digest32::of_bytes(b"fixture-tree"),
            objective_digest: Digest32::of_bytes(b"fixture-objective"),
            grammar_digest: Digest32::of_bytes(b"fixture-grammar"),
            maximum_files: 1,
            maximum_diff_bytes: 128,
            maximum_candidates: 1,
            maximum_parallel_sandboxes: 1,
            expiry_unix_seconds: 100,
        },
        budget: LearningIterationBudgetV1 {
            maximum_dataset_rows: 2,
            maximum_dataset_bytes: 64,
            maximum_training_steps: 2,
            maximum_training_milliseconds: 10,
            maximum_artifact_bytes,
        },
    };
    let owners = LearningIterationOwnersV1 {
        evidence_trust_digest: Digest32::of_bytes(b"fixture-trust"),
        experience: StableId::new("owner:experience")?,
        dataset: StableId::new("owner:dataset")?,
        trainer: StableId::new("owner:trainer")?,
        evaluator: StableId::new("owner:evaluator")?,
        proposal: StableId::new("owner:proposal")?,
        selector: StableId::new("owner:selector")?,
        next_use_observer: StableId::new("owner:observer")?,
    };
    let completed_task_receipt = request.completed_task_receipt;
    let mut coordinator = LearningIterationCoordinatorV1::new(request, owners)?;
    for (now, observation) in [
        (
            10,
            LearningIterationObservationV1::Experience {
                episode_digest: Digest32::of_bytes(b"fixture-episode"),
                completed_task_receipt,
            },
        ),
        (
            11,
            LearningIterationObservationV1::Dataset {
                snapshot_digest: Digest32::of_bytes(b"fixture-dataset"),
                episode_digest: Digest32::of_bytes(b"fixture-episode"),
                withdrawal_frontier: Digest32::of_bytes(b"fixture-withdrawals"),
                rows: 2,
                bytes: 64,
            },
        ),
    ] {
        let snapshot = coordinator.snapshot();
        let receipt = LearningIterationReceiptV1 {
            operation_id: snapshot.request.operation_id.clone(),
            predecessor: snapshot.head_digest,
            actor_id: snapshot.owners.owner(observation.stage()).clone(),
            evidence_digest: Digest32::of_bytes(b"synthetic-structural-evidence"),
            observed_unix_seconds: now,
            observation,
        };
        coordinator.record(receipt, now)?;
    }
    Ok(coordinator.snapshot().clone())
}

fn lineage(snapshot: &LearningIterationSnapshotV1) -> TestResult<CellTrainingLineageV1> {
    Ok(CellTrainingLineageV1 {
        source_bundle: snapshot.request.selected_bundle.digest()?,
        dataset: Digest32::of_bytes(b"fixture-dataset"),
        update_rule: Digest32::of_bytes(b"fixture-declared-update-rule"),
        evaluation_profile: snapshot.request.evaluation_profile,
    })
}

#[test]
fn assembly_binds_physical_packet_without_advancing_checkpoint() -> TestResult {
    let packet = weight_fixture::observed_weights().encode()?;
    let snapshot = training_snapshot(packet.len() as u64)?;
    let original = snapshot.clone();
    let lineage = lineage(&snapshot)?;
    let artifact_id = StableId::new("artifact:assembled")?;
    let assembled = assemble_joint_v4_training_bundle_v1(
        &snapshot,
        artifact_id.clone(),
        lineage.clone(),
        &packet,
    )?;
    assert_eq!(
        (
            assembled.bundle().artifact_id.clone(),
            assembled.bundle().generation,
            assembled.bundle().training_lineage.clone(),
            assembled.bundle().rollback_predecessor
        ),
        (
            artifact_id,
            snapshot.request.selected_bundle.generation.next()?,
            Some(lineage.clone()),
            Some(lineage.source_bundle)
        ),
    );
    assert_eq!(
        (
            assembled.physical_weights_digest(),
            assembled.weights_bytes(),
            assembled.iteration_head()
        ),
        (
            Digest32::of_bytes(&packet),
            packet.len() as u64,
            snapshot.head_digest
        ),
    );
    assert!(!assembled.bundle().digest()?.is_zero());
    assert_ne!(
        assembled.decoded_weights_digest(),
        assembled.physical_weights_digest()
    );
    assert_eq!(assembled.authority(), AuthorityPosture::DENY_ALL);
    assert_eq!(snapshot, original);
    assert_eq!(
        LearningIterationCoordinatorV1::from_snapshot(snapshot)?.next_stage(),
        Some(LearningIterationStageV1::Training),
    );
    Ok(())
}

#[test]
fn assembly_rejects_checksum_damage_and_incomplete_component_mapping() -> TestResult {
    let mut weights = weight_fixture::observed_weights();
    let mut packet = weights.encode()?;
    let snapshot = training_snapshot(packet.len() as u64)?;
    // This is the actual encoded body, leaving its original checksum unchanged.
    packet[20] ^= 1;
    assert_eq!(
        assemble_joint_v4_training_bundle_v1(
            &snapshot,
            StableId::new("artifact:assembled")?,
            lineage(&snapshot)?,
            &packet,
        ),
        Err(JointBundleAssemblyErrorV1::InvalidWeights)
    );
    assert!(weights.tensors.remove("text_recurrent.weight").is_some());
    let incomplete = weights.encode()?;
    assert!(JointTensorPacketV1::decode(&incomplete).is_ok());
    assert_eq!(
        assemble_joint_v4_training_bundle_v1(
            &snapshot,
            StableId::new("artifact:assembled")?,
            lineage(&snapshot)?,
            &incomplete,
        ),
        Err(JointBundleAssemblyErrorV1::InvalidWeights)
    );
    let mut wrong_shape = weight_fixture::observed_weights();
    let tensor = wrong_shape
        .tensors
        .get_mut("text_recurrent.weight")
        .ok_or("fixture tensor absent")?;
    // Same scalar count and a valid packet, but not the actual consumer shape.
    tensor.shape = vec![16, 64];
    let wrong_shape = wrong_shape.encode()?;
    assert!(JointTensorPacketV1::decode(&wrong_shape).is_ok());
    assert_eq!(
        assemble_joint_v4_training_bundle_v1(
            &snapshot,
            StableId::new("artifact:assembled")?,
            lineage(&snapshot)?,
            &wrong_shape,
        ),
        Err(JointBundleAssemblyErrorV1::InvalidWeights)
    );
    let mut missing_profile = weight_fixture::observed_weights();
    assert!(missing_profile.meta.remove("text_profile").is_some());
    assert_eq!(
        assemble_joint_v4_training_bundle_v1(
            &snapshot,
            StableId::new("artifact:assembled")?,
            lineage(&snapshot)?,
            &missing_profile.encode()?,
        ),
        Err(JointBundleAssemblyErrorV1::InvalidWeights)
    );
    Ok(())
}

#[test]
fn assembly_rejects_noncanonical_bytes_even_when_packet_contents_match() -> TestResult {
    let canonical = weight_fixture::observed_weights().encode()?;
    let snapshot = training_snapshot(canonical.len() as u64)?;
    let entries = [("allow_initial_stop", "false"), ("boundary", "direct")].map(|(key, value)| {
        let mut bytes = Vec::new();
        for field in [key, value] {
            bytes.extend((field.len() as u32).to_le_bytes());
            bytes.extend(field.as_bytes());
        }
        bytes
    });
    let entries_end = 12 + entries[0].len() + entries[1].len();
    let original_entries = [entries[0].clone(), entries[1].clone()].concat();
    assert_eq!(&canonical[12..entries_end], original_entries.as_slice());
    let mut reordered = canonical[..12].to_vec();
    reordered.extend(&entries[1]);
    reordered.extend(&entries[0]);
    reordered.extend(&canonical[entries_end..canonical.len() - 64]);
    let checksum = joint_packet_sha256_v1(&reordered);
    reordered.extend(checksum.as_bytes());
    assert_eq!(
        JointTensorPacketV1::decode(&reordered)?,
        JointTensorPacketV1::decode(&canonical)?
    );
    assert_ne!(reordered, canonical);
    assert_eq!(
        assemble_joint_v4_training_bundle_v1(
            &snapshot,
            StableId::new("artifact:assembled")?,
            lineage(&snapshot)?,
            &reordered,
        ),
        Err(JointBundleAssemblyErrorV1::InvalidWeights)
    );
    Ok(())
}

#[test]
fn assembly_rejects_cross_dataset_predecessor_evaluation_and_empty_update_rule() -> TestResult {
    let packet = weight_fixture::observed_weights().encode()?;
    let snapshot = training_snapshot(packet.len() as u64)?;
    let original = lineage(&snapshot)?;
    let other = Digest32::of_bytes(b"different-job");
    for wrong in [
        CellTrainingLineageV1 {
            source_bundle: other,
            ..original.clone()
        },
        CellTrainingLineageV1 {
            dataset: other,
            ..original.clone()
        },
        CellTrainingLineageV1 {
            evaluation_profile: other,
            ..original.clone()
        },
        CellTrainingLineageV1 {
            update_rule: Digest32::ZERO,
            ..original.clone()
        },
    ] {
        assert_eq!(
            assemble_joint_v4_training_bundle_v1(
                &snapshot,
                StableId::new("artifact:assembled")?,
                wrong,
                &packet,
            ),
            Err(JointBundleAssemblyErrorV1::LineageMismatch)
        );
    }
    Ok(())
}

#[test]
fn assembly_rejects_stale_snapshot_wrong_stage_reused_id_and_actual_byte_overrun() -> TestResult {
    let packet = weight_fixture::observed_weights().encode()?;
    let snapshot = training_snapshot(packet.len() as u64)?;
    let mut stale = snapshot.clone();
    stale.head_digest = Digest32::of_bytes(b"stale-head");
    assert_eq!(
        assemble_joint_v4_training_bundle_v1(
            &stale,
            StableId::new("artifact:assembled")?,
            lineage(&snapshot)?,
            &packet,
        ),
        Err(JointBundleAssemblyErrorV1::InvalidSnapshot)
    );
    let before_dataset =
        LearningIterationCoordinatorV1::new(snapshot.request.clone(), snapshot.owners.clone())?
            .snapshot()
            .clone();
    assert_eq!(
        assemble_joint_v4_training_bundle_v1(
            &before_dataset,
            StableId::new("artifact:assembled")?,
            lineage(&snapshot)?,
            &packet,
        ),
        Err(JointBundleAssemblyErrorV1::WrongStage)
    );
    assert_eq!(
        assemble_joint_v4_training_bundle_v1(
            &snapshot,
            snapshot.request.selected_bundle.artifact_id.clone(),
            lineage(&snapshot)?,
            &packet,
        ),
        Err(JointBundleAssemblyErrorV1::CandidateIdentity)
    );
    let bounded = training_snapshot(packet.len() as u64 - 1)?;
    assert_eq!(
        assemble_joint_v4_training_bundle_v1(
            &bounded,
            StableId::new("artifact:assembled")?,
            lineage(&bounded)?,
            &packet,
        ),
        Err(JointBundleAssemblyErrorV1::Capacity)
    );
    Ok(())
}
