#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]


def path(name: str) -> pathlib.Path:
    return ROOT / name


def read(name: str) -> str:
    return path(name).read_text(encoding="utf-8")


def write(name: str, value: str) -> None:
    path(name).write_text(value, encoding="utf-8")


def replace_once(name: str, old: str, new: str) -> None:
    value = read(name)
    count = value.count(old)
    if count != 1:
        raise RuntimeError(f"{name}: expected one match, found {count}: {old[:100]!r}")
    write(name, value.replace(old, new, 1))


def regex_once(name: str, pattern: str, replacement: str) -> None:
    value = read(name)
    updated, count = re.subn(pattern, replacement, value, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{name}: expected one regex match, found {count}: {pattern!r}")
    write(name, updated)


replace_once(
    "codex-rs/hepta-supervisor/src/lib.rs",
    "mod lease;\nmod matrix;",
    "mod lease;\nmod lock_metrics;\nmod matrix;",
)
replace_once(
    "codex-rs/hepta-supervisor/src/lib.rs",
    "mod process_deadline;\nmod recovery;",
    "mod process_deadline;\nmod production_caller;\nmod qualification_fault;\nmod recovery;\nmod recovery_diagnostics;",
)
replace_once(
    "codex-rs/hepta-supervisor/src/lib.rs",
    "pub use daemon::run_supervisord_with_grant_verifier;\n",
    "pub use daemon::run_supervisord_with_grant_verifier;\n"
    "#[cfg(feature = \"qualification\")]\n"
    "pub use daemon::run_supervisord_qualification;\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/lib.rs",
    "pub use model::TickReport;\n",
    "pub use model::TickReport;\n"
    "pub use lock_metrics::SupervisorLockClassSnapshot;\n"
    "pub use lock_metrics::SupervisorLockLatencySnapshot;\n"
    "pub use lock_metrics::SupervisorLockMetricsSnapshot;\n"
    "pub use production_caller::ProductionCallerRequest;\n"
    "pub use production_caller::execute_production_caller;\n"
    "pub use recovery_diagnostics::RECOVERY_DIAGNOSTIC_SCHEMA_VERSION;\n"
    "pub use recovery_diagnostics::RecoveryBlockerClass;\n"
    "pub use recovery_diagnostics::RecoveryDiagnostic;\n"
    "pub use recovery_diagnostics::RecoveryObservation;\n"
    "pub use recovery_diagnostics::RecoveryOperatorAction;\n"
    "pub use recovery_diagnostics::diagnose_supervisor_recovery;\n",
)

replace_once(
    "codex-rs/hepta-supervisor/Cargo.toml",
    '[[bin]]\nname = "hepta-authority-signer"\n',
    '[[bin]]\n'
    'name = "hepta-supervisor-production-caller"\n'
    'path = "src/bin/hepta-supervisor-production-caller.rs"\n'
    'test = false\n'
    'required-features = ["production-authority"]\n\n'
    '[[bin]]\n'
    'name = "hepta-authority-signer"\n',
)

replace_once(
    "codex-rs/hepta-supervisor/src/durable_publish.rs",
    "use std::io;\nuse std::path::Path;\n",
    "use std::fs::File;\nuse std::io;\nuse std::io::Write;\nuse std::path::Path;\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/durable_publish.rs",
    "    publish_same_directory(staging, destination)\n}\n",
    "    crate::qualification_fault::maybe_delay(\"rename\", destination)?;\n"
    "    crate::qualification_fault::maybe_fail(\"rename\", destination)?;\n"
    "    publish_same_directory(staging, destination)\n}\n\n"
    "pub(crate) fn write_all(file: &mut File, bytes: &[u8], destination: &Path) -> io::Result<()> {\n"
    "    crate::qualification_fault::maybe_delay(\"write\", destination)?;\n"
    "    crate::qualification_fault::maybe_fail(\"write\", destination)?;\n"
    "    file.write_all(bytes)\n"
    "}\n\n"
    "pub(crate) fn sync_file(file: &File, destination: &Path) -> io::Result<()> {\n"
    "    crate::qualification_fault::maybe_delay(\"file_sync\", destination)?;\n"
    "    crate::qualification_fault::maybe_fail(\"file_sync\", destination)?;\n"
    "    file.sync_all()\n"
    "}\n\n"
    "pub(crate) fn sync_directory(directory: &Path, destination: &Path) -> io::Result<()> {\n"
    "    crate::qualification_fault::maybe_delay(\"directory_sync\", destination)?;\n"
    "    crate::qualification_fault::maybe_fail(\"directory_sync\", destination)?;\n"
    "    #[cfg(unix)]\n"
    "    {\n"
    "        File::open(directory)?.sync_all()\n"
    "    }\n"
    "    #[cfg(not(unix))]\n"
    "    {\n"
    "        let _ = directory;\n"
    "        Ok(())\n"
    "    }\n"
    "}\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/durable_publish.rs",
    "    std::fs::File::open(parent)?.sync_all()\n",
    "    sync_directory(parent, destination)\n",
)

replace_once("codex-rs/hepta-supervisor/src/signed_intent.rs", "use std::io::Write;\n", "")
replace_once(
    "codex-rs/hepta-supervisor/src/signed_intent.rs",
    "    file.write_all(&bytes)?;\n    file.sync_all()?;\n",
    "    crate::durable_publish::write_all(&mut file, &bytes, &final_path)?;\n"
    "    crate::durable_publish::sync_file(&file, &final_path)?;\n",
)
write(
    "codex-rs/hepta-supervisor/src/signed_intent_publish.rs",
    "//! Shared same-directory durable publication for signed intents.\n\n"
    "use std::io;\n"
    "use std::path::Path;\n\n"
    "pub(crate) fn publish(staging: &Path, destination: &Path) -> io::Result<()> {\n"
    "    crate::durable_publish::publish(staging, destination)\n"
    "}\n",
)

replace_once("codex-rs/hepta-supervisor/src/restart_journal.rs", "use std::io::Write;\n", "")
replace_once(
    "codex-rs/hepta-supervisor/src/restart_journal.rs",
    "    file.write_all(&bytes)?;\n    file.sync_all()?;\n",
    "    crate::durable_publish::write_all(&mut file, &bytes, &final_path)?;\n"
    "    crate::durable_publish::sync_file(&file, &final_path)?;\n",
)

replace_once("codex-rs/hepta-supervisor/src/release_transaction.rs", "use std::io::Write;\n", "")
replace_once(
    "codex-rs/hepta-supervisor/src/release_transaction.rs",
    "    file.write_all(&bytes)?;\n    file.sync_all()?;\n    drop(file);\n"
    "    replace_same_directory(&temp, &final_path)?;\n    sync_directory(run_root)?;\n",
    "    crate::durable_publish::write_all(&mut file, &bytes, &final_path)?;\n"
    "    crate::durable_publish::sync_file(&file, &final_path)?;\n"
    "    drop(file);\n"
    "    crate::durable_publish::publish(&temp, &final_path)?;\n",
)
regex_once(
    "codex-rs/hepta-supervisor/src/release_transaction.rs",
    r"\nfn replace_same_directory\(.*?\nfn valid_sha256",
    "\nfn valid_sha256",
)

replace_once("codex-rs/hepta-supervisor/src/lease.rs", "use std::io::Write;\n", "")
replace_once(
    "codex-rs/hepta-supervisor/src/lease.rs",
    "    file.write_all(&bytes)?;\n    file.sync_all()?;\n"
    "    match std::fs::hard_link(&temp_path, &final_path) {",
    "    crate::durable_publish::write_all(&mut file, &bytes, &final_path)?;\n"
    "    crate::durable_publish::sync_file(&file, &final_path)?;\n"
    "    crate::qualification_fault::maybe_delay(\"link\", &final_path)?;\n"
    "    crate::qualification_fault::maybe_fail(\"link\", &final_path)?;\n"
    "    match std::fs::hard_link(&temp_path, &final_path) {",
)
replace_once(
    "codex-rs/hepta-supervisor/src/lease.rs",
    "    file.write_all(&bytes)?;\n    file.sync_all()?;\n"
    "    match std::fs::hard_link(&temp_path, path) {",
    "    crate::durable_publish::write_all(&mut file, &bytes, path)?;\n"
    "    crate::durable_publish::sync_file(&file, path)?;\n"
    "    crate::qualification_fault::maybe_delay(\"link\", path)?;\n"
    "    crate::qualification_fault::maybe_fail(\"link\", path)?;\n"
    "    match std::fs::hard_link(&temp_path, path) {",
)
replace_once(
    "codex-rs/hepta-supervisor/src/lease.rs",
    "    File::open(path)?.sync_all()?;\n",
    "    crate::durable_publish::sync_directory(path, path)?;\n",
)

replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    "#[cfg(unix)]\nuse tokio::sync::Mutex;\n",
    "",
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    "#[cfg(unix)]\nuse crate::ProcessDriver;\n",
    "#[cfg(unix)]\nuse crate::ProcessDriver;\n"
    "#[cfg(unix)]\nuse crate::lock_metrics::InstrumentedMutex;\n"
    "#[cfg(unix)]\nuse crate::lock_metrics::SupervisorLockClass;\n"
    "#[cfg(unix)]\nuse crate::lock_metrics::write_lock_metrics_snapshot;\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    "    supervisor: Mutex<Supervisor<D>>,\n",
    "    supervisor: InstrumentedMutex<Supervisor<D>>,\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    "    run_supervisord_inner(fleet_root, cancellation, None).await\n",
    "    run_supervisord_inner(fleet_root, cancellation, None, None).await\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    "    run_supervisord_inner(fleet_root, cancellation, Some(verifier)).await\n}\n",
    "    run_supervisord_inner(fleet_root, cancellation, Some(verifier), None).await\n"
    "}\n\n"
    "#[cfg(feature = \"qualification\")]\n"
    "pub async fn run_supervisord_qualification(\n"
    "    fleet_root: HeptaFleetRoot,\n"
    "    cancellation: CancellationToken,\n"
    "    verifier: Option<H7H89ProductionGrantVerifier>,\n"
    "    metrics_output: PathBuf,\n"
    ") -> Result<(), SupervisorError> {\n"
    "    if !metrics_output.is_absolute() {\n"
    "        return Err(SupervisorError::Invalid(\n"
    "            \"qualification metrics output must be absolute\".to_string(),\n"
    "        ));\n"
    "    }\n"
    "    run_supervisord_inner(fleet_root, cancellation, verifier, Some(metrics_output)).await\n"
    "}\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    "    production_grant_verifier: Option<H7H89ProductionGrantVerifier>,\n) -> Result<(), SupervisorError> {",
    "    production_grant_verifier: Option<H7H89ProductionGrantVerifier>,\n"
    "    qualification_metrics_output: Option<PathBuf>,\n"
    ") -> Result<(), SupervisorError> {",
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    "        supervisor: Mutex::new(supervisor),\n",
    "        supervisor: InstrumentedMutex::new(supervisor),\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    "                    let faults = tick_state.supervisor.lock().await.tick(Instant::now()).faults;\n",
    "                    let mut supervisor = tick_state\n"
    "                        .supervisor\n"
    "                        .lock(SupervisorLockClass::Tick)\n"
    "                        .await;\n"
    "                    let _ = crate::qualification_fault::maybe_delay(\n"
    "                        \"driver_poll\",\n"
    "                        Path::new(\"supervisor-driver\"),\n"
    "                    );\n"
    "                    let faults = supervisor.tick(Instant::now()).faults;\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    "    let result = server.run().await;\n    cancellation.cancel();\n    let _ = ticker.await;\n    result\n",
    "    let reporter = qualification_metrics_output.map(|output| {\n"
    "        let metrics_state = Arc::clone(&state);\n"
    "        let metrics_cancellation = cancellation.clone();\n"
    "        tokio::spawn(async move {\n"
    "            let mut interval = tokio::time::interval(Duration::from_millis(250));\n"
    "            interval.set_missed_tick_behavior(MissedTickBehavior::Skip);\n"
    "            loop {\n"
    "                tokio::select! {\n"
    "                    _ = metrics_cancellation.cancelled() => {\n"
    "                        let snapshot = metrics_state.supervisor.snapshot();\n"
    "                        let path = output.clone();\n"
    "                        let _ = tokio::task::spawn_blocking(move || {\n"
    "                            write_lock_metrics_snapshot(&path, &snapshot)\n"
    "                        }).await;\n"
    "                        return;\n"
    "                    }\n"
    "                    _ = interval.tick() => {\n"
    "                        let snapshot = metrics_state.supervisor.snapshot();\n"
    "                        let path = output.clone();\n"
    "                        let _ = tokio::task::spawn_blocking(move || {\n"
    "                            write_lock_metrics_snapshot(&path, &snapshot)\n"
    "                        }).await;\n"
    "                    }\n"
    "                }\n"
    "            }\n"
    "        })\n"
    "    });\n"
    "    let result = server.run().await;\n"
    "    cancellation.cancel();\n"
    "    let _ = ticker.await;\n"
    "    if let Some(reporter) = reporter {\n"
    "        let _ = reporter.await;\n"
    "    }\n"
    "    result\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    "    _production_grant_verifier: Option<H7H89ProductionGrantVerifier>,\n) -> Result<(), SupervisorError> {",
    "    _production_grant_verifier: Option<H7H89ProductionGrantVerifier>,\n"
    "    _qualification_metrics_output: Option<PathBuf>,\n"
    ") -> Result<(), SupervisorError> {",
)

