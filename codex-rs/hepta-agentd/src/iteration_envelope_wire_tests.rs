use super::*;
use codex_hepta_agent_components::learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_agent_components::learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_agent_components::learning_ledger::TrustedLearningSignerV1;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

fn fixture() -> serde_json::Value {
    serde_json::json!({
        "envelopeId": "iteration-1", "baseCommit": "1".repeat(40), "baseTree": "2".repeat(40),
        "objectiveDigest": "3".repeat(64), "grammarDigest": "4".repeat(64),
        "allowedPaths": ["src/learning"], "deniedAuthorities": ["release", "selection"],
        "maximumFiles": 10, "maximumBytes": 1024, "maximumCandidates": 4,
        "wallTimeMicros": 300000000,
        "computeBudget": {"profile": COMPUTE_PROFILE, "maximumParallelSandboxes": 2,
            "maximumMemoryBytes": 1073741824_u64, "maximumProcesses": 64},
        "mandatoryChecks": ["unit"], "expiresUnixMs": 80
    })
}

fn decode(value: &serde_json::Value) -> Result<CanonicalIterationEnvelopeV1, String> {
    CanonicalIterationEnvelopeV1::decode(
        &serde_json::to_vec(value).map_err(|error| error.to_string())?,
    )
}

fn signed(
    envelope: &CanonicalIterationEnvelopeV1,
) -> TestResult<(LearningEvidenceVerifierV1, SignedLearningEvidenceV1)> {
    signed_at(envelope, /*clock_origin_ms*/ 0)
}

fn signed_at(
    envelope: &CanonicalIterationEnvelopeV1,
    clock_origin_ms: u64,
) -> TestResult<(LearningEvidenceVerifierV1, SignedLearningEvidenceV1)> {
    let key = SigningKey::from_bytes(&[7; 32]);
    let scope = Digest32::of_bytes(b"scope");
    let objective = Digest32::from_str(&"3".repeat(64))?;
    let principal = StableId::new("generator")?;
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: scope,
        objective_digest: objective,
        authority_epoch: 7,
        signers: vec![TrustedLearningSignerV1 {
            principal: AuthenticatedPrincipalV1 {
                principal_id: principal.clone(),
                credential_chain_digest: Digest32::of_bytes(b"chain"),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                scope_digest: scope,
                authority_epoch: 7,
                authenticated_at: clock_origin_ms + 10,
                expires_at: clock_origin_ms + 100,
            },
            controller_id: StableId::new("controller")?,
            verifying_key: key.verifying_key().to_bytes(),
            roles: vec![LearningEvidenceRoleV1::Generator],
            revoked_at: None,
        }],
    })?;
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: StableId::new("submission")?,
        principal_id: principal,
        role: LearningEvidenceRoleV1::Generator,
        trust_digest: verifier.trust_digest(),
        scope_digest: scope,
        objective_digest: objective,
        authority_epoch: 7,
        issued_at: clock_origin_ms + 20,
        expires_at: clock_origin_ms + 90,
        payload_digest: Digest32::of_bytes(&envelope.signing_payload()),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    Ok((verifier, evidence))
}

#[test]
fn authenticates_exact_generator_submission_with_separate_host_pin() -> TestResult {
    let envelope = decode(&fixture())?;
    let (verifier, evidence) = signed(&envelope)?;
    let verified =
        envelope.verify_generator_submission(envelope.digest(), &verifier, &evidence, 30)?;
    assert_eq!(verified.principal().principal_id, evidence.principal_id);
    assert_eq!(
        verified.payload_digest(),
        Digest32::of_bytes(&envelope.signing_payload())
    );
    assert_eq!(verified.trust_digest(), verifier.trust_digest());
    assert!(
        envelope
            .verify_generator_submission(Digest32::ZERO, &verifier, &evidence, 30)
            .is_err()
    );
    assert!(
        envelope
            .verify_generator_submission(envelope.digest(), &verifier, &evidence, 80)
            .is_err()
    );
    let mut modified = fixture();
    modified["maximumCandidates"] = 3.into();
    let modified = decode(&modified)?;
    assert!(
        modified
            .verify_generator_submission(modified.digest(), &verifier, &evidence, 30)
            .is_err()
    );
    let mut invalid = evidence;
    invalid.signature[0] ^= 1;
    assert!(
        envelope
            .verify_generator_submission(envelope.digest(), &verifier, &invalid, 30)
            .is_err()
    );
    Ok(())
}

#[test]
fn rejects_unknown_duplicate_missing_and_noncanonical_policy_inputs() -> TestResult {
    for name in fixture().as_object().ok_or("object")?.keys() {
        let mut value = fixture();
        value.as_object_mut().ok_or("object")?.remove(name);
        assert!(decode(&value).is_err(), "missing {name}");
    }
    for (field, value) in [
        ("maximumFiles", serde_json::json!(101)),
        ("maximumBytes", serde_json::json!(1048577)),
        ("allowedPaths", serde_json::json!(["../src"])),
        ("allowedPaths", serde_json::json!(["src/*"])),
        ("allowedPaths", serde_json::json!(["C:/src"])),
        ("mandatoryChecks", serde_json::json!(["unit", "unit"])),
        ("deniedAuthorities", serde_json::json!(null)),
        ("baseCommit", serde_json::json!("A".repeat(40))),
    ] {
        let mut modified = fixture();
        modified[field] = value;
        assert!(decode(&modified).is_err(), "invalid {field}");
    }
    let mut unknown = fixture();
    unknown["computeBudget"]["untrusted"] = true.into();
    assert!(decode(&unknown).is_err());
    let bytes = serde_json::to_string(&fixture())?;
    let duplicate = bytes.replacen('{', "{\"envelopeId\":\"other\",", 1);
    assert!(CanonicalIterationEnvelopeV1::decode(duplicate.as_bytes()).is_err());
    Ok(())
}

