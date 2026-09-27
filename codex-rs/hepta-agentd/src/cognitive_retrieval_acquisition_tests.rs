//! Execute the actual provider entry point; fixture keys are not product pins.

use super::*;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_memory::RetrievalExecutionContextV1;
use codex_hepta_memory::sqlite_owner_cue_profile_digest;
use codex_hepta_memory::sqlite_owner_retrieval_policy_v1;
use codex_hepta_memory_retrieval::EngramDynamicsPolicyV1;
use codex_hepta_memory_retrieval::EngramSnapshotV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

fn now_ms() -> u64 {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_millis(),
    )
    .expect("clock bound")
}

fn publication() -> SignedMemoryRetrievalContextV1 {
    let policy = sqlite_owner_retrieval_policy_v1().expect("policy");
    let fixture = Digest32::of_bytes(b"explicit-acquisition-test-owner");
    let vector = LaneCGenerationVectorV1 {
        scope_id: StableId::new("scope:acquisition-test").expect("scope"),
        purpose_id: StableId::new("purpose:recall").expect("purpose"),
        memory_ledger_frontier: 1,
        knowledge_fact_frontier: 1,
        tombstone_frontier: 1,
        source_ledger_frontier: 1,
        knowledge_graph_generation: Generation::new(1).expect("generation"),
        compact_checkpoint_generation: Generation::new(1).expect("generation"),
        prompt_registry_revision: Revision::new(1).expect("revision"),
        retrieval_profile_digest: policy.digest(),
        encoder_preprocessor_digest: fixture,
        authority_epoch: 7,
        model_digest: fixture,
        tokenizer_digest: fixture,
        template_digest: fixture,
        tool_schema_digest: fixture,
    };
    let graph =
        EngramSnapshotV1::new(vector.digest(), fixture, Vec::new(), Vec::new()).expect("graph");
    let now = now_ms();
    let mut value = SignedMemoryRetrievalContextV1 {
        owner: AgentId::parse("00000000-0000-4000-8000-000000000741").expect("owner"),
        body_generation: 9,
        sequence: 1,
        not_before_unix_ms: now.saturating_sub(1),
        expires_unix_ms: now + 20_000,
        context: RetrievalExecutionContextV1 {
            generation_vector: vector,
            objective_digest: fixture,
            approved_context_digest: fixture,
            cue_profile_digest: sqlite_owner_cue_profile_digest(),
            retrieval_policy: policy,
            engram_snapshot: graph,
            dynamics_policy: EngramDynamicsPolicyV1::product_default().expect("dynamics"),
        },
        signature: [0; 64],
    };
    sign(&mut value);
    value
}

fn sign(value: &mut SignedMemoryRetrievalContextV1) {
    value.signature = SigningKey::from_bytes(&[2; 32])
        .sign(&value.signing_bytes())
        .to_bytes();
}

struct CountingFrontier {
    current: Mutex<SignedMemoryRetrievalContextV1>,
    calls: AtomicUsize,
    revoked: AtomicBool,
}

impl MemoryRetrievalFrontierOwnerV1 for CountingFrontier {
    fn observe(
        &self,
        owner: &AgentId,
        body_generation: u64,
        challenge: [u8; 32],
    ) -> Result<MemoryRetrievalFrontierV1, String> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        let value = self
            .current
            .lock()
            .map_err(|_| "fixture poisoned".to_string())?;
        if owner != &value.owner || body_generation != value.body_generation {
            return Err("fixture identity".to_string());
        }
        let revoked = self.revoked.load(Ordering::SeqCst);
        let mut response = MemoryRetrievalFrontierV1 {
            owner: value.owner.clone(),
            body_generation,
            authority_epoch: value.context.generation_vector.authority_epoch,
            sequence: value.sequence + u64::from(revoked),
            publication_digest: (!revoked).then(|| value.publication_digest()),
            expires_unix_ms: now_ms() + 10_000,
            challenge,
            signature: [0; 64],
        };
        response.signature = SigningKey::from_bytes(&[3; 32])
            .sign(&response.signing_bytes())
            .to_bytes();
        Ok(response)
    }
}

fn fixture() -> (
    SignedMemoryRetrievalContextV1,
    Arc<CountingFrontier>,
    LeasedMemoryRetrievalProviderV1,
) {
    let publication = publication();
    let frontier = Arc::new(CountingFrontier {
        current: Mutex::new(publication.clone()),
        calls: AtomicUsize::new(0),
        revoked: AtomicBool::new(false),
    });
    let provider = LeasedMemoryRetrievalProviderV1::new(
        publication.owner.clone(),
        publication.body_generation,
        SigningKey::from_bytes(&[2; 32]).verifying_key().to_bytes(),
        SigningKey::from_bytes(&[3; 32]).verifying_key().to_bytes(),
        frontier.clone(),
        30_000,
    )
    .expect("provider");
    (publication, frontier, provider)
}

#[test]
fn combined_install_acquisition_observes_once_and_never_caches_freshness() {
    let (publication, frontier, provider) = fixture();
    for expected_calls in 1..=3 {
        let (context, binding, lease) = provider
            .install_and_acquire(publication.clone(), &publication.owner, 9)
            .expect("acquire");
        assert_eq!(context, publication.context);
        assert_eq!(binding, publication.publication_digest());
        assert_eq!(lease, Some(publication.expires_unix_ms));
        assert_eq!(frontier.calls.load(Ordering::SeqCst), expected_calls);
    }
    frontier.revoked.store(true, Ordering::SeqCst);
    assert!(
        provider
            .install_and_acquire(publication.clone(), &publication.owner, 9)
            .is_err()
    );
    assert_eq!(frontier.calls.load(Ordering::SeqCst), 4);
}

#[test]
fn combined_acquisition_binds_same_payload_renewal_and_rejects_old_publication() {
    let (first, frontier, provider) = fixture();
    let (_, initial, _) = provider
        .install_and_acquire(first.clone(), &first.owner, 9)
        .expect("first");
    let mut renewed = first.clone();
    renewed.sequence += 1;
    sign(&mut renewed);
    *frontier.current.lock().expect("fixture") = renewed.clone();
    let (context, next, _) = provider
        .install_and_acquire(renewed, &first.owner, 9)
        .expect("renewed");
    assert_eq!(context, first.context);
    assert_ne!(initial, next);
    assert!(
        provider
            .install_and_acquire(first.clone(), &first.owner, 9)
            .is_err()
    );
}

#[test]
fn wrong_request_identity_is_rejected_before_installation() {
    let (publication, frontier, provider) = fixture();
    assert!(
        provider
            .install_and_acquire(publication.clone(), &publication.owner, 10)
            .is_err()
    );
    assert_eq!(frontier.calls.load(Ordering::SeqCst), 0);
}
