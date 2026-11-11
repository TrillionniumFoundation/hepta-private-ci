use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use pretty_assertions::assert_eq;
use serde_json::Value;
use tempfile::TempDir;

use super::EpisodicRecordAdmission;
use super::EpisodicSnapshotAdmission;
use super::EpisodicSnapshotVerifier;
use crate::CognitiveAccess;
use crate::CognitiveRecoveryRequirement;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::MemoryLifecycleState;
use crate::MemoryVerification;
use crate::ProductionAuthorityLease;
use crate::ProductionAuthorityToken;
use crate::ProductionAuthorityVerifier;
use crate::ProductionDurableWriter;
use crate::StableMemoryId;
use crate::cognitive_test_support;
use crate::cognitive_test_support::source;

type TestResult = Result<(), Box<dyn std::error::Error>>;

// Frozen complete-source fixtures; their canonical hashes were independently
// recomputed with Python json.dumps(sort_keys=True, ensure_ascii=False).
// UNICODE was emitted by the actual pinned EpisodicStore.export_snapshot.
const GOLDEN: &str = r#"{"body":{"authority_id":"bridge-original-source-owner","generation":1,"namespace":"bridge-fixture","records":[{"dependencies":[],"key":"route","namespace":"bridge-fixture","provenance":{"episode_id":"source-episode","source_sha256":"9da1fafe5fde75bec5c885139496d8a5efd1c5f4dacfd6802304e546be30a8e7","source_uri":"fixture://route","source_version":"1"},"record_id":"d7a24d35085622e41780640b27e454d4e9b68f0af33321f79683a017c752843f","source_id":"source-a","text":"Use route blue.","version":1,"write_sequence":1}],"schema":"hepta.mem6.snapshot.v1"},"sha256":"7de06091c154432340b6973938a53311b44ed7bbc3dc32b36e2a21d5ef2484a6"}"#;
const INITIAL: &str = r#"{"body":{"authority_id":"bridge-original-source-owner","generation":3,"namespace":"bridge-fixture","records":[{"dependencies":[],"key":"route","namespace":"bridge-fixture","provenance":{"episode_id":"source-episode","source_sha256":"9da1fafe5fde75bec5c885139496d8a5efd1c5f4dacfd6802304e546be30a8e7","source_uri":"fixture://route","source_version":"1"},"record_id":"d7a24d35085622e41780640b27e454d4e9b68f0af33321f79683a017c752843f","source_id":"source-a","text":"Use route blue.","version":1,"write_sequence":1},{"dependencies":["d7a24d35085622e41780640b27e454d4e9b68f0af33321f79683a017c752843f"],"key":"derived","namespace":"bridge-fixture","provenance":{"episode_id":"source-episode","source_sha256":"2a4fbbdb68f1ad47b4a1a4e6e92e8a53ed259cefa076e2d30fe99aa975d01180","source_uri":"fixture://derived","source_version":"1"},"record_id":"cb489b504f4b7e981c8ef505d2927ae89071fe961709c30950acb727cb8afb51","source_id":"source-b","text":"The route evidence says blue.","version":1,"write_sequence":2},{"dependencies":[],"key":"unrelated","namespace":"bridge-fixture","provenance":{"episode_id":"source-episode","source_sha256":"1160510952698f0c61ba4864a9ab4fcbf7c2c4039971c602816a93d4faea8bfd","source_uri":"fixture://unrelated","source_version":"1"},"record_id":"329bae60950e23696c7caa7ef873d0625e5735ce4161bc5a52e4e9a7dad1d8c7","source_id":"source-c","text":"Use flow gamma.","version":1,"write_sequence":3}],"schema":"hepta.mem6.snapshot.v1"},"sha256":"bb189d0445231bbfa748f26e039f909fa0fe654fb59d08cad8b3e2ecbf9056e8"}"#;
const UPDATED: &str = r#"{"body":{"authority_id":"bridge-original-source-owner","generation":4,"namespace":"bridge-fixture","records":[{"dependencies":[],"key":"route","namespace":"bridge-fixture","provenance":{"episode_id":"source-episode","source_sha256":"02bbd47c6798065603afb46f0bc505a5474b23371d372aca4a61c733fc97e47f","source_uri":"fixture://route","source_version":"2"},"record_id":"471981f50b02f9f8351c781eff23726c37452fb51a1dd51815ca41cbe70670de","source_id":"source-a","text":"Use route green.","version":2,"write_sequence":4},{"dependencies":[],"key":"unrelated","namespace":"bridge-fixture","provenance":{"episode_id":"source-episode","source_sha256":"1160510952698f0c61ba4864a9ab4fcbf7c2c4039971c602816a93d4faea8bfd","source_uri":"fixture://unrelated","source_version":"1"},"record_id":"329bae60950e23696c7caa7ef873d0625e5735ce4161bc5a52e4e9a7dad1d8c7","source_id":"source-c","text":"Use flow gamma.","version":1,"write_sequence":3}],"schema":"hepta.mem6.snapshot.v1"},"sha256":"70ab3c9221edf5854109a0185024c84d846a731a1593cabdd5411f4c1846ae6b"}"#;
const WITHDRAWN: &str = r#"{"body":{"authority_id":"bridge-original-source-owner","generation":5,"namespace":"bridge-fixture","records":[],"schema":"hepta.mem6.snapshot.v1"},"sha256":"ebff4cd2b9a1732240ac8bf8e1f2300c163d6bcd709226d2d3afb00b3b7647e2"}"#;
const RESURRECT: &str = r#"{"body":{"authority_id":"bridge-original-source-owner","generation":6,"namespace":"bridge-fixture","records":[{"dependencies":[],"key":"route","namespace":"bridge-fixture","provenance":{"episode_id":"source-episode","source_sha256":"5f03ce01e024cff408b367c1a4e4854170afe4c1fb108a5411614da417c11246","source_uri":"fixture://route","source_version":"3"},"record_id":"577730f0a4d97f697793d53503a5442c1b626bb15f3e34bccb4befe354213e87","source_id":"source-a","text":"Use route red.","version":3,"write_sequence":6}],"schema":"hepta.mem6.snapshot.v1"},"sha256":"257c679691e230fe4c6227241b1274f7d6b871042789c097a19450e234f22e7e"}"#;
const REPLACED_AUTHORITY: &str = r#"{"body":{"authority_id":"different-source-owner","generation":5,"namespace":"bridge-fixture","records":[{"dependencies":[],"key":"route","namespace":"bridge-fixture","provenance":{"episode_id":"source-episode","source_sha256":"02bbd47c6798065603afb46f0bc505a5474b23371d372aca4a61c733fc97e47f","source_uri":"fixture://route","source_version":"2"},"record_id":"471981f50b02f9f8351c781eff23726c37452fb51a1dd51815ca41cbe70670de","source_id":"source-a","text":"Use route green.","version":2,"write_sequence":4},{"dependencies":[],"key":"unrelated","namespace":"bridge-fixture","provenance":{"episode_id":"source-episode","source_sha256":"1160510952698f0c61ba4864a9ab4fcbf7c2c4039971c602816a93d4faea8bfd","source_uri":"fixture://unrelated","source_version":"1"},"record_id":"329bae60950e23696c7caa7ef873d0625e5735ce4161bc5a52e4e9a7dad1d8c7","source_id":"source-c","text":"Use flow gamma.","version":1,"write_sequence":3}],"schema":"hepta.mem6.snapshot.v1"},"sha256":"fa7dff9e681f53a3a06b6a52ecf6ca2d48b0cb2c6113148e62e9c5d33cd2253d"}"#;
const INCOMPLETE_DEPENDENCY: &str = r#"{"body":{"authority_id":"bridge-original-source-owner","generation":4,"namespace":"bridge-fixture","records":[{"dependencies":[],"key":"route","namespace":"bridge-fixture","provenance":{"episode_id":"source-episode","source_sha256":"02bbd47c6798065603afb46f0bc505a5474b23371d372aca4a61c733fc97e47f","source_uri":"fixture://route","source_version":"2"},"record_id":"471981f50b02f9f8351c781eff23726c37452fb51a1dd51815ca41cbe70670de","source_id":"source-a","text":"Use route green.","version":2,"write_sequence":4},{"dependencies":["d7a24d35085622e41780640b27e454d4e9b68f0af33321f79683a017c752843f"],"key":"derived","namespace":"bridge-fixture","provenance":{"episode_id":"source-episode","source_sha256":"2a4fbbdb68f1ad47b4a1a4e6e92e8a53ed259cefa076e2d30fe99aa975d01180","source_uri":"fixture://derived","source_version":"1"},"record_id":"cb489b504f4b7e981c8ef505d2927ae89071fe961709c30950acb727cb8afb51","source_id":"source-b","text":"The route evidence says blue.","version":1,"write_sequence":2},{"dependencies":[],"key":"unrelated","namespace":"bridge-fixture","provenance":{"episode_id":"source-episode","source_sha256":"1160510952698f0c61ba4864a9ab4fcbf7c2c4039971c602816a93d4faea8bfd","source_uri":"fixture://unrelated","source_version":"1"},"record_id":"329bae60950e23696c7caa7ef873d0625e5735ce4161bc5a52e4e9a7dad1d8c7","source_id":"source-c","text":"Use flow gamma.","version":1,"write_sequence":3}],"schema":"hepta.mem6.snapshot.v1"},"sha256":"75da1bc33d94f16bc7383c8c8561be5522f21deb23a36e154b88c223d5a742c2"}"#;
const SAME_GENERATION_CONFLICT: &str = r#"{"body":{"authority_id":"bridge-original-source-owner","generation":3,"namespace":"bridge-fixture","records":[{"dependencies":[],"key":"unrelated","namespace":"bridge-fixture","provenance":{"episode_id":"source-episode","source_sha256":"1160510952698f0c61ba4864a9ab4fcbf7c2c4039971c602816a93d4faea8bfd","source_uri":"fixture://unrelated","source_version":"1"},"record_id":"329bae60950e23696c7caa7ef873d0625e5735ce4161bc5a52e4e9a7dad1d8c7","source_id":"source-c","text":"Use flow gamma.","version":1,"write_sequence":3}],"schema":"hepta.mem6.snapshot.v1"},"sha256":"e599ecf54d8ffa4be63552dcffd78f0006045ed6b86a0ac60cd73664989d4e3d"}"#;

