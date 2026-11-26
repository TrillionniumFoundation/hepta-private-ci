#![allow(clippy::unwrap_used, reason = "local durable-owner fixture assertions")]
use super::support::NOW;
use super::support::decision;
use super::support::digest;
use super::support::id;
use super::support::outcome;
use super::support::sign;
use codex_hepta_agent_components::bellman_operator::*;
use codex_hepta_agent_components::learning_artifacts as artifacts;
use codex_hepta_agent_components::learning_ledger::*;
use codex_hepta_agent_components::types::Digest32;
use codex_hepta_agent_components::types::Generation;
use codex_hepta_agent_components::types::StableId;
use std::fs::File;

pub(super) fn collect(owner: &mut LedgerWriter, prefix: &str, selected: &str, value: i64) {
    collect_with_support(owner, prefix, selected, value, decision().support_digest);
}

pub(super) fn collect_with_support(
    owner: &mut LedgerWriter,
    prefix: &str,
    selected: &str,
    value: i64,
    support_digest: Digest32,
) {
    let mut request = decision();
    request.support_digest = support_digest;
    request.record_id = id(&format!("{prefix}.decision"));
    request.episode_id = id(&format!("{prefix}.episode"));
    request.selected_candidate_id = id(selected);
    let signed = sign(
        owner.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &decision_signing_payload_v2(&request).unwrap(),
    );
    let predecessor = owner.witness_frontier().unwrap().anchor.chain_digest;
    let receipt = owner
        .append_decision(predecessor, request, &signed, NOW)
        .unwrap();
    let mut observed = outcome(
        &format!("{prefix}.result-record"),
        &format!("{prefix}.result"),
        None,
        value,
    );
    observed.episode_id = id(&format!("{prefix}.episode"));
    let signed = sign(
        owner.verifier(),
        "observer",
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&observed),
    );
    owner
        .append_outcome(receipt.chain_digest, observed, &signed, NOW)
        .unwrap();
}

pub(super) fn freeze(owner: &LedgerWriter, name: &str) -> DatasetSnapshotReceiptV3 {
    let plan = DatasetFreezePlanV2 {
        snapshot_id: id(name),
        objective_digest: digest("objective"),
        inclusion_policy_digest: digest("all-active-owner-episodes"),
    };
    let payload = dataset_freeze_signing_payload_v2(&owner.snapshot().unwrap(), &plan).unwrap();
    let signed = sign(
        owner.verifier(),
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &payload,
    );
    owner.freeze_dataset(plan, &signed, NOW).unwrap()
}

pub(super) fn profile(generation: u64) -> TerminalCellProfileV1 {
    TerminalCellProfileV1 {
        artifact_id: id(&format!("local.cell.generation.{generation}")),
        producer_id: id("operator.native.owner"),
        generation: Generation::new(generation).unwrap(),
        sensor_id: id("single-approved-state"),
        objective_digest: digest("objective"),
        run_snapshot_digest: digest("run-snapshot"),
        unit_profile_digest: digest("reward-units"),
        action_ids: vec![id("abstain"), id("read")],
        minimum_samples_per_action: 1,
    }
}

pub(super) fn persist_reload(
    root: &std::path::Path,
    registry: &mut artifacts::ArtifactRegistry,
    trained: &TabularOperatorArtifactV1,
    predecessor: Option<StableId>,
) -> LoadedTabularOperatorV1 {
    let bytes = encode_tabular_payload_v1(trained).unwrap();
    let manifest = artifacts::ArtifactManifest {
        artifact_id: trained.artifact_id.clone(),
        kind: artifacts::ArtifactKind::Policy,
        generation: trained.generation,
        predecessor_id: predecessor,
        content_digest: Digest32::of_bytes(&bytes),
        objective_digest: trained.objective_digest,
        support_digest: trained.dataset_digest,
        producer_id: trained.producer_id.clone(),
        compatibility_digest: trained.training_profile_digest,
        encoded_size_bytes: bytes.len() as u64,
    };
    registry
        .append(artifacts::ArtifactEvent::Register {
            event_id: id(&format!("register.{}", trained.generation.get())),
            manifest: manifest.clone(),
        })
        .unwrap();
    let payload = root.join(format!("payload-{}", trained.generation.get()));
    let snapshot = root.join(format!("registry-{}", trained.generation.get()));
    artifacts::write_candidate_payload(
        artifacts::CreateOnlyArtifactFile::create(&payload).unwrap(),
        registry,
        &manifest.artifact_id,
        &bytes,
    )
    .unwrap();
    let receipt = artifacts::write_registry_snapshot(
        artifacts::CreateOnlyArtifactFile::create(&snapshot).unwrap(),
        registry,
        digest("host-artifact-binding"),
    )
    .unwrap();
    let retained = artifacts::PinnedCandidateSpec {
        registry_receipt: receipt,
        manifest,
    };
    let loaded = artifacts::load_pinned_candidate(
        File::open(snapshot).unwrap(),
        File::open(payload).unwrap(),
        retained,
    )
    .unwrap();
    let pin = TabularPayloadPinV1 {
        payload_digest: Digest32::of_bytes(&bytes),
        artifact_digest: trained.artifact_digest,
        objective_digest: trained.objective_digest,
        dataset_digest: trained.dataset_digest,
        sensor_core_digest: trained.sensor_core_digest,
        training_profile_digest: trained.training_profile_digest,
        generation: trained.generation,
    };
    LoadedTabularOperatorV1::from_pinned_payload(loaded.bytes(), &pin).unwrap()
}
