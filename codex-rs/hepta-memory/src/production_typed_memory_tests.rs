//! Real SQLite and Ed25519 paths with explicitly test-only host trust. This
//! qualifies admission mechanics, not an installed production evidence owner.
#![cfg(unix)]

use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::*;
use crate::CognitiveRecoveryRequirement;
use crate::CognitiveStore;
use crate::ForgetMemoryDraft;
use crate::KgEntityFactDraft;
use crate::KgFactSetDraft;
use crate::KgRelationFactDraft;
use crate::MemoryDraft;
use crate::MemoryLifecycleState;
use crate::MemoryRevisionDraft;
use crate::MemoryVerification;
use crate::ProductionAuthorityLease;
use crate::ProductionAuthorityToken;
use crate::ProductionAuthorityVerifier;
use crate::ProductionCognitiveMutation;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::source;

const SCOPE: CognitiveScope = CognitiveScope::AgentPrivate;

struct TestEvidence(Arc<AtomicBool>);
impl TypedMemoryEvidenceVerifierV1 for TestEvidence {
    fn verify(&self, _: &AgentId, proposal: &TypedMemoryProposalV1) -> Result<(), String> {
        if self.0.load(Ordering::SeqCst)
            || proposal.host_evidence_sha256
                != Sha256Digest::for_bytes(b"test-only independent event receipt")
        {
            Err("test evidence revoked or unresolved".into())
        } else {
            Ok(())
        }
    }
}

struct TestOwner {
    temp: TempDir,
    store: CognitiveStore,
    writer: Arc<ProductionDurableWriter>,
    cap: ProductionTypedMemoryCapabilityV1,
    access: CognitiveAccess,
    issuer: SigningKey,
    evidence_revoked: Arc<AtomicBool>,
}

async fn owner() -> TestOwner {
    let temp = TempDir::new().unwrap();
    let agent = agent_id(185);
    let store = CognitiveStore::open(&layout(&temp, &agent)).await.unwrap();
    let authority = ProductionAuthorityLease::from_verified_parts(
        agent.clone(),
        Sha256Digest::for_bytes(b"test-only typed lease"),
        /*authority_epoch*/ 1,
        /*owner_epoch*/ 1,
        crate::production_writer::now_unix_seconds().unwrap() + 3600,
        ProductionAuthorityToken::from_verified_bytes(b"test-only typed token".to_vec()).unwrap(),
    )
    .unwrap();
    let verifier: Arc<dyn ProductionAuthorityVerifier> =
        Arc::new(|lease: &ProductionAuthorityLease, expected: &AgentId| {
            if lease.agent_id == *expected {
                Ok(())
            } else {
                Err("wrong test owner".into())
            }
        });
    let writer = Arc::new(
        ProductionDurableWriter::open_with_live_verifier(
            store.clone(),
            authority,
            verifier,
            "typed-memory-test",
            /*generation*/ 1,
        )
        .await
        .unwrap(),
    );
    let issuer = SigningKey::from_bytes(&[91; 32]);
    let directory = temp.path().join("typed-final-use");
    std::fs::create_dir(&directory).unwrap();
    std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o700)).unwrap();
    let final_use = FinalUseAuthority::open_state_dir(
        &directory,
        "test-only-typed-issuer".into(),
        issuer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .unwrap();
    let evidence_revoked = Arc::new(AtomicBool::new(false));
    let cap = writer
        .typed_memory_capability(
            final_use,
            Arc::new(TestEvidence(Arc::clone(&evidence_revoked))),
        )
        .unwrap();
    TestOwner {
        temp,
        store,
        writer,
        cap,
        access: CognitiveAccess::agent_private(agent),
        issuer,
        evidence_revoked,
    }
}

async fn proposal(owner: &TestOwner, key: &str) -> TypedMemoryProposalV1 {
    let cut = owner.cap.observe_cut(&owner.access, &SCOPE).await.unwrap();
    TypedMemoryProposalV1 {
        kind: TypedMemoryKindV1::Episode,
        change: TypedMemoryChangeV1::Create {
            draft: MemoryDraft {
                stable_key: key.into(),
                revision: MemoryRevisionDraft {
                    scope: SCOPE,
                    content: "User completed the calibration run.".into(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: 100,
                    valid_to_unix_seconds: None,
                    citations: vec![],
                },
            },
        },
        source: source(SCOPE, key, "User completed the calibration run."),
        facts: KgFactSetDraft::default(),
        expected_owner_cut_sha256: Sha256Digest::parse(cut.cut_digest().to_string()).unwrap(),
        expected_source_frontier: cut.frontiers().source,
        expected_tombstone_frontier: cut.frontiers().tombstone,
        host_evidence_sha256: Sha256Digest::for_bytes(b"test-only independent event receipt"),
    }
}

fn sign(owner: &TestOwner, proposal: &TypedMemoryProposalV1, id: &str) -> SignedFinalUseGrant {
    let now = crate::production_writer::now_unix_ms().unwrap();
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "test-only-typed-issuer".into(),
        authority_epoch: 1,
        grant_id: id.into(),
        nonce: *Digest32::of_bytes(id.as_bytes()).as_array(),
        binding: owner.cap.proposal_binding(proposal).unwrap(),
        not_before_unix_ms: now - 1000,
        expires_at_unix_ms: now + 60_000,
    };
    let signature = owner
        .issuer
        .sign(&grant.signing_bytes().unwrap())
        .to_bytes()
        .to_vec();
    SignedFinalUseGrant { grant, signature }
}

