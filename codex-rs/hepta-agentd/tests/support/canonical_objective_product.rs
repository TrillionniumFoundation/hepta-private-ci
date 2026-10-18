//! Normal CLI and signed control-socket exercise of the conservative provider.
//! This tests startup/admission/abstention, not learned action selection or efficacy.

use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_agent_components::authbus::SignedMessageClaims;
use codex_hepta_agent_components::objective::canonical_objective_intent_digest_v1;
use codex_hepta_agent_components::objective::decode_source_envelope_json_v1;
use codex_hepta_agent_components::types::Digest32;
use codex_hepta_agent_components::types::Generation;
use codex_hepta_agent_components::types::StableId;
use codex_hepta_agentd::AuthBusObjectiveBody;
use codex_hepta_agentd::AuthBusObjectiveIngress;
use codex_hepta_agentd::IntelligenceAuthorityFileV1;
use codex_hepta_agentd::IntelligenceAuthorityOwnerFileV1;
use codex_hepta_agentd::ObjectiveStartOutcome;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::json;

use super::AGENT_ID;
use super::ISSUER_ID;
use super::hex;
use super::physical_send_count;
use super::support::fleet::FleetHarness;
use super::write_checkpoint;
use super::write_trust;

#[path = "canonical_objective_profile.rs"]
mod profile;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn timestamp(seconds: u64) -> String {
    // UTC conversion for the test producer without an additional runtime dependency.
    let mut days = seconds / 86_400;
    let mut year = 1970;
    loop {
        let leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
        let length = if leap { 366 } else { 365 };
        if days < length {
            break;
        }
        days -= length;
        year += 1;
    }
    let leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
    let months = [
        31,
        if leap { 29 } else { 28 },
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ];
    let mut month = 1;
    for length in months {
        if days < length {
            break;
        }
        days -= length;
        month += 1;
    }
    let day = days + 1;
    let hour = seconds % 86_400 / 3_600;
    let minute = seconds % 3_600 / 60;
    let second = seconds % 60;
    format!("{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}Z")
}

fn signed_objective(key: &SigningKey, sequence: u64) -> Result<AuthBusObjectiveIngress> {
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let mut source = json!({
        "requestId": format!("request.canonical.{sequence}"),
        "principalScopeDigest": "3".repeat(64),
        "intentDigest": "0".repeat(64),
        "structuredIntent": {
            "successPredicates": [{"predicateId":"task.success", "unit":"ratio", "comparator":"gte", "boundQ32":2147483648_i64, "evidenceSourceId":"observer.task", "terminal":false}],
            "terminalConditions": [{"predicateId":"task.terminal", "unit":"boolean", "comparator":"eq", "boundQ32":4294967296_i64, "evidenceSourceId":"observer.task", "terminal":true}],
            "legalActionClasses":["read"], "forbiddenActionClasses":[], "confirmationActionClasses":[],
            "constraints":[{"constraintId":"latency.ceiling", "unit":"micros", "comparator":"lte", "boundQ32":5000, "evidenceSourceId":"observer.clock", "terminal":false}],
            "softDimensions":[],
            "evidenceRequirements":[{"requirementId":"evidence.quality", "evidenceSourceId":"observer.evidence", "minimumConfidencePpm":900000, "terminal":true}],
            "resources":{"timeMicros":120000000, "tokenCount":1000, "computeMicros":50000, "memoryBytes":1048576, "networkBytes":0, "externalEffectCount":0},
            "risk":{"riskClass":"low", "abstentionRule":"ask", "rollbackClass":"reversible", "compensationRequired":false},
            "provenance":{"sourceDigest":digest("producer-source").to_string(), "normalizationProfileDigest":"2".repeat(64)}
        },
        "sourceTrustClass":"authorized_adapter", "locale":"en-US",
        "observedAt":timestamp(now), "deadline":timestamp(now + 120),
        "inputSchemaDigest":"1".repeat(64)
    });
    let envelope = decode_source_envelope_json_v1(&serde_json::to_vec(&source)?)?;
    source["intentDigest"] = json!(canonical_objective_intent_digest_v1(&envelope)?.to_string());
    let body = AuthBusObjectiveBody {
        spawn_generation: 1,
        run_id: format!("run.canonical.{sequence}"),
        objective_revision: 1,
        source_envelope_json: serde_json::to_string(&source)?,
        runtime_body_digest: digest("runtime-body").to_string(),
        preference_state_digest: digest("preferences").to_string(),
        model_tuple_digest: digest("model-tuple").to_string(),
        prompt_registry_digest: digest("prompt-registry").to_string(),
        artifact_set_digest: digest("artifact-set").to_string(),
        authority_epoch: 11,
    };
    let mut scope = b"hepta:agentd:signed-objective:v1\0".to_vec();
    scope.extend_from_slice(AGENT_ID.as_bytes());
    let claims = SignedMessageClaims {
        issuer_id: StableId::new(ISSUER_ID)?,
        key_epoch: Generation::new(1)?,
        message_id: StableId::new(format!("message.canonical.{sequence}"))?,
        subject_id: StableId::new(AGENT_ID)?,
        scope_digest: Digest32::of_bytes(&scope),
        payload_digest: Digest32::of_bytes(&serde_json::to_vec(&body)?),
        sequence,
        expires_at_ms: (now + 120) * 1_000,
    };
    Ok(AuthBusObjectiveIngress {
        issuer_id: claims.issuer_id.to_string(),
        key_epoch: 1,
        message_id: claims.message_id.to_string(),
        sequence,
        expires_at_ms: claims.expires_at_ms,
        signature_hex: hex(&key.sign(&claims.signing_bytes()).to_bytes()),
        body,
    })
}

