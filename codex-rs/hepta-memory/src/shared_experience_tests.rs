use super::*;
use crate::CognitiveScope;
use crate::MemoryDraft;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::memory_revision;
use crate::cognitive_test_support::source;
use crate::cognitive_test_support::workspace;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_cognitive_types::shared_experience::SharedExperienceRevocationCompletenessV2;
use codex_hepta_cognitive_types::shared_experience::SharedExperienceUseDispositionV2;
use codex_hepta_cognitive_types::shared_experience::SharedExperienceUseGrantV2;

#[tokio::test]
async fn independent_agents_share_only_declared_use_and_current_evidence() {
    let temp = tempfile::tempdir().unwrap();
    let owner_id = agent_id(1);
    let consumer_id = agent_id(2);
    let owner_layout = layout(&temp, &owner_id);
    let store = CognitiveStore::open(&owner_layout).await.unwrap();
    let clean = CognitiveStore::open(&layout(&temp, &consumer_id))
        .await
        .unwrap();
    let access = CognitiveAccess::agent_private(owner_id.clone());
    let citation = store
        .append_source(
            &access,
            &source(
                CognitiveScope::AgentPrivate,
                "source.shared",
                "observed input -> verified result",
            ),
        )
        .await
        .unwrap();
    let memory = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "shared.experience".into(),
                revision: memory_revision(
                    CognitiveScope::AgentPrivate,
                    "use current API signature before editing",
                    citation.clone(),
                ),
            },
        )
        .await
        .unwrap();
    let consumer =
        FederationConsumerAccess::new(consumer_id.clone(), workspace("isolated.clean.workspace"));
    assert!(
        clean
            .latest_memory(
                &CognitiveAccess::agent_private(consumer_id.clone()),
                &memory.id.memory_id
            )
            .await
            .is_err()
    );
    let request = SharedExperienceGrantV1 {
        memory_id: memory.id.memory_id.clone(),
        memory_revision: 1,
        consumer: consumer.clone(),
        purpose: SharedExperiencePurposeV1::Recall,
        expires_at_unix_seconds: now().unwrap() + 60,
    };
    let recall = store
        .grant_shared_experience(&access, &request, 0)
        .await
        .unwrap();
    assert_eq!(
        store
            .grant_shared_experience(&access, &request, 0)
            .await
            .unwrap(),
        recall,
        "lost acknowledgement is an exact replay"
    );
    let mut conflicting = request.clone();
    conflicting.expires_at_unix_seconds += 1;
    assert!(
        store
            .grant_shared_experience(&access, &conflicting, 0)
            .await
            .is_err()
    );
    let replay_purpose = SharedExperiencePurposeV1::Replay {
        parameter_scope: "domain.code-head".into(),
        artifact_consumer: consumer_id.clone(),
    };
    assert!(
        store
            .read_shared_experience(&consumer, recall.policy_id(), &replay_purpose)
            .await
            .is_err()
    );
    assert!(
        store
            .read_shared_experience(
                &FederationConsumerAccess::new(consumer_id.clone(), workspace("other.workspace")),
                recall.policy_id(),
                &SharedExperiencePurposeV1::Recall
            )
            .await
            .is_err()
    );
    let mut training = request.clone();
    training.purpose = replay_purpose.clone();
    let replay = store
        .grant_shared_experience(&access, &training, 0)
        .await
        .unwrap();
    assert_eq!(
        store
            .read_shared_experience(&consumer, replay.policy_id(), &replay_purpose)
            .await
            .unwrap()
            .memory(),
        &memory
    );
    let other_target = SharedExperiencePurposeV1::Replay {
        parameter_scope: "global.base".into(),
        artifact_consumer: consumer_id.clone(),
    };
    assert!(
        store
            .read_shared_experience(&consumer, replay.policy_id(), &other_target)
            .await
            .is_err()
    );
    let other_recipient = SharedExperiencePurposeV1::Replay {
        parameter_scope: "domain.code-head".into(),
        artifact_consumer: agent_id(3),
    };
    assert!(
        store
            .read_shared_experience(&consumer, replay.policy_id(), &other_recipient)
            .await
            .is_err()
    );
    assert!(
        store
            .grant_shared_experience(
                &CognitiveAccess::agent_private(consumer_id.clone()),
                &training,
                0
            )
            .await
            .is_err()
    );
    // Reopening source does not renew permission or install private context.
    store.pool.close().await;
    drop(store);
    let store = CognitiveStore::open(&owner_layout).await.unwrap();
    store.revalidate_shared_experience(&replay).await.unwrap();
    store
        .revoke_shared_experience(&access, &replay)
        .await
        .unwrap();
    assert!(store.revalidate_shared_experience(&replay).await.is_err());
    store
        .revoke_shared_experience(&access, &replay)
        .await
        .unwrap();
    assert!(
        store
            .grant_shared_experience(&access, &training, 0)
            .await
            .is_err(),
        "replay cannot undo revocation"
    );
    store.revalidate_shared_experience(&recall).await.unwrap();
    store
        .correct_memory(
            &access,
            &memory.id.memory_id,
            1,
            &memory_revision(
                CognitiveScope::AgentPrivate,
                "corrected source applicability",
                citation,
            ),
        )
        .await
        .unwrap();
    assert!(store.revalidate_shared_experience(&recall).await.is_err());
    assert!(
        clean
            .latest_memory(
                &CognitiveAccess::agent_private(consumer_id),
                &memory.id.memory_id
            )
            .await
            .is_err()
    );
}

