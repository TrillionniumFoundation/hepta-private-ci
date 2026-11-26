//! Isolated durable fixtures, never installed data or scientific qualification.
#![allow(clippy::expect_used, clippy::unwrap_used)]
use super::*;
use codex_hepta_agent_components::types::FixedQ32;
use codex_hepta_agent_components::types::Generation;
use codex_hepta_agent_components::types::ProbabilityQ32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use ledger::*;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::{self};
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;

pub(super) fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}
pub(super) fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

pub(super) struct Fixture {
    pub root: PathBuf,
    pub writer: LedgerWriter,
    pub owner: LearningArtifactOwnerService,
    pub intent: HostLearningWithdrawalIntentV1,
    pub config: LearningArtifactOwnerServiceConfigV1,
    pub trust: ActivatedLearningTrustV1,
    pub key: SigningKey,
    pub now: u64,
}
impl Fixture {
    pub fn new(root: PathBuf) -> Self {
        fs::create_dir_all(&root).unwrap();
        fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).unwrap();
        let now = wall_clock_millis().unwrap();
        let keys: [SigningKey; 4] =
            std::array::from_fn(|i| SigningKey::from_bytes(&[71 + i as u8; 32]));
        let principals: [AuthenticatedPrincipalV1; 4] =
            std::array::from_fn(|i| AuthenticatedPrincipalV1 {
                principal_id: id(&format!("fixture-authority-{i}")),
                credential_chain_digest: digest(&format!("fixture-chain-{i}")),
                signing_key_digest: Digest32::of_bytes(keys[i].verifying_key().as_bytes()),
                scope_digest: digest("fixture-scope"),
                authority_epoch: 1,
                authenticated_at: now - 1000,
                expires_at: now + 120_000,
            });
        let signers = (0..4)
            .map(|i| TrustedLearningSignerV1 {
                principal: principals[i].clone(),
                controller_id: id(&format!("fixture-controller-{i}")),
                verifying_key: keys[i].verifying_key().to_bytes(),
                roles: vec![role(i)],
                revoked_at: None,
            })
            .collect();
        let root_key = SigningKey::from_bytes(&[99; 32]);
        let trust_root = LearningTrustRootV1 {
            root_id: id("fixture-root"),
            scope_digest: digest("fixture-scope"),
            verifying_key: root_key.verifying_key().to_bytes(),
            valid_from: now - 1000,
            expires_at: now + 120_000,
            revoked_at: None,
        };
        let mut distribution = SignedLearningTrustDistributionV1 {
            distribution: LearningTrustDistributionV1 {
                distribution_id: id("fixture-distribution"),
                generation: 1,
                effective_at: now - 1000,
                trust: LearningEvidenceTrustV1 {
                    scope_digest: digest("fixture-scope"),
                    objective_digest: digest("fixture-objective"),
                    authority_epoch: 1,
                    signers,
                },
            },
            root_id: trust_root.root_id.clone(),
            issued_at: now - 1000,
            expires_at: now + 120_000,
            signature: [0; 64],
        };
        distribution.signature = root_key
            .sign(&distribution.signing_bytes().unwrap())
            .to_bytes();
        let trust = activate_learning_trust(&trust_root, distribution, None, now).unwrap();
        let mut writer = create_writer(&root, trust.clone());
        let candidates = vec![id("action"), id("abstain")];
        let decision = ProductionDecisionV2 {
            record_id: id("decision"),
            episode_id: id("episode"),
            run_snapshot_digest: digest("run"),
            objective_digest: digest("fixture-objective"),
            policy_digest: digest("policy"),
            candidate_ids: candidates.clone(),
            selected_candidate_id: id("action"),
            selected_propensity: ProbabilityQ32::ONE,
            completeness: CandidateSetCompletenessReceiptV1 {
                set_id: id("set"),
                state_digest: digest("state"),
                generator_id: principals[0].principal_id.clone(),
                generator_code_digest: digest("code"),
                grammar_digest: digest("grammar"),
                hard_filter_digest: digest("filter"),
                truncation_digest: digest("truncate"),
                candidates_digest: candidate_ids_digest_v2(&candidates),
                candidate_count: 2,
                omitted_count_bound: 0,
                canonical_order_digest: candidate_order_digest_v2(&candidates),
                complete_for_generator: true,
            },
            support_digest: digest("decision-support"),
        };
        let evidence = sign(
            &writer,
            &keys[0],
            &principals[0],
            role(0),
            &decision_signing_payload_v2(&decision).unwrap(),
            now,
        );
        let decision_ack = writer
            .append_decision(Digest32::ZERO, decision, &evidence, now)
            .unwrap();
        let outcome = AuthenticatedOutcomeV1 {
            record_id: id("outcome"),
            outcome_id: id("observed-outcome"),
            episode_id: id("episode"),
            observer: principals[1].clone(),
            observed_at: Some(now),
            value: Some(FixedQ32::from_raw(100)),
            unit_profile_digest: digest("unit"),
            support_digest: digest("outcome-support"),
            watermark: OutcomeWatermarkV1 {
                latest_observable_at: now,
                expected_delay_profile_digest: digest("delay"),
                terminality: OutcomeTerminalityV1::Terminal,
                censoring_reason: None,
                correction_predecessor: None,
                finalized_at: Some(now),
            },
        };
        let evidence = sign(
            &writer,
            &keys[1],
            &principals[1],
            role(1),
            &outcome_signing_payload_v2(&outcome),
            now,
        );
        let outcome_ack = writer
            .append_outcome(decision_ack.chain_digest, outcome, &evidence, now)
            .unwrap();
        let plan = DatasetFreezePlanV2 {
            snapshot_id: id("dataset"),
            objective_digest: digest("fixture-objective"),
            inclusion_policy_digest: digest("cut"),
        };
        let evidence = sign(
            &writer,
            &keys[2],
            &principals[2],
            role(2),
            &dataset_freeze_signing_payload_v2(&writer.snapshot().unwrap(), &plan).unwrap(),
            now,
        );
        let dataset = writer.freeze_dataset(plan, &evidence, now).unwrap();
        let lineage = UnlearningLineageRequestV1 {
            record_id: id("unlearning-record"),
            lineage_id: id("unlearning-lineage"),
            source_record_id: id("outcome"),
            dataset_snapshot_id: dataset.snapshot.snapshot_id.clone(),
            dataset_digest: dataset.snapshot.dataset_digest,
            artifact_id: id("source"),
            reason_digest: digest("withdrawal-reason"),
        };
        let evidence = sign(
            &writer,
            &keys[3],
            &principals[3],
            role(3),
            &unlearning_signing_payload_v1(&lineage),
            now,
        );
        let key = SigningKey::from_bytes(&[9; 32]);
        let withdrawals = DatasetWithdrawalRegistry::new_scoped(DatasetWithdrawalScopeV1 {
            authority_domain_id: id("fixture-dataset-owner"),
            registry_id: id("withdrawals"),
            scope_id: id("scope"),
        });
        let scope = withdrawals.scope_digest().unwrap();
        let signer = TrustedArtifactSignerV1 {
            signer_id: id("artifact-authority"),
            verifying_key: key.verifying_key().to_bytes(),
            minimum_authority_epoch: 1,
            maximum_authority_epoch: 1,
            valid_from: now - 1000,
            expires_at: now + 120_000,
            revoked_at: None,
        };
        let mut lease = SignedArtifactWriterLeaseV1 {
            lease_id: id("original-writer"),
            producer_id: id("producer"),
            registry_id: id("artifacts"),
            withdrawal_scope_digest: scope,
            signer_id: signer.signer_id.clone(),
            signing_key_digest: Digest32::of_bytes(key.verifying_key().as_bytes()),
            authority_epoch: 1,
            lease_generation: 1,
            issued_at: now - 1000,
            expires_at: now + 120_000,
            signature: [0; 64],
        };
        lease.signature = key.sign(&lease.signing_bytes()).to_bytes();
        let config = LearningArtifactOwnerServiceConfigV1 {
            root: root.join("artifacts"),
            trust: ArtifactOwnerTrustV1 {
                registry_id: id("artifacts"),
                withdrawal_scope_digest: scope,
                minimum_registry_generation: Generation::new(1).unwrap(),
                genesis_predecessor_head_digest: Digest32::ZERO,
                minimum_authority_epoch: 1,
                writer_signers: vec![signer.clone()],
                head_signers: vec![signer],
            },
            writer_lease: lease,
            required_current_head: None,
            withdrawal_registry: withdrawals,
            storage_binding: digest("artifact-binding"),
            now,
        };
        fs::create_dir(&config.root).unwrap();
        fs::set_permissions(&config.root, fs::Permissions::from_mode(0o700)).unwrap();
        let mut owner = LearningArtifactOwnerService::open(config.clone()).unwrap();
        for (name, parent, generation) in [("source", None, 1), ("child", Some("source"), 2)] {
            let mut manifest = model(name, dataset.snapshot.dataset_digest, now);
            manifest.generation = Generation::new(generation).unwrap();
            manifest.predecessor_ids = parent.map(id).into_iter().collect();
            let request = publication(&owner, &key, name, manifest, &[], now);
            owner.publish(request).unwrap();
        }
        let intent = HostLearningWithdrawalIntentV1 {
            ledger_predecessor: outcome_ack.chain_digest,
            lineage,
            dataset,
            evidence,
            artifact_predecessor: owner.registry().head_digest(),
        };
        Self {
            root,
            writer,
            owner,
            intent,
            config,
            trust,
            key,
            now,
        }
    }
    pub fn reader(&self) -> ReadOnlyArtifactCurrentOwnerV1 {
        ReadOnlyArtifactCurrentOwnerV1::open(
            &self.config.root,
            self.config.trust.clone(),
            self.owner.withdrawal_registry().clone(),
            self.now,
        )
        .unwrap()
    }
    pub fn consumers(&self) -> Vec<RevalidatingCandidate> {
        let snapshot = self.root.join("historical-snapshot");
        let receipt = write_registry_snapshot(
            CreateOnlyArtifactFile::create(&snapshot).unwrap(),
            self.owner.registry(),
            digest("historical-pin"),
        )
        .unwrap();
        ["source", "child"]
            .map(|name| {
                let path = self.root.join(format!("historical-{name}"));
                write_candidate_payload(
                    CreateOnlyArtifactFile::create(&path).unwrap(),
                    self.owner.registry(),
                    &id(name),
                    b"payload",
                )
                .unwrap();
                RevalidatingCandidate::new(
                    load_pinned_candidate(
                        File::open(&snapshot).unwrap(),
                        File::open(path).unwrap(),
                        PinnedCandidateSpec {
                            registry_receipt: receipt,
                            manifest: self.owner.registry().manifest(&id(name)).unwrap().clone(),
                        },
                    )
                    .unwrap(),
                )
            })
            .into_iter()
            .collect()
    }
}

