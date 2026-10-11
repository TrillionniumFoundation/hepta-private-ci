use std::path::Path;
use std::path::PathBuf;
use std::process::Command;

use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::G5_ASSESSMENT_SCHEMA;
use super::G5_REVOCATION_SCHEMA;
use super::G5_TRUST_POLICY_SCHEMA;
use super::G5_TRUST_POLICY_SCOPE;
use super::G5AssessRequest;
use super::G5Assessment;
use super::G5AuthorityBoundary;
use super::G5EvidenceBinding;
use super::G5HeadBinding;
use super::G5PrepareRequest;
use super::G5RevocationState;
use super::G5SignatureInput;
use super::G5TrustInputs;
use super::G5TrustPolicy;
use super::assess_g5_challenge;
use super::prepare_g5_challenge;
use crate::durable::canonical_json;
use crate::durable::sha256;
use crate::durable::write_private_new;
use crate::test_support::private_tempdir;
use crate::trust::SSHSIG_NAMESPACE;

#[test]
fn fresh_head_scoped_challenge_reaches_ready_without_authority() {
    let fixture = TrustFixture::new(false);
    let challenge_path = fixture.root.join("g5-challenge.json");
    let prepared = prepare_g5_challenge(G5PrepareRequest {
        challenge_path: &challenge_path,
        candidate: candidate(),
        evidence: evidence(),
        lifetime_seconds: 120,
        now_unix_seconds: 1_000,
        trust: fixture.inputs(),
    })
    .expect("prepare fresh G5 challenge");
    assert_eq!(prepared.challenge_sha256.len(), 64);
    let challenge_bytes = std::fs::read(&challenge_path).expect("read challenge");
    let challenge: super::G5Challenge =
        serde_json::from_slice(&challenge_bytes).expect("decode challenge");
    assert_eq!(challenge.authority, G5AuthorityBoundary::all_false());

    let assessment_path = fixture.root.join("g5-assessment.json");
    let assessed = assess_g5_challenge(G5AssessRequest {
        assessment_path: Some(&assessment_path),
        challenge_path: &challenge_path,
        expected_candidate: candidate(),
        expected_evidence: evidence(),
        now_unix_seconds: 1_001,
        signature: G5SignatureInput::Absent,
        trust: fixture.inputs(),
    })
    .expect("assess unsigned challenge");
    assert_eq!(assessed.status, "READY_FOR_CHALLENGE");
    assert!(!assessed.signature_verified);
    let (receipt, _) = read_assessment(&assessment_path);
    assert_eq!(receipt.schema, G5_ASSESSMENT_SCHEMA);
    assert_eq!(
        receipt.authority,
        G5AuthorityBoundary {
            deployment: false,
            fleet_and_automation_unfrozen: false,
            g5_allowed: false,
            operator_acceptance: false,
            promotion: false,
            provider_physical_exactly_once: false,
        }
    );
    assert_eq!(receipt.evidence, evidence());
    assert!(
        receipt
            .blockers
            .iter()
            .any(|blocker| blocker.contains("independent signer"))
    );
}

#[test]
fn exact_head_and_predecessor_binding_is_required() {
    let fixture = TrustFixture::new(false);
    let challenge_path = fixture.root.join("g5-challenge.json");
    prepare_g5_challenge(G5PrepareRequest {
        challenge_path: &challenge_path,
        candidate: candidate(),
        evidence: evidence(),
        lifetime_seconds: 120,
        now_unix_seconds: 1_000,
        trust: fixture.inputs(),
    })
    .expect("prepare challenge");

    let mut wrong = candidate();
    wrong.parent_head = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".to_string();
    assert!(
        assess_g5_challenge(G5AssessRequest {
            assessment_path: None,
            challenge_path: &challenge_path,
            expected_candidate: wrong,
            expected_evidence: evidence(),
            now_unix_seconds: 1_001,
            signature: G5SignatureInput::Absent,
            trust: fixture.inputs(),
        })
        .is_err()
    );
}

#[test]
fn expiry_is_half_open_and_never_creates_acceptance() {
    let fixture = TrustFixture::new(false);
    let challenge_path = fixture.root.join("g5-challenge.json");
    let prepared = prepare_g5_challenge(G5PrepareRequest {
        challenge_path: &challenge_path,
        candidate: candidate(),
        evidence: evidence(),
        lifetime_seconds: 2,
        now_unix_seconds: 1_000,
        trust: fixture.inputs(),
    })
    .expect("prepare challenge");
    let assessed = assess_g5_challenge(G5AssessRequest {
        assessment_path: None,
        challenge_path: &challenge_path,
        expected_candidate: candidate(),
        expected_evidence: evidence(),
        now_unix_seconds: prepared.expires_at_unix_seconds,
        signature: G5SignatureInput::Absent,
        trust: fixture.inputs(),
    })
    .expect("expired challenge assessment");
    assert_eq!(assessed.status, "EXPIRED");
    assert!(!assessed.signature_verified);
}

