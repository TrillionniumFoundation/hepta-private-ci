use super::*;

fn unrelated_successor() -> Result<VerifiedAdmissionSnapshotSuccessorV2, ProviderRequestProofErrorV2>
{
    let predecessor = verify_admission_snapshot_v2(
        snapshot(
            "snapshot:other-root",
            /*observed_unix_ms*/ 10,
            /*revocation_epoch*/ 1,
            /*predecessor*/ None,
            Vec::new(),
        ),
        &AdmissionVerifier,
    )?;
    verify_typed_admission_snapshot_successor_v2(
        snapshot(
            "snapshot:other-successor",
            /*observed_unix_ms*/ 20,
            /*revocation_epoch*/ 2,
            Some(predecessor.snapshot_digest()),
            Vec::new(),
        ),
        &predecessor,
        &AdmissionVerifier,
    )
}

fn proof_for(
    fixture: &Fixture,
    final_request: &[u8],
    attachment_digest: Digest32,
    tokenizer: &FinalByteTokenizer,
) -> Result<ProviderFinalRequestProofV2, ProviderRequestProofErrorV2> {
    let selected_length = b"alpha".len();
    assert!(final_request.starts_with(b"alpha"));
    assert!(final_request.len() > selected_length);
    let segments = vec![
        segment(
            final_request,
            /*offset*/ 0,
            selected_length,
            ProviderRequestSegmentKindV2::SelectedContextItem {
                item_id: id("item:developer"),
                source_content_digest: digest("alpha"),
            },
        ),
        segment(
            final_request,
            selected_length,
            final_request.len() - selected_length,
            ProviderRequestSegmentKindV2::HostCanonicalMaterial {
                material_type: id("test-host-framing"),
                semantic_digest: digest("test-host-semantics"),
            },
        ),
    ];
    ProviderFinalRequestProofV2::from_exact_request(
        id("proof:profile-boundary"),
        attachment_digest,
        fixture
            .canonical
            .serialized_context()
            .receipt()
            .payload_digest(),
        fixture.canonical.coverage_digest(),
        digest("wire-semantic-request"),
        final_request,
        segments,
        &fixture.selected,
        tokenizer,
        /*prepared_at_unix_ms*/ 30,
    )
}

#[test]
fn typed_successor_must_extend_the_attachment_snapshot() -> Result<(), ProviderRequestProofErrorV2>
{
    let fixture = fixture();
    let unrelated = unrelated_successor()?;
    assert_ne!(
        unrelated.predecessor_snapshot_digest(),
        fixture.attachment.admission_snapshot_digest(),
    );
    assert_eq!(
        prepare_provider_bound_delivery_v2(
            &fixture.compiled,
            fixture.canonical.serialized_context(),
            &fixture.attachment,
            &profile(),
            &unrelated,
            exact_request_proof(&fixture),
            id("preparation:unrelated-parent"),
        ),
        Err(ProviderRequestProofErrorV2::SnapshotPredecessorMismatch),
    );
    let preparation = prepare_provider_bound_delivery_v2(
        &fixture.compiled,
        fixture.canonical.serialized_context(),
        &fixture.attachment,
        &profile(),
        &fixture.successor,
        exact_request_proof(&fixture),
        id("preparation:direct-parent"),
    )?;
    preparation.validate_for(
        &fixture.attachment,
        fixture.canonical.serialized_context(),
        &profile(),
    )?;
    Ok(())
}

#[test]
fn final_tokenizer_identity_must_match_both_profile_names()
-> Result<(), ProviderRequestProofErrorV2> {
    let fixture = fixture();
    for (provider, model) in [("provider-other", "model-a"), ("provider-a", "model-other")] {
        let proof = proof_for(
            &fixture,
            b"alpha framing",
            fixture.attachment.attachment_digest(),
            &FinalByteTokenizer {
                provider: provider.to_owned(),
                model: model.to_owned(),
            },
        )?;
        assert_eq!(
            proof.tokenization().tokenizer_identity().provider_id(),
            provider
        );
        assert_eq!(proof.tokenization().tokenizer_identity().model(), model);
        assert_eq!(
            prepare_provider_bound_delivery_v2(
                &fixture.compiled,
                fixture.canonical.serialized_context(),
                &fixture.attachment,
                &profile(),
                &fixture.successor,
                proof,
                id("preparation:identity-mismatch"),
            ),
            Err(ProviderRequestProofErrorV2::Context(
                ContextCompilerV2Error::ProviderModelProfileMismatch,
            )),
        );
    }
    let preparation = prepare_provider_bound_delivery_v2(
        &fixture.compiled,
        fixture.canonical.serialized_context(),
        &fixture.attachment,
        &profile(),
        &fixture.successor,
        exact_request_proof(&fixture),
        id("preparation:matching-identity"),
    )?;
    preparation.validate_for(
        &fixture.attachment,
        fixture.canonical.serialized_context(),
        &profile(),
    )?;
    Ok(())
}

#[test]
fn final_request_budget_counts_host_framing_at_the_profile_boundary()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = fixture();
    let profile = profile();
    let limit = usize::try_from(profile.maximum_context_tokens)?;
    let tokenizer = FinalByteTokenizer {
        provider: "provider-a".to_owned(),
        model: "model-a".to_owned(),
    };
    let mut final_request = b"alpha".to_vec();
    final_request.resize(limit, b' ');
    let proof = proof_for(
        &fixture,
        &final_request,
        fixture.attachment.attachment_digest(),
        &tokenizer,
    )?;
    assert_eq!(
        proof.tokenization().token_count(),
        profile.maximum_context_tokens
    );
    let preparation = prepare_provider_bound_delivery_v2(
        &fixture.compiled,
        fixture.canonical.serialized_context(),
        &fixture.attachment,
        &profile,
        &fixture.successor,
        proof,
        id("preparation:at-profile-budget"),
    )?;
    preparation.validate_for(
        &fixture.attachment,
        fixture.canonical.serialized_context(),
        &profile,
    )?;

    final_request.push(b' ');
    let proof = proof_for(
        &fixture,
        &final_request,
        fixture.attachment.attachment_digest(),
        &tokenizer,
    )?;
    assert_eq!(
        proof.tokenization().token_count(),
        profile.maximum_context_tokens + 1
    );
    assert_eq!(
        prepare_provider_bound_delivery_v2(
            &fixture.compiled,
            fixture.canonical.serialized_context(),
            &fixture.attachment,
            &profile,
            &fixture.successor,
            proof,
            id("preparation:over-profile-budget"),
        ),
        Err(ProviderRequestProofErrorV2::InvalidTokenCount),
    );
    Ok(())
}

#[test]
fn attachment_mismatch_still_precedes_the_new_parent_check()
-> Result<(), ProviderRequestProofErrorV2> {
    let fixture = fixture();
    let unrelated = unrelated_successor()?;
    let proof = proof_for(
        &fixture,
        b"alpha framing",
        digest("another-attachment"),
        &FinalByteTokenizer {
            provider: "provider-a".to_owned(),
            model: "model-a".to_owned(),
        },
    )?;
    assert_eq!(
        prepare_provider_bound_delivery_v2(
            &fixture.compiled,
            fixture.canonical.serialized_context(),
            &fixture.attachment,
            &profile(),
            &unrelated,
            proof,
            id("preparation:attachment-mismatch"),
        ),
        Err(ProviderRequestProofErrorV2::PreparationMismatch),
    );
    Ok(())
}
