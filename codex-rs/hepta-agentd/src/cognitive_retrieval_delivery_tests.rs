use codex_hepta_agentd::CognitiveRetrievalLearningSink;
use codex_hepta_contracts::AgentId;
use codex_hepta_infer_core::CognitiveContextDeliveryStateV1;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeDispatch;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use codex_hepta_infer_worker_host::native_app_server::AppServerModelDriver;
use codex_hepta_infer_worker_host::native_app_server::NativeWorkerConfig;
use codex_hepta_learning_ledger as ledger;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::Path;

use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn writer(root: &Path) -> ledger::LedgerWriter {
    let scope = digest("cognitive-delivery-test-scope");
    let key = SigningKey::from_bytes(&[11; 32]);
    let root_key = SigningKey::from_bytes(&[12; 32]);
    let root_trust = ledger::LearningTrustRootV1 {
        root_id: id("delivery-root"),
        scope_digest: scope,
        verifying_key: root_key.verifying_key().to_bytes(),
        valid_from: 1,
        expires_at: 200,
        revoked_at: None,
    };
    let mut distribution = ledger::SignedLearningTrustDistributionV1 {
        distribution: ledger::LearningTrustDistributionV1 {
            distribution_id: id("delivery-trust"),
            generation: 1,
            effective_at: 20,
            trust: ledger::LearningEvidenceTrustV1 {
                scope_digest: scope,
                objective_digest: digest("delivery-objective"),
                authority_epoch: 7,
                signers: vec![ledger::TrustedLearningSignerV1 {
                    principal: ledger::AuthenticatedPrincipalV1 {
                        principal_id: id("delivery-generator"),
                        credential_chain_digest: digest("delivery-credential"),
                        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                        scope_digest: scope,
                        authority_epoch: 7,
                        authenticated_at: 10,
                        expires_at: 100,
                    },
                    controller_id: id("delivery-controller"),
                    verifying_key: key.verifying_key().to_bytes(),
                    roles: vec![ledger::LearningEvidenceRoleV1::Generator],
                    revoked_at: None,
                }],
            },
        },
        root_id: root_trust.root_id.clone(),
        issued_at: 15,
        expires_at: 90,
        signature: [0; 64],
    };
    distribution.signature = root_key
        .sign(&distribution.signing_bytes().unwrap())
        .to_bytes();
    let previous = None;
    let now = 50;
    let trust = ledger::activate_learning_trust(&root_trust, distribution, previous, now).unwrap();
    let open = |name: &str| {
        OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(root.join(name))
            .unwrap()
    };
    let binding = digest("delivery-ledger-binding");
    let capacity = 64;
    let durable =
        ledger::DurableLedger::create(open("learning.journal"), binding, capacity).unwrap();
    let witness = ledger::LedgerWitnessStore::create(open("learning.witness"), binding).unwrap();
    let directory = File::open(root).unwrap();
    ledger::LedgerWriter::from_durable(durable, witness, trust, &directory, &directory).unwrap()
}

fn assignment(record_id: StableId, episode_id: StableId) -> ledger::RetrievalAssignmentFact {
    ledger::RetrievalAssignmentFact {
        record_id,
        episode_id,
        cue_digest: digest("cue"),
        policy_digest: digest("policy"),
        source_completeness_digest: digest("source-completeness"),
        candidate_union_digest: digest("candidate-union"),
        recall_packet_digest: digest("recall"),
        enumerated_candidate_digests: vec![digest("candidate")],
        legal_candidate_indices: vec![0],
        selected_candidate_indices: vec![0],
        delivered_candidate_indices: vec![0],
        context_exposed: true,
        published_context_digest: Some(digest("published-context")),
        omitted_by_policy_limits: 0,
        assignment_propensity: ProbabilityQ32::ONE,
        downstream_policy_digest: None,
        delivery_propensity: ProbabilityQ32::ONE,
        completeness: ledger::CandidateSetCompleteness::Complete,
        support_digest: digest("assignment-support"),
    }
}

// Mirror the frozen public episode identity in an external integration test.
// This test deliberately uses the library crate on both sides of the existing
// Agentd/worker-host dev-dependency edge, not a second unit-test crate identity.
fn assignment_identity(owner: &AgentId, generation: u64, request: u64) -> (StableId, StableId) {
    let raw = owner.as_str().as_bytes();
    let mut bytes = b"hepta.agentd.retrieval-assignment.v1".to_vec();
    bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
    bytes.extend_from_slice(raw);
    bytes.extend_from_slice(&generation.to_be_bytes());
    bytes.extend_from_slice(&request.to_be_bytes());
    (
        id(&format!(
            "retrieval-assignment:{}",
            Digest32::of_bytes(&bytes)
        )),
        id(&format!(
            "retrieval-episode:{}:{generation}:{request}",
            owner.as_str()
        )),
    )
}

