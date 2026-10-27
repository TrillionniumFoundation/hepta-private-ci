use super::*;
use crate::windows_signature_trace;
use serde_json::json;

#[test]
#[ignore = "manual Windows metadata collector; not a functional qualification"]
fn records_original_detached_signature_identity() {
    let fixture = TrustFixture::new();
    let anchor = fixture.load_anchor();
    let statement = b"canonical operator acceptance statement";
    let signature = fixture.sign(statement, SSHSIG_NAMESPACE, "accepted");
    let before = windows_signature_trace::inspect(&signature);
    let verified = anchor.verify(statement, &signature);
    let facts = json!({
        "schema": "hepta.windows-original-signature-metadata.v1",
        "original_case": "trust::tests::sshsig_verifies_only_exact_namespace_against_pinned_policy",
        "collection_is_not_functional_qualification": true,
        "namespace": SSHSIG_NAMESPACE,
        "fixture_signer": openssh_keygen(),
        "statement_sha256": sha256(statement),
        "effective_token": windows_signature_trace::effective_token(),
        "generated_signature_before": before,
        "original_verify": {"ok": verified.is_ok(), "result": format!("{:?}", verified.as_ref().map(|value| &value.detached_signature_sha256))},
        "generated_signature_after": windows_signature_trace::inspect(&signature),
        "private_allowed_signers_control": windows_signature_trace::inspect(&fixture.allowed_signers),
        "private_policy_control": windows_signature_trace::inspect(&fixture.policy)
    });
    windows_signature_trace::save("trust-signature-original.json", facts)
        .expect("save actual original signature metadata");
}
