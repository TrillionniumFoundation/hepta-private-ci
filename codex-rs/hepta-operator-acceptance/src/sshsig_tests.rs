use std::io::Write;
use std::process::Stdio;

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use tempfile::TempDir;

use super::BEGIN;
use super::END;
use super::verify;
use crate::test_support::private_tempdir;
use crate::test_support::ssh_keygen_command;

const PRINCIPAL: &str = "operator@example.test";
const NAMESPACE: &str = "hepta-vnext-operator-acceptance-v1";
const STATEMENT: &[u8] = b"independent OpenSSH signed statement\n";

struct OpenSshFixture {
    _temporary: TempDir,
    allowed: Vec<u8>,
    signature: Vec<u8>,
}

impl OpenSshFixture {
    fn new(hash: &str) -> Self {
        let temporary = private_tempdir("SSHSIG interoperability");
        let key = temporary.path().join("key");
        let generated = ssh_keygen_command()
            .args(["-q", "-t", "ed25519", "-N", "", "-f"])
            .arg(&key)
            .output()
            .expect("run OpenSSH key generation");
        assert!(generated.status.success(), "{generated:?}");
        let public = std::fs::read_to_string(key.with_extension("pub")).expect("read public key");
        let mut fields = public.split_ascii_whitespace();
        let algorithm = fields.next().expect("key algorithm");
        let key_blob = fields.next().expect("key blob");
        let allowed = format!("{PRINCIPAL} {algorithm} {key_blob}\n").into_bytes();
        let allowed_path = temporary.path().join("allowed_signers");
        std::fs::write(&allowed_path, &allowed).expect("write allowed signer");
        let message = temporary.path().join("statement");
        std::fs::write(&message, STATEMENT).expect("write statement");
        let signed = ssh_keygen_command()
            .args(["-Y", "sign", "-f"])
            .arg(&key)
            .args(["-n", NAMESPACE, "-O", &format!("hashalg={hash}")])
            .arg(&message)
            .output()
            .expect("run OpenSSH signing");
        assert!(signed.status.success(), "{signed:?}");
        let signature_path = message.with_extension("sig");
        let signature = std::fs::read(&signature_path).expect("read OpenSSH signature");
        let mut original = ssh_keygen_command()
            .args(["-Y", "verify", "-f"])
            .arg(&allowed_path)
            .args(["-I", PRINCIPAL, "-n", NAMESPACE, "-s"])
            .arg(&signature_path)
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .spawn()
            .expect("start independent OpenSSH verifier");
        original
            .stdin
            .take()
            .expect("verification stdin")
            .write_all(STATEMENT)
            .expect("send signed statement");
        let result = original
            .wait_with_output()
            .expect("finish independent verifier");
        assert!(result.status.success(), "{result:?}");
        Self {
            _temporary: temporary,
            allowed,
            signature,
        }
    }

    fn openssh_accepts(&self, signature: &[u8]) -> bool {
        let signature_path = self._temporary.path().join("reserved-variant.sig");
        std::fs::write(&signature_path, signature).expect("write verifier input");
        let mut original = ssh_keygen_command()
            .args(["-Y", "verify", "-f"])
            .arg(self._temporary.path().join("allowed_signers"))
            .args(["-I", PRINCIPAL, "-n", NAMESPACE, "-s"])
            .arg(&signature_path)
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .spawn()
            .expect("start independent OpenSSH verifier");
        original
            .stdin
            .take()
            .expect("verification stdin")
            .write_all(STATEMENT)
            .expect("send signed statement");
        original
            .wait_with_output()
            .expect("finish verifier")
            .status
            .success()
    }

    fn wire(&self) -> Vec<u8> {
        let envelope = std::str::from_utf8(&self.signature).expect("OpenSSH UTF-8");
        STANDARD
            .decode(
                envelope
                    .strip_prefix(BEGIN)
                    .expect("header")
                    .strip_suffix(END)
                    .expect("footer")
                    .replace('\n', ""),
            )
            .expect("OpenSSH signature base64")
    }

    fn accepts(&self, signature: &[u8]) -> bool {
        verify(STATEMENT, signature, &self.allowed, PRINCIPAL, NAMESPACE).is_ok()
    }
}

fn armor(wire: &[u8]) -> Vec<u8> {
    format!("{BEGIN}{}\n{END}", STANDARD.encode(wire)).into_bytes()
}

#[test]
fn independently_generated_openssh_sha256_and_sha512_signatures_verify() {
    for hash in ["sha256", "sha512"] {
        let fixture = OpenSshFixture::new(hash);
        assert!(fixture.accepts(&fixture.signature));
        assert!(fixture.accepts(&armor(&fixture.wire())));
    }
}