#[tokio::test]
async fn migration_rebuilds_exact_schema_and_source_withdrawal_never_reopens_use() {
    let temp = tempfile::tempdir().unwrap();
    let owner = agent_id(4);
    let path = layout(&temp, &owner);
    let store = CognitiveStore::open(&path).await.unwrap();
    let access = CognitiveAccess::agent_private(owner);
    let citation = store
        .append_source(
            &access,
            &source(
                CognitiveScope::AgentPrivate,
                "withdraw-source",
                "verified observation",
            ),
        )
        .await
        .unwrap();
    let memory = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "withdraw-memory".into(),
                revision: memory_revision(
                    CognitiveScope::AgentPrivate,
                    "shared evidence",
                    citation.clone(),
                ),
            },
        )
        .await
        .unwrap();
    let request = SharedExperienceGrantV1 {
        memory_id: memory.id.memory_id.clone(),
        memory_revision: 1,
        consumer: FederationConsumerAccess::new(agent_id(5), workspace("clean")),
        purpose: SharedExperiencePurposeV1::Recall,
        expires_at_unix_seconds: now().unwrap() + 60,
    };
    let receipt = store
        .grant_shared_experience(&access, &request, 0)
        .await
        .unwrap();
    let withdrawn = crate::ForgetMemoryDraft {
        scope: CognitiveScope::AgentPrivate,
        reason: "source withdrawn".into(),
        valid_from_unix_seconds: now().unwrap(),
        citations: vec![citation],
    };
    store
        .forget_memory(&access, &memory.id.memory_id, 1, &withdrawn)
        .await
        .unwrap();
    assert!(store.revalidate_shared_experience(&receipt).await.is_err());
    store.pool.close().await;
    drop(store);
    let reopened = CognitiveStore::open(&path).await.unwrap();
    assert!(
        reopened
            .revalidate_shared_experience(&receipt)
            .await
            .is_err()
    );
    assert!(
        reopened
            .grant_shared_experience(&access, &request, 1)
            .await
            .is_err()
    );
    // The grant history itself remains append-only, not a cache to clear.
    assert!(
        sqlx::query("DELETE FROM shared_experience_use_events")
            .execute(&reopened.pool)
            .await
            .is_err()
    );
}

