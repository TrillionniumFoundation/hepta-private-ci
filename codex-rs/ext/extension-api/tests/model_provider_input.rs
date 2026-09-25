#![allow(clippy::expect_used)]

use codex_extension_api::EPHEMERAL_MODEL_INPUT_MAX_CONTENT_BYTES;
use codex_extension_api::EPHEMERAL_MODEL_INPUT_MAX_CONTENT_TOKENS;
use codex_extension_api::EPHEMERAL_MODEL_INPUT_SCHEMA_VERSION;
use codex_extension_api::EphemeralModelInputProposal;
use codex_extension_api::EphemeralModelInputSource;
use codex_extension_api::ModelProviderSha256Digest;
use pretty_assertions::assert_eq;

fn digest(byte: char) -> ModelProviderSha256Digest {
    ModelProviderSha256Digest::parse(byte.to_string().repeat(64))
        .expect("test digest should be valid")
}

fn expect_invalid(
    result: Result<EphemeralModelInputProposal, codex_extension_api::ModelProviderPolicyError>,
) -> codex_extension_api::ModelProviderPolicyError {
    match result {
        Err(error) => error,
        Ok(_) => panic!("proposal should be rejected"),
    }
}

#[test]
fn source_identity_is_bounded_and_canonical() {
    assert_eq!(
        EphemeralModelInputSource::parse("hepta_memory_same_thread_v1")
            .expect("source")
            .as_str(),
        "hepta_memory_same_thread_v1"
    );

    for invalid in ["", "Hepta", "hepta/memory", &"a".repeat(65)] {
        let error = EphemeralModelInputSource::parse(invalid)
            .expect_err("non-canonical source should be rejected");
        assert_eq!(error.reason_code(), "ephemeral_model_input_source_invalid");
    }
}

#[test]
fn proposal_preserves_exact_physical_send_binding_until_consumed() {
    let proposal = EphemeralModelInputProposal::new(
        EphemeralModelInputSource::parse("hepta_memory_same_thread_v1").expect("source"),
        "attempt-1",
        digest('a'),
        "thread-1",
        "turn-1",
        digest('b'),
        digest('c'),
        "bounded memory summary",
        6,
    )
    .expect("proposal");

    assert_eq!(
        proposal.schema_version(),
        EPHEMERAL_MODEL_INPUT_SCHEMA_VERSION
    );
    assert_eq!(proposal.source().as_str(), "hepta_memory_same_thread_v1");
    assert_eq!(proposal.attempt_id(), "attempt-1");
    assert_eq!(
        proposal.base_logical_request_sha256().as_str(),
        "a".repeat(64)
    );
    assert_eq!(proposal.thread_id(), "thread-1");
    assert_eq!(proposal.turn_id(), "turn-1");
    assert_eq!(proposal.source_binding_sha256().as_str(), "b".repeat(64));
    assert_eq!(proposal.content_sha256().as_str(), "c".repeat(64));
    assert_eq!(proposal.claimed_token_count(), 6);
    assert_eq!(proposal.into_content(), "bounded memory summary");
}

#[test]
fn proposal_constructor_rejects_empty_or_over_hard_bounds() {
    let proposal =
        |attempt: &str, thread: &str, turn: &str, content: String, claimed_token_count| {
            EphemeralModelInputProposal::new(
                EphemeralModelInputSource::parse("source").expect("source"),
                attempt,
                digest('a'),
                thread,
                turn,
                digest('b'),
                digest('c'),
                content,
                claimed_token_count,
            )
        };

    for error in [
        expect_invalid(proposal("", "thread-1", "turn-1", "content".to_string(), 1)),
        expect_invalid(proposal(
            "attempt-1",
            "",
            "turn-1",
            "content".to_string(),
            1,
        )),
        expect_invalid(proposal(
            "attempt-1",
            "thread-1",
            "",
            "content".to_string(),
            1,
        )),
        expect_invalid(proposal(
            "attempt-1",
            "thread-1",
            "turn-1",
            String::new(),
            1,
        )),
        expect_invalid(proposal(
            "attempt-1",
            "thread-1",
            "turn-1",
            "x".repeat(EPHEMERAL_MODEL_INPUT_MAX_CONTENT_BYTES as usize + 1),
            1,
        )),
        expect_invalid(proposal(
            "attempt-1",
            "thread-1",
            "turn-1",
            "content".to_string(),
            0,
        )),
        expect_invalid(proposal(
            "attempt-1",
            "thread-1",
            "turn-1",
            "content".to_string(),
            EPHEMERAL_MODEL_INPUT_MAX_CONTENT_TOKENS + 1,
        )),
    ] {
        assert_eq!(
            error.reason_code(),
            "ephemeral_model_input_proposal_invalid"
        );
    }

    let boundary = proposal(
        "attempt-1",
        "thread-1",
        "turn-1",
        "x".repeat(EPHEMERAL_MODEL_INPUT_MAX_CONTENT_BYTES as usize),
        EPHEMERAL_MODEL_INPUT_MAX_CONTENT_TOKENS,
    )
    .expect("exact hard bounds should remain valid");
    assert_eq!(
        boundary.into_content().len(),
        EPHEMERAL_MODEL_INPUT_MAX_CONTENT_BYTES as usize
    );
}
