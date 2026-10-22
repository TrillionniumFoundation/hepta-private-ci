use pretty_assertions::assert_eq;

use super::*;
use crate::test_support::windows_custody::grant;
use crate::test_support::windows_custody::world_sid;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;

#[test]
fn each_g5_input_requires_private_custody_even_with_unchanged_valid_signed_bytes() {
    for input in [
        "policy",
        "allowed-signers",
        "revocation",
        "challenge",
        "signature",
    ] {
        let fixture = TrustFixture::new(/*revoked*/ false);
        let challenge = fixture.root.join("challenge.json");
        prepare_g5_challenge(G5PrepareRequest {
            challenge_path: &challenge,
            candidate: candidate(),
            evidence: evidence(),
            lifetime_seconds: 120,
            now_unix_seconds: 1_000,
            trust: fixture.inputs(),
        })
        .expect("valid private challenge setup");
        let signature = fixture.sign(&challenge);
        let assess = || {
            assess_g5_challenge(G5AssessRequest {
                assessment_path: None,
                challenge_path: &challenge,
                expected_candidate: candidate(),
                expected_evidence: evidence(),
                now_unix_seconds: 1_001,
                signature: G5SignatureInput::Detached(&signature),
                trust: fixture.inputs(),
            })
        };
        let valid = assess().expect("signed private positive control must reach success");
        assert_eq!(valid.status, "SIGNATURE_VERIFIED_NO_AUTHORITY");
        assert!(valid.signature_verified);
        let path = match input {
            "policy" => &fixture.policy,
            "allowed-signers" => &fixture.allowed_signers,
            "revocation" => &fixture.revocation_path,
            "challenge" => &challenge,
            "signature" => &signature,
            _ => unreachable!(),
        };
        let bytes = std::fs::read(path).unwrap();
        let inventory = std::fs::read_dir(&fixture.root).unwrap().count();
        grant(path, world_sid(), FILE_GENERIC_READ, /*flags*/ 0);
        assert!(
            assess().is_err(),
            "{input} custody rejection must precede signature success"
        );
        assert_eq!(std::fs::read(path).unwrap(), bytes);
        assert_eq!(
            std::fs::read_dir(&fixture.root).unwrap().count(),
            inventory,
            "assessment_path None must not write or repair anything"
        );
    }
}

#[test]
fn signed_assessment_preserves_optional_private_output_and_no_authority() {
    let fixture = TrustFixture::new(/*revoked*/ false);
    let challenge = fixture.root.join("challenge.json");
    prepare_g5_challenge(G5PrepareRequest {
        challenge_path: &challenge,
        candidate: candidate(),
        evidence: evidence(),
        lifetime_seconds: 120,
        now_unix_seconds: 1_000,
        trust: fixture.inputs(),
    })
    .unwrap();
    let signature = fixture.sign(&challenge);
    let assessment = fixture.root.join("assessment.json");
    let result = assess_g5_challenge(G5AssessRequest {
        assessment_path: Some(&assessment),
        challenge_path: &challenge,
        expected_candidate: candidate(),
        expected_evidence: evidence(),
        now_unix_seconds: 1_001,
        signature: G5SignatureInput::Detached(&signature),
        trust: fixture.inputs(),
    })
    .expect("Some output is not silently disabled");
    assert!(result.signature_verified);
    let bytes = crate::durable::secure_read(&assessment, crate::durable::MAX_SMALL_FILE_BYTES)
        .expect("persisted result has private custody");
    let assessment: G5Assessment = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(assessment.authority, G5AuthorityBoundary::all_false());
}
