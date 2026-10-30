use std::collections::BTreeMap;
use std::path::PathBuf;

use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::*;
use crate::test_support::platform::*;
use crate::test_support::private_tempdir;
use crate::test_support::write_fixture_file;

#[test]
fn challenge_preparation_refuses_unqualified_durable_commit_without_authority() {
    let fixture = TrustFixture::new();
    let challenge_path = fixture.root.join("prepare.json");
    let error = prepare_g5_challenge(G5PrepareRequest {
        challenge_path: &challenge_path,
        candidate: candidate(),
        evidence: evidence(),
        lifetime_seconds: 120,
        now_unix_seconds: 1_000,
        trust: fixture.inputs(),
    })
    .expect_err("Windows directory flush is not qualified");
    assert!(matches!(error, crate::AcceptanceError::Io(ref source)
        if matches!(source.kind(), std::io::ErrorKind::PermissionDenied | std::io::ErrorKind::Unsupported)));
    // A failed flush may leave an uncommitted challenge input. It cannot
    // create an acceptance, claim, ledger or successful assessment.
    if challenge_path.exists() {
        let challenge: G5Challenge =
            serde_json::from_slice(&std::fs::read(&challenge_path).unwrap()).unwrap();
        assert_eq!(challenge.authority, G5AuthorityBoundary::all_false());
    }
    fixture.assert_no_authority();
}

#[test]
fn exact_signature_transport_refuses_windows_and_assessment_cannot_grant_authority() {
    let fixture = TrustFixture::new();
    let error = verify_sshsig_bytes(
        STATEMENT.as_bytes(),
        VALID_SIGNATURE.as_bytes(),
        ALLOWED_SIGNERS.as_bytes(),
        "operator@example",
        SSHSIG_NAMESPACE,
    )
    .expect_err("real valid SSHSIG still requires supported transport");
    assert_eq!(
        error.to_string(),
        "operator acceptance rejected: G5 SSHSIG verification requires Unix"
    );
    let challenge = fixture.seed_challenge();
    for (name, packet) in [
        ("valid-envelope", VALID_SIGNATURE),
        ("wrong-namespace", WRONG_NAMESPACE_SIGNATURE),
        ("corrupt", "not a signature"),
    ] {
        let signature = fixture.root.join(format!("{name}.sig"));
        write_fixture_file(&signature, packet.as_bytes()).expect("signature fixture");
        let before = fixture.snapshot();
        let assessed = fixture
            .assess(&challenge, G5SignatureInput::Detached(&signature), 1_001)
            .expect("failed verification assessment");
        assert_eq!(assessed.status, ASSESSMENT_STATUS_SIGNATURE_INVALID);
        assert!(!assessed.signature_verified);
        assert_eq!(assessed.assessment_path, None);
        assert_eq!(fixture.snapshot(), before);
        fixture.assert_no_authority();
    }
}

#[test]
fn exact_head_and_predecessor_binding_is_required() {
    let fixture = TrustFixture::new();
    let challenge = fixture.seed_challenge();
    for mutate in [
        |value: &mut G5HeadBinding| value.head = "f".repeat(40),
        |value: &mut G5HeadBinding| value.parent_head = "f".repeat(40),
        |value: &mut G5HeadBinding| value.parent_tree = "f".repeat(40),
    ] {
        let before = fixture.snapshot();
        let mut expected = candidate();
        mutate(&mut expected);
        assert!(
            assess_g5_challenge(G5AssessRequest {
                assessment_path: None,
                challenge_path: &challenge,
                expected_candidate: expected,
                expected_evidence: evidence(),
                now_unix_seconds: 1_001,
                signature: G5SignatureInput::Absent,
                trust: fixture.inputs(),
            })
            .is_err()
        );
        assert_eq!(fixture.snapshot(), before);
    }
    fixture.assert_no_authority();
}

#[test]
fn expiry_is_half_open_and_never_creates_acceptance() {
    let fixture = TrustFixture::new();
    let challenge = fixture.seed_challenge();
    let before = fixture.snapshot();
    let assessed = fixture
        .assess(&challenge, G5SignatureInput::Absent, 1_120)
        .expect("expired assessment");
    assert_eq!(assessed.status, ASSESSMENT_STATUS_EXPIRED);
    assert!(!assessed.signature_verified);
    assert_eq!(fixture.snapshot(), before);
    fixture.assert_no_authority();
}