#[tokio::test]
async fn last_active_revision_can_be_revoked_and_stays_revoked_after_restart() {
    let temp = tempfile::tempdir().unwrap();
    let owner_id = agent_id(7);
    let owner_layout = layout(&temp, &owner_id);
    let store = CognitiveStore::open(&owner_layout).await.unwrap();
    let access = CognitiveAccess::agent_private(owner_id);
    let citation = store
        .append_source(
            &access,
            &source(
                CognitiveScope::AgentPrivate,
                "capacity.source",
                "independently observed fact",
            ),
        )
        .await
        .unwrap();
    let memory = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "capacity.memory".into(),
                revision: memory_revision(
                    CognitiveScope::AgentPrivate,
                    "bounded shared evidence",
                    citation,
                ),
            },
        )
        .await
        .unwrap();
    let request = SharedExperienceGrantV1 {
        memory_id: memory.id.memory_id,
        memory_revision: 1,
        consumer: FederationConsumerAccess::new(agent_id(8), workspace("capacity.consumer")),
        purpose: SharedExperiencePurposeV1::Recall,
        expires_at_unix_seconds: now().unwrap() + 3600,
    };
    let initial = store
        .grant_shared_experience(&access, &request, 0)
        .await
        .unwrap();
    // Seed the equivalent immutable renewal history once. The boundary under
    // test still uses the real grant, read, revoke and reopen owner APIs.
    sqlx::query("WITH RECURSIVE revisions(n) AS (VALUES(2) UNION ALL SELECT n+1 FROM revisions WHERE n < ?) INSERT INTO shared_experience_use_events SELECT policy_id,n,revoked,memory_id,memory_revision,content_sha256,consumer_agent_id,consumer_workspace_sha256,purpose,parameter_scope,artifact_consumer_id,expires_at FROM shared_experience_use_events,revisions WHERE policy_id=? AND revision=1")
        .bind(MAX_POLICY_REVISIONS - 1).bind(initial.policy_id().as_str())
        .execute(&store.pool).await.unwrap();
    let receipt = store
        .grant_shared_experience(&access, &request, (MAX_POLICY_REVISIONS - 1) as u64)
        .await
        .unwrap();
    assert_eq!(receipt.policy_revision(), MAX_POLICY_REVISIONS as u64);
    store.revalidate_shared_experience(&receipt).await.unwrap();
    assert!(
        store
            .grant_shared_experience(&access, &request, receipt.policy_revision())
            .await
            .is_err()
    );
    // The reserved slot is enforced by SQLite too, not only by the Rust API.
    assert!(sqlx::query("INSERT INTO shared_experience_use_events SELECT policy_id,revision+1,0,memory_id,memory_revision,content_sha256,consumer_agent_id,consumer_workspace_sha256,purpose,parameter_scope,artifact_consumer_id,expires_at FROM shared_experience_use_events WHERE policy_id=? AND revision=?")
        .bind(receipt.policy_id().as_str()).bind(receipt.policy_revision() as i64)
        .execute(&store.pool).await.is_err());
    store
        .revoke_shared_experience(&access, &receipt)
        .await
        .unwrap();
    store
        .revoke_shared_experience(&access, &receipt)
        .await
        .unwrap();
    assert!(store.revalidate_shared_experience(&receipt).await.is_err());
    store.pool.close().await;
    drop(store);
    let reopened = CognitiveStore::open(&owner_layout).await.unwrap();
    assert!(
        reopened
            .revalidate_shared_experience(&receipt)
            .await
            .is_err()
    );
    reopened
        .revoke_shared_experience(&access, &receipt)
        .await
        .unwrap();
    assert!(
        reopened
            .grant_shared_experience(&access, &request, MAX_POLICY_REVISIONS as u64 + 1)
            .await
            .is_err()
    );
}

fn canonical_digest(value: &Sha256Digest) -> ContractDigestV1 {
    ContractDigestV1::parse(value.as_str()).expect("canonical digest")
}

fn canonical_id(value: &str) -> ContractIdV1 {
    ContractIdV1::new(value).expect("canonical id")
}