const UNICODE: &str = r#"{"body":{"authority_id":"0000000000004000800000000000e001","generation":1,"namespace":"bridge-fixture","records":[{"dependencies":[],"key":"流程","namespace":"bridge-fixture","provenance":{"episode_id":"独立来源","source_sha256":"81b2ada28e09db7ffcc8f0f0dde36515818b1d79b29c75c4bbda85c7cc881e81","source_uri":"fixture://café/路径","source_version":"修订一"},"record_id":"df205a88266e26029285c4ae4e570edf47a2435888a26500de19e6af2820af4a","source_id":"源A","text":"更新：蓝色路径 café 🚀\n保留事实，而不是执行指令。","version":1,"write_sequence":1}],"schema":"hepta.mem6.snapshot.v1"},"sha256":"fb4e834f9e8d6cec04fcbbfa7c20b11f7f42aac1e9385754d336e2825581032e"}"#;

struct SourceWitness {
    expected: &'static str,
    admitted: EpisodicSnapshotAdmission,
    checks: AtomicUsize,
    reject_on_check: usize,
}

impl SourceWitness {
    fn current(expected: &'static str) -> Self {
        let value: Value = serde_json::from_str(expected).expect("fixture");
        let records = value["body"]["records"].as_array().expect("records").iter()
            .map(|record| {
                let id = record["record_id"].as_str().expect("id");
                (id.to_owned(), EpisodicRecordAdmission {
                    source: source(CognitiveScope::AgentPrivate, id, record["text"].as_str().expect("source fixture text")),
                    verification: MemoryVerification::Verified,
                })
            }).collect::<BTreeMap<_, _>>();
        Self {
            expected,
            admitted: EpisodicSnapshotAdmission { records, withdrawal: None },
            checks: AtomicUsize::new(0), reject_on_check: usize::MAX,
        }
    }

