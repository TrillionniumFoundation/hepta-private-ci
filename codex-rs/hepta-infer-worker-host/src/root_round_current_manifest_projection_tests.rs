//! Real original Artifact writer/ACK/Root Sources exercise the registration
//! reader. The isolated signing fixtures qualify no scientific model or role.
use super::*;
use codex_hepta_agent_components::intelligence_eval::*;
use codex_hepta_agent_components::learning_artifacts::*;
use codex_hepta_neuron::NeuronGenerationMaterialV2;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::os::unix::fs::PermissionsExt;

fn identity(value: &str) -> Result<StableId, Box<dyn std::error::Error>> {
    Ok(StableId::new(value)?)
}
fn pin(value: &[u8]) -> Digest32 { Digest32::of_bytes(value) }
type Manifests = [(ParameterRoleSourceV3, Digest32); 3];

struct OriginalWriter {
    owner: LearningArtifactOwnerHost,
    registry: ArtifactRegistry,
    withdrawals: DatasetWithdrawalRegistry,
    trust: ArtifactOwnerTrustV1,
    lease: SignedArtifactWriterLeaseV1,
    key: SigningKey,
    head: Option<SignedCurrentArtifactHeadV1>,
    root: PathBuf,
    now: u64,
}
impl OriginalWriter {
    fn open(root: PathBuf, now: u64) -> Result<Self, Box<dyn std::error::Error>> {
        std::fs::create_dir(&root)?;
        std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700))?;
        let key = SigningKey::from_bytes(&[73; 32]);
        let scope = DatasetWithdrawalScopeV1 {
            authority_domain_id: identity("native-projection-dataset-authority")?,
            registry_id: identity("native-projection-withdrawals")?,
            scope_id: identity("native-projection-scope")?,
        };
        let signer = TrustedArtifactSignerV1 {
            signer_id: identity("native-projection-owner-authority")?,
            verifying_key: key.verifying_key().to_bytes(),
            minimum_authority_epoch: 1, maximum_authority_epoch: 1,
            valid_from: now - 1000, expires_at: now + 60000, revoked_at: None,
        };
        let trust = ArtifactOwnerTrustV1 {
            registry_id: identity("native-projection-artifacts")?,
            withdrawal_scope_digest: scope.digest(),
            minimum_registry_generation: Generation::new(1)?,
            genesis_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            writer_signers: vec![signer.clone()], head_signers: vec![signer],
        };
        let mut lease = SignedArtifactWriterLeaseV1 {
            lease_id: identity("native-projection-existing-lease")?,
            producer_id: identity("native-projection-original-producer")?,
            registry_id: trust.registry_id.clone(), withdrawal_scope_digest: scope.digest(),
            signer_id: identity("native-projection-owner-authority")?,
            signing_key_digest: pin(key.verifying_key().as_bytes()),
            authority_epoch: 1, lease_generation: 1,
            issued_at: now, expires_at: now + 60000, signature: [0; 64],
        };
        lease.signature = key.sign(&lease.signing_bytes()).to_bytes();
        let owner = LearningArtifactOwnerHost::open(&root, trust.clone(), lease.clone(), now)?;
        Ok(Self { owner, registry: ArtifactRegistry::new(),
            withdrawals: DatasetWithdrawalRegistry::new_scoped(scope), trust, lease, key,
            head: None, root, now })
    }

    fn publish_material(
        &mut self,
        material: &NeuronGenerationMaterialV2,
        label: &str,
        predecessor: Option<StableId>,
        payloads: [Vec<u8>; 4],
    ) -> Result<(Manifests, StableId), Box<dyn std::error::Error>> {
        let mut sources = Vec::new();
        let mut model_id = None;
        for (index, payload) in payloads.into_iter().enumerate() {
            let kind = match index { 0 => ArtifactKind::Model, 3 => ArtifactKind::Parameters,
                _ => ArtifactKind::Policy };
            let artifact_id = identity(&format!("{label}.artifact.{index}"))?;
            if index == 0 { model_id = Some(artifact_id.clone()); }
            let manifest = LearningArtifactManifestV2 {
                artifact_id, kind, generation: material.runtime.generation,
                provenance_mode: ProvenanceModeV1::DatasetDerived,
                source_dataset_digests: vec![pin(b"original immutable dataset")],
                lineage_digests: vec![material.runtime.model_manifest_digest,
                    pin(&encode_neuron_generation_material_v2(material)?)],
                predecessor_ids: if index == 0 { predecessor.clone().into_iter().collect() }
                    else { Vec::new() }, rollback_predecessor: None,
                bytes_digest: pin(&payload), encoded_size_bytes: payload.len() as u64,
                training_code_digest: pin(b"original native fixture code"),
                runtime_tuple_digest: material.runtime.execution_profile_digest_v1()?,
                device_profile_digest: material.runtime.device_digest,
                objective_class_digest: material.scope.objective_digest,
                compatibility_digest: material.runtime.execution_profile_digest_v1()?,
                schema_profile_digest: pin(b"original three manifest projection fixture"),
                normalization_digest: material.runtime.normalization_digest,
                producer_id: self.owner.producer_id().clone(),
                created_at: self.now, expires_at: self.now + 60000,
            };
            let admission = admit_manifest_at_withdrawal_head_v3(&self.withdrawals,
                self.withdrawals.head_digest(), manifest, self.now)?;
            let manifest_digest = admission.validated_manifest.manifest_digest;
            let admission_digest = admission.admission_digest;
            let previous = self.registry.head_digest();
            let mut transaction = self.owner.begin_publication(
                identity(&format!("{label}.publication.{index}"))?, admission,
                &self.withdrawals, &self.registry, previous, self.now)?;
            self.owner.stage_compatibility_registration(&transaction, &mut self.registry, self.now)?;
            self.owner.ensure_payload_durable(&mut transaction, &self.registry, &payload, self.now)?;
            let binding = pin(b"original native projection storage binding");
            self.owner.ensure_registry_durable(&mut transaction, &self.registry,
                &self.withdrawals, binding, self.now)?;
            let mut head = SignedCurrentArtifactHeadV1 {
                withdrawal_scope_digest: self.trust.withdrawal_scope_digest, binding,
                witness: RegistryHeadWitnessV1 {
                    registry_id: self.trust.registry_id.clone(),
                    generation: self.head.as_ref().map_or(Ok(Generation::new(1)?),
                        |head| head.witness.generation.next())?,
                    head_digest: self.registry.head_digest(), predecessor_head_digest: previous,
                    authority_epoch: 1, signer_id: identity("native-projection-owner-authority")?,
                    signing_key_digest: pin(self.key.verifying_key().as_bytes()),
                    issued_at: self.now, expires_at: self.now + 60000,
                }, signature: [0; 64],
            };
            head.signature = self.key.sign(&head.signing_bytes()).to_bytes();
            self.owner.ensure_witness_durable(&mut transaction, &head, &self.withdrawals, self.now)?;
            self.owner.acknowledge(&mut transaction, &self.withdrawals, self.now)?;
            self.owner.publish_root_read_frontier(&self.withdrawals, self.now)?;
            self.head = Some(head);
            if index < 3 {
                let path = self.root.join("admissions").join(format!("{manifest_digest}.manifest"));
                let bytes = std::fs::read(&path)?;
                sources.push((ParameterRoleSourceV3 { path, digest: pin(&bytes).to_string() },
                    admission_digest));
            }
        }
        Ok((sources.try_into().map_err(|_| "three original manifests")?,
            model_id.ok_or("original model absent")?))
    }

    fn template(&self, baseline: &Manifests) -> Result<PathBuf, Box<dyn std::error::Error>> {
        let trust = encode_artifact_public_trust_v1(&self.trust)?;
        let trust_path = self.root.join("original-public-trust.bin");
        std::fs::write(&trust_path, &trust)?;
        let withdrawal_path = self.root.join("original-withdrawals.bin");
        let receipt = write_dataset_withdrawal_snapshot_beneath(&self.root,
            "original-withdrawals.bin", &self.withdrawals, pin(b"original withdrawal binding"))?;
        let path = self.root.join("original-registration.json");
        std::fs::write(&path, serde_json::to_vec(&serde_json::json!({
            "subject":"actual.agent", "owner": {"root":self.root,
                "trust":{"path":trust_path,"digest":pin(&trust).to_string()},
                "withdrawals":{"path":withdrawal_path,"digest":receipt.file_digest.to_string()},
                "withdrawal_binding":receipt.binding.to_string(),
                "withdrawal_scope":receipt.scope_digest.to_string(),
                "withdrawal_head":receipt.head_digest.to_string(),
                "withdrawal_records":receipt.records, "withdrawal_encoded_bytes":receipt.encoded_bytes},
            "manifests":baseline.iter().map(|(source,admission)|serde_json::json!({
                "source":source,"admission_digest":admission.to_string()})).collect::<Vec<_>>(),
            "predecessor_id":null,"predecessor_manifest_digest":null,
            "publication_operation_id":"baseline.publication.3",
        }))?)?;
        Ok(path)
    }
}