#[tokio::test]
async fn typed_episode_survives_exact_reopen_and_both_real_snapshot_paths() {
    let owner = owner().await;
    let input = proposal(&owner, "episode").await;
    let receipt = owner
        .cap
        .admit(&owner.access, &input, &sign(&owner, &input, "create"))
        .await
        .unwrap();
    receipt.mutation.validate().unwrap();
    let observed_at = i64::try_from(crate::production_writer::now_unix_seconds().unwrap()).unwrap();
    let before = owner
        .store
        .lane_c_snapshot(&owner.access, &SCOPE, observed_at)
        .await
        .unwrap();
    assert_eq!(
        before
            .snapshot()
            .records
            .iter()
            .map(|r| (r.kind, r.state))
            .collect::<Vec<_>>(),
        vec![(MemoryKind::Episode, RecordState::Live)]
    );
    let anchor = owner.store.recovery_anchor().await.unwrap();
    let TestOwner {
        temp,
        store,
        writer,
        cap,
        access,
        ..
    } = owner;
    let authority = writer.authority().clone();
    let verifier = Arc::clone(writer.live_verifier.as_ref().unwrap());
    drop(cap);
    drop(writer);
    store.close().await;
    let reopened = CognitiveStore::open_with_recovery(
        &layout(&temp, &authority.agent_id),
        CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
        &authority,
        verifier.as_ref(),
    )
    .await
    .unwrap();
    let after = reopened
        .lane_c_snapshot(&access, &SCOPE, observed_at)
        .await
        .unwrap();
    assert_eq!(after, before);
    let page = reopened
        .lane_c_snapshot_page(
            &access,
            &SCOPE,
            observed_at,
            /*maximum_heads*/ 8,
            /*after*/ None,
        )
        .await
        .unwrap();
    assert_eq!(page.records(), after.snapshot().records.as_slice());
}

#[tokio::test]
async fn signed_full_proposal_rejects_changed_type_source_facts_and_scope() {
    let owner = owner().await;
    let input = proposal(&owner, "bound").await;
    let signed = sign(&owner, &input, "bound");
    let mut variants = vec![input.clone(); 4];
    variants[0].kind = TypedMemoryKindV1::Fact;
    variants[1].source.event_key = "different source event".into();
    variants[2].facts.entities.push(KgEntityFactDraft {
        key: "run".into(),
        entity_type: "event".into(),
        label: "run".into(),
    });
    variants[3].expected_tombstone_frontier += 1;
    for changed in variants {
        assert!(
            owner
                .cap
                .admit(&owner.access, &changed, &signed)
                .await
                .is_err()
        );
    }
    let alien = CognitiveAccess::agent_private(agent_id(186));
    assert!(owner.cap.admit(&alien, &input, &signed).await.is_err());
    let mut forged = signed.clone();
    forged.signature[0] ^= 1;
    assert!(
        owner
            .cap
            .admit(&owner.access, &input, &forged)
            .await
            .is_err()
    );
    owner
        .cap
        .admit(&owner.access, &input, &signed)
        .await
        .unwrap();
    assert_eq!(
        owner
            .cap
            .observe_cut(&owner.access, &SCOPE)
            .await
            .unwrap()
            .snapshot()
            .records
            .len(),
        1
    );
}