daemon = read("codex-rs/hepta-supervisor/src/daemon.rs")
daemon = daemon.replace(
    "state.supervisor.lock().await",
    "state.supervisor.lock(SupervisorLockClass::Read).await",
)
daemon = daemon.replace(
    ".supervisor\n                .lock()\n                .await",
    ".supervisor\n                .lock(SupervisorLockClass::Read)\n                .await",
)
daemon = daemon.replace(
    "let mut supervisor = state.supervisor.lock(SupervisorLockClass::Read).await;",
    "let mut supervisor = state\n"
    "        .supervisor\n"
    "        .lock(SupervisorLockClass::Mutation)\n"
    "        .await;",
)
roster_old = (
    "            let supervisor = state.supervisor.lock(SupervisorLockClass::Read).await;\n"
    "            let records = match state.registry.load() {"
)
if roster_old not in daemon:
    raise RuntimeError("daemon.rs: roster lock pattern missing")
daemon = daemon.replace(
    roster_old,
    "            let supervisor = state.supervisor.lock(SupervisorLockClass::Read).await;\n"
    "            let _ = crate::qualification_fault::maybe_delay(\n"
    "                \"registry_load\",\n"
    "                Path::new(\"fleet-registry\"),\n"
    "            );\n"
    "            let records = match state.registry.load() {",
    1,
)
if "supervisor.lock().await" in daemon or "\n                .lock()\n" in daemon:
    raise RuntimeError("daemon.rs still contains an uninstrumented supervisor lock")
