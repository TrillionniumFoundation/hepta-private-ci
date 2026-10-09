//! Numerical consumer integration, not production authorization. Fixture keys
//! authorize this test process only; upstream owner qualification remains absent.
use super::*;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::collections::BTreeSet;

#[test]
#[ignore = "requires staged pretrained base and an actually trained owner adapter"]
fn real_pretrained_adapter_runs_through_native_effect_consumer() {
    let python = PathBuf::from(std::env::var("HEPTA_MEMORY_PYTHON").expect("staged Python"));
    let program =
        PathBuf::from(std::env::var("HEPTA_MEMORY_SERVING_PROGRAM").expect("serving program"));
    let model = PathBuf::from(std::env::var("HEPTA_MEMORY_MODEL_DIR").expect("staged model"));
    let evidence =
        PathBuf::from(std::env::var("HEPTA_MEMORY_EVIDENCE_DIR").expect("evidence directory"));
    let payload = bounded_read(&evidence.join("adapter.safetensors"), 64 * 1024 * 1024)
        .expect("actual adapter");
    assert!(payload.len() >= 10, "bounded tensor header");
    let header_size = usize::try_from(u64::from_le_bytes(
        payload[..8].try_into().expect("tensor header"),
    ))
    .expect("header fits usize");
    assert!((2..=1024 * 1024).contains(&header_size) && header_size <= payload.len() - 8);
    let header: serde_json::Value =
        serde_json::from_slice(&payload[8..8 + header_size]).expect("tensor metadata");
    let metadata = &header["__metadata__"];
    let field = |key: &str| {
        metadata[key]
            .as_str()
            .expect("bound metadata field")
            .to_owned()
    };
    let scratch = tempfile::tempdir().expect("scratch directory");
    let process = MemoryServingProcessV1::new(MemoryServingProcessConfigV1 {
        interpreter_digest: Digest32::of_bytes(&fs::read(&python).expect("interpreter bytes")),
        python_executable: python,
        code_digest: MemoryServingProcessV1::code_digest(&program).expect("code identity"),
        program,
        model_directory: model,
        scratch_root: scratch.path().to_owned(),
    })
    .expect("native process installation");
    let job = MemoryServingJobV1 {
        schema: "hepta.memory-serving.job.v1",
        request_id: "real-pretrained-serving-fixture".into(),
        subject_id: "fixture.agent".into(),
        destination_id: "fixture.node".into(),
        route_generation: 1,
        base_digest: field("base_digest"),
        encoder_digest: field("base_digest"),
        payload_digest: Digest32::of_bytes(&payload).to_string(),
        scope_digest: field("scope_digest"),
        selection_digest: Digest32::of_bytes(b"fixture selection: not production").to_string(),
        qualification_digest: Digest32::of_bytes(b"fixture qualification: not production")
            .to_string(),
        source_support_digest: field("source_support_digest"),
        training_job_digest: field("job_digest"),
        trainer_digest: field("trainer_digest"),
        runtime_digest: process.runtime_digest().to_string(),
        interpreter_digest: process.interpreter_digest().to_string(),
        question: "What operational procedure was learned from the permitted history?".into(),
        question_time: "2026-10-09T00:00:00Z".into(),
        deadline_unix_millis: now_ms().expect("clock") + 240_000,
    };
    let key = SigningKey::from_bytes(&[94; 32]);
    let authority_root = tempfile::tempdir().expect("test authority");
    use std::os::unix::fs::PermissionsExt;
    fs::set_permissions(authority_root.path(), fs::Permissions::from_mode(0o700))
        .expect("private authority");
    let authority = FinalUseAuthority::open_state_dir(
        authority_root.path(),
        "pretrained-fixture-issuer".into(),
        key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("test authority owner");
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "pretrained-fixture-issuer".into(),
        authority_epoch: 1,
        grant_id: "pretrained-use.1".into(),
        nonce: [27; 32],
        binding: job.binding().expect("exact model/query/code binding"),
        not_before_unix_ms: now_ms().expect("clock") - 1,
        expires_at_unix_ms: job.deadline_unix_millis,
    };
    let signature = key
        .sign(&grant.signing_bytes().expect("canonical grant"))
        .to_bytes()
        .to_vec();
    let signed = SignedFinalUseGrant { grant, signature };
    let token = authority
        .claim(&signed, &signed.grant.binding)
        .expect("single effect claim");
    let job_digest = Digest32::of_bytes(&serde_json::to_vec(&job).expect("job bytes"));
    let output = process
        .execute(job, payload, token, CancellationToken::new())
        .expect("actual pretrained serving");
    assert!(!output.answer().trim().is_empty());
    assert_eq!(
        fs::read_dir(scratch.path())
            .expect("scratch listing")
            .count(),
        0
    );
    assert!(authority.claim(&signed, &signed.grant.binding).is_err());
    let receipt = serde_json::json!({
        "schema": "hepta.memory-serving.pretrained-fixture.v1",
        "actual_pretrained_base": true,
        "actual_owner_trained_adapter": true,
        "raw_replay_delivered": false,
        "fixture_authority": true,
        "production_qualified": false,
        "job_digest": job_digest.to_string(),
        "answer": output.answer(),
        "answer_digest": output.answer_digest().to_string(),
        "prompt_digest": output.prompt_digest().to_string(),
        "usage": output.usage(),
        "final_use_witness": output.final_use_witness(),
    });
    fs::write(
        evidence.join("native-serving.json"),
        serde_json::to_vec_pretty(&receipt).expect("receipt"),
    )
    .expect("retained receipt");
}