#[test]
fn revocation_is_external_and_fail_closed_before_challenge_issuance() {
    let mut fixture = TrustFixture::new();
    fixture
        .revocation
        .revoked_key_fingerprints
        .push(FINGERPRINT.to_string());
    fixture.rewrite_policy_and_revocation();
    let path = fixture.root.join("revoked.json");
    let before = fixture.snapshot();
    let error = prepare_g5_challenge(G5PrepareRequest {
        challenge_path: &path,
        candidate: candidate(),
        evidence: evidence(),
        lifetime_seconds: 120,
        now_unix_seconds: 1_000,
        trust: fixture.inputs(),
    })
    .expect_err("revoked signer must not receive a challenge");
    assert!(error.to_string().contains("revoked"));
    assert!(!path.exists());
    assert_eq!(fixture.snapshot(), before);
    fixture.assert_no_authority();
}

#[test]
fn revocation_digest_change_invalidates_existing_challenge() {
    let mut fixture = TrustFixture::new();
    let challenge = fixture.seed_challenge();
    fixture.revocation.revoked_nonces = vec!["f".repeat(64)];
    fixture.rewrite_policy_and_revocation();
    let before = fixture.snapshot();
    assert!(
        fixture
            .assess(&challenge, G5SignatureInput::Absent, 1_001)
            .is_err()
    );
    assert_eq!(fixture.snapshot(), before);
    fixture.assert_no_authority();
}

#[test]
fn noncanonical_policy_and_revocation_are_rejected_even_with_matching_digests() {
    let mut fixture = TrustFixture::new();
    let mut bytes = canonical_json(&fixture.policy_value).expect("policy bytes");
    bytes.push(b' ');
    std::fs::remove_file(&fixture.policy).expect("replace policy");
    write_fixture_file(&fixture.policy, &bytes).expect("noncanonical policy");
    fixture.policy_sha256 = sha256(&bytes);
    assert!(load_g5_trust(fixture.inputs()).is_err());
    fixture.assert_no_authority();

    let mut fixture = TrustFixture::new();
    let mut bytes = canonical_json(&fixture.revocation).expect("revocation bytes");
    bytes.push(b' ');
    std::fs::remove_file(&fixture.revocation_path).expect("replace revocation");
    write_fixture_file(&fixture.revocation_path, &bytes).expect("noncanonical revocation");
    fixture.policy_value.revocation_sha256 = sha256(&bytes);
    fixture.rewrite_policy();
    assert!(load_g5_trust(fixture.inputs()).is_err());
    fixture.assert_no_authority();
}

fn candidate() -> G5HeadBinding {
    G5HeadBinding {
        base: "a".repeat(40),
        head: "b".repeat(40),
        parent_head: "c".repeat(40),
        parent_tree: "d".repeat(40),
        tree: "e".repeat(40),
    }
}

fn evidence() -> G5EvidenceBinding {
    G5EvidenceBinding {
        aggregate_sha256: "a".repeat(64),
        evidence_manifest_sha256: "b".repeat(64),
        sha256sums_sha256: "c".repeat(64),
    }
}

struct TrustFixture {
    _temporary: TempDir,
    root: PathBuf,
    allowed_signers: PathBuf,
    policy: PathBuf,
    policy_value: G5TrustPolicy,
    policy_sha256: String,
    revocation: G5RevocationState,
    revocation_path: PathBuf,
}

impl TrustFixture {
    fn new() -> Self {
        let temporary = private_tempdir("Windows G5 fixture");
        let root = temporary
            .path()
            .canonicalize()
            .expect("canonical fixture root");
        let allowed_signers = root.join("allowed_signers");
        write_fixture_file(&allowed_signers, ALLOWED_SIGNERS.as_bytes())
            .expect("allowed signers fixture");
        let revocation = G5RevocationState {
            effective_at_unix_seconds: 1,
            revoked_challenge_sha256: Vec::new(),
            revoked_key_fingerprints: Vec::new(),
            revoked_nonces: Vec::new(),
            revocation_revision: 1,
            schema: G5_REVOCATION_SCHEMA.to_string(),
            schema_version: 1,
            trust_root_id: "g5-test-root".to_string(),
            trust_root_revision: 1,
        };
        let revocation_path = root.join("revocations.json");
        let bytes = canonical_json(&revocation).expect("canonical revocation");
        write_fixture_file(&revocation_path, &bytes).expect("revocation fixture");
        let policy_value = G5TrustPolicy {
            allowed_signers_sha256: sha256(ALLOWED_SIGNERS.as_bytes()),
            key_fingerprint: FINGERPRINT.to_string(),
            maximum_lifetime_seconds: 900,
            principal: "operator@example".to_string(),
            revocation_owner: "security@example".to_string(),
            revocation_sha256: sha256(&bytes),
            revocation_revision: 1,
            schema: G5_TRUST_POLICY_SCHEMA.to_string(),
            schema_version: 1,
            trust_policy_scope: G5_TRUST_POLICY_SCOPE.to_string(),
            trust_root_id: "g5-test-root".to_string(),
            trust_root_revision: 1,
        };
        let policy = root.join("trust-policy.json");
        let bytes = canonical_json(&policy_value).expect("canonical policy");
        write_fixture_file(&policy, &bytes).expect("policy fixture");
        Self {
            _temporary: temporary,
            root,
            allowed_signers,
            policy,
            policy_value,
            policy_sha256: sha256(&bytes),
            revocation,
            revocation_path,
        }
    }

