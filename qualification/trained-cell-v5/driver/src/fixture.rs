//! Public development identities, synthetic source notices and synthetic review
//! measurements. They are unrelated to installed product or scientific trust.

use crate::*;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

pub struct Fixture {
    pub config: LearningArtifactOwnerServiceConfigV1,
    pub policy: ScientificCandidatePolicyV1,
    owner: SigningKey,
    reviewer: SigningKey,
    selector: SigningKey,
}

pub fn signer(key: &SigningKey, name: &str, now: u64) -> Result<TrustedArtifactSignerV1> {
    Ok(TrustedArtifactSignerV1 {
        signer_id: id(name)?,
        verifying_key: key.verifying_key().to_bytes(),
        minimum_authority_epoch: 1,
        maximum_authority_epoch: 1,
        valid_from: now,
        expires_at: now + 3600,
        revoked_at: None,
    })
}

impl Fixture {
    pub fn new(root: &Path, now: u64) -> Result<Self> {
        fs::create_dir(root)?;
        let owner = SigningKey::from_bytes(&[53; 32]);
        let reviewer = SigningKey::from_bytes(&[54; 32]);
        let selector = SigningKey::from_bytes(&[55; 32]);
        let scope = DatasetWithdrawalScopeV1 {
            authority_domain_id: id("development-only")?,
            registry_id: id("typed-withdrawals")?,
            scope_id: id("typed-v5-mechanics")?,
        };
        let trust = ArtifactOwnerTrustV1 {
            registry_id: id("typed-artifacts")?,
            withdrawal_scope_digest: scope.digest(),
            minimum_registry_generation: Generation::new(1)?,
            genesis_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            writer_signers: vec![signer(&owner, "dev-owner", now)?],
            head_signers: vec![signer(&owner, "dev-owner", now)?],
        };
        let mut lease = SignedArtifactWriterLeaseV1 {
            lease_id: id("dev-lease")?,
            producer_id: id("dev-exporter")?,
            registry_id: trust.registry_id.clone(),
            withdrawal_scope_digest: scope.digest(),
            signer_id: id("dev-owner")?,
            signing_key_digest: Digest32::of_bytes(&owner.verifying_key().to_bytes()),
            authority_epoch: 1,
            lease_generation: 1,
            issued_at: now,
            expires_at: now + 3600,
            signature: [0; 64],
        };
        lease.signature = owner.sign(&lease.signing_bytes()).to_bytes();
        let policy = ScientificCandidatePolicyV1 {
            protocol_digest: digest(
                "SYNTHETIC development mechanics protocol; not V4 or V5 efficacy",
            ),
            candidate_definition_digest: digest("SYNTHETIC all12 typed lifecycle fixture"),
            task: ScientificComparisonPolicyV1 {
                comparison_digest: digest("SYNTHETIC task"),
                maximum_upper_bound: -0.001,
                minimum_observations: 3,
            },
            retention: ScientificComparisonPolicyV1 {
                comparison_digest: digest("SYNTHETIC retention"),
                maximum_upper_bound: 0.0,
                minimum_observations: 3,
            },
            total_cost: ScientificComparisonPolicyV1 {
                comparison_digest: digest("SYNTHETIC cost"),
                maximum_upper_bound: 3.0,
                minimum_observations: 3,
            },
        };
        Ok(Self {
            config: LearningArtifactOwnerServiceConfigV1 {
                root: root.to_path_buf(),
                trust,
                writer_lease: lease,
                required_current_head: None,
                withdrawal_registry: DatasetWithdrawalRegistry::new_scoped(scope),
                storage_binding: digest("development typed storage v5"),
                now,
            },
            policy,
            owner,
            reviewer,
            selector,
        })
    }

