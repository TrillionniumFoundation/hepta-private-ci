#![allow(clippy::expect_used)]
#![cfg(unix)]

mod support;

use std::fs::OpenOptions;
use std::fs::{self};
use std::path::Path;

use anyhow::Result;
use codex_hepta_learning_artifacts::ArtifactEvent;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactManifest;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_artifacts::CreateOnlyArtifactFile;
use codex_hepta_learning_artifacts::write_registry_snapshot;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::CandidateSetCompleteness;
use codex_hepta_learning_ledger::DatasetFreezeRequestV1;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::EpisodeDecision;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::freeze_dataset_receipt_v3;
use codex_hepta_ndu::NduProjectionJournalV1;
use codex_hepta_ndu::NduProjectionKindV1;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_neuron::SparseJournal;
use codex_hepta_neuron::SparseTick;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;
use serde_json::json;

use codex_hepta_agentd::PlasticityDynamicSignalBindingV1;
use codex_hepta_agentd::plasticity_modulator_broadcast_digest_v1;
use codex_hepta_agentd::plasticity_modulator_digest_v1;
use support::fleet::FleetHarness;

const Q24: i64 = 1_i64 << 24;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("generation")
}

fn new_rw(path: &Path) -> std::fs::File {
    OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(path)
        .expect("create owner file")
}

fn policy_manifest(
    artifact_id: &str,
    producer: &str,
    content_digest: Digest32,
    objective_digest: Digest32,
) -> ArtifactManifest {
    ArtifactManifest {
        artifact_id: id(artifact_id),
        kind: ArtifactKind::Policy,
        generation: generation(1),
        predecessor_id: None,
        content_digest,
        objective_digest,
        support_digest: digest(&format!("{artifact_id}:support")),
        producer_id: id(producer),
        compatibility_digest: digest(&format!("{artifact_id}:compatibility")),
        encoded_size_bytes: 64,
    }
}

fn principal_json(principal: &AuthenticatedPrincipalV1) -> serde_json::Value {
    json!({
        "principal_id": principal.principal_id.as_str(),
        "credential_chain_digest": principal.credential_chain_digest.to_string(),
        "signing_key_digest": principal.signing_key_digest.to_string(),
        "scope_digest": principal.scope_digest.to_string(),
        "authority_epoch": principal.authority_epoch,
        "authenticated_at": principal.authenticated_at,
        "expires_at": principal.expires_at,
    })
}

fn hex32(value: [u8; 32]) -> String {
    value.iter().map(|byte| format!("{byte:02x}")).collect()
}

