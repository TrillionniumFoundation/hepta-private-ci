//! Concrete owner-evidence adapters for governed Agentd plasticity.
//!
//! This layer deliberately resolves only facts that already have authoritative
//! repository stores: DatasetSnapshotReceiptV3 against the current DurableLedger
//! frontier, and immutable Policy artifacts against the current ArtifactRegistry
//! frontier. Dynamic modulator/eligibility/signal facts are delegated to a
//! mandatory owner adapter rather than being reclassified as artifacts.

use std::collections::BTreeMap;

use codex_hepta_learning_artifacts::{ArtifactKind, ArtifactManifest, ArtifactRegistry};
use codex_hepta_learning_ledger::{
    DatasetSnapshotReceiptV3, verify_dataset_snapshot_receipt_v3,
};
use codex_hepta_types::{Digest32, StableId};

use crate::{
    PlasticityOwnerEvidenceErrorV1, PlasticityOwnerEvidenceKindV1,
    PlasticityOwnerEvidenceQueryV1, PlasticityOwnerEvidenceResolverV1,
    VerifiedPlasticityOwnerEvidenceV1,
};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityArtifactOwnerBindingV1 {
    pub kind: PlasticityOwnerEvidenceKindV1,
    pub artifact_id: StableId,
}

/// Resolver that closes the owner boundary for durable dataset and immutable
/// policy artifacts, while requiring another real owner for dynamic signals.
pub struct ConcretePlasticityOwnerEvidenceResolverV1 {
    dataset: DatasetSnapshotReceiptV3,
    artifacts: ArtifactRegistry,
    artifact_observed_at: u64,
    artifact_expires_at: u64,
    artifact_bindings: BTreeMap<PlasticityOwnerEvidenceKindV1, StableId>,
    dynamic: Box<dyn PlasticityOwnerEvidenceResolverV1 + Send>,
}

impl ConcretePlasticityOwnerEvidenceResolverV1 {
    pub fn new(
        dataset: DatasetSnapshotReceiptV3,
        artifacts: ArtifactRegistry,
        artifact_observed_at: u64,
        artifact_expires_at: u64,
        bindings: Vec<PlasticityArtifactOwnerBindingV1>,
        dynamic: Box<dyn PlasticityOwnerEvidenceResolverV1 + Send>,
    ) -> Result<Self, PlasticityOwnerEvidenceErrorV1> {
        if artifact_observed_at > artifact_expires_at {
            return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt);
        }
        let mut artifact_bindings = BTreeMap::new();
        for binding in bindings {
            if !matches!(
                binding.kind,
                PlasticityOwnerEvidenceKindV1::UpdateRule
                    | PlasticityOwnerEvidenceKindV1::MutationPolicy
            ) {
                return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt);
            }
            if artifact_bindings
                .insert(binding.kind, binding.artifact_id)
                .is_some()
            {
                return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt);
            }
        }
        for required in [
            PlasticityOwnerEvidenceKindV1::UpdateRule,
            PlasticityOwnerEvidenceKindV1::MutationPolicy,
        ] {
            if !artifact_bindings.contains_key(&required) {
                return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt);
            }
        }
        Ok(Self {
            dataset,
            artifacts,
            artifact_observed_at,
            artifact_expires_at,
            artifact_bindings,
            dynamic,
        })
    }

    fn resolve_dataset(
        &self,
        query: &PlasticityOwnerEvidenceQueryV1,
    ) -> Result<VerifiedPlasticityOwnerEvidenceV1, PlasticityOwnerEvidenceErrorV1> {
        verify_dataset_snapshot_receipt_v3(&self.dataset, query.now)
            .map_err(|_| PlasticityOwnerEvidenceErrorV1::Missing)?;
        let snapshot = &self.dataset.snapshot;
        if snapshot.dataset_digest != query.evidence_digest
            || snapshot.dataset_digest != query.dataset_digest
            || snapshot.objective_digest != query.objective_digest
            || snapshot.ledger_head_digest != query.qualification_evidence_head_digest
        {
            return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
        }
        Ok(receipt_from_query(
            query,
            self.dataset.producer.principal_id.clone(),
            snapshot.ledger_head_digest,
            snapshot.dataset_digest,
            self.dataset.producer.authenticated_at,
            self.dataset.producer.expires_at,
        ))
    }

    fn resolve_artifact(
        &self,
        query: &PlasticityOwnerEvidenceQueryV1,
    ) -> Result<VerifiedPlasticityOwnerEvidenceV1, PlasticityOwnerEvidenceErrorV1> {
        let current_head = self.artifacts.snapshot().head_digest;
        if current_head.is_zero() || current_head != query.artifact_registry_head_digest {
            return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
        }
        let artifact_id = self
            .artifact_bindings
            .get(&query.kind)
            .ok_or(PlasticityOwnerEvidenceErrorV1::Missing)?;
        let manifest = self
            .artifacts
            .manifest(artifact_id)
            .ok_or(PlasticityOwnerEvidenceErrorV1::Missing)?;
        if !self.artifacts.is_eligible(artifact_id)
            || manifest.kind != ArtifactKind::Policy
            || manifest.content_digest != query.evidence_digest
            || manifest.objective_digest != query.objective_digest
        {
            return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
        }
        Ok(receipt_from_query(
            query,
            manifest.producer_id.clone(),
            current_head,
            artifact_manifest_receipt_digest(manifest),
            self.artifact_observed_at,
            self.artifact_expires_at,
        ))
    }
}