#[test]
fn real_learning_and_native_owners_join_exact_preparation_and_acceptance() {
    let temp = tempfile::tempdir().unwrap();
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000191").unwrap();
    let generation = 4;
    let read_request_id = 17;
    let (record_id, episode_id) = assignment_identity(&owner, generation, read_request_id);
    let prepared = assignment(record_id, episode_id);
    let context = prepared.published_context_digest.unwrap();
    let mut writer = writer(temp.path());
    writer
        .append_retrieval_assignment_current(prepared)
        .unwrap();
    let ledger_before = std::fs::read(temp.path().join("learning.journal")).unwrap();
    let witness_before = std::fs::read(temp.path().join("learning.witness")).unwrap();
    let sink = CognitiveRetrievalLearningSink::new(writer);
    let driver = AppServerModelDriver::new(NativeWorkerConfig {
        agentd_socket: temp.path().join("agentd.sock"),
        agent_id: owner,
        generation,
        model: "model".to_string(),
        timeout: std::time::Duration::from_secs(5),
    })
    .unwrap();
    let capacity = 8;
    let mut control =
        DurableInferenceControl::open(temp.path().join("native.journal"), capacity).unwrap();
    let request = NativeRequest {
        request_id: "native-request".to_string(),
        principal_id: "00000000-0000-4000-8000-000000000191".to_string(),
        worker_generation: generation,
        model: "model".to_string(),
        payload_digest: digest("source-admission").to_string(),
    };
    let maximum_in_flight = 1;
    control
        .reserve_native(request.clone(), maximum_in_flight)
        .unwrap();
    assert!(
        driver
            .inspect_cognitive_assignment(&control, &sink, &request, read_request_id, context)
            .is_err()
    );
    let dispatch = NativeDispatch {
        thread_id: "thread".to_string(),
        model_provider: "provider".to_string(),
        context_digest: digest("additional-context").to_string(),
        owner_context_digest: Some(context.to_string()),
        cognitive_preparation: None,
        codex_payload_digest: Some(digest("turn-payload").to_string()),
        codex_request_digest: Some(digest("turn-request").to_string()),
        app_server_version: Some("1.2.3".to_string()),
        protocol_id: Some("codex.app-server.v2".to_string()),
        codex_source_admission_digest: Some(request.payload_digest.clone()),
        codex_home_digest: Some(digest("home").to_string()),
        codex_connection_id: Some(7),
        codex_session_id: Some("session".to_string()),
        codex_deadline_ms: Some(10_000),
        codex_authority_epoch: Some(7),
        codex_revocation_revision: Some(1),
        codex_revocation_head_sha256: Some(digest("revocation").to_string()),
        codex_authority_witness_sha256: Some(digest("authority").to_string()),
    };
    control
        .dispatch_native(&request.request_id, dispatch)
        .unwrap();
    let pending = driver
        .inspect_cognitive_assignment(&control, &sink, &request, read_request_id, context)
        .unwrap();
    assert_eq!(
        pending.0,
        CognitiveContextDeliveryStateV1::AcceptanceUnknown
    );
    control
        .native_started(&request.request_id, "turn".to_string())
        .unwrap();
    let accepted = driver
        .inspect_cognitive_assignment(&control, &sink, &request, read_request_id, context)
        .unwrap();
    assert_eq!(accepted.0, CognitiveContextDeliveryStateV1::TurnAccepted);
    assert_ne!(pending.1, accepted.1);
    assert!(
        driver
            .inspect_cognitive_assignment(&control, &sink, &request, read_request_id + 1, context)
            .is_err()
    );
    assert!(
        driver
            .inspect_cognitive_assignment(
                &control,
                &sink,
                &request,
                read_request_id,
                digest("wrong-context")
            )
            .is_err()
    );
    let mut wrong_generation = request.clone();
    wrong_generation.worker_generation += 1;
    assert!(
        driver
            .inspect_cognitive_assignment(
                &control,
                &sink,
                &wrong_generation,
                read_request_id,
                context
            )
            .is_err()
    );
    assert_eq!(
        std::fs::read(temp.path().join("learning.journal")).unwrap(),
        ledger_before
    );
    assert_eq!(
        std::fs::read(temp.path().join("learning.witness")).unwrap(),
        witness_before
    );
    drop(control);
    let reopened =
        DurableInferenceControl::open(temp.path().join("native.journal"), capacity).unwrap();
    assert_eq!(
        driver
            .inspect_cognitive_assignment(&reopened, &sink, &request, read_request_id, context)
            .unwrap(),
        accepted
    );
}

#[path = "cognitive_owner_preparation_delivery_tests.rs"]
mod owner_preparation_tests;
