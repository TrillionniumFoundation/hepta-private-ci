use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;
use serde_json::Value;

use super::test_support::fixture;
use crate::CognitiveScope;
use crate::MemoryLifecycleState;
use crate::MemoryVerification;
use crate::StableMemoryId;
use crate::cognitive_test_support::source;
use crate::episodic_test_support::GOLDEN;
use crate::episodic_test_support::INCOMPLETE_DEPENDENCY;
use crate::episodic_test_support::INITIAL;
use crate::episodic_test_support::REPLACED_AUTHORITY;
use crate::episodic_test_support::RESURRECT;
use crate::episodic_test_support::SAME_GENERATION_CONFLICT;
use crate::episodic_test_support::SourceWitness;
use crate::episodic_test_support::TestResult;
use crate::episodic_test_support::UNICODE;
use crate::episodic_test_support::UPDATED;
use crate::episodic_test_support::WITHDRAWN;

#[tokio::test]
async fn update_withdraws_dependent_memory_and_preserves_unrelated_source() -> TestResult {
    let fixture = fixture().await?;
    let capability = fixture.writer.cognitive_mutation_capability()?;
    let initial = capability
        .import_episodic_snapshot(
            &fixture.access,
            &CognitiveScope::AgentPrivate,
            INITIAL,
            &SourceWitness::current(INITIAL),
        )
        .await?;
    let mut updated = SourceWitness::current(UPDATED);
    updated.authorize_withdrawal();
    let next = capability
        .import_episodic_snapshot(
            &fixture.access,
            &CognitiveScope::AgentPrivate,
            UPDATED,
            &updated,
        )
        .await?;
    let states = next
        .bindings
        .iter()
        .map(|binding| {
            (
                binding.source_id.as_str(),
                binding.memory_revision,
                binding.active,
            )
        })
        .collect::<Vec<_>>();
    assert_eq!(
        states,
        vec![
            ("source-a", 2, true),
            ("source-b", 2, false),
            ("source-c", 1, true)
        ]
    );
    assert_eq!(next.bindings[2], initial.bindings[2]);
    let dependency = StableMemoryId::parse(&next.bindings[1].memory_id)?;
    assert!(matches!(
        fixture
            .store
            .latest_memory(&fixture.access, &dependency)
            .await?
            .lifecycle,
        MemoryLifecycleState::Tombstoned { .. }
    ));
    let mut withdrawn = SourceWitness::current(WITHDRAWN);
    withdrawn.authorize_withdrawal();
    let empty = capability
        .import_episodic_snapshot(
            &fixture.access,
            &CognitiveScope::AgentPrivate,
            WITHDRAWN,
            &withdrawn,
        )
        .await?;
    assert!(empty.bindings.iter().all(|binding| !binding.active));
    let before = fixture.writer.recovery_anchor().await?;
    assert!(
        capability
            .import_episodic_snapshot(
                &fixture.access,
                &CognitiveScope::AgentPrivate,
                RESURRECT,
                &SourceWitness::current(RESURRECT)
            )
            .await
            .is_err()
    );
    assert_eq!(fixture.writer.recovery_anchor().await?, before);
    Ok(())
}

