use super::*;

use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_memory::sqlite_owner_cue_profile_digest;
use codex_hepta_memory::sqlite_owner_retrieval_policy_v1;
use codex_hepta_memory_retrieval::EngramDynamicsPolicyV1;
use codex_hepta_memory_retrieval::EngramSnapshotV1;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

fn owner() -> AgentId {
    AgentId::parse("00000000-0000-4000-8000-000000000961").unwrap()
}

fn context() -> RetrievalExecutionContextV1 {
    let policy = sqlite_owner_retrieval_policy_v1().unwrap();
    let external = Digest32::of_bytes(b"product-provider-test-only");
    let vector = LaneCGenerationVectorV1 {
        scope_id: StableId::new("scope:provider-test").unwrap(),
        purpose_id: StableId::new("purpose:provider-test").unwrap(),
        memory_ledger_frontier: 10,
        knowledge_fact_frontier: 8,
        tombstone_frontier: 4,
        source_ledger_frontier: 11,
        knowledge_graph_generation: Generation::new(2).unwrap(),
        compact_checkpoint_generation: Generation::new(1).unwrap(),
        prompt_registry_revision: Revision::new(1).unwrap(),
        retrieval_profile_digest: policy.digest(),
        encoder_preprocessor_digest: external,
        authority_epoch: 2,
        model_digest: external,
        tokenizer_digest: external,
        template_digest: external,
        tool_schema_digest: external,
    };
    let snapshot = EngramSnapshotV1::new(vector.digest(), external, Vec::new(), Vec::new()).unwrap();
    let context = RetrievalExecutionContextV1 {
        generation_vector: vector,
        objective_digest: external,
        approved_context_digest: external,
        cue_profile_digest: sqlite_owner_cue_profile_digest(),
        retrieval_policy: policy,
        engram_snapshot: snapshot,
        dynamics_policy: EngramDynamicsPolicyV1::product_default().unwrap(),
    };
    context.validate().unwrap();
    context
}

fn product() -> (Arc<dyn CurrentMemoryRetrievalContext>, ProductRetrievalContextControlV1) {
    <dyn CurrentMemoryRetrievalContext>::product_with_control(owner(), 1, context(), now_unix_ms().unwrap() + 120_000).unwrap()
}

struct Witness(ProductRetrievalContextSnapshotV1);
impl RetrievalRecoveryWitnessV1 for Witness {
    fn latest_state(&self, owner: &AgentId, body: u64) -> Result<(u64, Digest32), String> {
        if owner != &self.0.owner || body != self.0.body_generation {
            return Err("wrong witness owner".to_string());
        }
        Ok((self.0.epoch, self.0.state_digest))
    }
}

#[test]
fn product_reader_has_no_lifecycle_write_capability() {
    let (reader, _) = product();
    assert!(reader.rotate_context(1, context(), now_unix_ms().unwrap() + 120_000).is_err());
    assert!(reader.renew_context(1, now_unix_ms().unwrap() + 120_000).is_err());
    assert!(reader.revoke_context(1).is_err());
    assert!(reader.current(&owner(), 1).is_ok());
}

#[test]
fn same_payload_rotation_and_renewal_change_read_binding() {
    let (reader, control) = product();
    let first = reader.acquire_context(&owner(), 1).unwrap();
    let lease = first.2.unwrap();
    assert_eq!(control.rotate(1, first.0.clone(), lease).unwrap(), 2);
    let second = reader.acquire_context(&owner(), 1).unwrap();
    assert_eq!(first.0, second.0);
    assert_ne!(first.1, second.1);
    assert_eq!(control.renew(2, lease).unwrap(), 3);
    assert_ne!(second.1, reader.acquire_context(&owner(), 1).unwrap().1);
}

#[test]
fn owner_body_and_epoch_substitution_fail_closed() {
    let (reader, control) = product();
    let other = AgentId::parse("00000000-0000-4000-8000-000000000962").unwrap();
    assert!(reader.current(&other, 1).is_err());
    assert!(reader.current(&owner(), 2).is_err());
    assert!(control.renew(2, now_unix_ms().unwrap() + 120_000).is_err());
    assert_eq!(reader.lifecycle_epoch().unwrap(), 1);
}