#[test]
fn independently_signed_challenge_is_verified_but_not_accepted() {
    let fixture = TrustFixture::new(false);
    let challenge_path = fixture.root.join("g5-challenge.json");
    prepare_g5_challenge(G5PrepareRequest {
        challenge_path: &challenge_path,
        candidate: candidate(),
        evidence: evidence(),
        lifetime_seconds: 120,
        now_unix_seconds: 1_000,
        trust: fixture.inputs(),
    })
    .expect("prepare challenge");
    let signature_path = fixture.sign(&challenge_path);
    let assessed = assess_g5_challenge(G5AssessRequest {
        assessment_path: None,
        challenge_path: &challenge_path,
        expected_candidate: candidate(),
        expected_evidence: evidence(),
        now_unix_seconds: 1_001,
        signature: G5SignatureInput::Detached(&signature_path),
        trust: fixture.inputs(),
    })
    .expect("verify independent signature");
    assert_eq!(assessed.status, "SIGNATURE_VERIFIED_NO_AUTHORITY");
    assert!(assessed.signature_verified);
}

#[test]
fn revocation_is_external_and_fail_closed_before_challenge_issuance() {
    let fixture = TrustFixture::new(true);
    let challenge_path = fixture.root.join("g5-challenge.json");
    let error = prepare_g5_challenge(G5PrepareRequest {
        challenge_path: &challenge_path,
        candidate: candidate(),
        evidence: evidence(),
        lifetime_seconds: 120,
        now_unix_seconds: 1_000,
        trust: fixture.inputs(),
    })
    .expect_err("revoked signer must not receive a challenge");
    assert!(error.to_string().contains("revoked"));
    assert!(!challenge_path.exists());
}

#[test]
fn revocation_digest_change_invalidates_existing_challenge() {
    let mut fixture = TrustFixture::new(false);
    let challenge_path = fixture.root.join("g5-challenge.json");
    prepare_g5_challenge(G5PrepareRequest {
        challenge_path: &challenge_path,
        candidate: candidate(),
        evidence: evidence(),
        lifetime_seconds: 120,
        now_unix_seconds: 1_000,
        trust: fixture.inputs(),
    })
    .expect("prepare challenge");

    fixture.revocation.revoked_nonces = vec!["f".repeat(64)];
    fixture.rewrite_policy_and_revocation();
    assert!(
        assess_g5_challenge(G5AssessRequest {
            assessment_path: None,
            challenge_path: &challenge_path,
            expected_candidate: candidate(),
            expected_evidence: evidence(),
            now_unix_seconds: 1_001,
            signature: G5SignatureInput::Absent,
            trust: fixture.inputs(),
        })
        .is_err()
    );
}

#[test]
fn policy_and_revocation_files_must_be_canonical() {
    let mut fixture = TrustFixture::new(false);
    let policy_bytes = std::fs::read(&fixture.policy).expect("read policy");
    std::fs::remove_file(&fixture.policy).expect("remove policy");
    write_private_new(
        &fixture.policy,
        br#"{"trust_root_id":"root","trust_root_revision":1,"schema":"hepta_g5_operator_trust_policy_v1","schema_version":1,"trust_policy_scope":"g5_head_scoped_ed25519_external_policy_with_explicit_revocation_v1","principal":"operator@example","key_fingerprint":"SHA256:bad","allowed_signers_sha256":"bad","maximum_lifetime_seconds":120,"revocation_owner":"security@example","revocation_revision":1,"revocation_sha256":"bad"}"#,
    )
    .expect("write malformed policy");
    assert!(fixture.try_inputs().is_err());
    std::fs::remove_file(&fixture.policy).expect("remove malformed policy");
    write_private_new(&fixture.policy, &policy_bytes).expect("restore policy");
    fixture.rewrite_policy_and_revocation();
}

fn candidate() -> G5HeadBinding {
    G5HeadBinding {
        base: "73ff3b438a25d88201169aed7c7c79cf5d9644a8"[..40].to_string(),
        head: "6670ed318d87e51f6ad4d033e2fa6708537e5359".to_string(),
        parent_head: "34dc4ff430af665a4e4aed0fea58482cbb703f34".to_string(),
        parent_tree: "07cff4d567769dc891edffec4fb2c33cd03efb79".to_string(),
        tree: "a4d5c5502ea14d6d91491555df24db8db55053fd"[..40].to_string(),
    }
}

fn evidence() -> G5EvidenceBinding {
    G5EvidenceBinding {
        aggregate_sha256: "a".repeat(64),
        evidence_manifest_sha256: "b".repeat(64),
        sha256sums_sha256: "c".repeat(64),
    }
}

fn read_assessment(path: &Path) -> (G5Assessment, Vec<u8>) {
    let bytes = std::fs::read(path).expect("read assessment");
    let value = serde_json::from_slice(&bytes).expect("decode assessment");
    (value, bytes)
}

