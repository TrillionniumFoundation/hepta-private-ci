//! Same named artifact writer, immutable payloads and signed current heads.
use super::support::Fitted;
use super::support::Roles;
use super::support::micros;
use super::support::save;
use super::*;
use codex_hepta_learning_artifacts as artifacts;
use serde_json::json;

pub(super) struct Published {
    pub selected: artifacts::PinnedCandidateSpec,
    pub source: artifacts::LearningArtifactManifestV2,
    pub snapshot: PathBuf,
    pub payload: PathBuf,
}
pub(super) struct StudyView {
    root: PathBuf,
    trust: artifacts::ArtifactOwnerTrustV1,
    pub service: Mutex<Option<artifacts::LearningArtifactOwnerService>>,
    config: Mutex<artifacts::LearningArtifactOwnerServiceConfigV1>,
}
impl CurrentCognitiveRegistry for StudyView {
    fn current(&self) -> Result<VerifiedCurrentRegistryViewV1, String> {
        self.service
            .lock()
            .unwrap()
            .as_ref()
            .expect("named owner suspended for process restart")
            .current_registry_view(micros() / 1_000_000)
            .map_err(|e| e.to_string())
    }
}
impl StudyView {
    pub fn new(root: PathBuf, roles: &mut Roles) -> Self {
        let namespace = Digest32::of_bytes(root.to_string_lossy().as_bytes());
        let key = roles.processes[4].key;
        let signer = artifacts::TrustedArtifactSignerV1 {
            signer_id: id("publisher"),
            verifying_key: key,
            minimum_authority_epoch: 1,
            maximum_authority_epoch: 1,
            valid_from: roles.from / 1_000_000,
            expires_at: roles.until / 1_000_000,
            revoked_at: None,
        };
        let withdrawals =
            artifacts::DatasetWithdrawalRegistry::new_scoped(artifacts::DatasetWithdrawalScopeV1 {
                authority_domain_id: id("local-study-authority"),
                registry_id: id(&format!("study-withdrawals-{namespace}")),
                scope_id: id("local-study-scope"),
            });
        let trust = artifacts::ArtifactOwnerTrustV1 {
            registry_id: id(&format!("study-registry-{namespace}")),
            withdrawal_scope_digest: withdrawals.scope_digest().unwrap(),
            minimum_registry_generation: Generation::new(1).unwrap(),
            genesis_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            writer_signers: vec![signer.clone()],
            head_signers: vec![signer],
        };
        let mut lease = artifacts::SignedArtifactWriterLeaseV1 {
            lease_id: id("study-artifact-writer"),
            producer_id: id("generator"),
            registry_id: trust.registry_id.clone(),
            withdrawal_scope_digest: trust.withdrawal_scope_digest,
            signer_id: id("publisher"),
            signing_key_digest: Digest32::of_bytes(&key),
            authority_epoch: 1,
            lease_generation: 1,
            issued_at: roles.from / 1_000_000,
            expires_at: roles.until / 1_000_000,
            signature: [0; 64],
        };
        lease.signature = roles.processes[4].sign(&lease.signing_bytes());
        let config = artifacts::LearningArtifactOwnerServiceConfigV1 {
            root: root.clone(),
            trust: trust.clone(),
            writer_lease: lease,
            required_current_head: None,
            withdrawal_registry: withdrawals,
            storage_binding: hash("three-generation-storage"),
            now: micros() / 1_000_000,
        };
        let service = artifacts::LearningArtifactOwnerService::open(config.clone()).unwrap();
        save(
            &root.join("study-namespace.json"),
            &json!({"root":root,"registry_id":trust.registry_id.as_str(),
            "scope_digest":trust.withdrawal_scope_digest.to_string(),"administrative_domain":"one local study operator"}),
        );
        Self {
            root,
            trust,
            service: Mutex::new(Some(service)),
            config: Mutex::new(config),
        }
    }
    fn signed(
        &self,
        head: Digest32,
        predecessor: Digest32,
        records: usize,
        roles: &mut Roles,
    ) -> artifacts::SignedCurrentArtifactHeadV1 {
        let mut signed = artifacts::SignedCurrentArtifactHeadV1 {
            withdrawal_scope_digest: self.trust.withdrawal_scope_digest,
            binding: hash("three-generation-storage"),
            witness: artifacts::RegistryHeadWitnessV1 {
                registry_id: self.trust.registry_id.clone(),
                generation: Generation::new(records.try_into().unwrap()).unwrap(),
                head_digest: head,
                predecessor_head_digest: predecessor,
                authority_epoch: 1,
                signer_id: id("publisher"),
                signing_key_digest: Digest32::of_bytes(&roles.processes[4].key),
                issued_at: micros() / 1_000_000,
                expires_at: roles.until / 1_000_000,
            },
            signature: [0; 64],
        };
        signed.signature = roles.processes[4].sign(&signed.signing_bytes());
        signed
    }
    pub fn publish(
        &self,
        root: &std::path::Path,
        fitted: &Fitted,
        predecessor: Option<&ArtifactManifest>,
        roles: &mut Roles,
    ) -> Published {
        self.publish_declared_dataset(root, fitted, predecessor, fitted.pin.dataset_digest, roles)
    }
    pub fn publish_declared_dataset(
        &self,
        root: &std::path::Path,
        fitted: &Fitted,
        predecessor: Option<&ArtifactManifest>,
        source_dataset: Digest32,
        roles: &mut Roles,
    ) -> Published {
        let now = micros() / 1_000_000;
        let source = artifacts::LearningArtifactManifestV2 {
            artifact_id: fitted.artifact.artifact_id.clone(),
            kind: ArtifactKind::Policy,
            generation: fitted.artifact.generation,
            provenance_mode: artifacts::ProvenanceModeV1::DatasetDerived,
            source_dataset_digests: vec![source_dataset],
            lineage_digests: vec![fitted.snapshot.head_digest],
            predecessor_ids: predecessor.iter().map(|p| p.artifact_id.clone()).collect(),
            rollback_predecessor: None,
            bytes_digest: fitted.pin.payload_digest,
            encoded_size_bytes: fitted.bytes.len().try_into().unwrap(),
            training_code_digest: Digest32::of_bytes(include_bytes!(
                "cognitive_three_generation_support.rs"
            )),
            runtime_tuple_digest: hash("native-hepttb01-published-ranker-v1"),
            device_profile_digest: hash("local-cpu-fixedq32"),
            objective_class_digest: fitted.pin.objective_digest,
            compatibility_digest: fitted.pin.training_profile_digest,
            schema_profile_digest: hash("HEPTTB01"),
            normalization_digest: hash("native-q32-observed-correctness"),
            producer_id: id("generator"),
            created_at: now,
            expires_at: roles.until / 1_000_000,
        };
        let mut guard = self.service.lock().unwrap();
        let service = guard.as_mut().unwrap();
        let before = service.registry().snapshot().head_digest;
        let operation = id(&format!(
            "publish-generation-{}",
            fitted.artifact.generation.get()
        ));
        let withdrawals = service.withdrawal_registry();
        let admission = artifacts::admit_manifest_at_withdrawal_head_v3(
            withdrawals,
            withdrawals.head_digest(),
            source.clone(),
            now,
        )
        .unwrap();
        let transaction = artifacts::ArtifactPublicationTransactionV1::begin(
            operation.clone(),
            admission.clone(),
            withdrawals,
            service.registry(),
            before,
            now,
        )
        .unwrap();
        let mut projected = service.registry().clone();
        let manifest = ArtifactManifest {
            artifact_id: source.artifact_id.clone(),
            kind: source.kind,
            generation: source.generation,
            predecessor_id: predecessor.map(|p| p.artifact_id.clone()),
            content_digest: source.bytes_digest,
            objective_digest: source.objective_class_digest,
            support_digest: admission.validated_manifest.manifest_digest,
            producer_id: source.producer_id.clone(),
            compatibility_digest: source.compatibility_digest,
            encoded_size_bytes: source.encoded_size_bytes,
        };
        projected
            .append(ArtifactEvent::Register {
                event_id: id(&format!(
                    "artifact-publication:{}",
                    transaction.intent().intent_digest
                )),
                manifest: manifest.clone(),
            })
            .unwrap();
        let signed = self.signed(
            projected.snapshot().head_digest,
            before,
            projected.snapshot().records().len(),
            roles,
        );
        let publication = service
            .publish(artifacts::LearningArtifactPublishRequestV1 {
                operation_id: operation,
                admission,
                payload: fitted.bytes.clone(),
                signed_current_head: signed.clone(),
                expected_registry_predecessor_head: before,
                now,
            })
            .unwrap();
        self.config.lock().unwrap().required_current_head = Some(signed.clone());
        let current = service.current_registry_view(micros() / 1_000_000).unwrap();
        assert_eq!(
            service.registry().manifest(&source.artifact_id).unwrap(),
            &manifest
        );
        let receipt = current.receipt();
        let snapshot = self.root.join("registries").join(format!(
            "{}-{}.snapshot",
            receipt.head_digest, receipt.file_digest
        ));
        let payload = self.root.join("payloads").join(format!(
            "{}-{}.bin",
            source.artifact_id, source.bytes_digest
        ));
        // Exact observation copy for the evaluator; native consumption uses the
        // named owner's original immutable file paths, not this copy.
        write_candidate_payload(
            CreateOnlyArtifactFile::create(root.join("payload")).unwrap(),
            service.registry(),
            &manifest.artifact_id,
            &fitted.bytes,
        )
        .unwrap();
        save(
            &root.join("publication.json"),
            &json!({"owner":"LearningArtifactOwnerService", "head":publication.registry_head_digest.to_string(),
            "manifest_debug":format!("{source:?}"), "payload":payload, "snapshot":snapshot,
            "signed_current_bytes":support::hex(&signed.signing_bytes()), "signature":support::hex(&signed.signature)}),
        );
        Published {
            selected: artifacts::PinnedCandidateSpec {
                registry_receipt: receipt,
                manifest,
            },
            source,
            snapshot,
            payload,
        }
    }
    pub fn suspend(&self) {
        drop(
            self.service
                .lock()
                .unwrap()
                .take()
                .expect("one active named owner"),
        );
    }
    pub fn resume(&self) {
        let mut config = self.config.lock().unwrap().clone();
        config.now = micros() / 1_000_000;
        let mut guard = self.service.lock().unwrap();
        assert!(guard.is_none());
        *guard = Some(artifacts::LearningArtifactOwnerService::open(config).unwrap());
    }
    pub fn config(&self) -> artifacts::LearningArtifactOwnerServiceConfigV1 {
        self.config.lock().unwrap().clone()
    }
    pub fn revoke(&self, root: &std::path::Path, artifact: StableId, roles: &mut Roles) {
        let mut guard = self.service.lock().unwrap();
        let service = guard.as_mut().unwrap();
        let mut projected = service.registry().clone();
        let before = projected.snapshot().head_digest;
        let change = StateChange {
            event_id: id("study-revoke"),
            artifact_id: artifact,
            evaluator_id: id("publisher"),
            reason_digest: hash("explicit-study-withdrawal"),
        };
        projected
            .append(ArtifactEvent::Revoke(change.clone()))
            .unwrap();
        let signed = self.signed(
            projected.snapshot().head_digest,
            before,
            projected.snapshot().records().len(),
            roles,
        );
        let receipt = service
            .revoke(artifacts::LearningArtifactRevokeRequestV1 {
                operation_id: change.event_id.clone(),
                change,
                signed_current_head: signed.clone(),
                expected_registry_predecessor_head: before,
                now: micros() / 1_000_000,
            })
            .unwrap();
        self.config.lock().unwrap().required_current_head = Some(signed.clone());
        save(
            &root.join("revocation.json"),
            &json!({"scope":"actual named owner durable Revoke",
            "receipt":{"operation_id":receipt.operation_id.as_str(),"event_id":receipt.change.event_id.as_str(),
                "artifact_id":receipt.change.artifact_id.as_str(),"evaluator_id":receipt.change.evaluator_id.as_str(),
                "reason_digest":receipt.change.reason_digest.to_string(),"registry_head_digest":receipt.registry_head_digest.to_string(),
                "witness_digest":receipt.witness_digest.to_string(),"state_digest":receipt.state_digest.to_string(),"acknowledged_at":receipt.acknowledged_at},
            "receipt_debug":format!("{receipt:?}"), "signed_current_bytes":support::hex(&signed.signing_bytes()),
            "signature":support::hex(&signed.signature)}),
        );
    }
}