fn publish_authority(path: &std::path::Path, key: &SigningKey, omit_owner: bool) -> Result<()> {
    use std::os::unix::fs::PermissionsExt;
    let mut owners = [
        "objective.compiler",
        "utility.ndu",
        "neuron.runtime",
        "prompt.optimizer",
        "intuition.policy",
        "context.compiler",
        "learning.eval",
    ]
    .into_iter()
    .map(|owner| IntelligenceAuthorityOwnerFileV1 {
        owner_id: owner.to_string(),
        generation: 1,
        implementation_digest: digest(&format!("{owner}:implementation")).to_string(),
        key_digest: digest(&format!("{owner}:key")).to_string(),
        key_epoch: 1,
    })
    .collect::<Vec<_>>();
    if omit_owner {
        owners.pop();
    }
    let mut document = IntelligenceAuthorityFileV1 {
        schema_version: 1,
        authority_epoch: 11,
        revocation_frontier_digest: digest("current-frontier").to_string(),
        owners,
        signer_id: "product-test.authority".to_string(),
        signature: Vec::new(),
    };
    let payload = serde_json::to_vec(&(
        "hepta.agentd.intelligence-authority.v1",
        document.schema_version,
        document.authority_epoch,
        &document.revocation_frontier_digest,
        &document.owners,
        &document.signer_id,
    ))?;
    document.signature = key.sign(&payload).to_bytes().to_vec();
    let mut temporary =
        tempfile::NamedTempFile::new_in(path.parent().context("authority file parent missing")?)?;
    temporary
        .as_file()
        .set_permissions(std::fs::Permissions::from_mode(0o600))?;
    serde_json::to_writer(temporary.as_file_mut(), &document)?;
    temporary.as_file().sync_all()?;
    temporary.persist(path)?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn ordinary_cli_signed_objective_uses_canonical_abstention_and_exact_retry() -> Result<()> {
    use app_test_support::MockResponsesConfig;
    use codex_hepta_agent_components::evidence::HeptaEvidenceStore;
    use codex_state::SqliteConfig;
    use codex_utils_absolute_path::AbsolutePathBuf;
    use core_test_support::responses;
    use std::os::unix::fs::PermissionsExt;

    let started = std::time::Instant::now();
    let observe = |phase: &str| {
        eprintln!(
            "canonical-phase: {phase}; elapsed_ms={}",
            started.elapsed().as_millis()
        );
    };
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_ID, "canonical-objective-workspace")?;
    let model = responses::start_mock_server().await;
    MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;
    std::fs::set_permissions(
        agent.layout.home_root(),
        std::fs::Permissions::from_mode(0o700),
    )?;
    let issuer = SigningKey::from_bytes(&[93; 32]);
    let authority = SigningKey::from_bytes(&[94; 32]);
    let trust = agent.layout.home_root().join("objective-trust.json");
    write_trust(
        &trust,
        &agent.agent_id,
        &issuer,
        &[],
        /*revoked*/ false,
    )?;
    let checkpoint_root = tempfile::tempdir()?;
    std::fs::set_permissions(
        checkpoint_root.path(),
        std::fs::Permissions::from_mode(0o700),
    )?;
    let checkpoint = checkpoint_root.path().join("replay.json");
    let home = AbsolutePathBuf::from_absolute_path(agent.layout.home_root())?;
    let store = HeptaEvidenceStore::open(&SqliteConfig::from_sqlite_home(home)).await?;
    let frontier = store.authbus_replay_frontier_digest().await?;
    drop(store);
    write_checkpoint(
        &checkpoint,
        &agent.agent_id,
        /*generation*/ 1,
        frontier,
    )?;
    let profile = agent.layout.home_root().join("objective-profile.json");
    std::fs::write(&profile, profile::profile_json()?)?;
    std::fs::set_permissions(&profile, std::fs::Permissions::from_mode(0o600))?;
    let authority_file = agent.layout.home_root().join("intelligence-authority.json");
    publish_authority(&authority_file, &authority, /*omit_owner*/ false)?;
    fleet.start_with_arguments(
        &agent,
        vec![
            "--authbus-trust-file".into(),
            trust.as_os_str().to_owned(),
            "--authbus-checkpoint-file".into(),
            checkpoint.as_os_str().to_owned(),
            "--objective-profile-file".into(),
            profile.as_os_str().to_owned(),
            "--intelligence-authority-file".into(),
            authority_file.as_os_str().to_owned(),
            "--intelligence-authority-signer".into(),
            "product-test.authority".into(),
            "--intelligence-authority-verifying-key".into(),
            hex(authority.verifying_key().as_bytes()).into(),
            "--canonical-intelligence-provider-profile".into(),
            "durable-safe-abstain-v1".into(),
        ],
    )?;
    observe("waiting-ready");
    let (control, _) = fleet.wait_ready(&agent, /*generation*/ 1).await?;
    observe("ready");
    let request = signed_objective(&issuer, /*sequence*/ 1)?;
    observe("first-request");
    let ObjectiveStartOutcome::Admitted { receipt } =
        control.objective_start(request.clone()).await?
    else {
        anyhow::bail!("ordinary signed objective unexpectedly conflicted");
    };
    ensure!(
        receipt.disposition == "canonical_abstained",
        "not canonical abstention: {receipt:?}"
    );
    ensure!(!receipt.idempotent);
    observe("admitted");
    let journal = agent
        .layout
        .home_root()
        .join("objective-run-start-v1/journal.bin");
    let committed_bytes = std::fs::read(&journal)?;
    ensure!(!committed_bytes.is_empty());
    observe("exact-retry");
    let replay = control.objective_start(request.clone()).await?;
    let mut expected = receipt;
    expected.idempotent = true;
    ensure!(replay == ObjectiveStartOutcome::Admitted { receipt: expected });
    ensure!(
        std::fs::read(&journal)? == committed_bytes,
        "retry appended a second durable objective"
    );

    observe("exact-retry-complete");
    // A valid external signature cannot substitute for a missing canonical owner.
    publish_authority(&authority_file, &authority, /*omit_owner*/ true)?;
    let next = signed_objective(&issuer, /*sequence*/ 2)?;
    ensure!(
        control.objective_start(next.clone()).await.is_err(),
        "missing owner entered compatibility mode"
    );
    observe("missing-owner-rejected");
    let published_before_repair = std::fs::read(&journal)?;
    publish_authority(&authority_file, &authority, /*omit_owner*/ false)?;
    observe("repaired-request");
    let ObjectiveStartOutcome::Admitted { receipt: repaired } =
        control.objective_start(next).await?
    else {
        anyhow::bail!("repaired canonical request conflicted");
    };
    ensure!(repaired.idempotent && repaired.disposition == "canonical_abstained");
    ensure!(std::fs::read(&journal)? == published_before_repair);
    observe("repaired");
    let mut tampered = request;
    tampered.body.runtime_body_digest = digest("substituted-body").to_string();
    ensure!(control.objective_start(tampered).await.is_err());
    ensure!(std::fs::read(&journal)? == published_before_repair);
    ensure!(
        physical_send_count(&model).await == 0,
        "abstention dispatched a model call"
    );
    observe("before-shutdown");
    drop(fleet);
    ensure!(physical_send_count(&model).await == 0);
    println!(
        "{}",
        json!({"profile":"durable-safe-abstain-v1", "transport":"ordinary-cli-and-control-socket", "model_transport_requests":0, "action_selection_proven":false, "elapsed_millis":started.elapsed().as_millis()})
    );
    Ok(())
}
