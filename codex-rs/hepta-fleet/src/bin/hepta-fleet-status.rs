//! Read-only operator surface for the supervisor-owned durable fleet state.

use codex_hepta_fleet::DurableFleetOwner;
use codex_hepta_fleet::FleetOperationalMetricsV1;
use codex_hepta_fleet::FleetResultCountersV1;
use codex_hepta_fleet::ResourceAxisV1;
use codex_hepta_fleet::SystemFleetClock;
use serde_json::Value;
use serde_json::json;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;

const DURABLE_FLEET_DIRECTORY: &str = "fleet-allocation-v1";
const STATE_FILE_PREFIX: &str = "generation-";
const STATE_FILE_SUFFIX: &str = ".json";

fn main() {
    if let Err(error) = run() {
        eprintln!("hepta-fleet-status: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let options = Options::parse()?;
    require_existing_state(&options.state_root)?;
    let mut owner = DurableFleetOwner::open_supervisor_state_root(
        &options.state_root,
        Arc::new(SystemFleetClock),
    )?;
    let metrics = owner.metrics()?;
    let state = owner.state();
    let alerts = alerts(&metrics, state.fleet_revocation_frontier.as_ref());
    let has_alerts = !alerts.is_empty();
    let operation = options.operation_id.as_ref().and_then(|operation_id| {
        state
            .fleet_operation_receipts
            .iter()
            .find(|receipt| receipt.operation_id == *operation_id)
            .cloned()
    });
    let output = json!({
        "schema_version": 1,
        "state_generation": state.generation,
        "state_sha256": state.content_sha256.clone(),
        "workspace_reservations_sha256": state.workspace_reservations_sha256.clone(),
        "metrics": {
            "fleet_active_grants": metrics.fleet_active_grants,
            "fleet_expired_uncollected_grants": metrics.fleet_expired_uncollected_grants,
            "fleet_revoked_uncompacted_grants": metrics.fleet_revoked_uncompacted_grants,
            "fleet_reserved_resource": metrics.fleet_reserved_resource,
            "fleet_observed_capacity": metrics.fleet_observed_capacity,
            "fleet_stale_hosts": metrics.fleet_stale_hosts,
            "fleet_grant_issue_total": counters(metrics.fleet_grant_issue_total),
            "fleet_grant_renew_total": counters(metrics.fleet_grant_renew_total),
            "fleet_grant_revoke_total": counters(metrics.fleet_grant_revoke_total),
            "fleet_revocation_lag_ms": metrics.fleet_revocation_lag_ms,
            "fleet_registry_conflict_total": metrics.fleet_registry_conflict_total,
            "fleet_indeterminate_commit_total": metrics.fleet_indeterminate_commit_total,
            "fleet_staging_debris": metrics.fleet_staging_debris,
            "fleet_compaction_backlog": metrics.fleet_compaction_backlog
        },
        "alerts": alerts,
        "operation_lookup": options.operation_id.as_ref().map(|operation_id| json!({
            "operation_id": operation_id,
            "receipt": operation.clone(),
            "retention_boundary": "bounded retained receipt window"
        })),
        "claim_boundary": {
            "read_only": true,
            "allocation_authority": false,
            "release_authority": false
        }
    });
    println!("{}", serde_json::to_string_pretty(&output)?);
    if options.fail_on_alert && has_alerts {
        std::process::exit(2);
    }
    Ok(())
}

fn require_existing_state(state_root: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let owner_root = state_root.join(DURABLE_FLEET_DIRECTORY);
    let metadata = std::fs::symlink_metadata(&owner_root)?;
    if !metadata.file_type().is_dir() || metadata.file_type().is_symlink() {
        return Err(format!(
            "durable fleet owner root is not a physical directory: {}",
            owner_root.display()
        )
        .into());
    }

    let mut found_generation = false;
    for entry in std::fs::read_dir(&owner_root)? {
        let entry = entry?;
        let file_name = entry.file_name();
        let name = file_name.to_str().ok_or_else(|| {
            format!(
                "durable fleet state filename is not UTF-8: {}",
                entry.path().display()
            )
        })?;
        if !is_generation_file(name) {
            continue;
        }
        let metadata = std::fs::symlink_metadata(entry.path())?;
        if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
            return Err(format!(
                "durable fleet generation is not a regular file: {}",
                entry.path().display()
            )
            .into());
        }
        found_generation = true;
    }
    if !found_generation {
        return Err(format!(
            "durable fleet owner has no committed generation: {}",
            owner_root.display()
        )
        .into());
    }
    Ok(())
}

fn is_generation_file(name: &str) -> bool {
    name.strip_prefix(STATE_FILE_PREFIX)
        .and_then(|value| value.strip_suffix(STATE_FILE_SUFFIX))
        .is_some_and(|value| {
            value.len() == 20 && value.bytes().all(|byte| byte.is_ascii_digit())
        })
}

fn counters(value: FleetResultCountersV1) -> Value {
    json!({
        "success": value.success,
        "rejected": value.rejected,
        "indeterminate": value.indeterminate,
        "scope": "process_local_since_supervisord_start"
    })
}

fn alerts(
    metrics: &FleetOperationalMetricsV1,
    revocation: Option<&codex_hepta_fleet::FleetRevocationSnapshotV1>,
) -> Vec<Value> {
    let mut alerts = Vec::new();
    push_nonzero(
        &mut alerts,
        "critical",
        "expired_grants_uncollected",
        metrics.fleet_expired_uncollected_grants,
        "run owner reconciliation; never delete generation files",
    );
    push_nonzero(
        &mut alerts,
        "critical",
        "stale_capacity_observation",
        metrics.fleet_stale_hosts,
        "restore the trusted observer; new grants must remain denied",
    );
    push_nonzero(
        &mut alerts,
        "critical",
        "indeterminate_commit",
        metrics.fleet_indeterminate_commit_total,
        "reopen state and look up the exact operation ID before retrying",
    );
    push_nonzero(
        &mut alerts,
        "warning",
        "registry_staging_debris",
        metrics.fleet_staging_debris,
        "reopen FleetRegistry and investigate repeated registration crashes",
    );
    push_nonzero(
        &mut alerts,
        "warning",
        "generation_compaction_backlog",
        metrics.fleet_compaction_backlog,
        "verify owner-lock health and allow a successful commit to compact",
    );
    if let (Some(lag), Some(snapshot)) = (metrics.fleet_revocation_lag_ms, revocation)
        && lag > snapshot.convergence_sla_ms
    {
        alerts.push(json!({
            "severity": "critical",
            "code": "revocation_convergence_lag",
            "value_ms": lag,
            "threshold_ms": snapshot.convergence_sla_ms,
            "action": "quarantine non-ready nodes and restore authenticated fanout"
        }));
    }
    for (host_id, reserved) in &metrics.fleet_reserved_resource {
        let Some(capacity) = metrics.fleet_observed_capacity.get(host_id) else {
            alerts.push(json!({
                "severity": "critical",
                "code": "reserved_without_capacity_observation",
                "host_id": host_id,
                "action": "deny use and restore the host observation"
            }));
            continue;
        };
        for axis in ResourceAxisV1::ALL {
            if !reserved.supports(axis) || !capacity.supports(axis) {
                continue;
            }
            let maximum = capacity.amount(axis);
            if maximum == 0 {
                continue;
            }
            let basis_points = u128::from(reserved.amount(axis)).saturating_mul(10_000)
                / u128::from(maximum);
            if basis_points >= 9_000 {
                alerts.push(json!({
                    "severity": if basis_points >= 10_000 { "critical" } else { "warning" },
                    "code": "fleet_capacity_utilization",
                    "host_id": host_id,
                    "axis": axis.id(),
                    "basis_points": basis_points,
                    "threshold_basis_points": 9_000,
                    "action": "reduce admission or add independently observed capacity"
                }));
            }
        }
    }
    alerts
}

fn push_nonzero(
    alerts: &mut Vec<Value>,
    severity: &str,
    code: &str,
    value: u64,
    action: &str,
) {
    if value > 0 {
        alerts.push(json!({
            "severity": severity,
            "code": code,
            "value": value,
            "action": action
        }));
    }
}

struct Options {
    state_root: PathBuf,
    operation_id: Option<String>,
    fail_on_alert: bool,
}

impl Options {
    fn parse() -> Result<Self, Box<dyn std::error::Error>> {
        let mut arguments = std::env::args_os().skip(1);
        let mut state_root = None;
        let mut operation_id = None;
        let mut fail_on_alert = false;
        while let Some(argument) = arguments.next() {
            match argument.to_str() {
                Some("--state-root") if state_root.is_none() => {
                    state_root = Some(PathBuf::from(
                        arguments.next().ok_or("--state-root requires a value")?,
                    ));
                }
                Some("--operation-id") if operation_id.is_none() => {
                    operation_id = Some(
                        arguments
                            .next()
                            .ok_or("--operation-id requires a value")?
                            .into_string()
                            .map_err(|_| "--operation-id is not UTF-8")?,
                    );
                }
                Some("--fail-on-alert") => fail_on_alert = true,
                _ => {
                    return Err("usage: hepta-fleet-status --state-root ABSOLUTE_PATH [--operation-id ID] [--fail-on-alert]".into());
                }
            }
        }
        let state_root = state_root.ok_or("--state-root is required")?;
        if !state_root.is_absolute() {
            return Err("--state-root must be absolute".into());
        }
        Ok(Self {
            state_root,
            operation_id,
            fail_on_alert,
        })
    }
}
