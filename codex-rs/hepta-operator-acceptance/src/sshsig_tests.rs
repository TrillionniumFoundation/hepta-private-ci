use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use sha2::Digest as _;
use sha2::Sha256;

use super::MAX_SIGNATURE_BYTES;
use super::verify_ed25519;
use crate::trust::SSHSIG_NAMESPACE;

#[test]
fn frozen_openssh_sha256_and_sha512_signatures_verify_without_a_child_process() {
    for signature in [OPENSSH_SHA256, OPENSSH_SHA512] {
        verify_ed25519(MESSAGE, signature, FINGERPRINT, SSHSIG_NAMESPACE)
            .expect("independently generated OpenSSH signature");
    }
    verify_ed25519(
        MESSAGE,
        OTHER_SIGNATURE,
        OTHER_FINGERPRINT,
        SSHSIG_NAMESPACE,
    )
    .expect("independent second-key positive control");
}

#[test]
fn valid_self_signed_packet_cannot_replace_the_externally_pinned_key() {
    assert!(verify_ed25519(MESSAGE, OTHER_SIGNATURE, FINGERPRINT, SSHSIG_NAMESPACE).is_err());
    assert!(verify_ed25519(MESSAGE, OPENSSH_SHA512, OTHER_FINGERPRINT, SSHSIG_NAMESPACE).is_err());
    assert!(
        verify_ed25519(
            b"different statement",
            OPENSSH_SHA512,
            FINGERPRINT,
            SSHSIG_NAMESPACE
        )
        .is_err()
    );
    assert!(verify_ed25519(MESSAGE, OPENSSH_SHA512, FINGERPRINT, "different-namespace").is_err());
    assert!(verify_ed25519(MESSAGE, OPENSSH_SHA512, FINGERPRINT, "").is_err());
}

#[test]
fn all_truncations_and_untrusted_field_lengths_reject_without_panicking() {
    let binary = decode(OPENSSH_SHA512);
    for length in 0..binary.len() {
        assert!(
            verify_ed25519(
                MESSAGE,
                &armor(&binary[..length]),
                FINGERPRINT,
                SSHSIG_NAMESPACE
            )
            .is_err(),
            "truncation at {length}"
        );
    }
    let mut offset = 10;
    for _ in 0..5 {
        let length = u32::from_be_bytes(binary[offset..offset + 4].try_into().unwrap()) as usize;
        let mut damaged = binary.clone();
        damaged[offset..offset + 4].copy_from_slice(&u32::MAX.to_be_bytes());
        assert!(verify_ed25519(MESSAGE, &armor(&damaged), FINGERPRINT, SSHSIG_NAMESPACE).is_err());
        offset += 4 + length;
    }
    let mut trailing = binary;
    trailing.push(0);
    assert!(verify_ed25519(MESSAGE, &armor(&trailing), FINGERPRINT, SSHSIG_NAMESPACE).is_err());
}

#[test]
fn version_and_reserved_fields_preserve_openssh_compatibility() {
    let mut packet = Packet::new(OPENSSH_SHA512);
    packet.version = 0;
    packet.verify().expect("OpenSSH accepts version zero");
    packet.version = 2;
    assert!(packet.verify().is_err());
    packet.version = 1;
    packet.fields[2] = b"ignored metadata, never authority".to_vec();
    packet
        .verify()
        .expect("OpenSSH ignores the wire reserved field");
}

#[test]
fn namespace_and_hash_changes_cannot_reinterpret_a_signature() {
    let packet = Packet::new(OPENSSH_SHA512);
    for namespace in [b"".as_slice(), b"other", b"hepta\0vnext"] {
        let mut altered = packet.clone();
        altered.fields[1] = namespace.to_vec();
        assert!(altered.verify().is_err());
    }
    for hash in [b"sha1".as_slice(), b"sha256", b"sha512\0", b""] {
        let mut altered = packet.clone();
        altered.fields[3] = hash.to_vec();
        assert!(altered.verify().is_err());
    }
}

