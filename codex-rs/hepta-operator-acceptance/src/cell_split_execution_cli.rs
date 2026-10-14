//! Operator-facing, one-effect-at-a-time CellSplit coordination.
//!
//! This command is a client of four separately pinned real effect owners.
//! Its configuration is not trusted by its location or by contents inside it:
//! an independently supplied SHA-256 of the exact configuration bytes is
//! mandatory. Server-side final-use and Selector/NDU checks remain required.
//! Even a completed transcript cannot issue production or promotion authority.

use std::fs::OpenOptions;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_types::PhaseMetricSinkV1;

use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest as _;
use sha2::Sha256;

use crate::CellSplitExecutionOwnerV1;
use crate::CellSplitExecutionPlanV1;
use crate::CellSplitExecutionReceiptV1;
use crate::CellSplitExecutionTranscriptV1;
use crate::CellSplitOwnerTrustV1;
use crate::CellSplitUnixEffectPortV1;

const CONFIG_SCHEMA: &str = "hepta.learning.cell-split.execution-cli.v1";
const OUTCOME_SCHEMA: &str = "hepta.learning.cell-split.execution-cli-result.v1";
const MAX_CONFIG_BYTES: u64 = 64 * 1024;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ExecutionConfigV1 {
    schema: String,
    plan: CellSplitExecutionPlanV1,
    execution_root: PathBuf,
    owner_socket_paths: [PathBuf; 4],
    owner_verifying_keys_hex: [String; 4],
    timeout_millis: u64,
}

/// Diagnostic/effect-coordinate output. Never a signed production acceptance.
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CellSplitExecutionCliOutcomeV1 {
    schema: &'static str,
    action: &'static str,
    completed_steps: usize,
    complete: bool,
    receipt: Option<CellSplitExecutionReceiptV1>,
    transcript: Option<CellSplitExecutionTranscriptV1>,
    production_activation_authorized: bool,
}

/// Legacy operator-facing entry: only read-only transcript verification.
/// Effectful advancement requires a separately admitted NDU/Selector choice
/// through the Agentd product entry, plus live final-use checks at every owner.
/// A pinned configuration SHA-256 identifies bytes but grants no authority.
pub fn run_pinned_cell_split_execution_v1(
    action: &str,
    config_path: &Path,
    externally_pinned_config_sha256: &str,
) -> Result<CellSplitExecutionCliOutcomeV1, String> {
    // This legacy operator interface has no independent NDU/Selector token.
    // In particular, a pinned configuration hash is not an effect grant.
    // Only the admission-bound Agentd entry may start a durable side effect.
    if action == "advance" {
        return Err(
            "CellSplit advance requires independently admitted NDU/Selector selection".to_string(),
        );
    }
    if action == "reconcile" {
        return Err(
            "CellSplit recovery requires the explicit pending-only reconciliation API".to_string(),
        );
    }
    run_pinned_cell_split_execution_with_admission_v1(
        action,
        config_path,
        externally_pinned_config_sha256,
        |_| Ok(()),
    )
}

/// Explicit crash/lost-ACK recovery against an existing prepared intent.
/// It requires the same externally pinned config and four original owner keys,
/// but cannot prepare any new effect or call `port.execute`. This is a narrow
/// recovery operation, NOT a current Selector/NDU admission or permission to
/// activate a successor. No file or lock is created for an absent split.
pub fn run_pinned_cell_split_reconcile_only_v1(
    config_path: &Path,
    externally_pinned_config_sha256: &str,
) -> Result<CellSplitExecutionCliOutcomeV1, String> {
    run_pinned_cell_split_execution_inner_v1(
        "reconcile",
        config_path,
        externally_pinned_config_sha256,
        None,
        |_| Ok(()),
    )
}

