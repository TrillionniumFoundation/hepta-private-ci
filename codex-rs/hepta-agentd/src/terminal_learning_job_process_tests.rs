//! Explicit root qualification: the child reopens all three original owners.
//! Local test keys remain fixtures; no production authority or task win is claimed.

use super::*;
use crate::TERMINAL_LEARNING_JOB_RECORD_BYTES_V1;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_learning_ledger::LedgerWitnessStore;
use pretty_assertions::assert_eq;

#[tokio::test]
#[ignore = "requires root and root-owned /root; explicitly qualifies the original protected backend"]
async fn durable_native_job_with_original_host_cas() {
    let fixtures = fixtures().await;
    let directory = tempfile::Builder::new()
        .prefix("terminal-job-")
        .tempdir_in("/root")
        .unwrap();
    let root = RootAuthorityDirectory::open(directory.path()).unwrap();
    let vacant = TerminalLearningJobRecordV1::vacant(
        &fixtures.request,
        &fixtures.daemon.identity.agent_id,
        &id("operator.native.owner"),
    )
    .unwrap();
    let store = HostAuthorityFrontierStore::initialize_bounded(
        root,
        OWNER.into(),
        vacant,
        TERMINAL_LEARNING_JOB_RECORD_BYTES_V1,
    )
    .unwrap();
    let registered = TerminalLearningJobOwnerV1::from_registered(
        store,
        OWNER.into(),
        &fixtures.request,
        fixtures.daemon.identity.agent_id.clone(),
        id("operator.native.owner"),
    )
    .unwrap();
    let owner = native(&fixtures, registered);
    let receipt = owner
        .train(fixtures.request.clone(), /*now*/ 50)
        .await
        .unwrap();
    let context = serde_json::json!({
        "root": directory.path(), "memory": fixtures._memory_root.path(),
        "ledger": fixtures.ledger_root.root, "agent": fixtures.daemon.identity.agent_id.to_string(),
        "policy": fixtures.grant.policy_id().as_str(), "payload": receipt.payload,
        "job_digest": receipt.job_digest.to_string(), "elapsed": receipt.elapsed_microseconds,
    });
    drop(owner);
    drop(
        Arc::try_unwrap(fixtures.ledger)
            .ok()
            .unwrap()
            .into_inner()
            .unwrap(),
    );
    drop(fixtures.replay);
    drop(fixtures.source);
    let output = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "durable_native_job_child_readback",
            "--ignored",
            "--nocapture",
        ])
        .env("HEPTA_TERMINAL_JOB_TEST_CONTEXT", context.to_string())
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(String::from_utf8_lossy(&output.stdout).contains("1 passed"));
}

#[tokio::test]
#[ignore = "child entry point: only the parent test supplies original owner locations"]
async fn durable_native_job_child_readback() {
    let context: serde_json::Value =
        serde_json::from_str(&std::env::var("HEPTA_TERMINAL_JOB_TEST_CONTEXT").unwrap()).unwrap();
    let field = |name: &str| context[name].as_str().unwrap();
    let agent = AgentId::parse(field("agent")).unwrap();
    let fleet = HeptaFleetRoot::parse(
        std::path::PathBuf::from(field("memory"))
            .canonicalize()
            .unwrap(),
    )
    .unwrap()
    .layout();
    let source_owner = AgentId::parse("00000000-0000-4000-8000-000000000011").unwrap();
    let source = Arc::new(
        CognitiveStore::open(&fleet.agent(&source_owner))
            .await
            .unwrap(),
    );
    let replay = Arc::new(
        AgentdSharedReplayHostV1::new(
            source,
            FederationConsumerAccess::new(
                agent.clone(),
                Sha256Digest::for_bytes(b"terminal-workspace"),
            ),
            "terminal.local".into(),
            agent.clone(),
        )
        .unwrap(),
    );
    let policy = Sha256Digest::parse(field("policy").to_owned()).unwrap();
    let grant = replay.training_source(&policy).await.unwrap();
    // Borrow the parent's files without letting the fixture destructor remove
    // them. The parent owns cleanup after this child has exited.
    let ledger_root = std::mem::ManuallyDrop::new(Fixture {
        root: field("ledger").into(),
    });
    let witness = LedgerWitnessStore::recover(
        ledger_root.file("witness"),
        digest("production-ledger-binding"),
    )
    .unwrap();
    let frontier = witness.frontier().unwrap();
    drop(witness);
    let ledger = ledger_root.recover_writer(/*limit*/ 64, frontier);
    // Reconstruct the same test request from real original owners. The fixture
    // evaluator key signs the original ledger head, never a caller digest.
    let template = fixtures().await;
    let mut request = template.request.clone();
    drop(template);
    request.source_policy_id = policy;
    request.expected_source_support_digest =
        grant.source_support_digest().as_str().parse().unwrap();
    request.dataset_evidence = sign(
        ledger.verifier(),
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &dataset_freeze_signing_payload_v2(&ledger.snapshot().unwrap(), &request.dataset_plan)
            .unwrap(),
    );
    request.expected_dataset_digest = ledger
        .freeze_dataset(
            request.dataset_plan.clone(),
            &request.dataset_evidence,
            /*now*/ 50,
        )
        .unwrap()
        .snapshot
        .dataset_digest;
    let root = RootAuthorityDirectory::open(Path::new(field("root"))).unwrap();
    let store = HostAuthorityFrontierStore::open_bounded(
        root,
        OWNER.into(),
        TERMINAL_LEARNING_JOB_RECORD_BYTES_V1,
    )
    .unwrap();
    let registered = TerminalLearningJobOwnerV1::from_registered(
        store,
        OWNER.into(),
        &request,
        agent.clone(),
        id("operator.native.owner"),
    )
    .unwrap();
    let owner = AgentdTerminalLearningOwnerV1::from_registered_job(
        agent,
        id("operator.native.owner"),
        Arc::new(Mutex::new(ledger)),
        replay,
        registered,
    )
    .unwrap();
    let receipt = owner.readback(request.clone(), /*now*/ 51).await.unwrap();
    assert_eq!(
        receipt.payload,
        serde_json::from_value::<Vec<u8>>(context["payload"].clone()).unwrap()
    );
    assert_eq!(receipt.job_digest.to_string(), field("job_digest"));
    assert_eq!(
        receipt.elapsed_microseconds,
        context["elapsed"].as_u64().unwrap()
    );
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(owner.train(request, /*now*/ 51).await.unwrap(), receipt);
}
