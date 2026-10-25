use std::io::Write;
use std::process::Command;
use std::process::Stdio;

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;

use super::verify;

const PRINCIPAL: &str = "test@example";
const NAMESPACE: &str = "hepta-vnext-operator-acceptance-v1";

#[test]
fn real_openssh_sha256_and_sha512_packets_verify_with_exact_pins() {
    let temporary = tempfile::tempdir().unwrap();
    let key = temporary.path().join("signer");
    let generated = Command::new(crate::test_support::ssh_keygen())
        .args(["-q", "-t", "ed25519", "-N", "", "-f"])
        .arg(&key)
        .status()
        .unwrap();
    assert!(generated.success());
    let public = std::fs::read_to_string(key.with_extension("pub")).unwrap();
    let key_fields: Vec<_> = public.split_ascii_whitespace().collect();
    let allowed = format!("{PRINCIPAL} {} {}\n", key_fields[0], key_fields[1]);
    let allowed_path = temporary.path().join("allowed_signers");
    std::fs::write(&allowed_path, &allowed).unwrap();
    let message = b"real OpenSSH interoperability; no runtime authority";
    let statement = temporary.path().join("statement");
    std::fs::write(&statement, message).unwrap();
    let signature_path = temporary.path().join("statement.sig");

    for hash in ["sha256", "sha512"] {
        let signed = Command::new(crate::test_support::ssh_keygen())
            .args(["-Y", "sign", "-f"])
            .arg(&key)
            .args(["-n", NAMESPACE, "-O", &format!("hashalg={hash}")])
            .arg(&statement)
            .output()
            .unwrap();
        assert!(signed.status.success(), "{signed:?}");
        let envelope = std::fs::read(&signature_path).unwrap();
        assert!(oracle(message, &allowed_path, &signature_path));
        assert!(!oracle(
            b"changed statement",
            &allowed_path,
            &signature_path
        ));
        verify(message, &envelope, allowed.as_bytes(), PRINCIPAL, NAMESPACE).unwrap();
        // Preserve OpenSSH's interior ASCII whitespace handling within the
        // original strict LF header/footer gates used by both product callers.
        let body = envelope
            .strip_prefix(b"-----BEGIN SSH SIGNATURE-----\n")
            .unwrap()
            .strip_suffix(b"\n-----END SSH SIGNATURE-----\n")
            .unwrap();
        let mut spaced = b"-----BEGIN SSH SIGNATURE-----\n \t".to_vec();
        for byte in body {
            if *byte == b'\n' {
                spaced.extend_from_slice(b"\r\n \t");
            } else {
                spaced.push(*byte);
            }
        }
        spaced.extend_from_slice(b"\n-----END SSH SIGNATURE-----\n");
        std::fs::write(&signature_path, &spaced).unwrap();
        assert!(oracle(message, &allowed_path, &signature_path));
        verify(message, &spaced, allowed.as_bytes(), PRINCIPAL, NAMESPACE).unwrap();
        std::fs::write(&signature_path, &envelope).unwrap();
        for (statement, principal, namespace) in [
            (b"changed statement".as_slice(), PRINCIPAL, NAMESPACE),
            (message.as_slice(), "other@example", NAMESPACE),
            (message.as_slice(), PRINCIPAL, "wrong-domain"),
        ] {
            assert!(
                verify(
                    statement,
                    &envelope,
                    allowed.as_bytes(),
                    principal,
                    namespace
                )
                .is_err()
            );
        }
        let wrong_key = allowed.replace(key_fields[1], &STANDARD.encode([0_u8; 51]));
        assert!(
            verify(
                message,
                &envelope,
                wrong_key.as_bytes(),
                PRINCIPAL,
                NAMESPACE
            )
            .is_err()
        );

        let encoded = envelope
            .strip_prefix(b"-----BEGIN SSH SIGNATURE-----\n")
            .unwrap()
            .strip_suffix(b"\n-----END SSH SIGNATURE-----\n")
            .unwrap();
        let blob = STANDARD
            .decode(
                encoded
                    .iter()
                    .copied()
                    .filter(|byte| *byte != b'\n')
                    .collect::<Vec<_>>(),
            )
            .unwrap();
        // Mutations cover every byte of the actual external packet, including
        // wire lengths, key, domain, hash selection and signature. No local
        // test signer or mock verifier can make these controls pass.
        for offset in 0..blob.len() {
            let mut changed = blob.clone();
            changed[offset] ^= 0x80;
            assert!(
                verify(
                    message,
                    &armor(&changed),
                    allowed.as_bytes(),
                    PRINCIPAL,
                    NAMESPACE
                )
                .is_err(),
                "accepted changed {hash} packet byte {offset}"
            );
        }
        for end in 0..blob.len() {
            assert!(
                verify(
                    message,
                    &armor(&blob[..end]),
                    allowed.as_bytes(),
                    PRINCIPAL,
                    NAMESPACE
                )
                .is_err(),
                "accepted truncated packet at {end}"
            );
        }
        let mut trailing = blob;
        trailing.push(0);
        assert!(
            verify(
                message,
                &armor(&trailing),
                allowed.as_bytes(),
                PRINCIPAL,
                NAMESPACE
            )
            .is_err()
        );
        assert!(
            verify(
                message,
                &vec![b'x'; 4097],
                allowed.as_bytes(),
                PRINCIPAL,
                NAMESPACE
            )
            .is_err()
        );
        std::fs::remove_file(&signature_path).unwrap();
    }
}

fn armor(blob: &[u8]) -> Vec<u8> {
    format!(
        "-----BEGIN SSH SIGNATURE-----\n{}\n-----END SSH SIGNATURE-----\n",
        STANDARD.encode(blob)
    )
    .into_bytes()
}

fn oracle(message: &[u8], allowed: &std::path::Path, signature: &std::path::Path) -> bool {
    let mut verifier = Command::new(crate::test_support::ssh_keygen())
        .args(["-Y", "verify", "-f"])
        .arg(allowed)
        .args(["-I", PRINCIPAL, "-n", NAMESPACE, "-s"])
        .arg(signature)
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    verifier.stdin.take().unwrap().write_all(message).unwrap();
    verifier.wait().unwrap().success()
}
