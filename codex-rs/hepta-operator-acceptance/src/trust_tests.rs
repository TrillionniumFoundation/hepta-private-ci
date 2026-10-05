use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use tempfile::TempDir;

use super::SSHSIG_NAMESPACE;
use super::TRUST_POLICY_SCHEMA;
use super::TRUST_POLICY_SCOPE;
use super::TrustAnchor;
use super::TrustInputs;
use super::TrustPolicy;
use super::validate_ed25519_blob;
use crate::durable::canonical_json;
use crate::durable::sha256;
use crate::test_support::TestSshKey;
use crate::test_support::private_tempdir;

#[test]
fn sshsig_verifies_only_exact_namespace_against_pinned_policy() {
    let fixture = TrustFixture::new();
    let anchor = fixture.load_anchor();
    let statement = b"canonical operator acceptance statement";

    let signature = fixture.sign(statement, SSHSIG_NAMESPACE, "accepted");
    let verified = anchor
        .verify(statement, &signature)
        .expect("valid exact-namespace SSHSIG");
    assert_eq!(
        verified.detached_signature_sha256,
        sha256(&std::fs::read(&signature).unwrap())
    );
    std::fs::remove_file(&signature).expect("delete original signature packet");
    anchor
        .verify_base64(statement, &verified.detached_signature_sshsig_base64)
        .expect("stored receipt signature remains independently verifiable");

    let mut corrupted = STANDARD
        .decode(&verified.detached_signature_sshsig_base64)
        .expect("decode verified signature");
    corrupted[0] ^= 1;
    assert!(
        anchor
            .verify_base64(statement, &STANDARD.encode(corrupted))
            .is_err()
    );

    let wrong = fixture.sign(statement, "hepta-operator-acceptance-v1", "wrong-namespace");
    assert!(anchor.verify(statement, &wrong).is_err());
}

#[test]
fn mutable_binding_cannot_replace_the_privately_pinned_signer() {
    let fixture = TrustFixture::new();
    let other = TrustFixture::new();
    let mut anchor = fixture.load_anchor();
    anchor.binding.key_fingerprint = other.policy_value.key_fingerprint.clone();
    let statement = b"pinned signer must survive mutable display metadata";
    let signature = other.sign(statement, SSHSIG_NAMESPACE, "other-signer");
    assert!(anchor.verify(statement, &signature).is_err());
}

#[test]
fn mutable_binding_cannot_relabel_the_pinned_principal() {
    let fixture = TrustFixture::new();
    let mut anchor = fixture.load_anchor();
    anchor.binding.principal = "other@example".to_string();
    let statement = b"pinned principal must survive mutable display metadata";
    let signature = fixture.sign(statement, SSHSIG_NAMESPACE, "other-principal");
    assert!(anchor.verify(statement, &signature).is_err());
}

#[test]
fn stored_signature_base64_is_bounded_before_decoding() {
    let fixture = TrustFixture::new();
    let anchor = fixture.load_anchor();
    let encoded = STANDARD.encode(vec![0; super::MAX_SIGNATURE_BYTES + 4]);
    let error = anchor
        .verify_base64(b"statement", &encoded)
        .err()
        .expect("reject oversized persisted signature before base64 allocation");
    assert!(matches!(error, crate::AcceptanceError::Invalid(message)
        if message == "stored SSHSIG base64 exceeds its read bound"));
}

#[test]
fn trust_policy_digest_is_external_and_fail_closed() {
    let fixture = TrustFixture::new();
    let error = TrustAnchor::load(TrustInputs {
        acceptance_store_root: &fixture.root,
        allowed_signers_path: &fixture.allowed_signers,
        externally_pinned_trust_policy_sha256: "0000000000000000000000000000000000000000000000000000000000000000",
        trust_policy_path: &fixture.policy,
    });
    assert!(error.is_err());
}

