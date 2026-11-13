use super::*;

use std::fs::OpenOptions;
use std::os::unix::fs::PermissionsExt;

use codex_hepta_context_compiler::ContextAdmissionBindingV2;
use codex_hepta_context_compiler::ContextModelProfileV2;
use codex_hepta_context_compiler::ContextRoleV2;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::json;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn write_file(path: &Path, bytes: &[u8], mode: u32) {
    std::fs::write(path, bytes).expect("write test file");
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(mode))
        .expect("set test permissions");
}

struct AdmissionFixture {
    authority: ExternalContextAdmissionAuthorityV3,
    trust_path: PathBuf,
    record: ContextAdmissionRecordV2,
    snapshot: ContextAdmissionSnapshotV2,
}

fn admission_fixture(root: &Path) -> AdmissionFixture {
    let rollback_root = root.join("agent-home");
    let external_root = root.join("external-authority");
    std::fs::create_dir_all(&rollback_root).expect("rollback root");
    std::fs::create_dir_all(&external_root).expect("external root");
    let rollback_root = rollback_root.canonicalize().expect("canonical rollback root");
    let external_root = external_root.canonicalize().expect("canonical external root");

    let authority_id = id("authority:context:v3");
    let key_epoch = 7;
    let signing_key = SigningKey::from_bytes(&[71; 32]);
    let scope_digest = digest("scope:context:v3");
    let authority_domain_digest = digest("authority-domain:context:v3");
    let snapshot = ContextAdmissionSnapshotV2::new(
        id("snapshot:context:v3"),
        scope_digest,
        authority_domain_digest,
        100,
        1,
        Vec::new(),
        true,
        None,
    )
    .expect("snapshot");
    let record = ContextAdmissionRecordV2::new(
        id("admission:context:v3"),
        ContextAdmissionBindingV2 {
            item_id: id("item:context:v3"),
            role: ContextRoleV2::TrustedInstruction,
            content_digest: digest("content:context:v3"),
            source_digest: digest("source:context:v3"),
            generation_vector_digest: digest("generation:context:v3"),
            scope_digest,
            authority_domain_digest,
            contains_secret: false,
        },
        50,
        500,
    )
    .expect("record");

    let record_signature = signing_key
        .sign(&context_admission_record_signing_bytes_v3(
            &authority_id,
            key_epoch,
            record.record_digest,
        ))
        .to_bytes();
    let snapshot_signature = signing_key
        .sign(&context_admission_snapshot_signing_bytes_v3(
            &authority_id,
            key_epoch,
            snapshot.snapshot_digest,
        ))
        .to_bytes();
    let trust_path = external_root.join("trust.json");
    let bundle_path = external_root.join("bundle.json");
    write_file(
        &trust_path,
        serde_json::to_vec(&json!({
            "schemaVersion": 3,
            "authorityId": authority_id.as_str(),
            "keyEpoch": key_epoch,
            "publicKeyHex": hex(&signing_key.verifying_key().to_bytes()),
            "revoked": false
        }))
        .expect("trust json")
        .as_slice(),
        0o600,
    );
    write_file(
        &bundle_path,
        serde_json::to_vec(&json!({
            "schemaVersion": 3,
            "authorityId": authority_id.as_str(),
            "keyEpoch": key_epoch,
            "records": [{
                "digestHex": record.record_digest.to_string(),
                "signatureHex": hex(&record_signature)
            }],
            "snapshots": [{
                "digestHex": snapshot.snapshot_digest.to_string(),
                "signatureHex": hex(&snapshot_signature)
            }]
        }))
        .expect("bundle json")
        .as_slice(),
        0o600,
    );
    let view = load_admission_authority_view(
        &trust_path,
        &bundle_path,
        &rollback_root,
        None,
    )
    .expect("load authority view");
    let authority = ExternalContextAdmissionAuthorityV3 {
        trust_path: trust_path.clone(),
        bundle_path,
        rollback_root,
        expected_authority_id: view.authority_id,
        expected_key_epoch: view.key_epoch,
        expected_verifying_key: view.verifying_key_bytes,
        verifier_digest: view.verifier_digest,
    };
    AdmissionFixture {
        authority,
        trust_path,
        record,
        snapshot,
    }
}

#[test]
fn signed_admission_authority_reloads_and_honors_revocation() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let fixture = admission_fixture(temporary.path());
    assert!(fixture.authority.verify_record(&fixture.record));
    assert!(fixture.authority.verify_snapshot(&fixture.snapshot));

    let mut trust: serde_json::Value = serde_json::from_slice(
        &std::fs::read(&fixture.trust_path).expect("read trust"),
    )
    .expect("parse trust");
    trust["revoked"] = serde_json::Value::Bool(true);
    write_file(
        &fixture.trust_path,
        serde_json::to_vec(&trust).expect("encode trust").as_slice(),
        0o600,
    );
    assert!(!fixture.authority.verify_record(&fixture.record));
    assert!(!fixture.authority.verify_snapshot(&fixture.snapshot));
}

#[test]
fn unsigned_or_wrongly_signed_digest_is_rejected() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let fixture = admission_fixture(temporary.path());
    let bundle_path = &fixture.authority.bundle_path;
    let mut bundle: serde_json::Value =
        serde_json::from_slice(&std::fs::read(bundle_path).expect("read bundle"))
            .expect("parse bundle");
    bundle["records"][0]["signatureHex"] = serde_json::Value::String(hex(&[0; 64]));
    write_file(
        bundle_path,
        serde_json::to_vec(&bundle).expect("encode bundle").as_slice(),
        0o600,
    );
    assert!(!fixture.authority.verify_record(&fixture.record));
}

