use codex_hepta_agentd::AgentdSharedReplayHostV1;
use codex_hepta_agentd::SharedTerminalCandidateV1;
use codex_hepta_bellman_operator::TerminalCellProfileV1;
use codex_hepta_bellman_operator::encode_tabular_payload_v1;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_learning_artifacts as artifacts;
use codex_hepta_learning_ledger::*;
use codex_hepta_memory::*;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::fs::File;
use std::sync::Arc;

#[path = "support/terminal_cell_owner.rs"]
mod support;
use support::Fixture;
use support::decision;
use support::digest;
use support::id;
use support::outcome;
use support::sign;

struct SharedCase {
    host: AgentdSharedReplayHostV1,
    ledger: LedgerWriter,
    candidate: SharedTerminalCandidateV1,
    payload: Vec<u8>,
    _ledger_files: Fixture,
    _memory_files: tempfile::TempDir,
}

async fn shared_case() -> SharedCase {
    let memory_files = tempfile::tempdir().unwrap();
    let fleet = HeptaFleetRoot::parse(memory_files.path().to_path_buf())
        .unwrap()
        .layout();
    let owner_id = AgentId::parse("00000000-0000-4000-8000-000000000011").unwrap();
    let consumer_id = AgentId::parse("00000000-0000-4000-8000-000000000012").unwrap();
    let source = Arc::new(CognitiveStore::open(&fleet.agent(&owner_id)).await.unwrap());
    let access = CognitiveAccess::agent_private(owner_id);
    let citation = source
        .append_source(
            &access,
            &SourceDraft {
                scope: CognitiveScope::AgentPrivate,
                kind: LedgerSourceKind::PersistedToolResult,
                event_key: "terminal.current.support".into(),
                content: b"observed terminal action results".to_vec(),
                observed_at_unix_seconds: 100,
            },
        )
        .await
        .unwrap();
    let memory = source
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "terminal.current.support".into(),
                revision: MemoryRevisionDraft {
                    scope: CognitiveScope::AgentPrivate,
                    content: "observed terminal action results".into(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: 100,
                    valid_to_unix_seconds: None,
                    citations: vec![citation],
                },
            },
        )
        .await
        .unwrap();
    let consumer = FederationConsumerAccess::new(
        consumer_id.clone(),
        Sha256Digest::for_bytes(b"terminal.current.workspace"),
    );
    let wall_now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs() as i64;
    let replay = source
        .grant_shared_experience(
            &access,
            &SharedExperienceGrantV1 {
                memory_id: memory.id.memory_id,
                memory_revision: memory.id.revision,
                consumer: consumer.clone(),
                purpose: SharedExperiencePurposeV1::Replay {
                    parameter_scope: "domain.terminal".into(),
                    artifact_consumer: consumer_id.clone(),
                },
                expires_at_unix_seconds: wall_now + 3600,
            },
            0,
        )
        .await
        .unwrap();
    let source_digest = replay.source_support_digest().as_str().parse().unwrap();
    let ledger_files = Fixture::new();
    let mut ledger = ledger_files.writer();
    for (selected, reward) in [("read", FixedQ32::ONE.raw()), ("abstain", 0)] {
        let mut request = decision();
        request.record_id = id(&format!("{selected}.decision"));
        request.episode_id = id(&format!("{selected}.episode"));
        request.selected_candidate_id = id(selected);
        request.support_digest = source_digest;
        let evidence = sign(
            ledger.verifier(),
            "generator",
            LearningEvidenceRoleV1::Generator,
            &decision_signing_payload_v2(&request).unwrap(),
        );
        let head = ledger.witness_frontier().unwrap().anchor.chain_digest;
        let receipt = ledger
            .append_decision(head, request, &evidence, 50)
            .unwrap();
        let mut observed = outcome(
            &format!("{selected}.result-record"),
            &format!("{selected}.result"),
            None,
            reward,
        );
        observed.episode_id = id(&format!("{selected}.episode"));
        let evidence = sign(
            ledger.verifier(),
            "observer",
            LearningEvidenceRoleV1::Observer,
            &outcome_signing_payload_v2(&observed),
        );
        ledger
            .append_outcome(receipt.chain_digest, observed, &evidence, 50)
            .unwrap();
    }
    let plan = DatasetFreezePlanV2 {
        snapshot_id: id("terminal.current.dataset"),
        objective_digest: digest("objective"),
        inclusion_policy_digest: digest("all-active-owner-episodes"),
    };
    let evidence = sign(
        ledger.verifier(),
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &dataset_freeze_signing_payload_v2(&ledger.snapshot().unwrap(), &plan).unwrap(),
    );
    let dataset = ledger.freeze_dataset(plan, &evidence, 50).unwrap();
    let host =
        AgentdSharedReplayHostV1::new(source, consumer, "domain.terminal".into(), consumer_id)
            .unwrap();
    let candidate = host
        .train(
            replay.policy_id(),
            &ledger,
            &dataset,
            TerminalCellProfileV1 {
                artifact_id: id("terminal.current.policy"),
                producer_id: id("terminal.owner"),
                generation: Generation::new(2).unwrap(),
                sensor_id: id("single-approved-state"),
                objective_digest: digest("objective"),
                run_snapshot_digest: digest("run-snapshot"),
                unit_profile_digest: digest("reward-units"),
                action_ids: vec![id("abstain"), id("read")],
                minimum_samples_per_action: 1,
            },
            50,
        )
        .await
        .unwrap();
    let payload = encode_tabular_payload_v1(candidate.artifact()).unwrap();
    SharedCase {
        host,
        ledger,
        candidate,
        payload,
        _ledger_files: ledger_files,
        _memory_files: memory_files,
    }
}