struct TrustFixture {
    _temporary: TempDir,
    allowed_signers: PathBuf,
    key: PathBuf,
    policy: PathBuf,
    policy_sha256: String,
    revocation: G5RevocationState,
    revocation_path: PathBuf,
    root: PathBuf,
    policy_value: G5TrustPolicy,
}

impl TrustFixture {
    fn new(revoked: bool) -> Self {
        let temporary = private_tempdir("G5 trust fixture");
        let root = temporary.path().canonicalize().expect("canonical root");
        let key = root.join("operator-key");
        let status = Command::new("/usr/bin/ssh-keygen")
            .args(["-q", "-t", "ed25519", "-N", "", "-f"])
            .arg(&key)
            .status()
            .expect("start test key generation");
        assert!(status.success());
        let public = std::fs::read_to_string(key.with_extension("pub")).expect("public key");
        let fields = public.split_ascii_whitespace().collect::<Vec<_>>();
        assert_eq!(fields.first().copied(), Some("ssh-ed25519"));
        let allowed_signers = root.join("allowed_signers");
        write_private_new(
            &allowed_signers,
            format!("operator@example {} {}\n", fields[0], fields[1]).as_bytes(),
        )
        .expect("write allowed signers");
        let fingerprint_output = Command::new("/usr/bin/ssh-keygen")
            .args(["-E", "sha256", "-lf"])
            .arg(key.with_extension("pub"))
            .output()
            .expect("compute fingerprint");
        assert!(fingerprint_output.status.success());
        let fingerprint = String::from_utf8_lossy(&fingerprint_output.stdout)
            .split_ascii_whitespace()
            .nth(1)
            .expect("fingerprint field")
            .to_string();
        let revocation = G5RevocationState {
            effective_at_unix_seconds: 1,
            revoked_challenge_sha256: Vec::new(),
            revoked_key_fingerprints: if revoked {
                vec![fingerprint.clone()]
            } else {
                Default::default()
            },
            revoked_nonces: Vec::new(),
            revocation_revision: 1,
            schema: G5_REVOCATION_SCHEMA.to_string(),
            schema_version: 1,
            trust_root_id: "g5-test-root".to_string(),
            trust_root_revision: 1,
        };
        let revocation_path = root.join("revocations.json");
        write_private_new(&revocation_path, &canonical_json(&revocation).unwrap()).unwrap();
        let policy_value = G5TrustPolicy {
            allowed_signers_sha256: sha256(&std::fs::read(&allowed_signers).unwrap()),
            key_fingerprint: fingerprint,
            maximum_lifetime_seconds: 900,
            principal: "operator@example".to_string(),
            revocation_owner: "security@example".to_string(),
            revocation_sha256: sha256(&std::fs::read(&revocation_path).unwrap()),
            revocation_revision: 1,
            schema: G5_TRUST_POLICY_SCHEMA.to_string(),
            schema_version: 1,
            trust_policy_scope: G5_TRUST_POLICY_SCOPE.to_string(),
            trust_root_id: "g5-test-root".to_string(),
            trust_root_revision: 1,
        };
        let policy = root.join("trust-policy.json");
        write_private_new(&policy, &canonical_json(&policy_value).unwrap()).unwrap();
        let policy_sha256 = sha256(&std::fs::read(&policy).unwrap());
        Self {
            _temporary: temporary,
            allowed_signers,
            key,
            policy,
            policy_sha256,
            revocation,
            revocation_path,
            root,
            policy_value,
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

    fn try_inputs(&self) -> Result<(), crate::AcceptanceError> {
        let _ = super::load_g5_trust(self.inputs())?;
        Ok(())
    }

    fn rewrite_policy_and_revocation(&mut self) {
        let revocation_bytes = canonical_json(&self.revocation).expect("canonical revocation");
        std::fs::remove_file(&self.revocation_path).expect("replace revocation");
        write_private_new(&self.revocation_path, &revocation_bytes).expect("write revocation");
        self.policy_value.revocation_sha256 = sha256(&revocation_bytes);
        let policy_bytes = canonical_json(&self.policy_value).expect("canonical policy");
        std::fs::remove_file(&self.policy).expect("replace policy");
        write_private_new(&self.policy, &policy_bytes).expect("write policy");
        self.policy_sha256 = sha256(&policy_bytes);
    }

    fn sign(&self, challenge: &Path) -> PathBuf {
        let status = Command::new("/usr/bin/ssh-keygen")
            .args(["-Y", "sign", "-f"])
            .arg(&self.key)
            .args(["-n", SSHSIG_NAMESPACE])
            .arg(challenge)
            .status()
            .expect("start SSHSIG signer");
        assert!(status.success());
        let signature = PathBuf::from(format!("{}.sig", challenge.display()));
        set_private_permissions(&signature);
        signature
    }
}

fn set_private_permissions(path: &Path) {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))
            .expect("private signature permissions");
    }
}
