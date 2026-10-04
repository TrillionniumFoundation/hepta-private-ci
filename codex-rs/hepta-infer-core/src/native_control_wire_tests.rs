//! Golden controls for unchanged native journal and abort digest encodings.

use super::*;

#[test]
fn dispatch_event_preserves_original_json_bytes() -> Result<(), Box<dyn std::error::Error>> {
    let payload = dispatch();
    let expected = format!(
        "{{\"Dispatch\":{{\"request_id\":\"request-wire\",\"dispatch\":{},\"terminal_owner\":null}}}}",
        serde_json::to_string(&payload)?,
    );
    let event = Event::Dispatch {
        request_id: "request-wire".to_owned(),
        dispatch: payload.into(),
        terminal_owner: None,
    };
    assert_eq!(serde_json::to_string(&event)?, expected);
    let restored: Event = serde_json::from_str(&expected)?;
    assert_eq!(serde_json::to_string(&restored)?, expected);
    Ok(())
}

#[test]
fn abort_commitment_and_proof_preserve_length_prefixed_digest_bytes() -> Result<(), Error> {
    let token = NativePreEffectAbortToken {
        request_id: "request-wire".to_owned(),
        dispatch_revision: 1,
        abort_nonce: [42; 32],
    };
    let binding = "b".repeat(64);
    assert_eq!(
        token.commitment_digest("owner-run", &binding)?,
        "dd48470d4626640e6c4f6cf492044140d6f40086b324c3e60412d8617b03ee04"
    );
    let proof = token.proof_record(
        "owner-run".to_owned(),
        /*owner_dispatch_revision*/ 1,
        binding,
        "cancelled".to_owned(),
    )?;
    assert_eq!(
        proof.proof_digest,
        "c01d6bd1a2fd6acdcb40acdbe7e8e533a40e2eaa2b83067ff73dd283a21bedcb"
    );
    Ok(())
}