#[test]
#[ignore = "requires actual Root and isolated /run original writer custody"]
fn root_projects_successor_model_with_parentless_policies_and_preserves_actual_cold_ack()
-> TestResult {
    assert_eq!(rustix::process::geteuid().as_raw(), 0);
    let directory = tempfile::Builder::new().prefix("hepta-current-manifest-projection-")
        .tempdir_in("/run")?;
    let now: u64 = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)?
        .as_millis().try_into()?;
    let fixture = fixture::Fixture::new(directory.path().join("original-private-generations"))?;
    let round = fixture.round("actual.original.projection.goal", 1)?;
    let materials = fixture.derive(&round)?;
    let mut writer = OriginalWriter::open(directory.path().join("original-artifacts"), now)?;
    let (baseline, baseline_id) = writer.publish_material(materials.baseline(), "baseline", None,
        [b"weights".to_vec(), b"independent E calibration".to_vec(),
            b"independent E OOD".to_vec(), b"fixed heads".to_vec()])?;
    let template = writer.template(&baseline)?;
    let original = std::fs::read(&template)?;
    let template_pin = pin(&original);
    let subject = identity("actual.agent")?;
    let candidate = finalize_parameter_pre_registration_material_v1(
        &materials.candidates()[0].generation, 7, 9)?;
    let payloads = |material: &NeuronGenerationMaterialV2| -> Result<_, Box<dyn std::error::Error>> {
        Ok([b"weights".to_vec(), material.runtime.calibration_evidence_payload_v1()?,
            material.runtime.ood_evidence_payload_v1()?, b"fixed heads".to_vec()])
    };
    let (candidate_sources, candidate_id) = writer.publish_material(&candidate, "candidate",
        Some(baseline_id), payloads(&candidate)?)?;
    let first = project_registered_artifact_manifest_configuration_v3(&template,
        template_pin, &candidate_sources, &candidate, &subject, now)?;
    qualify_indexed_material_projection(directory.path(), materials.baseline(), &candidate,
        &subject, &first)?;
    let rollback = finalize_parameter_pre_registration_material_v1(materials.rollback(), 7, 9)?;
    let (rollback_sources, _) = writer.publish_material(&rollback, "rollback",
        Some(candidate_id), payloads(&rollback)?)?;
    let read_frontier = std::fs::read(writer.root.join("READ-CURRENT"))?;
    let projected = project_registered_artifact_manifest_configuration_v3(&template,
        template_pin, &rollback_sources, &rollback, &subject, now)?;
    let source = writer.root.join("projected-current-registration.json");
    std::fs::write(&source, &projected)?;
    let facts = inspect_registered_artifact_current_material_v3(&source, pin(&projected),
        &rollback, &subject, now)?;
    assert_eq!(facts.acknowledgement().operation_id.as_str(), "rollback.publication.3");
    assert_eq!(facts.current_head().witness.generation.get(), 12);
    assert!(facts.manifests()[1].manifest.predecessor_ids.is_empty());
    assert!(facts.manifests()[2].manifest.predecessor_ids.is_empty());
    let again = project_registered_artifact_manifest_configuration_v3(&template,
        template_pin, &rollback_sources, &rollback, &subject, now)?;
    assert_eq!(again, projected);
    // An older eligible material can observe the new actual ACK without
    // rewriting its historical four-artifact completion into that new head.
    let latest_candidate = project_registered_artifact_manifest_configuration_v3(&template,
        template_pin, &candidate_sources, &candidate, &subject, now)?;
    assert_ne!(first, latest_candidate);
    let cold = inspect_registered_artifact_current_material_v3(&source, pin(&projected),
        &rollback, &subject, now)?;
    assert_eq!(cold.acknowledgement(), facts.acknowledgement());
    let baseline_at_latest_head = project_registered_artifact_current_configuration_v3(
        &template, template_pin, materials.baseline(), &subject, now)?;
    let baseline_latest_source = writer.root.join("baseline-at-latest-head.json");
    std::fs::write(&baseline_latest_source, &baseline_at_latest_head)?;
    let baseline_current = inspect_registered_artifact_current_material_v3(
        &baseline_latest_source, pin(&baseline_at_latest_head), materials.baseline(), &subject, now)?;
    assert_eq!(baseline_current.acknowledgement(), facts.acknowledgement());
    assert_eq!(baseline_current.material_digest(), pin(&encode_neuron_generation_material_v2(materials.baseline())?));
    assert_ne!(baseline_current.material_digest(), facts.material_digest());
    let mut altered = rollback.clone();
    altered.body.source_revision_digest = pin(b"caller changed body revision");
    let body_digest = altered.body.semantic_digest()?;
    altered.store_context.body_bundle_digest = body_digest;
    altered.index_context.body_bundle_digest = body_digest;
    codex_hepta_neuron::validate_neuron_generation_material_v2(&altered)?;
    assert!(project_registered_artifact_manifest_configuration_v3(&template,
        template_pin, &rollback_sources, &altered, &subject, now).is_err());
    let mut swapped = rollback_sources.clone();
    swapped.swap(1, 2);
    assert!(project_registered_artifact_manifest_configuration_v3(&template,
        template_pin, &swapped, &rollback, &subject, now).is_err());
    assert_eq!(std::fs::read(&template)?, original);
    assert_eq!(std::fs::read(writer.root.join("READ-CURRENT"))?, read_frontier);
    assert!(!directory.path().join("original-private-generations").exists());
    assert!(matches!(LearningArtifactOwnerHost::open(&writer.root, writer.trust.clone(),
        writer.lease.clone(), now), Err(ArtifactOwnerHostError::WriterFenceBusy)));
    Ok(())
}