    fn authorize_withdrawal(&mut self) {
        self.admitted.withdrawal = Some(source(CognitiveScope::AgentPrivate,
            "source-owner-withdrawal", "Withdraw superseded source evidence."));
    }
}

impl EpisodicSnapshotVerifier for SourceWitness {
    fn verify_current(&self, snapshot_json: &str) -> Result<EpisodicSnapshotAdmission, String> {
        let check = self.checks.fetch_add(1, Ordering::SeqCst) + 1;
        if snapshot_json != self.expected || check == self.reject_on_check {
            return Err("original source owner no longer admits these bytes".to_owned());
        }
        Ok(self.admitted.clone())
    }
}

struct Fixture {
    directory: TempDir,
    store: CognitiveStore,
    writer: Arc<ProductionDurableWriter>,
    authority: ProductionAuthorityLease,
    verifier: Arc<dyn ProductionAuthorityVerifier>,
    live: Arc<AtomicBool>,
    access: CognitiveAccess,
}

async fn fixture() -> Result<Fixture, Box<dyn std::error::Error>> {
    let directory = TempDir::new()?;
    let owner = cognitive_test_support::agent_id(/*suffix*/ 80);
    let layout = cognitive_test_support::layout(&directory, &owner);
    let store = CognitiveStore::open(&layout).await?;
    let grant = Sha256Digest::for_bytes(b"episodic-fixture-original-writer-grant");
    let authority = ProductionAuthorityLease::from_verified_parts(
        owner.clone(), grant.clone(), /*authority_epoch*/ 1, /*owner_epoch*/ 1,
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs() + 600,
        ProductionAuthorityToken::from_verified_bytes(b"episodic-fixture-original-writer-token".to_vec())?,
    )?;
    let live = Arc::new(AtomicBool::new(true));
    let live_for_verifier = Arc::clone(&live);
    let verifier: Arc<dyn ProductionAuthorityVerifier> = Arc::new(
        move |lease: &ProductionAuthorityLease, expected: &AgentId| {
            if live_for_verifier.load(Ordering::SeqCst) && lease.agent_id == *expected && lease.grant_digest == grant {
                Ok(())
            } else {
                Err("original writer authority rejected".to_string())
            }
        },
    );
    let writer = Arc::new(ProductionDurableWriter::open_with_live_verifier(
        store.clone(), authority.clone(), Arc::clone(&verifier), "episodic-original-writer", /*generation*/ 1,
    ).await?);
    Ok(Fixture { directory, store, writer, authority, verifier, live, access: CognitiveAccess::agent_private(owner) })
}

