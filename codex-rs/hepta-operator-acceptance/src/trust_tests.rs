use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use pretty_assertions::assert_eq;
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
use crate::test_support::private_tempdir;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

#[test]
fn sshsig_verifies_only_exact_namespace_against_pinned_policy() -> TestResult {
    let fixture = TrustFixture::new()?;
    let anchor = fixture.try_load_anchor()?;
    let statement = b"canonical operator acceptance statement";

    let signature = fixture.sign(statement, SSHSIG_NAMESPACE, "accepted")?;
    let verified = anchor.verify(statement, &signature)?;
    assert_eq!(
        verified.detached_signature_sha256,
        sha256(&std::fs::read(&signature)?)
    );
    std::fs::remove_file(&signature)?;
    anchor.verify_base64(statement, &verified.detached_signature_sshsig_base64)?;

    let mut corrupted = STANDARD.decode(&verified.detached_signature_sshsig_base64)?;
    corrupted[0] ^= 1;
    assert!(
        anchor
            .verify_base64(statement, &STANDARD.encode(corrupted))
            .is_err()
    );

    let wrong = fixture.sign(statement, "hepta-operator-acceptance-v1", "wrong-namespace")?;
    assert!(anchor.verify(statement, &wrong).is_err());
    Ok(())
}

#[test]
fn trust_policy_digest_is_external_and_fail_closed() -> TestResult {
    let fixture = TrustFixture::new()?;
    let error = TrustAnchor::load(TrustInputs {
        acceptance_store_root: &fixture.root,
        allowed_signers_path: &fixture.allowed_signers,
        externally_pinned_trust_policy_sha256: "0000000000000000000000000000000000000000000000000000000000000000",
        trust_policy_path: &fixture.policy,
    });
    assert!(error.is_err());
    Ok(())
}

#[test]
fn trust_policy_pins_store_principal_fingerprint_and_allowed_signers() -> TestResult {
    let fixture = TrustFixture::new()?;
    let other_store = private_tempdir("other acceptance store");
    let other_store = other_store.path().canonicalize()?;
    assert!(
        TrustAnchor::load(TrustInputs {
            acceptance_store_root: &other_store,
            allowed_signers_path: &fixture.allowed_signers,
            externally_pinned_trust_policy_sha256: &fixture.policy_sha256,
            trust_policy_path: &fixture.policy,
        })
        .is_err()
    );

    let mut principal_fixture = TrustFixture::new()?;
    principal_fixture.policy_value.principal = "different@example".to_string();
    principal_fixture.persist_changed_policy()?;
    assert!(principal_fixture.try_load_anchor().is_err());

    let mut fingerprint_fixture = TrustFixture::new()?;
    fingerprint_fixture.policy_value.key_fingerprint =
        "SHA256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".to_string();
    fingerprint_fixture.persist_changed_policy()?;
    assert!(fingerprint_fixture.try_load_anchor().is_err());

    let allowed_fixture = TrustFixture::new()?;
    std::fs::remove_file(&allowed_fixture.allowed_signers)?;
    write_private(
        &allowed_fixture.allowed_signers,
        b"operator@example ssh-ed25519 AAAA\n",
    )?;
    assert!(allowed_fixture.try_load_anchor().is_err());
    Ok(())
}

#[test]
fn weak_ed25519_public_key_is_rejected_before_openssh() -> TestResult {
    let mut blob = ssh_string(b"ssh-ed25519")?;
    blob.extend(ssh_string(&[0_u8; 32])?);
    assert!(validate_ed25519_blob(&blob).is_err());
    Ok(())
}

struct TrustFixture {
    _temporary: TempDir,
    allowed_signers: PathBuf,
    key: PathBuf,
    policy: PathBuf,
    policy_sha256: String,
    policy_value: TrustPolicy,
    root: PathBuf,
}