write("codex-rs/hepta-supervisor/src/daemon.rs", daemon)

replace_once(
    "codex-rs/hepta-supervisor/src/main.rs",
    "    match options.grant_verifier {\n",
    "    if let Some(metrics_output) = options.qualification_metrics_out {\n"
    "        #[cfg(feature = \"qualification\")]\n"
    "        {\n"
    "            codex_hepta_supervisor::run_supervisord_qualification(\n"
    "                options.fleet_root,\n"
    "                cancellation,\n"
    "                options.grant_verifier,\n"
    "                metrics_output,\n"
    "            )\n"
    "            .await?;\n"
    "            return Ok(());\n"
    "        }\n"
    "        #[cfg(not(feature = \"qualification\"))]\n"
    "        {\n"
    "            let _ = metrics_output;\n"
    "            anyhow::bail!(\"--qualification-metrics-out requires the qualification feature\");\n"
    "        }\n"
    "    }\n"
    "    match options.grant_verifier {\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/main.rs",
    "    grant_verifier: Option<codex_hepta_supervisor::H7H89ProductionGrantVerifier>,\n",
    "    grant_verifier: Option<codex_hepta_supervisor::H7H89ProductionGrantVerifier>,\n"
    "    qualification_metrics_out: Option<PathBuf>,\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/main.rs",
    "    let mut h7_signer_epoch = None;\n",
    "    let mut h7_signer_epoch = None;\n"
    "    let mut qualification_metrics_out = None;\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/main.rs",
    "            Some(\"--h7-signer-epoch\") if h7_signer_epoch.is_none() => h7_signer_epoch = Some(value),\n",
    "            Some(\"--h7-signer-epoch\") if h7_signer_epoch.is_none() => h7_signer_epoch = Some(value),\n"
    "            Some(\"--qualification-metrics-out\") if qualification_metrics_out.is_none() => {\n"
    "                qualification_metrics_out = Some(PathBuf::from(value))\n"
    "            }\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/main.rs",
    "                \"usage: hepta-supervisord --fleet-root ABSOLUTE_PATH [--grant-verifier-key ABSOLUTE_PATH --grant-signer-id ID --grant-signer-epoch N --h7-verifier-key ABSOLUTE_PATH --h7-signer-id ID --h7-signer-epoch N]\"\n",
    "                \"usage: hepta-supervisord --fleet-root ABSOLUTE_PATH [--grant-verifier-key ABSOLUTE_PATH --grant-signer-id ID --grant-signer-epoch N --h7-verifier-key ABSOLUTE_PATH --h7-signer-id ID --h7-signer-epoch N] [--qualification-metrics-out ABSOLUTE_PATH]\"\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/main.rs",
    "    Ok(Options {\n        fleet_root,\n        grant_verifier,\n    })\n",
    "    if qualification_metrics_out\n"
    "        .as_ref()\n"
    "        .is_some_and(|path| !path.is_absolute())\n"
    "    {\n"
    "        anyhow::bail!(\"qualification metrics output must be absolute\");\n"
    "    }\n"
    "    Ok(Options {\n"
    "        fleet_root,\n"
    "        grant_verifier,\n"
    "        qualification_metrics_out,\n"
    "    })\n",
)

