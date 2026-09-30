//! Cryptographic/unit fixtures only; no live frontier service or deployment claim.

use super::*;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_memory::sqlite_owner_cue_profile_digest;
use codex_hepta_memory::sqlite_owner_retrieval_policy_v1;
use codex_hepta_memory_retrieval::EngramDynamicsPolicyV1;
use codex_hepta_memory_retrieval::EngramSnapshotV1;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

fn owner() -> AgentId {
    AgentId::parse("00000000-0000-4000-8000-000000000731").expect("owner")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn publication(sequence: u64) -> SignedMemoryRetrievalContextV1 {
    let policy = sqlite_owner_retrieval_policy_v1().expect("policy");
    let external = digest("fixture-external");
    let vector = LaneCGenerationVectorV1 {
        scope_id: StableId::new("scope:retrieval-provider-fixture").expect("scope"),
        purpose_id: StableId::new("purpose:recall").expect("purpose"),
        memory_ledger_frontier: 1,
        knowledge_fact_frontier: 1,
        tombstone_frontier: 1,
        source_ledger_frontier: 1,
        knowledge_graph_generation: Generation::new(1).expect("generation"),
        compact_checkpoint_generation: Generation::new(1).expect("generation"),
        prompt_registry_revision: Revision::new(1).expect("revision"),
        retrieval_profile_digest: policy.digest(),
        encoder_preprocessor_digest: external,
        authority_epoch: 7,
        model_digest: digest(&format!("fixture-model-{sequence}")),
        tokenizer_digest: external,
        template_digest: external,
        tool_schema_digest: external,
    };
    let graph =
        EngramSnapshotV1::new(vector.digest(), external, Vec::new(), Vec::new()).expect("graph");
    let context = RetrievalExecutionContextV1 {
        generation_vector: vector,
        objective_digest: digest("objective"),
        approved_context_digest: digest("approved-context"),
        cue_profile_digest: sqlite_owner_cue_profile_digest(),
        retrieval_policy: policy,
        engram_snapshot: graph,
        dynamics_policy: EngramDynamicsPolicyV1::product_default().expect("dynamics"),
    };
    let now = now_ms().expect("clock");
    let mut result = SignedMemoryRetrievalContextV1 {
        owner: owner(),
        body_generation: 9,
        sequence,
        not_before_unix_ms: now.saturating_sub(1),
        expires_unix_ms: now + 20_000,
        context,
        signature: [0; 64],
    };
    resign(&mut result);
    result
}

fn resign(publication: &mut SignedMemoryRetrievalContextV1) {
    // Reproducible public test seeds are not product authority keys.
    publication.signature = SigningKey::from_bytes(&[2; 32])
        .sign(&publication.signing_bytes())
        .to_bytes();
}

struct FixtureOwner {
    frontier: Mutex<MemoryRetrievalFrontierV1>,
    unavailable: AtomicBool,
    wrong_challenge: AtomicBool,
    wrong_key: AtomicBool,
}

impl FixtureOwner {
    fn new(publication: &SignedMemoryRetrievalContextV1) -> Self {
        Self {
            frontier: Mutex::new(MemoryRetrievalFrontierV1 {
                owner: publication.owner.clone(),
                body_generation: publication.body_generation,
                authority_epoch: publication.context.generation_vector.authority_epoch,
                sequence: publication.sequence,
                publication_digest: Some(publication.publication_digest()),
                expires_unix_ms: 0,
                challenge: [0; 32],
                signature: [0; 64],
            }),
            unavailable: AtomicBool::new(false),
            wrong_challenge: AtomicBool::new(false),
            wrong_key: AtomicBool::new(false),
        }
    }

    fn publish(&self, publication: &SignedMemoryRetrievalContextV1) {
        let mut frontier = self.frontier.lock().expect("fixture mutex");
        frontier.authority_epoch = publication.context.generation_vector.authority_epoch;
        frontier.sequence = publication.sequence;
        frontier.publication_digest = Some(publication.publication_digest());
    }

    fn revoke(&self) {
        let mut frontier = self.frontier.lock().expect("fixture mutex");
        frontier.sequence += 1;
        frontier.publication_digest = None;
    }
}

impl MemoryRetrievalFrontierOwnerV1 for FixtureOwner {
    fn observe(
        &self,
        _: &AgentId,
        _: u64,
        challenge: [u8; 32],
    ) -> Result<MemoryRetrievalFrontierV1, String> {
        if self.unavailable.load(Ordering::SeqCst) {
            return Err("fixture owner unavailable".to_string());
        }
        let mut result = self.frontier.lock().expect("fixture mutex").clone();
        result.challenge = challenge;
        if self.wrong_challenge.load(Ordering::SeqCst) {
            result.challenge[0] ^= 1;
        }
        result.expires_unix_ms = now_ms()? + 10_000;
        let seed = if self.wrong_key.load(Ordering::SeqCst) {
            [4; 32]
        } else {
            [3; 32]
        };
        result.signature = SigningKey::from_bytes(&seed)
            .sign(&result.signing_bytes())
            .to_bytes();
        Ok(result)
    }
}

fn provider(frontier: Arc<FixtureOwner>) -> LeasedMemoryRetrievalProviderV1 {
    LeasedMemoryRetrievalProviderV1::new(
        owner(),
        9,
        SigningKey::from_bytes(&[2; 32]).verifying_key().to_bytes(),
        SigningKey::from_bytes(&[3; 32]).verifying_key().to_bytes(),
        frontier,
        30_000,
    )
    .expect("provider")
}

fn fixture() -> (
    SignedMemoryRetrievalContextV1,
    Arc<FixtureOwner>,
    LeasedMemoryRetrievalProviderV1,
) {
    let publication = publication(1);
    let frontier = Arc::new(FixtureOwner::new(&publication));
    let provider = provider(Arc::clone(&frontier));
    (publication, frontier, provider)
}

#[test]
fn cold_start_never_mints_or_recovers_context_implicitly() {
    let (_, _, provider) = fixture();
    assert!(provider.current(&owner(), 9).is_err());
}

#[test]
fn signed_publication_reaches_the_existing_current_context_port() {
    let (publication, _, provider) = fixture();
    let expected = publication.context.clone();
    provider.install(publication).expect("install");
    assert_eq!(provider.current(&owner(), 9).expect("current"), expected);
}

#[test]
fn publication_tampering_and_forged_key_are_rejected() {
    let (mut publication, _, provider) = fixture();
    publication.context.objective_digest = digest("tampered-objective");
    assert!(provider.install(publication.clone()).is_err());
    publication.signature = SigningKey::from_bytes(&[5; 32])
        .sign(&publication.signing_bytes())
        .to_bytes();
    assert!(provider.install(publication).is_err());
}

#[test]
fn owner_and_body_substitution_fail_closed() {
    let (publication, _, provider) = fixture();
    provider.install(publication).expect("install");
    let other = AgentId::parse("00000000-0000-4000-8000-000000000732").expect("other");
    assert!(provider.current(&other, 9).is_err());
    assert!(provider.current(&owner(), 10).is_err());
}

#[test]
fn valid_frontier_signature_for_another_challenge_is_rejected() {
    let (publication, frontier, provider) = fixture();
    frontier.wrong_challenge.store(true, Ordering::SeqCst);
    assert!(provider.install(publication).is_err());
}

#[test]
fn forged_frontier_key_is_rejected() {
    let (publication, frontier, provider) = fixture();
    frontier.wrong_key.store(true, Ordering::SeqCst);
    assert!(provider.install(publication).is_err());
}

#[test]
fn unavailable_frontier_never_falls_back_to_cached_context() {
    let (publication, frontier, provider) = fixture();
    provider.install(publication).expect("install");
    frontier.unavailable.store(true, Ordering::SeqCst);
    assert!(provider.current(&owner(), 9).is_err());
}

#[test]
fn rotation_invalidates_inflight_binding_until_new_publication_is_installed() {
    let (first, frontier, provider) = fixture();
    provider.install(first.clone()).expect("first");
    let second = publication(2);
    frontier.publish(&second);
    assert!(provider.current(&owner(), 9).is_err());
    provider.install(second.clone()).expect("second");
    assert_eq!(
        provider.current(&owner(), 9).expect("current"),
        second.context
    );
    assert!(provider.install(first).is_err());
}

#[test]
fn signed_same_sequence_payload_drift_is_not_idempotence() {
    let (first, frontier, provider) = fixture();
    provider.install(first.clone()).expect("first");
    let mut conflicting = first;
    conflicting.context.objective_digest = digest("changed-objective");
    resign(&mut conflicting);
    frontier.publish(&conflicting);
    assert!(provider.install(conflicting).is_err());
    assert!(provider.current(&owner(), 9).is_err());
}

#[test]
fn revocation_survives_provider_restart_via_fresh_owner_challenge() {
    let (first, frontier, original) = fixture();
    original.install(first.clone()).expect("first");
    frontier.revoke();
    assert!(original.current(&owner(), 9).is_err());
    let restarted = provider(Arc::clone(&frontier));
    assert!(restarted.install(first).is_err());
    let third = publication(3);
    frontier.publish(&third);
    restarted
        .install(third.clone())
        .expect("recovery from current owner");
    assert_eq!(
        restarted.current(&owner(), 9).expect("current"),
        third.context
    );
}

#[test]
fn idempotent_install_does_not_extend_monotonic_lease() {
    let (publication, _, provider) = fixture();
    provider.install(publication.clone()).expect("install");
    let original = provider
        .state
        .lock()
        .expect("mutex")
        .pinned
        .as_ref()
        .expect("pinned")
        .installed_at;
    provider.install(publication.clone()).expect("idempotence");
    assert_eq!(
        provider
            .state
            .lock()
            .expect("mutex")
            .pinned
            .as_ref()
            .expect("pinned")
            .installed_at,
        original
    );
    provider
        .state
        .lock()
        .expect("mutex")
        .pinned
        .as_mut()
        .expect("pinned")
        .remaining = Duration::ZERO;
    provider
        .install(publication)
        .expect("idempotence does not renew");
    assert!(provider.current(&owner(), 9).is_err());
}

#[test]
fn expired_publication_is_rejected_even_with_valid_signature() {
    let (mut publication, frontier, provider) = fixture();
    let now = now_ms().expect("clock");
    publication.not_before_unix_ms = now - 100;
    publication.expires_unix_ms = now - 1;
    resign(&mut publication);
    frontier.publish(&publication);
    assert!(provider.install(publication).is_err());
}

#[test]
fn backwards_wall_clock_invalidates_cached_context() {
    let (publication, _, provider) = fixture();
    provider.install(publication).expect("install");
    provider.state.lock().expect("mutex").last_wall_ms = u64::MAX;
    assert!(provider.current(&owner(), 9).is_err());
    assert!(provider.state.lock().expect("mutex").pinned.is_none());
}

#[test]
fn concurrent_reads_keep_one_exact_context_identity() {
    let (publication, _, provider) = fixture();
    let expected = publication.context.binding_digest();
    provider.install(publication).expect("install");
    let provider = Arc::new(provider);
    let threads = (0..8)
        .map(|_| {
            let provider = Arc::clone(&provider);
            std::thread::spawn(move || {
                provider
                    .current(&owner(), 9)
                    .expect("current")
                    .binding_digest()
            })
        })
        .collect::<Vec<_>>();
    for thread in threads {
        assert_eq!(thread.join().expect("join"), expected);
    }
}

#[test]
fn expired_request_cannot_install_or_reuse_a_signed_publication() {
    let (publication, _frontier, provider) = fixture();
    let expired = Instant::now();
    assert!(
        provider
            .install_and_acquire_before(publication, &owner(), 9, expired)
            .is_err()
    );
    assert!(
        provider
            .acquire_context_before(&owner(), 9, expired)
            .is_err()
    );
}