#[tokio::test]
async fn committed_import_reopens_and_reconciles_lost_response_without_rewriting() -> TestResult {
    let Fixture { directory, store, writer, authority, verifier, access, .. } = fixture().await?;
    let capability = writer.cognitive_mutation_capability()?;
    let witness = SourceWitness::current(GOLDEN);
    let committed = capability.import_episodic_snapshot(&access, &CognitiveScope::AgentPrivate, GOLDEN, &witness).await?;
    let id = StableMemoryId::parse(&committed.bindings[0].memory_id)?;
    let original_memory = store.latest_memory(&access, &id).await?;
    assert_eq!(original_memory.content, "Use route blue.");
    assert_eq!(original_memory.verification, MemoryVerification::Verified);
    let candidates = store.retrieve_memory_candidates(&access,
        &crate::RetrievalRequest::new("route blue", /*now_unix_seconds*/ 100)).await?;
    assert_eq!(candidates.candidates.iter().map(|candidate| candidate.memory.id.memory_id.clone()).collect::<Vec<_>>(), vec![id.clone()]);
    let cut = writer.recovery_anchor().await?;
    drop(capability);
    drop(writer); // The client loses the response before its own state advances.
    store.close().await;
    drop(store);
    let layout = cognitive_test_support::layout(&directory, &authority.agent_id);
    let recovered = CognitiveStore::open_with_recovery(&layout,
        CognitiveRecoveryRequirement::ExactCurrentCut(&cut), &authority, verifier.as_ref()).await?;
    let writer = Arc::new(ProductionDurableWriter::open_with_live_verifier(recovered.clone(),
        authority, verifier, "episodic-original-writer", /*generation*/ 1).await?);
    let replay = writer.cognitive_mutation_capability()?.import_episodic_snapshot(
        &access, &CognitiveScope::AgentPrivate, GOLDEN, &witness).await?;
    assert_eq!(replay, committed);
    assert_eq!(writer.recovery_anchor().await?, cut);
    assert_eq!(recovered.latest_memory(&access, &id).await?, original_memory);
    Ok(())
}

#[tokio::test]
async fn update_withdraws_dependent_memory_and_preserves_unrelated_source() -> TestResult {
    let fixture = fixture().await?;
    let capability = fixture.writer.cognitive_mutation_capability()?;
    let initial = capability.import_episodic_snapshot(&fixture.access, &CognitiveScope::AgentPrivate,
        INITIAL, &SourceWitness::current(INITIAL)).await?;
    let mut updated = SourceWitness::current(UPDATED);
    updated.authorize_withdrawal();
    let next = capability.import_episodic_snapshot(&fixture.access, &CognitiveScope::AgentPrivate, UPDATED, &updated).await?;
    let states = next.bindings.iter().map(|binding|
        (binding.source_id.as_str(), binding.memory_revision, binding.active)).collect::<Vec<_>>();
    assert_eq!(states, vec![("source-a", 2, true), ("source-b", 2, false), ("source-c", 1, true)]);
    assert_eq!(next.bindings[2], initial.bindings[2]);
    let dependency = StableMemoryId::parse(&next.bindings[1].memory_id)?;
    assert!(matches!(fixture.store.latest_memory(&fixture.access, &dependency).await?.lifecycle,
        MemoryLifecycleState::Tombstoned { .. }));
    let mut withdrawn = SourceWitness::current(WITHDRAWN);
    withdrawn.authorize_withdrawal();
    let empty = capability.import_episodic_snapshot(&fixture.access, &CognitiveScope::AgentPrivate, WITHDRAWN, &withdrawn).await?;
    assert!(empty.bindings.iter().all(|binding| !binding.active));
    let before = fixture.writer.recovery_anchor().await?;
    assert!(capability.import_episodic_snapshot(&fixture.access, &CognitiveScope::AgentPrivate,
        RESURRECT, &SourceWitness::current(RESURRECT)).await.is_err());
    assert_eq!(fixture.writer.recovery_anchor().await?, before);
    Ok(())
}