fn qualify_indexed_material_projection(
    directory: &Path,
    baseline: &NeuronGenerationMaterialV2,
    candidate: &NeuronGenerationMaterialV2,
    subject: &StableId,
    registration_bytes: &[u8],
) -> TestResult {
    use crate::initial_cpu_anchor::InstalledCpuSourceV1;
    use crate::initial_cpu_anchor::read_current_cpu_neuron_material_projection_v3;
    let publish = |name: &str, bytes: &[u8]| -> Result<InstalledCpuSourceV1, Box<dyn std::error::Error>> {
        let path = directory.join(name);
        std::fs::write(&path, bytes)?;
        Ok(InstalledCpuSourceV1 { path, digest: pin(bytes).to_string() })
    };
    let baseline_source = publish("indexed-baseline-material.json",
        &encode_neuron_generation_material_v2(baseline)?)?;
    let candidate_source = publish("indexed-candidate-material.json",
        &encode_neuron_generation_material_v2(candidate)?)?;
    let current_registration = publish("indexed-current-registration.json", registration_bytes)?;
    let registry_path = directory.join("original-model-index.json");
    let resolver = publish("original-model-resolver.json", &serde_json::to_vec(&serde_json::json!({
        "schema":"hepta.cpu-neuron.protected-model-resolver.v3", "subject":subject.as_str(),
        "registry_head":registry_path,
    }))?)?;
    let identity = |material: &NeuronGenerationMaterialV2| -> Result<_, Box<dyn std::error::Error>> {
        Ok(serde_json::json!({"generation":material.runtime.generation.get(),
            "configuration_digest":material.runtime.semantic_digest()?.to_string(),
            "body_digest":material.body.semantic_digest()?.to_string(), "subject":subject.as_str()}))
    };
    let original_identity = identity(baseline)?;
    std::fs::write(&registry_path, serde_json::to_vec(&serde_json::json!({
        "schema":"hepta.cpu-neuron.registered-model-head.v3", "current":original_identity,
        "registrations":[{"identity":original_identity,"installation":baseline_source,
            "operational_reader":"original-installed-model-use.v2"}],
    }))?)?;
    let original = read_current_cpu_neuron_material_projection_v3(&resolver, &baseline_source, subject)?;
    assert_eq!(encode_neuron_generation_material_v2(&original.material)?,
        encode_neuron_generation_material_v2(baseline)?);
    assert_eq!(original.current_registration_configuration, None);
    // This is a pinned factual configuration projection. It does not verify
    // these fixture role fields as a signature or grant any model capability.
    let use_configuration = publish("original-registered-use.json", &serde_json::to_vec(&serde_json::json!({
        "schema":"hepta.cpu-neuron.registered-model-use-config.v3", "subject":subject.as_str(),
        "workload_uid":999, "evaluation_config":current_registration,
        "independent_report":current_registration, "current_material":current_registration,
        "artifact_public_trust":current_registration, "selector_program":current_registration,
        "selector":{"id":"fixture-selector","uid":998,"gid":997,"public_key_hex":"ab".repeat(32),
            "credential_digest":pin(b"fixture credential").to_string(),"private_key_path":"/unused/fixture-selector"},
        "authority_epoch":1,"frozen_at_ms":1,"expires_at_ms":2,
        "inaccessible_paths":["/unused/a","/unused/b","/unused/c","/unused/d","/unused/e"],
    }))?)?;
    let successor_identity = identity(candidate)?;
    std::fs::write(&registry_path, serde_json::to_vec(&serde_json::json!({
        "schema":"hepta.cpu-neuron.registered-model-head.v3", "current":successor_identity,
        "registrations":[{"identity":successor_identity,"installation":candidate_source,
            "operational_reader":"original-registered-model-use.v3",
            "registered_model_use":{"configuration":use_configuration,"selection":current_registration},
            "tick_provider":current_registration,"weights":current_registration,
            "compiled_body":current_registration,"original_profile":current_registration}],
    }))?)?;
    assert!(original.revalidate().is_err());
    let successor = read_current_cpu_neuron_material_projection_v3(&resolver, &baseline_source, subject)?;
    assert_eq!(encode_neuron_generation_material_v2(&successor.material)?,
        encode_neuron_generation_material_v2(candidate)?);
    assert_eq!(successor.current_registration_configuration, Some(current_registration));
    assert_eq!(successor.registered_use_configuration, Some(use_configuration.clone()));
    successor.revalidate()?;
    let mut changed: serde_json::Value = serde_json::from_slice(&std::fs::read(&use_configuration.path)?)?;
    changed["subject"] = "another-agent".into();
    std::fs::write(&use_configuration.path, serde_json::to_vec(&changed)?)?;
    assert!(successor.revalidate().is_err());
    assert!(read_current_cpu_neuron_material_projection_v3(&resolver, &baseline_source, subject).is_err());
    Ok(())
}