#[test]
fn canonical_bytes_preserve_policy_and_accept_bounded_whitespace() -> TestResult {
    let envelope = decode(&fixture())?;
    let decoded = CanonicalIterationEnvelopeV1::decode(envelope.canonical_bytes())?;
    assert_eq!(envelope.canonical_bytes(), decoded.canonical_bytes());
    assert_eq!(envelope.digest(), decoded.digest());
    let mut padded = envelope.canonical_bytes().to_vec();
    padded.resize(MAX_ENCODED_BYTES, b' ');
    assert!(CanonicalIterationEnvelopeV1::decode(&padded).is_ok());
    padded.push(b' ');
    assert!(CanonicalIterationEnvelopeV1::decode(&padded).is_err());
    Ok(())
}

#[test]
fn canonical_matches_independent_python_vector() -> TestResult {
    let envelope = decode(&fixture())?;
    // Python json.dumps(sort_keys=True, separators=(",", ":")) and hashlib.sha256.
    let expected = r#"{"allowedPaths":["src/learning"],"baseCommit":"1111111111111111111111111111111111111111","baseTree":"2222222222222222222222222222222222222222","computeBudget":{"maximumMemoryBytes":1073741824,"maximumParallelSandboxes":2,"maximumProcesses":64,"profile":"hepta.iteration-compute-budget.v1"},"deniedAuthorities":["release","selection"],"envelopeId":"iteration-1","expiresUnixMs":80,"grammarDigest":"4444444444444444444444444444444444444444444444444444444444444444","mandatoryChecks":["unit"],"maximumBytes":1024,"maximumCandidates":4,"maximumFiles":10,"objectiveDigest":"3333333333333333333333333333333333333333333333333333333333333333","wallTimeMicros":300000000}"#;
    assert_eq!(envelope.canonical_bytes(), expected.as_bytes());
    assert_eq!(
        envelope.digest().to_string(),
        "17a138ccf3f145caf5adf920b9697fc0b34c1efdf001faae0ee8e98000491383"
    );
    Ok(())
}

#[test]
fn rejects_other_signature_domains_roles_and_current_context() -> TestResult {
    let envelope = decode(&fixture())?;
    let (verifier, _) = signed(&envelope)?;
    let key = SigningKey::from_bytes(&[7; 32]);
    for mutation in 0..4 {
        let (_, mut evidence) = signed(&envelope)?;
        match mutation {
            0 => evidence.payload_digest = Digest32::of_bytes(envelope.canonical_bytes()),
            1 => evidence.role = LearningEvidenceRoleV1::Evaluator,
            2 => evidence.authority_epoch += 1,
            3 => evidence.objective_digest = Digest32::of_bytes(b"other objective"),
            _ => return Err("unexpected test case".into()),
        }
        evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
        assert!(
            envelope
                .verify_generator_submission(envelope.digest(), &verifier, &evidence, 30)
                .is_err()
        );
    }
    Ok(())
}

#[test]
fn rejects_positional_top_level_envelope() -> TestResult {
    let value = fixture();
    let fields = [
        "envelopeId",
        "baseCommit",
        "baseTree",
        "objectiveDigest",
        "grammarDigest",
        "allowedPaths",
        "deniedAuthorities",
        "maximumFiles",
        "maximumBytes",
        "maximumCandidates",
        "wallTimeMicros",
        "computeBudget",
        "mandatoryChecks",
        "expiresUnixMs",
    ];
    let positional =
        serde_json::Value::Array(fields.iter().map(|field| value[field].clone()).collect());
    assert!(decode(&positional).is_err());
    Ok(())
}

#[test]
fn rejects_positional_compute_budget() -> TestResult {
    let mut value = fixture();
    value["computeBudget"] = serde_json::json!([COMPUTE_PROFILE, 2, 1073741824_u64, 64]);
    assert!(decode(&value).is_err());
    Ok(())
}

#[test]
fn map_only_decode_preserves_duplicate_and_trailing_rejection() -> TestResult {
    let bytes = serde_json::to_string(&fixture())?;
    let duplicate = bytes.replacen(
        "\"maximumProcesses\":64",
        "\"maximumProcesses\":64,\"maximumProcesses\":65",
        1,
    );
    assert_ne!(duplicate, bytes);
    assert!(CanonicalIterationEnvelopeV1::decode(duplicate.as_bytes()).is_err());
    let trailing = format!("{bytes} {{}}");
    assert!(CanonicalIterationEnvelopeV1::decode(trailing.as_bytes()).is_err());
    Ok(())
}

#[test]
fn rejects_seconds_evidence_in_the_millisecond_submission_profile() -> TestResult {
    let origin_ms = 1_700_000_000_000;
    let mut value = fixture();
    value["expiresUnixMs"] = (origin_ms + 80).into();
    let envelope = decode(&value)?;
    let (verifier, mut evidence) = signed_at(&envelope, origin_ms)?;
    assert!(
        envelope
            .verify_generator_submission(envelope.digest(), &verifier, &evidence, origin_ms + 30)
            .is_ok()
    );
    evidence.issued_at /= 1_000;
    evidence.expires_at /= 1_000;
    evidence.signature = SigningKey::from_bytes(&[7; 32])
        .sign(&evidence.signing_bytes())
        .to_bytes();
    assert!(
        envelope
            .verify_generator_submission(envelope.digest(), &verifier, &evidence, origin_ms + 30)
            .is_err()
    );
    Ok(())
}
