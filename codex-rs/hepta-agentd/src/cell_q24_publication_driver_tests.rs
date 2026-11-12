//! Protocol and material negative controls with explicitly synthetic learning
//! receipts. These tests construct no original aggregate/Root Model factory and
//! do not claim an ordinary publication, independent evaluation or C task.

use codex_hepta_learning_artifacts::*;
use codex_hepta_neuron::CellLearningBindingV2;
use pretty_assertions::assert_eq;

use super::*;
use crate::neuron_generation_current::test_support::Fixture;
use crate::neuron_generation_current::test_support::config;
use crate::neuron_generation_update_bootstrap::learning_test_baseline;
use crate::neuron_generation_update_bootstrap::learning_test_decision;
use crate::neuron_generation_update_bootstrap::learning_test_receipt;

fn digest(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

fn no_update(
    baseline: CellCompatibilityBundleV1,
) -> anyhow::Result<LearningIterationCoordinatorV1> {
    let mut old = config()?;
    old.manifest.bundle_digest = baseline.digest()?.into_array();
    old.initial.manifest_digest = old.manifest.digest()?;
    let fixture = Fixture::new(old)?;
    learning_test_decision(&fixture, baseline, "none")
}

fn qualified(
    original: &LearningIterationCoordinatorV1,
    disposition: Option<LearningLocalDispositionV2>,
    policy: &str,
) -> anyhow::Result<LearningIterationCoordinatorV1> {
    let saved = original.snapshot();
    let mut current =
        LearningIterationCoordinatorV1::new(saved.request.clone(), saved.owners.clone())?;
    for receipt in &saved.receipts[..3] {
        current.record(receipt.clone(), /*now_unix_seconds*/ 20)?;
    }
    let candidate_bundle = current.candidate().unwrap().digest()?;
    for observation in [
        LearningIterationObservationV1::Evaluation {
            candidate_bundle,
            evaluation_profile: saved.request.evaluation_profile,
            disposition: LearningEvaluationDispositionV1::Qualified,
        },
        LearningIterationObservationV1::Proposal {
            candidate_bundle,
            proposal_id: saved.request.operation_id.clone(),
            composition_digest: digest("synthetic-proposal"),
            disposition: LearningProposalDispositionV1::UpdateCandidates,
        },
    ] {
        current.record(
            learning_test_receipt(&current, observation),
            /*now_unix_seconds*/ 20,
        )?;
    }
    if let Some(disposition) = disposition {
        let selected_bundle = if disposition == LearningLocalDispositionV2::AdoptCandidate {
            candidate_bundle
        } else {
            saved.request.selected_bundle.digest()?
        };
        let observation =
            LearningIterationObservationV1::LocalDecisionV2(LearningLocalDecisionV2 {
                proposal_head: current.snapshot().head_digest,
                candidate_bundle,
                selected_bundle,
                policy_digest: digest(policy),
                reason_digest: digest("synthetic-reason"),
                disposition,
            });
        current.record(
            learning_test_receipt(&current, observation),
            /*now_unix_seconds*/ 20,
        )?;
    }
    Ok(current)
}

#[test]
fn bare_qualification_and_rehashed_cut_substitutions_do_not_authorize_publication()
-> anyhow::Result<()> {
    let original = no_update(learning_test_baseline()?)?;
    let bare = qualified(&original, /*disposition*/ None, "policy")?;
    assert!(matches!(
        Decision::new(bare.snapshot().clone()),
        Err(Error::Binding(
            "actual local decision or original NoUpdate cut required"
        ))
    ));
    let admitted = qualified(
        &original,
        Some(LearningLocalDispositionV2::AdoptCandidate),
        "policy",
    )?;
    assert!(Decision::new(admitted.snapshot().clone())?.adopts());
    let mut tampered = admitted.snapshot().clone();
    tampered.receipts.last_mut().unwrap().evidence_digest = digest("substituted-original-receipt");
    assert!(matches!(
        Decision::new(tampered),
        Err(Error::Binding("original decision history"))
    ));
    // A correctly rehashed earlier cut is still not a local decision.
    let mut earlier = LearningIterationCoordinatorV1::new(
        original.snapshot().request.clone(),
        original.snapshot().owners.clone(),
    )?;
    for receipt in &original.snapshot().receipts[..3] {
        earlier.record(receipt.clone(), /*now_unix_seconds*/ 20)?;
    }
    assert!(matches!(
        Decision::new(earlier.snapshot().clone()),
        Err(Error::Binding(
            "actual local decision or original NoUpdate cut required"
        ))
    ));
    Ok(())
}

#[test]
fn no_update_retention_and_defer_preserve_original_operation_and_policy() -> anyhow::Result<()> {
    let original = no_update(learning_test_baseline()?)?;
    let unchanged = Decision::new(original.snapshot().clone())?;
    assert!(!unchanged.adopts());
    assert_eq!(
        unchanged.operation,
        crate::learning_retained_task_operation_id_v1(&original)?
    );
    assert!(matches!(
        unchanged.require_new_work(),
        Err(Error::Binding("new publication after original deadline"))
    ));
    for disposition in [
        LearningLocalDispositionV2::RetainParent,
        LearningLocalDispositionV2::DeferCandidate,
    ] {
        let first = qualified(&original, Some(disposition), "original-policy")?;
        let other = qualified(&original, Some(disposition), "replacement-policy")?;
        let first = Decision::new(first.snapshot().clone())?;
        let other = Decision::new(other.snapshot().clone())?;
        assert!(!first.adopts());
        assert_eq!(first.bundle, original.snapshot().request.selected_bundle);
        assert_ne!(first.operation, unchanged.operation);
        assert_ne!(first.operation, other.operation);
        assert_ne!(first.artifact_operation, other.artifact_operation);
    }
    Ok(())
}

fn model(output_width: u16) -> anyhow::Result<crate::LoadedCellQ24ModelV1> {
    let root = tempfile::tempdir()?;
    let file = |name: &str, rows: u16| -> anyhow::Result<std::fs::File> {
        let mut bytes = b"HQ24M001".to_vec();
        bytes.extend(rows.to_le_bytes());
        bytes.extend(1_u16.to_le_bytes());
        for _ in 0..rows {
            bytes.extend((1_i64 << 24).to_le_bytes());
        }
        let path = root.path().join(name);
        std::fs::write(&path, bytes)?;
        Ok(std::fs::File::open(path)?)
    };
    Ok(crate::LoadedCellQ24ModelV1::open_files(
        crate::CellQ24ModelFilesV1 {
            base: file("base", /*rows*/ 1)?,
            organ_adapter: None,
            cell_adapter: None,
            encoder: file("encoder", /*rows*/ 1)?,
            heads: file("heads", output_width * 2)?,
        },
    )?)
}

#[test]
fn artifact_material_is_exact_actual_b_manifest_and_full_learning_lineage() -> anyhow::Result<()> {
    let model = model(/*output_width*/ 1)?;
    let mut baseline = learning_test_baseline()?;
    baseline.components = model.components().clone();
    let original = no_update(baseline)?;
    let adopted = qualified(
        &original,
        Some(LearningLocalDispositionV2::AdoptCandidate),
        "policy",
    )?;
    let decision = Decision::new(adopted.snapshot().clone())?;
    let bundle = &decision.bundle;
    let lineage = bundle.training_lineage.as_ref().unwrap();
    let mut actual = config()?.manifest;
    actual.profile = crate::CellQ24GenerationWorkerV1::PROFILE.into();
    actual.bundle_digest = bundle.digest()?.into_array();
    actual.encoder = Some(bundle.components.encoder.into_array());
    actual.head = Some(bundle.components.heads.into_array());
    actual.input_schema = crate::CellQ24GenerationWorkerV1::input_schema_digest();
    actual.state_schema = bundle.components.state_schema.into_array();
    actual.output_schema = bundle.components.output_schema.into_array();
    actual.learning = CellLearningBindingV2::Frozen {
        weights: model.effective_weights_digest().into_array(),
    };
    actual.max_input_bytes = 18;
    actual.max_state_bytes = 1;
    actual.max_delta_bytes = 18;
    actual.max_prefix_bytes = 18;
    let payload = serde_json::to_vec(&actual)?;
    let manifest = LearningArtifactManifestV2 {
        artifact_id: bundle.artifact_id.clone(),
        kind: ArtifactKind::Model,
        generation: bundle.generation,
        provenance_mode: ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![lineage.dataset],
        lineage_digests: vec![
            lineage.source_bundle,
            lineage.dataset,
            lineage.update_rule,
            lineage.evaluation_profile,
            decision.snapshot.receipts[2].evidence_digest,
        ],
        predecessor_ids: vec![
            decision
                .snapshot
                .request
                .selected_bundle
                .artifact_id
                .clone(),
        ],
        rollback_predecessor: Some(
            decision
                .snapshot
                .request
                .selected_bundle
                .artifact_id
                .clone(),
        ),
        bytes_digest: Digest32::of_bytes(&payload),
        encoded_size_bytes: payload.len() as u64,
        training_code_digest: Digest32::from_array(actual.source_digest),
        runtime_tuple_digest: Digest32::from_array(actual.runtime_digest),
        device_profile_digest: Digest32::from_array(actual.device_digest),
        objective_class_digest: decision.snapshot.request.envelope.objective_digest,
        compatibility_digest: Digest32::from_array(actual.digest()?),
        schema_profile_digest: bundle.components.state_schema,
        normalization_digest: bundle.components.normalizer,
        producer_id: decision.snapshot.owners.trainer.clone(),
        created_at: 1,
        expires_at: 100,
    };
    validation::artifact_material(
        &decision,
        &actual,
        &manifest,
        &payload,
        &decision.artifact_operation,
    )?;
    for field in [
        "runtime",
        "device",
        "source",
        "producer",
        "dataset",
        "lineage",
        "rollback",
        "objective",
        "size",
    ] {
        let mut changed = manifest.clone();
        match field {
            "runtime" => changed.runtime_tuple_digest = digest("other-runtime"),
            "device" => changed.device_profile_digest = digest("other-device"),
            "source" => changed.training_code_digest = digest("other-source"),
            "producer" => changed.producer_id = StableId::new("other-producer")?,
            "dataset" => changed.source_dataset_digests.clear(),
            "lineage" => changed.lineage_digests.clear(),
            "rollback" => changed.rollback_predecessor = None,
            "objective" => changed.objective_class_digest = digest("other-objective"),
            "size" => changed.encoded_size_bytes += 1,
            _ => unreachable!(),
        }
        assert!(
            matches!(
                validation::artifact_material(
                    &decision,
                    &actual,
                    &changed,
                    &payload,
                    &decision.artifact_operation
                ),
                Err(Error::Binding(
                    "artifact request differs from original qualified material"
                ))
            ),
            "{field}"
        );
    }
    let mut substituted = actual.clone();
    substituted.device_digest = digest("different-B-device").into_array();
    let substituted_payload = serde_json::to_vec(&substituted)?;
    let mut rehashed = manifest;
    rehashed.bytes_digest = Digest32::of_bytes(&substituted_payload);
    rehashed.encoded_size_bytes = substituted_payload.len() as u64;
    rehashed.compatibility_digest = Digest32::from_array(substituted.digest()?);
    rehashed.device_profile_digest = Digest32::from_array(substituted.device_digest);
    assert!(matches!(
        validation::artifact_material(
            &decision,
            &actual,
            &rehashed,
            &substituted_payload,
            &decision.artifact_operation
        ),
        Err(Error::Binding(
            "artifact request differs from original qualified material"
        ))
    ));
    let wrong_operation = StableId::new("other-publication-operation")?;
    assert!(
        validation::artifact_material(&decision, &actual, &rehashed, &payload, &wrong_operation)
            .is_err()
    );
    Ok(())
}

#[path = "cell_q24_publication_feature_tests.rs"]
mod feature;

#[path = "cell_q24_publication_root_policy_tests.rs"]
mod root_policy;