    pub fn manifest(
        &self,
        bundle: &TrainedCellBundleV5,
        payload: &[u8],
        previous: Option<StableId>,
        source: Digest32,
    ) -> LearningArtifactManifestV2 {
        LearningArtifactManifestV2 {
            artifact_id: bundle.artifact_id().clone(),
            kind: ArtifactKind::Parameters,
            generation: bundle.generation(),
            provenance_mode: ProvenanceModeV1::DatasetDerived,
            source_dataset_digests: vec![digest(&format!(
                "SYNTHETIC dataset {}",
                bundle.artifact_id()
            ))],
            lineage_digests: vec![digest("SYNTHETIC passing lifecycle evidence"), source],
            predecessor_ids: previous.iter().cloned().collect(),
            rollback_predecessor: previous,
            bytes_digest: bundle.content_digest(),
            encoded_size_bytes: payload.len() as u64,
            training_code_digest: digest(
                "development exporter source; identities in parity manifest",
            ),
            runtime_tuple_digest: digest("development qualification runtime"),
            device_profile_digest: digest("linux CPU float64"),
            objective_class_digest: self.policy.protocol_digest,
            compatibility_digest: trained_cell_compatibility_digest_v5(),
            schema_profile_digest: trained_cell_compatibility_digest_v5(),
            normalization_digest: trained_cell_normalization_digest_v5(),
            producer_id: self.config.writer_lease.producer_id.clone(),
            created_at: self.config.now,
            expires_at: self.config.now + 3600,
        }
    }

    pub fn request(
        &self,
        registry: &ArtifactRegistry,
        withdrawals: &DatasetWithdrawalRegistry,
        manifest: LearningArtifactManifestV2,
        payload: Vec<u8>,
    ) -> Result<LearningArtifactPublishRequestV1> {
        let now = self.config.now;
        let operation_id = id(&format!("publish:{}", manifest.artifact_id))?;
        let admission = admit_manifest_at_withdrawal_head_v3(
            withdrawals,
            withdrawals.head_digest(),
            manifest.clone(),
            now,
        )?;
        let previous = registry.snapshot().head_digest;
        let transaction = ArtifactPublicationTransactionV1::begin(
            operation_id.clone(),
            admission.clone(),
            withdrawals,
            registry,
            previous,
            now,
        )?;
        let mut staged = registry.clone();
        staged.append(ArtifactEvent::Register {
            event_id: id(&format!(
                "artifact-publication:{}",
                transaction.intent().intent_digest
            ))?,
            manifest: ArtifactManifest {
                artifact_id: manifest.artifact_id,
                kind: manifest.kind,
                generation: manifest.generation,
                predecessor_id: manifest.predecessor_ids.first().cloned(),
                content_digest: manifest.bytes_digest,
                objective_digest: manifest.objective_class_digest,
                support_digest: admission.validated_manifest.manifest_digest,
                producer_id: manifest.producer_id,
                compatibility_digest: manifest.compatibility_digest,
                encoded_size_bytes: manifest.encoded_size_bytes,
            },
        })?;
        let mut signed_current_head = SignedCurrentArtifactHeadV1 {
            withdrawal_scope_digest: self.config.trust.withdrawal_scope_digest,
            binding: self.config.storage_binding,
            witness: RegistryHeadWitnessV1 {
                registry_id: self.config.trust.registry_id.clone(),
                generation: Generation::new(staged.records().len() as u64)?,
                head_digest: staged.snapshot().head_digest,
                predecessor_head_digest: previous,
                authority_epoch: 1,
                signer_id: id("dev-owner")?,
                signing_key_digest: Digest32::of_bytes(&self.owner.verifying_key().to_bytes()),
                issued_at: now,
                expires_at: now + 3600,
            },
            signature: [0; 64],
        };
        signed_current_head.signature = self
            .owner
            .sign(&signed_current_head.signing_bytes())
            .to_bytes();
        Ok(LearningArtifactPublishRequestV1 {
            operation_id,
            admission,
            payload,
            signed_current_head,
            expected_registry_predecessor_head: previous,
            now,
        })
    }

    pub fn reviewer(&self) -> Result<TrustedArtifactSignerV1> {
        signer(&self.reviewer, "dev-reviewer", self.config.now)
    }

