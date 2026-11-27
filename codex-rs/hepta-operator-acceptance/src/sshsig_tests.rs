use std::io::Write;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use tempfile::TempDir;

use super::verify;
use crate::test_support::assert_ssh_keygen_success;
use crate::test_support::ssh_keygen;

const PRINCIPAL: &str = "operator@example";
const NAMESPACE: &str = "hepta-native-sshsig-differential-v1";
const STATEMENT: &[u8] = b"exact bounded acceptance statement\n";

#[test]
fn openssh_sha256_and_sha512_signatures_verify_natively() {
    let fixture = Fixture::new();
    for algorithm in ["sha256", "sha512"] {
        let signature = fixture.sign(algorithm);
        verify(
            STATEMENT,
            &signature,
            &fixture.allowed,
            PRINCIPAL,
            NAMESPACE,
        )
        .expect("native verifier accepts the actual OpenSSH signature");
        assert!(fixture.openssh_verifies(STATEMENT, algorithm, NAMESPACE));
        assert!(!fixture.openssh_verifies(b"changed statement", algorithm, NAMESPACE));
        assert!(!fixture.openssh_verifies(STATEMENT, algorithm, "other-domain"));
    }
}

#[test]
fn native_sshsig_binds_principal_key_namespace_and_statement() {
    let fixture = Fixture::new();
    let signature = fixture.sign("sha512");
    let other = Fixture::new();
    for (statement, allowed, principal, namespace) in [
        (
            b"changed statement".as_slice(),
            fixture.allowed.as_slice(),
            PRINCIPAL,
            NAMESPACE,
        ),
        (STATEMENT, other.allowed.as_slice(), PRINCIPAL, NAMESPACE),
        (
            STATEMENT,
            fixture.allowed.as_slice(),
            "different@example",
            NAMESPACE,
        ),
        (
            STATEMENT,
            fixture.allowed.as_slice(),
            PRINCIPAL,
            "other-domain",
        ),
        (STATEMENT, fixture.allowed.as_slice(), PRINCIPAL, ""),
    ] {
        assert!(verify(statement, &signature, allowed, principal, namespace).is_err());
    }
}

#[test]
fn native_sshsig_rejects_truncation_lengths_algorithms_and_trailing_bytes() {
    let fixture = Fixture::new();
    let signature = fixture.sign("sha512");
    let blob = unarmor(&signature);
    // Every incomplete wire prefix is rejected, including nested key/signature fields.
    for length in 0..blob.len() {
        assert!(
            fixture.verify(&armor(&blob[..length])).is_err(),
            "prefix {length}"
        );
    }
    let mut trailing = blob.clone();
    trailing.push(0);
    let mut overflowing_length = blob.clone();
    overflowing_length[10..14].copy_from_slice(&u32::MAX.to_be_bytes());
    let mut future_version = blob.clone();
    future_version[6..10].copy_from_slice(&2_u32.to_be_bytes());
    let mut wrong_hash = blob.clone();
    let hash_at = wrong_hash
        .windows(/*size*/ 6)
        .position(|bytes| bytes == b"sha512")
        .unwrap();
    wrong_hash[hash_at..hash_at + 6].copy_from_slice(b"sha384");
    let mut wrong_algorithm = blob.clone();
    let algorithm_at = wrong_algorithm
        .windows(/*size*/ 11)
        .rposition(|bytes| bytes == b"ssh-ed25519")
        .unwrap();
    wrong_algorithm[algorithm_at] = b'x';
    let mut altered_signature = blob;
    *altered_signature.last_mut().unwrap() ^= 1;
    for malformed in [
        trailing,
        overflowing_length,
        future_version,
        wrong_hash,
        wrong_algorithm,
        altered_signature,
    ] {
        assert!(fixture.verify(&armor(&malformed)).is_err());
    }
}

#[test]
fn native_sshsig_refuses_signer_options_certificates_and_wildcards() {
    let fixture = Fixture::new();
    let signature = fixture.sign("sha512");
    let signer = std::str::from_utf8(&fixture.allowed).unwrap();
    let key = signer.split_ascii_whitespace().nth(2).unwrap();
    for allowed in [
        format!("* ssh-ed25519 {key}\n"),
        format!("operator@* ssh-ed25519 {key}\n"),
        format!("{PRINCIPAL} namespaces=\"{NAMESPACE}\" ssh-ed25519 {key}\n"),
        format!("{PRINCIPAL} ssh-ed25519-cert-v01@openssh.com {key}\n"),
        format!("{PRINCIPAL} ssh-ed25519 {key} comment\n"),
        format!("{signer}{signer}"),
    ] {
        assert!(
            verify(
                STATEMENT,
                &signature,
                allowed.as_bytes(),
                PRINCIPAL,
                NAMESPACE
            )
            .is_err()
        );
    }
    let wildcard = format!("* ssh-ed25519 {key}\n");
    assert!(verify(STATEMENT, &signature, wildcard.as_bytes(), "*", NAMESPACE).is_err());
}

