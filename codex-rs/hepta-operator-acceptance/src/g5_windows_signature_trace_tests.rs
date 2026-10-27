use super::*;
use crate::windows_signature_trace;
use serde_json::json;

#[test]
#[ignore = "manual Windows metadata collector; not a functional qualification"]
fn records_original_detached_signature_identity() {
    let fixture = TrustFixture::new(/*revoked*/ false);
    let challenge_path = fixture.root.join("g5-challenge.json");
    prepare_g5_challenge(G5PrepareRequest {
        challenge_path: &challenge_path,
        candidate: candidate(),
        evidence: evidence(),
        lifetime_seconds: 120,
        now_unix_seconds: 1_000,
        trust: fixture.inputs(),
    })
    .expect("prepare original challenge");
    let signature = fixture.sign(&challenge_path);
    let before = windows_signature_trace::inspect(&signature);
    let assessed = assess_g5_challenge(G5AssessRequest {
        assessment_path: None,
        challenge_path: &challenge_path,
        expected_candidate: candidate(),
        expected_evidence: evidence(),
        now_unix_seconds: 1_001,
        signature: G5SignatureInput::Detached(&signature),
        trust: fixture.inputs(),
    });
    let facts = json!({
        "schema": "hepta.windows-original-signature-metadata.v1",
        "original_case": "g5_trust::tests::independently_signed_challenge_is_verified_but_not_accepted",
        "collection_is_not_functional_qualification": true,
        "namespace": SSHSIG_NAMESPACE,
        "fixture_signer": openssh_keygen(),
        "challenge_sha256": sha256(&std::fs::read(&challenge_path).expect("original challenge bytes")),
        "effective_token": windows_signature_trace::effective_token(),
        "generated_signature_before": before,
        "original_assess": {"ok": assessed.is_ok(), "result": format!("{assessed:?}")},
        "generated_signature_after": windows_signature_trace::inspect(&signature),
        "private_allowed_signers_control": windows_signature_trace::inspect(&fixture.allowed_signers),
        "private_policy_control": windows_signature_trace::inspect(&fixture.policy)
    });
    windows_signature_trace::save("g5-signature-original.json", facts)
        .expect("save actual original G5 signature metadata");
}
