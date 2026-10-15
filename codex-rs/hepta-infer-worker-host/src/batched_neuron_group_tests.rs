use super::*;

use std::cell::Cell;
use std::collections::BTreeSet;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_infer_core::microbatch::MicrobatchKeyV1;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use crate::model_worker::WorkerRequest;
use crate::model_worker::canonical_neuron_feature_payload_digest_with_slice;

fn digest(label: &[u8]) -> Digest32 {
    Digest32::of_bytes(label)
}

fn id(label: &str) -> StableId {
    StableId::new(label).expect("bounded original Worker identity")
}

fn fixture() -> (
    MicrobatchKeyV1,
    NeuronFeatureRequest,
    NeuronFeatureRequest,
    SharedFeatureBufferV1,
) {
    let model_digest = digest(b"one actual loaded model");
    let key = MicrobatchKeyV1 {
        scope_id: id("scope.original.1"),
        model_digest,
        generation: Generation::new(3).expect("original Worker generation"),
        route_fence: 71,
        authority_epoch: 9,
    };
    let feature = SharedFeatureBufferV1::from_vec(vec![0, 1_i64 << 24])
        .expect("one original Q24 Arc");
    let mut first = NeuronFeatureRequest {
        authorization: WorkerRequest {
            request_id: "request.one".to_string(),
            reservation_id: "reservation.one".to_string(),
            model_digest: model_digest.to_string(),
            payload_digest: String::new(),
            maximum_tokens: 8,
            deadline_ms: 9000,
            lease_payload_digest: String::new(),
            reservation_model_digest: model_digest.to_string(),
            reservation_maximum_tokens: 8,
            cancelled: false,
        },
        encoder_digest: digest(b"pipeline").to_string(),
        head_digest: digest(b"first head identity").to_string(),
        weights_digest: digest(b"shared loaded weights").to_string(),
        input_digest: digest(b"original scoped stem input").to_string(),
        feature_vector_q24: Vec::new(),
        expected_output_width: 3,
    };
    let exact = canonical_neuron_feature_payload_digest_with_slice(
        &first,
        feature.as_slice(),
    );
    first.authorization.payload_digest = exact.clone();
    first.authorization.lease_payload_digest = exact;
    let mut second = first.clone();
    second.authorization.request_id = "request.two".to_string();
    second.authorization.reservation_id = "reservation.two".to_string();
    (key, first, second, feature)
}

fn prepare<'a>(
    first_key: &'a MicrobatchKeyV1,
    second_key: &'a MicrobatchKeyV1,
    first: &'a NeuronFeatureRequest,
    second: &'a NeuronFeatureRequest,
    feature: &'a SharedFeatureBufferV1,
) -> Result<NonAuthorizingNativeBatchGroupV1, BatchWorkerErrorV1> {
    prepare_original_native_batch_group_v1(
        "worker.original",
        "model.original",
        &[
            NativeBatchGroupMemberV1 {
                key: first_key,
                request: first,
                feature,
            },
            NativeBatchGroupMemberV1 {
                key: second_key,
                request: second,
                feature,
            },
        ],
    )
}

#[test]
fn original_native_group_is_order_sensitive_and_binds_each_real_original_request() {
    let (key, first, second, feature) = fixture();
    let cohort = prepare(&key, &key, &first, &second, &feature)
        .expect("two valid original-member bindings");
    let reversed = prepare(&key, &key, &second, &first, &feature)
        .expect("second ordered signed group");
    assert_eq!(cohort.member_bindings.len(), 2);
    assert_eq!(
        cohort.group_binding.request_sha256,
        cohort.ordered_digest.into_array(),
    );
    assert_ne!(cohort.ordered_digest, reversed.ordered_digest);
    assert_ne!(
        cohort.group_binding.request_sha256,
        reversed.group_binding.request_sha256,
    );
    assert_eq!(
        cohort.group_binding.scope_sha256,
        reversed.group_binding.scope_sha256,
        "the same exact Scope cohort is eligible but ORDERED requests differ",
    );
    assert_eq!(
        cohort.member_bindings[0].payload_sha256,
        cohort.member_bindings[1].payload_sha256,
        "numeric Q24 model payload is shared",
    );
    assert_ne!(
        cohort.member_bindings[0].request_sha256,
        cohort.member_bindings[1].request_sha256,
        "the original member FinalUseBinding still includes each request and reservation",
    );
    assert!(!cohort.authority.grants_any());
}