fn role(index: usize) -> LearningEvidenceRoleV1 {
    match index {
        0 => LearningEvidenceRoleV1::Generator,
        1 => LearningEvidenceRoleV1::Observer,
        2 => LearningEvidenceRoleV1::Evaluator,
        _ => LearningEvidenceRoleV1::UnlearningAuthority,
    }
}
fn sign(
    writer: &LedgerWriter,
    key: &SigningKey,
    principal: &AuthenticatedPrincipalV1,
    role: LearningEvidenceRoleV1,
    payload: &[u8],
    now: u64,
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("evidence-{}", principal.principal_id)),
        principal_id: principal.principal_id.clone(),
        role,
        trust_digest: writer.verifier().trust_digest(),
        scope_digest: principal.scope_digest,
        objective_digest: writer.verifier().objective_digest(),
        authority_epoch: 1,
        issued_at: now,
        expires_at: now + 60_000,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    evidence
}
fn file(root: &Path, name: &str) -> File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .open(root.join(name))
        .unwrap()
}
fn create_writer(root: &Path, trust: ActivatedLearningTrustV1) -> LedgerWriter {
    for name in ["ledger", "witness"] {
        File::create(root.join(name)).unwrap();
    }
    let ledger = DurableLedger::create(file(root, "ledger"), digest("ledger-binding"), 64).unwrap();
    let witness =
        LedgerWitnessStore::create(file(root, "witness"), digest("ledger-binding")).unwrap();
    let directory = File::open(root).unwrap();
    LedgerWriter::from_durable(ledger, witness, trust, &directory, &directory).unwrap()
}
pub(super) fn reopen_writer(root: &Path, trust: ActivatedLearningTrustV1) -> LedgerWriter {
    let witness =
        LedgerWitnessStore::recover(file(root, "witness"), digest("ledger-binding")).unwrap();
    let anchor = witness.frontier().unwrap().anchor;
    let ledger = DurableLedger::recover(
        file(root, "ledger"),
        digest("ledger-binding"),
        64,
        LedgerRecovery::Acknowledged(anchor),
    )
    .unwrap();
    let directory = File::open(root).unwrap();
    LedgerWriter::from_durable(ledger, witness, trust, &directory, &directory).unwrap()
}
pub(super) fn model(name: &str, dataset: Digest32, now: u64) -> LearningArtifactManifestV2 {
    LearningArtifactManifestV2 {
        artifact_id: id(name),
        kind: ArtifactKind::Model,
        generation: Generation::new(1).unwrap(),
        provenance_mode: ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![dataset],
        lineage_digests: vec![digest("lineage")],
        predecessor_ids: vec![],
        rollback_predecessor: None,
        bytes_digest: digest("payload"),
        encoded_size_bytes: 7,
        training_code_digest: digest("code"),
        runtime_tuple_digest: digest("runtime"),
        device_profile_digest: digest("device"),
        objective_class_digest: digest("fixture-objective"),
        compatibility_digest: digest("compatibility"),
        schema_profile_digest: digest("schema"),
        normalization_digest: digest("normalize"),
        producer_id: id("producer"),
        created_at: now,
        expires_at: now + 120_000,
    }
}
pub(super) fn publication(
    owner: &LearningArtifactOwnerService,
    key: &SigningKey,
    operation: &str,
    manifest: LearningArtifactManifestV2,
    changes: &[ArtifactEvent],
    now: u64,
) -> LearningArtifactPublishRequestV1 {
    let admission = admit_manifest_at_withdrawal_head_v3(
        owner.withdrawal_registry(),
        owner.withdrawal_registry().head_digest(),
        manifest,
        now,
    )
    .unwrap();
    let preview = owner
        .preview_publication_with_state_changes(id(operation), admission.clone(), changes, now)
        .unwrap();
    let mut signed = SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: owner.withdrawal_registry().scope_digest().unwrap(),
        binding: digest("artifact-binding"),
        witness: RegistryHeadWitnessV1 {
            registry_id: id("artifacts"),
            generation: preview.generation,
            head_digest: preview.head_digest,
            predecessor_head_digest: preview.predecessor,
            authority_epoch: 1,
            signer_id: id("artifact-authority"),
            signing_key_digest: Digest32::of_bytes(key.verifying_key().as_bytes()),
            issued_at: now,
            expires_at: now + 120_000,
        },
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    LearningArtifactPublishRequestV1 {
        operation_id: id(operation),
        admission,
        payload: b"payload".to_vec(),
        signed_current_head: signed,
        expected_registry_predecessor_head: preview.predecessor,
        now,
    }
}