fn manifest(case: &SharedCase) -> artifacts::LearningArtifactManifestV2 {
    let artifact = case.candidate.artifact();
    artifacts::LearningArtifactManifestV2 {
        artifact_id: artifact.artifact_id.clone(),
        kind: artifacts::ArtifactKind::Policy,
        generation: artifact.generation,
        provenance_mode: artifacts::ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![artifact.dataset_digest],
        lineage_digests: vec![artifact.artifact_digest, artifact.sensor_core_digest],
        predecessor_ids: vec![],
        rollback_predecessor: None,
        bytes_digest: Digest32::of_bytes(&case.payload),
        encoded_size_bytes: case.payload.len() as u64,
        training_code_digest: digest("terminal.code"),
        runtime_tuple_digest: digest("terminal.runtime"),
        device_profile_digest: digest("terminal.device"),
        objective_class_digest: artifact.objective_digest,
        compatibility_digest: artifact.training_profile_digest,
        schema_profile_digest: digest("terminal.schema"),
        normalization_digest: digest("terminal.normalization"),
        producer_id: artifact.producer_id.clone(),
        created_at: 45,
        expires_at: 80,
    }
}

struct CurrentEvidence {
    verifier: artifacts::ArtifactOwnerVerifierV1,
    registry: artifacts::ArtifactRegistry,
    receipt: artifacts::RegistrySnapshotReceipt,
    head: artifacts::SignedCurrentArtifactHeadV1,
    admissions: Vec<artifacts::WithdrawalBoundArtifactAdmissionV3>,
    withdrawals: artifacts::DatasetWithdrawalRegistry,
    directory: tempfile::TempDir,
}

impl CurrentEvidence {
    fn new(manifests: Vec<artifacts::LearningArtifactManifestV2>) -> Self {
        Self::signed_by(manifests, /*seed*/ 70)
    }