#[test]
fn original_native_group_rejects_duplicate_cohort_or_changed_q24_without_nonce() {
    let (key, first, second, feature) = fixture();
    let same_request = prepare(&key, &key, &first, &first, &feature);
    assert_eq!(same_request, Err(BatchWorkerErrorV1::InvalidBinding));

    let mut same_reservation = second.clone();
    same_reservation.authorization.reservation_id =
        first.authorization.reservation_id.clone();
    assert_eq!(
        prepare(&key, &key, &first, &same_reservation, &feature),
        Err(BatchWorkerErrorV1::InvalidBinding),
    );

    let mutated = SharedFeatureBufferV1::from_vec(vec![0, (1_i64 << 24) + 1])
        .expect("valid altered Q24 Arc");
    assert_eq!(
        prepare(&key, &key, &first, &second, &mutated),
        Err(BatchWorkerErrorV1::InvalidBinding),
    );
    let mut incompatible = key.clone();
    incompatible.model_digest = digest(b"different physical model");
    assert_eq!(
        prepare(&key, &incompatible, &first, &second, &feature),
        Err(BatchWorkerErrorV1::InvalidBinding),
    );
    let mut stale = key.clone();
    stale.route_fence = 0;
    assert_eq!(
        prepare(&key, &stale, &first, &second, &feature),
        Err(BatchWorkerErrorV1::InvalidBinding),
    );
    let mut double_source = second.clone();
    double_source.feature_vector_q24 = feature.as_slice().to_vec();
    assert_eq!(
        prepare(&key, &key, &first, &double_source, &feature),
        Err(BatchWorkerErrorV1::InvalidBinding),
    );
}

#[test]
fn original_native_group_binds_distinct_scope_and_cns_route_into_aggregate_signature() {
    let (key, first, second, feature) = fixture();
    let mut second_key = key.clone();
    second_key.scope_id = id("scope.original.2");
    second_key.route_fence += 1;
    let separate = prepare(&key, &second_key, &first, &second, &feature)
        .expect("distinct Scope and CNS fences remain individually signed");
    let same = prepare(&key, &key, &first, &second, &feature)
        .expect("same scope also permitted under original physical model");
    assert_ne!(
        separate.group_binding.scope_sha256,
        same.group_binding.scope_sha256,
    );
    assert_ne!(
        separate.group_binding.request_sha256,
        same.group_binding.request_sha256,
    );
    assert_ne!(
        separate.member_bindings[1].scope_sha256,
        same.member_bindings[1].scope_sha256,
    );
    assert!(!separate.authority.grants_any());
}

fn signed(
    signer: &SigningKey,
    binding: FinalUseBinding,
    grant_id: &str,
    nonce: u8,
) -> SignedFinalUseGrant {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("trusted test Unix clock")
        .as_millis() as u64;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "original.group.security-owner".to_string(),
        authority_epoch: 9,
        grant_id: grant_id.to_string(),
        nonce: [nonce; 32],
        binding,
        not_before_unix_ms: now.saturating_sub(1000),
        expires_at_unix_ms: now + 30_000,
    };
    let signature = signer
        .sign(&grant.signing_bytes().expect("exact canonical signature bytes"))
        .to_bytes()
        .to_vec();
    SignedFinalUseGrant { grant, signature }
}

fn authority(
    signer: &SigningKey,
    directory: &tempfile::TempDir,
) -> FinalUseAuthority {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(
            directory.path(),
            std::fs::Permissions::from_mode(0o700),
        )
        .expect("private durable FinalUse nonce journal directory");
    }
    FinalUseAuthority::open_state_dir(
        directory.path(),
        "original.group.security-owner".to_string(),
        signer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("ONE original persistent FinalUse owner, no substitute")
}