#[test]
fn every_wire_byte_mutation_and_truncation_is_rejected() {
    let fixture = OpenSshFixture::new("sha512");
    let wire = fixture.wire();
    for index in 0..wire.len() {
        let mut changed = wire.clone();
        changed[index] ^= 1;
        assert!(!fixture.accepts(&armor(&changed)), "wire byte {index}");
        assert!(
            !fixture.accepts(&armor(&wire[..index])),
            "wire length {index}"
        );
    }
    let mut trailing = wire.clone();
    trailing.push(0);
    assert!(!fixture.accepts(&armor(&trailing)));
    let mut oversized_field = wire;
    oversized_field[10..14].copy_from_slice(&u32::MAX.to_be_bytes());
    assert!(!fixture.accepts(&armor(&oversized_field)));
}

#[test]
fn wrong_statement_principal_namespace_and_independent_signer_are_rejected() {
    let fixture = OpenSshFixture::new("sha512");
    let other = OpenSshFixture::new("sha256");
    assert!(
        verify(
            b"changed",
            &fixture.signature,
            &fixture.allowed,
            PRINCIPAL,
            NAMESPACE
        )
        .is_err()
    );
    assert!(
        verify(
            STATEMENT,
            &fixture.signature,
            &fixture.allowed,
            "other",
            NAMESPACE
        )
        .is_err()
    );
    assert!(
        verify(
            STATEMENT,
            &fixture.signature,
            &fixture.allowed,
            PRINCIPAL,
            "other"
        )
        .is_err()
    );
    assert!(
        verify(
            STATEMENT,
            &fixture.signature,
            &other.allowed,
            PRINCIPAL,
            NAMESPACE
        )
        .is_err()
    );
    let mut multiple = fixture.allowed.clone();
    multiple.extend_from_slice(&fixture.allowed);
    assert!(
        verify(
            STATEMENT,
            &fixture.signature,
            &multiple,
            PRINCIPAL,
            NAMESPACE
        )
        .is_err()
    );
}

#[test]
fn malformed_armor_and_oversized_inputs_are_rejected() {
    let fixture = OpenSshFixture::new("sha512");
    assert!(!fixture.accepts(b"not an SSHSIG"));
    let crlf = String::from_utf8(fixture.signature.clone())
        .expect("UTF-8")
        .replace('\n', "\r\n");
    assert!(!fixture.accepts(crlf.as_bytes()));
    assert!(!fixture.accepts(&vec![b'a'; 4097]));
    assert!(
        verify(
            STATEMENT,
            &fixture.signature,
            &vec![b'a'; 65537],
            PRINCIPAL,
            NAMESPACE
        )
        .is_err()
    );
}

#[test]
fn nonempty_reserved_wire_field_matches_independent_openssh() {
    let fixture = OpenSshFixture::new("sha512");
    let mut wire = fixture.wire();
    let mut reserved_offset = 10;
    for _ in 0..2 {
        let length = u32::from_be_bytes(
            wire[reserved_offset..reserved_offset + 4]
                .try_into()
                .expect("field length"),
        ) as usize;
        reserved_offset += 4 + length;
    }
    assert!(
        wire[reserved_offset..reserved_offset + 4]
            .iter()
            .all(|byte| *byte == 0)
    );
    let reserved = b"ignored\0\xff";
    let mut replacement = (reserved.len() as u32).to_be_bytes().to_vec();
    replacement.extend_from_slice(reserved);
    wire.splice(reserved_offset..reserved_offset + 4, replacement);
    let variant = armor(&wire);
    assert!(
        fixture.openssh_accepts(&variant),
        "original OpenSSH reserved-field behavior"
    );
    assert!(fixture.accepts(&variant));
}

#[cfg(windows)]
#[test]
fn windows_openssh_program_data_is_scoped_to_the_child_environment() {
    let parent_before = std::env::var_os("ProgramData");
    let temporary = private_tempdir("OpenSSH startup environment");
    let denied_key = temporary.path().join("missing-program-data");
    let denied = ssh_keygen_command()
        .env_remove("ProgramData")
        .args(["-q", "-t", "ed25519", "-N", "", "-f"])
        .arg(&denied_key)
        .output()
        .expect("run OpenSSH without its required startup environment");
    assert_eq!(denied.status.code(), Some(255), "{denied:?}");
    assert!(!denied_key.exists());
    assert!(!denied_key.with_extension("pub").exists());

    let key = temporary.path().join("known-folder-program-data");
    let generated = ssh_keygen_command()
        .args(["-q", "-t", "ed25519", "-N", "", "-f"])
        .arg(&key)
        .output()
        .expect("run OpenSSH with the actual known-folder path");
    assert!(generated.status.success(), "{generated:?}");
    assert!(key.is_file());
    assert!(key.with_extension("pub").is_file());
    assert_eq!(std::env::var_os("ProgramData"), parent_before);
}