    fn signed_by(manifests: Vec<artifacts::LearningArtifactManifestV2>, seed: u8) -> Self {
        let directory = tempfile::tempdir().unwrap();
        let key = SigningKey::from_bytes(&[seed; 32]);
        let scope = artifacts::DatasetWithdrawalScopeV1 {
            authority_domain_id: id("terminal.dataset.owner"),
            registry_id: id("terminal.withdrawals"),
            scope_id: id("terminal.scope"),
        };
        let scope_digest = scope.digest();
        let withdrawals = artifacts::DatasetWithdrawalRegistry::new_scoped(scope);
        let signer = artifacts::TrustedArtifactSignerV1 {
            signer_id: id("terminal.registry.signer"),
            verifying_key: key.verifying_key().to_bytes(),
            minimum_authority_epoch: 1,
            maximum_authority_epoch: 1,
            valid_from: 1,
            expires_at: 100,
            revoked_at: None,
        };
        let verifier = artifacts::ArtifactOwnerVerifierV1::new(artifacts::ArtifactOwnerTrustV1 {
            registry_id: id("terminal.registry"),
            withdrawal_scope_digest: scope_digest,
            minimum_registry_generation: Generation::new(1).unwrap(),
            genesis_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            writer_signers: vec![signer.clone()],
            head_signers: vec![signer],
        })
        .unwrap();
        let mut registry = artifacts::ArtifactRegistry::new();
        let mut admissions = vec![];
        for full in manifests {
            let admission = artifacts::admit_manifest_at_withdrawal_head_v3(
                &withdrawals,
                withdrawals.head_digest(),
                full,
                50,
            )
            .unwrap();
            let full = &admission.validated_manifest.manifest;
            registry
                .append(artifacts::ArtifactEvent::Register {
                    event_id: id(&format!("register.{}", full.artifact_id)),
                    manifest: artifacts::ArtifactManifest {
                        artifact_id: full.artifact_id.clone(),
                        kind: full.kind,
                        generation: full.generation,
                        predecessor_id: if full.predecessor_ids.len() == 1 {
                            full.predecessor_ids.first().cloned()
                        } else {
                            None
                        },
                        content_digest: full.bytes_digest,
                        objective_digest: full.objective_class_digest,
                        support_digest: admission.validated_manifest.manifest_digest,
                        producer_id: full.producer_id.clone(),
                        compatibility_digest: full.compatibility_digest,
                        encoded_size_bytes: full.encoded_size_bytes,
                    },
                })
                .unwrap();
            admissions.push(admission);
        }
        let receipt = artifacts::write_registry_snapshot(
            artifacts::CreateOnlyArtifactFile::create(directory.path().join("snapshot")).unwrap(),
            &registry,
            digest("terminal.registry.binding"),
        )
        .unwrap();
        let mut head = artifacts::SignedCurrentArtifactHeadV1 {
            withdrawal_scope_digest: scope_digest,
            binding: receipt.binding,
            witness: artifacts::RegistryHeadWitnessV1 {
                registry_id: id("terminal.registry"),
                generation: Generation::new(1).unwrap(),
                head_digest: receipt.head_digest,
                predecessor_head_digest: Digest32::ZERO,
                authority_epoch: 1,
                signer_id: id("terminal.registry.signer"),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                issued_at: 50,
                expires_at: 90,
            },
            signature: [0; 64],
        };
        head.signature = key.sign(&head.signing_bytes()).to_bytes();
        Self {
            verifier,
            registry,
            receipt,
            head,
            admissions,
            withdrawals,
            directory,
        }
    }

    fn requirement(now: u64) -> artifacts::RegistryHeadRequirementV1 {
        artifacts::RegistryHeadRequirementV1 {
            registry_id: id("terminal.registry"),
            minimum_generation: Generation::new(1).unwrap(),
            expected_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            now,
        }
    }

    fn compatibility_view(&self) -> artifacts::VerifiedCurrentRegistryViewV1 {
        self.verifier
            .verify_current_registry_view(
                File::open(self.directory.path().join("snapshot")).unwrap(),
                self.receipt,
                &self.head,
                &Self::requirement(50),
            )
            .unwrap()
    }

    fn full_view(&self, now: u64) -> artifacts::VerifiedCurrentRegistryViewV1 {
        self.verifier
            .verify_current_registry_view_with_admission_closure(
                File::open(self.directory.path().join("snapshot")).unwrap(),
                self.receipt,
                &self.head,
                &Self::requirement(now),
                self.admissions.clone(),
                &self.withdrawals,
            )
            .unwrap()
    }

    fn withdraw(&mut self, dataset: Digest32) {
        self.withdrawals
            .append(artifacts::DatasetWithdrawalNoticeV1 {
                notice_id: id("terminal.withdrawal"),
                dataset_digest: dataset,
                source_tombstone_digest: digest("terminal.tombstone"),
                authority_id: id("terminal.dataset.owner"),
                credential_chain_digest: digest("terminal.withdrawal.credential"),
                signing_key_digest: digest("terminal.withdrawal.key"),
                authority_epoch: 1,
                issued_at: 51,
            })
            .unwrap();
    }
}

