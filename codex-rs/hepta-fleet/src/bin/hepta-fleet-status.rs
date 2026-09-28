//! Read-only operator surface for the supervisor-owned durable fleet state.

use codex_hepta_fleet::FleetOperationalMetricsV1;
use codex_hepta_fleet::ResourceAxisV1;
use codex_hepta_fleet::SystemFleetClock;
use codex_hepta_fleet::read_fleet_snapshot;
use serde_json::Value;
use serde_json::json;
use std::ffi::OsString;
use std::path::PathBuf;
use std::sync::Arc;

const USAGE: &str = "usage: hepta-fleet-status [status] --supervisor-state-root ABSOLUTE_PATH [--format json] [--operation-id ID] [--fail-on-alert]\n       --state-root and --state-dir are compatibility aliases for --supervisor-state-root\n       hepta-fleet-status --help";

fn main() {
    match run() {
        Ok(code) => std::process::exit(code),
        Err(error) => {
            eprintln!("hepta-fleet-status: {error}");
            std::process::exit(1);
        }
    }
}

fn run() -> Result<i32, Box<dyn std::error::Error>> {
    let Some(options) = Options::parse(std::env::args_os().skip(1))? else {
        println!("{USAGE}");
        return Ok(0);
    };
    // Unlike DurableFleetOwner::open_supervisor_state_root, this cannot
    // initialize, recover, chmod, compact, or advance the durable frontier.
    // It validates one coherent, already-sealed state under a shared lock.
    let snapshot = read_fleet_snapshot(&options.state_root, Arc::new(SystemFleetClock))?;
    let metrics = &snapshot.metrics;
    let state = &snapshot.state;
    let alerts = alerts(metrics, state.fleet_revocation_frontier.as_ref());
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
        "sampled_at_ms": snapshot.sampled_at_ms,
        "state_generation": state.generation,
        "state_sha256": state.content_sha256,
        "workspace_reservations_sha256": state.workspace_reservations_sha256,
        "metrics": {
            "fleet_active_grants": metrics.fleet_active_grants,
            "fleet_expired_uncollected_grants": metrics.fleet_expired_uncollected_grants,
            "fleet_revoked_uncompacted_grants": metrics.fleet_revoked_uncompacted_grants,
            "fleet_reserved_resource": metrics.fleet_reserved_resource,
            "fleet_observed_capacity": metrics.fleet_observed_capacity,
            "fleet_stale_hosts": metrics.fleet_stale_hosts,
            "fleet_grant_issue_total": unavailable_counters(),
            "fleet_grant_renew_total": unavailable_counters(),
            "fleet_grant_revoke_total": unavailable_counters(),
            "fleet_revocation_lag_ms": metrics.fleet_revocation_lag_ms,
            "fleet_registry_conflict_total": null,
            "fleet_indeterminate_commit_total": null,
            "fleet_staging_debris": metrics.fleet_staging_debris,
            "fleet_compaction_backlog": metrics.fleet_compaction_backlog
        },
        "metric_availability": {
            "durable_snapshot": "observed",
            "process_local_counters": "unavailable_from_read_only_snapshot"
        },
        "alerts": alerts,
        "operation_lookup": options.operation_id.as_ref().map(|operation_id| json!({
            "operation_id": operation_id,
            "receipt": operation,
            "retention_boundary": "bounded retained receipt window; absence is not proof of nonexecution"
        })),
        "claim_boundary": {
            "read_only": true,
            "allocation_authority": false,
            "release_authority": false
        }
    });
    println!("{}", serde_json::to_string_pretty(&output)?);
    Ok(if options.fail_on_alert && has_alerts { 2 } else { 0 })
}

fn unavailable_counters() -> Value {
    json!({
        "success": null,
        "rejected": null,
        "indeterminate": null,
        "scope": "process_local_since_supervisord_start",
        "available": false
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
    // Process-local failure counters cannot be reconstructed by reopening a
    // snapshot. Their absence is reported above, never interpreted as zero.
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
            if !reserved.supports(axis) {
                continue;
            }
            if !capacity.supports(axis) || capacity.amount(axis) == 0 {
                if reserved.amount(axis) > 0 {
                    alerts.push(json!({
                        "severity": "critical",
                        "code": "reserved_without_supported_capacity",
                        "host_id": host_id,
                        "axis": axis.id(),
                        "action": "deny new admission and restore independently observed capacity"
                    }));
                }
                continue;
            }
            let maximum = capacity.amount(axis);
            let basis_points =
                u128::from(reserved.amount(axis)).saturating_mul(10_000) / u128::from(maximum);
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

fn push_nonzero(alerts: &mut Vec<Value>, severity: &str, code: &str, value: u64, action: &str) {
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
    fn parse(
        arguments: impl IntoIterator<Item = OsString>,
    ) -> Result<Option<Self>, Box<dyn std::error::Error>> {
        let mut arguments = arguments.into_iter().peekable();
        if arguments.peek().is_some_and(|value| value == "--help" || value == "-h") {
            arguments.next();
            if arguments.next().is_some() {
                return Err(USAGE.into());
            }
            return Ok(None);
        }
        if arguments.peek().is_some_and(|value| value == "status") {
            arguments.next();
        }
        let mut state_root = None;
        let mut operation_id = None;
        let mut fail_on_alert = false;
        let mut format_seen = false;
        while let Some(argument) = arguments.next() {
            match argument.to_str() {
                Some("--supervisor-state-root" | "--state-root" | "--state-dir")
                    if state_root.is_none() =>
                {
                    state_root = Some(PathBuf::from(required_value(&mut arguments, "state root")?));
                }
                Some("--operation-id") if operation_id.is_none() => {
                    let value = required_value(&mut arguments, "operation ID")?
                        .into_string()
                        .map_err(|_| "--operation-id is not UTF-8")?;
                    if value.trim().is_empty() {
                        return Err("--operation-id must not be empty".into());
                    }
                    operation_id = Some(value);
                }
                Some("--format") if !format_seen => {
                    if required_value(&mut arguments, "format")? != "json" {
                        return Err("--format supports only json".into());
                    }
                    format_seen = true;
                }
                Some("--fail-on-alert") if !fail_on_alert => fail_on_alert = true,
                _ => return Err(USAGE.into()),
            }
        }
        let state_root = state_root.ok_or("--supervisor-state-root is required")?;
        if !state_root.is_absolute() {
            return Err("--supervisor-state-root must be absolute".into());
        }
        Ok(Some(Self {
            state_root,
            operation_id,
            fail_on_alert,
        }))
    }
}

fn required_value(
    arguments: &mut impl Iterator<Item = OsString>,
    name: &str,
) -> Result<OsString, Box<dyn std::error::Error>> {
    let value = arguments.next().ok_or_else(|| format!("missing {name}"))?;
    if value.is_empty() || value.to_string_lossy().starts_with('-') {
        return Err(format!("missing {name}; a flag is not a value").into());
    }
    Ok(value)
}
