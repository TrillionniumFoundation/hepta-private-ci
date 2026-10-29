"""Bind focused compatibility checks to the actual repaired source files."""

import hashlib
import json
from pathlib import Path
import tomllib


REPO = Path('/workspace/scratch/07399998a2e3/hepta-deny-repair')
DEST = Path('/workspace/scratch/07399998a2e3/recovery/dependencies/compatibility')

I18N_TESTS = r'''
#[test]
fn maintained_toml_parser_loads_actual_crate_and_locale_files() {
    let directory = tempfile::tempdir().unwrap();
    std::fs::write(directory.path().join("Cargo.toml"),
        "[package]\nname = 'i18n-check'\nversion = '1.2.3'\n").unwrap();
    std::fs::write(directory.path().join("i18n.toml"),
        "fallback_language = 'en-US'\nsubcrates = ['child']\n").unwrap();
    let value = i18n_config::Crate::from(directory.path(), None, "i18n.toml").unwrap();
    let locale = value.i18n_config.unwrap();
    assert_eq!((value.name, value.version, locale.fallback_language.to_string(), locale.subcrates),
        ("i18n-check".to_string(), "1.2.3".to_string(), "en-US".to_string(), vec![std::path::PathBuf::from("child")]));
}

#[test]
fn malformed_locale_retains_source_path_in_real_error_type() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("i18n.toml");
    std::fs::write(&path,
        "fallback_language = 'en-US'\nfallback_language = 'fr'\n").unwrap();
    match i18n_config::I18nConfig::from_file(&path) {
        Err(i18n_config::I18nConfigError::CannotDeserializeToml(actual, error)) => {
            assert_eq!(actual, path);
            assert!(error.to_string().contains("duplicate key"));
        }
        other => panic!("unexpected parser outcome: {other:?}"),
    }
}
'''

AWS_IMPORTS = r'''
use aws_smithy_json::serialize::JsonObjectWriter;
use aws_smithy_types::Number;
use p256::ecdsa::signature::RandomizedSigner;
use p256::ecdsa::{Signature, SigningKey};
use p256::elliptic_curve::sec1::ToSec1Point;
use p256::SecretKey;
use std::time::SystemTime;

// Only the enclosing SDK error carrier is a shim; the tested DPoP functions,
// JSON writer, entropy source and cryptography below are the actual sources.
#[derive(Debug)]
struct LoginTokenError;
impl LoginTokenError {
    fn other(_: impl Into<String>, _: Option<Box<dyn std::error::Error + Send + Sync>>) -> Self {
        Self
    }
}
'''

