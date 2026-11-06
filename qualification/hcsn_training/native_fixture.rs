//! Engineering-only bridge fixture. The fixed synthetic signing key is NOT production trust.
//! Each invocation is a new process. Candidate publication never grants adoption authority.
use codex_hepta_learning_artifacts::*;
use codex_hepta_neuron::*;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::json;
use serde_json::Value;
use std::error::Error;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::{self};
use std::io::Write;
use std::path::Path;

type Result<T> = std::result::Result<T, Box<dyn Error>>;
fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixed fixture identifier")
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn number(value: &Value, key: &str) -> u64 {
    value[key].as_u64().expect("fixture integer")
}
fn hash(value: &Value, key: &str) -> Digest32 {
    value[key]
        .as_str()
        .expect("fixture digest")
        .parse()
        .expect("SHA256")
}
fn read(root: &Path, name: &str) -> Result<Value> {
    Ok(serde_json::from_slice(&fs::read(root.join(name))?)?)
}
fn write(root: &Path, name: &str, bytes: &[u8]) -> Result<()> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(root.join(name))?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}
fn record(root: &Path, name: &str, value: Value) -> Result<()> {
    write(root, name, &serde_json::to_vec_pretty(&value)?)
}
fn identity(binding: &Value, model_digest: Digest32) -> HcsnClockIdentityV1 {
    HcsnClockIdentityV1 {
        clock_epoch: hash(binding, "clock_epoch"),
        scope_digest: hash(binding, "scope_digest"),
        generation: Generation::new(number(binding, "generation")).unwrap(),
        writer_epoch: number(binding, "writer_epoch"),
        model_digest,
    }
}
fn expected(root: &Path) -> Result<HcsnTrainingBindingV1> {
    // This file is created by the caller BEFORE worker dispatch, never copied from its handoff.
    let v = read(root, "admitted.json")?;
    Ok(HcsnTrainingBindingV1 {
        operation_id: id(v["operation_id"].as_str().unwrap()),
        request_digest: hash(&v, "request_digest"),
        training_code_digest: hash(&v, "training_code_digest"),
        runtime_tuple_digest: hash(&v, "runtime_tuple_digest"),
        graph_digest: hash(&v, "graph_digest"),
        time_profile_digest: hash(&v, "time_profile_digest"),
        base_checkpoint_digest: hash(&v, "base_checkpoint_digest"),
        dataset_digest: hash(&v, "dataset_digest"),
        target_generation: Generation::new(number(&v, "target_generation"))?,
        optimizer_steps: number(&v, "optimizer_steps"),
        logical_cells: number(&v, "logical_cells").try_into()?,
        trainable_parameters: number(&v, "trainable_parameters"),
    })
}
fn config(root: &Path) -> (LearningArtifactOwnerServiceConfigV1, SigningKey) {
    let key = SigningKey::from_bytes(&[19; 32]); // Publicly known synthetic TEST key only.
    let scope = DatasetWithdrawalScopeV1 {
        authority_domain_id: id("fixture-authority"),
        registry_id: id("fixture-withdrawals"),
        scope_id: id("fixture-scope"),
    };
    let signer = TrustedArtifactSignerV1 {
        signer_id: id("fixture-signer"),
        verifying_key: key.verifying_key().to_bytes(),
        minimum_authority_epoch: 1,
        maximum_authority_epoch: 1,
        valid_from: 1,
        expires_at: 1000,
        revoked_at: None,
    };
    let trust = ArtifactOwnerTrustV1 {
        registry_id: id("fixture-artifacts"),
        withdrawal_scope_digest: scope.digest(),
        minimum_registry_generation: Generation::new(1).unwrap(),
        genesis_predecessor_head_digest: Digest32::ZERO,
        minimum_authority_epoch: 1,
        writer_signers: vec![signer.clone()],
        head_signers: vec![signer],
    };
    let mut lease = SignedArtifactWriterLeaseV1 {
        lease_id: id("fixture-lease"),
        producer_id: id("fixture-worker"),
        registry_id: id("fixture-artifacts"),
        withdrawal_scope_digest: scope.digest(),
        signer_id: id("fixture-signer"),
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        authority_epoch: 1,
        lease_generation: 1,
        issued_at: 1,
        expires_at: 1000,
        signature: [0; 64],
    };
    lease.signature = key.sign(&lease.signing_bytes()).to_bytes();
    (
        LearningArtifactOwnerServiceConfigV1 {
            root: root.join("artifact-store"),
            trust,
            writer_lease: lease,
            required_current_head: None,
            withdrawal_registry: DatasetWithdrawalRegistry::new_scoped(scope),
            storage_binding: digest("fixture-storage"),
            now: 10,
        },
        key,
    )
}
fn signed_head(
    config: &LearningArtifactOwnerServiceConfigV1,
    key: &SigningKey,
    head: Digest32,
) -> SignedCurrentArtifactHeadV1 {
    let mut signed = SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: config.trust.withdrawal_scope_digest,
        binding: config.storage_binding,
        witness: RegistryHeadWitnessV1 {
            registry_id: id("fixture-artifacts"),
            generation: Generation::new(1).unwrap(),
            head_digest: head,
            predecessor_head_digest: Digest32::ZERO,
            authority_epoch: 1,
            signer_id: id("fixture-signer"),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            issued_at: 10,
            expires_at: 1000,
        },
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    signed
}
fn plan(root: &Path) -> Result<()> {
    let input = read(root, "clock-input.json")?;
    let profile: HcsnTimeProfileV1 = serde_json::from_value(input["profile"].clone())?;
    let ident = identity(&input["binding"], hash(&input["binding"], "model_digest"));
    let anchor = HcsnClockCheckpointV1::initial(
        &profile,
        ident,
        number(&input, "start_micros"),
        hash(&input, "initial_state_digest"),
    )?;
    let ends: Vec<u64> = serde_json::from_value(input["ends"].clone())?;
    let plans = plan_hcsn_batch_v1(&profile, ident, &anchor, &ends)?;
    write(root, "training-clock.json", &anchor.encode()?)?;
    record(
        root,
        "training-plan.json",
        json!({"profile":profile,"intervals":plans,
        "anchor_digest":anchor.digest().to_string(),"state_digest":anchor.state_digest().to_string(),
        "model_digest":ident.model_digest.to_string(),"pid":std::process::id()}),
    )
}
fn publish(root: &Path) -> Result<()> {
    let expected = expected(root)?;
    let handoff = fs::read(root.join("worker/handoff.bin"))?;
    let diagnostics = fs::read(root.join("worker/receipt.json"))?;
    let payload = fs::read(root.join("worker/candidate.pt"))?;
    let outcome = decode_hcsn_handoff_v1(&expected.operation_id, &handoff)?;
    let (config, key) = config(root);
    fs::create_dir(&config.root)?;
    let manifest = LearningArtifactManifestV2 {
        artifact_id: id("hcsn-fixture-candidate"),
        kind: ArtifactKind::Model,
        generation: expected.target_generation,
        provenance_mode: ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![expected.dataset_digest],
        lineage_digests: vec![
            expected.request_digest,
            expected.graph_digest,
            expected.time_profile_digest,
            expected.base_checkpoint_digest,
            outcome.gradient_digest,
            outcome.receipt_digest,
            Digest32::of_bytes(&handoff),
        ],
        predecessor_ids: Vec::new(),
        rollback_predecessor: None,
        bytes_digest: Digest32::of_bytes(&payload),
        encoded_size_bytes: payload.len() as u64,
        training_code_digest: expected.training_code_digest,
        runtime_tuple_digest: expected.runtime_tuple_digest,
        device_profile_digest: digest("fixture-cpu"),
        objective_class_digest: digest("fixture-task-mse"),
        compatibility_digest: expected.graph_digest,
        schema_profile_digest: digest("fixture-tensor-checkpoint-v1"),
        normalization_digest: digest("identity"),
        producer_id: id("fixture-worker"),
        created_at: 1,
        expires_at: 1000,
    };
    let admission = admit_manifest_at_withdrawal_head_v3(
        &config.withdrawal_registry,
        config.withdrawal_registry.head_digest(),
        manifest,
        10,
    )?;
    let host = LearningArtifactOwnerHost::open(
        &config.root,
        config.trust.clone(),
        config.writer_lease.clone(),
        10,
    )?;
    let mut registry = ArtifactRegistry::new();
    let tx = ArtifactPublicationTransactionV1::begin(
        expected.operation_id.clone(),
        admission.clone(),
        &config.withdrawal_registry,
        &registry,
        Digest32::ZERO,
        10,
    )?;
    host.stage_compatibility_registration(&tx, &mut registry, 10)?;
    drop(host);
    let request = LearningArtifactPublishRequestV1 {
        operation_id: expected.operation_id.clone(),
        admission,
        payload,
        signed_current_head: signed_head(&config, &key, registry.snapshot().head_digest),
        expected_registry_predecessor_head: Digest32::ZERO,
        now: 10,
    };
    let mut wrong = expected.clone();
    wrong.dataset_digest = digest("wrong-dispatch-dataset");
    assert_eq!(
        prepare_hcsn_publication_v1(&wrong, &handoff, &diagnostics, request.clone()).err(),
        Some(HcsnCandidateErrorV1::RequestMismatch)
    );
    let mut corrupt_receipt = diagnostics.clone();
    corrupt_receipt.push(b' ');
    assert_eq!(
        prepare_hcsn_publication_v1(&expected, &handoff, &corrupt_receipt, request.clone()).err(),
        Some(HcsnCandidateErrorV1::IncompleteBackpropagation)
    );
    let prepared = prepare_hcsn_publication_v1(&expected, &handoff, &diagnostics, request)?;
    let mut owner = LearningArtifactOwnerService::open(config.clone())?;
    assert!(LearningArtifactOwnerService::open(config).is_err());
    let receipt = prepared.clone().publish(&mut owner)?;
    assert_eq!(prepared.publish(&mut owner)?, receipt);
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(
        owner.registry().state(&id("hcsn-fixture-candidate")),
        Some(ArtifactState::Candidate)
    );
    record(
        root,
        "publication.json",
        json!({"candidate_digest":outcome.candidate_digest.to_string(),
        "registry_head_digest":receipt.registry_head_digest.to_string(),"witness_digest":receipt.witness_digest.to_string(),
        "publication_state_digest":receipt.state_digest.to_string(),"admission_digest":receipt.admission_digest.to_string(),
        "acknowledged_at":receipt.acknowledged_at,"candidate_only":true,"authority":"DENY_ALL",
        "synthetic_test_trust":true,"production_trust":false,"retry_same_receipt":true,
        "wrong_dispatch_rejected":true,"changed_receipt_rejected":true,"second_writer_rejected":true,
        "pid":std::process::id()}),
    )
}
fn reopen(root: &Path) -> Result<()> {
    let publication = read(root, "publication.json")?;
    let candidate = hash(&publication, "candidate_digest");
    let (mut config, key) = config(root);
    config.required_current_head = Some(signed_head(
        &config,
        &key,
        hash(&publication, "registry_head_digest"),
    ));
    let owner = LearningArtifactOwnerService::open(config.clone())?;
    assert!(owner.recovery_required().is_none());
    assert_eq!(
        owner.registry().snapshot().head_digest,
        hash(&publication, "registry_head_digest")
    );
    let name = format!("hcsn-fixture-candidate-{candidate}.bin");
    let payload = read_candidate_payload(
        File::open(config.root.join("payloads").join(name))?,
        owner.registry(),
        &id("hcsn-fixture-candidate"),
    )?;
    assert_eq!(Digest32::of_bytes(&payload), candidate);
    write(root, "readback.pt", &payload)?;
    let mut tampered = payload.clone();
    tampered[0] ^= 1;
    write(root, "tampered-copy.pt", &tampered)?;
    assert!(read_candidate_payload(
        File::open(root.join("tampered-copy.pt"))?,
        owner.registry(),
        &id("hcsn-fixture-candidate")
    )
    .is_err());
    let input = read(root, "clock-input.json")?;
    let training = read(root, "training-plan.json")?;
    let state = read(root, "candidate-state.json")?;
    assert_eq!(hash(&state, "checkpoint_sha256"), candidate);
    let profile: HcsnTimeProfileV1 = serde_json::from_value(input["profile"].clone())?;
    let ident = identity(&input["binding"], candidate);
    assert_eq!(
        HcsnClockCheckpointV1::restore(
            &profile,
            ident,
            &fs::read(root.join("training-clock.json"))?,
            hash(&training, "anchor_digest")
        )
        .err(),
        Some(HcsnTimeError::IdentityMismatch)
    );
    // Explicit fixture-only candidate context; never commit new weights into the old model identity.
    let last = number(&state, "last_end_micros");
    let anchor =
        HcsnClockCheckpointV1::initial(&profile, ident, last, hash(&state, "state_digest"))?;
    let plans = plan_hcsn_batch_v1(&profile, ident, &anchor, &[last + 200_000, last + 300_000])?;
    write(root, "candidate-clock.json", &anchor.encode()?)?;
    record(
        root,
        "continuation-plan.json",
        json!({"profile":profile,"intervals":plans,
        "anchor_digest":anchor.digest().to_string(),"candidate_digest":candidate.to_string(),
        "initial_state_digest":anchor.state_digest().to_string(),"explicit_test_context":true}),
    )?;
    record(
        root,
        "cold-owner.json",
        json!({"candidate_digest":candidate.to_string(),"payload_bytes":payload.len(),
        "required_current_head":publication["registry_head_digest"],"recovery_required":false,
        "tampered_payload_rejected":true,"old_model_clock_restore_rejected":true,
        "candidate_only":true,"pid":std::process::id()}),
    )
}
fn finish(root: &Path) -> Result<()> {
    let plan = read(root, "continuation-plan.json")?;
    let resumed = read(root, "resumed.json")?;
    let reference = read(root, "reference.json")?;
    assert_eq!(resumed["prediction"], reference["prediction"]);
    assert_eq!(resumed["state_digest"], reference["state_digest"]);
    assert_eq!(resumed["candidate_digest"], plan["candidate_digest"]);
    let input = read(root, "clock-input.json")?;
    let profile: HcsnTimeProfileV1 = serde_json::from_value(plan["profile"].clone())?;
    let ident = identity(&input["binding"], hash(&plan, "candidate_digest"));
    let anchor = HcsnClockCheckpointV1::restore(
        &profile,
        ident,
        &fs::read(root.join("candidate-clock.json"))?,
        hash(&plan, "anchor_digest"),
    )?;
    let plans: Vec<HcsnIntervalPlanV1> = serde_json::from_value(plan["intervals"].clone())?;
    let next = commit_hcsn_batch_v1(
        &profile,
        ident,
        &anchor,
        &plans,
        hash(&resumed, "state_digest"),
    )?;
    write(root, "continued-clock.json", &next.encode()?)?;
    record(
        root,
        "clock-commit.json",
        json!({"state_digest":next.state_digest().to_string(),
        "clock_digest":next.digest().to_string(),"last_micros":next.last_micros(),"sequence":next.sequence(),
        "explicit_test_context":true,"production_adoption":false,"pid":std::process::id()}),
    )
}
fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    assert_eq!(
        args.len(),
        3,
        "native_fixture <plan|publish|reopen|finish> <fixture-root>"
    );
    let root = Path::new(&args[2]);
    match args[1].as_str() {
        "plan" => plan(root)?,
        "publish" => publish(root)?,
        "reopen" => reopen(root)?,
        "finish" => finish(root)?,
        _ => return Err("unknown fixture mode".into()),
    }
    println!(
        "{}",
        json!({"mode":args[1],"status":"passed","pid":std::process::id()})
    );
    Ok(())
}