impl PlasticityOwnerEvidenceResolverV1 for ConcretePlasticityOwnerEvidenceResolverV1 {
    fn resolve(
        &self,
        query: &PlasticityOwnerEvidenceQueryV1,
    ) -> Result<VerifiedPlasticityOwnerEvidenceV1, PlasticityOwnerEvidenceErrorV1> {
        match query.kind {
            PlasticityOwnerEvidenceKindV1::Dataset => self.resolve_dataset(query),
            PlasticityOwnerEvidenceKindV1::UpdateRule
            | PlasticityOwnerEvidenceKindV1::MutationPolicy => self.resolve_artifact(query),
            PlasticityOwnerEvidenceKindV1::Modulator
            | PlasticityOwnerEvidenceKindV1::ModulatorBroadcast
            | PlasticityOwnerEvidenceKindV1::Eligibility
            | PlasticityOwnerEvidenceKindV1::ParameterSignal => self.dynamic.resolve(query),
        }
    }
}

fn receipt_from_query(
    query: &PlasticityOwnerEvidenceQueryV1,
    owner_id: StableId,
    owner_store_head_digest: Digest32,
    owner_receipt_digest: Digest32,
    observed_at: u64,
    expires_at: u64,
) -> VerifiedPlasticityOwnerEvidenceV1 {
    VerifiedPlasticityOwnerEvidenceV1 {
        kind: query.kind,
        evidence_digest: query.evidence_digest,
        owner_id,
        owner_store_head_digest,
        owner_receipt_digest,
        objective_digest: query.objective_digest,
        selected_artifact_digest: query.selected_artifact_digest,
        artifact_registry_head_digest: query.artifact_registry_head_digest,
        qualification_evidence_head_digest: query.qualification_evidence_head_digest,
        window: query.window.clone(),
        dataset_digest: query.dataset_digest,
        baseline_generation: query.baseline_generation,
        layer_id: query.layer_id.clone(),
        parameter_id: query.parameter_id.clone(),
        signal_eligibility: query.signal_eligibility,
        signal_modulator: query.signal_modulator,
        signal_learning_rate: query.signal_learning_rate,
        signal_lower_bound: query.signal_lower_bound,
        signal_upper_bound: query.signal_upper_bound,
        observed_at,
        expires_at,
    }
}

