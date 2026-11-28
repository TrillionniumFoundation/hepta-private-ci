use std::io::Write;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use sha2::Digest as _;

use super::FOOTER;
use super::HEADER;
use super::MAX_SIGNATURE_BYTES;
use super::verify_captured;
use crate::test_support::ssh_keygen_path;

struct Oracle {
    _temporary: tempfile::TempDir,
    key: PathBuf,
    allowed: PathBuf,
    other_allowed: PathBuf,
    signature: PathBuf,
    fingerprint: String,
    other_fingerprint: String,
}

impl Oracle {
    fn new() -> Self {
        let temporary = tempfile::tempdir().expect("private SSHSIG oracle");
        let key = temporary.path().join("key");
        let other = temporary.path().join("other-key");
        let mut fingerprints = Vec::new();
        let mut allowed_paths = Vec::new();
        for (index, key) in [&key, &other].into_iter().enumerate() {
            let result = Command::new(ssh_keygen_path())
                .args(["-q", "-t", "ed25519", "-N", "", "-f"])
                .arg(key)
                .output()
                .expect("start fixed system key generator");
            assert!(result.status.success(), "{:?}", result.status);
            let public = std::fs::read_to_string(key.with_extension("pub")).expect("public key");
            let fields = public.split_ascii_whitespace().collect::<Vec<_>>();
            assert_eq!(fields[0], "ssh-ed25519");
            let blob = STANDARD.decode(fields[1]).expect("public key blob");
            fingerprints.push(format!(
                "SHA256:{}",
                STANDARD_NO_PAD.encode(sha2::Sha256::digest(&blob))
            ));
            let path = temporary.path().join(format!("allowed-{index}"));
            std::fs::write(
                &path,
                format!("operator@example {} {}\n", fields[0], fields[1]),
            )
            .expect("captured allowed signer");
            allowed_paths.push(path);
        }
        Self {
            signature: temporary.path().join("signature"),
            _temporary: temporary,
            key,
            allowed: allowed_paths.remove(0),
            other_allowed: allowed_paths.remove(0),
            fingerprint: fingerprints.remove(0),
            other_fingerprint: fingerprints.remove(0),
        }
    }

    fn sign(&self, message: &[u8], namespace: &str, hash: &str) -> Vec<u8> {
        let mut child = Command::new(ssh_keygen_path())
            .args(["-Y", "sign", "-f"])
            .arg(&self.key)
            .args(["-n", namespace, "-O", &format!("hashalg={hash}")])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .expect("start independent OpenSSH signer");
        child
            .stdin
            .take()
            .expect("signer stdin")
            .write_all(message)
            .expect("statement");
        let output = child.wait_with_output().expect("wait for signer");
        assert!(output.status.success(), "{:?}", output.status);
        output.stdout
    }

    fn openssh(&self, message: &[u8], signature: &[u8], namespace: &str, other: bool) -> bool {
        // These are the original consumer's envelope and size preconditions,
        // applied before the unchanged external OpenSSH verifier.
        if signature.len() > MAX_SIGNATURE_BYTES
            || !signature.starts_with(HEADER)
            || !signature.ends_with(FOOTER)
        {
            return false;
        }
        std::fs::write(&self.signature, signature).expect("oracle signature");
        let mut child = Command::new(ssh_keygen_path())
            .args(["-Y", "verify", "-f"])
            .arg(if other {
                &self.other_allowed
            } else {
                &self.allowed
            })
            .args(["-I", "operator@example", "-n", namespace, "-s"])
            .arg(&self.signature)
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("start independent OpenSSH verifier");
        let write = child
            .stdin
            .take()
            .expect("verifier stdin")
            .write_all(message);
        let status = child.wait().expect("wait for verifier");
        // A malformed signature can make OpenSSH close stdin before reading.
        if status.success() {
            write.expect("successful verifier consumed the statement");
        }
        status.success()
    }

    fn compare(
        &self,
        label: &str,
        message: &[u8],
        signature: &[u8],
        namespace: &str,
        other: bool,
        expected: bool,
    ) {
        let fingerprint = if other {
            &self.other_fingerprint
        } else {
            &self.fingerprint
        };
        let native = verify_captured(message, signature, namespace, fingerprint).is_ok();
        let openssh = self.openssh(message, signature, namespace, other);
        assert_eq!(openssh, expected, "OpenSSH {label}");
        assert_eq!(native, openssh, "captured verifier {label}");
    }
}

fn blob(signature: &[u8]) -> Vec<u8> {
    let encoded = signature[HEADER.len()..signature.len() - FOOTER.len()]
        .iter()
        .copied()
        .filter(|byte| !byte.is_ascii_whitespace())
        .collect::<Vec<_>>();
    STANDARD.decode(encoded).expect("oracle's base64")
}

fn armor(blob: &[u8]) -> Vec<u8> {
    let mut output = HEADER.to_vec();
    output.extend(STANDARD.encode(blob).bytes());
    output.push(b'\n');
    output.extend_from_slice(FOOTER);
    output
}

fn fields(signature: &[u8]) -> Vec<Vec<u8>> {
    let blob = blob(signature);
    let mut cursor = 10;
    let mut result = Vec::new();
    for _ in 0..5 {
        let length = u32::from_be_bytes(blob[cursor..cursor + 4].try_into().unwrap()) as usize;
        cursor += 4;
        result.push(blob[cursor..cursor + length].to_vec());
        cursor += length;
    }
    assert_eq!(cursor, blob.len());
    result
}

fn encoded_fields(version: u32, fields: &[Vec<u8>]) -> Vec<u8> {
    let mut output = b"SSHSIG".to_vec();
    output.extend_from_slice(&version.to_be_bytes());
    for value in fields {
        output.extend_from_slice(&(value.len() as u32).to_be_bytes());
        output.extend_from_slice(value);
    }
    armor(&output)
}