#[test]
fn trust_policy_pins_store_principal_fingerprint_and_allowed_signers() {
    let fixture = TrustFixture::new();
    let other_store = private_tempdir("other acceptance store");
    let other_store = other_store
        .path()
        .canonicalize()
        .expect("canonical other store");
    assert!(
        TrustAnchor::load(TrustInputs {
            acceptance_store_root: &other_store,
            allowed_signers_path: &fixture.allowed_signers,
            externally_pinned_trust_policy_sha256: &fixture.policy_sha256,
            trust_policy_path: &fixture.policy,
        })
        .is_err()
    );

    let mut principal_fixture = TrustFixture::new();
    principal_fixture.policy_value.principal = "different@example".to_string();
    principal_fixture.persist_changed_policy();
    assert!(principal_fixture.try_load_anchor().is_err());

    let mut fingerprint_fixture = TrustFixture::new();
    fingerprint_fixture.policy_value.key_fingerprint =
        "SHA256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".to_string();
    fingerprint_fixture.persist_changed_policy();
    assert!(fingerprint_fixture.try_load_anchor().is_err());

    let allowed_fixture = TrustFixture::new();
    std::fs::remove_file(&allowed_fixture.allowed_signers).expect("replace allowed_signers");
    write_private(
        &allowed_fixture.allowed_signers,
        b"operator@example ssh-ed25519 AAAA\n",
    );
    assert!(allowed_fixture.try_load_anchor().is_err());
}

#[test]
fn weak_ed25519_public_key_is_rejected_before_openssh() {
    let mut blob = ssh_string(b"ssh-ed25519");
    blob.extend(ssh_string(&[0_u8; 32]));
    assert!(validate_ed25519_blob(&blob).is_err());
}

struct TrustFixture {
    _temporary: TempDir,
    allowed_signers: PathBuf,
    key: TestSshKey,
    policy: PathBuf,
    policy_sha256: String,
    policy_value: TrustPolicy,
    root: PathBuf,
}

impl TrustFixture {
    fn new() -> Self {
        let temporary = private_tempdir("temporary trust directory");
        let root = temporary
            .path()
            .canonicalize()
            .expect("canonical trust root");
        let key = TestSshKey::new();
        let allowed_signers = root.join("allowed_signers");
        write_private(
            &allowed_signers,
            format!("operator@example {}\n", key.public_key()).as_bytes(),
        );
        let fingerprint = key.fingerprint();

        let policy_value = TrustPolicy {
            acceptance_store_root: root.to_string_lossy().into_owned(),
            allowed_signers_sha256: sha256(&std::fs::read(&allowed_signers).unwrap()),
            key_fingerprint: fingerprint,
            maximum_lifetime_seconds: 900,
            principal: "operator@example".to_string(),
            schema: TRUST_POLICY_SCHEMA.to_string(),
            schema_version: 1,
            trust_policy_scope: TRUST_POLICY_SCOPE.to_string(),
            trust_root_id: "test-operator-root".to_string(),
            trust_root_revision: 1,
        };
        let policy_bytes = canonical_json(&policy_value).expect("canonical test policy");
        let policy = root.join("trust-policy.json");
        write_private(&policy, &policy_bytes);
        let policy_sha256 = sha256(&policy_bytes);
        Self {
            _temporary: temporary,
            allowed_signers,
            key,
            policy,
            policy_sha256,
            policy_value,
            root,
        }
    }

    fn load_anchor(&self) -> TrustAnchor {
        self.try_load_anchor()
            .expect("load externally pinned test trust")
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
        std::fs::remove_file(&self.policy).expect("replace test policy");
        write_private(&self.policy, &bytes);
        self.policy_sha256 = sha256(&bytes);
    }

    fn sign(&self, statement: &[u8], namespace: &str, name: &str) -> PathBuf {
        let statement_path = self.root.join(name);
        write_private(&statement_path, statement);
        let signature = PathBuf::from(format!("{}.sig", statement_path.display()));
        write_private(&signature, &self.key.sign(statement, namespace));
        signature
    }
}

fn ssh_string(bytes: &[u8]) -> Vec<u8> {
    let mut encoded = u32::try_from(bytes.len())
        .expect("test SSH string length")
        .to_be_bytes()
        .to_vec();
    encoded.extend(bytes);
    encoded
}

fn write_private(path: &Path, bytes: &[u8]) {
    let mut options = OpenOptions::new();
    options.create_new(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(path).expect("create private test file");
    file.write_all(bytes).expect("write private test file");
}