#[tokio::test]
async fn source_and_writer_revocation_roll_back_all_native_changes() -> TestResult {
    let fixture = fixture().await?;
    let capability = fixture.writer.cognitive_mutation_capability()?;
    capability.import_episodic_snapshot(&fixture.access, &CognitiveScope::AgentPrivate,
        INITIAL, &SourceWitness::current(INITIAL)).await?;
    let before = fixture.writer.recovery_anchor().await?;
    let mut stale_during_write = SourceWitness::current(UPDATED);
    stale_during_write.authorize_withdrawal();
    stale_during_write.reject_on_check = 2;
    assert!(capability.import_episodic_snapshot(&fixture.access, &CognitiveScope::AgentPrivate,
        UPDATED, &stale_during_write).await.is_err());
    assert_eq!(fixture.writer.recovery_anchor().await?, before);
    assert!(capability.import_episodic_snapshot(&fixture.access, &CognitiveScope::AgentPrivate,
        WITHDRAWN, &SourceWitness::current(WITHDRAWN)).await.is_err());
    assert_eq!(fixture.writer.recovery_anchor().await?, before);
    let mut false_source = SourceWitness::current(UPDATED);
    false_source.admitted.records.values_mut().next().expect("record").source.content = b"different original source".to_vec();
    assert!(capability.import_episodic_snapshot(&fixture.access, &CognitiveScope::AgentPrivate,
        UPDATED, &false_source).await.is_err());
    fixture.live.store(false, Ordering::SeqCst);
    assert!(capability.import_episodic_snapshot(&fixture.access, &CognitiveScope::AgentPrivate,
        INITIAL, &SourceWitness::current(INITIAL)).await.is_err());
    assert_eq!(fixture.writer.recovery_anchor().await?, before);
    Ok(())
}

#[tokio::test]
async fn historical_or_incoherent_source_states_cannot_overwrite_native_heads() -> TestResult {
    let fixture = fixture().await?;
    let capability = fixture.writer.cognitive_mutation_capability()?;
    let receipt = capability.import_episodic_snapshot(&fixture.access, &CognitiveScope::AgentPrivate,
        INITIAL, &SourceWitness::current(INITIAL)).await?;
    let before = fixture.writer.recovery_anchor().await?;
    for input in [GOLDEN, SAME_GENERATION_CONFLICT, REPLACED_AUTHORITY, INCOMPLETE_DEPENDENCY] {
        assert!(capability.import_episodic_snapshot(&fixture.access, &CognitiveScope::AgentPrivate,
            input, &SourceWitness::current(input)).await.is_err());
        assert_eq!(fixture.writer.recovery_anchor().await?, before);
    }
    let id = StableMemoryId::parse(&receipt.bindings[0].memory_id)?;
    let foreign = source(CognitiveScope::AgentPrivate, "ordinary-owner-correction", "Original owner corrected the memory.");
    let draft = crate::MemoryRevisionDraft {
        scope: CognitiveScope::AgentPrivate, content: "Original owner corrected the memory.".to_owned(),
        verification: MemoryVerification::Verified, lifecycle: MemoryLifecycleState::Active,
        valid_from_unix_seconds: 101, valid_to_unix_seconds: None, citations: Vec::new(),
    };
    crate::ProductionCognitiveMutation::correct_with_kg(&capability, &fixture.access, &id,
        /*expected_revision*/ 1, &foreign, &draft, &crate::KgFactSetDraft::default()).await?;
    let after_owner = fixture.writer.recovery_anchor().await?;
    assert!(capability.import_episodic_snapshot(&fixture.access, &CognitiveScope::AgentPrivate,
        INITIAL, &SourceWitness::current(INITIAL)).await.is_err());
    assert_eq!(fixture.writer.recovery_anchor().await?, after_owner);
    Ok(())
}