/// Product composition seam: validate the independently admitted, frozen split
/// against the operator's externally pinned configuration *before* opening the
/// coordinator, preparing an intent, or contacting any effect owner.
///
/// This callback is not an issuer or a substitute for each durable effect
/// backend's fresh final-use check. Its caller must validate real signed
/// NDU/Selector evidence rather than accept self-asserted digests.
pub fn run_pinned_cell_split_execution_with_admission_v1<F>(
    action: &str,
    config_path: &Path,
    externally_pinned_config_sha256: &str,
    admit_selected_plan: F,
) -> Result<CellSplitExecutionCliOutcomeV1, String>
where
    F: FnMut(&CellSplitExecutionPlanV1) -> Result<(), String>,
{
    run_pinned_cell_split_execution_inner_v1(
        action,
        config_path,
        externally_pinned_config_sha256,
        None,
        admit_selected_plan,
    )
}

/// Explicitly telemetry-bound product seam. The Evidence sink is injected by
/// the trusted Agentd composition, never minted by a CLI config or callback.
/// It must be healthy before *any* new effect; the underlying coordinator
/// rechecks health at dispatch and latches a failed record without replaying
/// an already committed CAS/CNS/Supervisor effect.
pub fn run_pinned_cell_split_execution_with_admission_and_metrics_v1<F>(
    action: &str,
    config_path: &Path,
    externally_pinned_config_sha256: &str,
    metric_sink: Arc<dyn PhaseMetricSinkV1>,
    admit_selected_plan: F,
) -> Result<CellSplitExecutionCliOutcomeV1, String>
where
    F: FnMut(&CellSplitExecutionPlanV1) -> Result<(), String>,
{
    run_pinned_cell_split_execution_inner_v1(
        action,
        config_path,
        externally_pinned_config_sha256,
        Some(metric_sink),
        admit_selected_plan,
    )
}

