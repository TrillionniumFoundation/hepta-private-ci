use std::collections::BTreeMap;
use std::path::PathBuf;

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::TRUST_POLICY_SCHEMA;
use super::TRUST_POLICY_SCOPE;
use super::TrustAnchor;
use super::TrustInputs;
use super::TrustPolicy;
use super::validate_ed25519_blob;
use crate::durable::canonical_json;
use crate::durable::sha256;
use crate::test_support::platform::*;
use crate::test_support::private_tempdir;
use crate::test_support::write_fixture_file;

#[test]
fn sshsig_entrypoints_fail_closed_without_unix_inherited_descriptors() {
    let fixture = TrustFixture::new();
    let anchor = fixture.load_anchor();
    for (name, statement, packet) in [
        ("valid", STATEMENT.as_bytes(), VALID_SIGNATURE),
        (
            "wrong-namespace",
            STATEMENT.as_bytes(),
            WRONG_NAMESPACE_SIGNATURE,
        ),
        (
            "changed-statement",
            b"changed operator statement".as_slice(),
            VALID_SIGNATURE,
        ),
    ] {
        let path = fixture.root.join(format!("{name}.sig"));
        write_fixture_file(&path, packet.as_bytes()).expect("test packet");
        let before = fixture.snapshot();
        for result in [
            anchor.verify(statement, &path),
            anchor.verify_base64(statement, &STANDARD.encode(packet.as_bytes())),
        ] {
            let error = result.err().expect("Windows verifier must refuse");
            assert_eq!(
                error.to_string(),
                "operator acceptance rejected: OpenSSH SSHSIG verification requires Unix inherited descriptors"
            );
        }
        assert_eq!(fixture.snapshot(), before);
        fixture.assert_no_authority();
    }
    assert!(
        anchor
            .verify_base64(STATEMENT.as_bytes(), &STANDARD.encode(b"corrupt packet"))
            .is_err()
    );
    fixture.assert_no_authority();
}

#[test]
fn trust_policy_digest_is_external_and_fail_closed() {
    let fixture = TrustFixture::new();
    assert!(
        TrustAnchor::load(TrustInputs {
            acceptance_store_root: &fixture.root,
            allowed_signers_path: &fixture.allowed_signers,
            externally_pinned_trust_policy_sha256: &"0".repeat(64),
            trust_policy_path: &fixture.policy,
        })
        .is_err()
    );
    fixture.assert_no_authority();
}

#[test]
fn trust_policy_pins_store_principal_fingerprint_and_allowed_signers() {
    let fixture = TrustFixture::new();
    let other = private_tempdir("other acceptance store");
    assert!(
        TrustAnchor::load(TrustInputs {
            acceptance_store_root: &other.path().canonicalize().expect("canonical other store"),
            allowed_signers_path: &fixture.allowed_signers,
            externally_pinned_trust_policy_sha256: &fixture.policy_sha256,
            trust_policy_path: &fixture.policy,
        })
        .is_err()
    );
    for mutate in [
        |policy: &mut TrustPolicy| policy.principal = "different@example".to_string(),
        |policy: &mut TrustPolicy| {
            policy.key_fingerprint =
                "SHA256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".to_string()
        },
    ] {
        let mut fixture = TrustFixture::new();
        mutate(&mut fixture.policy_value);
        fixture.persist_changed_policy();
        assert!(fixture.try_load_anchor().is_err());
        fixture.assert_no_authority();
    }
    let fixture = TrustFixture::new();
    std::fs::remove_file(&fixture.allowed_signers).expect("replace allowed signers");
    write_fixture_file(
        &fixture.allowed_signers,
        b"operator@example ssh-ed25519 AAAA\n",
    )
    .expect("changed signer");
    assert!(fixture.try_load_anchor().is_err());
    fixture.assert_no_authority();
}

#[test]
fn weak_ed25519_public_key_is_rejected_before_verifier() {
    let mut blob = Vec::new();
    for value in [b"ssh-ed25519".as_slice(), &[0_u8; 32]] {
        blob.extend_from_slice(&(value.len() as u32).to_be_bytes());
        blob.extend_from_slice(value);
    }
    assert!(validate_ed25519_blob(&blob).is_err());
}

struct TrustFixture {
    _temporary: TempDir,
    root: PathBuf,
    allowed_signers: PathBuf,
    policy: PathBuf,
    policy_sha256: String,
    policy_value: TrustPolicy,
}

impl TrustFixture {
    fn new() -> Self {
        let temporary = private_tempdir("Windows trust fixture");
        let root = temporary
            .path()
            .canonicalize()
            .expect("canonical trust root");
        let allowed_signers = root.join("allowed_signers");
        write_fixture_file(&allowed_signers, ALLOWED_SIGNERS.as_bytes())
            .expect("allowed signers fixture");
        let policy_value = TrustPolicy {
            acceptance_store_root: root.to_string_lossy().into_owned(),
            allowed_signers_sha256: sha256(ALLOWED_SIGNERS.as_bytes()),
            key_fingerprint: FINGERPRINT.to_string(),
            maximum_lifetime_seconds: 900,
            principal: "operator@example".to_string(),
            schema: TRUST_POLICY_SCHEMA.to_string(),
            schema_version: 1,
            trust_policy_scope: TRUST_POLICY_SCOPE.to_string(),
            trust_root_id: "test-operator-root".to_string(),
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
            policy_sha256: sha256(&bytes),
            policy_value,
        }
    }

    fn load_anchor(&self) -> TrustAnchor {
        self.try_load_anchor().expect("load pinned fixture trust")
    }

    fn try_load_anchor(&self) -> Result<TrustAnchor, crate::AcceptanceError> {
        TrustAnchor::load(TrustInputs {
            acceptance_store_root: &self.root,
            allowed_signers_path: &self.allowed_signers,
            externally_pinned_trust_policy_sha256: &self.policy_sha256,
            trust_policy_path: &self.policy,
        })
    }

    fn persist_changed_policy(&mut self) {
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
        ] {
            assert!(!self.root.join(name).exists(), "unexpected {name}");
        }
    }
}