impl TrustFixture {
    fn new() -> TestResult<Self> {
        let temporary = private_tempdir("temporary trust directory");
        let root = temporary.path().canonicalize()?;
        let key = root.join("operator-key");
        let generated = Command::new("/usr/bin/ssh-keygen")
            .args(["-q", "-t", "ed25519", "-N", "", "-f"])
            .arg(&key)
            .status()?;
        assert!(generated.success(), "generate test-only Ed25519 key");

        let public = std::fs::read_to_string(key.with_extension("pub"))?;
        let fields = public.split_ascii_whitespace().collect::<Vec<_>>();
        assert_eq!(fields.first().copied(), Some("ssh-ed25519"));
        let allowed_signers = root.join("allowed_signers");
        write_private(
            &allowed_signers,
            format!("operator@example {0} {1}\n", fields[0], fields[1]).as_bytes(),
        )?;

        let fingerprint_output = Command::new("/usr/bin/ssh-keygen")
            .args(["-E", "sha256", "-lf"])
            .arg(key.with_extension("pub"))
            .output()?;
        assert!(fingerprint_output.status.success());
        let fingerprint_line = std::str::from_utf8(&fingerprint_output.stdout)?;
        let fingerprint = fingerprint_line
            .split_ascii_whitespace()
            .nth(1)
            .ok_or("OpenSSH fingerprint field")?
            .to_string();

        let policy_value = TrustPolicy {
            acceptance_store_root: root.to_string_lossy().into_owned(),
            allowed_signers_sha256: sha256(&std::fs::read(&allowed_signers)?),
            key_fingerprint: fingerprint,
            maximum_lifetime_seconds: 900,
            principal: "operator@example".to_string(),
            schema: TRUST_POLICY_SCHEMA.to_string(),
            schema_version: 1,
            trust_policy_scope: TRUST_POLICY_SCOPE.to_string(),
            trust_root_id: "test-operator-root".to_string(),
            trust_root_revision: 1,
        };
        let policy_bytes = canonical_json(&policy_value)?;
        let policy = root.join("trust-policy.json");
        write_private(&policy, &policy_bytes)?;
        let policy_sha256 = sha256(&policy_bytes);
        Ok(Self {
            _temporary: temporary,
            allowed_signers,
            key,
            policy,
            policy_sha256,
            policy_value,
            root,
        })
    }

    fn try_load_anchor(&self) -> Result<TrustAnchor, crate::AcceptanceError> {
        TrustAnchor::load(TrustInputs {
            acceptance_store_root: &self.root,
            allowed_signers_path: &self.allowed_signers,
            externally_pinned_trust_policy_sha256: &self.policy_sha256,
            trust_policy_path: &self.policy,
        })
    }

    fn persist_changed_policy(&mut self) -> Result<(), crate::AcceptanceError> {
        let bytes = canonical_json(&self.policy_value)?;
        std::fs::remove_file(&self.policy)?;
        write_private(&self.policy, &bytes)?;
        self.policy_sha256 = sha256(&bytes);
        Ok(())
    }

    fn sign(&self, statement: &[u8], namespace: &str, name: &str) -> std::io::Result<PathBuf> {
        let statement_path = self.root.join(name);
        write_private(&statement_path, statement)?;
        let signed = Command::new("/usr/bin/ssh-keygen")
            .args(["-Y", "sign", "-f"])
            .arg(&self.key)
            .args(["-n", namespace])
            .arg(&statement_path)
            .status()?;
        assert!(signed.success(), "create test-only SSHSIG");
        let signature = PathBuf::from(format!("{}.sig", statement_path.display()));
        set_private_permissions(&signature)?;
        Ok(signature)
    }
}

fn ssh_string(bytes: &[u8]) -> Result<Vec<u8>, std::num::TryFromIntError> {
    let mut encoded = u32::try_from(bytes.len())?.to_be_bytes().to_vec();
    encoded.extend(bytes);
    Ok(encoded)
}

fn write_private(path: &Path, bytes: &[u8]) -> std::io::Result<()> {
    let mut options = OpenOptions::new();
    options.create_new(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(path)?;
    file.write_all(bytes)
}

fn set_private_permissions(path: &Path) -> std::io::Result<()> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
    }
    Ok(())
}