fn run_pinned_cell_split_execution_inner_v1<F>(
    action: &str,
    config_path: &Path,
    externally_pinned_config_sha256: &str,
    metric_sink: Option<Arc<dyn PhaseMetricSinkV1>>,
    mut admit_selected_plan: F,
) -> Result<CellSplitExecutionCliOutcomeV1, String>
where
    F: FnMut(&CellSplitExecutionPlanV1) -> Result<(), String>,
{
    let selected_action = match action {
        "advance" => "advance",
        "transcript" => "transcript",
        "reconcile" => "reconcile",
        _ => return Err("expected advance or transcript, or explicit reconcile".to_string()),
    };
    // The owner checks Evidence health only before dispatching a NEW effect.
    // A prepared effect whose acknowledgment was lost must still be allowed
    // to reconcile with the original owner even when telemetry is unhealthy.
    // Read-only transcript inspection is likewise never gated by telemetry.

    let config_bytes = read_private_config(config_path)?;
    if !canonical_hex(externally_pinned_config_sha256)
        || format!("{:x}", Sha256::digest(&config_bytes)) != externally_pinned_config_sha256
    {
        return Err("execution configuration does not match the external SHA-256 pin".to_string());
    }
    let config: ExecutionConfigV1 = serde_json::from_slice(&config_bytes)
        .map_err(|error| format!("invalid execution configuration: {error}"))?;
    if config.schema != CONFIG_SCHEMA {
        return Err("unknown execution configuration schema".to_string());
    }
    // No filesystem owner initialization and no prepared intent may precede
    // this independent selection check. The operator pin alone does not
    // establish the current NDU or Selector authorization.
    if selected_action != "reconcile" {
        admit_selected_plan(&config.plan)?;
    }
    // Opening and recovering the coordinator may require disk and original
    // owner readbacks. Revalidate the independent selection after that work,
    // immediately before a new durable intent may be prepared.
    let recheck_plan = (selected_action == "advance").then(|| config.plan.clone());
    if !(1..=30_000).contains(&config.timeout_millis) {
        return Err("RPC timeout must be between 1 and 30000 ms".to_string());
    }
    let parsed_keys = config
        .owner_verifying_keys_hex
        .iter()
        .map(|value| parse_verifying_key(value.as_str()))
        .collect::<Result<Vec<_>, _>>()?;
    let keys: [VerifyingKey; 4] = parsed_keys
        .try_into()
        .map_err(|_| "exactly four pinned owner keys are required".to_string())?;
    let trust = CellSplitOwnerTrustV1::new(&config.plan, keys.clone())
        .map_err(|error| error.to_string())?;
    let port = CellSplitUnixEffectPortV1::new(
        config.owner_socket_paths,
        keys,
        Duration::from_millis(config.timeout_millis),
    )
    .map_err(|error| error.to_string())?;
    let owner = match selected_action {
        "transcript" => {
            CellSplitExecutionOwnerV1::open_existing(&config.execution_root, config.plan, trust, port)
        }
        "reconcile" => CellSplitExecutionOwnerV1::open_pending_reconciliation(
            &config.execution_root,
            config.plan,
            trust,
            port,
        ),
        _ => CellSplitExecutionOwnerV1::open(&config.execution_root, config.plan, trust, port),
    }
    .map_err(|error| error.to_string())?;
    let mut owner = if let Some(sink) = metric_sink {
        owner.with_metric_sink(sink)
    } else {
        owner
    };
    if let Some(plan) = recheck_plan.as_ref() {
        // The callback is only an admission check, never a grant: each real
        // effect backend must still revalidate its own final-use frontier.
        admit_selected_plan(plan)?;
    }
    let (receipt, transcript) = match selected_action {
        "advance" => {
            // Preflight can perform slow original-owner RPC reads. Selection
            // may be revoked after the earlier ingress/open checks. Refresh
            // live Selector/NDU admission inside the coordinator after its
            // preflight and before any durable prepared intent is written.
            let plan = recheck_plan
                .as_ref()
                .ok_or_else(|| "missing frozen admission plan".to_string())?;
            (
                owner
                    .advance_with_admission(|| admit_selected_plan(plan))
                    .map_err(|error| error.to_string())?,
                None,
            )
        }
        "reconcile" => (
            Some(
                owner
                    .reconcile_pending_only()
                    .map_err(|error| error.to_string())?,
            ),
            None,
        ),
        _ => (
            None,
            owner
                .verified_transcript()
                .map_err(|error| error.to_string())?,
        ),
    };
    // Historical cursor completion alone is not live proof: a signed
    // original effect may have been revoked after the last advance.
    // Transcript mode has already performed its four-owner verification;
    // avoid a second remote pass while keeping the result fail-closed.
    let verified_complete = if selected_action == "transcript" {
        transcript.is_some()
    } else {
        owner
            .verified_complete()
            .map_err(|error| error.to_string())?
    };
    Ok(CellSplitExecutionCliOutcomeV1 {
        schema: OUTCOME_SCHEMA,
        action: selected_action,
        completed_steps: owner.completed_steps(),
        complete: verified_complete,
        receipt,
        transcript,
        production_activation_authorized: false,
    })
}

fn canonical_hex(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|ch| ch.is_ascii_hexdigit() && !ch.is_ascii_uppercase())
}

fn parse_verifying_key(value: &str) -> Result<VerifyingKey, String> {
    if !canonical_hex(value) {
        return Err("owner verification key must be 32 bytes of lowercase hex".to_string());
    }
    let mut bytes = [0_u8; 32];
    for (index, target) in bytes.iter_mut().enumerate() {
        *target = u8::from_str_radix(&value[index * 2..index * 2 + 2], 16)
            .map_err(|_| "malformed owner verification key".to_string())?;
    }
    VerifyingKey::from_bytes(&bytes).map_err(|_| "invalid owner verification key".to_string())
}

