//! Diagnostic workload, not a production SLA. Runs only in fresh private temp
//! directories with fixture keys. No provider calls or production enrollment.
use std::error::Error;
use std::time::Instant;

use codex_hepta_authbus::AuthBusAuthorityHost;
use codex_hepta_authbus::IssuerPurpose;
use codex_hepta_authbus::IssuerSpec;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;

#[cfg(unix)]
#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    use std::os::unix::fs::PermissionsExt;
    let count = std::env::args()
        .nth(1)
        .map(|value| value.parse::<usize>())
        .transpose()?
        .unwrap_or(64);
    if !(1..=256).contains(&count) {
        return Err("sample count must be 1..=256".into());
    }
    let database_root = tempfile::tempdir()?;
    let checkpoint_root = tempfile::tempdir()?;
    for root in [&database_root, &checkpoint_root] {
        std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700))?;
    }
    let database = database_root
        .path()
        .canonicalize()?
        .join("authority.sqlite");
    let checkpoint = checkpoint_root
        .path()
        .canonicalize()?
        .join("checkpoint.json");
    let started = Instant::now();
    let host =
        AuthBusAuthorityHost::bootstrap(&database, checkpoint.clone(), "latency-fixture").await?;
    let bootstrap_micros = started.elapsed().as_micros();
    let key = SigningKey::from_bytes(&[61; 32]);
    let mut samples = Vec::with_capacity(count);
    for index in 0..count {
        let started = Instant::now();
        host.enroll_issuer(
            IssuerPurpose::Message,
            IssuerSpec {
                issuer_id: StableId::new(format!("issuer:latency-{index}"))?,
                key_epoch: Generation::new(1)?,
                verifying_key: key.verifying_key(),
            },
        )
        .await?;
        samples.push(started.elapsed().as_micros());
    }
    samples.sort_unstable();
    let quantile =
        |percent: usize| samples[(samples.len() * percent).div_ceil(100).saturating_sub(1)];
    let diagnostics = host.owner_diagnostics();
    host.close().await?;
    let started = Instant::now();
    let reopened = AuthBusAuthorityHost::open(&database, checkpoint, "latency-fixture").await?;
    let reopen_micros = started.elapsed().as_micros();
    reopened.close().await?;
    let mut state_bytes = 0_u64;
    for root in [&database_root, &checkpoint_root] {
        for entry in std::fs::read_dir(root.path())? {
            state_bytes += entry?.metadata()?.len();
        }
    }
    println!(
        "{}",
        serde_json::json!({
            "schema": "hepta.authbus.owner-latency.v1", "diagnostic_only": true,
            "samples": samples.len(), "bootstrap_micros": bootstrap_micros,
            "reopen_micros": reopen_micros, "enroll_full_operation_micros": {
                "p50": quantile(50), "p95": quantile(95), "p99": quantile(99)
            }, "retained_state_bytes": state_bytes, "owner_diagnostics": diagnostics
        })
    );
    Ok(())
}

#[cfg(not(unix))]
fn main() -> Result<(), Box<dyn Error>> {
    Err("persistent AuthBus ownership is unsupported on this platform".into())
}