    fn inputs(&self) -> G5TrustInputs<'_> {
        G5TrustInputs {
            allowed_signers_path: &self.allowed_signers,
            externally_pinned_policy_sha256: &self.policy_sha256,
            revocation_path: &self.revocation_path,
            trust_policy_path: &self.policy,
        }
    }

    fn seed_challenge(&self) -> PathBuf {
        // This is fixture input for the read-only assessor, not a claim that
        // Windows successfully committed prepare_g5_challenge.
        let trust = load_g5_trust(self.inputs()).expect("independently loaded trust");
        let value = G5Challenge {
            authority: G5AuthorityBoundary::all_false(),
            candidate: candidate(),
            decision: "accept_bounded_evidence_only".to_string(),
            evidence: evidence(),
            expires_at_unix_seconds: 1_120,
            issued_at_unix_seconds: 1_000,
            namespace: SSHSIG_NAMESPACE.to_string(),
            nonce: "1".repeat(64),
            not_before_unix_seconds: 1_000,
            schema: G5_CHALLENGE_SCHEMA.to_string(),
            schema_version: 1,
            scope: G5_CHALLENGE_SCOPE.to_string(),
            signature_algorithm: SIGNATURE_ALGORITHM.to_string(),
            trust: trust.binding,
        };
        let path = self.root.join("challenge-fixture.json");
        write_fixture_file(
            &path,
            &canonical_json(&value).expect("canonical challenge fixture"),
        )
        .expect("seed challenge fixture");
        path
    }

    fn assess(
        &self,
        challenge: &std::path::Path,
        signature: G5SignatureInput<'_>,
        time: u64,
    ) -> Result<G5AssessmentResult, crate::AcceptanceError> {
        assess_g5_challenge(G5AssessRequest {
            assessment_path: None,
            challenge_path: challenge,
            expected_candidate: candidate(),
            expected_evidence: evidence(),
            now_unix_seconds: time,
            signature,
            trust: self.inputs(),
        })
    }

    fn rewrite_policy_and_revocation(&mut self) {
        let bytes = canonical_json(&self.revocation).expect("canonical changed revocation");
        std::fs::remove_file(&self.revocation_path).expect("replace revocation");
        write_fixture_file(&self.revocation_path, &bytes).expect("changed revocation fixture");
        self.policy_value.revocation_sha256 = sha256(&bytes);
        self.rewrite_policy();
    }

    fn rewrite_policy(&mut self) {
        let bytes = canonical_json(&self.policy_value).expect("canonical changed policy");
        std::fs::remove_file(&self.policy).expect("replace policy");
        write_fixture_file(&self.policy, &bytes).expect("changed policy fixture");
        self.policy_sha256 = sha256(&bytes);
    }

    fn snapshot(&self) -> BTreeMap<PathBuf, Vec<u8>> {
        std::fs::read_dir(&self.root)
            .expect("fixture entries")
            .map(|entry| {
                let path = entry.expect("fixture entry").path();
                let bytes = std::fs::read(&path).expect("fixture bytes");
                (path, bytes)
            })
            .collect()
    }

    fn assert_no_authority(&self) {
        for name in [
            crate::CLAIM_FILE,
            crate::RECEIPT_FILE,
            "ledger",
            "authority.claims",
            "g5-assessment.json",
        ] {
            assert!(!self.root.join(name).exists(), "unexpected {name}");
        }
    }
}