#[test]
fn original_native_group_real_signature_claims_entire_cohort_in_one_nonce_commit() {
    let (key, first, second, feature) = fixture();
    let cohort = prepare(&key, &key, &first, &second, &feature)
        .expect("exact frozen ordered cohort");
    let signer = SigningKey::from_bytes(&[83; 32]);
    let directory = tempfile::tempdir().expect("test nonce journal");
    let owner = authority(&signer, &directory);
    let group = signed(
        &signer,
        cohort.group_binding.clone(),
        "original-ordered-group",
        95,
    );
    let first_signed = signed(
        &signer,
        cohort.member_bindings[0].clone(),
        "head-one",
        96,
    );
    let second_signed = signed(
        &signer,
        cohort.member_bindings[1].clone(),
        "head-two",
        97,
    );
    let all = [
        (&group, &cohort.group_binding),
        (&first_signed, &cohort.member_bindings[0]),
        (&second_signed, &cohort.member_bindings[1]),
    ];
    let verified = owner
        .claim_batch(&all)
        .expect("one atomic original nonce-journal claim for group plus members");
    assert_eq!(verified.len(), 3);
    let expected = vec![
        cohort.group_binding.clone(),
        cohort.member_bindings[0].clone(),
        cohort.member_bindings[1].clone(),
    ];
    let entries = verified.into_iter().zip(expected).collect::<Vec<_>>();
    let invokes = Cell::new(0_u32);
    let observed = owner
        .with_verified_effect_batch(entries, || {
            // Deterministic synchronous TEST callback. It is not a second
            // physical driver or claim of a production Stem inference.
            invokes.set(invokes.get() + 1);
            assert_eq!(
                owner.update_revocations(FinalUseRevocations {
                    authority_epoch: 9,
                    revision: 2,
                    revoked_grant_ids: BTreeSet::new(),
                }),
                Err(FinalUseError::DispatchInProgress)
            );
            19
        })
        .expect("three independently signed entries fenced together");
    assert_eq!(observed, 19);
    assert_eq!(invokes.get(), 1);
    assert_eq!(
        owner.claim_batch(&all).err(),
        Some(FinalUseError::AlreadyClaimed),
        "neither the group nonce nor any member nonce is ever refunded",
    );
}

#[test]
fn original_native_group_rejects_valid_but_wrong_order_group_before_burning_any_nonce() {
    let (key, first, second, feature) = fixture();
    let selected = prepare(&key, &key, &first, &second, &feature)
        .expect("original ordered group");
    let reversed = prepare(&key, &key, &second, &first, &feature)
        .expect("other order requires another independent grant");
    let signer = SigningKey::from_bytes(&[84; 32]);
    let dir = tempfile::tempdir().expect("nonce journal");
    let owner = authority(&signer, &dir);

    // The signature is REAL and correct for the reversed group, but cannot
    // authorize the originally selected cohort. None of its 3 nonces should
    // be consumed on binding disagreement.
    let wrong_group = signed(
        &signer,
        reversed.group_binding,
        "other-batch-order",
        101,
    );
    let first_signed = signed(
        &signer,
        selected.member_bindings[0].clone(),
        "head-one",
        102,
    );
    let second_signed = signed(
        &signer,
        selected.member_bindings[1].clone(),
        "head-two",
        103,
    );
    let wrong = [
        (&wrong_group, &selected.group_binding),
        (&first_signed, &selected.member_bindings[0]),
        (&second_signed, &selected.member_bindings[1]),
    ];
    assert_eq!(
        owner.claim_batch(&wrong).err(),
        Some(FinalUseError::BindingMismatch),
    );

    let right_group = signed(
        &signer,
        selected.group_binding.clone(),
        "original-batch-order",
        101,
    );
    let corrected = [
        (&right_group, &selected.group_binding),
        (&first_signed, &selected.member_bindings[0]),
        (&second_signed, &selected.member_bindings[1]),
    ];
    assert_eq!(
        owner.claim_batch(&corrected).map(|tokens| tokens.len()),
        Ok(3),
        "invalid cross-group reassembly did not consume the durable nonce set",
    );
}