replace_once(
    "codex-rs/hepta-supervisor/src/bin/hepta-supervisor-intent-recovery.rs",
    "use codex_hepta_supervisor::SignedIntentRecoveryDirective;\n",
    "use codex_hepta_supervisor::RecoveryObservation;\n"
    "use codex_hepta_supervisor::SignedIntentRecoveryDirective;\n"
    "use codex_hepta_supervisor::diagnose_supervisor_recovery;\n",
)
recovery_cli = read("codex-rs/hepta-supervisor/src/bin/hepta-supervisor-intent-recovery.rs")
recovery_cli = recovery_cli.replace("<inspect|abort>", "<inspect|diagnose|abort>")
needle = '        "abort" => {\n'
if recovery_cli.count(needle) != 1:
    raise RuntimeError("intent recovery CLI abort arm changed")
recovery_cli = recovery_cli.replace(
    needle,
    '        "diagnose" => {\n'
    '            let observation = args\n'
    '                .next()\n'
    '                .map(PathBuf::from)\n'
    '                .map(|path| -> Result<RecoveryObservation> {\n'
    '                    let bytes = std::fs::read(&path)\n'
    '                        .with_context(|| format!("read {}", path.display()))?;\n'
    '                    Ok(serde_json::from_slice(&bytes)\n'
    '                        .context("decode recovery observation")?)\n'
    '                })\n'
    '                .transpose()?;\n'
    '            if args.next().is_some() {\n'
    '                bail!("diagnose accepts <run-root> [observation.json]");\n'
    '            }\n'
    '            let diagnostic = diagnose_supervisor_recovery(&run_root, observation.as_ref());\n'
    '            println!("{}", serde_json::to_string_pretty(&diagnostic)?);\n'
    '        }\n'
    + needle,
    1,
)
recovery_cli = recovery_cli.replace(
    "expected inspect or abort",
    "expected inspect, diagnose, or abort",
)
write("codex-rs/hepta-supervisor/src/bin/hepta-supervisor-intent-recovery.rs", recovery_cli)