fn publication_for(
    source: &SharedExperienceUseV1,
    grants: Vec<SharedExperienceUseGrantV2>,
    contribution: &str,
) -> SharedExperiencePublicationV2 {
    let mut grants = grants;
    grants.sort_by(|left, right| left.grant_id.cmp(&right.grant_id));
    SharedExperiencePublicationV2 {
        publication_operation_id: canonical_id("operation:shared-publication"),
        contribution_id: canonical_id(contribution),
        source_owner_id: canonical_id(source.owner_id().as_str()),
        source_owner_epoch: 1,
        source_kind: SharedExperienceSourceKindV2::OwnerMemoryRevision,
        source_record_id: canonical_id(source.memory().id.memory_id.as_str()),
        source_revision: source.memory().id.revision,
        source_record_sha256: canonical_digest(&source.source_support_digest()),
        semantic_content_sha256: canonical_digest(&source.memory().content_sha256),
        source_scope_sha256: canonical_digest(&source_scope_digest(source)),
        environment_sha256: canonical_digest(&Sha256Digest::for_bytes(b"test-environment")),
        applicability_sha256: canonical_digest(&Sha256Digest::for_bytes(b"test-applicability")),
        publication_policy_sha256: canonical_digest(source.policy_id()),
        policy_generation: ContractGenerationV1::new(source.policy_revision()).expect("generation"),
        destination_scope_ids: std::collections::BTreeSet::from([destination_scope_id(
            source.consumer(),
        )
        .expect("destination scope")]),
        use_grants: grants,
        retention_lineage_sha256: canonical_digest(&Sha256Digest::for_bytes(b"retention")),
        correction_of_contribution_id: None,
        observed_at_unix_ms: u64::try_from(source.memory().valid_from_unix_seconds)
            .expect("observed time")
            .saturating_mul(1_000),
        expires_at_unix_ms: Some(
            u64::try_from(source.expires_at_unix_seconds())
                .expect("expiry")
                .saturating_mul(1_000),
        ),
    }
}

fn read_grant_for(source: &SharedExperienceUseV1) -> SharedExperienceUseGrantV2 {
    SharedExperienceUseGrantV2 {
        grant_id: canonical_id("grant:read"),
        use_class: SharedExperienceUseClassV2::RawEvidenceRead {
            consumer_id: canonical_id(source.consumer().agent_id().as_str()),
            consumer_workspace_sha256: canonical_digest(source.consumer().workspace_sha256()),
        },
        valid_from_unix_ms: u64::try_from(source.memory().valid_from_unix_seconds)
            .expect("valid from")
            .saturating_mul(1_000),
        expires_at_unix_ms: u64::try_from(source.expires_at_unix_seconds())
            .expect("expiry")
            .saturating_mul(1_000),
    }
}

fn replay_grants_for(source: &SharedExperienceUseV1) -> Vec<SharedExperienceUseGrantV2> {
    let SharedExperiencePurposeV1::Replay {
        parameter_scope,
        artifact_consumer,
    } = source.purpose()
    else {
        panic!("replay source")
    };
    let from = u64::try_from(source.memory().valid_from_unix_seconds)
        .expect("valid from")
        .saturating_mul(1_000);
    let expiry = u64::try_from(source.expires_at_unix_seconds())
        .expect("expiry")
        .saturating_mul(1_000);
    vec![
        SharedExperienceUseGrantV2 {
            grant_id: canonical_id("grant:training"),
            use_class: SharedExperienceUseClassV2::PurposeBoundTraining {
                trainer_id: canonical_id(source.consumer().agent_id().as_str()),
                purpose_id: canonical_id("purpose:replay"),
                parameter_scope_sha256: canonical_digest(&parameter_scope_digest(parameter_scope)),
                dataset_split_sha256: canonical_digest(&Sha256Digest::for_bytes(b"dataset-split")),
            },
            valid_from_unix_ms: from,
            expires_at_unix_ms: expiry,
        },
        SharedExperienceUseGrantV2 {
            grant_id: canonical_id("grant:artifact"),
            use_class: SharedExperienceUseClassV2::DerivedArtifactUse {
                artifact_id: canonical_id("artifact:candidate"),
                artifact_consumer_id: canonical_id(artifact_consumer.as_str()),
                artifact_lineage_sha256: canonical_digest(&Sha256Digest::for_bytes(
                    b"artifact-lineage",
                )),
            },
            valid_from_unix_ms: from,
            expires_at_unix_ms: expiry,
        },
    ]
}

