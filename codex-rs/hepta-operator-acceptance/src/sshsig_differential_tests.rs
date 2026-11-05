//! Real original OpenSSH bytes/oracle; no mocked cryptographic verdicts.
use super::*;
use crate::sshsig_strict::verify_ed25519_sshsig;
use std::process::Stdio;

#[test]
fn original_openssh_sha256_sha512_and_every_packet_binding_are_preserved() -> std::io::Result<()> {
    let fixture = TrustFixture::new();
    let other = TrustFixture::new();
    let allowed = std::fs::read(&fixture.allowed_signers)?;
    let other_allowed = std::fs::read_to_string(&other.allowed_signers)?;
    let other_key = STANDARD
        .decode(
            other_allowed
                .split_ascii_whitespace()
                .nth(2)
                .ok_or_else(|| std::io::Error::other("test signer key"))?,
        )
        .map_err(std::io::Error::other)?;
    let statement = vec![b'x'; 8 * 1024 + 17];
    let anchor = fixture.load_anchor();
    for hash in ["sha256", "sha512"] {
        let signed_path = fixture.sign_hash(&statement, SSHSIG_NAMESPACE, hash, hash);
        let original = std::fs::read(signed_path)?;
        assert!(
            verify_ed25519_sshsig(
                &statement,
                &original,
                &allowed,
                "operator@example",
                SSHSIG_NAMESPACE
            )
            .is_ok()
        );
        assert!(anchor.verify_bytes(&statement, &original).is_ok());
        assert!(oracle(
            &fixture,
            &statement,
            &original,
            "operator@example",
            hash,
            "positive"
        )?);

        let mut wrong_magic = packet(&original)?;
        wrong_magic[0] ^= 1;
        let mut wrong_version = packet(&original)?;
        wrong_version[6..10].copy_from_slice(&2_u32.to_be_bytes());
        let mut bad_signature = field(&original, 4)?;
        let last = bad_signature.len() - 1;
        bad_signature[last] ^= 1;
        let mut bad_algorithm = field(&original, 4)?;
        bad_algorithm[4] ^= 1;
        let mut trailing = packet(&original)?;
        trailing.push(0);
        let mut truncated_length = packet(&original)?;
        truncated_length[10..14].copy_from_slice(&u32::MAX.to_be_bytes());
        let alternative_hash: &[u8] = if hash == "sha256" {
            b"sha512"
        } else {
            b"sha256"
        };
        let cases = [
            ("magic", armor(&wrong_magic)),
            ("version", armor(&wrong_version)),
            ("raw-key", replace_field(&original, 0, &other_key)?),
            (
                "namespace",
                replace_field(&original, 1, b"different-namespace")?,
            ),
            (
                "reserved",
                replace_field(&original, 2, b"changed-reserved-bytes")?,
            ),
            (
                "message-hash-algorithm",
                replace_field(&original, 3, alternative_hash)?,
            ),
            ("unsupported-hash", replace_field(&original, 3, b"sha1")?),
            (
                "signature-algorithm",
                replace_field(&original, 4, &bad_algorithm)?,
            ),
            (
                "signature-bits",
                replace_field(&original, 4, &bad_signature)?,
            ),
            ("packet-trailer", armor(&trailing)),
            ("length-overflow", armor(&truncated_length)),
        ];
        for (label, modified) in cases {
            assert!(
                verify_ed25519_sshsig(
                    &statement,
                    &modified,
                    &allowed,
                    "operator@example",
                    SSHSIG_NAMESPACE
                )
                .is_err(),
                "{hash}/{label}"
            );
            assert!(
                anchor.verify_bytes(&statement, &modified).is_err(),
                "pipeline {hash}/{label}"
            );
            let oracle_accepts = oracle(
                &fixture,
                &statement,
                &modified,
                "operator@example",
                hash,
                label,
            )?;
            // OpenSSH intentionally ignores packet reserved bytes and rebuilds
            // an empty reserved signed field. Our fixed V1 profile refuses it.
            assert_eq!(
                oracle_accepts,
                label == "reserved",
                "original OpenSSH behavior changed for {hash}/{label}"
            );
            println!("SSHSIG_DIFFERENTIAL_REJECT {hash}/{label} oracleAccepted={oracle_accepts}");
        }
        let mut changed = statement.clone();
        let last = changed.len() - 1;
        changed[last] ^= 1;
        assert!(
            verify_ed25519_sshsig(
                &changed,
                &original,
                &allowed,
                "operator@example",
                SSHSIG_NAMESPACE
            )
            .is_err()
        );
        assert!(!oracle(
            &fixture,
            &changed,
            &original,
            "operator@example",
            hash,
            "complete-message-tail"
        )?);
        assert!(
            verify_ed25519_sshsig(
                &statement,
                &original,
                &allowed,
                "different@example",
                SSHSIG_NAMESPACE
            )
            .is_err()
        );
        assert!(!oracle(
            &fixture,
            &statement,
            &original,
            "different@example",
            hash,
            "principal"
        )?);
        println!("SSHSIG_DIFFERENTIAL_REJECT {hash}/complete-message-tail");
        println!("SSHSIG_DIFFERENTIAL_REJECT {hash}/principal");
        println!("SSHSIG_DIFFERENTIAL_PASS {hash}/original");
    }
    Ok(())
}