#[tokio::test]
async fn authenticated_v2_policy_loads_and_predicts_without_legacy_downgrade() {
    let case = shared_case().await;
    let evidence = CurrentEvidence::new(vec![manifest(&case)]);
    assert!(
        case.host
            .load(
                case.candidate.clone(),
                &case.ledger,
                &evidence.registry,
                &case.payload,
                50
            )
            .await
            .is_err()
    );
    assert!(
        case.host
            .load_from_current(
                case.candidate.clone(),
                &case.ledger,
                &evidence.compatibility_view(),
                &case.payload,
                50
            )
            .await
            .is_err()
    );
    let model = case
        .host
        .load_from_current(
            case.candidate.clone(),
            &case.ledger,
            &evidence.full_view(50),
            &case.payload,
            50,
        )
        .await
        .unwrap();
    // A V2-loaded model must retain its stronger revalidation requirement even
    // if a caller replaces the owner projection with a plausible legacy entry.
    let mut legacy_manifest = evidence
        .registry
        .manifest(&case.candidate.artifact().artifact_id)
        .unwrap()
        .clone();
    legacy_manifest.support_digest = case.candidate.artifact().dataset_digest;
    let mut legacy = artifacts::ArtifactRegistry::new();
    legacy
        .append(artifacts::ArtifactEvent::Register {
            event_id: id("legacy.replacement"),
            manifest: legacy_manifest,
        })
        .unwrap();
    let legacy_model = case
        .host
        .load(
            case.candidate.clone(),
            &case.ledger,
            &legacy,
            &case.payload,
            50,
        )
        .await
        .unwrap();
    assert!(
        case.host
            .predict_from_current(
                &legacy_model,
                &case.ledger,
                &evidence.full_view(50),
                &id("single-approved-state"),
                &id("read"),
                50
            )
            .await
            .is_err(),
        "legacy models require an explicit current-registry load"
    );
    assert!(
        case.host
            .predict(
                &model,
                &case.ledger,
                &legacy,
                &id("single-approved-state"),
                &id("read"),
                50
            )
            .await
            .is_err()
    );
    let prediction = case
        .host
        .predict_from_current(
            &model,
            &case.ledger,
            &evidence.full_view(50),
            &id("single-approved-state"),
            &id("read"),
            50,
        )
        .await
        .unwrap();
    assert_eq!(prediction.value, FixedQ32::ONE);
    assert_eq!(prediction.authority, AuthorityPosture::DENY_ALL);
    let mut payload = case.payload.clone();
    payload[0] ^= 1;
    assert!(
        case.host
            .load_from_current(
                case.candidate.clone(),
                &case.ledger,
                &evidence.full_view(50),
                &payload,
                50
            )
            .await
            .is_err()
    );
}

#[tokio::test]
async fn authenticated_v2_policy_requires_each_exact_terminal_binding() {
    let case = shared_case().await;
    let correct = manifest(&case);
    let mutations: [(&str, fn(&mut artifacts::LearningArtifactManifestV2)); 10] = [
        ("identity", |value| value.artifact_id = id("other.policy")),
        ("kind", |value| value.kind = artifacts::ArtifactKind::Model),
        ("generation", |value| {
            value.generation = Generation::new(3).unwrap()
        }),
        ("dataset", |value| {
            value.source_dataset_digests = vec![digest("other.dataset")]
        }),
        ("sensor lineage", |value| {
            value.lineage_digests = vec![digest("other.sensor")]
        }),
        ("objective", |value| {
            value.objective_class_digest = digest("other.objective")
        }),
        ("training profile", |value| {
            value.compatibility_digest = digest("other.profile")
        }),
        ("producer", |value| value.producer_id = id("other.producer")),
        ("bytes", |value| {
            value.bytes_digest = digest("other.payload")
        }),
        ("length", |value| value.encoded_size_bytes += 1),
    ];
    for (label, mutate) in mutations {
        let mut changed = correct.clone();
        mutate(&mut changed);
        let evidence = CurrentEvidence::new(vec![changed]);
        assert!(
            case.host
                .load_from_current(
                    case.candidate.clone(),
                    &case.ledger,
                    &evidence.full_view(50),
                    &case.payload,
                    50
                )
                .await
                .is_err(),
            "mismatched {label} must not authorize loading"
        );
    }
}