#[test]
fn revoke_is_terminal_and_retry_is_idempotent() {
    let (reader, control) = product();
    assert_eq!(control.revoke(1).unwrap(), 2);
    assert_eq!(control.revoke(1).unwrap(), 2);
    assert_eq!(control.revoke(2).unwrap(), 2);
    assert!(reader.current(&owner(), 1).is_err());
    assert!(control.rotate(2, context(), now_unix_ms().unwrap() + 120_000).is_err());
    assert!(control.renew(2, now_unix_ms().unwrap() + 120_000).is_err());
    assert!(control.snapshot().unwrap().revoked);
}

#[test]
fn monotonic_expiry_cannot_be_renewed_back_to_life() {
    let (reader, control) = product();
    control.provider.state.write().unwrap().monotonic_deadline = Instant::now();
    assert!(reader.current(&owner(), 1).is_err());
    assert!(control.renew(1, now_unix_ms().unwrap() + 120_000).is_err());
    // Revocation remains available after expiry.
    assert_eq!(control.revoke(1).unwrap(), 2);
}

#[test]
fn backward_wall_clock_is_not_a_valid_lease() {
    let (reader, control) = product();
    control.provider.state.write().unwrap().acquired_wall_ms = u64::MAX;
    assert!(reader.current(&owner(), 1).is_err());
}

#[test]
fn historical_self_hash_does_not_authorize_recovery() {
    let (_, control) = product();
    let old = control.snapshot().unwrap();
    control.revoke(1).unwrap();
    let witness = Witness(control.snapshot().unwrap());
    assert!(<dyn CurrentMemoryRetrievalContext>::recover_product_with_witness(old.clone(), &witness).is_err());
    assert!(<dyn CurrentMemoryRetrievalContext>::recover_product(old.owner, old.body_generation, old.epoch, old.lease_expires_unix_ms, old.context, old.revoked, old.state_digest).is_err());
}

#[test]
fn recovery_preserves_current_revocation_and_validates_exact_state() {
    let (_, control) = product();
    control.revoke(1).unwrap();
    let snapshot = control.snapshot().unwrap();
    let witness = Witness(snapshot.clone());
    let (reader, recovered_control) = <dyn CurrentMemoryRetrievalContext>::recover_product_with_witness(snapshot.clone(), &witness).unwrap();
    assert!(reader.current(&owner(), 1).is_err());
    assert_eq!(recovered_control.snapshot().unwrap(), snapshot);
    let mut tampered = snapshot;
    tampered.epoch += 1;
    assert!(<dyn CurrentMemoryRetrievalContext>::recover_product_with_witness(tampered, &witness).is_err());
}

#[test]
fn lease_bounds_and_invalid_generations_fail_before_publication() {
    let now = now_unix_ms().unwrap();
    for deadline in [0, now, now + MAX_LEASE_MS + 10_000] {
        assert!(<dyn CurrentMemoryRetrievalContext>::product(owner(), 1, context(), deadline).is_err());
    }
    assert!(<dyn CurrentMemoryRetrievalContext>::product(owner(), 0, context(), now + 120_000).is_err());
}

#[test]
fn concurrent_control_writers_have_one_epoch_winner() {
    let (reader, control) = product();
    let control = Arc::new(control);
    let barrier = Arc::new(std::sync::Barrier::new(8));
    let mut threads = Vec::new();
    for _ in 0..8 {
        let control = Arc::clone(&control);
        let barrier = Arc::clone(&barrier);
        threads.push(std::thread::spawn(move || {
            barrier.wait();
            control.renew(1, now_unix_ms().unwrap() + 120_000).is_ok()
        }));
    }
    let winners = threads.into_iter().map(|thread| usize::from(thread.join().unwrap())).sum::<usize>();
    assert_eq!(winners, 1);
    assert_eq!(reader.lifecycle_epoch().unwrap(), 2);
}