AWS_TESTS = r'''
#[cfg(test)]
mod tests {
    use super::*;
    use p256::ecdsa::signature::Verifier;
    use p256::ecdsa::VerifyingKey;

    fn issued_token() -> (Vec<String>, VerifyingKey) {
        let key = SecretKey::from_slice(&[7_u8; 32]).unwrap();
        let token = calculate(&key, "https://example.invalid/oauth/token",
            SystemTime::UNIX_EPOCH + std::time::Duration::from_secs(1_000)).unwrap();
        let parts: Vec<_> = token.split('.').map(str::to_owned).collect();
        assert_eq!(parts.len(), 3);
        let header: serde_json::Value = serde_json::from_slice(
            &base64_simd::URL_SAFE_NO_PAD.decode_to_vec(&parts[0]).unwrap()).unwrap();
        assert_eq!(header["typ"], "dpop+jwt");
        assert_eq!(header["alg"], "ES256");
        assert_eq!(header["jwk"]["crv"], "P-256");
        let mut point = vec![4];
        for coordinate in ["x", "y"] {
            point.extend(base64_simd::URL_SAFE_NO_PAD.decode_to_vec(
                header["jwk"][coordinate].as_str().unwrap()).unwrap());
        }
        let verifier = VerifyingKey::from_sec1_bytes(&point).unwrap();
        (parts, verifier)
    }

    #[test]
    fn real_dpop_signature_verifies_against_its_reconstructed_jwk() {
        let (parts, verifier) = issued_token();
        let payload: serde_json::Value = serde_json::from_slice(
            &base64_simd::URL_SAFE_NO_PAD.decode_to_vec(&parts[1]).unwrap()).unwrap();
        assert_eq!(payload["htm"], "POST");
        assert_eq!(payload["htu"], "https://example.invalid/oauth/token");
        assert_eq!(payload["iat"], 1_000);
        uuid::Uuid::parse_str(payload["jti"].as_str().unwrap()).unwrap();
        let signature = Signature::from_slice(
            &base64_simd::URL_SAFE_NO_PAD.decode_to_vec(&parts[2]).unwrap()).unwrap();
        verifier.verify(format!("{}.{}", parts[0], parts[1]).as_bytes(), &signature).unwrap();
    }

    #[test]
    fn reconstructed_jwk_rejects_a_changed_signed_message() {
        let (parts, verifier) = issued_token();
        let signature = Signature::from_slice(
            &base64_simd::URL_SAFE_NO_PAD.decode_to_vec(&parts[2]).unwrap()).unwrap();
        assert!(verifier.verify(format!("{}.{}x", parts[0], parts[1]).as_bytes(), &signature).is_err());
    }
}
'''


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    (DEST / 'src').mkdir(exist_ok=True)
    manifest = tomllib.loads((REPO / 'codex-rs/Cargo.toml').read_text())
    lock = tomllib.loads((REPO / 'codex-rs/Cargo.lock').read_text())['package']
    dependencies = {}
    for name in ['aws-smithy-json', 'aws-smithy-types', 'base64-simd', 'p256', 'serde_json', 'tempfile', 'uuid']:
        values = {value['version'] for value in lock if value['name'] == name}
        if len(values) != 1:
            raise ValueError(f'Ambiguous dependency {name}: {values}')
        dependencies[name] = next(iter(values))
    lines = ['[workspace]', '[package]', 'name = "hepta-dependency-compatibility"',
             'version = "0.0.0"', 'edition = "2024"', '[dependencies]']
    for name, version in dependencies.items():
        features = ', features = ["v4"]' if name == 'uuid' else ''
        lines.append(f'{name} = {{ version = "={version}"{features} }}')
    lines.append('rand = { version = "=0.10.3", default-features = false, features = ["std", "sys_rng"] }')
    lines.append('pretty_assertions = "1"')
    lines.append('i18n-config = { path = ' + json.dumps(str(REPO / 'codex-rs/third_party/i18n-config-0.4.8')) + ' }')
    zip_features = manifest['workspace']['dependencies']['zip']['features']
    lines.append('zip = { version = "=9.1.3", default-features = false, features = ' + json.dumps(zip_features) + ' }')
    (DEST / 'Cargo.toml').write_text('\n'.join(lines) + '\n')

    zip_source_path = REPO / 'codex-rs/core-plugins/src/startup_sync.rs'
    zip_test_path = REPO / 'codex-rs/core-plugins/src/startup_sync_tests.rs'
    aws_path = REPO / 'codex-rs/third_party/aws-config-1.13.0/src/login/dpop.rs'
    zip_source = zip_source_path.read_text().split('fn extract_zipball_to_dir(', 1)[1]
    zip_source = 'fn extract_zipball_to_dir(' + zip_source.split('#[cfg(test)]', 1)[0]
    zip_test = zip_test_path.read_text().split('#[cfg(unix)]\n#[test]\nfn extraction_strips_', 1)[1]
    zip_test = '#[cfg(unix)]\n#[test]\nfn extraction_strips_' + zip_test.split('#[tokio::test]', 1)[0]
    zip_code = 'use std::path::{Path,PathBuf};\nuse zip::ZipArchive;\n' + zip_source
    zip_code += '\n#[cfg(test)]\nmod tests {\nuse super::*;\nuse std::io::Write;\nuse tempfile::tempdir;\nuse zip::ZipWriter;\nuse zip::write::SimpleFileOptions;\nuse pretty_assertions::assert_eq;\n'
    zip_code += zip_test + '\n}\n'
    aws = aws_path.read_text().split('pub(super) struct Header', 1)[1]
    aws = 'pub(super) struct Header' + aws.split('/// Auth scheme ID for DPoP', 1)[0]
    (DEST / 'src/zip_actual.rs').write_text(zip_code)
    (DEST / 'src/aws_actual.rs').write_text(AWS_IMPORTS + aws + AWS_TESTS)
    (DEST / 'src/lib.rs').write_text('mod zip_actual;\nmod aws_actual;\n#[cfg(test)]\nmod i18n_tests {\n' + I18N_TESTS + '\n}\n')
    evidence = {
        'full_source_sha256': {str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest()
                               for path in [zip_source_path, zip_test_path, aws_path]},
        'zip_function_bytes_sha256': hashlib.sha256(zip_source.encode()).hexdigest(),
        'zip_original_test_sha256': hashlib.sha256(zip_test.encode()).hexdigest(),
        'aws_function_bytes_sha256': hashlib.sha256(aws.encode()).hexdigest(),
        'i18n_library': 'Complete actual patched vendored library compiled through path dependency.',
        'aws_scope': 'Actual Header/Payload/JWK/message/sign/calculate functions, real AWS JSON writer and real crypto crates; surrounding SDK error carrier shim only. Not a whole AWS SDK build.',
        'expected_tests': 5,
    }
    (DEST / 'SOURCE_BINDING.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps({'destination': str(DEST), 'expected_tests': 5}))


if __name__ == '__main__':
    main()