with path("docs/modules/runtime.supervisor/RECOVERY_AND_QUALIFICATION.md").open(
    "a", encoding="utf-8"
) as handle:
    handle.write(
        "\n\n## 9. Repository-controlled qualification closure\n\n"
        "The daemon now records bounded log2 lock wait/hold histograms separately for "
        "tick, read and mutation work. `--qualification-metrics-out` is available only "
        "from a build carrying the explicit `qualification` feature and atomically "
        "refreshes a JSON snapshot every 250 ms plus at orderly shutdown. This supplies "
        "the p50/p95/p99/max evidence needed to decide whether the existing global lock "
        "requires collect-effect-apply or per-Agent serialization. It does not itself "
        "justify such a refactor.\n\n"
        "The same feature compiles one-shot write, file-sync, same-directory publish, "
        "directory-sync and lease-link failpoints. Default and ordinary production "
        "builds keep those hooks inert. The target-host runner and strict receipt "
        "verifier live in `qualification/runtime-supervisor/`; the verifier requires all "
        "256-instance, crash-wave, slow-driver, slow-filesystem, concurrent-control, "
        "SIGKILL, fsync, rename, disk-full, corruption and authority-rotation cases.\n\n"
        "`hepta-supervisor-intent-recovery diagnose` classifies the current blocker as "
        "process ambiguity, release-CAS ambiguity, intent mismatch, admission-frontier "
        "drift, authority-epoch change, durability failure or awaiting an independent "
        "decision and returns the corresponding bounded operator action. Existing "
        "`inspect` and exact-digest `abort` behavior is unchanged.\n\n"
        "`hepta-supervisor-production-caller` is a named, source-composed caller for an "
        "already signed upgrade or rollback request. It cannot sign, choose a trust root, "
        "widen a grant or bypass the daemon verifier. Deployment of the caller, signer "
        "distribution/rotation and independent operational acceptance remain external "
        "evidence gates.\n"
    )