#[tokio::test]
async fn supervisor_exec_reconstructs_named_plasticity_owner_from_durable_descriptor() -> Result<()>
{
    let mut harness = FleetHarness::new()?;
    let agent = harness.register("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12", "plasticity-process")?;

    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    let objective_digest = digest("plasticity-process-objective");
    let selected_artifact_digest = digest("plasticity-process-selected-artifact");

    let ledger_path = root.join("learning-ledger");
    let ledger_binding = digest("plasticity-process-ledger-binding");
    let mut ledger = DurableLedger::create(new_rw(&ledger_path), ledger_binding, 32)?;
    ledger.append_qualification(
        Digest32::ZERO,
        LedgerEvent::Decision(EpisodeDecision {
            record_id: id("decision:plasticity-process"),
            episode_id: id("episode:plasticity-process"),
            objective_digest,
            policy_id: id("policy:plasticity-process"),
            candidate_ids: vec![id("candidate:update"), id("abstain")],
            selected_candidate_id: id("candidate:update"),
            selected_propensity: ProbabilityQ32::from_raw(1_u64 << 31)?,
            completeness: CandidateSetCompleteness::Complete,
            support_digest: digest("plasticity-process-decision-support"),
        }),
    )?;
    let ledger_snapshot = ledger.snapshot()?;
    let ledger_head = ledger_snapshot.head_digest;
    let ledger_records = u64::try_from(ledger_snapshot.records().len())?;

    let dataset_principal = AuthenticatedPrincipalV1 {
        principal_id: id("owner:dataset"),
        credential_chain_digest: digest("dataset:credential"),
        signing_key_digest: digest("dataset:key"),
        scope_digest: digest("dataset:scope"),
        authority_epoch: 1,
        authenticated_at: 10,
        expires_at: 100,
    };
    let dataset = freeze_dataset_receipt_v3(
        DatasetFreezeRequestV1 {
            snapshot_id: id("dataset:plasticity-process"),
            producer: dataset_principal.clone(),
            ledger_head_digest: ledger_head,
            objective_digest,
            eligible_frontier: 1,
            outcome_watermark: 1,
            correction_cut_digest: digest("dataset:correction"),
            revocation_cut_digest: digest("dataset:revocation"),
            inclusion_policy_digest: digest("dataset:policy"),
            source_record_digests: vec![ledger_head],
            pending_outcomes: 0,
            censored_outcomes: 0,
        },
        50,
    )?;

    let signal_binding = PlasticityDynamicSignalBindingV1 {
        layer_id: id("layer:plasticity-process"),
        parameter_id: id("parameter:plasticity-process"),
        eligibility_index: 0,
        modulator_weights: vec![FixedQ32::ONE],
    };
    let broadcast_digest =
        plasticity_modulator_broadcast_digest_v1(std::iter::once(&signal_binding))?;
    let update_rule_digest = digest("plasticity-process-update-rule");
    let mutation_policy_digest = digest("plasticity-process-mutation-policy");

    let mut artifacts = ArtifactRegistry::new();
    for (event_id, manifest) in [
        (
            "event:baseline",
            ArtifactManifest {
                artifact_id: id("artifact:baseline"),
                kind: ArtifactKind::Model,
                generation: generation(1),
                predecessor_id: None,
                content_digest: selected_artifact_digest,
                objective_digest,
                support_digest: digest("baseline:support"),
                producer_id: id("owner:model"),
                compatibility_digest: digest("baseline:compatibility"),
                encoded_size_bytes: 128,
            },
        ),
        (
            "event:update-rule",
            policy_manifest(
                "policy:update-rule",
                "owner:update-rule",
                update_rule_digest,
                objective_digest,
            ),
        ),
        (
            "event:mutation-policy",
            policy_manifest(
                "policy:mutation",
                "owner:mutation-policy",
                mutation_policy_digest,
                objective_digest,
            ),
        ),
        (
            "event:broadcast",
            policy_manifest(
                "policy:broadcast",
                "owner:broadcast",
                broadcast_digest,
                objective_digest,
            ),
        ),
    ] {
        artifacts.append(ArtifactEvent::Register {
            event_id: id(event_id),
            manifest,
        })?;
    }
    let artifact_snapshot_path = root.join("artifact-registry.snapshot");
    let artifact_binding = digest("plasticity-process-artifact-binding");
    let artifact_receipt = write_registry_snapshot(
        CreateOnlyArtifactFile::create(&artifact_snapshot_path)?,
        &artifacts,
        artifact_binding,
    )?;

    let modulator_values = vec![FixedQ32::from_raw(FixedQ32::ONE.raw() / 2)];
    let ndu_subject_digest = digest("plasticity-process-ndu-subject");
    let modulator_digest =
        plasticity_modulator_digest_v1(objective_digest, ndu_subject_digest, &modulator_values)?;
    let mut ndu = NduProjectionJournalV1::new();
    ndu.append_projection(
        NduProjectionKindV1::Utility,
        digest("ndu:plasticity-process-projection"),
        objective_digest,
        ndu_subject_digest,
        modulator_digest,
    )?;
    ndu.select_projection(
        digest("ndu:plasticity-process-selection"),
        objective_digest,
        ndu_subject_digest,
        modulator_digest,
    )?;
    let ndu_path = root.join("ndu-projection.journal");
    fs::write(&ndu_path, ndu.export_bytes())?;

    let neuron_path = root.join("neuron.journal");
    let neuron_scope_digest = digest("plasticity-process-neuron-scope");
    let neuron_config = SparseConfig {
        model_digest: selected_artifact_digest,
        normalization_digest: digest("plasticity-process-normalization"),
        generation: generation(1),
        width: 5,
        top_k: 1,
        temporal_decay_q24: Q24 / 2,
        inhibition_gain_q24: 0,
        inhibition: Vec::new(),
        activity_decay_q24: Q24 / 2,
        target_activity_q24: Q24 / 4,
        threshold_rate_q24: Q24 / 10,
        threshold_min_q24: -Q24,
        threshold_max_q24: Q24,
        eligibility_decay_q24: Q24 / 2,
    };
    let mut neuron = SparseJournal::open(
        new_rw(&neuron_path),
        neuron_config.clone(),
        JournalScope {
            scope_digest: neuron_scope_digest,
            objective_digest,
        },
        16,
    )?;
    neuron.commit(
        Digest32::ZERO,
        &SparseTick {
            scope_digest: neuron_scope_digest,
            objective_digest,
            ndu_digest: digest("plasticity-process-ndu-input"),
            body_digest: digest("plasticity-process-body"),
            input_digest: digest("plasticity-process-input"),
            sequence: 1,
            monotonic_micros: 1,
            drive_q24: vec![Q24, Q24 / 2, 0, 0, 0],
            prediction_q24: vec![0; 5],
        },
    )?;
    let neuron_anchor = neuron.current_anchor()?.expect("neuron anchor");

    let trust_scope = digest("plasticity-process-trust-scope");
    let keys = [
        SigningKey::from_bytes(&[11; 32]),
        SigningKey::from_bytes(&[22; 32]),
        SigningKey::from_bytes(&[33; 32]),
    ];
    let trust_signers = keys
        .iter()
        .enumerate()
        .map(|(index, key)| {
            let principal = AuthenticatedPrincipalV1 {
                principal_id: id(&format!("plasticity-process-signer-{index}")),
                credential_chain_digest: digest(&format!("plasticity-process-credential-{index}")),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                scope_digest: trust_scope,
                authority_epoch: 7,
                authenticated_at: 10,
                expires_at: 100,
            };
            let role = match index {
                0 => "generator",
                1 => "observer",
                _ => "evaluator",
            };
            json!({
                "principal": principal_json(&principal),
                "controller_id": format!("plasticity-process-controller-{index}"),
                "verifying_key_hex": hex32(key.verifying_key().to_bytes()),
                "roles": [role],
                "revoked_at": null,
            })
        })
        .collect::<Vec<_>>();

    let parameter_registry = root.join("parameter-registry");
    let parameter_anchor = root.join("parameter-anchor");
    let topology_registry = root.join("topology-registry");
    let topology_anchor = root.join("topology-anchor");

    let descriptor_path = root.join("plasticity-bootstrap.json");
    let descriptor = json!({
        "schema": "hepta.agentd.plasticity-bootstrap.v1",
        "agent_id": agent.agent_id.as_str(),
        "spawn_generation": 1,
        "queue_capacity": 8,
        "objective_digest": objective_digest.to_string(),
        "artifacts": {
            "path": artifact_snapshot_path,
            "receipt": {
                "binding": artifact_receipt.binding.to_string(),
                "head_digest": artifact_receipt.head_digest.to_string(),
                "file_digest": artifact_receipt.file_digest.to_string(),
                "records": artifact_receipt.records,
                "encoded_bytes": artifact_receipt.encoded_bytes,
            },
            "observed_at": 40,
            "expires_at": 60,
            "update_rule_artifact_id": "policy:update-rule",
            "mutation_policy_artifact_id": "policy:mutation",
            "broadcast_artifact_id": "policy:broadcast",
        },
        "ledger": {
            "path": ledger_path,
            "binding": ledger_binding.to_string(),
            "max_records": 32,
            "anchor_sequence": ledger_records,
            "anchor_chain_digest": ledger_head.to_string(),
        },
        "dataset": {
            "snapshot": {
                "snapshot_id": dataset.snapshot.snapshot_id.as_str(),
                "ledger_head_digest": dataset.snapshot.ledger_head_digest.to_string(),
                "objective_digest": dataset.snapshot.objective_digest.to_string(),
                "eligible_frontier": dataset.snapshot.eligible_frontier,
                "outcome_watermark": dataset.snapshot.outcome_watermark,
                "source_record_digests": dataset.snapshot.source_record_digests
                    .iter().map(ToString::to_string).collect::<Vec<_>>(),
                "pending_outcomes": dataset.snapshot.pending_outcomes,
                "censored_outcomes": dataset.snapshot.censored_outcomes,
                "dataset_digest": dataset.snapshot.dataset_digest.to_string(),
            },
            "producer": principal_json(&dataset.producer),
            "correction_cut_digest": dataset.correction_cut_digest.to_string(),
            "revocation_cut_digest": dataset.revocation_cut_digest.to_string(),
            "inclusion_policy_digest": dataset.inclusion_policy_digest.to_string(),
        },
        "ndu": {
            "journal_path": ndu_path,
            "subject_digest": ndu_subject_digest.to_string(),
            "owner_id": "owner:utility.ndu",
            "modulator_values_raw_q32": modulator_values.iter().map(|value| value.raw()).collect::<Vec<_>>(),
        },
        "neuron": {
            "journal_path": neuron_path,
            "owner_id": "owner:neuron.runtime",
            "scope_digest": neuron_scope_digest.to_string(),
            "objective_digest": objective_digest.to_string(),
            "max_records": 16,
            "anchor_sequence": neuron_anchor.sequence,
            "anchor_checkpoint_digest": neuron_anchor.checkpoint_digest.to_string(),
            "config": {
                "model_digest": neuron_config.model_digest.to_string(),
                "normalization_digest": neuron_config.normalization_digest.to_string(),
                "generation": neuron_config.generation.get(),
                "width": neuron_config.width,
                "top_k": neuron_config.top_k,
                "temporal_decay_q24": neuron_config.temporal_decay_q24,
                "inhibition_gain_q24": neuron_config.inhibition_gain_q24,
                "inhibition": [],
                "activity_decay_q24": neuron_config.activity_decay_q24,
                "target_activity_q24": neuron_config.target_activity_q24,
                "threshold_rate_q24": neuron_config.threshold_rate_q24,
                "threshold_min_q24": neuron_config.threshold_min_q24,
                "threshold_max_q24": neuron_config.threshold_max_q24,
                "eligibility_decay_q24": neuron_config.eligibility_decay_q24,
            }
        },
        "signal_bindings": [{
            "layer_id": signal_binding.layer_id.as_str(),
            "parameter_id": signal_binding.parameter_id.as_str(),
            "eligibility_index": signal_binding.eligibility_index,
            "modulator_weights_raw_q32": signal_binding.modulator_weights
                .iter().map(|value| value.raw()).collect::<Vec<_>>(),
        }],
        "trust": {
            "scope_digest": trust_scope.to_string(),
            "objective_digest": objective_digest.to_string(),
            "authority_epoch": 7,
            "signers": trust_signers,
        },
        "owner_policy": {
            "dataset_owner_id": "owner:dataset",
            "update_rule_owner_id": "owner:update-rule",
            "modulator_owner_id": "owner:utility.ndu",
            "modulator_broadcast_owner_id": "owner:broadcast",
            "eligibility_owner_id": "owner:neuron.runtime",
            "parameter_signal_owner_id": "owner:neuron.runtime",
            "mutation_policy_owner_id": "owner:mutation-policy",
        },
        "parameter_registry": {
            "mode": "bootstrap_new",
            "registry_path": parameter_registry,
            "anchor_path": parameter_anchor,
            "scope_digest": digest("plasticity-process-parameter-scope").to_string(),
            "maximum_records": 32,
        },
        "topology_registry": {
            "mode": "bootstrap_new",
            "registry_path": topology_registry,
            "anchor_path": topology_anchor,
            "scope_digest": digest("plasticity-process-topology-scope").to_string(),
            "maximum_records": 32,
        }
    });
    let descriptor_bytes = serde_json::to_vec_pretty(&descriptor)?;
    let descriptor_digest = Digest32::of_bytes(&descriptor_bytes).to_string();
    fs::write(&descriptor_path, descriptor_bytes)?;

    // The child must own every mutable descriptor referenced above.
    drop(neuron);
    drop(ledger);
    drop(artifacts);

    harness.start_with_plasticity_bootstrap_descriptor(
        &agent,
        &descriptor_path,
        &descriptor_digest,
    )?;
    let (_control, health) = harness.wait_ready(&agent, 1).await?;
    assert!(health.ready);
    assert!(!health.fenced);

    for path in [
        parameter_registry,
        parameter_anchor,
        topology_registry,
        topology_anchor,
    ] {
        assert!(fs::metadata(path)?.len() > 0);
    }
    Ok(())
}