#[test]
fn pinned_malformed_or_weak_public_keys_are_rejected() {
    let original = Packet::new(OPENSSH_SHA512);
    let mut weak_key = ssh_string(b"ssh-ed25519");
    weak_key.extend(ssh_string(&[0; 32]));
    let mut wrong_algorithm = ssh_string(b"ssh-rsa");
    wrong_algorithm.extend(ssh_string(&[0; 32]));
    let mut trailing_key = original.fields[0].clone();
    trailing_key.push(0);
    for malformed in [weak_key, wrong_algorithm, trailing_key, vec![0; 4]] {
        let mut packet = original.clone();
        packet.fields[0] = malformed;
        let pinned = format!(
            "SHA256:{}",
            STANDARD_NO_PAD.encode(Sha256::digest(&packet.fields[0]))
        );
        assert!(verify_ed25519(MESSAGE, &packet.armor(), &pinned, SSHSIG_NAMESPACE).is_err());
    }
}

#[test]
fn malformed_and_malleable_ed25519_signature_records_are_rejected() {
    let original = Packet::new(OPENSSH_SHA512);
    let record = &original.fields[4];
    let payload = &record[19..];
    assert_eq!(payload.len(), 64);
    let mut wrong_algorithm = ssh_string(b"ssh-rsa");
    wrong_algorithm.extend(ssh_string(payload));
    let mut short_signature = ssh_string(b"ssh-ed25519");
    short_signature.extend(ssh_string(&payload[..63]));
    let mut trailing_record = record.clone();
    trailing_record.push(0);
    let mut bad_scalar = record.clone();
    bad_scalar[19 + 32..].fill(255);
    let mut weak_r = record.clone();
    weak_r[19..19 + 32].fill(0);
    let mut flipped = record.clone();
    flipped[19] ^= 1;
    for malformed in [
        wrong_algorithm,
        short_signature,
        trailing_record,
        bad_scalar,
        weak_r,
        flipped,
    ] {
        let mut packet = original.clone();
        packet.fields[4] = malformed;
        assert!(packet.verify().is_err());
    }
}

#[test]
fn armor_is_bounded_and_cannot_hide_trailing_packets_or_bad_base64() {
    let mut oversized = OPENSSH_SHA512.to_vec();
    oversized.resize(MAX_SIGNATURE_BYTES + 1, b'A');
    let mut prefixed = b"untrusted prefix\n".to_vec();
    prefixed.extend(OPENSSH_SHA512);
    let mut suffixed = OPENSSH_SHA512.to_vec();
    suffixed.extend(OPENSSH_SHA512);
    let mut invalid_base64 = OPENSSH_SHA512.to_vec();
    invalid_base64[29] = b'!';
    for malformed in [oversized, prefixed, suffixed, invalid_base64] {
        assert!(verify_ed25519(MESSAGE, &malformed, FINGERPRINT, SSHSIG_NAMESPACE).is_err());
    }
}

#[derive(Clone)]
struct Packet {
    version: u32,
    fields: Vec<Vec<u8>>,
}

impl Packet {
    fn new(signature: &[u8]) -> Self {
        let binary = decode(signature);
        let version = u32::from_be_bytes(binary[6..10].try_into().unwrap());
        let mut remaining = &binary[10..];
        let mut fields = Vec::new();
        for _ in 0..5 {
            let length = u32::from_be_bytes(remaining[..4].try_into().unwrap()) as usize;
            fields.push(remaining[4..4 + length].to_vec());
            remaining = &remaining[4 + length..];
        }
        assert!(remaining.is_empty());
        Self { version, fields }
    }

    fn armor(&self) -> Vec<u8> {
        let mut binary = b"SSHSIG".to_vec();
        binary.extend(self.version.to_be_bytes());
        for field in &self.fields {
            binary.extend(ssh_string(field));
        }
        armor(&binary)
    }