fn oracle(
    fixture: &TrustFixture,
    statement: &[u8],
    signature: &[u8],
    principal: &str,
    hash: &str,
    label: &str,
) -> std::io::Result<bool> {
    let path = fixture.root.join(format!("oracle-{hash}-{label}"));
    write_private(&path, signature);
    let mut child = Command::new("/usr/bin/ssh-keygen")
        .args(["-Y", "verify", "-f"])
        .arg(&fixture.allowed_signers)
        .args(["-I", principal, "-n", SSHSIG_NAMESPACE, "-s"])
        .arg(path)
        .env_clear()
        .env("LANG", "C")
        .env("LC_ALL", "C")
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()?;
    child
        .stdin
        .take()
        .ok_or_else(|| std::io::Error::other("original OpenSSH stdin"))?
        .write_all(statement)?;
    Ok(child.wait()?.success())
}

fn packet(signature: &[u8]) -> std::io::Result<Vec<u8>> {
    let text = std::str::from_utf8(signature).map_err(std::io::Error::other)?;
    let body = text
        .lines()
        .filter(|line| !line.starts_with("-----"))
        .collect::<String>();
    STANDARD.decode(body).map_err(std::io::Error::other)
}

fn armor(packet: &[u8]) -> Vec<u8> {
    format!(
        "-----BEGIN SSH SIGNATURE-----\n{}\n-----END SSH SIGNATURE-----\n",
        STANDARD.encode(packet)
    )
    .into_bytes()
}

fn location(packet: &[u8], index: usize) -> std::io::Result<(usize, usize)> {
    let mut offset = 10;
    for current in 0..5 {
        let raw: [u8; 4] = packet
            .get(offset..offset + 4)
            .ok_or_else(|| std::io::Error::other("test packet field"))?
            .try_into()
            .map_err(std::io::Error::other)?;
        let end = offset + 4 + u32::from_be_bytes(raw) as usize;
        if current == index {
            return Ok((offset, end));
        }
        offset = end;
    }
    Err(std::io::Error::other("test packet field index"))
}

fn field(signature: &[u8], index: usize) -> std::io::Result<Vec<u8>> {
    let packet = packet(signature)?;
    let (start, end) = location(&packet, index)?;
    Ok(packet[start + 4..end].to_vec())
}

fn replace_field(signature: &[u8], index: usize, replacement: &[u8]) -> std::io::Result<Vec<u8>> {
    let mut packet = packet(signature)?;
    let (start, end) = location(&packet, index)?;
    let mut value = u32::try_from(replacement.len())
        .map_err(std::io::Error::other)?
        .to_be_bytes()
        .to_vec();
    value.extend(replacement);
    packet.splice(start..end, value);
    Ok(armor(&packet))
}
