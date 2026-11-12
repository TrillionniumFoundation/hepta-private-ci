//! External Observer process for the ordinary fixture. Its original measured
//! value is supplied separately before A runs; task success never becomes a
//! reward. A has no access to this Root0600 key or business input file.

use std::fs::OpenOptions;
use std::io::Read;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_agent_protocol::Q24OriginalTaskObservationV1;
use codex_hepta_agent_protocol::Q24OriginalTerminalOutcomeReceiptV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_learning_ledger::AuthenticatedOutcomeV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::OutcomeTerminalityV1;
use codex_hepta_learning_ledger::OutcomeWatermarkV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::outcome_signing_payload_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde::Deserialize;
use serde::Serialize;

pub(super) const CHILD_TEST: &str = "neuron_generation_current::initial_root_tests::ordinary::observer::ordinary_original_observer_child";
pub(super) const PLAN_ENV: &str = "HEPTA_ORDINARY_Q24_ORIGINAL_OBSERVER_PLAN";

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ObserverPlan {
    pub(super) schema: u8,
    pub(super) control: PathBuf,
    pub(super) agent: String,
    pub(super) spawn: u64,
    pub(super) daemon_pid: u32,
    pub(super) run_id: String,
    pub(super) objective: String,
    pub(super) trust: PathBuf,
    pub(super) key: PathBuf,
    pub(super) fact: PathBuf,
    pub(super) result: PathBuf,
    pub(super) expires_at_millis: u64,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalBusinessFact {
    pub(super) schema: u8,
    pub(super) episode_id: String,
    pub(super) unit_profile_digest: String,
    pub(super) expected_delay_profile_digest: String,
    pub(super) value_raw_q32: i64,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ObservedOriginalOutcome {
    pub(super) observed: Q24OriginalTaskObservationV1,
    pub(super) appended: Q24OriginalTerminalOutcomeReceiptV1,
    pub(super) original_fact_digest: String,
    pub(super) original_outcome_digest: String,
    pub(super) original_evidence_digest: String,
}

#[test]
#[ignore = "original ordinary fixture launches this independent Observer process explicitly"]
fn ordinary_original_observer_child() -> anyhow::Result<()> {
    // SAFETY: this process observes actual credentials, without changing them.
    anyhow::ensure!(
        unsafe { (libc::getuid(), libc::geteuid()) } == (0, 0),
        "original Observer custody requires actual administrator launch"
    );
    let path = std::env::var_os(PLAN_ENV)
        .ok_or_else(|| anyhow::anyhow!("original Observer plan missing"))?;
    let plan: ObserverPlan = serde_json::from_slice(&read_private(Path::new(&path), 16 * 1024)?)?;
    anyhow::ensure!(
        plan.schema == 1 && crate::authbus_ingress::now_ms()? < plan.expires_at_millis,
        "original Observer plan schema or deadline"
    );
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    runtime.block_on(observe_and_submit(&plan))
}

async fn observe_and_submit(plan: &ObserverPlan) -> anyhow::Result<()> {
    let client = crate::AgentdClient::new(
        plan.control.clone(),
        AgentId::parse(&plan.agent)?,
        plan.spawn,
    )?;
    let health = client.health().await?;
    anyhow::ensure!(
        health.ready && !health.fenced && health.process_id == plan.daemon_pid,
        "actual original A process must be current"
    );
    let fact_bytes = read_private(&plan.fact, 4096)?;
    let fact: OriginalBusinessFact = serde_json::from_slice(&fact_bytes)?;
    anyhow::ensure!(
        fact.schema == 1 && (-(8_i64 << 32)..=(8_i64 << 32)).contains(&fact.value_raw_q32),
        "original bounded unit declaration required"
    );
    let payload: crate::root_initial_learning_trust_data::LearningTrustPayloadV1 =
        serde_json::from_slice(&read_private(&plan.trust, 12 * 1024)?)?;
    let now = crate::authbus_ingress::now_ms()? / 1_000;
    let (trust, generator, observer) = payload.activate_pinned_genesis(now)?;
    anyhow::ensure!(
        generator.principal.principal_id != observer.principal.principal_id
            && generator.controller_id != observer.controller_id,
        "business Observer must retain an independent original role and controller"
    );
    let key = SigningKey::from_bytes(
        &read_private(&plan.key, 32)?
            .try_into()
            .map_err(|_| anyhow::anyhow!("original Observer key size"))?,
    );
    anyhow::ensure!(
        key.verifying_key().to_bytes() == observer.verifying_key
            && trust.verifier().objective_digest() == plan.objective.parse::<Digest32>()?,
        "original Observer key/objective differs from Root-fixed public trust"
    );
    let observed = client.original_q24_task_observation().await?;
    anyhow::ensure!(
        observed.run_id == plan.run_id
            && observed.episode_id == fact.episode_id
            && observed.unit_profile_digest == fact.unit_profile_digest
            && observed.expected_delay_profile_digest == fact.expected_delay_profile_digest
            && observed.observer_principal_id == observer.principal.principal_id.as_str()
            && observed.observer_controller_id == observer.controller_id.as_str()
            && observed.decision_sequence > 0,
        "original task observation does not bind this independent business input"
    );
    let outcome = AuthenticatedOutcomeV1 {
        record_id: StableId::new(&observed.outcome_record_id)?,
        outcome_id: StableId::new(&observed.outcome_id)?,
        episode_id: StableId::new(&fact.episode_id)?,
        observer: observer.principal.clone(),
        observed_at: Some(now),
        value: Some(FixedQ32::from_raw(fact.value_raw_q32)),
        unit_profile_digest: fact.unit_profile_digest.parse()?,
        support_digest: observed.source_publication_digest.parse()?,
        watermark: OutcomeWatermarkV1 {
            latest_observable_at: now,
            expected_delay_profile_digest: fact.expected_delay_profile_digest.parse()?,
            terminality: OutcomeTerminalityV1::Terminal,
            censoring_reason: None,
            correction_predecessor: None,
            finalized_at: Some(now),
        },
    };
    let mut signed = SignedLearningEvidenceV1 {
        evidence_id: StableId::new("ordinary-original-independent-observer-evidence")?,
        principal_id: observer.principal.principal_id.clone(),
        role: LearningEvidenceRoleV1::Observer,
        trust_digest: trust.verifier().trust_digest(),
        scope_digest: observer.principal.scope_digest,
        objective_digest: trust.verifier().objective_digest(),
        authority_epoch: observer.principal.authority_epoch,
        issued_at: now,
        expires_at: now
            .checked_add(120)
            .ok_or_else(|| anyhow::anyhow!("Observer expiry overflow"))?,
        payload_digest: Digest32::of_bytes(&outcome_signing_payload_v2(&outcome)),
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    anyhow::ensure!(
        crate::authbus_ingress::now_ms()? < plan.expires_at_millis,
        "original Observer deadline before submission"
    );
    let appended = client
        .submit_original_q24_terminal_outcome(&outcome, &signed)
        .await?;
    anyhow::ensure!(
        appended.decision_sequence == observed.decision_sequence
            && appended.decision_chain_digest == observed.decision_chain_digest
            && appended.outcome_sequence
                == appended
                    .decision_sequence
                    .checked_add(1)
                    .ok_or_else(|| anyhow::anyhow!("actual Ledger sequence overflow"))?
            && appended.outcome_chain_digest.parse::<Digest32>()?
                != observed.decision_chain_digest.parse::<Digest32>()?,
        "actual original witnessed Outcome must follow its exact Decision"
    );
    pretty_assertions::assert_eq!(client.original_q24_task_observation().await?, observed);
    anyhow::ensure!(
        read_private(&plan.fact, 4096)? == fact_bytes
            && crate::authbus_ingress::now_ms()? < plan.expires_at_millis,
        "original business fact changed or Observer completed late"
    );
    let result = ObservedOriginalOutcome {
        observed,
        appended,
        original_fact_digest: Digest32::of_bytes(&fact_bytes).to_string(),
        original_outcome_digest: signed.payload_digest.to_string(),
        original_evidence_digest: Digest32::of_parts(&[&signed.signing_bytes(), &signed.signature])
            .to_string(),
    };
    super::root::write_json(&plan.result, &result)
}

pub(super) fn read_private(path: &Path, bound: usize) -> anyhow::Result<Vec<u8>> {
    let mut file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)?;
    let before = file.metadata()?;
    anyhow::ensure!(
        before.is_file()
            && before.uid() == 0
            && before.nlink() == 1
            && before.mode() & 0o777 == 0o600
            && before.len() > 0
            && before.len() <= bound as u64,
        "original Observer input custody/size differs"
    );
    let mut bytes = Vec::new();
    Read::by_ref(&mut file)
        .take(bound as u64 + 1)
        .read_to_end(&mut bytes)?;
    let stamp = |m: &std::fs::Metadata| {
        (
            m.dev(),
            m.ino(),
            m.len(),
            m.uid(),
            m.gid(),
            m.mode(),
            m.nlink(),
            m.mtime(),
            m.mtime_nsec(),
            m.ctime(),
            m.ctime_nsec(),
        )
    };
    anyhow::ensure!(
        bytes.len() as u64 == before.len()
            && stamp(&file.metadata()?) == stamp(&before)
            && stamp(&std::fs::symlink_metadata(path)?) == stamp(&before),
        "original Observer input changed"
    );
    Ok(bytes)
}