    fn verify(&self) -> Result<(), crate::AcceptanceError> {
        verify_ed25519(MESSAGE, &self.armor(), FINGERPRINT, SSHSIG_NAMESPACE)
    }
}

fn ssh_string(value: &[u8]) -> Vec<u8> {
    let mut encoded = u32::try_from(value.len()).unwrap().to_be_bytes().to_vec();
    encoded.extend(value);
    encoded
}

fn decode(signature: &[u8]) -> Vec<u8> {
    let text = std::str::from_utf8(signature).unwrap();
    let body: String = text
        .lines()
        .filter(|line| !line.starts_with("-----"))
        .collect();
    STANDARD.decode(body).unwrap()
}

fn armor(binary: &[u8]) -> Vec<u8> {
    format!(
        "-----BEGIN SSH SIGNATURE-----\n{}\n-----END SSH SIGNATURE-----\n",
        STANDARD.encode(binary)
    )
    .into_bytes()
}

// Independent OpenSSH fixtures are appended below. Only public keys' fingerprints
// and signatures are retained; no signing key is part of the repository.

const MESSAGE: &[u8] = b"hepta native SSHSIG independent interoperability fixture\n";
const FINGERPRINT: &str = "SHA256:MCc0LyTcIzJn0PegfMmAORR5i4KgM+2K6ykCMsX7R2Y";
const OTHER_FINGERPRINT: &str = "SHA256:hqUir0E273VtpNsmN0PG0B6/XfFcdTH8pvyZbv9WCAI";
const OPENSSH_SHA256: &[u8] = b"-----BEGIN SSH SIGNATURE-----
U1NIU0lHAAAAAQAAADMAAAALc3NoLWVkMjU1MTkAAAAgGKOwEq8wpCeR62xgG+lxDkavAX
Qba1uCOeKv3HK/HxwAAAAiaGVwdGEtdm5leHQtb3BlcmF0b3ItYWNjZXB0YW5jZS12MQAA
AAAAAAAGc2hhMjU2AAAAUwAAAAtzc2gtZWQyNTUxOQAAAEAlQacjUkwVD7j+XYESMWgGQt
HpQcboyRQA5RwmphUX7jJh+hXk8Ox3dSy5T8dELIVK6w7ViVPHyB1CJU1GylIB
-----END SSH SIGNATURE-----
";
const OPENSSH_SHA512: &[u8] = b"-----BEGIN SSH SIGNATURE-----
U1NIU0lHAAAAAQAAADMAAAALc3NoLWVkMjU1MTkAAAAgGKOwEq8wpCeR62xgG+lxDkavAX
Qba1uCOeKv3HK/HxwAAAAiaGVwdGEtdm5leHQtb3BlcmF0b3ItYWNjZXB0YW5jZS12MQAA
AAAAAAAGc2hhNTEyAAAAUwAAAAtzc2gtZWQyNTUxOQAAAEA6hR+24E4J3lkHvJaT1TBCZm
qSSYuctNUICqG5wiyJkGZ+6UTPAwImwi796UMIYD+omdp4F+pEYJya+JY22qUN
-----END SSH SIGNATURE-----
";
const OTHER_SIGNATURE: &[u8] = b"-----BEGIN SSH SIGNATURE-----
U1NIU0lHAAAAAQAAADMAAAALc3NoLWVkMjU1MTkAAAAgjtGEcWyePVfATZCy04z2y2/vGe
5r06/MILcjhsX7hhIAAAAiaGVwdGEtdm5leHQtb3BlcmF0b3ItYWNjZXB0YW5jZS12MQAA
AAAAAAAGc2hhNTEyAAAAUwAAAAtzc2gtZWQyNTUxOQAAAEDFemwZFk2r+e7KlPp00XfpQW
91AT45+8V0UsKs3/y4svZj8quBjYmJp8T5sjiYqoEmzUwRZwDXIHwxsP+dKosE
-----END SSH SIGNATURE-----
";