#[tokio::test]
async fn source_and_writer_revocation_roll_back_all_native_changes() -> TestResult {
    let fixture = fixture().await?;
    let capability = fixture.writer.cognitive_mutation_capability()?;
    capability
        .import_episodic_snapshot(
            &fixture.access,
            &CognitiveScope::AgentPrivate,
            INITIAL,
            &SourceWitness::current(INITIAL),
        )
        .await?;
    let before = fixture.writer.recovery_anchor().await?;
    let mut stale_during_write = SourceWitness::current(UPDATED);
    stale_during_write.authorize_withdrawal();
    stale_during_write.reject_on_check = 2;
    assert!(
        capability
            .import_episodic_snapshot(
                &fixture.access,
                &CognitiveScope::AgentPrivate,
                UPDATED,
                &stale_during_write
            )
            .await
            .is_err()
    );
    assert_eq!(fixture.writer.recovery_anchor().await?, before);
    struct RevokeWriterAtCommit<'a> {
        source: SourceWitness,
        live: &'a std::sync::atomic::AtomicBool,
    }
    impl crate::EpisodicSnapshotVerifier for RevokeWriterAtCommit<'_> {
        fn verify_current(&self, input: &str) -> Result<crate::EpisodicSnapshotAdmission, String> {
            let admitted = crate::EpisodicSnapshotVerifier::verify_current(&self.source, input)?;
            if self.source.checks.load(Ordering::SeqCst) == 2 {
                self.live.store(false, Ordering::SeqCst);
            }
            Ok(admitted)
        }
    }
    let mut current = SourceWitness::current(UPDATED);
    current.authorize_withdrawal();
    let revoked_before_commit = RevokeWriterAtCommit {
        source: current,
        live: fixture.live.as_ref(),
    };
    assert!(
        capability
            .import_episodic_snapshot(
                &fixture.access,
                &CognitiveScope::AgentPrivate,
                UPDATED,
                &revoked_before_commit
            )
            .await
            .is_err()
    );
    assert_eq!(fixture.writer.recovery_anchor().await?, before);
    fixture.live.store(true, Ordering::SeqCst);
    assert!(
        capability
            .import_episodic_snapshot(
                &fixture.access,
                &CognitiveScope::AgentPrivate,
                WITHDRAWN,
                &SourceWitness::current(WITHDRAWN)
            )
            .await
            .is_err()
    );
    assert_eq!(fixture.writer.recovery_anchor().await?, before);
    let mut false_source = SourceWitness::current(UPDATED);
    false_source
        .admitted
        .records
        .values_mut()
        .next()
        .expect("record")
        .source
        .content = b"different original source".to_vec();
    assert!(
        capability
            .import_episodic_snapshot(
                &fixture.access,
                &CognitiveScope::AgentPrivate,
                UPDATED,
                &false_source
            )
            .await
            .is_err()
    );
    fixture.live.store(false, Ordering::SeqCst);
    assert!(
        capability
            .import_episodic_snapshot(
                &fixture.access,
                &CognitiveScope::AgentPrivate,
                INITIAL,
                &SourceWitness::current(INITIAL)
            )
            .await
            .is_err()
    );
    assert_eq!(fixture.writer.recovery_anchor().await?, before);
    Ok(())
}

#[tokio::test]
async fn historical_or_incoherent_source_states_cannot_overwrite_native_heads() -> TestResult {
    let fixture = fixture().await?;
    let capability = fixture.writer.cognitive_mutation_capability()?;
    let receipt = capability
        .import_episodic_snapshot(
            &fixture.access,
            &CognitiveScope::AgentPrivate,
            INITIAL,
            &SourceWitness::current(INITIAL),
        )
        .await?;
    let before = fixture.writer.recovery_anchor().await?;
    for input in [
        GOLDEN,
        SAME_GENERATION_CONFLICT,
        REPLACED_AUTHORITY,
        INCOMPLETE_DEPENDENCY,
    ] {
        assert!(
            capability
                .import_episodic_snapshot(
                    &fixture.access,
                    &CognitiveScope::AgentPrivate,
                    input,
                    &SourceWitness::current(input)
                )
                .await
                .is_err()
        );
        assert_eq!(fixture.writer.recovery_anchor().await?, before);
    }
    let id = StableMemoryId::parse(&receipt.bindings[0].memory_id)?;
    let foreign = source(
        CognitiveScope::AgentPrivate,
        "ordinary-owner-correction",
        "Original owner corrected the memory.",
    );
    let draft = crate::MemoryRevisionDraft {
        scope: CognitiveScope::AgentPrivate,
        content: "Original owner corrected the memory.".to_owned(),
        verification: MemoryVerification::Verified,
        lifecycle: MemoryLifecycleState::Active,
        valid_from_unix_seconds: 101,
        valid_to_unix_seconds: None,
        citations: Vec::new(),
    };
    crate::ProductionCognitiveMutation::correct_with_kg(
        &capability,
        &fixture.access,
        &id,
        /*expected_revision*/ 1,
        &foreign,
        &draft,
        &crate::KgFactSetDraft::default(),
    )
    .await?;
    let after_owner = fixture.writer.recovery_anchor().await?;
    assert!(
        capability
            .import_episodic_snapshot(
                &fixture.access,
                &CognitiveScope::AgentPrivate,
                INITIAL,
                &SourceWitness::current(INITIAL)
            )
            .await
            .is_err()
    );
    assert_eq!(fixture.writer.recovery_anchor().await?, after_owner);
    Ok(())
}