struct TokenizerFixture {
    tokenizer: PinnedTokenizerProcessV3,
    vocabulary_path: PathBuf,
    product_profile: ContextModelProfileRevisionV2,
}

fn tokenizer_fixture(root: &Path, script_body: &str, timeout: Duration) -> TokenizerFixture {
    let rollback_root = root.join("agent-home");
    let external_root = root.join("tokenizer-deployment");
    std::fs::create_dir_all(&rollback_root).expect("rollback root");
    std::fs::create_dir_all(&external_root).expect("external root");
    let rollback_root = rollback_root.canonicalize().expect("canonical rollback root");
    let external_root = external_root.canonicalize().expect("canonical external root");
    let binary_path = external_root.join("tokenizer");
    let vocabulary_path = external_root.join("vocabulary.json");
    let normalization_path = external_root.join("normalization.json");
    write_file(&binary_path, script_body.as_bytes(), 0o500);
    write_file(&vocabulary_path, b"{\"vocabulary\":\"test\"}", 0o400);
    write_file(
        &normalization_path,
        b"{\"normalization\":\"identity\"}",
        0o400,
    );

    let tokenizer_digest = digest("tokenizer:test:v3");
    let base_profile = ContextModelProfileV2 {
        model_digest: digest("model:test:v3"),
        provider_id_digest: digest("provider:test:v3"),
        provider_model_digest: digest("model:test:v3"),
        tokenizer_digest,
        serializer_digest: digest("serializer:test:v3"),
        template_digest: digest("template:test:v3"),
        tool_schema_digest: digest("tool-schema:test:v3"),
        maximum_context_tokens: 16_384,
    };
    let product_profile = ContextModelProfileRevisionV2 {
        profile_id: id("profile:test:v3"),
        base_profile,
        provider_revision_digest: digest("provider-revision:test:v3"),
        model_revision_digest: digest("model-revision:test:v3"),
        tokenizer_binary_digest: Digest32::of_bytes(script_body.as_bytes()),
        tokenizer_vocabulary_digest: Digest32::of_bytes(b"{\"vocabulary\":\"test\"}"),
        tokenizer_normalization_digest: Digest32::of_bytes(
            b"{\"normalization\":\"identity\"}",
        ),
        serializer_revision_digest: digest("serializer-revision:test:v3"),
        template_revision_digest: digest("template-revision:test:v3"),
        tool_schema_revision_digest: digest("tool-schema-revision:test:v3"),
        role_profile_digest: digest("role-profile:test:v3"),
    };
    let tokenizer = PinnedTokenizerProcessV3 {
        binary_path,
        vocabulary_path: vocabulary_path.clone(),
        normalization_path,
        rollback_root,
        tokenizer_digest,
        product_profile_digest: product_profile.digest(),
        binary_digest: product_profile.tokenizer_binary_digest,
        vocabulary_digest: product_profile.tokenizer_vocabulary_digest,
        normalization_digest: product_profile.tokenizer_normalization_digest,
        timeout,
    };
    tokenizer.verify_artifacts().expect("verify artifacts");
    TokenizerFixture {
        tokenizer,
        vocabulary_path,
        product_profile,
    }
}

const EXACT_TOKENIZER_SCRIPT: &str = r#"#!/usr/bin/python3
import hashlib
import json
import sys

args = sys.argv[1:]
try:
    digest = args[args.index("--tokenizer-digest") + 1]
except (ValueError, IndexError):
    sys.exit(11)
data = sys.stdin.buffer.read()
print(json.dumps({
    "schemaVersion": 1,
    "tokenizerDigest": digest,
    "inputSha256": hashlib.sha256(data).hexdigest(),
    "tokenCount": len(data),
}, separators=(",", ":")))
"#;

#[test]
fn pinned_tokenizer_counts_the_exact_input_bytes() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let fixture = tokenizer_fixture(
        temporary.path(),
        EXACT_TOKENIZER_SCRIPT,
        Duration::from_secs(5),
    );
    let input = b"exact provider-visible bytes";
    assert_eq!(
        fixture.tokenizer.count_tokens(input).expect("token count"),
        u64::try_from(input.len()).expect("input length")
    );
    let rendered = format!("{:?}", fixture.tokenizer);
    assert!(!rendered.contains(temporary.path().to_string_lossy().as_ref()));
    assert_eq!(
        fixture.tokenizer.product_profile_digest,
        fixture.product_profile.digest()
    );
}

#[test]
fn tokenizer_artifact_drift_is_detected_before_use() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let fixture = tokenizer_fixture(
        temporary.path(),
        EXACT_TOKENIZER_SCRIPT,
        Duration::from_secs(5),
    );
    let mut file = OpenOptions::new()
        .write(true)
        .truncate(true)
        .open(&fixture.vocabulary_path)
        .expect("open vocabulary");
    file.write_all(b"drifted vocabulary")
        .expect("write drift");
    drop(file);
    assert!(matches!(
        fixture.tokenizer.invoke(b"input"),
        Err(AgentdPromptCompilerAdapterErrorV3::TokenizerArtifactMismatch)
    ));
}

#[test]
fn tokenizer_timeout_kills_the_child_and_fails_closed() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let script = r#"#!/usr/bin/python3
import time
time.sleep(5)
"#;
    let fixture = tokenizer_fixture(temporary.path(), script, Duration::from_millis(20));
    assert!(matches!(
        fixture.tokenizer.invoke(b"input"),
        Err(AgentdPromptCompilerAdapterErrorV3::TokenizerTimedOut)
    ));
}