#[test]
fn native_sshsig_rejects_read_bounds_and_noncanonical_armor() {
    let fixture = Fixture::new();
    let signature = fixture.sign("sha256");
    let text = std::str::from_utf8(&signature).unwrap();
    for malformed in [
        text.replace('\n', "\r\n").into_bytes(),
        text.trim_end().as_bytes().to_vec(),
        format!("{text}trailing").into_bytes(),
        vec![b'A'; 4097],
    ] {
        assert!(fixture.verify(&malformed).is_err());
    }
    assert!(
        verify(
            STATEMENT,
            &signature,
            &vec![b'A'; 65537],
            PRINCIPAL,
            NAMESPACE
        )
        .is_err()
    );
    assert!(
        fixture
            .verify_statement(&vec![b'A'; 1024 * 1024 + 1], &signature)
            .is_err()
    );
}

struct Fixture {
    temporary: TempDir,
    key: PathBuf,
    allowed: Vec<u8>,
}

impl Fixture {
    fn new() -> Self {
        let temporary = tempfile::tempdir().expect("synthetic SSHSIG fixture directory");
        let key = temporary.path().join("fixture-key");
        let output = Command::new(ssh_keygen())
            .args(["-q", "-t", "ed25519", "-N", "", "-f"])
            .arg(&key)
            .stdin(Stdio::null())
            .output()
            .expect("generate synthetic OpenSSH key");
        assert_ssh_keygen_success("generate synthetic OpenSSH key", &output);
        let public = std::fs::read_to_string(key.with_extension("pub")).unwrap();
        let key_blob = public.split_ascii_whitespace().nth(1).unwrap();
        let allowed = format!("{PRINCIPAL} ssh-ed25519 {key_blob}\n").into_bytes();
        std::fs::write(temporary.path().join("allowed_signers"), &allowed).unwrap();
        Self {
            temporary,
            key,
            allowed,
        }
    }

    fn sign(&self, algorithm: &str) -> Vec<u8> {
        let statement = self.temporary.path().join(algorithm);
        std::fs::write(&statement, STATEMENT).unwrap();
        let output = Command::new(ssh_keygen())
            .args(["-Y", "sign", "-f"])
            .arg(&self.key)
            .args(["-n", NAMESPACE, "-O"])
            .arg(format!("hashalg={algorithm}"))
            .arg(&statement)
            .stdin(Stdio::null())
            .output()
            .expect("sign fixture using actual OpenSSH");
        assert_ssh_keygen_success("sign fixture using actual OpenSSH", &output);
        std::fs::read(statement.with_extension("sig")).unwrap()
    }

    fn openssh_verifies(&self, statement: &[u8], algorithm: &str, namespace: &str) -> bool {
        let mut child = Command::new(ssh_keygen())
            .args(["-Y", "verify", "-f"])
            .arg(self.temporary.path().join("allowed_signers"))
            .args(["-I", PRINCIPAL, "-n", namespace, "-s"])
            .arg(self.temporary.path().join(algorithm).with_extension("sig"))
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("verify fixture using actual OpenSSH");
        child.stdin.take().unwrap().write_all(statement).unwrap();
        child.wait().unwrap().success()
    }

    fn verify(&self, signature: &[u8]) -> Result<(), crate::AcceptanceError> {
        self.verify_statement(STATEMENT, signature)
    }

    fn verify_statement(
        &self,
        statement: &[u8],
        signature: &[u8],
    ) -> Result<(), crate::AcceptanceError> {
        verify(statement, signature, &self.allowed, PRINCIPAL, NAMESPACE)
    }
}

fn unarmor(signature: &[u8]) -> Vec<u8> {
    let text = std::str::from_utf8(signature).unwrap();
    let encoded = text
        .lines()
        .filter(|line| !line.starts_with("-----"))
        .collect::<String>();
    STANDARD.decode(encoded).unwrap()
}

fn armor(blob: &[u8]) -> Vec<u8> {
    format!(
        "-----BEGIN SSH SIGNATURE-----\n{}\n-----END SSH SIGNATURE-----\n",
        STANDARD.encode(blob)
    )
    .into_bytes()
}