#[tokio::test]
async fn loaded_v2_policy_checks_time_again_at_prediction() {
    let case = shared_case().await;
    let mut full = manifest(&case);
    full.expires_at = 55;
    let evidence = CurrentEvidence::new(vec![full]);
    let current = evidence.full_view(50);
    let model = case
        .host
        .load_from_current(
            case.candidate.clone(),
            &case.ledger,
            &current,
            &case.payload,
            50,
        )
        .await
        .unwrap();
    assert!(
        case.host
            .predict_from_current(
                &model,
                &case.ledger,
                &current,
                &id("single-approved-state"),
                &id("read"),
                56
            )
            .await
            .is_err()
    );
}

#[tokio::test]
async fn loaded_v2_policy_rejects_withdrawn_additional_dataset_and_expired_parent() {
    let case = shared_case().await;
    let mut full = manifest(&case);
    let extra_dataset = digest("additional.source.dataset");
    full.source_dataset_digests.push(extra_dataset);
    let mut evidence = CurrentEvidence::new(vec![full.clone()]);
    let model = case
        .host
        .load_from_current(
            case.candidate.clone(),
            &case.ledger,
            &evidence.full_view(50),
            &case.payload,
            50,
        )
        .await
        .unwrap();
    evidence.withdraw(extra_dataset);
    assert!(
        case.host
            .predict_from_current(
                &model,
                &case.ledger,
                &evidence.full_view(51),
                &id("single-approved-state"),
                &id("read"),
                51
            )
            .await
            .is_err()
    );

    let mut parent = full.clone();
    parent.artifact_id = id("terminal.current.parent");
    parent.generation = Generation::new(1).unwrap();
    parent.expires_at = 55;
    full.predecessor_ids = vec![parent.artifact_id.clone()];
    let evidence = CurrentEvidence::new(vec![parent, full]);
    let model = case
        .host
        .load_from_current(
            case.candidate.clone(),
            &case.ledger,
            &evidence.full_view(50),
            &case.payload,
            50,
        )
        .await
        .unwrap();
    assert!(
        case.host
            .predict_from_current(
                &model,
                &case.ledger,
                &evidence.full_view(56),
                &id("single-approved-state"),
                &id("read"),
                56
            )
            .await
            .is_err()
    );
}

#[tokio::test]
async fn cached_current_cannot_hide_parent_expiry_or_revive_failed_model() {
    let case = shared_case().await;
    let mut full = manifest(&case);
    let mut parent = full.clone();
    parent.artifact_id = id("terminal.current.parent");
    parent.generation = Generation::new(1).unwrap();
    parent.expires_at = 55;
    full.predecessor_ids = vec![parent.artifact_id.clone()];
    let evidence = CurrentEvidence::new(vec![parent, full]);
    let cached = evidence.full_view(50);
    let model = case
        .host
        .load_from_current(
            case.candidate.clone(),
            &case.ledger,
            &cached,
            &case.payload,
            50,
        )
        .await
        .unwrap();
    assert!(
        case.host
            .load_from_current(
                case.candidate.clone(),
                &case.ledger,
                &cached,
                &case.payload,
                56
            )
            .await
            .is_err(),
        "a cached view cannot admit a model after its parent expires"
    );
    assert!(
        case.host
            .predict_from_current(
                &model,
                &case.ledger,
                &cached,
                &id("single-approved-state"),
                &id("read"),
                56
            )
            .await
            .is_err(),
        "a child whose own expiry is still valid cannot hide an expired parent"
    );
    assert!(
        case.host
            .predict_from_current(
                &model,
                &case.ledger,
                &evidence.full_view(50),
                &id("single-approved-state"),
                &id("read"),
                50
            )
            .await
            .is_err(),
        "an earlier valid view cannot revive a failed refresh"
    );
}