replace_once(
    "docs/modules/runtime.supervisor/TECHNICAL.md",
    "Current operating and state-format references:\n",
    "Qualification observability exposes atomic lock wait/hold snapshots for tick, read and "
    "mutation classes through the explicit `qualification` build and "
    "`--qualification-metrics-out`; default production execution has no environment-driven "
    "fault injection. `hepta-supervisor-intent-recovery diagnose` maps persisted recovery "
    "evidence to bounded operator actions. The separately built "
    "`hepta-supervisor-production-caller` forwards only already signed grants and owns no "
    "selection or signing authority.\n\nCurrent operating and state-format references:\n",
)

map_name = "docs/modules/runtime.supervisor/IMPLEMENTATION_MAP.json"
implementation_map = json.loads(read(map_name))
implementation_map["productCallerState"] = "source_composed_not_deployed"
for key in (
    "productExecutionComplete",
    "deploymentQualificationComplete",
    "independentAcceptanceComplete",
    "productionImplementation",
):
    implementation_map["claimBoundary"][key] = False
for source in (
    "codex-rs/hepta-supervisor/src/lock_metrics.rs",
    "codex-rs/hepta-supervisor/src/recovery_diagnostics.rs",
    "codex-rs/hepta-supervisor/src/production_caller.rs",
    "qualification/runtime-supervisor",
):
    if source not in implementation_map["observedSourcePaths"]:
        implementation_map["observedSourcePaths"].append(source)
implementation_map["externalEvidenceGates"] = [
    "exact deployed hepta-supervisord and hepta-supervisor-production-caller binaries, host identity and externally pinned production grant/H7 verifier configuration",
    "target-host 256-instance lock/HOL, startup, watchdog, typed Agentd drain, bounded restart and signed-recovery crash/fault/latency receipt accepted by qualification/runtime-supervisor/verify_receipt.py",
    "deployment and independent verification of the external release-policy/authority distribution feeding Fleet allow/revoke state and signer rotation",
    "independent operational acceptance of signed upgrade, rollback and recovery outcomes",
]
write(map_name, json.dumps(implementation_map, indent=2) + "\n")

workflow_name = ".github/workflows/hepta-lane-b-truth.yml"
workflow = read(workflow_name)
anchor = "          cargo test -p codex-hepta-supervisor --lib\n"
if workflow.count(anchor) != 1:
    raise RuntimeError("Lane B workflow supervisor test anchor changed")
workflow = workflow.replace(
    anchor,
    anchor
    + "          cargo test -p codex-hepta-supervisor --features qualification --lib\n"
    + "          cargo test -p codex-hepta-supervisor --features qualification --test qualification_256\n"
    + "          cargo check -p codex-hepta-supervisor --features \"qualification production-authority\" --all-targets\n"
    + "          python3 qualification/runtime-supervisor/verify_receipt.py --self-test\n",
    1,
)
write(workflow_name, workflow)