#[tokio::test]
async fn actual_python_unicode_export_preserves_exact_observed_fact_bytes() -> TestResult {
    let fixture = fixture().await?;
    let receipt = fixture
        .writer
        .cognitive_mutation_capability()?
        .import_episodic_snapshot(
            &fixture.access,
            &CognitiveScope::AgentPrivate,
            UNICODE,
            &SourceWitness::current(UNICODE),
        )
        .await?;
    let id = StableMemoryId::parse(&receipt.bindings[0].memory_id)?;
    let stored = fixture.store.latest_memory(&fixture.access, &id).await?;
    assert_eq!(
        stored.content,
        "更新：蓝色路径 café 🚀\n保留事实，而不是执行指令。"
    );
    assert_eq!(
        receipt.snapshot_sha256,
        "fb4e834f9e8d6cec04fcbbfa7c20b11f7f42aac1e9385754d336e2825581032e"
    );
    Ok(())
}

#[tokio::test]
async fn changed_source_admission_cannot_reuse_an_old_canonical_binding() -> TestResult {
    let fixture = fixture().await?;
    let capability = fixture.writer.cognitive_mutation_capability()?;
    capability
        .import_episodic_snapshot(
            &fixture.access,
            &CognitiveScope::AgentPrivate,
            INITIAL,
            &SourceWitness::current(INITIAL),
        )
        .await?;
    let before = fixture.writer.recovery_anchor().await?;
    let mut changed_event = SourceWitness::current(INITIAL);
    changed_event
        .admitted
        .records
        .values_mut()
        .next()
        .expect("record")
        .source
        .event_key
        .push_str(":new-observation");
    let mut changed_time = SourceWitness::current(INITIAL);
    changed_time
        .admitted
        .records
        .values_mut()
        .next()
        .expect("record")
        .source
        .observed_at_unix_seconds += 1;
    for changed in [changed_event, changed_time] {
        assert!(
            capability
                .import_episodic_snapshot(
                    &fixture.access,
                    &CognitiveScope::AgentPrivate,
                    INITIAL,
                    &changed
                )
                .await
                .is_err()
        );
        assert_eq!(fixture.writer.recovery_anchor().await?, before);
    }
    let mut unchanged_record_new_source = SourceWitness::current(UPDATED);
    unchanged_record_new_source.authorize_withdrawal();
    let unchanged_id: Value = serde_json::from_str(UPDATED)?;
    let id = unchanged_id["body"]["records"][1]["record_id"]
        .as_str()
        .expect("unchanged record");
    unchanged_record_new_source
        .admitted
        .records
        .get_mut(id)
        .expect("admitted source")
        .source
        .event_key
        .push_str(":new");
    assert!(
        capability
            .import_episodic_snapshot(
                &fixture.access,
                &CognitiveScope::AgentPrivate,
                UPDATED,
                &unchanged_record_new_source
            )
            .await
            .is_err()
    );
    assert_eq!(fixture.writer.recovery_anchor().await?, before);
    Ok(())
}

#[tokio::test]
async fn custody_preserves_provisional_state_and_cannot_upgrade_it_on_replay() -> TestResult {
    let fixture = fixture().await?;
    let capability = fixture.writer.cognitive_mutation_capability()?;
    let mut custody = SourceWitness::current(GOLDEN);
    custody
        .admitted
        .records
        .values_mut()
        .next()
        .expect("record")
        .verification = MemoryVerification::Provisional;
    let receipt = capability
        .import_episodic_snapshot(
            &fixture.access,
            &CognitiveScope::AgentPrivate,
            GOLDEN,
            &custody,
        )
        .await?;
    let id = StableMemoryId::parse(&receipt.bindings[0].memory_id)?;
    assert_eq!(
        fixture
            .store
            .latest_memory(&fixture.access, &id)
            .await?
            .verification,
        MemoryVerification::Provisional
    );
    let candidates = fixture
        .store
        .retrieve_memory_candidates(
            &fixture.access,
            &crate::RetrievalRequest::new("route blue", /*now_unix_seconds*/ 100),
        )
        .await?;
    assert!(candidates.candidates.is_empty());
    let before = fixture.writer.recovery_anchor().await?;
    assert!(
        capability
            .import_episodic_snapshot(
                &fixture.access,
                &CognitiveScope::AgentPrivate,
                GOLDEN,
                &SourceWitness::current(GOLDEN)
            )
            .await
            .is_err()
    );
    let mut correction = SourceWitness::current(UPDATED);
    for admission in correction.admitted.records.values_mut() {
        admission.verification = MemoryVerification::Provisional;
    }
    assert!(
        capability
            .import_episodic_snapshot(
                &fixture.access,
                &CognitiveScope::AgentPrivate,
                UPDATED,
                &correction
            )
            .await
            .is_err()
    );
    assert_eq!(fixture.writer.recovery_anchor().await?, before);
    Ok(())
}