fn read_private_config(path: &Path) -> Result<Vec<u8>, String> {
    if !path.is_absolute() || path.canonicalize().map_err(|e| e.to_string())? != path {
        return Err("configuration path must be canonical, absolute and symlink-free".to_string());
    }
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt as _;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC);
    }
    let mut file = options.open(path).map_err(|error| error.to_string())?;
    let before = file.metadata().map_err(|error| error.to_string())?;
    if !before.is_file() || before.len() > MAX_CONFIG_BYTES {
        return Err("configuration must be a bounded regular file".to_string());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt as _;
        if before.mode() & 0o077 != 0 {
            return Err("configuration file must not be accessible by group or others".to_string());
        }
        // A writable alias to these externally pinned trust inputs is not an
        // acceptable configuration path, even if this read has the right hash.
        // Require one physical link both before and after reading.
        if before.nlink() != 1 {
            return Err("configuration file must not be hard-linked".to_string());
        }
    }
    let mut bytes = Vec::new();
    (&mut file)
        .take(MAX_CONFIG_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|error| error.to_string())?;
    if bytes.is_empty() || bytes.len() as u64 > MAX_CONFIG_BYTES {
        return Err("empty or oversized configuration".to_string());
    }
    let after_fd = file.metadata().map_err(|error| error.to_string())?;
    let after_path = std::fs::symlink_metadata(path).map_err(|error| error.to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt as _;
        if !after_path.is_file()
            || before.dev() != after_fd.dev()
            || before.ino() != after_fd.ino()
            || before.len() != after_fd.len()
            || before.dev() != after_path.dev()
            || before.ino() != after_path.ino()
            || before.len() != after_path.len()
            || before.nlink() != 1
            || after_fd.nlink() != 1
            || after_path.nlink() != 1
            || after_path.mode() & 0o077 != 0
        {
            return Err("configuration changed while being read".to_string());
        }
    }
    Ok(bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Negative-only telemetry fixture: production Agentd accepts the
    /// concrete Evidence-owned durable writer, never this trait stub.
    #[derive(Debug)]
    struct UnhealthyMetricSink;

    impl PhaseMetricSinkV1 for UnhealthyMetricSink {
        fn record(
            &self,
            _event: codex_hepta_types::PhaseMetricEventV1,
        ) -> Result<(), codex_hepta_types::PhaseMetricSinkErrorV1> {
            Err(codex_hepta_types::PhaseMetricSinkErrorV1::Unavailable)
        }

        fn healthy(&self) -> bool {
            false
        }

        fn flush(&self) -> Result<(), codex_hepta_types::PhaseMetricSinkErrorV1> {
            Err(codex_hepta_types::PhaseMetricSinkErrorV1::Unavailable)
        }
    }

    #[test]
    fn requires_external_config_pin_before_opening_any_owner() {
        let dir = tempfile::tempdir().expect("tempdir");
        let file = dir.path().join("config.json");
        std::fs::write(&file, b"{}").expect("fixture");
        use std::os::unix::fs::PermissionsExt as _;
        std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o600))
            .expect("private config");
        let error = run_pinned_cell_split_execution_v1(
            "transcript",
            &file,
            &format!("{:x}", Sha256::digest(b"different configuration")),
        )
        .expect_err("untrusted config must fail");
        assert!(error.contains("external SHA-256 pin"));
    }

    #[test]
    fn rejects_malformed_and_shared_owner_keys() {
        assert!(parse_verifying_key(&"GG".repeat(32)).is_err());
        assert!(parse_verifying_key(&"00".repeat(31)).is_err());
        assert!(canonical_hex(&"00".repeat(32)));
        assert!(!canonical_hex(&"AA".repeat(32)));
    }

    #[test]
    fn missing_live_owner_does_not_create_prepared_intent() {
        let dir = tempfile::tempdir().expect("private directory");
        let execution_root = dir.path().join("split-execution");
        std::fs::create_dir(&execution_root).expect("execution root");
        use std::os::unix::fs::PermissionsExt as _;
        std::fs::set_permissions(&execution_root, std::fs::Permissions::from_mode(0o700))
            .expect("private execution root");

        let keys = (11_u8..15)
            .map(|index| {
                let signer = ed25519_dalek::SigningKey::from_bytes(&[index; 32]);
                signer
                    .verifying_key()
                    .to_bytes()
                    .iter()
                    .map(|byte| format!("{byte:02x}"))
                    .collect::<Vec<_>>()
                    .join("")
            })
            .collect::<Vec<_>>();
        let sockets = (0..4)
            .map(|index| {
                dir.path()
                    .join(format!("absent-owner-{index}.sock"))
                    .to_string_lossy()
                    .into_owned()
            })
            .collect::<Vec<_>>();
        let configuration = serde_json::json!({
            "schema": CONFIG_SCHEMA,
            "plan": {
                "splitId": "split-pinned-test",
                "scopeDigest": "11".repeat(32),
                "parentGeneration": 1,
                "childGeneration": 2,
                "parentArtifactDigest": "22".repeat(32),
                "childArtifactDigest": "33".repeat(32),
                "nduSnapshotDigest": "44".repeat(32),
                "routeFenceDigest": "55".repeat(32),
                "ownerIds": [
                    "artifact-owner", "migration-owner", "cns-owner", "supervisor-owner"
                ]
            },
            "executionRoot": execution_root.clone(),
            "ownerSocketPaths": sockets,
            "ownerVerifyingKeysHex": keys,
            "timeoutMillis": 1000
        });
        let bytes = serde_json::to_vec(&configuration).expect("configuration");
        let pin = format!("{:x}", Sha256::digest(&bytes));
        let config_path = dir.path().join("frozen-config.json");
        std::fs::write(&config_path, bytes).expect("config write");
        std::fs::set_permissions(&config_path, std::fs::Permissions::from_mode(0o600))
            .expect("private config");

        let mut inspected_selected_plan = false;
        let denied = run_pinned_cell_split_execution_with_admission_v1(
            "advance",
            &config_path,
            &pin,
            |selected| {
                inspected_selected_plan = true;
                assert_eq!(selected.split_id, "split-pinned-test");
                Err("independent NDU/Selector evidence unavailable".to_string())
            },
        );
        assert!(denied.is_err());
        assert!(inspected_selected_plan);
        assert!(!execution_root.join("cell-split-frozen-plan.json").exists());
        assert!(!execution_root.join("cell-split-00-prepared.json").exists());

        assert!(run_pinned_cell_split_execution_v1("transcript", &config_path, &pin).is_err());
        assert!(!execution_root.join("cell-split-frozen-plan.json").exists());
        assert!(!execution_root.join(".operator-acceptance.lock").exists());

        // A valid selection can be revoked while the coordinator opens its
        // frozen plan. A second denial must leave no prepared effect intent.
        let mut admissions = 0_usize;
        let stale = run_pinned_cell_split_execution_with_admission_v1(
            "advance",
            &config_path,
            &pin,
            |_| {
                admissions += 1;
                if admissions == 1 {
                    Ok(())
                } else {
                    Err("independent Selector revoked during owner open".to_string())
                }
            },
        );
        assert!(
            stale
                .expect_err("stale selection")
                .contains("Selector revoked")
        );
        assert_eq!(admissions, 2);
        assert!(execution_root.join("cell-split-frozen-plan.json").exists());
        assert!(!execution_root.join("cell-split-00-prepared.json").exists());

        // A pinned hash and independently admitted fixture cannot turn a
        // missing owner socket into an ambiguous effect. The coordinator may
        // freeze its plan, but must never write a prepared intent.
        assert!(
            run_pinned_cell_split_execution_with_admission_v1(
                "advance",
                &config_path,
                &pin,
                |_| Ok(()),
            )
            .is_err()
        );
        let pending = execution_root.join("cell-split-00-prepared.json");
        let committed = execution_root.join("cell-split-00-committed.json");
        assert!(!pending.exists());
        assert!(!committed.exists());

        let read_only = run_pinned_cell_split_execution_v1("transcript", &config_path, &pin)
            .expect("read-only reopen of frozen plan without effects");
        assert_eq!(read_only.completed_steps, 0);
        assert!(!read_only.complete);
        assert!(read_only.transcript.is_none());
        assert!(!read_only.production_activation_authorized);

        // The telemetry-bound endpoint must not prepare a new CAS intent
        // while its writer is unhealthy, even with an allow-all fixture
        // admission. Its read-only original-owner transcript must remain
        // independently accessible under the very same outage.
        let stopped_sink = Arc::new(UnhealthyMetricSink);
        let metrics_rejection = run_pinned_cell_split_execution_with_admission_and_metrics_v1(
            "advance",
            &config_path,
            &pin,
            stopped_sink.clone(),
            |_| Ok(()),
        )
        .expect_err("unhealthy Evidence writer must deny new effects");
        assert!(metrics_rejection.contains("telemetry unavailable for new effects"));
        assert!(!pending.exists());
        assert!(!committed.exists());

        let read_only_during_outage =
            run_pinned_cell_split_execution_with_admission_and_metrics_v1(
                "transcript",
                &config_path,
                &pin,
                stopped_sink,
                |_| Ok(()),
            )
            .expect("a failed telemetry writer never prevents owner readback");
        assert_eq!(read_only_during_outage.completed_steps, 0);
        assert!(!read_only_during_outage.production_activation_authorized);

        // A retry also performs only the signed readiness preflight. It may
        // later execute once a real service is deployed, without an orphaned
        // local prepared intent forcing an unwarranted reconciliation.
        assert!(
            run_pinned_cell_split_execution_with_admission_v1(
                "advance",
                &config_path,
                &pin,
                |_| Ok(()),
            )
            .is_err()
        );
        assert!(!pending.exists());
        assert!(!committed.exists());
    }

    #[test]
    fn legacy_operator_advance_denied_before_any_config_or_effect() {
        let dir = tempfile::tempdir().expect("tempdir");
        let missing = dir.path().join("absent-config.json");
        let error = run_pinned_cell_split_execution_v1("advance", &missing, &"00".repeat(32))
            .expect_err("a configuration hash is not an NDU/Selector grant");
        assert!(error.contains("independently admitted NDU/Selector"));
        assert!(!missing.exists());
        assert_eq!(
            std::fs::read_dir(dir.path())
                .expect("no generated state")
                .count(),
            0
        );
    }

    #[test]
    fn rejects_hardlinked_config_even_if_exact_hash_is_pinned() {
        let dir = tempfile::tempdir().expect("tempdir");
        let file = dir.path().join("config.json");
        let alias = dir.path().join("config-alias.json");
        std::fs::write(&file, b"{}").expect("fixture");
        use std::os::unix::fs::PermissionsExt as _;
        std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o600))
            .expect("private config");
        std::fs::hard_link(&file, &alias).expect("same inode");
        let error = run_pinned_cell_split_execution_v1(
            "transcript",
            &file,
            &format!("{:x}", Sha256::digest(b"{}")),
        )
        .expect_err("hardlinked configuration must fail");
        assert!(error.contains("hard-linked"));
    }

    #[test]
    fn rejects_group_readable_config_even_if_hash_is_pinned() {
        let dir = tempfile::tempdir().expect("tempdir");
        let file = dir.path().join("config.json");
        std::fs::write(&file, b"{}").expect("fixture");
        use std::os::unix::fs::PermissionsExt as _;
        std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o644))
            .expect("readable fixture");
        let error = run_pinned_cell_split_execution_v1(
            "transcript",
            &file,
            &format!("{:x}", Sha256::digest(b"{}")),
        )
        .expect_err("readable config must fail");
        assert!(error.contains("group or others"));
    }

    #[test]
    fn rejects_symlinked_config_even_if_target_digest_matches() {
        let dir = tempfile::tempdir().expect("tempdir");
        let target = dir.path().join("canonical.json");
        let link = dir.path().join("linked.json");
        std::fs::write(&target, b"{}").expect("fixture");
        std::os::unix::fs::symlink(&target, &link).expect("symlink");
        let error = run_pinned_cell_split_execution_v1(
            "transcript",
            &link,
            &format!("{:x}", Sha256::digest(b"{}")),
        )
        .expect_err("symlinked configuration must fail");
        assert!(error.contains("symlink-free"));
    }

    #[test]
    fn rejects_unknown_action_before_any_disk_or_network_access() {
        let error = run_pinned_cell_split_execution_v1(
            "promote",
            Path::new("/nonexistent-cell-split-config"),
            &"00".repeat(32),
        )
        .expect_err("no promotion action");
        assert!(error.contains("advance or transcript"));
    }
}