#[tokio::test]
async fn equally_signed_payload_from_another_owner_closes_current_model() {
    let case = shared_case().await;
    let full = manifest(&case);
    let evidence = CurrentEvidence::new(vec![full.clone()]);
    let accepted = evidence.full_view(50);
    let model = case
        .host
        .load_from_current(
            case.candidate.clone(),
            &case.ledger,
            &accepted,
            &case.payload,
            50,
        )
        .await
        .unwrap();
    let foreign = CurrentEvidence::signed_by(vec![full], /*seed*/ 71);
    let foreign_view = foreign.full_view(50);
    assert!(foreign_view.extends(accepted.receipt()));
    assert_ne!(foreign_view.trust_digest(), accepted.trust_digest());
    assert!(
        case.host
            .predict_from_current(
                &model,
                &case.ledger,
                &foreign_view,
                &id("single-approved-state"),
                &id("read"),
                50
            )
            .await
            .is_err(),
        "identical bytes and history do not replace the pinned owner trust"
    );
    assert!(
        case.host
            .predict_from_current(
                &model,
                &case.ledger,
                &accepted,
                &id("single-approved-state"),
                &id("read"),
                50
            )
            .await
            .is_err()
    );
}

#[tokio::test]
async fn correctly_signed_longer_fork_cannot_replace_current_history() {
    let case = shared_case().await;
    let full = manifest(&case);
    let evidence = CurrentEvidence::new(vec![full.clone()]);
    let accepted = evidence.full_view(50);
    let model = case
        .host
        .load_from_current(
            case.candidate.clone(),
            &case.ledger,
            &accepted,
            &case.payload,
            50,
        )
        .await
        .unwrap();
    let mut prefix = full.clone();
    prefix.artifact_id = id("terminal.fork.prefix");
    prefix.generation = Generation::new(1).unwrap();
    let fork = CurrentEvidence::new(vec![prefix, full]);
    let fork_view = fork.full_view(51);
    assert!(fork_view.receipt().records > accepted.receipt().records);
    assert_eq!(fork_view.trust_digest(), accepted.trust_digest());
    assert!(!fork_view.extends(accepted.receipt()));
    assert!(
        case.host
            .predict_from_current(
                &model,
                &case.ledger,
                &fork_view,
                &id("single-approved-state"),
                &id("read"),
                51
            )
            .await
            .is_err()
    );
    assert!(
        case.host
            .predict_from_current(
                &model,
                &case.ledger,
                &evidence.full_view(51),
                &id("single-approved-state"),
                &id("read"),
                51
            )
            .await
            .is_err()
    );
}

#[tokio::test]
async fn genuine_current_extension_advances_frontier_and_rejects_rollback() {
    let case = shared_case().await;
    let full = manifest(&case);
    let evidence = CurrentEvidence::new(vec![full.clone()]);
    let accepted = evidence.full_view(50);
    let model = case
        .host
        .load_from_current(
            case.candidate.clone(),
            &case.ledger,
            &accepted,
            &case.payload,
            50,
        )
        .await
        .unwrap();
    let mut next = full.clone();
    next.artifact_id = id("terminal.current.extension");
    next.generation = Generation::new(3).unwrap();
    let extension = CurrentEvidence::new(vec![full, next]);
    let extended = extension.full_view(51);
    assert!(extended.extends(accepted.receipt()));
    case.host
        .predict_from_current(
            &model,
            &case.ledger,
            &extended,
            &id("single-approved-state"),
            &id("read"),
            51,
        )
        .await
        .unwrap();
    assert!(
        case.host
            .predict_from_current(
                &model,
                &case.ledger,
                &evidence.full_view(52),
                &id("single-approved-state"),
                &id("read"),
                52
            )
            .await
            .is_err(),
        "a successfully advanced model must not accept the earlier registry"
    );
    assert!(
        case.host
            .predict_from_current(
                &model,
                &case.ledger,
                &extension.full_view(52),
                &id("single-approved-state"),
                &id("read"),
                52
            )
            .await
            .is_err(),
        "the newer view cannot revive a model after rollback rejection"
    );
}