#[tokio::test]
async fn legacy_correction_cannot_retype_but_forget_retains_the_admission() {
    let owner = owner().await;
    let initial = proposal(&owner, "revise").await;
    let first = owner
        .cap
        .admit(&owner.access, &initial, &sign(&owner, &initial, "first"))
        .await
        .unwrap();
    let id = first.mutation.write.memory.id.memory_id;
    let mut correction = proposal(&owner, "correct").await;
    correction.change = TypedMemoryChangeV1::Correct {
        memory_id: id.clone(),
        expected_revision: 1,
        draft: initial.change.revision().clone(),
    };
    let legacy = owner.writer.cognitive_mutation_capability().unwrap();
    assert!(
        legacy
            .correct_with_kg(
                &owner.access,
                &id,
                /*expected_revision*/ 1,
                &correction.source,
                correction.change.revision(),
                &correction.facts
            )
            .await
            .is_err()
    );
    let mut retype = correction.clone();
    retype.kind = TypedMemoryKindV1::Fact;
    assert!(
        owner
            .cap
            .admit(&owner.access, &retype, &sign(&owner, &retype, "retype"))
            .await
            .is_err()
    );
    let second = owner
        .cap
        .admit(
            &owner.access,
            &correction,
            &sign(&owner, &correction, "second"),
        )
        .await
        .unwrap();
    assert_eq!(second.mutation.write.memory.id.revision, 2);
    legacy
        .forget_with_kg(
            &owner.access,
            &id,
            /*expected_revision*/ 2,
            &source(SCOPE, "forget", "user withdrew event"),
            &ForgetMemoryDraft {
                scope: SCOPE,
                reason: "user withdrew event".into(),
                valid_from_unix_seconds: 101,
                citations: vec![],
            },
        )
        .await
        .unwrap();
    let cut = owner.cap.observe_cut(&owner.access, &SCOPE).await.unwrap();
    assert_eq!(
        cut.snapshot()
            .records
            .iter()
            .map(|r| (r.kind, r.state, r.revision.get()))
            .collect::<Vec<_>>(),
        vec![(MemoryKind::Episode, RecordState::Tombstone, 3)]
    );
}

#[tokio::test]
async fn another_committed_write_invalidates_signed_owner_cut() {
    let owner = owner().await;
    let stale = proposal(&owner, "stale").await;
    let current = proposal(&owner, "current").await;
    let signed = sign(&owner, &stale, "stale");
    owner
        .cap
        .admit(&owner.access, &current, &sign(&owner, &current, "current"))
        .await
        .unwrap();
    assert!(
        owner
            .cap
            .admit(&owner.access, &stale, &signed)
            .await
            .is_err()
    );
    assert_eq!(
        owner
            .cap
            .observe_cut(&owner.access, &SCOPE)
            .await
            .unwrap()
            .frontiers()
            .source,
        1
    );
}

#[tokio::test]
async fn post_open_evidence_revocation_and_final_use_revocation_deny_writes() {
    let owner = owner().await;
    let input = proposal(&owner, "revoked").await;
    let signed = sign(&owner, &input, "revoked");
    owner.evidence_revoked.store(true, Ordering::SeqCst);
    assert!(
        owner
            .cap
            .admit(&owner.access, &input, &signed)
            .await
            .is_err()
    );
    owner.evidence_revoked.store(false, Ordering::SeqCst);
    owner
        .cap
        .final_use
        .update_revocations(FinalUseRevocations {
            authority_epoch: 1,
            revision: 2,
            revoked_grant_ids: BTreeSet::from(["revoked".into()]),
        })
        .unwrap();
    assert!(
        owner
            .cap
            .admit(&owner.access, &input, &signed)
            .await
            .is_err()
    );
    assert_eq!(
        owner
            .cap
            .observe_cut(&owner.access, &SCOPE)
            .await
            .unwrap()
            .frontiers()
            .memory,
        0
    );
}

#[tokio::test]
async fn failed_fact_projection_rolls_back_source_revision_and_lease_but_burns_nonce() {
    let owner = owner().await;
    let mut input = proposal(&owner, "rollback").await;
    input.facts.relations.push(KgRelationFactDraft {
        key: "bad".into(),
        from_entity_key: "missing".into(),
        to_entity_key: "missing2".into(),
        relation: "causes".into(),
    });
    let signed = sign(&owner, &input, "rollback");
    assert!(
        owner
            .cap
            .admit(&owner.access, &input, &signed)
            .await
            .is_err()
    );
    let cut = owner.cap.observe_cut(&owner.access, &SCOPE).await.unwrap();
    assert_eq!(
        (
            cut.frontiers().memory,
            cut.frontiers().source,
            cut.frontiers().knowledge_facts
        ),
        (0, 0, 0)
    );
    assert!(matches!(
        owner.cap.admit(&owner.access, &input, &signed).await,
        Err(ProductionCognitiveMutationError::Authority(
            ProductionWriterError::FinalUse(codex_hepta_contracts::FinalUseError::AlreadyClaimed)
        ))
    ));
}

#[tokio::test]
async fn procedural_claim_has_no_success_path_through_fact_or_step_metadata() {
    let owner = owner().await;
    let mut input = proposal(&owner, "procedure").await;
    input.kind = TypedMemoryKindV1::Procedure;
    input.facts.relations.push(KgRelationFactDraft {
        key: "step".into(),
        from_entity_key: "start".into(),
        to_entity_key: "end".into(),
        relation: "procedure_step".into(),
    });
    assert!(matches!(
        owner.cap.proposal_binding(&input),
        Err(ProductionCognitiveMutationError::Store(
            CognitiveStoreError::AccessDenied(_)
        ))
    ));
    assert_eq!(
        owner
            .cap
            .observe_cut(&owner.access, &SCOPE)
            .await
            .unwrap()
            .frontiers()
            .memory,
        0
    );
}