#[tokio::test]
async fn canonical_v2_publication_use_and_revocation_bind_existing_owner_state() {
    let temp = tempfile::tempdir().expect("temp");
    let owner_id = agent_id(31);
    let consumer_id = agent_id(32);
    let store = CognitiveStore::open(&layout(&temp, &owner_id))
        .await
        .expect("store");
    let access = CognitiveAccess::agent_private(owner_id.clone());
    let citation = store
        .append_source(
            &access,
            &source(
                CognitiveScope::AgentPrivate,
                "shared.v2.source",
                "verified V2 source",
            ),
        )
        .await
        .expect("source");
    let memory = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "shared.v2.memory".into(),
                revision: memory_revision(
                    CognitiveScope::AgentPrivate,
                    "canonical shared experience V2",
                    citation,
                ),
            },
        )
        .await
        .expect("memory");
    let consumer = FederationConsumerAccess::new(
        consumer_id.clone(),
        workspace("shared.v2.consumer.workspace"),
    );
    let expiry = now().expect("now") + 60;

    let recall = store
        .grant_shared_experience(
            &access,
            &SharedExperienceGrantV1 {
                memory_id: memory.id.memory_id.clone(),
                memory_revision: memory.id.revision,
                consumer: consumer.clone(),
                purpose: SharedExperiencePurposeV1::Recall,
                expires_at_unix_seconds: expiry,
            },
            0,
        )
        .await
        .expect("recall grant");
    let recall_publication = publication_for(
        &recall,
        vec![read_grant_for(&recall)],
        "contribution:recall-v2",
    );
    let recall_binding = store
        .bind_shared_experience_publication_v2(&recall, recall_publication)
        .expect("publication binding");
    // One legitimate grant must not launder additional consumers or scopes.
    let mut widened = recall_binding.publication.clone();
    let mut extra = widened.use_grants[0].clone();
    extra.grant_id = canonical_id("grant:unauthorized");
    extra.use_class = SharedExperienceUseClassV2::RawEvidenceRead {
        consumer_id: canonical_id("agent:unauthorized"),
        consumer_workspace_sha256: canonical_digest(&workspace("other workspace")),
    };
    widened.use_grants.push(extra);
    assert!(
        store
            .bind_shared_experience_publication_v2(&recall, widened)
            .is_err()
    );
    let mut widened = recall_binding.publication.clone();
    widened
        .destination_scope_ids
        .insert(canonical_id("scope:unauthorized"));
    assert!(
        store
            .bind_shared_experience_publication_v2(&recall, widened)
            .is_err()
    );
    let mut reinterpreted = recall_binding.publication.clone();
    reinterpreted.source_kind = SharedExperienceSourceKindV2::CanonicalMemoryEvent;
    assert!(
        store
            .bind_shared_experience_publication_v2(&recall, reinterpreted)
            .is_err()
    );

    let read_grant = recall_binding.publication.use_grants[0].clone();
    let use_receipt = SharedExperienceUseReceiptV2 {
        use_operation_id: canonical_id("operation:shared-read"),
        publication_sha256: recall_binding.publication_sha256,
        grant: read_grant,
        source_owner_id: canonical_id(owner_id.as_str()),
        source_revision: memory.id.revision,
        consumer_id: canonical_id(consumer_id.as_str()),
        observed_policy_generation: ContractGenerationV1::new(recall.policy_revision())
            .expect("generation"),
        observed_revocation_frontier: recall.policy_revision(),
        payload_sha256: canonical_digest(&memory.content_sha256),
        used_at_unix_ms: u64::try_from(
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock")
                .as_millis(),
        )
        .expect("time"),
        final_use_observed: true,
        disposition: SharedExperienceUseDispositionV2::Delivered,
    };
    store
        .revalidate_shared_experience_use_v2(&recall, &recall_binding, &use_receipt)
        .await
        .expect("V2 use receipt");

    let mut forged_frontier = use_receipt.clone();
    forged_frontier.observed_revocation_frontier += 1;
    assert!(
        store
            .revalidate_shared_experience_use_v2(&recall, &recall_binding, &forged_frontier)
            .await
            .is_err()
    );
    let mut future = use_receipt;
    future.used_at_unix_ms += 30_000;
    assert!(
        store
            .revalidate_shared_experience_use_v2(&recall, &recall_binding, &future)
            .await
            .is_err()
    );

    let replay_purpose = SharedExperiencePurposeV1::Replay {
        parameter_scope: "domain.code-head".into(),
        artifact_consumer: consumer_id.clone(),
    };
    let replay = store
        .grant_shared_experience(
            &access,
            &SharedExperienceGrantV1 {
                memory_id: memory.id.memory_id.clone(),
                memory_revision: memory.id.revision,
                consumer: consumer.clone(),
                purpose: replay_purpose,
                expires_at_unix_seconds: expiry,
            },
            0,
        )
        .await
        .expect("replay grant");
    let mut incomplete = replay_grants_for(&replay);
    incomplete.retain(|grant| {
        !matches!(
            grant.use_class,
            SharedExperienceUseClassV2::DerivedArtifactUse { .. }
        )
    });
    assert!(
        store
            .bind_shared_experience_publication_v2(
                &replay,
                publication_for(&replay, incomplete, "contribution:replay-incomplete"),
            )
            .is_err(),
        "training permission alone must not imply artifact adoption"
    );
    let replay_binding = store
        .bind_shared_experience_publication_v2(
            &replay,
            publication_for(
                &replay,
                replay_grants_for(&replay),
                "contribution:replay-v2",
            ),
        )
        .expect("replay publication");

    store
        .revoke_shared_experience(&access, &replay)
        .await
        .expect("durable revoke");
    let revocation = SharedExperienceRevocationReceiptV2 {
        revocation_operation_id: canonical_id("operation:shared-revoke"),
        contribution_id: replay_binding.publication.contribution_id.clone(),
        publication_sha256: replay_binding.publication_sha256,
        source_owner_id: canonical_id(owner_id.as_str()),
        source_revision: memory.id.revision,
        predecessor_policy_generation: ContractGenerationV1::new(replay.policy_revision())
            .expect("predecessor"),
        next_policy_generation: ContractGenerationV1::new(replay.policy_revision() + 1)
            .expect("next"),
        revocation_frontier: replay.policy_revision() + 1,
        all_uses_revoked: true,
        revoked_use_grant_ids: std::collections::BTreeSet::new(),
        affected_projection_sha256s: std::collections::BTreeSet::new(),
        affected_training_dataset_sha256s: std::collections::BTreeSet::from([canonical_digest(
            &Sha256Digest::for_bytes(b"dataset-split"),
        )]),
        affected_artifact_sha256s: std::collections::BTreeSet::from([canonical_digest(
            &Sha256Digest::for_bytes(b"artifact-candidate"),
        )]),
        pending_offline_owner_ids: std::collections::BTreeSet::from([
            canonical_id("learning.operator"),
            canonical_id("learning.artifacts"),
        ]),
        source_use_blocked: true,
        training_use_blocked: true,
        artifact_adoption_blocked: true,
        influence_status: SharedExperienceInfluenceStatusV2::Pending,
        influence_proof_sha256: None,
        completeness: SharedExperienceRevocationCompletenessV2::Partial,
    };
    store
        .verify_shared_experience_revocation_v2(&replay, &replay_binding, &revocation)
        .await
        .expect("V2 revocation receipt");
    let mut unobserved_downstream = revocation.clone();
    unobserved_downstream.completeness = SharedExperienceRevocationCompletenessV2::Complete;
    unobserved_downstream.pending_offline_owner_ids.clear();
    assert!(
        store
            .verify_shared_experience_revocation_v2(
                &replay,
                &replay_binding,
                &unobserved_downstream
            )
            .await
            .is_err()
    );
    let mut forged_frontier = revocation.clone();
    forged_frontier.revocation_frontier += 1;
    assert!(
        store
            .verify_shared_experience_revocation_v2(&replay, &replay_binding, &forged_frontier)
            .await
            .is_err()
    );
    let mut unlearning_claim = revocation;
    unlearning_claim.influence_status = SharedExperienceInfluenceStatusV2::ProvedRemoved;
    unlearning_claim.influence_proof_sha256 = Some(canonical_digest(&Sha256Digest::for_bytes(
        b"unverified claim",
    )));
    assert!(
        store
            .verify_shared_experience_revocation_v2(&replay, &replay_binding, &unlearning_claim)
            .await
            .is_err()
    );
    assert!(store.revalidate_shared_experience(&replay).await.is_err());
}