#[test]
fn actual_openssh_signatures_match_for_both_hashes_and_all_bindings() {
    let oracle = Oracle::new();
    let messages = [b"".as_slice(), b"statement\n", b"binary\0statement\xff"];
    let mut comparisons = 0;
    for namespace in ["hepta-vnext-operator-acceptance-v1", "hepta-g5-test-v1"] {
        for hash in ["sha256", "sha512"] {
            for message in messages {
                let signature = oracle.sign(message, namespace, hash);
                oracle.compare("original", message, &signature, namespace, false, true);
                let mut changed = message.to_vec();
                changed.push(0);
                oracle.compare("statement", &changed, &signature, namespace, false, false);
                oracle.compare(
                    "namespace",
                    message,
                    &signature,
                    "wrong-namespace",
                    false,
                    false,
                );
                oracle.compare("signer", message, &signature, namespace, true, false);
                let mut altered = blob(&signature);
                *altered.last_mut().unwrap() ^= 1;
                oracle.compare(
                    "signature",
                    message,
                    &armor(&altered),
                    namespace,
                    false,
                    false,
                );
                comparisons += 5;
            }
        }
    }
    assert_eq!(comparisons, 60);
}

#[test]
fn actual_openssh_framing_boundaries_match_without_widening_the_envelope() {
    let oracle = Oracle::new();
    let message = b"bounded framing";
    let namespace = "hepta-framing-v1";
    let signature = oracle.sign(message, namespace, "sha512");
    let original = fields(&signature);
    let mut cases = Vec::new();
    cases.push(("version zero", encoded_fields(0, &original), true));
    cases.push(("future version", encoded_fields(2, &original), false));
    let mut changed = original.clone();
    changed[2] = b"reserved bytes\0ignored by OpenSSH".to_vec();
    cases.push(("outer reserved", encoded_fields(1, &changed), true));
    changed = original.clone();
    changed[1].push(0);
    cases.push(("namespace terminator", encoded_fields(1, &changed), true));
    changed[1].extend_from_slice(b"other");
    cases.push(("embedded namespace NUL", encoded_fields(1, &changed), false));
    changed = original.clone();
    changed[1].extend_from_slice(&[0, 0]);
    cases.push(("double namespace NUL", encoded_fields(1, &changed), false));
    changed = original.clone();
    changed[3].push(0);
    cases.push(("hash terminator", encoded_fields(1, &changed), true));
    for field in [0, 4] {
        changed = original.clone();
        let count = u32::from_be_bytes(changed[field][..4].try_into().unwrap()) as usize;
        changed[field][..4].copy_from_slice(&((count + 1) as u32).to_be_bytes());
        changed[field].insert(count + 4, 0);
        cases.push(("algorithm terminator", encoded_fields(1, &changed), true));
    }
    changed = original.clone();
    changed[3] = b"sha1".to_vec();
    cases.push(("unsupported hash", encoded_fields(1, &changed), false));
    changed = original;
    changed[4].push(0);
    cases.push(("inner trailing data", encoded_fields(1, &changed), false));
    let mut raw = blob(&signature);
    raw.push(0);
    cases.push(("outer trailing data", armor(&raw), false));
    raw = blob(&signature);
    raw[10..14].copy_from_slice(&u32::MAX.to_be_bytes());
    cases.push(("oversized field", armor(&raw), false));
    raw = blob(&signature);
    raw[0] ^= 1;
    cases.push(("magic", armor(&raw), false));
    let mut trailing_armor = signature.clone();
    trailing_armor.extend_from_slice(b"ignored armor tail\n");
    trailing_armor.extend_from_slice(FOOTER);
    cases.push(("first footer", trailing_armor, true));
    let mut crlf = HEADER[..HEADER.len() - 1].to_vec();
    crlf.extend_from_slice(b"\r\n");
    crlf.extend_from_slice(&signature[HEADER.len()..]);
    cases.push(("original LF envelope", crlf, false));
    let mut exact_bound = HEADER.to_vec();
    exact_bound.extend(std::iter::repeat_n(
        b'\n',
        MAX_SIGNATURE_BYTES - signature.len(),
    ));
    exact_bound.extend_from_slice(&signature[HEADER.len()..]);
    assert_eq!(exact_bound.len(), MAX_SIGNATURE_BYTES);
    cases.push(("exact original bound", exact_bound.clone(), true));
    exact_bound.insert(HEADER.len(), b'\n');
    cases.push(("over original bound", exact_bound, false));
    assert_eq!(cases.len(), 18);
    for (name, bytes, expected) in cases {
        oracle.compare(name, message, &bytes, namespace, false, expected);
    }
    let raw = blob(&signature);
    for length in [0, 1, 5, 6, 7, 9, 10, 11, 12, 13, 20, raw.len() - 1] {
        oracle.compare(
            "truncation",
            message,
            &armor(&raw[..length]),
            namespace,
            false,
            false,
        );
    }
}

#[test]
fn captured_signature_verification_does_not_reopen_mutable_oracle_files() {
    let oracle = Oracle::new();
    let statement = b"captured statement";
    let namespace = "hepta-captured-v1";
    let signature = oracle.sign(statement, namespace, "sha256");
    std::fs::write(&oracle.signature, b"replaced").expect("replace signature path");
    std::fs::write(&oracle.allowed, b"replaced").expect("replace allowed signer path");
    assert!(verify_captured(statement, &signature, namespace, &oracle.fingerprint).is_ok());
    assert!(verify_captured(statement, &signature, namespace, &oracle.other_fingerprint).is_err());
    assert!(verify_captured(b"replaced", &signature, namespace, &oracle.fingerprint).is_err());
}