#[tokio::test]
async fn actual_python_unicode_export_preserves_exact_observed_fact_bytes() -> TestResult {
    let fixture = fixture().await?;
    let receipt = fixture.writer.cognitive_mutation_capability()?.import_episodic_snapshot(
        &fixture.access, &CognitiveScope::AgentPrivate, UNICODE, &SourceWitness::current(UNICODE)).await?;
    let id = StableMemoryId::parse(&receipt.bindings[0].memory_id)?;
    let stored = fixture.store.latest_memory(&fixture.access, &id).await?;
    assert_eq!(stored.content, "更新：蓝色路径 café 🚀\n保留事实，而不是执行指令。");
    assert_eq!(receipt.snapshot_sha256, "fb4e834f9e8d6cec04fcbbfa7c20b11f7f42aac1e9385754d336e2825581032e");
    Ok(())
}

#[tokio::test]
async fn changed_source_admission_cannot_reuse_an_old_canonical_binding() -> TestResult {
    let fixture = fixture().await?;
    let capability = fixture.writer.cognitive_mutation_capability()?;
    capability.import_episodic_snapshot(&fixture.access, &CognitiveScope::AgentPrivate,
        INITIAL, &SourceWitness::current(INITIAL)).await?;
    let before = fixture.writer.recovery_anchor().await?;
    let mut changed_event = SourceWitness::current(INITIAL);
    changed_event.admitted.records.values_mut().next().expect("record").source.event_key.push_str(":new-observation");
    let mut changed_time = SourceWitness::current(INITIAL);
    changed_time.admitted.records.values_mut().next().expect("record").source.observed_at_unix_seconds += 1;
    for changed in [changed_event, changed_time] {
        assert!(capability.import_episodic_snapshot(&fixture.access, &CognitiveScope::AgentPrivate,
            INITIAL, &changed).await.is_err());
        assert_eq!(fixture.writer.recovery_anchor().await?, before);
    }
    let mut unchanged_record_new_source = SourceWitness::current(UPDATED);
    unchanged_record_new_source.authorize_withdrawal();
    let unchanged_id: Value = serde_json::from_str(UPDATED)?;
    let id = unchanged_id["body"]["records"][1]["record_id"].as_str().expect("unchanged record");
    unchanged_record_new_source.admitted.records.get_mut(id).expect("admitted source").source.event_key.push_str(":new");
    assert!(capability.import_episodic_snapshot(&fixture.access, &CognitiveScope::AgentPrivate,
        UPDATED, &unchanged_record_new_source).await.is_err());
    assert_eq!(fixture.writer.recovery_anchor().await?, before);
    Ok(())
}

#[tokio::test]
async fn custody_preserves_provisional_state_and_cannot_upgrade_it_on_replay() -> TestResult {
    let fixture = fixture().await?;
    let capability = fixture.writer.cognitive_mutation_capability()?;
    let mut custody = SourceWitness::current(GOLDEN);
    custody.admitted.records.values_mut().next().expect("record").verification = MemoryVerification::Provisional;
    let receipt = capability.import_episodic_snapshot(&fixture.access, &CognitiveScope::AgentPrivate,
        GOLDEN, &custody).await?;
    let id = StableMemoryId::parse(&receipt.bindings[0].memory_id)?;
    assert_eq!(fixture.store.latest_memory(&fixture.access, &id).await?.verification, MemoryVerification::Provisional);
    let candidates = fixture.store.retrieve_memory_candidates(&fixture.access,
        &crate::RetrievalRequest::new("route blue", /*now_unix_seconds*/ 100)).await?;
    assert!(candidates.candidates.is_empty());
    let before = fixture.writer.recovery_anchor().await?;
    assert!(capability.import_episodic_snapshot(&fixture.access, &CognitiveScope::AgentPrivate,
        GOLDEN, &SourceWitness::current(GOLDEN)).await.is_err());
    let mut correction = SourceWitness::current(UPDATED);
    for admission in correction.admitted.records.values_mut() {
        admission.verification = MemoryVerification::Provisional;
    }
    assert!(capability.import_episodic_snapshot(&fixture.access, &CognitiveScope::AgentPrivate,
        UPDATED, &correction).await.is_err());
    assert_eq!(fixture.writer.recovery_anchor().await?, before);
    Ok(())
}