fn artifact_manifest_receipt_digest(manifest: &ArtifactManifest) -> Digest32 {
    let mut bytes = b"hepta.agentd.plasticity-artifact-owner-receipt.v1\0".to_vec();
    push_id(&mut bytes, &manifest.artifact_id);
    bytes.push(match manifest.kind {
        ArtifactKind::Prompt => 0,
        ArtifactKind::Policy => 1,
        ArtifactKind::Model => 2,
        ArtifactKind::Workflow => 3,
        ArtifactKind::Skill => 4,
        ArtifactKind::Parameters => 5,
        ArtifactKind::Topology => 6,
        ArtifactKind::Code => 7,
        ArtifactKind::ExternalAdapter => 8,
    });
    bytes.extend_from_slice(&manifest.generation.get().to_be_bytes());
    match &manifest.predecessor_id {
        Some(value) => {
            bytes.push(1);
            push_id(&mut bytes, value);
        }
        None => bytes.push(0),
    }
    for digest in [
        manifest.content_digest,
        manifest.objective_digest,
        manifest.support_digest,
        manifest.compatibility_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_id(&mut bytes, &manifest.producer_id);
    bytes.extend_from_slice(&manifest.encoded_size_bytes.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}


#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_learning_artifacts::{ArtifactEvent, ArtifactManifest};
    use codex_hepta_learning_ledger::{
        AuthenticatedPrincipalV1, DatasetFreezeRequestV1, freeze_dataset_receipt_v3,
    };
    use codex_hepta_plasticity::ProposalWindowV2;
    use codex_hepta_types::Generation;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    struct UnavailableDynamic;
    impl PlasticityOwnerEvidenceResolverV1 for UnavailableDynamic {
        fn resolve(
            &self,
            _query: &PlasticityOwnerEvidenceQueryV1,
        ) -> Result<VerifiedPlasticityOwnerEvidenceV1, PlasticityOwnerEvidenceErrorV1> {
            Err(PlasticityOwnerEvidenceErrorV1::Unavailable)
        }
    }

    fn policy_manifest(
        artifact_id: &str,
        producer: &str,
        content: Digest32,
        objective: Digest32,
    ) -> ArtifactManifest {
        ArtifactManifest {
            artifact_id: id(artifact_id),
            kind: ArtifactKind::Policy,
            generation: Generation::new(1).expect("generation"),
            predecessor_id: None,
            content_digest: content,
            objective_digest: objective,
            support_digest: digest(&format!("{artifact_id}:support")),
            producer_id: id(producer),
            compatibility_digest: digest(&format!("{artifact_id}:compatibility")),
            encoded_size_bytes: 32,
        }
    }

    fn fixture() -> (
        ConcretePlasticityOwnerEvidenceResolverV1,
        Digest32,
        Digest32,
        Digest32,
    ) {
        let objective = digest("objective");
        let ledger_head = digest("ledger-head");
        let producer = AuthenticatedPrincipalV1 {
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
                snapshot_id: id("dataset:snapshot"),
                producer,
                ledger_head_digest: ledger_head,
                objective_digest: objective,
                eligible_frontier: 7,
                outcome_watermark: 7,
                correction_cut_digest: digest("dataset:correction"),
                revocation_cut_digest: digest("dataset:revocation"),
                inclusion_policy_digest: digest("dataset:policy"),
                source_record_digests: vec![digest("dataset:record")],
                pending_outcomes: 0,
                censored_outcomes: 0,
            },
            50,
        )
        .expect("dataset receipt");
        let dataset_digest = dataset.snapshot.dataset_digest;

        let update_digest = digest("update-rule");
        let mutation_digest = digest("mutation-policy");
        let mut artifacts = ArtifactRegistry::new();
        for (event_id, manifest) in [
            (
                "event:update-rule",
                policy_manifest(
                    "policy:update-rule",
                    "owner:update-rule",
                    update_digest,
                    objective,
                ),
            ),
            (
                "event:mutation-policy",
                policy_manifest(
                    "policy:mutation-policy",
                    "owner:mutation-policy",
                    mutation_digest,
                    objective,
                ),
            ),
        ] {
            artifacts
                .append(ArtifactEvent::Register {
                    event_id: id(event_id),
                    manifest,
                })
                .expect("artifact append");
        }
        let artifact_head = artifacts.snapshot().head_digest;
        let resolver = ConcretePlasticityOwnerEvidenceResolverV1::new(
            dataset,
            artifacts,
            40,
            60,
            vec![
                PlasticityArtifactOwnerBindingV1 {
                    kind: PlasticityOwnerEvidenceKindV1::UpdateRule,
                    artifact_id: id("policy:update-rule"),
                },
                PlasticityArtifactOwnerBindingV1 {
                    kind: PlasticityOwnerEvidenceKindV1::MutationPolicy,
                    artifact_id: id("policy:mutation-policy"),
                },
            ],
            Box::new(UnavailableDynamic),
        )
        .expect("resolver");
        (resolver, artifact_head, ledger_head, dataset_digest)
    }

    fn query(
        kind: PlasticityOwnerEvidenceKindV1,
        evidence_digest: Digest32,
        artifact_head: Digest32,
        ledger_head: Digest32,
        dataset_digest: Digest32,
    ) -> PlasticityOwnerEvidenceQueryV1 {
        PlasticityOwnerEvidenceQueryV1 {
            kind,
            evidence_digest,
            objective_digest: digest("objective"),
            selected_artifact_digest: digest("selected-artifact"),
            artifact_registry_head_digest: artifact_head,
            qualification_evidence_head_digest: ledger_head,
            window: ProposalWindowV2 {
                window_id: id("window:1"),
                window_digest: digest("window"),
            },
            dataset_digest,
            baseline_generation: Generation::new(1).expect("generation"),
            layer_id: None,
            parameter_id: None,
            signal_eligibility: None,
            signal_modulator: None,
            signal_learning_rate: None,
            signal_lower_bound: None,
            signal_upper_bound: None,
            now: 50,
        }
    }

    #[test]
    fn concrete_dataset_and_policy_adapters_bind_live_frontiers() {
        let (resolver, artifact_head, ledger_head, dataset_digest) = fixture();

        let dataset = resolver
            .resolve(&query(
                PlasticityOwnerEvidenceKindV1::Dataset,
                dataset_digest,
                artifact_head,
                ledger_head,
                dataset_digest,
            ))
            .expect("dataset owner");
        assert_eq!(dataset.owner_id, id("owner:dataset"));
        assert_eq!(dataset.owner_store_head_digest, ledger_head);

        let update = resolver
            .resolve(&query(
                PlasticityOwnerEvidenceKindV1::UpdateRule,
                digest("update-rule"),
                artifact_head,
                ledger_head,
                dataset_digest,
            ))
            .expect("update owner");
        assert_eq!(update.owner_id, id("owner:update-rule"));
        assert_eq!(update.owner_store_head_digest, artifact_head);

        let mutation = resolver
            .resolve(&query(
                PlasticityOwnerEvidenceKindV1::MutationPolicy,
                digest("mutation-policy"),
                artifact_head,
                ledger_head,
                dataset_digest,
            ))
            .expect("mutation owner");
        assert_eq!(mutation.owner_id, id("owner:mutation-policy"));
    }

    #[test]
    fn concrete_adapters_reject_rollback_frontiers_and_missing_dynamic_owner() {
        let (resolver, artifact_head, ledger_head, dataset_digest) = fixture();

        let mut stale_dataset = query(
            PlasticityOwnerEvidenceKindV1::Dataset,
            dataset_digest,
            artifact_head,
            ledger_head,
            dataset_digest,
        );
        stale_dataset.qualification_evidence_head_digest = digest("rolled-back-ledger");
        assert_eq!(
            resolver.resolve(&stale_dataset),
            Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch)
        );

        let mut stale_policy = query(
            PlasticityOwnerEvidenceKindV1::UpdateRule,
            digest("update-rule"),
            artifact_head,
            ledger_head,
            dataset_digest,
        );
        stale_policy.artifact_registry_head_digest = digest("rolled-back-artifacts");
        assert_eq!(
            resolver.resolve(&stale_policy),
            Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch)
        );

        assert_eq!(
            resolver.resolve(&query(
                PlasticityOwnerEvidenceKindV1::Modulator,
                digest("modulator"),
                artifact_head,
                ledger_head,
                dataset_digest,
            )),
            Err(PlasticityOwnerEvidenceErrorV1::Unavailable)
        );
    }
}