    pub fn review(
        &self,
        request: &LearningArtifactPublishRequestV1,
        task_upper: f64,
    ) -> Result<ScientificReviewEvidenceV1> {
        let measured = |gate: &ScientificComparisonPolicyV1, upper: f64, lower: f64| {
            ScientificMeasurementStatusV1::Measured(ScientificMeasurementV1 {
                comparison_digest: gate.comparison_digest,
                evidence_digest: digest("SYNTHETIC passing lifecycle evidence"),
                observations: 3,
                lower_bound: lower,
                estimate: upper,
                upper_bound: upper,
            })
        };
        let mut review = SignedScientificCandidateReviewV1 {
            reviewer_id: id("dev-reviewer")?,
            operation_id: request.operation_id.clone(),
            authority_epoch: 1,
            policy_digest: self.policy.digest(),
            admission_digest: request.admission.admission_digest,
            expected_registry_predecessor_head: request.expected_registry_predecessor_head,
            report_digest: digest("SYNTHETIC passing lifecycle evidence"),
            task: measured(&self.policy.task, task_upper, -1.0),
            retention: measured(&self.policy.retention, -0.005, -1.0),
            total_cost: measured(&self.policy.total_cost, 1.0, 0.0),
            issued_at: self.config.now,
            expires_at: self.config.now + 300,
            signature: [0; 64],
        };
        review.signature = self.reviewer.sign(&review.signing_bytes()).to_bytes();
        Ok(ScientificReviewEvidenceV1::Signed(Box::new(review)))
    }

    pub fn selection(
        &self,
        owner: &LearningArtifactOwnerService,
        artifact: &StableId,
    ) -> Result<VerifiedArtifactSelectionV1> {
        let now = self.config.now;
        let current = owner.current_registry_view(now)?;
        let manifest = owner
            .registry()
            .manifest(artifact)
            .ok_or("selected artifact missing")?;
        let mut signed = SignedArtifactSelectionV1 {
            selection_id: id(&format!("select:{artifact}"))?,
            artifact_id: artifact.clone(),
            registry_id: self.config.trust.registry_id.clone(),
            withdrawal_scope_digest: self.config.trust.withdrawal_scope_digest,
            registry_head_digest: current.receipt().head_digest,
            current_witness_digest: current.witness_digest(),
            current_trust_digest: current.trust_digest(),
            artifact_kind: manifest.kind,
            artifact_generation: manifest.generation,
            predecessor_id: manifest.predecessor_id.clone(),
            content_digest: manifest.content_digest,
            objective_digest: manifest.objective_digest,
            support_digest: manifest.support_digest,
            compatibility_digest: manifest.compatibility_digest,
            encoded_size_bytes: manifest.encoded_size_bytes,
            selector_id: id("dev-selector")?,
            selector_credential_digest: digest("SYNTHETIC independent selector credential"),
            signing_key_digest: Digest32::of_bytes(&self.selector.verifying_key().to_bytes()),
            authority_epoch: 1,
            issued_at: now,
            expires_at: now + 300,
            signature: [0; 64],
        };
        signed.signature = self.selector.sign(&signed.signing_bytes()).to_bytes();
        let verifier = ArtifactSelectionVerifierV1::new(
            ArtifactSelectionTrustV1 {
                registry_id: self.config.trust.registry_id.clone(),
                withdrawal_scope_digest: self.config.trust.withdrawal_scope_digest,
                minimum_authority_epoch: 1,
                selectors: vec![TrustedArtifactSelectorV1 {
                    selector_id: id("dev-selector")?,
                    verifying_key: self.selector.verifying_key().to_bytes(),
                    minimum_authority_epoch: 1,
                    maximum_authority_epoch: 1,
                    valid_from: now,
                    expires_at: now + 3600,
                    revoked_at: None,
                }],
            },
            &self.config.trust,
        )?;
        Ok(verifier.verify(&signed, &current, now)?)
    }

    pub fn withdraw(
        &self,
        registry: &mut DatasetWithdrawalRegistry,
        manifest: &LearningArtifactManifestV2,
    ) -> Result<()> {
        registry.append(DatasetWithdrawalNoticeV1 {
            notice_id: id(&format!("withdraw:{}", manifest.artifact_id))?,
            dataset_digest: manifest.source_dataset_digests[0],
            source_tombstone_digest: digest("SYNTHETIC tombstone"),
            authority_id: id("development-only")?,
            credential_chain_digest: digest("SYNTHETIC credential"),
            signing_key_digest: digest("SYNTHETIC source authority key"),
            authority_epoch: 1,
            issued_at: self.config.now,
        })?;
        Ok(())
    }
}
